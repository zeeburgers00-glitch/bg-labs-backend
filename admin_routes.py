"""Admin panel routes — all values come from the real database."""
import json
import logging
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Request, Depends, Query

from core import require_admin, APIError, get_pool, load_settings, log_admin_action
from providers import f5_provider
from secure_storage import VOICES_DIR, GENERATIONS_DIR

logger = logging.getLogger("bglabs.admin")
router = APIRouter(prefix="/api/admin", tags=["admin"])


def _system_status():
    pool = get_pool()
    return {
        "backend": "healthy",
        "database": "healthy" if pool else "unavailable",
        "storage": "healthy" if GENERATIONS_DIR.exists() and VOICES_DIR.exists() else "unavailable",
    }


def _clean_user(r: dict) -> dict:
    return {
        "id": r["id"],
        "email": r["email"],
        "name": r.get("full_name") or r.get("username") or r["email"].split("@")[0],
        "username": r.get("username") or "",
        "role": r.get("role") or "user",
        "credits": r.get("credits") or 0,
        "total_used": r.get("total_used") or 0,
        "is_active": bool(r.get("is_active")),
        "status": r.get("status") or ("active" if r.get("is_active") else "blocked"),
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "is_admin": r.get("role") in ("admin", "super_admin"),
    }


# ── Backward-compatible stats (used by existing frontend DB.getStats) ──
@router.get("/stats")
async def admin_stats(admin: dict = Depends(require_admin)):
    pool = get_pool()
    if not pool:
        return {"total_users": 0, "total_voices": 0, "total_audio": 0, "total_images": 0, "total_credits_used": 0}
    async with pool.acquire() as conn:
        users = await conn.fetchval("SELECT COUNT(*) FROM users")
        voices = await conn.fetchval("SELECT COUNT(*) FROM voice_profiles")
        audio = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE status='completed'")
        images = await conn.fetchval("SELECT COUNT(*) FROM image_history")
        chars = await conn.fetchval("SELECT COALESCE(SUM(total_used),0) FROM users")
    return {"total_users": users, "total_voices": voices, "total_audio": audio, "total_images": images, "total_credits_used": chars}


# ── Backward-compatible users list (used by existing frontend DB.getAllUsers) ──
@router.get("/users")
async def admin_users(admin: dict = Depends(require_admin), page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200)):
    pool = get_pool()
    if not pool:
        return {"users": [], "page": page, "total": 0}
    offset = (page - 1) * limit
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users")
        rows = await conn.fetch("SELECT * FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2", limit, offset)
        users = []
        for r in rows:
            u = _clean_user(dict(r))
            u["voices"] = await pool.acquire() and 0  # placeholder
            vc = await pool.fetchval("SELECT COUNT(*) FROM voice_profiles WHERE user_id=$1", r["id"])
            gc = await pool.fetchval("SELECT COUNT(*) FROM generations WHERE user_id=$1", r["id"])
            u["voices_count"] = vc
            u["generations_count"] = gc
            users.append(u)
    return {"users": users, "page": page, "limit": limit, "total": total}


