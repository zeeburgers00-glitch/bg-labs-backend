"""
BG LABS - Web UI API
====================

Every endpoint the bundled frontend (``index.html``) calls, implemented on top of
the pluggable store (:mod:`app.store`) so the same code runs against Supabase,
plain PostgreSQL or the in-memory fallback.

Route conventions kept identical to the UI:

* ``GET  /api/voices/builtin``      -> ``{voices: [...], languages: [...]}``
* ``GET  /api/voices/custom``       -> ``[...]``
* ``GET  /api/image/my-images``     -> ``[{name, settings: {images: [...]}}]``
* ``GET  /api/script/projects``     -> ``[{id, name, settings: {...}}]``
* ``POST /api/youtube/full-automation`` -> script + voiceover + thumbnail
"""
from __future__ import annotations

import logging
import os
import platform
import sys
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from app.deps import (
    RATE_LIMIT_GENERATE,
    RATE_LIMIT_IMAGE,
    check_rate_limit,
    get_client_ip,
    get_current_user,
    public_user,
    require_admin,
)
from app.engines import (
    avatar_preset,
    generate_avatar_svg,
    generate_image,
    guess_content_type,
    image_extension,
    parse_size,
)
from app.media import save_media
from app.script_engine import generate_script
from app.store import DuplicateError, StoreError, get_store
from tts_engine import (
    EDGE_VOICES,
    edge_tts_generate,
    get_edge_voices,
    resolve_voice_key,
    speed_to_rate,
    voices_for_language,
)

logger = logging.getLogger("bglabs.ui")

router = APIRouter(tags=["BG LABS Web UI"])

APP_VERSION = os.getenv("APP_VERSION", "10.0.0")


# ============================================================================
# helpers
# ============================================================================
def _abs_url(request: Request, path: str) -> str:
    base = str(request.base_url).rstrip("/")
    if path.startswith("http://") or path.startswith("https://") or path.startswith("data:"):
        return path
    return f"{base}{path}"


async def _generate_voiceover(store: Any, user: Dict[str, Any], text: str, voice_key: str,
                              rate: str = "+0%") -> Dict[str, Any]:
    """Run Edge-TTS, persist the audio and record it in history."""
    resolved = resolve_voice_key(voice_key)
    audio_bytes = await edge_tts_generate(text, resolved, rate=rate)
    filename = f"{uuid.uuid4().hex}.mp3"
    saved = await save_media(store, "audio", filename, audio_bytes, "audio/mpeg")
    voice_info = EDGE_VOICES.get(resolved, {})
    history_url, history_data = saved["url"], saved.get("data_uri")
    if saved.get("stored") != "storage" and history_data is None:
        history_url, history_data = saved["url"], None
    try:
        await store.add_audio(
            user_id=user["id"], text=text[:500], voice=voice_info.get("name", resolved),
            engine="Edge-TTS", filename=filename, url=history_url, chars=len(text),
            data_uri=history_data,
        )
        await store.add_usage(user["id"], len(text))
    except StoreError as exc:
        logger.warning("audio history not saved: %s", exc)
    return {
        "url": saved["url"],
        "data_uri": saved.get("data_uri"),
        "filename": filename,
        "voice_key": resolved,
        "voice": voice_info.get("name", resolved),
        "engine": "Edge-TTS",
        "chars": len(text),
        "stored": saved.get("stored"),
    }


# ============================================================================
# SYSTEM / DASHBOARD
# ============================================================================
@router.get("/api/system/status")
async def system_status() -> Dict[str, Any]:
    """Deployment health - handy to confirm which storage backend is live."""
    store = await get_store()
    status = store.status() if hasattr(store, "status") else {"backend": "unknown"}
    return {
        "name": "BG LABS API",
        "version": APP_VERSION,
        "status": "running",
        "store": status,
        "persistent": status.get("backend") in ("supabase", "postgres"),
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.system(),
            "vercel": bool(os.getenv("VERCEL")),
            "region": os.getenv("VERCEL_REGION"),
        },
        "engines": {
            "tts": "Edge-TTS (Microsoft, free)",
            "images": "Pollinations.ai (free, keyless)",
            "avatars": "generated SVG",
            "scripts": "built-in template engine",
        },
        "voices": len(EDGE_VOICES),
        "docs": "/docs",
    }


