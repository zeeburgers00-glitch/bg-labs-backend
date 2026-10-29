"""
BG LABS - media persistence
===========================

Serverless filesystems are ephemeral and a follow-up request is often served by
a different container, so generated audio/images are persisted in this order:

1. Supabase Storage (public URL)  -> survives everything, works across instances
2. local disk (``/tmp`` on Vercel) -> best effort, plus an in-process LRU cache
3. inline ``data:`` URI           -> always works for the response that created it

The history rows keep whichever URL succeeded, and fall back to the inline data
URI so old generations stay playable.
"""
from __future__ import annotations

import base64
import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("bglabs.media")

BASE_DIR = Path(__file__).resolve().parent.parent
ON_VERCEL = bool(os.getenv("VERCEL"))

STORAGE_DIR = Path(os.getenv("BGLABS_STORAGE_DIR") or ("/tmp/bglabs_storage" if ON_VERCEL else BASE_DIR / "storage"))
KINDS = {
    "audio": (STORAGE_DIR / "audio", "audio/mpeg"),
    "images": (STORAGE_DIR / "images", "image/png"),
    "videos": (STORAGE_DIR / "videos", "video/mp4"),
    "avatars": (STORAGE_DIR / "avatars", "image/svg+xml"),
    "voices": (STORAGE_DIR / "voices", "audio/mpeg"),
}

# Inline data URIs above this size are skipped (Vercel caps responses at ~4.5MB).
MAX_INLINE_BYTES = int(os.getenv("MAX_INLINE_BYTES", str(1_500_000)))

_CACHE_MAX_ENTRIES = int(os.getenv("MEDIA_CACHE_ENTRIES", "40"))
_cache: "OrderedDict[str, bytes]" = OrderedDict()


def ensure_dirs() -> None:
    for directory, _ in KINDS.values():
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:  # read-only filesystem
            pass


def _cache_put(key: str, data: bytes) -> None:
    _cache[key] = data
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)


def _cache_get(key: str) -> Optional[bytes]:
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    return None


def to_data_uri(data: bytes, content_type: str) -> Optional[str]:
    if not data or len(data) > MAX_INLINE_BYTES:
        return None
    return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"


def read_local(kind: str, filename: str) -> Optional[bytes]:
    """Read a previously generated file from disk or from the warm cache."""
    key = f"{kind}/{filename}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    directory = KINDS.get(kind, (STORAGE_DIR / kind, ""))[0]
    for candidate in (directory / filename, STORAGE_DIR / kind / filename, Path("/tmp/bglabs_storage") / kind / filename):
        try:
            if candidate.is_file():
                data = candidate.read_bytes()
                _cache_put(key, data)
                return data
        except OSError:
            continue
    return None


def write_local(kind: str, filename: str, data: bytes) -> Optional[Path]:
    directory = KINDS.get(kind, (STORAGE_DIR / kind, ""))[0]
    for target_dir in (directory, Path("/tmp/bglabs_storage") / kind):
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            path = target_dir / filename
            path.write_bytes(data)
            _cache_put(f"{kind}/{filename}", data)
            return path
        except OSError:
            continue
    # filesystem unavailable - keep it in the warm cache only
    _cache_put(f"{kind}/{filename}", data)
    return None


async def save_media(
    store: Any,
    kind: str,
    filename: str,
    data: bytes,
    content_type: Optional[str] = None,
    *,
    inline: bool = True,
) -> Dict[str, Any]:
    """Persist generated media and describe how it can be retrieved.

    Returns ``{"url", "data_uri", "stored", "bytes"}`` where ``stored`` is one of
    ``storage`` (durable), ``disk`` (ephemeral) or ``cache`` (this instance only).
    """
    directory, default_type = KINDS.get(kind, (STORAGE_DIR / kind, "application/octet-stream"))
    content_type = content_type or default_type
    result: Dict[str, Any] = {
        "url": f"/api/storage/{kind}/{filename}",
        "data_uri": None,
        "stored": "cache",
        "bytes": len(data),
    }

    # 1. durable object storage (Supabase) when the backend supports it
    upload = getattr(store, "upload_media", None)
    if upload is not None:
        try:
            public_url = await upload(kind, filename, data, content_type)
        except Exception as exc:  # never fail a generation because of storage
            logger.warning("upload_media failed: %s", exc)
            public_url = None
        if public_url:
            result["url"] = public_url
            result["stored"] = "storage"

    # 2. local disk (also warms the cache)
    if result["stored"] != "storage":
        written = write_local(kind, filename, data)
        result["stored"] = "disk" if written else "cache"

    # 3. inline data URI for the response that just generated it
    if inline:
        result["data_uri"] = to_data_uri(data, content_type)

    return result


def persistent_url_for_history(saved: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """Pick what to store in a history row: a durable URL, else the data URI."""
    if saved.get("stored") == "storage" and saved.get("url"):
        return saved["url"], None
    if saved.get("data_uri"):
        # keep the (short lived) path as well so the UI can try it first
        return saved.get("url") or "", saved["data_uri"]
    return saved.get("url") or "", None


__all__ = [
    "STORAGE_DIR",
    "KINDS",
    "MAX_INLINE_BYTES",
    "ensure_dirs",
    "read_local",
    "write_local",
    "to_data_uri",
    "save_media",
    "persistent_url_for_history",
]