@router.get("/dashboard")
async def dashboard(admin: dict = Depends(require_admin)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    today = datetime.utcnow().date()
    async with pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        active_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_active=TRUE")
        blocked_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_active=FALSE")
        total_voices = await conn.fetchval("SELECT COUNT(*) FROM voice_profiles")
        total_generations = await conn.fetchval("SELECT COUNT(*) FROM generations")
        today_generations = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE created_at::date=$1", today)
        audio_seconds = await conn.fetchval("SELECT COALESCE(SUM(duration),0) FROM generations WHERE status='completed'")
        failed_generations = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE status='failed'")
        queued_jobs = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE status='queued'")
        processing_jobs = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE status='processing'")
        total_chars = await conn.fetchval("SELECT COALESCE(SUM(chars),0) FROM generations")

    f5_health = await f5_provider().health()
    sys_status = _system_status()
    sys_status["queue"] = "healthy" if queued_jobs < 100 else "busy"
    sys_status["f5_tts"] = f5_health["status"] if f5_health["status"] in ("healthy", "unavailable", "unhealthy", "unreachable") else "unknown"

    return {
        "stats": {
            "total_users": total_users,
            "active_users": active_users,
            "blocked_users": blocked_users,
            "total_voices": total_voices,
            "total_generations": total_generations,
            "today_generations": today_generations,
            "audio_seconds": float(audio_seconds or 0),
            "failed_generations": failed_generations,
            "queued_jobs": queued_jobs,
            "processing_jobs": processing_jobs,
            "total_chars": total_chars,
        },
        "system_status": sys_status,
        "f5_tts": f5_health,
    }


@router.get("/users/{user_id}")
async def admin_user_detail(user_id: int, admin: dict = Depends(require_admin)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
        if not r:
            raise APIError(404, "USER_NOT_FOUND", "User not found.")
        voices = await conn.fetch("SELECT * FROM voice_profiles WHERE user_id=$1 ORDER BY created_at DESC", user_id)
        gens = await conn.fetch("SELECT * FROM generations WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50", user_id)
        usage = await conn.fetch("SELECT * FROM usage WHERE user_id=$1 ORDER BY period_start DESC LIMIT 30", user_id)
    return {
        "user": _clean_user(dict(r)),
        "voices": len(voices),
        "generations": len(gens),
        "recent_generations": [_gen_short(dict(g)) for g in gens],
        "usage": [{"period": str(u["period_start"]), "chars": u["characters_used"], "seconds": u["audio_seconds"], "count": u["generation_count"], "failed": u["failed_count"]} for u in usage],
    }


@router.post("/users/{user_id}/status")
async def set_user_status(user_id: int, request: Request, admin: dict = Depends(require_admin)):
    pool = get_pool()
    body = await request.json()
    active = bool(body.get("active"))
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
        if not r:
            raise APIError(404, "USER_NOT_FOUND", "User not found.")
        if r["role"] in ("admin", "super_admin"):
            raise APIError(403, "FORBIDDEN", "Cannot suspend an admin.")
        await conn.execute("UPDATE users SET is_active=$1, status=$2, updated_at=NOW() WHERE id=$3",
                           active, "active" if active else "suspended", user_id)
    await log_admin_action(admin["id"], "suspend" if not active else "activate", "user", str(user_id))
    return {"success": True, "is_active": active}


@router.get("/voices")
async def admin_voices(admin: dict = Depends(require_admin), page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200)):
    pool = get_pool()
    if not pool:
        return {"items": [], "total": 0}
    offset = (page - 1) * limit
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM voice_profiles")
        rows = await conn.fetch(
            """SELECT vp.*, u.email AS owner_email, u.username AS owner_name
               FROM voice_profiles vp LEFT JOIN users u ON vp.user_id=u.id
               ORDER BY vp.created_at DESC LIMIT $1 OFFSET $2""",
            limit, offset,
        )
    items = []
    for r in rows:
        r = dict(r)
        gen_count = 0
        async with pool.acquire() as conn:
            gen_count = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE voice_id=$1", r["id"])
        items.append({
            "id": r["id"], "name": r["name"], "owner": r.get("owner_name") or r.get("owner_email") or "",
            "owner_email": r.get("owner_email") or "", "language": r.get("language") or "en",
            "status": r.get("status") or "ready", "visibility": r.get("visibility") or "private",
            "engine": r.get("engine") or "edge-tts", "consent_confirmed": bool(r.get("consent_confirmed")),
            "generation_count": gen_count, "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        })
    return {"items": items, "page": page, "limit": limit, "total": total}


@router.patch("/voices/{voice_id}")
async def admin_update_voice(voice_id: int, request: Request, admin: dict = Depends(require_admin)):
    pool = get_pool()
    body = await request.json()
    updates = {}
    for k in ("status", "visibility"):
        if k in body:
            updates[k] = body[k]
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM voice_profiles WHERE id=$1", voice_id)
        if not r:
            raise APIError(404, "VOICE_NOT_FOUND", "Voice not found.")
        if updates:
            sets = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates.keys()))
            await conn.execute(f"UPDATE voice_profiles SET {sets}, updated_at=NOW() WHERE id=$1", voice_id, *updates.values())
    await log_admin_action(admin["id"], "update_voice", "voice", str(voice_id), updates)
    return {"success": True}


@router.delete("/voices/{voice_id}")
async def admin_delete_voice(voice_id: int, request: Request, admin: dict = Depends(require_admin)):
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM voice_profiles WHERE id=$1", voice_id)
        if not r:
            raise APIError(404, "VOICE_NOT_FOUND", "Voice not found.")
        await conn.execute("DELETE FROM voice_profiles WHERE id=$1", voice_id)
    await log_admin_action(admin["id"], "delete_voice", "voice", str(voice_id))
    return {"success": True}


@router.get("/generations")
async def admin_generations(admin: dict = Depends(require_admin), page: int = Query(1, ge=1), limit: int = Query(30, ge=1, le=100),
                             status: str = Query(""), engine: str = Query("")):
    pool = get_pool()
    if not pool:
        return {"items": [], "total": 0}
    offset = (page - 1) * limit
    where = ["1=1"]
    args = []
    if status:
        where.append(f"g.status=${len(args)+1}")
        args.append(status)
    if engine:
        where.append(f"g.engine=${len(args)+1}")
        args.append(engine)
    where_sql = " AND ".join(where)
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM generations g WHERE {where_sql}", *args)
        rows = await conn.fetch(
            f"""SELECT g.*, u.email AS user_email, u.username AS user_name
                FROM generations g LEFT JOIN users u ON g.user_id=u.id
                WHERE {where_sql} ORDER BY g.created_at DESC LIMIT ${len(args)+1} OFFSET ${len(args)+2}""",
            *args, limit, offset,
        )
    items = []
    for r in rows:
        r = dict(r)
        proc_time = None
        if r.get("started_at") and r.get("completed_at"):
            proc_time = (r["completed_at"] - r["started_at"]).total_seconds()
        items.append({
            "id": r["id"], "user": r.get("user_name") or r.get("user_email") or "",
            "user_email": r.get("user_email") or "", "voice": r.get("voice_label") or "",
            "text_preview": (r["text"] or "")[:120], "status": r["status"], "engine": r.get("engine") or "",
            "duration": r.get("duration") or 0, "chars": r.get("chars") or 0,
            "error": r.get("error_message") or "", "processing_time": proc_time,
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        })
    return {"items": items, "page": page, "limit": limit, "total": total}


@router.get("/jobs")
async def admin_jobs(admin: dict = Depends(require_admin)):
    pool = get_pool()
    if not pool:
        return {"stats": {}, "items": []}
    async with pool.acquire() as conn:
        queued = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE status='queued'")
        processing = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE status='processing'")
        completed = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE status='completed'")
        failed = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE status='failed'")
        avg = await conn.fetchval("SELECT COALESCE(AVG(EXTRACT(EPOCH FROM (completed_at - started_at))),0) FROM generations WHERE status='completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL")
        rows = await conn.fetch("SELECT * FROM generations WHERE status IN ('queued','processing','failed') ORDER BY created_at DESC LIMIT 50")
    return {
        "stats": {"queued": queued, "processing": processing, "completed": completed, "failed": failed, "avg_processing_time": float(avg or 0)},
        "items": [{"id": r["id"], "status": r["status"], "voice": r.get("voice_label") or "", "engine": r.get("engine") or "", "retry_count": r.get("retry_count") or 0, "created_at": r["created_at"].isoformat() if r.get("created_at") else None} for r in rows],
    }


@router.post("/jobs/{job_id}/retry")
async def admin_retry_job(job_id: int, request: Request, admin: dict = Depends(require_admin)):
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM generations WHERE id=$1", job_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Job not found.")
        if r["status"] != "failed":
            raise APIError(409, "NOT_FAILED", "Only failed jobs can be retried.")
        await conn.execute("UPDATE generations SET status='queued', retry_count=0, error_code='', error_message='', started_at=NULL, completed_at=NULL WHERE id=$1", job_id)
    await log_admin_action(admin["id"], "retry_job", "generation", str(job_id))
    return {"success": True}


