"""
BG LABS - Unified data store
============================

One small persistence interface used by every route, with three interchangeable
backends so the same code runs on Vercel, on Render/Docker, or with no database
at all:

  * ``supabase`` - Supabase PostgREST (+ Supabase Storage for generated media).
                   Needs ``SUPABASE_URL`` and ``SUPABASE_SERVICE_KEY``.
                   This is the default for the Vercel deployment because a
                   serverless function cannot hold a long lived DB pool.
  * ``postgres`` - any PostgreSQL via asyncpg (Neon, Supabase direct, local...).
                   Needs ``DATABASE_URL``.
  * ``memory``   - ephemeral, per instance. Used as a last resort so the API
                   never hard-fails; data is lost when the instance recycles.

Rows are normalised to plain dicts with a stable shape (see ``_norm_*``) so the
route layer never has to care which backend answered.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

logger = logging.getLogger("bglabs.store")

# ---------------------------------------------------------------- table names
T_USERS = "bglabs_users"
T_AUDIO = "bglabs_audio"
T_IMAGES = "bglabs_images"
T_VOICES = "bglabs_voices"
T_PROJECTS = "bglabs_projects"

ALL_TABLES = (T_USERS, T_AUDIO, T_IMAGES, T_VOICES, T_PROJECTS)


class StoreError(Exception):
    """Backend level failure (network, permissions, bad query...)."""

    def __init__(self, message: str, code: Optional[str] = None, status: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class DuplicateError(StoreError):
    """Unique constraint violation (email / username already taken)."""


# ------------------------------------------------------------------- helpers
def _iso(value: Any) -> str:
    """Normalise timestamps to ISO-8601 strings (JSON friendly)."""
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("t", "true", "1", "yes")
    return bool(value)


def _json(value: Any, default: Any = None) -> Any:
    if value is None:
        return default if default is not None else {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default if default is not None else {}


def _norm_user(row: Dict[str, Any]) -> Dict[str, Any]:
    """Shape consumed by the auth helpers and /api/auth/* responses."""
    return {
        "id": _int(row.get("id")),
        "email": row.get("email") or "",
        "username": row.get("username") or "",
        "full_name": row.get("full_name") or "",
        "password_hash": row.get("password_hash") or "",
        "role": row.get("role") or "user",
        "is_active": _bool(row.get("is_active"), True),
        "credits": _int(row.get("credits"), 999999),
        "total_used": _int(row.get("total_used"), 0),
        "referral_code": row.get("referral_code") or "",
        "referred_by": row.get("referred_by"),
        "created_at": _iso(row.get("created_at")),
    }


def _norm_audio(row: Dict[str, Any]) -> Dict[str, Any]:
    text = row.get("text") or ""
    return {
        "id": _int(row.get("id")),
        "user_id": _int(row.get("user_id")),
        "text": text,
        # the frontend renders `text_content`
        "text_content": row.get("text_content") or text,
        "voice": row.get("voice") or "",
        "engine": row.get("engine") or "Edge-TTS",
        "filename": row.get("filename") or "",
        "url": row.get("url") or "",
        "data_uri": row.get("data_uri") or "",
        "chars": _int(row.get("chars")),
        "created_at": _iso(row.get("created_at")),
    }


def _norm_image(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": _int(row.get("id")),
        "user_id": _int(row.get("user_id")),
        "prompt": row.get("prompt") or "",
        "style": row.get("style") or "",
        "model": row.get("model") or "",
        "size": row.get("size") or "",
        "filename": row.get("filename") or "",
        "url": row.get("url") or "",
        "data_uri": row.get("data_uri") or "",
        "created_at": _iso(row.get("created_at")),
    }


def _norm_voice(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": _int(row.get("id")),
        "user_id": _int(row.get("user_id")),
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "voice_key": row.get("voice_key") or "",
        "base_voice": row.get("base_voice") or "en-US-AriaNeural",
        "sample_url": row.get("sample_url") or "",
        "settings": _json(row.get("settings"), {}),
        "created_at": _iso(row.get("created_at")),
    }


def _norm_project(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": _int(row.get("id")),
        "user_id": _int(row.get("user_id")),
        "name": row.get("name") or "",
        "project_type": row.get("project_type") or "",
        "settings": _json(row.get("settings"), {}),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at") or row.get("created_at")),
    }


def _prepare_pg_dsn(url: str) -> tuple[str, bool]:
    """asyncpg does not understand every libpq DSN keyword.

    ``sslmode`` is stripped out and translated into the ``ssl`` argument, which
    keeps Neon/Supabase style connection strings working.
    """
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query))
    ssl = False
    sslmode = params.pop("sslmode", None)
    if sslmode and sslmode != "disable":
        ssl = True
    params.pop("channel_binding", None)
    query = urlencode(params)
    clean = urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    return clean, ssl


# =========================================================== Supabase backend
class SupabaseStore:
    """PostgREST + Storage backend (works great from serverless functions)."""

    name = "supabase"

    def __init__(self, url: str, key: str, bucket: str = "bglabs-media"):
        self.base = url.rstrip("/")
        self.key = key
        self.bucket = bucket
        self.rest = f"{self.base}/rest/v1"
        self.storage = f"{self.base}/storage/v1"
        self.detail = f"PostgREST @ {self.base}"
        self._client: Optional[httpx.AsyncClient] = None
        self.storage_ok: Optional[bool] = None

    # -- plumbing ---------------------------------------------------------
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=10.0))
        return self._client

    def _headers(self, prefer: Optional[str] = None, content_type: Optional[str] = "application/json") -> Dict[str, str]:
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        if prefer:
            headers["Prefer"] = prefer
        return headers

    async def _send(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        payload: Any = None,
        raw: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        expect: tuple = (200, 201, 204),
    ) -> httpx.Response:
        try:
            resp = await self.client.request(
                method,
                url,
                params=params,
                json=payload if raw is None else None,
                content=raw,
                headers=headers or self._headers(),
            )
        except httpx.HTTPError as exc:  # network / timeout
            raise StoreError(f"Supabase request failed: {exc}") from exc

        if resp.status_code in expect:
            return resp

        code, message = None, resp.text[:300]
        try:
            body = resp.json()
            code = body.get("code")
            message = body.get("message") or body.get("error") or message
        except (ValueError, AttributeError):
            pass
        err = StoreError(f"{method} {url} -> {resp.status_code}: {message}", code=code, status=resp.status_code)
        if code == "23505":
            raise DuplicateError(message, code=code, status=resp.status_code) from None
        if code == "42P01":
            raise StoreError(
                f"Table missing in Supabase ({message}). Run the schema setup again.",
                code=code,
                status=resp.status_code,
            ) from None
        raise err

    async def _select(self, table: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        query = {"select": "*", **params}
        resp = await self._send("GET", f"{self.rest}/{table}", params=query)
        try:
            return resp.json() or []
        except ValueError:
            return []

    async def _insert(self, table: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        resp = await self._send(
            "POST",
            f"{self.rest}/{table}",
            payload=payload,
            headers=self._headers("return=representation"),
            expect=(200, 201),
        )
        try:
            rows = resp.json()
        except ValueError:
            return None
        if isinstance(rows, list):
            return rows[0] if rows else None
        return rows

    async def _update(self, table: str, params: Dict[str, Any], payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        resp = await self._send(
            "PATCH",
            f"{self.rest}/{table}",
            params=params,
            payload=payload,
            headers=self._headers("return=representation"),
            expect=(200, 204),
        )
        try:
            rows = resp.json()
        except ValueError:
            return None
        if isinstance(rows, list):
            return rows[0] if rows else None
        return rows

    async def _delete(self, table: str, params: Dict[str, Any]) -> int:
        resp = await self._send(
            "DELETE",
            f"{self.rest}/{table}",
            params=params,
            headers=self._headers("return=representation"),
            expect=(200, 204),
        )
        try:
            rows = resp.json()
            return len(rows) if isinstance(rows, list) else 0
        except ValueError:
            return 0

    async def _count(self, table: str, params: Optional[Dict[str, Any]] = None) -> int:
        headers = self._headers("count=exact")
        headers["Range"] = "0-0"
        query = {"select": "id", **(params or {})}
        try:
            resp = await self._send("GET", f"{self.rest}/{table}", params=query, headers=headers)
        except StoreError:
            return 0
        content_range = resp.headers.get("content-range", "")
        if "/" in content_range:
            return _int(content_range.split("/")[-1])
        try:
            return len(resp.json() or [])
        except ValueError:
            return 0

    @staticmethod
    def _or_field(field: str, values: List[str]) -> Dict[str, str]:
        safe = [v for v in values if v and not any(c in v for c in ",()")]
        if len(safe) != len(values):
            return {}
        return {"or": "(" + ",".join(f"{field}.eq.{v}" for v in safe) + ")"}

    # -- lifecycle --------------------------------------------------------
    async def init(self) -> None:
        await self._select(T_USERS, {"limit": 1})
        logger.info("Supabase store ready (%s)", self.detail)

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    def status(self) -> Dict[str, Any]:
        return {"backend": self.name, "detail": self.detail, "storage": self.storage_ok}

    # -- users ------------------------------------------------------------
    async def create_user(self, *, email: str, username: str, password_hash: str,
                          full_name: str = "", role: str = "user",
                          referral_code: Optional[str] = None,
                          referred_by: Optional[int] = None) -> Dict[str, Any]:
        payload = {
            "email": email,
            "username": username,
            "full_name": full_name or "",
            "password_hash": password_hash,
            "role": role,
            "is_active": True,
            "credits": 999999,
            "total_used": 0,
            "referral_code": referral_code,
            "referred_by": referred_by,
        }
        row = await self._insert(T_USERS, payload)
        if not row:
            raise StoreError("User insert returned no row")
        return _norm_user(row)

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        rows = await self._select(T_USERS, {"id": f"eq.{_int(user_id)}", "limit": 1})
        return _norm_user(rows[0]) if rows else None

    async def get_user_by_login(self, identifier: str) -> Optional[Dict[str, Any]]:
        identifier = (identifier or "").strip()
        if not identifier:
            return None
        if self._or_field("username", [identifier]):
            params = {"or": f"(username.eq.{identifier},email.eq.{identifier})", "limit": 1}
            rows = await self._select(T_USERS, params)
            if rows:
                return _norm_user(rows[0])
            return None
        # identifier contains characters PostgREST would misread in an `or` group
        for column in ("username", "email"):
            rows = await self._select(T_USERS, {column: f"eq.{identifier}", "limit": 1})
            if rows:
                return _norm_user(rows[0])
        return None

    async def get_user_by_referral(self, code: str) -> Optional[Dict[str, Any]]:
        rows = await self._select(T_USERS, {"referral_code": f"eq.{code}", "limit": 1})
        return _norm_user(rows[0]) if rows else None

    async def update_user(self, user_id: int, **fields: Any) -> Optional[Dict[str, Any]]:
        if not fields:
            return await self.get_user(user_id)
        row = await self._update(T_USERS, {"id": f"eq.{_int(user_id)}"}, fields)
        return _norm_user(row) if row else None

    async def add_usage(self, user_id: int, amount: int) -> None:
        if amount <= 0:
            return
        user = await self.get_user(user_id)
        if not user:
            return
        await self._update(
            T_USERS,
            {"id": f"eq.{_int(user_id)}"},
            {"total_used": user["total_used"] + amount},
        )

    async def list_users(self, limit: int = 200) -> List[Dict[str, Any]]:
        rows = await self._select(T_USERS, {"order": "id.desc", "limit": limit})
        return [_norm_user(r) for r in rows]

    async def count_users(self, active_only: bool = False) -> int:
        params = {"is_active": "eq.true"} if active_only else {}
        return await self._count(T_USERS, params)

    async def list_referrals(self, user_id: int) -> List[Dict[str, Any]]:
        rows = await self._select(T_USERS, {"referred_by": f"eq.{_int(user_id)}", "order": "id.desc", "limit": 100})
        return [_norm_user(r) for r in rows]

    # -- audio ------------------------------------------------------------
    async def add_audio(self, *, user_id: int, text: str, voice: str, engine: str,
                        filename: str, url: str, chars: int = 0,
                        data_uri: Optional[str] = None) -> Optional[Dict[str, Any]]:
        row = await self._insert(T_AUDIO, {
            "user_id": _int(user_id), "text": text, "voice": voice, "engine": engine,
            "filename": filename, "url": url, "chars": _int(chars), "data_uri": data_uri,
        })
        return _norm_audio(row) if row else None

    async def list_audio(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        rows = await self._select(T_AUDIO, {
            "user_id": f"eq.{_int(user_id)}", "order": "created_at.desc,id.desc", "limit": limit,
        })
        return [_norm_audio(r) for r in rows]

    async def get_audio(self, audio_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        rows = await self._select(T_AUDIO, {"id": f"eq.{_int(audio_id)}", "user_id": f"eq.{_int(user_id)}", "limit": 1})
        return _norm_audio(rows[0]) if rows else None

    async def delete_audio(self, audio_id: int, user_id: int) -> bool:
        return await self._delete(T_AUDIO, {"id": f"eq.{_int(audio_id)}", "user_id": f"eq.{_int(user_id)}"}) > 0

    async def count_audio(self, user_id: Optional[int] = None) -> int:
        params = {"user_id": f"eq.{_int(user_id)}"} if user_id else None
        return await self._count(T_AUDIO, params)

    # -- images -----------------------------------------------------------
    async def add_image(self, *, user_id: int, prompt: str, style: str, filename: str, url: str,
                        model: str = "", size: str = "", data_uri: Optional[str] = None) -> Optional[Dict[str, Any]]:
        row = await self._insert(T_IMAGES, {
            "user_id": _int(user_id), "prompt": prompt, "style": style, "model": model,
            "size": size, "filename": filename, "url": url, "data_uri": data_uri,
        })
        return _norm_image(row) if row else None

    async def list_images(self, user_id: int, limit: int = 60) -> List[Dict[str, Any]]:
        rows = await self._select(T_IMAGES, {
            "user_id": f"eq.{_int(user_id)}", "order": "created_at.desc,id.desc", "limit": limit,
        })
        return [_norm_image(r) for r in rows]

    async def delete_image(self, image_id: int, user_id: int) -> bool:
        return await self._delete(T_IMAGES, {"id": f"eq.{_int(image_id)}", "user_id": f"eq.{_int(user_id)}"}) > 0

    async def count_images(self, user_id: Optional[int] = None) -> int:
        params = {"user_id": f"eq.{_int(user_id)}"} if user_id else None
        return await self._count(T_IMAGES, params)

    # -- custom voices ----------------------------------------------------
    async def add_voice(self, *, user_id: int, name: str, description: str = "",
                        voice_key: Optional[str] = None, base_voice: str = "en-US-AriaNeural",
                        sample_url: Optional[str] = None, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        row = await self._insert(T_VOICES, {
            "user_id": _int(user_id), "name": name, "description": description or "",
            "voice_key": voice_key, "base_voice": base_voice, "sample_url": sample_url,
            "settings": settings or {},
        })
        if not row:
            raise StoreError("Voice insert returned no row")
        return _norm_voice(row)

    async def list_voices(self, user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        rows = await self._select(T_VOICES, {"user_id": f"eq.{_int(user_id)}", "order": "created_at.desc", "limit": limit})
        return [_norm_voice(r) for r in rows]

    async def get_voice(self, voice_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        rows = await self._select(T_VOICES, {"id": f"eq.{_int(voice_id)}", "user_id": f"eq.{_int(user_id)}", "limit": 1})
        return _norm_voice(rows[0]) if rows else None

    async def delete_voice(self, key: str, user_id: int) -> bool:
        key = str(key)
        params = {"user_id": f"eq.{_int(user_id)}"}
        if key.isdigit():
            params["id"] = f"eq.{key}"
        else:
            params["or"] = f"(voice_key.eq.{key},name.eq.{key})"
        return await self._delete(T_VOICES, params) > 0

    async def count_voices(self) -> int:
        return await self._count(T_VOICES)

    # -- projects ---------------------------------------------------------
    async def add_project(self, *, user_id: int, name: str, project_type: str,
                          settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        row = await self._insert(T_PROJECTS, {
            "user_id": _int(user_id), "name": name, "project_type": project_type,
            "settings": settings or {},
        })
        if not row:
            raise StoreError("Project insert returned no row")
        return _norm_project(row)

    async def get_project(self, project_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        rows = await self._select(T_PROJECTS, {
            "id": f"eq.{_int(project_id)}", "user_id": f"eq.{_int(user_id)}", "limit": 1,
        })
        return _norm_project(rows[0]) if rows else None

    async def list_projects(self, user_id: int, project_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"user_id": f"eq.{_int(user_id)}", "order": "created_at.desc,id.desc", "limit": limit}
        if project_type:
            params["project_type"] = f"eq.{project_type}"
        rows = await self._select(T_PROJECTS, params)
        return [_norm_project(r) for r in rows]

    async def update_project(self, project_id: int, user_id: int, *,
                             name: Optional[str] = None,
                             settings: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if name is not None:
            payload["name"] = name
        if settings is not None:
            payload["settings"] = settings
        row = await self._update(T_PROJECTS, {"id": f"eq.{_int(project_id)}", "user_id": f"eq.{_int(user_id)}"}, payload)
        return _norm_project(row) if row else None

    async def delete_project(self, project_id: int, user_id: int) -> bool:
        return await self._delete(T_PROJECTS, {"id": f"eq.{_int(project_id)}", "user_id": f"eq.{_int(user_id)}"}) > 0

    async def count_projects(self, user_id: Optional[int] = None) -> int:
        params = {"user_id": f"eq.{_int(user_id)}"} if user_id else None
        return await self._count(T_PROJECTS, params)

    # -- media ------------------------------------------------------------
    async def upload_media(self, folder: str, filename: str, data: bytes, content_type: str) -> Optional[str]:
        """Upload generated media to Supabase Storage; returns a public URL."""
        path = f"{folder.strip('/')}/{filename}"
        headers = self._headers(content_type=content_type)
        headers["x-upsert"] = "true"
        try:
            await self._send(
                "POST",
                f"{self.storage}/object/{self.bucket}/{path}",
                raw=data,
                headers=headers,
                expect=(200, 201),
            )
        except StoreError as exc:
            self.storage_ok = False
            logger.warning("Supabase Storage upload failed (%s/%s): %s", folder, filename, exc)
            return None
        self.storage_ok = True
        return f"{self.storage}/object/public/{self.bucket}/{path}"


# =========================================================== Postgres backend
class PostgresStore:
    """asyncpg backend - keeps the original Neon/Render deployment path alive."""

    name = "postgres"

    DDL = f"""
    CREATE TABLE IF NOT EXISTS {T_USERS} (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        username TEXT UNIQUE NOT NULL,
        full_name TEXT DEFAULT '',
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        is_active BOOLEAN DEFAULT TRUE,
        credits INTEGER DEFAULT 999999,
        total_used INTEGER DEFAULT 0,
        referral_code TEXT,
        referred_by BIGINT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS {T_AUDIO} (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        user_id BIGINT NOT NULL,
        text TEXT,
        voice TEXT,
        engine TEXT DEFAULT 'Edge-TTS',
        filename TEXT,
        url TEXT,
        data_uri TEXT,
        chars INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS {T_IMAGES} (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        user_id BIGINT NOT NULL,
        prompt TEXT,
        style TEXT,
        model TEXT,
        size TEXT,
        filename TEXT,
        url TEXT,
        data_uri TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS {T_VOICES} (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        user_id BIGINT NOT NULL,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        voice_key TEXT,
        base_voice TEXT DEFAULT 'en-US-AriaNeural',
        sample_url TEXT,
        settings JSONB DEFAULT '{{}}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS {T_PROJECTS} (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        user_id BIGINT NOT NULL,
        name TEXT NOT NULL,
        project_type TEXT DEFAULT 'script',
        settings JSONB DEFAULT '{{}}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS bglabs_audio_user_idx ON {T_AUDIO} (user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS bglabs_images_user_idx ON {T_IMAGES} (user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS bglabs_voices_user_idx ON {T_VOICES} (user_id);
    CREATE INDEX IF NOT EXISTS bglabs_projects_user_idx ON {T_PROJECTS} (user_id, project_type, created_at DESC);
    """

    def __init__(self, dsn: str):
        self.dsn, self.ssl = _prepare_pg_dsn(dsn)
        host = urlsplit(self.dsn).hostname or ""
        self.detail = f"postgresql @ {host}"
        self.pool = None

    async def init(self) -> None:
        import asyncpg  # imported lazily so the dependency stays optional

        self.pool = await asyncpg.create_pool(
            self.dsn,
            min_size=1,
            max_size=int(os.getenv("BGLABS_PG_POOL_MAX", "3")),
            ssl="require" if self.ssl else None,
            # serverless pools are short lived and many poolers (PgBouncer /
            # Supavisor transaction mode) reject prepared statements.
            statement_cache_size=0,
            timeout=20,
        )
        async with self.pool.acquire() as conn:
            await conn.execute(self.DDL)
        logger.info("Postgres store ready (%s)", self.detail)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()

    def status(self) -> Dict[str, Any]:
        return {"backend": self.name, "detail": self.detail, "storage": False}

    async def _fetchrow(self, sql: str, *args: Any) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, *args)
        return dict(row) if row else None

    async def _fetch(self, sql: str, *args: Any) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]

    async def _execute(self, sql: str, *args: Any) -> str:
        async with self.pool.acquire() as conn:
            return await conn.execute(sql, *args)

    async def _fetchval(self, sql: str, *args: Any) -> Any:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(sql, *args)

    # -- users ------------------------------------------------------------
    async def create_user(self, *, email: str, username: str, password_hash: str,
                          full_name: str = "", role: str = "user",
                          referral_code: Optional[str] = None,
                          referred_by: Optional[int] = None) -> Dict[str, Any]:
        try:
            row = await self._fetchrow(
                f"""INSERT INTO {T_USERS}
                    (email, username, full_name, password_hash, role, referral_code, referred_by)
                    VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *""",
                email, username, full_name or "", password_hash, role, referral_code, referred_by,
            )
        except Exception as exc:  # asyncpg.UniqueViolationError
            if "23505" in str(getattr(exc, "sqlstate", "")) or "duplicate key" in str(exc):
                raise DuplicateError("Email or username already exists") from None
            raise StoreError(str(exc)) from None
        if not row:
            raise StoreError("User insert returned no row")
        return _norm_user(row)

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        row = await self._fetchrow(f"SELECT * FROM {T_USERS} WHERE id=$1", _int(user_id))
        return _norm_user(row) if row else None

    async def get_user_by_login(self, identifier: str) -> Optional[Dict[str, Any]]:
        identifier = (identifier or "").strip()
        if not identifier:
            return None
        row = await self._fetchrow(
            f"SELECT * FROM {T_USERS} WHERE username=$1 OR email=$1 LIMIT 1", identifier
        )
        return _norm_user(row) if row else None

    async def get_user_by_referral(self, code: str) -> Optional[Dict[str, Any]]:
        row = await self._fetchrow(f"SELECT * FROM {T_USERS} WHERE referral_code=$1 LIMIT 1", code)
        return _norm_user(row) if row else None

    async def update_user(self, user_id: int, **fields: Any) -> Optional[Dict[str, Any]]:
        allowed = {"email", "username", "full_name", "role", "is_active", "credits",
                   "total_used", "referral_code", "referred_by", "password_hash"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return await self.get_user(user_id)
        assignments = ", ".join(f"{k}=${i + 2}" for i, k in enumerate(sets))
        args = [_int(user_id), *sets.values()]
        row = await self._fetchrow(
            f"UPDATE {T_USERS} SET {assignments} WHERE id=$1 RETURNING *", *args
        )
        return _norm_user(row) if row else None

    async def add_usage(self, user_id: int, amount: int) -> None:
        if amount <= 0:
            return
        await self._execute(
            f"UPDATE {T_USERS} SET total_used = total_used + $1 WHERE id=$2",
            _int(amount), _int(user_id),
        )

    async def list_users(self, limit: int = 200) -> List[Dict[str, Any]]:
        rows = await self._fetch(f"SELECT * FROM {T_USERS} ORDER BY id DESC LIMIT $1", _int(limit))
        return [_norm_user(r) for r in rows]

    async def count_users(self, active_only: bool = False) -> int:
        sql = f"SELECT COUNT(*) FROM {T_USERS}"
        if active_only:
            sql += " WHERE is_active"
        return _int(await self._fetchval(sql))

    async def list_referrals(self, user_id: int) -> List[Dict[str, Any]]:
        rows = await self._fetch(
            f"SELECT * FROM {T_USERS} WHERE referred_by=$1 ORDER BY id DESC LIMIT 100", _int(user_id)
        )
        return [_norm_user(r) for r in rows]

    # -- audio ------------------------------------------------------------
    async def add_audio(self, *, user_id: int, text: str, voice: str, engine: str,
                        filename: str, url: str, chars: int = 0,
                        data_uri: Optional[str] = None) -> Optional[Dict[str, Any]]:
        row = await self._fetchrow(
            f"""INSERT INTO {T_AUDIO} (user_id, text, voice, engine, filename, url, chars, data_uri)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *""",
            _int(user_id), text, voice, engine, filename, url, _int(chars), data_uri,
        )
        return _norm_audio(row) if row else None

    async def list_audio(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        rows = await self._fetch(
            f"SELECT * FROM {T_AUDIO} WHERE user_id=$1 ORDER BY created_at DESC, id DESC LIMIT $2",
            _int(user_id), _int(limit),
        )
        return [_norm_audio(r) for r in rows]

    async def get_audio(self, audio_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        row = await self._fetchrow(
            f"SELECT * FROM {T_AUDIO} WHERE id=$1 AND user_id=$2", _int(audio_id), _int(user_id)
        )
        return _norm_audio(row) if row else None

    async def delete_audio(self, audio_id: int, user_id: int) -> bool:
        result = await self._execute(
            f"DELETE FROM {T_AUDIO} WHERE id=$1 AND user_id=$2", _int(audio_id), _int(user_id)
        )
        return not result.endswith("0")

    async def count_audio(self, user_id: Optional[int] = None) -> int:
        if user_id:
            return _int(await self._fetchval(f"SELECT COUNT(*) FROM {T_AUDIO} WHERE user_id=$1", _int(user_id)))
        return _int(await self._fetchval(f"SELECT COUNT(*) FROM {T_AUDIO}"))

    # -- images -----------------------------------------------------------
    async def add_image(self, *, user_id: int, prompt: str, style: str, filename: str, url: str,
                        model: str = "", size: str = "", data_uri: Optional[str] = None) -> Optional[Dict[str, Any]]:
        row = await self._fetchrow(
            f"""INSERT INTO {T_IMAGES} (user_id, prompt, style, model, size, filename, url, data_uri)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *""",
            _int(user_id), prompt, style, model, size, filename, url, data_uri,
        )
        return _norm_image(row) if row else None

    async def list_images(self, user_id: int, limit: int = 60) -> List[Dict[str, Any]]:
        rows = await self._fetch(
            f"SELECT * FROM {T_IMAGES} WHERE user_id=$1 ORDER BY created_at DESC, id DESC LIMIT $2",
            _int(user_id), _int(limit),
        )
        return [_norm_image(r) for r in rows]

    async def delete_image(self, image_id: int, user_id: int) -> bool:
        result = await self._execute(
            f"DELETE FROM {T_IMAGES} WHERE id=$1 AND user_id=$2", _int(image_id), _int(user_id)
        )
        return not result.endswith("0")

    async def count_images(self, user_id: Optional[int] = None) -> int:
        if user_id:
            return _int(await self._fetchval(f"SELECT COUNT(*) FROM {T_IMAGES} WHERE user_id=$1", _int(user_id)))
        return _int(await self._fetchval(f"SELECT COUNT(*) FROM {T_IMAGES}"))

    # -- custom voices ----------------------------------------------------
    async def add_voice(self, *, user_id: int, name: str, description: str = "",
                        voice_key: Optional[str] = None, base_voice: str = "en-US-AriaNeural",
                        sample_url: Optional[str] = None, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        row = await self._fetchrow(
            f"""INSERT INTO {T_VOICES} (user_id, name, description, voice_key, base_voice, sample_url, settings)
                VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb) RETURNING *""",
            _int(user_id), name, description or "", voice_key, base_voice, sample_url,
            json.dumps(settings or {}),
        )
        if not row:
            raise StoreError("Voice insert returned no row")
        return _norm_voice(row)

    async def list_voices(self, user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        rows = await self._fetch(
            f"SELECT * FROM {T_VOICES} WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2",
            _int(user_id), _int(limit),
        )
        return [_norm_voice(r) for r in rows]

    async def get_voice(self, voice_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        row = await self._fetchrow(
            f"SELECT * FROM {T_VOICES} WHERE id=$1 AND user_id=$2", _int(voice_id), _int(user_id)
        )
        return _norm_voice(row) if row else None

    async def delete_voice(self, key: str, user_id: int) -> bool:
        key = str(key)
        if key.isdigit():
            sql, args = f"DELETE FROM {T_VOICES} WHERE id=$1 AND user_id=$2", (_int(key), _int(user_id))
        else:
            sql, args = (
                f"DELETE FROM {T_VOICES} WHERE (voice_key=$1 OR name=$1) AND user_id=$2",
                (key, _int(user_id)),
            )
        result = await self._execute(sql, *args)
        return not result.endswith("0")

    async def count_voices(self) -> int:
        return _int(await self._fetchval(f"SELECT COUNT(*) FROM {T_VOICES}"))

    # -- projects ---------------------------------------------------------
    async def add_project(self, *, user_id: int, name: str, project_type: str,
                          settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        row = await self._fetchrow(
            f"""INSERT INTO {T_PROJECTS} (user_id, name, project_type, settings)
                VALUES ($1,$2,$3,$4::jsonb) RETURNING *""",
            _int(user_id), name, project_type, json.dumps(settings or {}),
        )
        if not row:
            raise StoreError("Project insert returned no row")
        return _norm_project(row)

    async def get_project(self, project_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        row = await self._fetchrow(
            f"SELECT * FROM {T_PROJECTS} WHERE id=$1 AND user_id=$2", _int(project_id), _int(user_id)
        )
        return _norm_project(row) if row else None

    async def list_projects(self, user_id: int, project_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        if project_type:
            rows = await self._fetch(
                f"""SELECT * FROM {T_PROJECTS} WHERE user_id=$1 AND project_type=$2
                    ORDER BY created_at DESC, id DESC LIMIT $3""",
                _int(user_id), project_type, _int(limit),
            )
        else:
            rows = await self._fetch(
                f"SELECT * FROM {T_PROJECTS} WHERE user_id=$1 ORDER BY created_at DESC, id DESC LIMIT $2",
                _int(user_id), _int(limit),
            )
        return [_norm_project(r) for r in rows]

    async def update_project(self, project_id: int, user_id: int, *,
                             name: Optional[str] = None,
                             settings: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        if name is not None and settings is not None:
            row = await self._fetchrow(
                f"""UPDATE {T_PROJECTS} SET name=$3, settings=$4::jsonb, updated_at=NOW()
                    WHERE id=$1 AND user_id=$2 RETURNING *""",
                _int(project_id), _int(user_id), name, json.dumps(settings),
            )
        elif name is not None:
            row = await self._fetchrow(
                f"UPDATE {T_PROJECTS} SET name=$3, updated_at=NOW() WHERE id=$1 AND user_id=$2 RETURNING *",
                _int(project_id), _int(user_id), name,
            )
        elif settings is not None:
            row = await self._fetchrow(
                f"UPDATE {T_PROJECTS} SET settings=$3::jsonb, updated_at=NOW() WHERE id=$1 AND user_id=$2 RETURNING *",
                _int(project_id), _int(user_id), json.dumps(settings),
            )
        else:
            return await self.get_project(project_id, user_id)
        return _norm_project(row) if row else None

    async def delete_project(self, project_id: int, user_id: int) -> bool:
        result = await self._execute(
            f"DELETE FROM {T_PROJECTS} WHERE id=$1 AND user_id=$2", _int(project_id), _int(user_id)
        )
        return not result.endswith("0")

    async def count_projects(self, user_id: Optional[int] = None) -> int:
        if user_id:
            return _int(await self._fetchval(f"SELECT COUNT(*) FROM {T_PROJECTS} WHERE user_id=$1", _int(user_id)))
        return _int(await self._fetchval(f"SELECT COUNT(*) FROM {T_PROJECTS}"))

    # -- media ------------------------------------------------------------
    async def upload_media(self, folder: str, filename: str, data: bytes, content_type: str) -> Optional[str]:
        return None  # plain Postgres has no object storage configured


# ============================================================ Memory backend
class MemoryStore:
    """In-process fallback so the API still runs with no database at all.

    Data disappears when the process/instance restarts - on Vercel that means
    per warm container. Everything degrades gracefully instead of returning 503.
    """

    name = "memory"

    def __init__(self, detail: str = "in-memory (ephemeral)"):
        self.detail = detail
        self.users: Dict[int, Dict[str, Any]] = {}
        self.audio: Dict[int, Dict[str, Any]] = {}
        self.images: Dict[int, Dict[str, Any]] = {}
        self.voices: Dict[int, Dict[str, Any]] = {}
        self.projects: Dict[int, Dict[str, Any]] = {}
        self._seq = {"users": 0, "audio": 0, "images": 0, "voices": 0, "projects": 0}
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        logger.warning("Using the in-memory store - data will not persist (%s)", self.detail)

    async def close(self) -> None:
        return None

    def status(self) -> Dict[str, Any]:
        return {"backend": self.name, "detail": self.detail, "storage": False}

    def _next(self, kind: str) -> int:
        self._seq[kind] += 1
        return self._seq[kind]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # -- users ------------------------------------------------------------
    async def create_user(self, *, email: str, username: str, password_hash: str,
                          full_name: str = "", role: str = "user",
                          referral_code: Optional[str] = None,
                          referred_by: Optional[int] = None) -> Dict[str, Any]:
        async with self._lock:
            for existing in self.users.values():
                if existing["email"].lower() == email.lower() or existing["username"].lower() == username.lower():
                    raise DuplicateError("Email or username already exists")
            user = _norm_user({
                "id": self._next("users"), "email": email, "username": username,
                "full_name": full_name, "password_hash": password_hash, "role": role,
                "is_active": True, "credits": 999999, "total_used": 0,
                "referral_code": referral_code, "referred_by": referred_by,
                "created_at": self._now(),
            })
            self.users[user["id"]] = user
            return dict(user)

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        user = self.users.get(_int(user_id))
        return dict(user) if user else None

    async def get_user_by_login(self, identifier: str) -> Optional[Dict[str, Any]]:
        identifier = (identifier or "").strip().lower()
        for user in self.users.values():
            if user["username"].lower() == identifier or user["email"].lower() == identifier:
                return dict(user)
        return None

    async def get_user_by_referral(self, code: str) -> Optional[Dict[str, Any]]:
        for user in self.users.values():
            if user["referral_code"] == code:
                return dict(user)
        return None

    async def update_user(self, user_id: int, **fields: Any) -> Optional[Dict[str, Any]]:
        user = self.users.get(_int(user_id))
        if not user:
            return None
        user.update({k: v for k, v in fields.items() if v is not None})
        return _norm_user(user)

    async def add_usage(self, user_id: int, amount: int) -> None:
        user = self.users.get(_int(user_id))
        if user and amount > 0:
            user["total_used"] = _int(user.get("total_used")) + amount

    async def list_users(self, limit: int = 200) -> List[Dict[str, Any]]:
        return [dict(u) for u in sorted(self.users.values(), key=lambda u: -u["id"])[:limit]]

    async def count_users(self, active_only: bool = False) -> int:
        return len([u for u in self.users.values() if (u["is_active"] or not active_only)])

    async def list_referrals(self, user_id: int) -> List[Dict[str, Any]]:
        return [dict(u) for u in self.users.values() if _int(u.get("referred_by")) == _int(user_id)]

    # -- audio ------------------------------------------------------------
    async def add_audio(self, *, user_id: int, text: str, voice: str, engine: str,
                        filename: str, url: str, chars: int = 0,
                        data_uri: Optional[str] = None) -> Optional[Dict[str, Any]]:
        item = _norm_audio({
            "id": self._next("audio"), "user_id": user_id, "text": text, "voice": voice,
            "engine": engine, "filename": filename, "url": url, "chars": chars,
            "data_uri": data_uri, "created_at": self._now(),
        })
        self.audio[item["id"]] = item
        return dict(item)

    async def list_audio(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        rows = [a for a in self.audio.values() if _int(a["user_id"]) == _int(user_id)]
        return [dict(a) for a in sorted(rows, key=lambda a: -a["id"])[:limit]]

    async def get_audio(self, audio_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        item = self.audio.get(_int(audio_id))
        if item and _int(item["user_id"]) == _int(user_id):
            return dict(item)
        return None

    async def delete_audio(self, audio_id: int, user_id: int) -> bool:
        item = self.audio.get(_int(audio_id))
        if item and _int(item["user_id"]) == _int(user_id):
            del self.audio[_int(audio_id)]
            return True
        return False

    async def count_audio(self, user_id: Optional[int] = None) -> int:
        if user_id is None:
            return len(self.audio)
        return len([a for a in self.audio.values() if _int(a["user_id"]) == _int(user_id)])

    # -- images -----------------------------------------------------------
    async def add_image(self, *, user_id: int, prompt: str, style: str, filename: str, url: str,
                        model: str = "", size: str = "", data_uri: Optional[str] = None) -> Optional[Dict[str, Any]]:
        item = _norm_image({
            "id": self._next("images"), "user_id": user_id, "prompt": prompt, "style": style,
            "model": model, "size": size, "filename": filename, "url": url,
            "data_uri": data_uri, "created_at": self._now(),
        })
        self.images[item["id"]] = item
        return dict(item)

    async def list_images(self, user_id: int, limit: int = 60) -> List[Dict[str, Any]]:
        rows = [i for i in self.images.values() if _int(i["user_id"]) == _int(user_id)]
        return [dict(i) for i in sorted(rows, key=lambda i: -i["id"])[:limit]]

    async def delete_image(self, image_id: int, user_id: int) -> bool:
        item = self.images.get(_int(image_id))
        if item and _int(item["user_id"]) == _int(user_id):
            del self.images[_int(image_id)]
            return True
        return False

    async def count_images(self, user_id: Optional[int] = None) -> int:
        if user_id is None:
            return len(self.images)
        return len([i for i in self.images.values() if _int(i["user_id"]) == _int(user_id)])

    # -- voices -----------------------------------------------------------
    async def add_voice(self, *, user_id: int, name: str, description: str = "",
                        voice_key: Optional[str] = None, base_voice: str = "en-US-AriaNeural",
                        sample_url: Optional[str] = None, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        item = _norm_voice({
            "id": self._next("voices"), "user_id": user_id, "name": name, "description": description,
            "voice_key": voice_key, "base_voice": base_voice, "sample_url": sample_url,
            "settings": settings or {}, "created_at": self._now(),
        })
        self.voices[item["id"]] = item
        return dict(item)

    async def list_voices(self, user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        rows = [v for v in self.voices.values() if _int(v["user_id"]) == _int(user_id)]
        return [dict(v) for v in sorted(rows, key=lambda v: -v["id"])[:limit]]

    async def get_voice(self, voice_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        item = self.voices.get(_int(voice_id))
        if item and _int(item["user_id"]) == _int(user_id):
            return dict(item)
        return None

    async def delete_voice(self, key: str, user_id: int) -> bool:
        key = str(key)
        for vid, item in list(self.voices.items()):
            if _int(item["user_id"]) != _int(user_id):
                continue
            if (key.isdigit() and str(item["id"]) == key) or item.get("voice_key") == key or item.get("name") == key:
                del self.voices[vid]
                return True
        return False

    async def count_voices(self) -> int:
        return len(self.voices)

    # -- projects ---------------------------------------------------------
    async def add_project(self, *, user_id: int, name: str, project_type: str,
                          settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        item = _norm_project({
            "id": self._next("projects"), "user_id": user_id, "name": name,
            "project_type": project_type, "settings": settings or {},
            "created_at": self._now(), "updated_at": self._now(),
        })
        self.projects[item["id"]] = item
        return dict(item)

    async def get_project(self, project_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        item = self.projects.get(_int(project_id))
        if item and _int(item["user_id"]) == _int(user_id):
            return dict(item)
        return None

    async def list_projects(self, user_id: int, project_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        rows = [
            p for p in self.projects.values()
            if _int(p["user_id"]) == _int(user_id) and (not project_type or p["project_type"] == project_type)
        ]
        return [dict(p) for p in sorted(rows, key=lambda p: -p["id"])[:limit]]

    async def update_project(self, project_id: int, user_id: int, *,
                             name: Optional[str] = None,
                             settings: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        item = self.projects.get(_int(project_id))
        if not item or _int(item["user_id"]) != _int(user_id):
            return None
        if name is not None:
            item["name"] = name
        if settings is not None:
            item["settings"] = settings
        item["updated_at"] = self._now()
        return dict(item)

    async def delete_project(self, project_id: int, user_id: int) -> bool:
        item = self.projects.get(_int(project_id))
        if item and _int(item["user_id"]) == _int(user_id):
            del self.projects[_int(project_id)]
            return True
        return False

    async def count_projects(self, user_id: Optional[int] = None) -> int:
        if user_id is None:
            return len(self.projects)
        return len([p for p in self.projects.values() if _int(p["user_id"]) == _int(user_id)])

    # -- media ------------------------------------------------------------
    async def upload_media(self, folder: str, filename: str, data: bytes, content_type: str) -> Optional[str]:
        return None


# ============================================================== factory / DI
_store: Optional[Any] = None
_store_lock = asyncio.Lock()
_init_error: str = ""


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return default


async def _build_store() -> Any:
    """Pick the best available backend, falling back step by step."""
    global _init_error
    _init_error = ""

    database_url = _env("DATABASE_URL", "BGLABS_DATABASE_URL")
    if database_url and os.getenv("BGLABS_DISABLE_POSTGRES", "").lower() not in ("1", "true", "yes"):
        store = PostgresStore(database_url)
        try:
            await store.init()
            return store
        except Exception as exc:
            _init_error = f"postgres: {exc}"
            logger.warning("Postgres backend unavailable, falling back: %s", exc)

    supabase_url = _env("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = _env("SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY", "SUPABASE_KEY")
    if supabase_url and supabase_key:
        store = SupabaseStore(supabase_url, supabase_key, _env("SUPABASE_STORAGE_BUCKET", default="bglabs-media"))
        try:
            await store.init()
            return store
        except Exception as exc:
            _init_error = (_init_error + f" | supabase: {exc}").strip(" |")
            logger.warning("Supabase backend unavailable, falling back to memory: %s", exc)

    if not _init_error:
        _init_error = "no DATABASE_URL and no SUPABASE_URL/SUPABASE_SERVICE_KEY configured"
    store = MemoryStore(_init_error)
    await store.init()
    return store


async def get_store() -> Any:
    """Return the shared store instance, creating it on first use."""
    global _store
    if _store is not None:
        return _store
    async with _store_lock:
        if _store is None:
            _store = await _build_store()
    return _store


async def reset_store() -> None:
    """Drop the cached instance (used by tests and /api/system/reload)."""
    global _store, _init_error
    async with _store_lock:
        if _store is not None:
            try:
                await _store.close()
            except Exception:
                pass
        _store = None
        _init_error = ""


def backend_name() -> str:
    return getattr(_store, "name", "uninitialised")


def init_error() -> str:
    return _init_error


__all__ = [
    "StoreError",
    "DuplicateError",
    "SupabaseStore",
    "PostgresStore",
    "MemoryStore",
    "get_store",
    "reset_store",
    "backend_name",
    "init_error",
    "T_USERS",
    "T_AUDIO",
    "T_IMAGES",
    "T_VOICES",
    "T_PROJECTS",
]
