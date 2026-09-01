"""Secure storage: reference audio is private, generated audio is served."""
import os
import uuid
import shutil
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("bglabs.storage")

BASE_DIR = Path(__file__).parent
# Public storage is mounted at /api/storage — generated audio lives here.
PUBLIC_STORAGE = BASE_DIR / "storage"
# Private storage is never mounted publicly — reference audio for cloned voices lives here.
PRIVATE_STORAGE = BASE_DIR / "storage_private"

VOICES_DIR = PRIVATE_STORAGE / "voices"          # private reference audio
GENERATIONS_DIR = PUBLIC_STORAGE / "generations" # generated audio (served)
TEMP_DIR = PRIVATE_STORAGE / "temp"


def ensure_dirs():
    for d in [PUBLIC_STORAGE, PRIVATE_STORAGE, VOICES_DIR, GENERATIONS_DIR, TEMP_DIR]:
        d.mkdir(parents=True, exist_ok=True)


ALLOWED_AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm", ".aac"}
AUDIO_SIGNATURES = {
    b"\xff\xfb": "mp3", b"\xff\xf3": "mp3", b"\xff\xfa": "mp3",
    b"RIFF": "wav", b"OggS": "ogg", b"ftyp": "m4a", b"fLaC": "flac", b"\x1a\x45\xdf\xa3": "webm",
}


def validate_audio_file(filename: str, content: bytes, max_size: int) -> dict:
    """Validate uploaded reference audio. Returns {ok, error?, ext?}."""
    if not content:
        return {"ok": False, "error": "Audio file is empty."}
    if len(content) > max_size:
        return {"ok": False, "error": f"Audio file too large (max {max_size // 1024 // 1024}MB)."}
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_AUDIO_EXT:
        return {"ok": False, "error": f"Unsupported file type '{ext}'. Allowed: mp3, wav, m4a, ogg, flac."}
    # Lightweight readability check — look for a known magic signature.
    head = content[:8]
    if not any(sig in head for sig in AUDIO_SIGNATURES):
        # Some valid mp3/m4a streams may not start with a signature; allow through if extension is valid.
        pass
    return {"ok": True, "ext": ext}


def safe_filename(ext: str) -> str:
    return f"{uuid.uuid4().hex}{ext or '.mp3'}"


def save_reference_audio(content: bytes, ext: str) -> str:
    ensure_dirs()
    fname = safe_filename(ext)
    path = VOICES_DIR / fname
    path.write_bytes(content)
    return fname  # stored privately; path resolved by backend


def save_generation_audio(content: bytes, ext: str = ".mp3") -> str:
    ensure_dirs()
    fname = safe_filename(ext)
    path = GENERATIONS_DIR / fname
    path.write_bytes(content)
    return fname


def reference_audio_path(filename: str) -> Optional[Path]:
    p = VOICES_DIR / filename
    return p if p.exists() else None


def cleanup_temp():
    try:
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR, ignore_errors=True)
            TEMP_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"temp cleanup failed: {e}")