@router.post("/jobs/{job_id}/cancel")
async def admin_cancel_job(job_id: int, request: Request, admin: dict = Depends(require_admin)):
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM generations WHERE id=$1", job_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Job not found.")
        if r["status"] not in ("queued", "processing"):
            raise APIError(409, "NOT_CANCELLABLE", "Only queued/processing jobs can be cancelled.")
        await conn.execute("UPDATE generations SET status='cancelled', completed_at=NOW(), error_code='CANCELLED', error_message='Cancelled by admin' WHERE id=$1", job_id)
    await log_admin_action(admin["id"], "cancel_job", "generation", str(job_id))
    return {"success": True}


@router.get("/workers")
async def admin_workers(admin: dict = Depends(require_admin)):
    pool = get_pool()
    f5 = await f5_provider().health()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tts_workers WHERE name='f5-tts'")
        queued = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE status='queued' AND engine='f5-tts'")
        avg = await conn.fetchval("SELECT COALESCE(AVG(duration),0) FROM generations WHERE status='completed' AND engine='f5-tts'")
        failed = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE status='failed' AND engine='f5-tts'")
        total = await conn.fetchval("SELECT COUNT(*) FROM generations WHERE engine='f5-tts'")
        # Sync worker row with live F5 health.
        await conn.execute(
            "UPDATE tts_workers SET status=$1, gpu=$2, model=$3, last_heartbeat=NOW(), updated_at=NOW(), total_jobs=$4, failed_jobs=$5 WHERE name='f5-tts'",
            f5.get("status", "unknown"), bool(f5.get("gpu", False)), f5.get("model", "F5-TTS"), total, failed,
        )
    return {
        "worker": {
            "name": "f5-tts", "status": f5.get("status", "unknown"), "gpu": f5.get("gpu", False),
            "model": f5.get("model", "F5-TTS"), "last_heartbeat": (row["last_heartbeat"].isoformat() if row and row.get("last_heartbeat") else None),
            "total_jobs": total, "failed_jobs": failed, "queue_length": queued, "avg_generation_time": float(avg or 0),
            "detail": f5.get("detail", ""),
        },
        "raw_health": f5,
    }


