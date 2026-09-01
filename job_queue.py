"""Generation job queue: DB-backed, single async worker, retries, timeouts, cancellation."""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import asyncpg

from core import get_pool, load_settings, get_setting_int
from providers import get_provider, TTSProviderError
from secure_storage import save_generation_audio

logger = logging.getLogger("bglabs.queue")

_worker_task: Optional[asyncio.Task] = None
_running = False


async def _claim_job(conn) -> Optional[dict]:
    row = await conn.fetchrow(
        """UPDATE generations SET status='processing', started_at=NOW()
           WHERE id = (SELECT id FROM generations WHERE status='queued'
                       ORDER BY priority DESC, created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
           RETURNING *"""
    )
    return dict(row) if row else None


async def _resolve_voice(conn, job: dict) -> dict:
    """Build the voice dict the provider expects."""
    engine = job.get("engine") or "edge-tts"
    if engine == "f5-tts" and job.get("voice_id"):
        vp = await conn.fetchrow("SELECT * FROM voice_profiles WHERE id=$1", job["voice_id"])
        if not vp:
            raise TTSProviderError("VOICE_NOT_FOUND", "Cloned voice not found.")
        return {
            "key": vp.get("voice_key") or "",
            "reference_audio_url": vp.get("reference_audio_url") or "",
            "reference_text": vp.get("reference_text") or "",
        }
    settings = json.loads(job.get("settings") or "{}") if isinstance(job.get("settings"), str) else (job.get("settings") or {})
    return {"key": settings.get("voice_key", "en-US-AriaNeural")}


async def _record_usage(conn, user_id: int, chars: int, seconds: float, failed: bool):
    today = datetime.utcnow().date()
    if failed:
        await conn.execute(
            """INSERT INTO usage (user_id, period_start, failed_count, updated_at)
               VALUES ($1,$2,1,NOW())
               ON CONFLICT (user_id, period_start) DO UPDATE
               SET failed_count = usage.failed_count + 1, updated_at = NOW()""",
            user_id, today,
        )
        return
    await conn.execute(
        """INSERT INTO usage (user_id, period_start, characters_used, audio_seconds, generation_count, updated_at)
           VALUES ($1,$2,$3,$4,1,NOW())
           ON CONFLICT (user_id, period_start) DO UPDATE
           SET characters_used = usage.characters_used + EXCLUDED.characters_used,
               audio_seconds = usage.audio_seconds + EXCLUDED.audio_seconds,
               generation_count = usage.generation_count + 1,
               updated_at = NOW()""",
        user_id, today, chars, seconds,
    )


async def _process_job(job: dict):
    pool = get_pool()
    settings = await load_settings()
    timeout = get_setting_int(settings, "generation_timeout", 180)
    max_retries = get_setting_int(settings, "queue_retry_count", 2)
    job_settings = json.loads(job.get("settings") or "{}") if isinstance(job.get("settings"), str) else (job.get("settings") or {})

    try:
        async with pool.acquire() as conn:
            voice = await _resolve_voice(conn, job)
        provider = get_provider(job.get("engine") or "edge-tts")
        try:
            audio, duration = await asyncio.wait_for(
                provider.generate(job["text"], voice, job_settings),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise TTSProviderError("GENERATION_TIMEOUT", "Generation timed out.")
        ext = ".mp3" if job.get("engine") != "f5-tts" else ".wav"
        fname = save_generation_audio(audio, ext)
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE generations SET status='completed', audio_url=$1, duration=$2, completed_at=NOW(),
                   error_code='', error_message='' WHERE id=$3""",
                f"/api/storage/generations/{fname}", float(duration or 0), job["id"],
            )
            await _record_usage(conn, job["user_id"], job.get("chars", 0), float(duration or 0), failed=False)
            await conn.execute("UPDATE users SET total_used = total_used + $1 WHERE id=$2", job.get("chars", 0), job["user_id"])
        logger.info(f"Job {job['id']} completed")
    except TTSProviderError as e:
        await _fail_job(job, e.code, e.message, max_retries)
    except Exception as e:
        await _fail_job(job, "GENERATION_FAILED", str(e), max_retries)


async def _fail_job(job: dict, code: str, message: str, max_retries: int):
    pool = get_pool()
    retry = (job.get("retry_count") or 0) + 1
    async with pool.acquire() as conn:
        if retry <= max_retries:
            await conn.execute(
                "UPDATE generations SET status='queued', retry_count=$1, error_code=$2, error_message=$3 WHERE id=$4",
                retry, code, message, job["id"],
            )
            logger.warning(f"Job {job['id']} failed ({code}) — retry {retry}/{max_retries}")
        else:
            await conn.execute(
                """UPDATE generations SET status='failed', error_code=$1, error_message=$2,
                   completed_at=NOW(), retry_count=$3 WHERE id=$4""",
                code, message, retry, job["id"],
            )
            await _record_usage(conn, job["user_id"], 0, 0, failed=True)
            logger.error(f"Job {job['id']} permanently failed: {code} — {message}")


async def _recover_stale():
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE generations SET status='failed', error_code='STALE_RECOVERY',
                   error_message='Worker died mid-processing', completed_at=NOW()
                   WHERE status='processing' AND started_at < NOW() - INTERVAL '15 minutes'"""
            )
            # Bump F5 worker heartbeat on startup.
            await conn.execute(
                "UPDATE tts_workers SET last_heartbeat=NOW() WHERE name='f5-tts'"
            )
    except Exception as e:
        logger.warning(f"stale recovery failed: {e}")


async def _worker_loop():
    global _running
    _running = True
    await _recover_stale()
    logger.info("Generation worker started")
    while _running:
        pool = get_pool()
        if not pool:
            await asyncio.sleep(2)
            continue
        try:
            async with pool.acquire() as conn:
                job = await _claim_job(conn)
            if job:
                await _process_job(job)
            else:
                await asyncio.sleep(1.0)
        except Exception as e:
            logger.error(f"worker loop error: {e}")
            await asyncio.sleep(2)


def start_worker():
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop())


def stop_worker():
    global _running
    _running = False
