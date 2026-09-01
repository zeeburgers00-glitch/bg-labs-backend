"""AI Video Studio API routes.

Full CRUD + pipeline control endpoints for AI projects.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query

from core import require_user, require_admin, APIError, get_pool, load_settings, get_setting_int, log_admin_action
from ai_studio_service import (
    DURATIONS, LANGUAGES, TONES, WPM_BY_LANGUAGE,
    calculate_word_count, calculate_section_count, estimate_generation_time,
    start_script_generation, start_audio_generation, check_audio_completion,
    resume_project, get_project_status_detail,
)
from llm_provider import llm_status

logger = logging.getLogger("bglabs.ai_routes")
router = APIRouter(prefix="/api/ai-projects", tags=["ai-studio"])


def _row_to_project(r: dict, include_script: bool = True) -> dict:
    script = r.get("script")
    if isinstance(script, str):
        try:
            script = json.loads(script)
        except Exception:
            script = {}
    elif script is None:
        script = {}

    sections = script.get("sections", []) if isinstance(script, dict) else []

    return {
        "id": r["id"],
        "user_id": r["user_id"],
        "title": r["title"],
        "language": r["language"],
        "target_duration": r["target_duration"],
        "actual_duration": r.get("actual_duration") or 0,
        "voice_id": r.get("voice_id"),
        "voice_key": r.get("voice_key") or "",
        "voice_name": r.get("voice_name") or "",
        "engine": r.get("engine") or "edge-tts",
        "tone": r.get("tone") or "documentary",
        "mode": r.get("mode") or "auto",
        "research_enabled": bool(r.get("research_enabled")),
        "status": r["status"],
        "script_status": r.get("script_status") or "pending",
        "audio_status": r.get("audio_status") or "pending",
        "estimated_words": r.get("estimated_words") or 0,
        "final_audio_url": r.get("final_audio_url") or "",
        "error_message": r.get("error_message") or "",
        "research_notes": r.get("research_notes") or "",
        "sections_count": len(sections),
        "sections": sections if include_script else [],
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
        "completed_at": r["completed_at"].isoformat() if r.get("completed_at") else None,
    }


# ── Metadata endpoints ─────────────────────────────────────

@router.get("/meta")
async def get_meta():
    """Return available durations, languages, tones, and WPM settings."""
    return {
        "durations": DURATIONS,
        "languages": LANGUAGES,
        "tones": [{"id": k, "name": v.split(" — ")[0], "desc": v} for k, v in TONES.items()],
        "wpm": WPM_BY_LANGUAGE,
        "llm": llm_status(),
    }


@router.get("/estimate")
async def get_estimate(
    duration: int = Query(...),
    language: str = Query("en"),
    request: Request = None,
):
    """Calculate estimated words, sections, chunks, and generation time."""
    settings = await load_settings()
    wpm = int(settings.get("default_wpm", str(WPM_BY_LANGUAGE.get(language, 145))))
    target_words = calculate_word_count(duration, language, wpm)
    section_count = calculate_section_count(duration)
    chunk_size = get_setting_int(settings, "f5_tts_chunk_size", 500)
    chunk_count = max(1, target_words * 5 // chunk_size)  # ~5 chars per word
    gen_time = estimate_generation_time(duration, chunk_count)
    return {
        "estimated_words": target_words,
        "estimated_sections": section_count,
        "estimated_chunks": chunk_count,
        "estimated_generation_time": gen_time,
        "estimated_audio_duration": duration * 60,
    }


# ── CRUD ────────────────────────────────────────────────────

@router.post("")
async def create_project(request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    body = await request.json()
    title = (body.get("title") or "").strip()
    if not title:
        raise APIError(400, "INVALID_INPUT", "Title is required.")
    if len(title) > 300:
        raise APIError(400, "INVALID_INPUT", "Title too long (max 300 chars).")

    duration = int(body.get("duration_minutes", 5))
    if duration not in DURATIONS and duration < 1:
        raise APIError(400, "INVALID_INPUT", "Invalid duration.")
    custom_duration = body.get("custom_duration")
    if custom_duration and int(custom_duration) > 0:
        duration = int(custom_duration)

    language = body.get("language", "en")
    tone = body.get("tone", "documentary")
    voice_id = body.get("voice_id")
    voice_key = body.get("voice_key", "en-US-AriaNeural")
    voice_name = body.get("voice_name", "")
    engine = body.get("engine", "edge-tts")
    mode = body.get("mode", "auto")
    research_enabled = bool(body.get("research_enabled", False))

    # Validate voice access
    if voice_id:
        async with pool.acquire() as conn:
            vp = await conn.fetchrow("SELECT * FROM voice_profiles WHERE id=$1", int(voice_id))
        if not vp:
            raise APIError(404, "VOICE_NOT_FOUND", "Voice not found.")
        vp = dict(vp)
        if vp["user_id"] != user["id"] and vp.get("visibility") != "public":
            raise APIError(403, "FORBIDDEN", "You do not have access to this voice.")
        engine = vp.get("engine") or "f5-tts"
        voice_name = vp["name"]

    settings = await load_settings()
    wpm = int(settings.get("default_wpm", str(WPM_BY_LANGUAGE.get(language, 145))))
    target_words = calculate_word_count(duration, language, wpm)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO ai_projects
               (user_id, title, language, target_duration, voice_id, voice_key, voice_name, engine,
                tone, mode, research_enabled, estimated_words, status)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'draft') RETURNING *""",
            user["id"], title, language, duration,
            int(voice_id) if voice_id else None, voice_key, voice_name, engine,
            tone, mode, research_enabled, target_words,
        )
    project = _row_to_project(dict(row))

    # Auto mode: kick off script generation immediately
    if mode == "auto":
        await start_script_generation(row["id"], mode)

    return {"success": True, "project": project}