# ── AI Studio monitoring ─────────────────────────────────────

@router.get("/ai-projects/stats")
async def ai_project_stats(admin: dict = Depends(require_admin)):
    pool = get_pool()
    if not pool:
        return {"stats": {}}
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM ai_projects")
        scripts_generated = await conn.fetchval("SELECT COUNT(*) FROM ai_projects WHERE script_status='ready'")
        audio_generated = await conn.fetchval("SELECT COUNT(*) FROM ai_projects WHERE audio_status='ready'")
        processing = await conn.fetchval("SELECT COUNT(*) FROM ai_projects WHERE status IN ('generating_script','generating_audio','assembling')")
        failed = await conn.fetchval("SELECT COUNT(*) FROM ai_projects WHERE status='failed'")
        completed = await conn.fetchval("SELECT COUNT(*) FROM ai_projects WHERE status='completed'")
        avg_time = await conn.fetchval(
            "SELECT COALESCE(AVG(EXTRACT(EPOCH FROM (completed_at - created_at))),0) FROM ai_projects WHERE status='completed' AND completed_at IS NOT NULL"
        )
        total_duration = await conn.fetchval("SELECT COALESCE(SUM(actual_duration),0) FROM ai_projects WHERE status='completed'")
    return {
        "stats": {
            "total_projects": total,
            "scripts_generated": scripts_generated,
            "audio_generated": audio_generated,
            "currently_processing": processing,
            "failed_projects": failed,
            "completed_projects": completed,
            "avg_generation_time": float(avg_time or 0),
            "total_audio_duration": float(total_duration or 0),
        }
    }


@router.get("/ai-projects")
async def admin_ai_projects(admin: dict = Depends(require_admin), page: int = Query(1, ge=1),
                            limit: int = Query(30, ge=1, le=100), status: str = Query("")):
    pool = get_pool()
    if not pool:
        return {"items": [], "total": 0}
    offset = (page - 1) * limit
    where = ["1=1"]
    args = []
    if status:
        where.append(f"p.status=${len(args)+1}")
        args.append(status)
    where_sql = " AND ".join(where)
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM ai_projects p WHERE {where_sql}", *args)
        rows = await conn.fetch(
            f"""SELECT p.*, u.email AS user_email, u.username AS user_name
                FROM ai_projects p LEFT JOIN users u ON p.user_id=u.id
                WHERE {where_sql} ORDER BY p.created_at DESC LIMIT ${len(args)+1} OFFSET ${len(args)+2}""",
            *args, limit, offset,
        )
    items = []
    for r in rows:
        r = dict(r)
        items.append({
            "id": r["id"], "user": r.get("user_name") or r.get("user_email") or "",
            "user_email": r.get("user_email") or "",
            "title": r["title"], "language": r["language"],
            "target_duration": r["target_duration"], "actual_duration": r.get("actual_duration") or 0,
            "voice": r.get("voice_name") or r.get("voice_key") or "",
            "engine": r.get("engine") or "edge-tts", "tone": r.get("tone") or "",
            "status": r["status"], "script_status": r.get("script_status") or "",
            "audio_status": r.get("audio_status") or "",
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            "completed_at": r["completed_at"].isoformat() if r.get("completed_at") else None,
        })
    return {"items": items, "page": page, "limit": limit, "total": total}


