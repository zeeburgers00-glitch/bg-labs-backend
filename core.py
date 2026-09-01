"""BG LABS core: shared pool, auth, errors, settings, admin logging."""
import os
import time
import json
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import asyncpg
import jwt
from fastapi import Request, HTTPException, Depends
from fastapi.responses import JSONResponse

logger = logging.getLogger("bglabs.core")

ALGORITHM = "HS256"
SECRET_KEY = os.getenv("SECRET_KEY", "bglabs-secret-key-change-in-production")

# ── Pool ──────────────────────────────────────
_pool: Optional[asyncpg.Pool] = None


def set_pool(p: asyncpg.Pool):
    global _pool
    _pool = p


def get_pool() -> Optional[asyncpg.Pool]:
    return _pool


# ── Auth helpers ───────────────────────────────
def hash_pass(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()


def create_token(user_id: int) -> str:
    return jwt.encode({"user_id": user_id, "exp": datetime.utcnow() + timedelta(days=30)}, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[int]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]).get("user_id")
    except Exception:
        return None


def _user_from_headers(request: Request) -> Optional[dict]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    uid = decode_token(auth.replace("Bearer ", ""))
    if not uid:
        return None
    pool = get_pool()
    if not pool:
        return None
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    # This is only used as a fallback; real usage is async below
    return None


async def require_user(request: Request) -> dict:
    """Dependency: authenticated, active user."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise APIError(401, "UNAUTHENTICATED", "Authentication required.")
    uid = decode_token(auth.replace("Bearer ", ""))
    if not uid:
        raise APIError(401, "INVALID_TOKEN", "Invalid or expired token.")
    pool = get_pool()
    if not pool:
        raise APIError(503, "DB_UNAVAILABLE", "Database not available.")
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE id=$1", uid)
    if not user or not user["is_active"]:
        raise APIError(401, "USER_BLOCKED", "User not found or blocked.")
    return dict(user)


async def require_admin(user: dict = Depends(require_user)) -> dict:
    if user.get("role") not in ("admin", "super_admin"):
        raise APIError(403, "FORBIDDEN", "Admin access required.")
    return user


# ── Errors ─────────────────────────────────────
class APIError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def register_error_handler(app):
    @app.exception_handler(APIError)
    async def _handle(request: Request, exc: APIError):
        return JSONResponse(
            status_code=exc.status,
            content={"success": False, "error": {"code": exc.code, "message": exc.message}, "error_message": exc.message},
        )


# ── Settings cache ─────────────────────────────
_settings_cache: Dict[str, str] = {}
_settings_loaded = 0.0

DEFAULT_SETTINGS = {
    "max_text_length": "5000",
    "max_reference_audio_size": "10485760",        # 10MB
    "max_reference_audio_duration": "30",          # seconds
    "max_voices_per_user": "10",
    "max_generations_per_minute": "20",
    "max_generations_per_day": "200",
    "default_language": "en",
    "default_audio_format": "mp3",
    "queue_retry_count": "2",
    "generation_timeout": "180",                   # seconds
    # AI Studio / LLM settings
    "llm_provider": "openai-compatible",
    "llm_model": "gpt-4o-mini",
    "llm_temperature": "0.7",
    "llm_max_tokens": "4000",
    "llm_research_enabled": "false",
    "llm_validation_enabled": "true",
    "default_narration_tone": "documentary",
    "default_wpm": "145",
    # F5-TTS settings
    "f5_tts_model": "F5-TTS",
    "f5_tts_workers": "1",
    "f5_tts_max_concurrent": "1",
    "f5_tts_timeout": "200",
    "f5_tts_retry_count": "2",
    "f5_tts_chunk_size": "500",
}


async def load_settings(force: bool = False):
    global _settings_cache, _settings_loaded
    if not force and (time.time() - _settings_loaded) < 30 and _settings_cache:
        return _settings_cache
    pool = get_pool()
    base = dict(DEFAULT_SETTINGS)
    if pool:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT key, value FROM system_settings")
                base.update({r["key"]: r["value"] for r in rows})
        except Exception as e:
            logger.warning(f"settings load failed: {e}")
    _settings_cache = base
    _settings_loaded = time.time()
    return base


def get_setting_int(settings: dict, key: str, default: int) -> int:
    try:
        return int(settings.get(key, default))
    except (ValueError, TypeError):
        return default


# ── Admin logging ──────────────────────────────
async def log_admin_action(admin_id: int, action: str, target_type: str = "", target_id: str = "", metadata: dict = None):
    pool = get_pool()
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO admin_logs (admin_id, action, target_type, target_id, metadata) VALUES ($1,$2,$3,$4,$5)",
                admin_id, action, target_type, target_id, json.dumps(metadata or {}),
            )
    except Exception as e:
        logger.warning(f"admin log failed: {e}")
