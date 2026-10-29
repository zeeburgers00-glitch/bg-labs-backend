"""AI Shorts Maker API, powered by Vizard's official long-video clipping API.

The browser never receives the provider API key. Each submitted provider project
is recorded against the authenticated BG LABS user, and polling verifies ownership.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.deps import RATE_LIMIT_GENERATE, check_rate_limit, get_client_ip, get_current_user
from app.store import StoreError, get_store

router = APIRouter(prefix="/api/shorts", tags=["AI Shorts Maker"])
logger = logging.getLogger("bglabs.shorts")

VIZARD_API_KEY = (os.getenv("VIZARDAI_API_KEY") or os.getenv("VIZARD_API_KEY") or "").strip()
VIZARD_BASE = "https://elb-api.vizard.ai/hvizard-server-front/open-api/v1"
PROJECT_TYPE = "shorts_project"
MAX_CLIPS_LIMIT = 20
MAX_KEYWORDS = 240
MAX_PROJECT_NAME = 100

SOURCE_TYPES = {
    "remote": 1, "youtube": 2, "gdrive": 3, "vimeo": 4, "streamyard": 5,
    "tiktok": 6, "twitter": 7, "twitch": 9, "loom": 10, "facebook": 11,
    "linkedin": 12, "dropbox": 13, "instagram": 14,
}
SOURCE_HINTS = (
    (("youtube.com", "youtu.be", "youtube-nocookie.com"), "youtube"),
    (("drive.google.com", "docs.google.com"), "gdrive"),
    (("vimeo.com",), "vimeo"),
    (("streamyard.com",), "streamyard"),
    (("tiktok.com",), "tiktok"),
    (("twitter.com", "x.com", "t.co"), "twitter"),
    (("twitch.tv",), "twitch"),
    (("loom.com",), "loom"),
    (("facebook.com", "fb.watch"), "facebook"),
    (("linkedin.com",), "linkedin"),
    (("dropbox.com", "dropboxusercontent.com"), "dropbox"),
    (("instagram.com",), "instagram"),
)
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".3gp"}


def _provider_headers():
    if not VIZARD_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI Shorts cloud engine is not configured. Add VIZARDAI_API_KEY in Vercel Environment Variables.",
        )
    return {"VIZARDAI_API_KEY": VIZARD_API_KEY, "Accept": "application/json"}


def _source_from_url(video_url: str, requested: str) -> tuple[str, int, str]:
    parsed = urlparse(video_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(400, "Use a public HTTPS video URL. Do not include usernames, passwords, or private links.")

    host = parsed.hostname.lower().rstrip(".")
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise HTTPException(400, "Private/internal IP addresses are not allowed as video sources.")
    except ValueError:
        if host in {"localhost", "metadata.google.internal"} or host.endswith((".localhost", ".local", ".internal")):
            raise HTTPException(400, "Local/internal addresses are not allowed as video sources.")

    source = (requested or "auto").lower().strip()
    if source in ("", "auto"):
        source = "remote"
        for suffixes, candidate in SOURCE_HINTS:
            if any(host == suffix or host.endswith("." + suffix) for suffix in suffixes):
                source = candidate
                break
    if source not in SOURCE_TYPES:
        raise HTTPException(400, "Choose a supported source: YouTube, Google Drive, Vimeo, Twitch, TikTok, social link, or direct video URL.")

    if source != "remote":
        accepted = next((suffixes for suffixes, candidate in SOURCE_HINTS if candidate == source), ())
        if not any(host == suffix or host.endswith("." + suffix) for suffix in accepted):
            raise HTTPException(400, f"The URL does not look like a supported {source} link.")

    path = parsed.path.lower()
    extension = next((ext for ext in VIDEO_EXTENSIONS if path.endswith(ext)), "")
    if source == "remote" and not extension:
        raise HTTPException(400, "Direct video URLs must end in .mp4, .mov, .avi or .3gp. Alternatively, paste a YouTube or public Drive link.")
    if source == "remote" and extension == ".3gp":
        ext = "3gp"
    elif source == "remote":
        ext = extension.lstrip(".")
    else:
        ext = ""
    return source, SOURCE_TYPES[source], ext


async def _vizard(method: str, path: str, payload: dict | None = None) -> dict:
    headers = _provider_headers()
    url = VIZARD_BASE + path
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(75.0, connect=15.0), follow_redirects=False) as client:
            if method == "GET":
                response = await client.get(url, headers=headers)
            else:
                response = await client.post(url, headers={**headers, "Content-Type": "application/json"}, json=payload or {})
    except httpx.TimeoutException:
        raise HTTPException(504, "Vizard API timed out. Check the project status before submitting again.") from None
    except httpx.HTTPError as exc:
        logger.warning("Vizard transport error: %s", type(exc).__name__)
        raise HTTPException(502, "Could not reach the Vizard API. Please retry shortly.") from None
    try:
        data = response.json()
    except ValueError:
        data = {"errMsg": response.text[:300]}
    if response.is_error:
        msg = data.get("errMsg") or data.get("message") or f"Vizard returned HTTP {response.status_code}"
        code = data.get("code")
        if code == 4001 or response.status_code == 401:
            raise HTTPException(502, "Vizard rejected the API key. Check VIZARDAI_API_KEY.")
        if code == 4007:
            raise HTTPException(402, "Vizard minutes are exhausted. Check your Vizard plan.")
        raise HTTPException(502, f"Vizard API error: {str(msg)[:400]}")
    if not isinstance(data, dict):
        raise HTTPException(502, "Vizard returned an unexpected response.")
    return data


def _provider_error(data: dict) -> str | None:
    try:
        code = int(data.get("code", 0))
    except (TypeError, ValueError):
        code = 0
    if code in (0, 2000, 1000):
        return None
    messages = {
        4001: "Vizard rejected the API key.",
        4002: "Vizard could not create this project.",
        4003: "Vizard rate limit reached.",
        4004: "The source video format is not supported.",
        4005: "The source video may be broken or too long for this operation.",
        4006: "Vizard rejected one or more settings.",
        4007: "There are not enough Vizard minutes remaining.",
        4008: "Vizard could not download the supplied video URL.",
        4009: "The video URL is invalid.",
        4010: "Spoken language detection failed. Choose the video's language instead of Auto.",
    }
    return messages.get(code, str(data.get("errMsg") or f"Vizard returned code {code}")[:400])


def _normalize_videos(data: dict) -> list[dict]:
    results = []
    for video in data.get("videos") or []:
        if not isinstance(video, dict):
            continue
        url = str(video.get("videoUrl") or "")
        # Only return external HTTPS links; never render provider-supplied script URLs.
        if urlparse(url).scheme != "https":
            url = ""
        editor_url = str(video.get("clipEditorUrl") or "")
        if urlparse(editor_url).scheme != "https":
            editor_url = ""
        try:
            duration = round(float(video.get("videoMsDuration") or 0) / 1000, 1)
        except (TypeError, ValueError):
            duration = 0
        try:
            score = max(0, min(10, float(video.get("viralScore") or 0)))
        except (TypeError, ValueError):
            score = 0
        results.append({
            "video_id": video.get("videoId"),
            "video_url": url,
            "duration_seconds": duration,
            "title": str(video.get("title") or "AI clip")[:240],
            "transcript": str(video.get("transcript") or "")[:12000],
            "viral_score": score,
            "viral_reason": str(video.get("viralReason") or "")[:1200],
            "related_topics": str(video.get("relatedTopic") or "")[:1200],
            "editor_url": editor_url,
            "starred": bool(video.get("starred")),
            "disliked": bool(video.get("disliked")),
        })
    return results


@router.get("/status")
async def shorts_status():
    return {
        "configured": bool(VIZARD_API_KEY),
        "provider": "Vizard AI",
        "mode": "cloud_ai_clipping",
        "supports": [
            "automatic_highlight_clipping", "viral_score_and_reason", "9:16_vertical",
            "1:1_square", "4:5_portrait", "16:9_landscape", "auto_subtitles",
            "keyword_highlights", "emoji_captions", "headline_hooks", "auto_broll",
            "remove_silence_and_fillers", "20_to_180_second_clip_preferences",
        ],
        "requires_paid_plan": True,
        "setup_url": "https://docs.vizard.ai/docs/quickstart",
        "message": "Ready" if VIZARD_API_KEY else "Add VIZARDAI_API_KEY to Vercel to enable the cloud clipping API.",
    }


@router.post("/create")
async def create_shorts_project(request: Request):
    user = await get_current_user(request)
    if not check_rate_limit(get_client_ip(request), "shorts-create", max(3, RATE_LIMIT_GENERATE // 4), 60):
        raise HTTPException(429, "Too many Shorts projects started at once. Wait a moment.")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Expected a JSON body.") from None
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected a JSON object.")

    video_url = str(body.get("video_url") or "").strip()
    if not video_url or len(video_url) > 3000:
        raise HTTPException(400, "Paste a video link first.")
    source, video_type, ext = _source_from_url(video_url, str(body.get("source_type") or "auto"))

    lang = str(body.get("language") or "auto").strip().lower()[:24]
    if not re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})*", lang) and lang != "auto":
        raise HTTPException(400, "Language should be 'auto' or a language code such as en, ur, hi, or es.")
    try:
        max_clips = max(1, min(MAX_CLIPS_LIMIT, int(body.get("max_clips") or 10)))
    except (TypeError, ValueError):
        raise HTTPException(400, "Number of clips must be a number from 1 to 20.") from None
    try:
        prefer_length = max(0, min(4, int(body.get("preferred_length") or 2)))
    except (TypeError, ValueError):
        raise HTTPException(400, "Select a supported clip length.") from None
    ratio_map = {"9:16": 1, "1:1": 2, "4:5": 3, "16:9": 4}
    ratio = str(body.get("aspect_ratio") or "9:16")
    if ratio not in ratio_map:
        raise HTTPException(400, "Aspect ratio must be 9:16, 1:1, 4:5 or 16:9.")
    keywords = str(body.get("keywords") or "").strip()[:MAX_KEYWORDS]
    project_name = str(body.get("project_name") or "AI Shorts Project").strip()[:MAX_PROJECT_NAME] or "AI Shorts Project"
    clip_model = str(body.get("clip_model") or "clip_v1")
    if clip_model not in ("clip_v1", "clip_v2"):
        raise HTTPException(400, "Unsupported clipping model.")

    payload = {
        "lang": lang,
        "preferLength": [prefer_length],
        "videoUrl": video_url,
        "videoType": video_type,
        "ratioOfClip": ratio_map[ratio],
        "maxClipNumber": max_clips,
        "subtitleSwitch": int(bool(body.get("subtitles", True))),
        "emojiSwitch": int(bool(body.get("emojis", False))),
        "highlightSwitch": int(bool(body.get("highlight_keywords", True))),
        "autoBrollSwitch": int(bool(body.get("auto_broll", False))),
        "headlineSwitch": int(bool(body.get("headlines", True))),
        "removeSilenceSwitch": int(bool(body.get("remove_silence", True))),
        "clipModel": clip_model,
        "projectName": project_name,
    }
    if keywords:
        payload["keywords"] = keywords
    if ext:
        payload["ext"] = ext
    if body.get("template_id"):
        try:
            payload["templateId"] = int(body["template_id"])
        except (TypeError, ValueError):
            raise HTTPException(400, "Template ID must be numeric.") from None

    response = await _vizard("POST", "/project/create", payload)
    error = _provider_error(response)
    if error:
        raise HTTPException(502, error)
    vizard_id = response.get("projectId")
    if not vizard_id:
        raise HTTPException(502, "Vizard accepted the request but returned no project ID. Check your Vizard dashboard.")
    project = None
    store = await get_store()
    try:
        project = await store.add_project(
            user_id=user["id"],
            name=project_name,
            project_type=PROJECT_TYPE,
            settings={
                "engine": "vizard",
                "vizard_project_id": str(vizard_id),
                "source_type": source,
                "source_url": video_url,
                "status": "processing",
                "request": {
                    "language": lang, "max_clips": max_clips, "preferred_length": prefer_length,
                    "aspect_ratio": ratio, "subtitles": bool(body.get("subtitles", True)),
                    "emojis": bool(body.get("emojis", False)),
                    "highlight_keywords": bool(body.get("highlight_keywords", True)),
                    "auto_broll": bool(body.get("auto_broll", False)),
                    "headlines": bool(body.get("headlines", True)),
                    "remove_silence": bool(body.get("remove_silence", True)),
                    "keywords": keywords, "clip_model": clip_model, "template_id": payload.get("templateId"),
                },
                "share_link": response.get("shareLink"),
                "clips": [],
            },
        )
    except StoreError:
        logger.exception("Could not persist Shorts project for user %s", user.get("id"))
        raise HTTPException(500, "Vizard started the project, but BG LABS could not save it. Check your Vizard dashboard before retrying.")
    return {
        "project_id": project["id"],
        "provider_project_id": str(vizard_id),
        "status": "processing",
        "source_type": source,
        "share_link": response.get("shareLink"),
        "message": "The source was submitted. Use Refresh results to check for generated clips.",
    }


@router.get("/projects")
async def list_shorts_projects(request: Request, limit: int = 20):
    user = await get_current_user(request)
    store = await get_store()
    rows = await store.list_projects(user["id"], project_type=PROJECT_TYPE, limit=max(1, min(50, limit)))
    projects = []
    for row in rows:
        settings = row.get("settings") or {}
        projects.append({
            "id": row["id"],
            "name": row.get("name"),
            "status": settings.get("status", "processing"),
            "source_type": settings.get("source_type"),
            "created_at": row.get("created_at"),
            "clip_count": len(settings.get("clips") or []),
            "share_link": settings.get("share_link"),
        })
    return {"projects": projects, "count": len(projects)}


@router.get("/projects/{project_id}")
async def get_shorts_project(project_id: int, request: Request):
    user = await get_current_user(request)
    store = await get_store()
    row = await store.get_project(project_id, user["id"])
    if not row or row.get("project_type") != PROJECT_TYPE:
        raise HTTPException(404, "Shorts project not found.")
    settings = row.get("settings") or {}
    provider_id = str(settings.get("vizard_project_id") or "")
    if not provider_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", provider_id):
        raise HTTPException(500, "This Shorts project has no valid Vizard project ID.")
    response = await _vizard("GET", f"/project/query/{provider_id}")
    error = _provider_error(response)
    if error:
        settings.update({"status": "failed", "last_error": error})
        await store.update_project(project_id, user["id"], settings=settings)
        raise HTTPException(502, error)
    try:
        code = int(response.get("code") or 0)
    except (TypeError, ValueError):
        code = 0
    clips = _normalize_videos(response)
    state = "ready" if code == 2000 and clips else ("processing" if code == 1000 or not clips else "processing")
    settings.update({
        "status": state,
        "clips": clips,
        "share_link": response.get("shareLink") or settings.get("share_link"),
        "project_name": response.get("projectName") or row.get("name"),
        "last_checked_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    })
    await store.update_project(project_id, user["id"], settings=settings)
    return {
        "project_id": project_id,
        "provider_project_id": provider_id,
        "name": row.get("name"),
        "status": state,
        "message": "Clips are ready." if state == "ready" else "Vizard is still processing this video. Check again in about 30 seconds.",
        "clips": clips,
        "share_link": settings.get("share_link"),
        "source_type": settings.get("source_type"),
        "request": settings.get("request") or {},
    }
