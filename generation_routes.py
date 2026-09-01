"""Generation routes: create queued jobs, poll status, cancel, history."""
import json
import time
import logging
from datetime import datetime, date

from fastapi import APIRouter, Request, Depends, Query

from core import require_user, APIError, get_pool, load_settings, get_setting_int
from providers import get_provider, TTSProviderError

logger = logging.getLogger("bglabs.generations")
router = APIRouter(prefix="/api/generations", tags=["generations"])


async def _check_rate_limits(conn, user_id: int, settings: dict):
    per_min = get_setting_int(settings, "max_generations_per_minute", 20)
    per_day = get_setting_int(settings, "max_generations_per_day", 200)
    today = datetime.utcnow().date()
    minute_ago = datetime.utcnow().timestamp() - 60
    recent = await conn.fetchval(
        "SELECT COUNT(*) FROM generations WHERE user_id=$1 AND created_at > NOW() - INTERVAL '1 minute'",
        user_id,
    )
    if recent >= per_min:
        raise APIError(429, "RATE_LIMIT", f"Rate limit: max {per_min} generations per minute.")
    day_count = await conn.fetchval(
        "SELECT COALESCE(SUM(generation_count),0) FROM usage WHERE user_id=$1 AND period_start=$2",
        user_id, today,
    )
    if day_count >= per_day:
        raise APIError(429, "DAILY_LIMIT", f"Daily limit reached: max {per_day} generations per day.")


@router.post("")
async def create_generation(request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise APIError(400, "INVALID_INPUT", "Text is required.")
    settings = await load_settings()
    max_len = get_setting_int(settings, "max_text_length", 5000)
    if len(text) > max_len:
        raise APIError(400, "TEXT_TOO_LONG", f"Text exceeds {max_len} characters.")

    async with pool.acquire() as conn:
        await _check_rate_limits(conn, user["id"], settings)

    voice_id = body.get("voice_id")
    engine = body.get("engine")
    voice_label = body.get("voice_label") or ""

    # Resolve engine + voice label.
    if voice_id and engine != "edge-tts":
        async with pool.acquire() as conn:
            vp = await conn.fetchrow("SELECT * FROM voice_profiles WHERE id=$1", int(voice_id))
        if not vp:
            raise APIError(404, "VOICE_NOT_FOUND", "Voice not found.")
        vp = dict(vp)
        if vp["user_id"] != user["id"] and vp.get("visibility") != "public":
            raise APIError(403, "FORBIDDEN", "You do not have access to this voice.")
        if vp.get("status") not in ("ready",):
            raise APIError(409, "VOICE_UNAVAILABLE", f"Voice status is '{vp.get('status')}'.")
        engine = vp.get("engine") or "f5-tts"
        voice_label = vp["name"]
        job_settings = {"speed": body.get("speed", 1.0)}
    else:
        engine = "edge-tts"
        voice_label = voice_label or body.get("voice_name") or "Voice"
        job_settings = {
            "voice_key": body.get("voice_key") or "en-US-AriaNeural",
            "rate": body.get("rate", "+0%"),
            "pitch": body.get("pitch", "+0Hz"),
        }

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO generations (user_id, voice_id, voice_label, text, engine, status, settings, chars)
               VALUES ($1,$2,$3,$4,$5,'queued',$6,$7) RETURNING id, status, created_at""",
            user["id"], (int(voice_id) if voice_id and engine != "edge-tts" else None),
            voice_label, text, engine, json.dumps(job_settings), len(text),
        )
    return {"success": True, "job": {"id": row["id"], "status": row["status"], "engine": engine, "created_at": row["created_at"].isoformat()}}


@router.get("")
async def list_generations(request: Request, user: dict = Depends(require_user),
                          page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100),
                          status: str = Query("")):
    pool = get_pool()
    if not pool:
        return {"items": [], "page": page, "total": 0}
    offset = (page - 1) * limit
    async with pool.acquire() as conn:
        if status:
            total = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE user_id=$1 AND status=$2", user["id"], status)
            rows = await conn.fetch(
                "SELECT * FROM generations WHERE user_id=$1 AND status=$2 ORDER BY created_at DESC LIMIT $3 OFFSET $4",
                user["id"], status, limit, offset)
        else:
            total = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE user_id=$1", user["id"])
            rows = await conn.fetch(
                "SELECT * FROM generations WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
                user["id"], limit, offset)
    return {"items": [_row_to_gen(dict(r)) for r in rows], "page": page, "limit": limit, "total": total}


@router.get("/{gen_id}")
async def get_generation(gen_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM generations WHERE id=$1", gen_id)
    if not r:
        raise APIError(404, "NOT_FOUND", "Generation not found.")
    r = dict(r)
    if r["user_id"] != user["id"] and user.get("role") not in ("admin", "super_admin"):
        raise APIError(403, "FORBIDDEN", "Not your generation.")
    return {"generation": _row_to_gen(r)}


@router.post("/{gen_id}/cancel")
async def cancel_generation(gen_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM generations WHERE id=$1", gen_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Generation not found.")
        if r["user_id"] != user["id"] and user.get("role") not in ("admin", "super_admin"):
            raise APIError(403, "FORBIDDEN", "Not your generation.")
        if r["status"] not in ("queued", "processing"):
            raise APIError(409, "NOT_CANCELLABLE", "Only queued or processing jobs can be cancelled.")
        await conn.execute(
            "UPDATE generations SET status='cancelled', completed_at=NOW(), error_code='CANCELLED', error_message='Cancelled by user' WHERE id=$1",
            gen_id,
        )
    return {"success": True}


def _row_to_gen(r: dict) -> dict:
    return {
        "id": r["id"],
        "user_id": r["user_id"],
        "voice_id": r.get("voice_id"),
        "voice_label": r.get("voice_label") or "",
        "text": r["text"],
        "engine": r.get("engine") or "edge-tts",
        "status": r["status"],
        "audio_url": r.get("audio_url") or "",
        "duration": r.get("duration") or 0,
        "chars": r.get("chars") or 0,
        "error_code": r.get("error_code") or "",
        "error_message": r.get("error_message") or "",
        "retry_count": r.get("retry_count") or 0,
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "started_at": r["started_at"].isoformat() if r.get("started_at") else None,
        "completed_at": r["completed_at"].isoformat() if r.get("completed_at") else None,
    }
