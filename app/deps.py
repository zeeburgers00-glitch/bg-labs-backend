"""
BG LABS - shared dependencies
=============================

Password hashing, JWT issuing/verification, the current-user dependency and the
in-memory rate limiter. Kept free of heavy imports so it works both in a
serverless function and in a long running container.

Passwords use PBKDF2-HMAC-SHA256 from the standard library (salted, 210k
iterations). Legacy ``sha256$...``/bare hex hashes written by older versions of
this app still verify, so existing accounts keep working.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import jwt
from fastapi import HTTPException, Request

from app.store import get_store

logger = logging.getLogger("bglabs.deps")

SECRET_KEY = os.getenv("SECRET_KEY") or os.getenv("BGLABS_SECRET_KEY") or "bglabs-secret-key-change-in-production"
ALGORITHM = "HS256"
TOKEN_TTL_DAYS = int(os.getenv("TOKEN_TTL_DAYS", "30"))

PBKDF2_ITERATIONS = 210_000

# ------------------------------------------------------------ rate limiting
_rate_limits: Dict[str, List[float]] = defaultdict(list)
RATE_LIMIT_GENERATE = int(os.getenv("RATE_LIMIT_GENERATE", "30"))
RATE_LIMIT_AUTH = int(os.getenv("RATE_LIMIT_AUTH", "10"))
RATE_LIMIT_IMAGE = int(os.getenv("RATE_LIMIT_IMAGE", "10"))


def check_rate_limit(ip: str, action: str = "generate", limit: int = 30, window: int = 60) -> bool:
    """Sliding-window per-IP limiter (per instance, which is fine for abuse control)."""
    now = time.time()
    key = f"{ip}:{action}"
    bucket = [t for t in _rate_limits[key] if now - t < window]
    if len(bucket) >= limit:
        _rate_limits[key] = bucket
        return False
    bucket.append(now)
    _rate_limits[key] = bucket
    return True


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    parts = stored.split("$")
    if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
        try:
            iterations = int(parts[1])
            digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(parts[2]), iterations).hex()
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(digest, parts[3])
    # legacy: plain sha256 hex (what older BG LABS builds stored)
    legacy = hashlib.sha256(password.encode()).hexdigest()
    return hmac.compare_digest(legacy, stored)


def needs_rehash(stored: str) -> bool:
    return not (stored or "").startswith("pbkdf2_sha256$")


# Backwards compatible aliases used by the older modules in this repo.
hash_pass = hash_password
verify_pass = verify_password


# -------------------------------------------------------------------- tokens
def create_token(user_id: int, role: str = "user") -> str:
    payload = {
        "user_id": int(user_id),
        "sub": str(user_id),
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_TTL_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    user_id = payload.get("user_id") or payload.get("sub")
    try:
        return int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        return None


# -------------------------------------------------------------- dependencies
async def get_current_user(request: Request) -> Dict[str, Any]:
    """Resolve the bearer token into a normalised user dict."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="No token provided")
    user_id = decode_token(auth[7:].strip())
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    store = await get_store()
    user = await store.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account blocked")
    return user


async def get_optional_user(request: Request) -> Optional[Dict[str, Any]]:
    """Like :func:`get_current_user` but returns ``None`` instead of raising."""
    if not request.headers.get("authorization"):
        return None
    try:
        return await get_current_user(request)
    except HTTPException:
        return None


async def require_admin(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """The user shape the frontend expects (never leaks the password hash)."""
    return {
        "id": user.get("id"),
        "email": user.get("email", ""),
        "username": user.get("username", ""),
        "full_name": user.get("full_name", ""),
        "role": user.get("role", "user"),
        "is_active": bool(user.get("is_active", True)),
        "credits": user.get("credits", 0),
        "total_credits_used": user.get("total_used", 0),
        "referral_code": user.get("referral_code", ""),
        "created_at": user.get("created_at"),
    }


__all__ = [
    "SECRET_KEY",
    "ALGORITHM",
    "RATE_LIMIT_GENERATE",
    "RATE_LIMIT_AUTH",
    "RATE_LIMIT_IMAGE",
    "check_rate_limit",
    "get_client_ip",
    "hash_password",
    "verify_password",
    "needs_rehash",
    "hash_pass",
    "verify_pass",
    "create_token",
    "decode_token",
    "get_current_user",
    "get_optional_user",
    "require_admin",
    "public_user",
]