@router.get("")
async def list_projects(request: Request, user: dict = Depends(require_user),
                         page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)):
    pool = get_pool()
    if not pool:
        return {"items": [], "page": page, "total": 0}
    offset = (page - 1) * limit
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM ai_projects WHERE user_id=$1", user["id"])
        rows = await conn.fetch(
            "SELECT * FROM ai_projects WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            user["id"], limit, offset,
        )
    return {"items": [_row_to_project(dict(r), include_script=False) for r in rows], "page": page, "total": total}


@router.get("/{project_id}")
async def get_project(project_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Project not found.")
        r = dict(r)
        if r["user_id"] != user["id"] and user.get("role") not in ("admin", "super_admin"):
            raise APIError(403, "FORBIDDEN", "Not your project.")
        jobs = await conn.fetch(
            "SELECT * FROM ai_project_jobs WHERE project_id=$1 ORDER BY created_at, id",
            project_id,
        )
    project = _row_to_project(r)
    job_list = [{
        "id": j["id"], "type": j["type"], "section_id": j.get("section_id") or "",
        "status": j["status"], "attempts": j.get("attempts") or 0,
        "error_message": j.get("error_message") or "",
        "started_at": j["started_at"].isoformat() if j.get("started_at") else None,
        "completed_at": j["completed_at"].isoformat() if j.get("completed_at") else None,
    } for j in jobs]
    status_detail = get_project_status_detail(r, job_list)
    return {"project": project, "jobs": job_list, "status_detail": status_detail}


@router.patch("/{project_id}")
async def update_project(project_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    body = await request.json()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Project not found.")
        r = dict(r)
        if r["user_id"] != user["id"]:
            raise APIError(403, "FORBIDDEN", "Not your project.")

        updates = {}
        for k in ("title", "language", "target_duration", "tone", "mode", "research_enabled"):
            if k in body:
                updates[k] = body[k]

        # Update script sections if provided
        if "sections" in body:
            script = json.loads(r["script"]) if isinstance(r["script"], str) and r["script"] else (r["script"] or {})
            script["sections"] = body["sections"]
            updates["script"] = json.dumps(script)

        if updates:
            sets = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates.keys()))
            vals = [project_id] + list(updates.values())
            await conn.execute(f"UPDATE ai_projects SET {sets}, updated_at=NOW() WHERE id=$1", *vals)
            r = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)

    return {"success": True, "project": _row_to_project(dict(r))}


