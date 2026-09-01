"""Voice cloning routes: create/list/update/delete cloned voices + audio validation."""
import json
import logging
from typing import Optional, List

from fastapi import APIRouter, Request, Depends, UploadFile, File, Form, Query
from fastapi.responses import FileResponse

from core import require_user, require_admin, APIError, get_pool, load_settings, get_setting_int, log_admin_action
from secure_storage import validate_audio_file, save_reference_audio, reference_audio_path, VOICES_DIR

logger = logging.getLogger("bglabs.voices")
router = APIRouter(prefix="/api/voices", tags=["voices"])


def _row_to_voice(r: dict, include_ref: bool = False) -> dict:
    v = {
        "id": r["id"],
        "user_id": r["user_id"],
        "name": r["name"],
        "description": r.get("description") or "",
        "language": r.get("language") or "en",
        "duration": r.get("duration") or 0,
        "sample_rate": r.get("sample_rate") or 22050,
        "status": r.get("status") or "ready",
        "visibility": r.get("visibility") or "private",
        "engine": r.get("engine") or "edge-tts",
        "reference_text": r.get("reference_text") or "",
        "consent_confirmed": bool(r.get("consent_confirmed")),
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }
    if include_ref:
        v["reference_audio_url"] = r.get("reference_audio_url") or ""
    return v


@router.post("/validate-audio")
async def validate_audio(request: Request, file: UploadFile = File(...), user: dict = Depends(require_user)):
    settings = await load_settings()
    max_size = get_setting_int(settings, "max_reference_audio_size", 10485760)
    content = await file.read()
    result = validate_audio_file(file.filename or "audio.mp3", content, max_size)
    if not result["ok"]:
        raise APIError(400, "AUDIO_INVALID", result["error"])
    return {"success": True, "valid": True, "size": len(content), "ext": result.get("ext")}


@router.post("")
async def create_voice(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    language: str = Form("en"),
    reference_text: str = Form(...),
    consent_confirmed: bool = Form(...),
    visibility: str = Form("private"),
    file: UploadFile = File(...),
    user: dict = Depends(require_user),
):
    if not name or len(name) > 80:
        raise APIError(400, "INVALID_INPUT", "Voice name is required (max 80 chars).")
    if not reference_text or len(reference_text) > 1000:
        raise APIError(400, "INVALID_INPUT", "Reference transcript is required (max 1000 chars).")
    if not consent_confirmed:
        raise APIError(400, "CONSENT_REQUIRED", "You must confirm you own or have permission to use this voice.")
    if visibility not in ("private", "public"):
        raise APIError(400, "INVALID_INPUT", "Visibility must be private or public.")

    settings = await load_settings()
    max_size = get_setting_int(settings, "max_reference_audio_size", 10485760)
    max_voices = get_setting_int(settings, "max_voices_per_user", 10)
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")

    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM voice_profiles WHERE user_id=$1", user["id"])
    if count >= max_voices:
        raise APIError(403, "VOICE_LIMIT", f"You have reached the maximum of {max_voices} voices.")

    content = await file.read()
    result = validate_audio_file(file.filename or "audio.mp3", content, max_size)
    if not result["ok"]:
        raise APIError(400, "AUDIO_INVALID", result["error"])

    fname = save_reference_audio(content, result["ext"])
    # Reference audio stored privately; the provider needs a readable path/url.
    ref_url = str(VOICES_DIR / fname)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO voice_profiles
               (user_id, name, description, reference_audio_url, reference_text, language, duration,
                status, visibility, consent_confirmed, consent_timestamp, engine)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW(),'f5-tts') RETURNING *""",
            user["id"], name, description, ref_url, reference_text, language, 0.0,
            "ready", "private", consent_confirmed,
        )
    return {"success": True, "voice": _row_to_voice(dict(row), include_ref=True)}


@router.get("")
async def list_voices(request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    if not pool:
        return {"voices": [], "total": 0}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM voice_profiles
               WHERE user_id=$1 OR (visibility='public' AND status='ready')
               ORDER BY created_at DESC""",
            user["id"],
        )
    voices = []
    for r in rows:
        v = _row_to_voice(dict(r))
        v["owned"] = r["user_id"] == user["id"]
        voices.append(v)
    return {"voices": voices, "total": len(voices)}


@router.get("/my")
async def my_voices(request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    if not pool:
        return {"voices": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM voice_profiles WHERE user_id=$1 ORDER BY created_at DESC", user["id"])
    return {"voices": [_row_to_voice(dict(r), include_ref=True) for r in rows]}


@router.get("/{voice_id}")
async def get_voice(voice_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM voice_profiles WHERE id=$1", voice_id)
    if not r:
        raise APIError(404, "VOICE_NOT_FOUND", "Voice not found.")
    r = dict(r)
    if r["user_id"] != user["id"] and r.get("visibility") != "public":
        raise APIError(403, "FORBIDDEN", "You do not have access to this voice.")
    return {"voice": _row_to_voice(r, include_ref=(r["user_id"] == user["id"]))}


@router.get("/{voice_id}/reference")
async def get_reference_audio(voice_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM voice_profiles WHERE id=$1", voice_id)
    if not r:
        raise APIError(404, "VOICE_NOT_FOUND", "Voice not found.")
    if r["user_id"] != user["id"] and user.get("role") not in ("admin", "super_admin"):
        raise APIError(403, "FORBIDDEN", "Private reference audio.")
    path = reference_audio_path((r["reference_audio_url"] or "").split("/")[-1])
    if not path:
        raise APIError(404, "AUDIO_NOT_FOUND", "Reference audio file not found.")
    return FileResponse(str(path))


@router.patch("/{voice_id}")
async def update_voice(voice_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    body = await request.json()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM voice_profiles WHERE id=$1", voice_id)
        if not r:
            raise APIError(404, "VOICE_NOT_FOUND", "Voice not found.")
        if r["user_id"] != user["id"]:
            raise APIError(403, "FORBIDDEN", "You can only edit your own voices.")
        updates = {}
        for k in ("name", "description", "language", "visibility"):
            if k in body:
                updates[k] = body[k]
        if updates:
            sets = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates.keys()))
            vals = [voice_id] + list(updates.values())
            await conn.execute(f"UPDATE voice_profiles SET {sets}, updated_at=NOW() WHERE id=$1", *vals)
            r = await conn.fetchrow("SELECT * FROM voice_profiles WHERE id=$1", voice_id)
    return {"success": True, "voice": _row_to_voice(dict(r))}


@router.delete("/{voice_id}")
async def delete_voice(voice_id: int, request: Request, user: dict = Depends(require_user)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM voice_profiles WHERE id=$1", voice_id)
        if not r:
            raise APIError(404, "VOICE_NOT_FOUND", "Voice not found.")
        if r["user_id"] != user["id"] and user.get("role") not in ("admin", "super_admin"):
            raise APIError(403, "FORBIDDEN", "You can only delete your own voices.")
        await conn.execute("DELETE FROM voice_profiles WHERE id=$1", voice_id)
    return {"success": True}
