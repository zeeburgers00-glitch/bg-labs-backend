"""
BG LABS - Complete AI Platform Backend
======================================

FastAPI entrypoint. Runs unchanged on:

* Vercel serverless functions (``vercel.json`` builds this file)
* Render / Railway / Fly (``python main.py``)
* Docker (see ``Dockerfile``)
* local development (``uvicorn main:app --reload``)

Everything persistent goes through :mod:`app.store`, which picks Supabase
(PostgREST + Storage), plain PostgreSQL (asyncpg) or an in-memory fallback
depending on the environment variables it finds.

Free engines used by the API:

* TTS      -> Edge-TTS (Microsoft neural voices, no key)
* Images   -> Pollinations.ai (no key)
* Avatars  -> generated SVG (no external service)
* Scripts  -> built-in template engine (:mod:`app.script_engine`)
"""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

try:  # local development convenience
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - python-dotenv is optional at runtime
    pass

from app.deps import (
    RATE_LIMIT_AUTH,
    RATE_LIMIT_GENERATE,
    RATE_LIMIT_IMAGE,
    check_rate_limit,
    create_token,
    get_client_ip,
    get_current_user,
    hash_password,
    needs_rehash,
    public_user,
    verify_password,
)
from app.engines import (
    IMAGE_STYLES,
    avatar_preset,
    generate_avatar_svg,
    generate_image,
    guess_content_type,
    image_extension,
    parse_size,
)
from app.media import STORAGE_DIR, ensure_dirs, read_local, save_media
from app.script_engine import generate_script
from app.store import DuplicateError, StoreError, get_store
from tts_engine import (
    EDGE_VOICES,
    cvoice_get_voices,
    cvoice_search_characters,
    edge_tts_generate,
    get_edge_voices,
    pitch_to_offset,
    resolve_voice_key,
    speed_to_rate,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("bglabs")

BASE_DIR = Path(__file__).resolve().parent
APP_VERSION = os.getenv("APP_VERSION", "10.0.0")

# Optional SQLAlchemy based routers (YouTube agent, workflow engine, MCP, ...).
# They need the full dependency set (``requirements-full.txt``) *and* the
# SQLAlchemy schema, so they are opt-in and never break the serverless build.
OPTIONAL_ROUTERS = (
    "app.routes.youtube_agent",
    "app.routes.video_generation",
    "app.routes.video_editing",
    "app.routes.agent_skills",
    "app.routes.tts_providers",
    "app.routes.llm_providers",
    "app.routes.vector_memory",
    "app.routes.browser_automation",
    "app.routes.workflow",
    "app.routes.mcp",
)

ensure_dirs()


# ============================================================
# APP + LIFECYCLE
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm the store once so the first request is fast (local/container runs)."""
    try:
        store = await get_store()
        logger.info("store ready: %s", store.status())
    except Exception as exc:  # pragma: no cover - the store never raises by design
        logger.error("store warm-up failed: %s", exc)
    yield


app = FastAPI(
    title="BG LABS API",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# The web UI contract (index.html) - always mounted.
from app.routes.frontend_api import router as frontend_router  # noqa: E402
from app.routes.agents_api import router as agents_router  # noqa: E402
from app.routes.youtube_connect import router as youtube_router  # noqa: E402
from app.routes.skills_api import router as skills_router  # noqa: E402
from app.routes.generation_api import router as generation_router  # noqa: E402
from app.routes.vimax_api import router as vimax_router
from app.routes.assistant_hub import router as assistant_hub_router  # noqa: E402
from app.routes.course_ai import router as course_ai_router  # noqa: E402
from app.routes.avatar_api import router as avatar_api_router  # noqa: E402
from app.routes.shorts_api import router as shorts_api_router  # noqa: E402

app.include_router(frontend_router)
app.include_router(agents_router)
app.include_router(youtube_router)
app.include_router(skills_router)
app.include_router(generation_router)
app.include_router(vimax_router)
app.include_router(assistant_hub_router)
app.include_router(course_ai_router)
app.include_router(avatar_api_router)
app.include_router(shorts_api_router)

loaded_optional_routers: List[str] = []
if os.getenv("ENABLE_EXTRA_ROUTERS", "").lower() in ("1", "true", "yes"):
    for module_name in OPTIONAL_ROUTERS:
        try:
            module = importlib.import_module(module_name)
            app.include_router(module.router)
            loaded_optional_routers.append(module_name)
        except Exception as exc:
            logger.warning("optional router %s skipped: %s", module_name, exc)


# ============================================================
# ROOT / HEALTH
# ============================================================
@app.get("/", include_in_schema=False)
async def root():
    """Serve the bundled web UI when it is available (local/container runs)."""
    html_path = BASE_DIR / "index.html"
    if html_path.is_file():
        return FileResponse(str(html_path), media_type="text/html")
    return {
        "name": "BG LABS API",
        "version": APP_VERSION,
        "status": "running",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health() -> Dict[str, Any]:
    store = await get_store()
    return {
        "status": "healthy",
        "version": APP_VERSION,
        "store": store.status(),
        "persistent": store.name in ("supabase", "postgres"),
        "extra_routers": loaded_optional_routers,
        "voices": len(EDGE_VOICES),
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/keep-alive", include_in_schema=False)
async def keep_alive() -> Dict[str, Any]:
    """Cheap endpoint for uptime pingers (cron-job.org, Render keep-alive...)."""
    return {"ok": True, "version": APP_VERSION, "time": datetime.now(timezone.utc).isoformat()}


# ============================================================
# AUTH
# ============================================================
async def _register_or_409(store: Any, *, email: str, username: str, full_name: str,
                           password: str, referred_by: Optional[int] = None) -> Dict[str, Any]:
    email = (email or "").strip().lower()
    username = (username or "").strip()
    if not email or not username or not password:
        raise HTTPException(400, "email, username and password are required")
    if len(password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    # The very first account becomes the admin so the owner can use the panel.
    role = "user"
    try:
        if await store.count_users() == 0:
            role = "admin"
    except StoreError:
        pass

    user = await store.create_user(
        email=email, username=username, full_name=(full_name or "").strip(),
        password_hash=hash_password(password), role=role,
        referral_code=uuid.uuid4().hex[:8].upper(), referred_by=referred_by,
    )
    return user


@app.post("/api/auth/register")
async def register(request: Request, email: str = Form(...), username: str = Form(...),
                   full_name: str = Form(""), password: str = Form(...),
                   referral_code: str = Form("")) -> Dict[str, Any]:
    ip = get_client_ip(request)
    if not check_rate_limit(ip, "auth", RATE_LIMIT_AUTH, 60):
        raise HTTPException(429, "Too many attempts. Please wait a minute.")

    store = await get_store()
    referred_by = None
    code = (referral_code or request.query_params.get("ref") or "").strip()
    if code:
        referrer = await store.get_user_by_referral(code)
        referred_by = referrer["id"] if referrer else None

    try:
        user = await _register_or_409(
            store, email=email, username=username, full_name=full_name,
            password=password, referred_by=referred_by,
        )
    except DuplicateError as exc:
        raise HTTPException(400, str(exc)) from None
    except StoreError as exc:
        logger.error("registration failed: %s", exc)
        raise HTTPException(503, f"Registration unavailable: {exc}") from None

    if referred_by:
        try:
            referrer = await store.get_user(referred_by)
            if referrer:
                await store.update_user(referrer["id"], credits=int(referrer.get("credits", 0)) + 50)
        except StoreError:
            pass

    return {
        "access_token": create_token(user["id"], user["role"]),
        "token_type": "bearer",
        "user": public_user(user),
        "store": store.name,
    }


@app.post("/api/auth/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)) -> Dict[str, Any]:
    ip = get_client_ip(request)
    if not check_rate_limit(ip, "auth", RATE_LIMIT_AUTH, 60):
        raise HTTPException(429, "Too many attempts. Please wait a minute.")

    store = await get_store()
    try:
        user = await store.get_user_by_login(username)
    except StoreError as exc:
        logger.error("login failed: %s", exc)
        raise HTTPException(503, f"Login unavailable: {exc}") from None

    if not user:
        raise HTTPException(401, "User not found")
    if not verify_password(password, user.get("password_hash", "")):
        raise HTTPException(401, "Incorrect password")
    if not user.get("is_active", True):
        raise HTTPException(403, "Account blocked")

    if needs_rehash(user.get("password_hash", "")):
        try:  # silently upgrade legacy sha256 hashes
            await store.update_user(user["id"], password_hash=hash_password(password))
        except StoreError:
            pass

    return {
        "access_token": create_token(user["id"], user["role"]),
        "token_type": "bearer",
        "user": public_user(user),
        "store": store.name,
    }


@app.get("/api/auth/me")
async def get_me(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    return public_user(user)


@app.put("/api/auth/me")
async def update_me(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    body = await request.json()
    fields: Dict[str, Any] = {}
    if "full_name" in body:
        fields["full_name"] = str(body["full_name"])[:255]
    if "email" in body:
        fields["email"] = str(body["email"]).strip().lower()
    if body.get("password"):
        fields["password_hash"] = hash_password(str(body["password"]))
    if not fields:
        return public_user(user)

    store = await get_store()
    try:
        updated = await store.update_user(user["id"], **fields)
    except DuplicateError as exc:
        raise HTTPException(400, str(exc)) from None
    if not updated:
        raise HTTPException(500, "Could not update the profile")
    return public_user(updated)


# ============================================================
# VOICES
# ============================================================
@app.get("/api/voices")
async def list_voices() -> Dict[str, Any]:
    return {"voices": get_edge_voices(), "total": len(EDGE_VOICES), "engine": "Edge-TTS"}


@app.get("/api/voices/languages")
async def list_languages() -> Dict[str, Any]:
    languages: Dict[str, Dict[str, Any]] = {}
    for key, info in EDGE_VOICES.items():
        lang = info.get("lang", "en")
        entry = languages.setdefault(lang, {"code": lang, "name": info.get("accent", lang), "voices": []})
        entry["voices"].append(key)
    return {"languages": list(languages.values()), "total": len(languages)}


@app.get("/api/voices/characters")
async def search_characters(q: str = Query(""), limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    try:
        characters = await cvoice_search_characters(q, limit)
        return {"characters": characters, "total": len(characters)}
    except Exception as exc:  # upstream service is optional
        return {"characters": [], "total": 0, "error": str(exc)}


@app.get("/api/voices/characters/{username}")
async def get_character_voices(username: str) -> Dict[str, Any]:
    try:
        voices = await cvoice_get_voices(username)
        return {"username": username, "voices": voices, "total": len(voices)}
    except Exception as exc:
        return {"username": username, "voices": [], "total": 0, "error": str(exc)}


# ============================================================
# TTS STUDIO
# ============================================================
@app.post("/api/studio/generate")
async def generate_audio(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    ip = get_client_ip(request)
    if not check_rate_limit(ip, "generate", RATE_LIMIT_GENERATE, 60):
        raise HTTPException(429, "Too many requests. Please wait a moment.")

    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Text is required")
    if len(text) > 10000:
        raise HTTPException(400, "Text too long (max 10,000 characters)")

    # A custom voice profile id/key maps onto its Edge-TTS base voice.
    voice_input = body.get("voice_key") or body.get("voice") or body.get("voice_id") or ""
    store = await get_store()
    if str(voice_input).isdigit():
        try:
            profile = await store.get_voice(int(voice_input), user["id"])
            if profile:
                voice_input = profile.get("base_voice") or voice_input
        except StoreError:
            pass

    voice_key = resolve_voice_key(voice_input, body.get("language"))
    rate = speed_to_rate(body.get("speed"), body.get("rate"))
    pitch = pitch_to_offset(body.get("pitch"))

    try:
        audio_bytes = await edge_tts_generate(text, voice_key, rate=rate, pitch=pitch)
    except Exception as exc:
        logger.error("TTS failed: %s", exc)
        raise HTTPException(502, f"TTS failed: {exc}") from None

    filename = f"{uuid.uuid4().hex}.mp3"
    saved = await save_media(store, "audio", filename, audio_bytes, "audio/mpeg")
    voice_info = EDGE_VOICES.get(voice_key, {})

    # durable object storage -> keep the URL; otherwise keep the inline audio so
    # the history list stays playable after the container is recycled.
    history_data = None if saved.get("stored") == "storage" else saved.get("data_uri")
    history_url = saved["url"]
    try:
        await store.add_audio(
            user_id=user["id"], text=text[:500], voice=voice_info.get("name", voice_key),
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
        "engine": "Edge-TTS",
        "voice": voice_info.get("name", voice_key),
        "voice_key": voice_key,
        "rate": rate,
        "pitch": pitch,
        "chars": len(text),
        "stored": saved.get("stored"),
    }


@app.get("/api/studio/audio")
async def list_audio(request: Request) -> List[Dict[str, Any]]:
    user = await get_current_user(request)
    store = await get_store()
    try:
        return await store.list_audio(user["id"], limit=50)
    except StoreError as exc:
        logger.warning("audio history unavailable: %s", exc)
        return []


@app.get("/api/studio/audio/download/{filename}")
async def download_audio(filename: str) -> Response:
    data = read_local("audio", filename)
    if not data:
        raise HTTPException(404, "Audio file not found (serverless storage is ephemeral)")
    return Response(content=data, media_type="audio/mpeg",
                    headers={"Content-Disposition": f'attachment; filename="bglabs_{filename}"'})


@app.get("/api/storage/{kind}/{filename}")
async def serve_storage(kind: str, filename: str) -> Response:
    """Serve locally generated media (Supabase Storage URLs are used when available)."""
    if kind not in ("audio", "images", "videos", "avatars", "voices"):
        raise HTTPException(404, "Unknown storage kind")
    data = read_local(kind, filename)
    if not data:
        raise HTTPException(404, "File not found on this instance")
    media_types = {
        "audio": "audio/mpeg", "images": guess_content_type(data), "videos": "video/mp4",
        "avatars": "image/svg+xml", "voices": "audio/mpeg",
    }
    return Response(content=data, media_type=media_types.get(kind, "application/octet-stream"))


# ============================================================
# IMAGE GENERATION
# ============================================================
@app.post("/api/image/generate")
async def image_generate(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    ip = get_client_ip(request)
    if not check_rate_limit(ip, "image", RATE_LIMIT_IMAGE, 60):
        raise HTTPException(429, "Too many image requests. Please wait.")

    body = await request.json()
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "Prompt is required")

    style = body.get("style") or "realistic"
    model = body.get("model") or ""
    width, height = parse_size(body.get("size"), body.get("width"), body.get("height"))
    count = max(1, min(2, int(body.get("n") or 1)))
    store = await get_store()

    results = await asyncio.gather(
        *[generate_image(prompt, style, width, height, model, seed=None) for _ in range(count)],
        return_exceptions=True,
    )
    images: List[Dict[str, Any]] = []
    errors: List[str] = []
    for item in results:
        if isinstance(item, Exception):
            errors.append(str(item))
            continue
        content_type = guess_content_type(item)
        filename = f"{uuid.uuid4().hex}{image_extension(content_type)}"
        saved = await save_media(store, "images", filename, item, content_type)
        durable = saved.get("stored") == "storage"
        try:
            await store.add_image(
                user_id=user["id"], prompt=prompt[:1000], style=style, filename=filename,
                url=saved["url"], model=model,
                size=f"{width}x{height}", data_uri=None if durable else saved.get("data_uri"),
            )
        except StoreError as exc:
            logger.warning("image history not saved: %s", exc)
        images.append({
            "url": saved["url"],
            "data_uri": saved.get("data_uri"),
            "filename": filename,
            "stored": saved.get("stored"),
        })

    if not images:
        raise HTTPException(502, f"Image generation failed: {errors[0] if errors else 'unknown error'}")

    first = images[0]
    return {
        "url": first["url"],
        "data_uri": first["data_uri"],
        "filename": first["filename"],
        "prompt": prompt,
        "style": style,
        "model": model,
        "size": f"{width}x{height}",
        "images": images,
        "result": {"image_url": first["url"], "revised_prompt": prompt},
        "stored": first["stored"],
        "errors": errors,
    }


@app.get("/api/image/styles")
async def list_image_styles() -> Dict[str, Any]:
    seen: Dict[str, Dict[str, Any]] = {}
    icons = {
        "realistic": "📷", "vivid": "🌈", "anime": "🎌", "oil_painting": "🎨", "digital_art": "💻",
        "watercolor": "🖌️", "3d_render": "🧊", "pixel_art": "👾", "cyberpunk": "🌃", "cinematic": "🎬",
        "portrait": "👤", "landscape": "🌄", "fantasy": "🧙", "minimalist": "⬜", "comic": "💥",
        "photorealistic": "📸", "sketch": "✏️",
    }
    for key, prompt_suffix in IMAGE_STYLES.items():
        canonical = key.replace("-", "_")
        if canonical in seen:
            continue
        seen[canonical] = {
            "id": canonical, "name": canonical.replace("_", " ").title(),
            "icon": icons.get(canonical, "🎨"), "desc": prompt_suffix,
        }
    return {"styles": list(seen.values()), "total": len(seen)}


@app.get("/api/image/history")
async def image_history(request: Request) -> List[Dict[str, Any]]:
    user = await get_current_user(request)
    store = await get_store()
    try:
        return await store.list_images(user["id"], limit=50)
    except StoreError as exc:
        logger.warning("image history unavailable: %s", exc)
        return []


# ============================================================
# AVATAR STUDIO
# ============================================================
@app.post("/api/avatar/generate")
async def avatar_generate(request: Request) -> Dict[str, Any]:
    await get_current_user(request)
    body = await request.json()
    preset = avatar_preset(body.get("avatar_type", "default"), body.get("background"))
    colours = {
        "hair_color": body.get("hair_color") or preset["hair_color"],
        "eye_color": body.get("eye_color") or preset["eye_color"],
        "skin_tone": body.get("skin_tone") or preset["skin_tone"],
        "clothing_color": body.get("clothing_color") or preset["clothing_color"],
    }
    svg = generate_avatar_svg(background=preset.get("background", "studio"), **colours)

    store = await get_store()
    filename = f"{uuid.uuid4().hex}.svg"
    saved = await save_media(store, "avatars", filename, svg.encode("utf-8"), "image/svg+xml")
    return {
        "url": saved["url"],
        "data_uri": saved.get("data_uri") or f"data:image/svg+xml;utf8,{svg}",
        "filename": filename,
        "svg": svg,
        "avatar_type": body.get("avatar_type", "default"),
        "background": preset.get("background"),
        "stored": saved.get("stored"),
    }


# ============================================================
# VOICE PROFILES (legacy /api/voice-clone/* contract)
# ============================================================
@app.post("/api/voice-clone/create")
async def create_voice_clone(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    body = await request.json()
    name = (body.get("name") or "My Voice").strip()
    base_voice = resolve_voice_key(body.get("base_voice"), body.get("language"))
    store = await get_store()
    try:
        voice = await store.add_voice(
            user_id=user["id"], name=name, description=body.get("description", ""),
            voice_key=f"custom-{uuid.uuid4().hex[:10]}", base_voice=base_voice,
            sample_url=body.get("sample_url"),
            settings={"base_voice": base_voice, "name": name, **{k: v for k, v in body.items() if k in ("rate", "pitch", "style")}},
        )
    except StoreError as exc:
        logger.warning("voice profile not saved: %s", exc)
        return {"id": 0, "name": name, "base_voice": base_voice, "persisted": False}
    return {"id": voice["id"], "name": name, "base_voice": base_voice, "voice_key": voice["voice_key"], "persisted": True}


@app.get("/api/voice-clone/list")
async def list_voice_clones(request: Request) -> List[Dict[str, Any]]:
    user = await get_current_user(request)
    store = await get_store()
    try:
        return await store.list_voices(user["id"])
    except StoreError as exc:
        logger.warning("voice profiles unavailable: %s", exc)
        return []


@app.post("/api/voice-clone/generate")
async def generate_with_clone(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    body = await request.json()
    text = (body.get("text") or "").strip()
    profile_id = body.get("profile_id") or body.get("voice_id")
    if not text:
        raise HTTPException(400, "Text is required")

    store = await get_store()
    profile = None
    if profile_id:
        try:
            profile = await store.get_voice(int(profile_id), user["id"])
        except (StoreError, ValueError, TypeError):
            profile = None
    if not profile:
        raise HTTPException(404, "Voice profile not found")

    voice_key = resolve_voice_key(profile.get("base_voice"))
    try:
        audio_bytes = await edge_tts_generate(text, voice_key,
                                              rate=speed_to_rate(body.get("speed"), body.get("rate")))
    except Exception as exc:
        raise HTTPException(502, f"Voice generation failed: {exc}") from None

    filename = f"{uuid.uuid4().hex}.mp3"
    saved = await save_media(store, "audio", filename, audio_bytes, "audio/mpeg")
    try:
        await store.add_audio(
            user_id=user["id"], text=text[:500], voice=profile["name"], engine="Edge-TTS (profile)",
            filename=filename, url=saved["url"], chars=len(text),
            data_uri=None if saved.get("stored") == "storage" else saved.get("data_uri"),
        )
        await store.add_usage(user["id"], len(text))
    except StoreError:
        pass
    return {
        "url": saved["url"], "data_uri": saved.get("data_uri"), "filename": filename,
        "profile_name": profile["name"], "voice_key": voice_key, "chars": len(text),
    }


# ============================================================
# SCRIPT WRITER (legacy endpoint)
# ============================================================
@app.post("/api/script/write")
async def write_script(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    body = await request.json()
    topic = (body.get("topic") or "").strip()
    if not topic:
        raise HTTPException(400, "Topic is required")

    try:
        result = generate_script(
            topic,
            template=body.get("genre") or body.get("template") or "general",
            style=body.get("style", ""),
            tone=body.get("mood") or body.get("tone") or "neutral",
            length=body.get("length") or "medium",
            audience=body.get("audience") or "general",
            language=body.get("language") or "english",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None

    store = await get_store()
    project_id = None
    try:
        project = await store.add_project(
            user_id=user["id"], name=topic[:80], project_type="script",
            settings={
                "topic": topic, "template": result["template"], "genre": result["genre"],
                "tone": result["tone"], "length": result["length"],
                "script_content": result["script"], "word_count": result["word_count"],
            },
        )
        project_id = project["id"]
    except StoreError as exc:
        logger.warning("script not saved: %s", exc)

    payload = dict(result)
    payload["project_id"] = project_id
    return payload


# ============================================================
# REFERRAL (legacy alias)
# ============================================================
@app.get("/api/referral/code")
async def get_referral_code(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    code = user.get("referral_code") or "UNKNOWN"
    base = str(request.base_url).rstrip("/")
    return {"referral_code": code, "referral_link": f"{base}/?ref={code}"}


# ============================================================
# LOCAL SERVER ENTRYPOINT
# ============================================================
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "7860"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=os.getenv("RELOAD", "") == "1")
