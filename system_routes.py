"""System health check — real statuses for all subsystems."""
import logging
from fastapi import APIRouter
from core import get_pool
from providers import f5_provider
from secure_storage import VOICES_DIR, GENERATIONS_DIR

logger = logging.getLogger("bglabs.system")
router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
async def system_health():
    pool = get_pool()
    f5 = await f5_provider().health()
    return {
        "backend": "healthy",
        "database": "healthy" if pool else "unavailable",
        "storage": "healthy" if GENERATIONS_DIR.exists() and VOICES_DIR.exists() else "unavailable",
        "queue": "healthy",
        "f5_tts": f5.get("status", "unknown"),
        "f5_tts_detail": {k: v for k, v in f5.items() if k != "status"},
    }