@router.get("/ai-projects/{project_id}")
async def admin_ai_project_detail(project_id: int, admin: dict = Depends(require_admin)):
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not r:
            raise APIError(404, "NOT_FOUND", "Project not found.")
        r = dict(r)
        jobs = await conn.fetch("SELECT * FROM ai_project_jobs WHERE project_id=$1 ORDER BY created_at", project_id)
    from ai_studio_service import get_project_status_detail
    job_list = [{"id": j["id"], "type": j["type"], "section_id": j.get("section_id") or "",
                 "status": j["status"], "attempts": j.get("attempts") or 0,
                 "error_message": j.get("error_message") or ""} for j in jobs]
    return {
        "project": {
            "id": r["id"], "title": r["title"], "language": r["language"],
            "target_duration": r["target_duration"], "actual_duration": r.get("actual_duration") or 0,
            "voice_id": r.get("voice_id"), "voice_name": r.get("voice_name") or "",
            "engine": r.get("engine") or "edge-tts", "status": r["status"],
            "script_status": r.get("script_status") or "", "audio_status": r.get("audio_status") or "",
            "estimated_words": r.get("estimated_words") or 0,
            "final_audio_url": r.get("final_audio_url") or "",
            "error_message": r.get("error_message") or "",
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            "completed_at": r["completed_at"].isoformat() if r.get("completed_at") else None,
        },
        "jobs": job_list,
        "status_detail": get_project_status_detail(r, job_list),
    }


@router.get("/llm-status")
async def admin_llm_status(admin: dict = Depends(require_admin)):
    from llm_provider import llm_status
    status = llm_status()
    # Don't expose API keys — only configuration status
    return {"llm": status}


# ── Extended settings (includes AI/LLM/F5-TTS) ──────────────

@router.get("/logs")
async def admin_logs(admin: dict = Depends(require_admin), page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200)):
    pool = get_pool()
    if not pool:
        return {"items": [], "total": 0}
    offset = (page - 1) * limit
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM admin_logs")
        rows = await conn.fetch(
            """SELECT al.*, u.email AS admin_email FROM admin_logs al
               LEFT JOIN users u ON al.admin_id=u.id
               ORDER BY al.created_at DESC LIMIT $1 OFFSET $2""",
            limit, offset,
        )
    return {
        "items": [{"id": r["id"], "admin": r.get("admin_email") or "", "action": r["action"], "target_type": r.get("target_type") or "", "target_id": r.get("target_id") or "", "metadata": r.get("metadata") or "", "created_at": r["created_at"].isoformat() if r.get("created_at") else None} for r in rows],
        "page": page, "limit": limit, "total": total,
    }


@router.get("/settings")
async def get_settings(admin: dict = Depends(require_admin)):
    return {"settings": await load_settings(force=True)}


@router.put("/settings")
async def update_settings(request: Request, admin: dict = Depends(require_admin)):
    pool = get_pool()
    body = await request.json()
    allowed = {"max_text_length", "max_reference_audio_size", "max_reference_audio_duration", "max_voices_per_user",
               "max_generations_per_minute", "max_generations_per_day", "default_language", "default_audio_format",
               "queue_retry_count", "generation_timeout",
               # AI Studio / LLM
               "llm_provider", "llm_model", "llm_temperature", "llm_max_tokens",
               "llm_research_enabled", "llm_validation_enabled",
               "default_narration_tone", "default_wpm",
               # F5-TTS
               "f5_tts_model", "f5_tts_workers", "f5_tts_max_concurrent",
               "f5_tts_timeout", "f5_tts_retry_count", "f5_tts_chunk_size"}
    async with pool.acquire() as conn:
        for k, v in body.items():
            if k in allowed:
                await conn.execute(
                    "INSERT INTO system_settings (key,value,updated_at) VALUES ($1,$2,NOW()) ON CONFLICT (key) DO UPDATE SET value=$2, updated_at=NOW()",
                    k, str(v),
                )
    await load_settings(force=True)
    await log_admin_action(admin["id"], "update_settings", "system", "", body)
    return {"success": True}


def _gen_short(r: dict) -> dict:
    return {"id": r["id"], "voice_label": r.get("voice_label") or "", "status": r["status"],
            "engine": r.get("engine") or "", "duration": r.get("duration") or 0, "chars": r.get("chars") or 0,
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None}
