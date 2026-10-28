"""
BG LABS - Google OAuth + YouTube Data API v3
============================================

Everything needed for "Continue with Google" channel connection, supporting
**multiple channels per user** (each channel is stored separately, one of them
flagged as primary).

Environment
-----------
``GOOGLE_CLIENT_ID``       OAuth client id (required for the button to work)
``GOOGLE_CLIENT_SECRET``   OAuth client secret (required)
``GOOGLE_REDIRECT_URI``    optional override; defaults to
                           ``<request base>/api/youtube/auth/callback``
``YOUTUBE_API_KEY``        optional - enables the read-only "manual connect"
                           fallback when OAuth is not configured yet
``GOOGLE_AUTH_BASE``/``GOOGLE_OAUTH_BASE``/``GOOGLE_API_BASE``
                           overridable endpoints (tests point these at a mock)

Tokens are stored server-side in the project store (never sent to the browser
except a short-lived access token for the client-side resumable video upload,
which is the only way to publish files larger than Vercel's 4.5 MB body limit).

No new dependencies: plain ``httpx`` calls.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("bglabs.google")

AUTH_BASE = os.getenv("GOOGLE_AUTH_BASE", "https://accounts.google.com").rstrip("/")
OAUTH_BASE = os.getenv("GOOGLE_OAUTH_BASE", "https://oauth2.googleapis.com").rstrip("/")
API_BASE = os.getenv("GOOGLE_API_BASE", "https://www.googleapis.com").rstrip("/")

SCOPES: Tuple[str, ...] = (
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/drive.readonly",
)

TIMEOUT = float(os.getenv("GOOGLE_TIMEOUT", "45"))
REFRESH_SKEW_SECONDS = 180


class GoogleError(Exception):
    """Any failure in the Google/YouTube flow that should reach the user."""

    def __init__(self, message: str, status: int = 502, detail: Any = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.detail = detail


# ====================================================================== config
def client_id() -> str:
    return (os.getenv("GOOGLE_CLIENT_ID") or "").strip()


def client_secret() -> str:
    return (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()


def api_key() -> str:
    return (os.getenv("YOUTUBE_API_KEY") or "").strip()


def oauth_configured() -> bool:
    return bool(client_id() and client_secret())


def status() -> Dict[str, Any]:
    """What the UI needs to decide how to render the connect panel."""
    return {
        "oauth_configured": oauth_configured(),
        "client_id_set": bool(client_id()),
        "client_secret_set": bool(client_secret()),
        "api_key_set": bool(api_key()),
        "manual_connect_available": bool(api_key()),
        "scopes": list(SCOPES),
        "multi_channel": True,
        "setup": {
            "needed": not oauth_configured(),
            "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI") or "<your-domain>/api/youtube/auth/callback",
            "steps": [
                "Open https://console.cloud.google.com/apis/credentials",
                "Enable 'YouTube Data API v3' for the project (APIs & Services -> Library).",
                "Create Credentials -> OAuth client ID -> Web application.",
                "Add the Authorized redirect URI shown above (exact match, https).",
                "Copy the Client ID and Client Secret into the Vercel environment variables "
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, then redeploy.",
                "Publish the OAuth consent screen (External) so accounts outside your test list can sign in.",
            ],
        },
    }


def default_redirect_uri(request: Any = None) -> str:
    configured = (os.getenv("GOOGLE_REDIRECT_URI") or "").strip()
    if configured:
        return configured
    if request is None:
        return ""
    base = str(getattr(request, "base_url", "") or "").rstrip("/")
    if not base:  # pragma: no cover - only in odd proxies
        scheme = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        base = f"{scheme}://{host}".rstrip("/")
    return f"{base}/api/youtube/auth/callback"


def redirect_uri_for(request: Any = None) -> str:
    uri = default_redirect_uri(request)
    if not uri:
        raise GoogleError("GOOGLE_REDIRECT_URI is not set and could not be derived from the request", 500)
    return uri


# ======================================================================= state
def make_state(user_id: int, purpose: str = "connect") -> str:
    """Short-lived signed state so the callback knows which user is connecting."""
    from app.deps import create_token  # local import keeps the module light

    import jwt

    payload = {"sub": str(user_id), "purpose": purpose, "typ": "google-state",
               "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
               "iat": datetime.now(timezone.utc)}
    secret = os.getenv("SECRET_KEY") or os.getenv("BGLABS_SECRET_KEY") or "bglabs-secret-key-change-in-production"
    return jwt.encode(payload, secret, algorithm="HS256")


def read_state(state: str) -> Optional[int]:
    import jwt

    secret = os.getenv("SECRET_KEY") or os.getenv("BGLABS_SECRET_KEY") or "bglabs-secret-key-change-in-production"
    try:
        payload = jwt.decode(state, secret, algorithms=["HS256"])
    except Exception as exc:
        logger.warning("google state rejected: %s", exc)
        return None
    if payload.get("typ") != "google-state":
        return None
    try:
        return int(payload.get("sub"))
    except (TypeError, ValueError):
        return None


def build_auth_url(state: str, redirect_uri: str, *, login_hint: str = "",
                   prompt: str = "consent") -> str:
    if not oauth_configured():
        raise GoogleError("Google OAuth is not configured on this server (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET). "
                          "See /api/youtube/auth/status for setup steps.", 503)
    params = {
        "client_id": client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",          # gives us a refresh token
        "include_granted_scopes": "true",  # keeps previously granted scopes
        "prompt": prompt,
        "state": state,
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_BASE}/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


# ====================================================================== tokens
async def _post_form(url: str, data: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if response.status_code >= 400:
        raise GoogleError(f"Google token request failed ({response.status_code}): {response.text[:200]}",
                          response.status_code, response.text[:500])
    try:
        return response.json()
    except json.JSONDecodeError as exc:  # pragma: no cover
        raise GoogleError(f"Google returned invalid JSON: {exc}", 502)


async def exchange_code(code: str, redirect_uri: str) -> Dict[str, Any]:
    return await _post_form(f"{OAUTH_BASE}/token", {
        "code": code,
        "client_id": client_id(),
        "client_secret": client_secret(),
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })


async def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    return await _post_form(f"{OAUTH_BASE}/token", {
        "refresh_token": refresh_token,
        "client_id": client_id(),
        "client_secret": client_secret(),
        "grant_type": "refresh_token",
    })


def normalize_tokens(raw: Dict[str, Any], previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Store tokens in one predictable shape, keeping the old refresh token."""
    previous = previous or {}
    expires_in = raw.get("expires_in") or 3600
    try:
        expires_in = int(expires_in)
    except (TypeError, ValueError):
        expires_in = 3600
    return {
        "access_token": raw.get("access_token") or previous.get("access_token", ""),
        "refresh_token": raw.get("refresh_token") or previous.get("refresh_token", ""),
        "token_type": raw.get("token_type") or previous.get("token_type", "Bearer"),
        "scope": raw.get("scope") or previous.get("scope", " ".join(SCOPES)),
        "expires_in": expires_in,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat(),
        "id_token": raw.get("id_token", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def token_expired(tokens: Dict[str, Any]) -> bool:
    expires_at = (tokens or {}).get("expires_at")
    if not expires_at:
        return True
    try:
        moment = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) + timedelta(seconds=REFRESH_SKEW_SECONDS) >= moment


async def ensure_access_token(tokens: Dict[str, Any]) -> Dict[str, Any]:
    """Return usable tokens, refreshing them if they are close to expiry."""
    tokens = dict(tokens or {})
    if tokens.get("access_token") and not token_expired(tokens):
        return tokens
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise GoogleError("This channel connection has no refresh token - please reconnect the channel.", 401)
    if not oauth_configured():
        raise GoogleError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set, so tokens cannot be refreshed.", 503)
    try:
        raw = await refresh_access_token(refresh)
    except GoogleError as exc:
        if exc.status in (400, 401):
            raise GoogleError("Google rejected the refresh token (the channel must be reconnected).", 401, exc.message)
        raise
    return normalize_tokens(raw, tokens)


# ================================================================ youtube API
async def _get(url: str, params: Dict[str, Any], access_token: str = "") -> Dict[str, Any]:
    headers = {"Accept": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(url, params={k: v for k, v in params.items() if v not in (None, "")},
                                    headers=headers)
    if response.status_code == 401:
        raise GoogleError("YouTube rejected the access token - reconnect the channel.", 401, response.text[:300])
    if response.status_code == 403:
        raise GoogleError("YouTube refused the request (scope, quota or permissions): "
                          f"{response.text[:220]}", 403, response.text[:500])
    if response.status_code >= 400:
        raise GoogleError(f"YouTube API error {response.status_code}: {response.text[:220]}",
                          response.status_code, response.text[:500])
    try:
        return response.json()
    except json.JSONDecodeError:  # pragma: no cover
        return {}


async def _post_json(url: str, payload: Dict[str, Any], access_token: str,
                     params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    query = {"key": api_key()} if not access_token else {}
    if params:
        query.update(params)
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            url, params={k: v for k, v in query.items() if v}, json=payload,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"} if access_token
            else {"Content-Type": "application/json"},
        )
    if response.status_code >= 400:
        raise GoogleError(f"YouTube API error {response.status_code}: {response.text[:220]}",
                          response.status_code, response.text[:500])
    try:
        return response.json()
    except json.JSONDecodeError:  # pragma: no cover
        return {}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def normalize_channel(item: Dict[str, Any]) -> Dict[str, Any]:
    snippet = item.get("snippet") or {}
    statistics = item.get("statistics") or {}
    details = item.get("contentDetails") or {}
    branding = item.get("brandingSettings") or {}
    thumbnails = snippet.get("thumbnails") or {}
    thumb = (thumbnails.get("medium") or thumbnails.get("default") or {}).get("url", "")
    return {
        "channel_id": item.get("id", ""),
        "title": snippet.get("title", ""),
        "description": (snippet.get("description") or "")[:400],
        "thumbnail": thumb,
        "custom_url": snippet.get("customUrl", ""),
        "country": snippet.get("country", ""),
        "published_at": snippet.get("publishedAt", ""),
        "uploads_playlist": (details.get("relatedPlaylists") or {}).get("uploads", ""),
        "keywords": (branding.get("channel") or {}).get("keywords", ""),
        "stats": {
            "subscribers": _int(statistics.get("subscriberCount")),
            "views": _int(statistics.get("viewCount")),
            "videos": _int(statistics.get("videoCount")),
            "hidden_subscriber_count": bool(statistics.get("hiddenSubscriberCount")),
        },
    }


async def fetch_my_channels(access_token: str) -> List[Dict[str, Any]]:
    data = await _get(f"{API_BASE}/youtube/v3/channels",
                      {"part": "snippet,statistics,contentDetails,brandingSettings", "mine": "true",
                       "maxResults": 50}, access_token)
    return [normalize_channel(item) for item in data.get("items") or []]


async def fetch_channel(access_token: str, channel_id: str = "", handle: str = "") -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"part": "snippet,statistics,contentDetails", "maxResults": 10}
    if channel_id:
        params["id"] = channel_id
    elif handle:
        value = handle.strip().lstrip("@")
        params["forHandle"] = value
    else:
        return []
    data = await _get(f"{API_BASE}/youtube/v3/channels", params, access_token)
    return [normalize_channel(item) for item in data.get("items") or []]


async def fetch_user_info(access_token: str) -> Dict[str, Any]:
    data = await _get(f"{API_BASE}/oauth2/v3/userinfo", {}, access_token)
    return {
        "email": data.get("email", ""),
        "name": data.get("name", ""),
        "picture": data.get("picture", ""),
        "verified_email": bool(data.get("email_verified")),
    }


def normalize_video(item: Dict[str, Any]) -> Dict[str, Any]:
    snippet = item.get("snippet") or {}
    statistics = item.get("statistics") or {}
    status = item.get("status") or {}
    thumbnails = snippet.get("thumbnails") or {}
    thumb = (thumbnails.get("medium") or thumbnails.get("default") or {}).get("url", "")
    video_id = item.get("id", "")
    if isinstance(video_id, dict):  # playlistItems shape
        video_id = video_id.get("videoId", "")
    views = _int(statistics.get("viewCount"))
    likes = _int(statistics.get("likeCount"))
    comments = _int(statistics.get("commentCount"))
    return {
        "video_id": video_id,
        "title": snippet.get("title", ""),
        "description": (snippet.get("description") or "")[:500],
        "thumbnail": thumb,
        "published_at": snippet.get("publishedAt", ""),
        "channel_id": snippet.get("channelId", ""),
        "channel_title": snippet.get("channelTitle", ""),
        "privacy": status.get("privacyStatus", ""),
        "stats": {"views": views, "likes": likes, "comments": comments,
                  "like_ratio": round(likes / views, 4) if views else 0.0},
        "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
    }


async def fetch_uploads(access_token: str, uploads_playlist: str, max_results: int = 10,
                        api_key_override: str = "") -> List[Dict[str, Any]]:
    """Recent uploads; with an API key (read-only) the stats are fetched too."""
    if not uploads_playlist:
        return []
    data = await _get(f"{API_BASE}/youtube/v3/playlistItems",
                      {"part": "snippet,contentDetails", "playlistId": uploads_playlist,
                       "maxResults": max(1, min(50, max_results)), "key": api_key_override},
                      access_token)
    videos = []
    for item in data.get("items") or []:
        video_id = ((item.get("contentDetails") or {}).get("videoId")
                    or ((item.get("snippet") or {}).get("resourceId") or {}).get("videoId", ""))
        if not video_id:
            continue
        snippet = item.get("snippet") or {}
        thumbnails = snippet.get("thumbnails") or {}
        videos.append({
            "video_id": video_id,
            "title": snippet.get("title", ""),
            "description": (snippet.get("description") or "")[:500],
            "thumbnail": (thumbnails.get("medium") or thumbnails.get("default") or {}).get("url", ""),
            "published_at": snippet.get("publishedAt", ""),
            "channel_id": snippet.get("channelId", ""),
            "channel_title": snippet.get("channelTitle", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "stats": {"views": 0, "likes": 0, "comments": 0, "like_ratio": 0.0},
        })
    if videos:
        try:
            await attach_video_stats(videos, access_token, api_key_override)
        except GoogleError as exc:
            logger.warning("video stats unavailable: %s", exc)
    return videos


async def attach_video_stats(videos: List[Dict[str, Any]], access_token: str = "",
                             api_key_override: str = "") -> None:
    ids = [v["video_id"] for v in videos if v.get("video_id")][:50]
    if not ids:
        return
    data = await _get(f"{API_BASE}/youtube/v3/videos",
                      {"part": "statistics,status", "id": ",".join(ids), "key": api_key_override},
                      access_token)
    by_id = {item.get("id", ""): item for item in data.get("items") or []}
    for video in videos:
        item = by_id.get(video["video_id"])
        if not item:
            continue
        stats = item.get("statistics") or {}
        views = _int(stats.get("viewCount"))
        likes = _int(stats.get("likeCount"))
        comments = _int(stats.get("commentCount"))
        video["stats"] = {"views": views, "likes": likes, "comments": comments,
                          "like_ratio": round(likes / views, 4) if views else 0.0}
        video["privacy"] = (item.get("status") or {}).get("privacyStatus", video.get("privacy", ""))


async def fetch_comments(access_token: str, video_id: str, max_results: int = 25,
                         api_key_override: str = "") -> List[Dict[str, Any]]:
    data = await _get(f"{API_BASE}/youtube/v3/commentThreads",
                      {"part": "snippet", "videoId": video_id, "maxResults": max(1, min(100, max_results)),
                       "order": "relevance", "textFormat": "plain", "key": api_key_override},
                      access_token)
    comments = []
    for item in data.get("items") or []:
        top = ((item.get("snippet") or {}).get("topLevelComment") or {}).get("snippet") or {}
        if not top:
            continue
        comments.append({
            "comment_id": item.get("id", ""),
            "video_id": video_id,
            "author": top.get("authorDisplayName", ""),
            "author_thumbnail": top.get("authorProfileImageUrl", ""),
            "text": top.get("textDisplay", ""),
            "likes": _int(top.get("likeCount")),
            "published_at": top.get("publishedAt", ""),
            "reply_count": _int((item.get("snippet") or {}).get("totalReplyCount")),
            "can_reply": bool(item.get("snippet", {}).get("canReply", True)),
        })
    return comments


async def post_comment_reply(access_token: str, video_id: str, parent_id: str, text: str) -> Dict[str, Any]:
    if not access_token:
        raise GoogleError("Replying needs an OAuth connection (an API key cannot post comments).", 403)
    data = await _post_json(f"{API_BASE}/youtube/v3/comments", {
        "snippet": {"parentId": parent_id, "videoId": video_id,
                    "textOriginal": text[:5000], "textDisplay": text[:5000]},
    }, access_token, params={"part": "snippet"})
    snippet = data.get("snippet") or {}
    return {"comment_id": data.get("id", ""), "text": snippet.get("textDisplay", text),
            "author": snippet.get("authorDisplayName", ""), "video_id": video_id,
            "published_at": snippet.get("createdAt", "")}


async def insert_video_metadata(access_token: str, snippet: Dict[str, Any],
                                status: Dict[str, Any]) -> Dict[str, Any]:
    """Create the video resource without media (used by the client-side uploader)."""
    return await _post_json(f"{API_BASE}/youtube/v3/videos",
                            {"snippet": snippet, "status": status}, access_token,
                            params={"part": "snippet,status"})


def resumable_upload_url() -> str:
    return f"{API_BASE}/upload/youtube/v3/videos"


def upload_headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/*",
    }


def upload_plan(access_token: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the browser needs to upload directly to Google.

    Vercel serverless bodies are capped at 4.5 MB, so media never passes through
    this API: the browser does the resumable upload with a short-lived token.
    """
    snippet = {
        "title": str(metadata.get("title") or "Untitled")[:100],
        "description": str(metadata.get("description") or "")[:5000],
        "tags": [str(tag)[:30] for tag in (metadata.get("tags") or [])][:30],
        "categoryId": str(metadata.get("category_id") or metadata.get("category") or "22"),
        "defaultLanguage": metadata.get("language") or "en",
        "defaultAudioLanguage": metadata.get("language") or "en",
    }
    status = {
        "privacyStatus": metadata.get("privacy") or "private",
        "selfDeclaredMadeForKids": bool(metadata.get("made_for_kids")),
        "publishAt": metadata.get("publish_at") or None,
        "license": metadata.get("license") or "youtube",
        "embeddable": True,
        "publicStatsViewable": True,
    }
    status = {k: v for k, v in status.items() if v is not None}
    return {
        "url": f"{resumable_upload_url()}?uploadType=resumable&part=snippet,status",
        "method": "POST",
        "headers": upload_headers(access_token),
        "body": {"snippet": snippet, "status": status},
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=55)).isoformat(),
        "notes": "Browser performs the resumable upload: POST this body to start, then PUT the bytes "
                 "to the Location header URL. Google allows CORS on this endpoint.",
    }


# =============================================================== storage shape
def connection_name(channel: Dict[str, Any]) -> str:
    return f"YouTube: {channel.get('title') or channel.get('channel_id') or 'channel'}"


def connection_payload(user_id: int, channel: Dict[str, Any], tokens: Dict[str, Any], *,
                       google_user: Optional[Dict[str, Any]] = None,
                       primary: bool = False, mode: str = "oauth") -> Dict[str, Any]:
    """A channel connection stored as a project row (``project_type='youtube_connection'``)."""
    settings: Dict[str, Any] = {
        "provider": "google",
        "mode": mode,                       # oauth | api_key
        "channel_id": channel.get("channel_id", ""),
        "title": channel.get("title", ""),
        "thumbnail": channel.get("thumbnail", ""),
        "custom_url": channel.get("custom_url", ""),
        "description": channel.get("description", ""),
        "country": channel.get("country", ""),
        "uploads_playlist": channel.get("uploads_playlist", ""),
        "stats": channel.get("stats") or {},
        "google_user": {k: v for k, v in (google_user or {}).items() if k != "picture"} | {
            "picture": (google_user or {}).get("picture", "")},
        "is_primary": bool(primary),
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }
    if mode == "oauth":
        settings["tokens"] = tokens
        settings["scope"] = tokens.get("scope", "")
        settings["expires_at"] = tokens.get("expires_at", "")
    else:
        settings["tokens"] = {}
        settings["scope"] = "read-only (API key)"
    return {"user_id": user_id, "name": connection_name(channel),
            "project_type": "youtube_connection", "settings": settings}


def public_channel(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Channel data safe to send to the browser - never includes tokens."""
    return {
        "channel_id": settings.get("channel_id", ""),
        "title": settings.get("title", ""),
        "thumbnail": settings.get("thumbnail", ""),
        "custom_url": settings.get("custom_url", ""),
        "description": settings.get("description", ""),
        "country": settings.get("country", ""),
        "url": settings.get("custom_url") or f"https://www.youtube.com/channel/{settings.get('channel_id', '')}",
        "uploads_playlist": settings.get("uploads_playlist", ""),
        "stats": settings.get("stats") or {},
        "google_email": (settings.get("google_user") or {}).get("email", ""),
        "is_primary": bool(settings.get("is_primary")),
        "mode": settings.get("mode", "oauth"),
        "scope": settings.get("scope", ""),
        "can_upload": settings.get("mode") == "oauth" and bool((settings.get("tokens") or {}).get("refresh_token")),
        "can_reply": settings.get("mode") == "oauth",
        "connected_at": settings.get("connected_at", ""),
        "token_expires_at": settings.get("expires_at", ""),
        "token_expired": bool(settings.get("tokens")) and token_expired(settings.get("tokens") or {}),
    }


def seconds_until_expiry(settings: Dict[str, Any]) -> int:
    expires_at = settings.get("expires_at")
    if not expires_at:
        return 0
    try:
        moment = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return 0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int((moment - datetime.now(timezone.utc)).total_seconds())


CATEGORY_IDS = {
    "Film & Animation": "1", "Autos & Vehicles": "2", "Music": "10", "Pets & Animals": "15",
    "Sports": "17", "Short Movies": "18", "Travel & Events": "19", "Gaming": "20",
    "Videoblogging": "21", "People & Blogs": "22", "Comedy": "23", "Entertainment": "24",
    "News & Politics": "25", "Howto & Style": "26", "Education": "27", "Science & Technology": "28",
    "Nonprofits & Activism": "29", "Movies": "30", "Anime/Animation": "31", "Action/Adventure": "32",
    "Classics": "33", "Documentary": "35", "Shows": "43",
}


def category_id(name_or_id: Any) -> str:
    value = str(name_or_id or "").strip()
    if value in CATEGORY_IDS:
        return CATEGORY_IDS[value]
    if value.isdigit():
        return value
    lowered = value.lower()
    for name, identifier in CATEGORY_IDS.items():
        if name.lower() == lowered:
            return identifier
    return "22"


def categories() -> List[Dict[str, str]]:
    return [{"name": name, "id": identifier} for name, identifier in sorted(CATEGORY_IDS.items(),
                                                                            key=lambda kv: int(kv[1]))]


__all__ = [
    "GoogleError", "SCOPES", "api_key", "attach_video_stats", "build_auth_url", "categories",
    "category_id", "client_id", "client_secret", "connection_name", "connection_payload",
    "default_redirect_uri", "ensure_access_token", "exchange_code", "fetch_channel",
    "fetch_comments", "fetch_my_channels", "fetch_uploads", "fetch_user_info", "insert_video_metadata",
    "make_state", "normalize_channel", "normalize_tokens", "normalize_video", "oauth_configured",
    "post_comment_reply", "public_channel", "read_state", "redirect_uri_for", "refresh_access_token",
    "resumable_upload_url", "seconds_until_expiry", "status", "token_expired", "upload_headers",
    "upload_plan",
]