@router.delete("/{project_id}")
async def delete_project(project_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Project not found.")
        if r["user_id"] != user["id"] and user.get("role") not in ("admin", "super_admin"):
            raise APIError(403, "FORBIDDEN", "Not your project.")
        await conn.execute("DELETE FROM ai_projects WHERE id=$1", project_id)
    return {"success": True}


# ── Pipeline control ───────────────────────────────────────

@router.post("/{project_id}/generate-script")
async def generate_script(project_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Project not found.")
        if r["user_id"] != user["id"]:
            raise APIError(403, "FORBIDDEN", "Not your project.")
        if r["status"] in ("generating_script", "generating_audio", "assembling"):
            raise APIError(409, "IN_PROGRESS", "Project is already processing.")

    await start_script_generation(project_id)
    return {"success": True, "message": "Script generation started."}


@router.post("/{project_id}/validate-script")
async def validate_script(project_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Project not found.")
        if r["user_id"] != user["id"]:
            raise APIError(403, "FORBIDDEN", "Not your project.")
        # Create a validation job
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM ai_project_jobs WHERE project_id=$1 AND type='validation' AND status IN ('pending','processing')",
            project_id,
        )
        if existing:
            raise APIError(409, "IN_PROGRESS", "Validation already running.")
        await conn.execute(
            "INSERT INTO ai_project_jobs (project_id, type, status) VALUES ($1, 'validation', 'pending')",
            project_id,
        )
        await conn.execute(
            "UPDATE ai_projects SET status='generating_script', script_status='validating', updated_at=NOW() WHERE id=$1",
            project_id,
        )
    return {"success": True, "message": "Script validation started."}


@router.post("/{project_id}/generate-audio")
async def generate_audio(project_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Project not found.")
        if r["user_id"] != user["id"]:
            raise APIError(403, "FORBIDDEN", "Not your project.")
        if r["status"] in ("generating_audio", "assembling"):
            raise APIError(409, "IN_PROGRESS", "Audio generation already in progress.")
        if r["script_status"] != "ready":
            raise APIError(409, "SCRIPT_NOT_READY", "Script must be ready before generating audio.")
        if not r.get("voice_id") and not r.get("voice_key"):
            raise APIError(400, "NO_VOICE", "No voice selected.")

    total_chunks = await start_audio_generation(project_id)
    return {"success": True, "message": "Audio generation started.", "total_chunks": total_chunks}


@router.get("/{project_id}/status")
async def get_status(project_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Project not found.")
        r = dict(r)
        if r["user_id"] != user["id"] and user.get("role") not in ("admin", "super_admin"):
            raise APIError(403, "FORBIDDEN", "Not your project.")
        jobs = await conn.fetch(
            "SELECT * FROM ai_project_jobs WHERE project_id=$1 ORDER BY created_at, id",
            project_id,
        )

    # Check if audio generation is complete and needs assembly
    if r["status"] == "generating_audio":
        await check_audio_completion(project_id)
        # Re-read after check
        async with pool.acquire() as conn:
            r = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
            r = dict(r)
            jobs = await conn.fetch(
                "SELECT * FROM ai_project_jobs WHERE project_id=$1 ORDER BY created_at, id",
                project_id,
            )

    job_list = [{
        "id": j["id"], "type": j["type"], "section_id": j.get("section_id") or "",
        "status": j["status"], "attempts": j.get("attempts") or 0,
        "error_message": j.get("error_message") or "",
    } for j in jobs]
    status_detail = get_project_status_detail(r, job_list)

    # Also mark project as failed if any job permanently failed
    if r["status"] in ("generating_script", "generating_audio", "assembling"):
        failed_jobs = [j for j in job_list if j["status"] == "failed" and j["type"] not in ("tts",)]
        # For TTS, we don't fail the whole project — just the chunk, and user can resume
        script_failed = any(j for j in job_list if j["status"] == "failed" and j["type"] in ("outline", "script", "validation"))
        if script_failed:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE ai_projects SET status='failed', error_message='Script generation failed', updated_at=NOW() WHERE id=$1",
                    project_id,
                )
            r = dict(r)
            r["status"] = "failed"

    return {
        "project": _row_to_project(r, include_script=False),
        "status_detail": status_detail,
        "jobs": job_list,
    }


@router.post("/{project_id}/cancel")
async def cancel_project(project_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Project not found.")
        if r["user_id"] != user["id"] and user.get("role") not in ("admin", "super_admin"):
            raise APIError(403, "FORBIDDEN", "Not your project.")
        if r["status"] not in ("generating_script", "generating_audio", "assembling"):
            raise APIError(409, "NOT_CANCELLABLE", "Only active projects can be cancelled.")
        await conn.execute(
            "UPDATE ai_projects SET status='cancelled', updated_at=NOW() WHERE id=$1",
            project_id,
        )
        await conn.execute(
            "UPDATE ai_project_jobs SET status='cancelled', completed_at=NOW() WHERE project_id=$1 AND status IN ('pending','processing')",
            project_id,
        )
    return {"success": True}


@router.post("/{project_id}/resume")
async def resume_project_endpoint(project_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Project not found.")
        if r["user_id"] != user["id"]:
            raise APIError(403, "FORBIDDEN", "Not your project.")
        if r["status"] not in ("failed",):
            raise APIError(409, "NOT_FAILED", "Only failed projects can be resumed.")

    await resume_project(project_id)
    return {"success": True, "message": "Project resumed."}


@router.post("/{project_id}/regenerate-section")
async def regenerate_section(project_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    body = await request.json()
    section_id = body.get("section_id")
    if not section_id:
        raise APIError(400, "INVALID_INPUT", "section_id is required.")

    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Project not found.")
        if r["user_id"] != user["id"]:
            raise APIError(403, "FORBIDDEN", "Not your project.")
        r = dict(r)
        script = json.loads(r["script"]) if isinstance(r["script"], str) and r["script"] else (r["script"] or {})
        sections = script.get("sections", [])
        section = next((s for s in sections if s.get("id") == section_id), None)
        if not section:
            raise APIError(404, "SECTION_NOT_FOUND", "Section not found.")
        section["text"] = ""
        section["status"] = "pending"
        await conn.execute(
            "UPDATE ai_projects SET script=$1, updated_at=NOW() WHERE id=$2",
            json.dumps(script), project_id,
        )
        await conn.execute(
            "INSERT INTO ai_project_jobs (project_id, type, section_id, status) VALUES ($1, 'script', $2, 'pending')",
            project_id, section_id,
        )
        if r["status"] not in ("generating_script",):
            await conn.execute(
                "UPDATE ai_projects SET status='generating_script', script_status='generating', updated_at=NOW() WHERE id=$1",
                project_id,
            )
    return {"success": True, "message": "Section regeneration started."}


@router.post("/{project_id}/generate-preview")
async def generate_preview(project_id: int, request: Request, user: dict = Depends(require_user)):
    """Generate a short 15-second preview using the selected voice."""
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Project not found.")
        if r["user_id"] != user["id"]:
            raise APIError(403, "FORBIDDEN", "Not your project.")
        r = dict(r)

    script = json.loads(r["script"]) if isinstance(r["script"], str) and r["script"] else (r["script"] or {})
    sections = script.get("sections", [])
    # Take first ~200 chars of first section with text
    preview_text = ""
    for s in sections:
        if s.get("text"):
            preview_text = s["text"][:200]
            break
    if not preview_text:
        preview_text = f"Welcome to {r['title']}. This is a preview of the narration voice."

    from providers import get_provider
    from secure_storage import save_generation_audio
    engine = r["engine"] or "edge-tts"
    voice_id = r.get("voice_id")
    voice_key = r.get("voice_key") or "en-US-AriaNeural"

    if engine == "f5-tts" and voice_id:
        async with pool.acquire() as conn:
            vp = await conn.fetchrow("SELECT * FROM voice_profiles WHERE id=$1", voice_id)
        if not vp:
            raise APIError(404, "VOICE_NOT_FOUND", "Voice not found.")
        voice = {"key": vp.get("voice_key") or "", "reference_audio_url": vp.get("reference_audio_url") or "", "reference_text": vp.get("reference_text") or ""}
    else:
        voice = {"key": voice_key}

    provider = get_provider(engine)
    try:
        audio, duration = await provider.generate(preview_text, voice, {"voice_key": voice_key, "speed": 1.0})
    except Exception as e:
        raise APIError(500, "PREVIEW_FAILED", f"Preview generation failed: {e}")

    ext = ".mp3" if engine != "f5-tts" else ".wav"
    fname = save_generation_audio(audio, ext)
    return {"success": True, "preview_url": f"/api/storage/generations/{fname}", "duration": float(duration or 0)}