@router.get("/api/dashboard/stats")
async def dashboard_stats(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    audio = await store.list_audio(user["id"], limit=5)
    images = await store.list_images(user["id"], limit=5)
    projects = await store.list_projects(user["id"], limit=200)

    recent: List[Dict[str, Any]] = []
    for item in audio:
        recent.append({
            "type": "audio", "icon": "fa-file-audio", "title": item["text_content"][:70] or "Audio",
            "meta": f'{item["voice"]} • {item["chars"]} chars', "created_at": item["created_at"],
        })
    for item in images:
        recent.append({
            "type": "image", "icon": "fa-image", "title": item["prompt"][:70] or "Image",
            "meta": f'{item["style"] or "image"} • {item["size"] or ""}'.strip(), "created_at": item["created_at"],
        })
    for item in projects:
        recent.append({
            "type": item["project_type"], "icon": "fa-folder", "title": item["name"][:70],
            "meta": item["project_type"], "created_at": item["created_at"],
        })
    recent.sort(key=lambda r: r.get("created_at") or "", reverse=True)

    return {
        "credits": user.get("credits", 0),
        "projects": len(projects),
        "audio": await store.count_audio(user["id"]),
        "images": await store.count_images(user["id"]),
        "subscription_tier": "free",
        "total_used": user.get("total_used", 0),
        "recent": recent[:8],
        "user": public_user(user),
    }


# ============================================================================
# VOICES
# ============================================================================
@router.get("/api/voices/builtin")
async def builtin_voices(language: Optional[str] = Query(None), gender: Optional[str] = Query(None)) -> Dict[str, Any]:
    voices: List[Dict[str, Any]] = []
    for voice in get_edge_voices():
        item = {
            "id": voice["key"],
            "key": voice["key"],
            "voice_key": voice["key"],
            "name": voice["name"],
            "label": f'{voice["name"]} ({voice["accent"]})',
            "language": voice["lang"],
            "lang": voice["lang"],
            "accent": voice["accent"],
            "gender": str(voice["gender"]).lower(),
            "engine": "Edge-TTS",
            "color": voice.get("color"),
        }
        if language and voice["lang"].lower() != language.lower():
            continue
        if gender and item["gender"] != gender.lower():
            continue
        voices.append(item)

    languages: Dict[str, Dict[str, Any]] = {}
    for voice in voices:
        entry = languages.setdefault(voice["lang"], {"code": voice["lang"], "name": voice["lang"].upper(), "voices": []})
        entry["voices"].append(voice["key"])

    return {
        "voices": voices,
        "total": len(voices),
        "engine": "Edge-TTS",
        "languages": list(languages.values()),
    }


@router.get("/api/voices/custom")
async def custom_voices(request: Request) -> List[Dict[str, Any]]:
    user = await get_current_user(request)
    store = await get_store()
    voices = await store.list_voices(user["id"])
    return [
        {
            "id": v["id"],
            "name": v["name"],
            "description": v["description"],
            "voice_key": v["voice_key"],
            "base_voice": v["base_voice"],
            "sample_url": v["sample_url"],
            "settings": v["settings"],
            "created_at": v["created_at"],
        }
        for v in voices
    ]


@router.post("/api/voices/clone")
async def clone_voice(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    base_voice: str = Form(""),
    audio_file: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    """Create a personal voice profile from an uploaded sample.

    Edge-TTS cannot clone a voice from audio (that needs a paid model), so the
    sample is stored and the profile maps onto the closest Edge voice. The UI
    then treats it like any other voice.
    """
    user = await get_current_user(request)
    ip = get_client_ip(request)
    if not check_rate_limit(ip, "clone", 10, 60):
        raise HTTPException(429, "Too many requests. Please wait a moment.")

    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "Voice name is required")

    store = await get_store()
    sample_url = None
    sample_bytes = 0
    if audio_file is not None and audio_file.filename:
        data = await audio_file.read()
        sample_bytes = len(data)
        if data:
            content_type = audio_file.content_type or guess_content_type(data, "audio/mpeg")
            ext = ".wav" if "wav" in content_type else ".mp3"
            saved = await save_media(store, "voices", f"{uuid.uuid4().hex}{ext}", data, content_type, inline=False)
            sample_url = saved["url"]

    resolved_base = resolve_voice_key(base_voice) if base_voice else "en-US-AriaNeural"
    voice_key = f"custom-{uuid.uuid4().hex[:10]}"
    try:
        voice = await store.add_voice(
            user_id=user["id"], name=name, description=(description or "").strip(),
            voice_key=voice_key, base_voice=resolved_base, sample_url=sample_url,
            settings={"source": "upload", "sample_bytes": sample_bytes, "cloned": False},
        )
    except DuplicateError as exc:
        raise HTTPException(400, str(exc)) from None
    except StoreError as exc:
        logger.error("voice profile failed: %s", exc)
        raise HTTPException(503, f"Could not save the voice profile: {exc}") from None

    return {
        "id": voice["id"],
        "name": voice["name"],
        "voice_key": voice_key,
        "base_voice": resolved_base,
        "sample_url": sample_url,
        "cloned": False,
        "message": "Profile created. Edge-TTS renders it with the closest Microsoft neural voice.",
    }


@router.delete("/api/voices/{key}")
async def delete_voice(request: Request, key: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    deleted = await store.delete_voice(key, user["id"])
    if not deleted:
        raise HTTPException(404, "Voice not found")
    return {"ok": True, "deleted": key}


# ============================================================================
# STUDIO EXTRAS
# ============================================================================
@router.delete("/api/studio/audio/{audio_id}")
async def delete_audio(request: Request, audio_id: int) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    deleted = await store.delete_audio(audio_id, user["id"])
    if not deleted:
        raise HTTPException(404, "Audio file not found")
    return {"ok": True, "deleted": audio_id}


# ============================================================================
# IMAGES
# ============================================================================
@router.get("/api/image/my-images")
async def my_images(request: Request) -> List[Dict[str, Any]]:
    user = await get_current_user(request)
    store = await get_store()
    images = await store.list_images(user["id"], limit=60)
    if not images:
        return []
    return [{
        "id": 0,
        "name": "My Gallery",
        "project_type": "image",
        "settings": {
            "images": [
                {
                    "id": img["id"],
                    "url": img["url"] or img["data_uri"],
                    "data_uri": img["data_uri"],
                    "prompt": img["prompt"],
                    "style": img["style"],
                    "model": img["model"],
                    "size": img["size"],
                    "created_at": img["created_at"],
                }
                for img in images
            ]
        },
        "created_at": images[0]["created_at"],
    }]


@router.post("/api/image/save")
async def save_image(request: Request) -> Dict[str, Any]:
    """Add an already generated image (or an external URL) to the gallery."""
    user = await get_current_user(request)
    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    image_url = (body.get("image_url") or body.get("url") or "").strip()
    if not image_url:
        raise HTTPException(400, "image_url is required")

    data_uri = image_url if image_url.startswith("data:") else None
    stored_url = "" if data_uri else image_url.replace(str(request.base_url).rstrip("/"), "")

    store = await get_store()
    try:
        row = await store.add_image(
            user_id=user["id"], prompt=prompt[:1000] or "Saved image",
            style=body.get("style", ""), filename=os.path.basename(stored_url.split("?")[0]) or "",
            url=stored_url, model=body.get("model", ""), size=body.get("size", ""),
            data_uri=data_uri,
        )
    except StoreError as exc:
        raise HTTPException(503, f"Could not save image: {exc}") from None
    return {"ok": True, "id": (row or {}).get("id"), "url": stored_url or data_uri}


@router.delete("/api/image/{image_id}")
async def delete_image(request: Request, image_id: int) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    deleted = await store.delete_image(image_id, user["id"])
    if not deleted:
        raise HTTPException(404, "Image not found")
    return {"ok": True, "deleted": image_id}


# ============================================================================
# SCRIPT WRITER
# ============================================================================
@router.post("/api/script/generate")
async def script_generate(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    ip = get_client_ip(request)
    if not check_rate_limit(ip, "script", RATE_LIMIT_GENERATE, 60):
        raise HTTPException(429, "Too many requests. Please wait a moment.")

    body = await request.json()
    topic = (body.get("topic") or "").strip()
    if not topic:
        raise HTTPException(400, "Topic is required")

    try:
        result = generate_script(
            topic,
            template=body.get("template") or body.get("genre") or "general",
            style=body.get("style", ""),
            tone=body.get("tone") or body.get("style") or "neutral",
            length=body.get("target_length") or body.get("length") or "medium",
            audience=body.get("target_audience") or "general",
            language=body.get("language") or "english",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None

    store = await get_store()
    project = None
    try:
        project = await store.add_project(
            user_id=user["id"],
            name=topic[:80],
            project_type="script",
            settings={
                "topic": topic,
                "template": result["template"],
                "genre": result["genre"],
                "style": result["style"],
                "tone": result["tone"],
                "length": result["length"],
                "language": result["language"],
                "target_audience": result["target_audience"],
                "script_content": result["script"],
                "word_count": result["word_count"],
            },
        )
    except StoreError as exc:
        logger.warning("script project not saved: %s", exc)

    payload = dict(result)
    payload["project_id"] = (project or {}).get("id")
    return payload


@router.get("/api/script/projects")
async def script_projects(request: Request) -> List[Dict[str, Any]]:
    user = await get_current_user(request)
    store = await get_store()
    return await store.list_projects(user["id"], project_type="script", limit=100)


@router.get("/api/script/projects/{project_id}")
async def script_project(request: Request, project_id: int) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    project = await store.get_project(project_id, user["id"])
    if not project:
        raise HTTPException(404, "Script project not found")
    return project


@router.post("/api/script/projects/{project_id}")
async def script_project_update(request: Request, project_id: int) -> Dict[str, Any]:
    user = await get_current_user(request)
    body = await request.json()
    store = await get_store()
    project = await store.get_project(project_id, user["id"])
    if not project:
        raise HTTPException(404, "Script project not found")

    settings = dict(project.get("settings") or {})
    if "script_content" in body:
        settings["script_content"] = body["script_content"]
        settings["word_count"] = len(str(body["script_content"]).split())
    for key in ("name", "topic", "template", "style", "tone", "length"):
        if key in body and key != "name":
            settings[key] = body[key]

    updated = await store.update_project(
        project_id, user["id"], name=body.get("name"), settings=settings
    )
    if not updated:
        raise HTTPException(500, "Could not update the script")
    return updated


@router.delete("/api/script/projects/{project_id}")
async def script_project_delete(request: Request, project_id: int) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    if not await store.delete_project(project_id, user["id"]):
        raise HTTPException(404, "Script project not found")
    return {"ok": True, "deleted": project_id}


@router.get("/api/script/projects/{project_id}/export")
async def script_project_export(request: Request, project_id: int, format: str = Query("txt")) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    project = await store.get_project(project_id, user["id"])
    if not project:
        raise HTTPException(404, "Script project not found")

    settings = project.get("settings") or {}
    script = settings.get("script_content", "")
    fmt = (format or "txt").lower()
    slug = "".join(c if c.isalnum() else "-" for c in project["name"].lower()).strip("-")[:40] or "script"

    if fmt == "json":
        content = str({
            "name": project["name"],
            "topic": settings.get("topic"),
            "template": settings.get("template"),
            "word_count": settings.get("word_count"),
            "script": script,
            "created_at": project.get("created_at"),
        })
        filename = f"{slug}.json"
    elif fmt in ("md", "markdown"):
        content = (
            f"# {project['name']}\n\n"
            f"- Topic: {settings.get('topic', '-')}\n"
            f"- Template: {settings.get('template', '-')}\n"
            f"- Words: {settings.get('word_count', len(script.split()))}\n\n"
            f"---\n\n{script}\n"
        )
        filename = f"{slug}.md"
    else:
        content = f"{project['name']}\n{'=' * len(project['name'])}\n\n{script}\n"
        filename = f"{slug}.txt"

    return {"content": content, "filename": filename, "format": fmt, "project_id": project_id}


# ============================================================================
# AVATAR STUDIO
# ============================================================================
@router.post("/api/avatar/create")
async def avatar_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    avatar_type: str = Form("default"),
    background: Optional[str] = Form(None),
    hair_color: Optional[str] = Form(None),
    eye_color: Optional[str] = Form(None),
    skin_tone: Optional[str] = Form(None),
    clothing_color: Optional[str] = Form(None),
) -> Dict[str, Any]:
    user = await get_current_user(request)
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "Project name is required")

    preset = avatar_preset(avatar_type or "default", background)
    colours = {
        "hair_color": hair_color or preset["hair_color"],
        "eye_color": eye_color or preset["eye_color"],
        "skin_tone": skin_tone or preset["skin_tone"],
        "clothing_color": clothing_color or preset["clothing_color"],
    }
    svg = generate_avatar_svg(background=preset.get("background", "studio"), **colours)

    store = await get_store()
    filename = f"{uuid.uuid4().hex}.svg"
    saved = await save_media(store, "avatars", filename, svg.encode("utf-8"), "image/svg+xml", inline=False)

    try:
        project = await store.add_project(
            user_id=user["id"], name=name[:120], project_type="avatar",
            settings={
                "description": (description or "").strip(),
                "avatar_type": avatar_type or "default",
                "background": preset.get("background", "studio"),
                "avatar_url": saved["url"],
                "avatar_svg": svg,
                "filename": filename,
                **colours,
            },
        )
    except StoreError as exc:
        raise HTTPException(503, f"Could not create the avatar project: {exc}") from None

    return {
        "id": project["id"],
        "name": project["name"],
        "avatar_url": saved["url"],
        "url": saved["url"],
        "svg": svg,
        "avatar_type": avatar_type,
        "background": preset.get("background"),
        "settings": project["settings"],
    }


@router.get("/api/avatar/projects")
async def avatar_projects(request: Request) -> List[Dict[str, Any]]:
    user = await get_current_user(request)
    store = await get_store()
    return await store.list_projects(user["id"], project_type="avatar", limit=100)


@router.delete("/api/avatar/projects/{project_id}")
async def avatar_project_delete(request: Request, project_id: int) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    if not await store.delete_project(project_id, user["id"]):
        raise HTTPException(404, "Avatar project not found")
    return {"ok": True, "deleted": project_id}


# ============================================================================
# YOUTUBE AUTOMATION
# ============================================================================
@router.post("/api/youtube/full-automation")
async def youtube_full_automation(request: Request) -> Dict[str, Any]:
    """Script + voiceover (+ thumbnail) in one call - the full free pipeline."""
    user = await get_current_user(request)
    ip = get_client_ip(request)
    if not check_rate_limit(ip, "youtube", 5, 300):
        raise HTTPException(429, "Too many automation runs. Please wait a few minutes.")

    body = await request.json()
    topic = (body.get("topic") or "").strip()
    if not topic:
        raise HTTPException(400, "Topic is required")

    style = body.get("style") or "youtube"
    length = body.get("length") or "medium"
    include_thumbnail = bool(body.get("include_thumbnail", True))
    store = await get_store()

    try:
        script = generate_script(topic, template=style, length=length,
                                 tone=body.get("tone", "energetic"), audience=body.get("target_audience", "general"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None

    steps: List[Dict[str, Any]] = [{"step": "script", "status": "done", "words": script["word_count"]}]

    audio: Dict[str, Any] = {}
    try:
        audio = await _generate_voiceover(store, user, script["script"][:4000], body.get("voice_key", "aria"))
        steps.append({"step": "voiceover", "status": "done", "voice": audio["voice"]})
    except Exception as exc:
        logger.warning("voiceover failed: %s", exc)
        steps.append({"step": "voiceover", "status": "failed", "error": str(exc)})

    thumbnail: Dict[str, Any] = {}
    if include_thumbnail:
        try:
            width, height = 1280, 720
            image_bytes = await generate_image(
                f"YouTube video thumbnail about {topic}, bold title space, eye catching",
                style="cinematic", width=width, height=height, model="dall-e-3",
            )
            content_type = guess_content_type(image_bytes)
            filename = f"{uuid.uuid4().hex}{image_extension(content_type)}"
            saved = await save_media(store, "images", filename, image_bytes, content_type)
            thumbnail = {"url": saved["url"], "data_uri": saved.get("data_uri"), "filename": filename}
            try:
                await store.add_image(
                    user_id=user["id"], prompt=f"YouTube thumbnail: {topic}", style="cinematic",
                    filename=filename, url=saved["url"] if saved.get("stored") == "storage" else "",
                    model="dall-e-3", size=f"{width}x{height}",
                    data_uri=None if saved.get("stored") == "storage" else saved.get("data_uri"),
                )
            except StoreError:
                pass
            steps.append({"step": "thumbnail", "status": "done"})
        except Exception as exc:
            logger.warning("thumbnail failed: %s", exc)
            steps.append({"step": "thumbnail", "status": "failed", "error": str(exc)})

    settings = {
        "topic": topic,
        "style": style,
        "length": length,
        "script": script["script"],
        "word_count": script["word_count"],
        "voice": audio.get("voice"),
        "voice_key": audio.get("voice_key"),
        "audio_url": audio.get("url"),
        "audio_data_uri": audio.get("data_uri"),
        "thumbnail_url": thumbnail.get("url"),
        "thumbnail_data_uri": thumbnail.get("data_uri"),
        "steps": steps,
        "status": "completed" if audio else "partial",
    }
    try:
        project = await store.add_project(
            user_id=user["id"], name=topic[:80], project_type="youtube", settings=settings
        )
    except StoreError as exc:
        raise HTTPException(503, f"Could not save the project: {exc}") from None

    return {
        "project_id": project["id"],
        "status": settings["status"],
        "topic": topic,
        "script": script["script"],
        "word_count": script["word_count"],
        "audio_url": audio.get("url"),
        "audio_data_uri": audio.get("data_uri"),
        "thumbnail_url": thumbnail.get("url"),
        "thumbnail_data_uri": thumbnail.get("data_uri"),
        "steps": steps,
        "estimated_seconds": script["estimated_seconds"],
    }


@router.get("/api/youtube/projects")
async def youtube_projects(request: Request) -> List[Dict[str, Any]]:
    user = await get_current_user(request)
    store = await get_store()
    return await store.list_projects(user["id"], project_type="youtube", limit=100)


@router.get("/api/youtube/projects/{project_id}")
async def youtube_project(request: Request, project_id: int) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    project = await store.get_project(project_id, user["id"])
    if not project or project["project_type"] != "youtube":
        raise HTTPException(404, "YouTube project not found")
    return project


# ============================================================================
# BILLING
# ============================================================================
PLANS: Dict[str, Dict[str, Any]] = {
    "free": {
        "name": "Free", "monthly_price": 0, "credits": 999999,
        "features": ["Unlimited Edge-TTS audio", "AI image generation", "Script writer", "64 neural voices"],
    },
    "pro": {
        "name": "Pro", "monthly_price": 9, "credits": 50000,
        "features": ["Everything in Free", "Priority generation queue", "Voice profiles & samples", "YouTube automation"],
    },
    "studio": {
        "name": "Studio", "monthly_price": 29, "credits": 250000,
        "features": ["Everything in Pro", "Avatar studio projects", "Bulk exports", "Team seats (3)"],
    },
    "agency": {
        "name": "Agency", "monthly_price": 99, "credits": 2000000,
        "features": ["Everything in Studio", "Unlimited team seats", "API access", "Priority support"],
    },
}


@router.get("/api/billing/plans")
async def billing_plans() -> Dict[str, Any]:
    return {"plans": PLANS, "currency": "USD", "provider": "stripe (not connected)"}


@router.get("/api/billing/current")
async def billing_current(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    return {
        "tier": "free",
        "plan": PLANS["free"]["name"],
        "credits": user.get("credits", 0),
        "status": "active",
        "total_used": user.get("total_used", 0),
        "renews_at": None,
    }


# ============================================================================
# REFERRALS
# ============================================================================
CREDITS_PER_REFERRAL = 50


@router.get("/api/referral/my-code")
async def referral_my_code(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    code = user.get("referral_code") or "UNKNOWN"
    return {
        "referral_code": code,
        "referral_link": f"{_abs_url(request, '/')}?ref={code}",
        "reward_per_referral": CREDITS_PER_REFERRAL,
    }


@router.get("/api/referral/stats")
async def referral_stats(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    try:
        referrals = await store.list_referrals(user["id"])
    except StoreError:
        referrals = []
    active = [r for r in referrals if r.get("is_active")]
    generated = sum(int(r.get("total_used", 0)) for r in referrals)
    return {
        "total_referrals": len(referrals),
        "active_referrals": len(active),
        "credits_earned": len(referrals) * CREDITS_PER_REFERRAL,
        "total_credits_generated": generated,
        "pending_payout": 0,
        "reward_per_referral": CREDITS_PER_REFERRAL,
    }


@router.get("/api/referral/my-referrals")
async def referral_list(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    try:
        referrals = await store.list_referrals(user["id"])
    except StoreError:
        referrals = []
    return {
        "referrals": [
            {
                "id": r["id"],
                "username": r["username"],
                "email": r["email"],
                "credits_used": r.get("total_used", 0),
                "joined_at": r.get("created_at"),
                "is_active": r.get("is_active", True),
            }
            for r in referrals
        ],
        "total": len(referrals),
    }


@router.post("/api/referral/apply")
async def referral_apply(request: Request) -> Dict[str, Any]:
    """Attach the current account to a referral code (``/?ref=CODE``)."""
    user = await get_current_user(request)
    body = await request.json()
    code = (body.get("code") or body.get("referral_code") or "").strip()
    if not code:
        raise HTTPException(400, "Referral code is required")
    if user.get("referred_by"):
        return {"ok": False, "detail": "A referral code is already applied to this account"}

    store = await get_store()
    referrer = await store.get_user_by_referral(code)
    if not referrer:
        raise HTTPException(404, "Unknown referral code")
    if referrer["id"] == user["id"]:
        raise HTTPException(400, "You cannot refer yourself")

    await store.update_user(user["id"], referred_by=referrer["id"],
                            credits=int(user.get("credits", 0)) + CREDITS_PER_REFERRAL)
    await store.update_user(referrer["id"], credits=int(referrer.get("credits", 0)) + CREDITS_PER_REFERRAL)
    return {"ok": True, "referral_code": code, "credits_added": CREDITS_PER_REFERRAL}


# ============================================================================
# ADMIN
# ============================================================================
@router.get("/api/admin/stats")
async def admin_stats(request: Request) -> Dict[str, Any]:
    await require_admin(request)
    store = await get_store()
    try:
        return {
            "total_users": await store.count_users(),
            "active_users": await store.count_users(active_only=True),
            "total_projects": await store.count_projects(),
            "total_audio_generated": await store.count_audio(),
            "total_images": await store.count_images(),
            "total_voices": len(EDGE_VOICES),
            "custom_voices": await store.count_voices(),
            "store": store.status(),
        }
    except StoreError as exc:
        raise HTTPException(503, f"Stats unavailable: {exc}") from None


@router.get("/api/admin/users")
async def admin_users(request: Request) -> List[Dict[str, Any]]:
    await require_admin(request)
    store = await get_store()
    users = await store.list_users(limit=500)
    referrals = [u for u in users if u.get("referred_by")]
    counts: Dict[int, int] = {}
    for user in referrals:
        counts[int(user["referred_by"])] = counts.get(int(user["referred_by"]), 0) + 1
    return [
        {
            **public_user(user),
            "total_used": user.get("total_used", 0),
            "referrals_count": counts.get(int(user["id"]), 0),
        }
        for user in users
    ]


@router.put("/api/admin/users/{user_id}")
async def admin_update_user(request: Request, user_id: int) -> Dict[str, Any]:
    await require_admin(request)
    body = await request.json()
    fields: Dict[str, Any] = {}
    if "role" in body:
        if body["role"] not in ("user", "admin", "creator"):
            raise HTTPException(400, "Invalid role")
        fields["role"] = body["role"]
    if "is_active" in body:
        fields["is_active"] = bool(body["is_active"])
    if "credits" in body:
        fields["credits"] = int(body["credits"])
    if "full_name" in body:
        fields["full_name"] = str(body["full_name"])[:255]
    if not fields:
        raise HTTPException(400, "Nothing to update")

    store = await get_store()
    updated = await store.update_user(user_id, **fields)
    if not updated:
        raise HTTPException(404, "User not found")
    return public_user(updated)


__all__ = ["router", "PLANS"]
