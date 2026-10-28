"""
BG LABS - YouTube channel connection API
========================================

"Continue with Google" for the web UI, with **multiple channels per account**.

Flow
----
1. ``GET /api/youtube/auth/url`` -> the UI opens the returned Google consent URL.
2. Google redirects back to ``GET /api/youtube/auth/callback`` with ``code`` +
   ``state`` (a signed short-lived JWT carrying the BG LABS user id).
3. The callback exchanges the code, reads ``userinfo`` + ``channels?mine=true``
   and stores **every** channel the Google account manages as a separate
   connection, marking the first one primary.
4. The browser lands back on ``/`` with ``#yt=connected`` and the YouTube page
   renders the channel list.

Connections are stored as project rows with ``project_type='youtube_connection'``
so they work on Supabase, PostgreSQL and the in-memory store with no extra
schema. Tokens never leave the server, with one deliberate exception: the
client-side upload plan hands the browser a short-lived access token, because
Vercel caps request bodies at 4.5 MB and videos are bigger.
"""
from __future__ import annotations

import logging
import os
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app import agents as agent_core
from app import google
from app.deps import check_rate_limit, get_client_ip, get_current_user
from app.store import StoreError, get_store

logger = logging.getLogger("bglabs.youtube")

router = APIRouter(tags=["YouTube Connect"])

CONN_TYPE = "youtube_connection"
MANAGER_RUN_TYPE = "youtube_ai_manager_run"
MAX_CHANNELS = 25
MAX_MANAGER_RUNS = 30


# ============================================================================
# helpers
# ============================================================================
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _load_connections(store: Any, user_id: int) -> List[Dict[str, Any]]:
    rows = await store.list_projects(user_id, project_type=CONN_TYPE, limit=MAX_CHANNELS)
    connections = []
    for row in rows:
        settings = row.get("settings") or {}
        connections.append({"row": row, "settings": settings, "id": row.get("id")})
    connections.sort(key=lambda item: (not bool(item["settings"].get("is_primary")),
                                       str(item["settings"].get("title", "")).lower()))
    return connections


async def _find_connection(connections: List[Dict[str, Any]], channel_id: str) -> Optional[Dict[str, Any]]:
    wanted = (channel_id or "").strip()
    for connection in connections:
        if connection["settings"].get("channel_id") == wanted:
            return connection
    return None


async def _upsert_channel(store: Any, user_id: int, channel: Dict[str, Any], tokens: Dict[str, Any], *,
                          google_user: Optional[Dict[str, Any]] = None, primary: bool = False,
                          mode: str = "oauth",
                          existing: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Insert or update one channel connection; returns the public channel shape."""
    connections = existing if existing is not None else await _load_connections(store, user_id)
    payload = google.connection_payload(user_id, channel, tokens, google_user=google_user,
                                        primary=primary, mode=mode)
    current = await _find_connection(connections, channel.get("channel_id", ""))
    if current:
        merged = dict(current["settings"])
        merged.update(payload["settings"])
        merged["last_synced"] = _now()
        row = await store.update_project(current["id"], user_id, name=payload["name"], settings=merged)
        settings = (row or {}).get("settings") or merged
    else:
        payload["settings"]["last_synced"] = _now()
        row = await store.add_project(user_id=user_id, name=payload["name"],
                                      project_type=CONN_TYPE, settings=payload["settings"])
        settings = row.get("settings") or payload["settings"]
    return google.public_channel(settings) | {"project_id": (row or {}).get("id")}


def _ui_redirect(request: Request, fragment: str) -> str:
    """Where the browser should land after the OAuth callback."""
    override = (os.getenv("APP_BASE_URL") or "").strip().rstrip("/")
    base = override or str(getattr(request, "base_url", "")).rstrip("/")
    if not base:
        scheme = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        base = f"{scheme}://{host}"
    return f"{base}/{fragment}"


async def _usable_tokens(connection: Dict[str, Any], *, allow_key: bool = True) -> Tuple[str, Dict[str, Any], str]:
    """Return ``(access_token, fresh_settings, mode)`` refreshing when needed."""
    settings = dict(connection.get("settings") or {})
    tokens = dict(settings.get("tokens") or {})
    if tokens.get("access_token"):
        try:
            tokens = await google.ensure_access_token(tokens)
        except google.GoogleError as exc:
            if not (allow_key and settings.get("mode") == "api_key"):
                raise
            logger.warning("token refresh failed for %s: %s", settings.get("channel_id"), exc)
        settings["tokens"] = tokens
        settings["expires_at"] = tokens.get("expires_at", "")
        if tokens.get("access_token"):
            return tokens["access_token"], settings, "oauth"
    key = google.api_key()
    if allow_key and key and settings.get("mode") == "api_key":
        return "", settings, "api_key"
    if allow_key and key:
        # OAuth token is unusable but a server API key can still serve read-only calls.
        return "", settings, "api_key"
    raise google.GoogleError("This channel needs to be reconnected (the stored token is no longer valid).", 401)


def _key_for(mode: str) -> str:
    return google.api_key() if mode == "api_key" else ""


# ============================================================================
# status / auth
# ============================================================================
@router.get("/api/youtube/auth/status")
async def auth_status(request: Request) -> Dict[str, Any]:
    """Is "Continue with Google" usable, and what is needed if not?"""
    user = await get_current_user(request)
    store = await get_store()
    info = google.status()
    info["redirect_uri"] = google.default_redirect_uri(request)
    info["setup"]["redirect_uri"] = info["redirect_uri"]
    try:
        connections = await _load_connections(store, user["id"])
        info["connected_channels"] = [google.public_channel(c["settings"]) for c in connections]
    except StoreError as exc:
        info["connected_channels"] = []
        info["storage_error"] = str(exc)
    return info


@router.get("/api/youtube/auth/url")
async def auth_url(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    if not google.oauth_configured():
        raise HTTPException(503, "Google OAuth is not configured on this server yet. "
                                 "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET - see /api/youtube/auth/status.")
    redirect_uri = google.redirect_uri_for(request)
    state = google.make_state(user["id"])
    try:
        url = google.build_auth_url(state, redirect_uri,
                                    login_hint=str(request.query_params.get("email") or ""))
    except google.GoogleError as exc:
        raise HTTPException(exc.status, exc.message) from None
    return {"url": url, "state": state, "redirect_uri": redirect_uri,
            "scopes": list(google.SCOPES), "multi_channel": True,
            "hint": "Sign in with any Google account; every channel it manages will be listed so you can pick."}


@router.get("/api/youtube/auth/callback")
async def auth_callback(request: Request, code: str = Query(""), state: str = Query(""),
                        error: str = Query(""), error_description: str = Query("")) -> RedirectResponse:
    """Google redirects the browser here. No bearer token - ``state`` authenticates."""
    if error:
        reason = "access_denied" if error == "access_denied" else error
        detail = urllib.parse.quote(error_description or reason)
        return RedirectResponse(_ui_redirect(request, f"?yt=error&reason={reason}&detail={detail}#youtube"), 303)
    if not code or not state:
        return RedirectResponse(_ui_redirect(request, "?yt=error&reason=missing_code#youtube"), 303)

    user_id = google.read_state(state)
    if not user_id:
        return RedirectResponse(_ui_redirect(request, "?yt=error&reason=bad_state#youtube"), 303)

    store = await get_store()
    user = await store.get_user(user_id)
    if not user:
        return RedirectResponse(_ui_redirect(request, "?yt=error&reason=unknown_user#youtube"), 303)

    redirect_uri = google.redirect_uri_for(request)
    try:
        raw_tokens = await google.exchange_code(code, redirect_uri)
        tokens = google.normalize_tokens(raw_tokens)
        if not tokens.get("access_token"):
            raise google.GoogleError("Google did not return an access token.", 502)
        info = await google.fetch_user_info(tokens["access_token"])
        channels = await google.fetch_my_channels(tokens["access_token"])
        if not channels:
            raise google.GoogleError("This Google account has no YouTube channel. Create one at "
                                     "youtube.com/channel_switcher, then connect again.", 400)
        existing = await _load_connections(store, user_id)
        have_primary = any(c["settings"].get("is_primary") for c in existing)
        connected = []
        for index, channel in enumerate(channels[:MAX_CHANNELS]):
            connected.append(await _upsert_channel(
                store, user_id, channel, tokens, google_user=info,
                primary=not have_primary and index == 0, mode="oauth", existing=existing,
            ))
    except google.GoogleError as exc:
        logger.warning("google connect failed: %s", exc)
        return RedirectResponse(
            _ui_redirect(request, f"?yt=error&reason=connect_failed&detail={urllib.parse.quote(exc.message[:160])}#youtube"),
            303)
    except StoreError as exc:
        logger.warning("could not store channel connection: %s", exc)
        return RedirectResponse(
            _ui_redirect(request, f"?yt=error&reason=storage&detail={urllib.parse.quote(str(exc)[:160])}#youtube"),
            303)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("unexpected google callback failure")
        return RedirectResponse(
            _ui_redirect(request, f"?yt=error&reason=server_error&detail={urllib.parse.quote(str(exc)[:160])}#youtube"),
            303)

    names = urllib.parse.quote(", ".join(c.get("title", "") for c in connected[:3]))
    return RedirectResponse(_ui_redirect(request, f"?yt=connected&channels={len(connected)}&names={names}#youtube"), 303)


# ============================================================================
# channels
# ============================================================================
@router.get("/api/youtube/channels")
async def channels(request: Request) -> Dict[str, Any]:
    """All channels this user connected (multi-channel support)."""
    user = await get_current_user(request)
    store = await get_store()
    connections = await _load_connections(store, user["id"])
    return {
        "channels": [google.public_channel(c["settings"]) | {"project_id": c["id"]} for c in connections],
        "count": len(connections),
        "primary": next((google.public_channel(c["settings"]) for c in connections
                         if c["settings"].get("is_primary")), None),
        "oauth_configured": google.oauth_configured(),
        "can_add_more": google.oauth_configured(),
        "max_channels": MAX_CHANNELS,
    }


@router.post("/api/youtube/channels/{channel_id}/primary")
async def set_primary(request: Request, channel_id: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    connections = await _load_connections(store, user["id"])
    target = await _find_connection(connections, channel_id)
    if not target:
        raise HTTPException(404, "That channel is not connected")
    for connection in connections:
        wants = connection["id"] == target["id"]
        if bool(connection["settings"].get("is_primary")) != wants:
            settings = dict(connection["settings"])
            settings["is_primary"] = wants
            await store.update_project(connection["id"], user["id"], settings=settings)
    settings = dict(target["settings"])
    settings["is_primary"] = True
    return {"primary": True, "channel": google.public_channel(settings)}


@router.delete("/api/youtube/channels/{channel_id}")
async def disconnect(request: Request, channel_id: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    connections = await _load_connections(store, user["id"])
    target = await _find_connection(connections, channel_id)
    if not target:
        raise HTTPException(404, "That channel is not connected")
    was_primary = bool(target["settings"].get("is_primary"))
    await store.delete_project(target["id"], user["id"])
    promoted = None
    if was_primary:
        remaining = [c for c in connections if c["id"] != target["id"]]
        if remaining:
            settings = dict(remaining[0]["settings"])
            settings["is_primary"] = True
            await store.update_project(remaining[0]["id"], user["id"], settings=settings)
            promoted = settings.get("channel_id")
    return {"disconnected": channel_id, "new_primary": promoted,
            "remaining": len(connections) - 1,
            "note": "Tokens were deleted from our database. You can also revoke access at "
                    "myaccount.google.com/permissions."}


@router.post("/api/youtube/channels/{channel_id}/refresh")
async def refresh_channel(request: Request, channel_id: str) -> Dict[str, Any]:
    """Re-read channel stats (and refresh the OAuth token when needed)."""
    user = await get_current_user(request)
    store = await get_store()
    connections = await _load_connections(store, user["id"])
    target = await _find_connection(connections, channel_id)
    if not target:
        raise HTTPException(404, "That channel is not connected")
    try:
        access_token, settings, mode = await _usable_tokens(target)
        fresh = await google.fetch_channel(access_token, channel_id=channel_id) if mode == "oauth" else \
            await google.fetch_channel("", channel_id=channel_id, handle="") or []
        if not fresh and settings.get("uploads_playlist"):
            fresh = [google.normalize_channel({"id": channel_id,
                                               "snippet": {"title": settings.get("title"),
                                                           "thumbnails": {"default": {"url": settings.get("thumbnail")}},
                                                           "description": settings.get("description"),
                                                           "customUrl": settings.get("custom_url")},
                                               "contentDetails": {"relatedPlaylists": {"uploads": settings["uploads_playlist"]}},
                                               "statistics": settings.get("stats") or {}})]
        if fresh:
            channel = fresh[0]
            channel["stats"] = channel.get("stats") or settings.get("stats") or {}
            tokens = settings.get("tokens") or {}
            updated = await _upsert_channel(store, user["id"], channel, tokens,
                                            google_user=settings.get("google_user"),
                                            primary=bool(settings.get("is_primary")),
                                            mode=settings.get("mode", "oauth"),
                                            existing=connections)
            return {"refreshed": True, "channel": updated, "mode": mode}
        settings["last_synced"] = _now()
        await store.update_project(target["id"], user["id"], settings=settings)
        return {"refreshed": True, "channel": google.public_channel(settings), "mode": mode}
    except google.GoogleError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.post("/api/youtube/channels/manual")
async def manual_connect(request: Request) -> Dict[str, Any]:
    """Read-only connection with a YouTube Data API key (no OAuth needed).

    Useful when the Google OAuth client is not configured yet, or to attach a
    channel the user does not own (e.g. a competitor for research).
    """
    user = await get_current_user(request)
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    channel_id = str(body.get("channel_id") or "").strip()
    handle = str(body.get("handle") or "").strip()
    provided_key = str(body.get("api_key") or "").strip()
    key = provided_key or google.api_key()
    if not key:
        raise HTTPException(400, "Provide an api_key (or set YOUTUBE_API_KEY on the server).")
    if not channel_id and not handle:
        raise HTTPException(400, "Provide channel_id or handle (e.g. @yourchannel).")

    store = await get_store()
    try:
        found = await google._get(  # noqa: SLF001 - internal helper, same module family
            f"{google.API_BASE}/youtube/v3/channels",
            {"part": "snippet,statistics,contentDetails", "maxResults": 5,
             **({"id": channel_id} if channel_id else {"forHandle": handle.lstrip('@')})}, "")
        items = found.get("items") or []
        if not items:
            raise HTTPException(404, "No channel found for that id/handle with this API key.")
        channel = google.normalize_channel(items[0])
        connections = await _load_connections(store, user["id"])
        primary = not any(c["settings"].get("is_primary") for c in connections)
        saved = await _upsert_channel(store, user["id"], channel, {}, mode="api_key",
                                      primary=primary, existing=connections)
        return {"connected": True, "channel": saved, "mode": "api_key",
                "limits": "read-only: videos, comments and stats work; publishing and replying need "
                          "'Continue with Google'."}
    except HTTPException:
        raise
    except google.GoogleError as exc:
        raise HTTPException(exc.status, exc.message) from None
    except StoreError as exc:
        raise HTTPException(503, f"Could not save the channel: {exc}") from None


# ============================================================================
# content: videos, analytics, comments
# ============================================================================
@router.get("/api/youtube/videos")
async def videos(request: Request, channel_id: str = Query(""), max: int = Query(10)) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    connections = await _load_connections(store, user["id"])
    if not connections:
        raise HTTPException(409, "No channel connected yet - use 'Continue with Google'.")
    target = await _find_connection(connections, channel_id) if channel_id else connections[0]
    if not target:
        raise HTTPException(404, "That channel is not connected")
    settings = target["settings"]
    try:
        access_token, fresh, mode = await _usable_tokens(target)
        items = await google.fetch_uploads(access_token, settings.get("uploads_playlist", ""),
                                           max_results=max, api_key_override=_key_for(mode))
        if mode == "oauth" and fresh.get("tokens") != settings.get("tokens"):
            await store.update_project(target["id"], user["id"], settings=fresh)
        total = sum(v["stats"]["views"] for v in items)
        return {"channel": google.public_channel(fresh), "videos": items, "count": len(items),
                "mode": mode, "totals": {"views": total,
                                         "avg_views": int(total / len(items)) if items else 0,
                                         "likes": sum(v["stats"]["likes"] for v in items),
                                         "comments": sum(v["stats"]["comments"] for v in items)},
                "fetched_at": _now()}
    except google.GoogleError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.get("/api/youtube/analytics")
async def analytics(request: Request, channel_id: str = Query(""),
                    insight: str = Query("yes")) -> Dict[str, Any]:
    """Channel numbers, optionally interpreted by the Analytics agent."""
    user = await get_current_user(request)
    store = await get_store()
    connections = await _load_connections(store, user["id"])
    if not connections:
        raise HTTPException(409, "No channel connected yet.")
    target = await _find_connection(connections, channel_id) if channel_id else connections[0]
    if not target:
        raise HTTPException(404, "That channel is not connected")
    settings = target["settings"]
    try:
        access_token, fresh, mode = await _usable_tokens(target)
        items = await google.fetch_uploads(access_token, settings.get("uploads_playlist", ""),
                                           max_results=10, api_key_override=_key_for(mode))
    except google.GoogleError as exc:
        raise HTTPException(exc.status, exc.message) from None

    stats = settings.get("stats") or {}
    views = [v["stats"]["views"] for v in items if v["stats"]["views"]]
    data = {
        "channel": google.public_channel(fresh),
        "statistics": {"views": stats.get("views", 0), "subscribers": stats.get("subscribers", 0),
                       "videos": stats.get("videos", 0)},
        "recent_videos": items[:10],
        "recent_totals": {"views": sum(views), "avg_views": int(sum(views) / len(views)) if views else 0,
                          "likes": sum(v["stats"]["likes"] for v in items),
                          "comments": sum(v["stats"]["comments"] for v in items)},
        "best_video": max(items, key=lambda v: v["stats"]["views"]) if items else None,
    }
    if str(insight).lower() not in ("no", "false", "0"):
        envelope = await agent_core.run_agent(
            "analytics",
            {"goal": str(request.query_params.get("goal") or "grow watch time and subscribers"),
             "data": {"viewCount": stats.get("views", 0), "subscriberCount": stats.get("subscribers", 0),
                      "videoCount": stats.get("videos", 0),
                      "recentAverageViews": data["recent_totals"]["avg_views"],
                      "recentLikes": data["recent_totals"]["likes"],
                      "recentComments": data["recent_totals"]["comments"]}},
        )
        data["insight"] = envelope
    return data


@router.get("/api/youtube/comments")
async def comments(request: Request, video_id: str = Query(...), channel_id: str = Query(""),
                   max: int = Query(25)) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    connections = await _load_connections(store, user["id"])
    if not connections:
        raise HTTPException(409, "No channel connected yet.")
    target = await _find_connection(connections, channel_id) if channel_id else connections[0]
    if not target:
        raise HTTPException(404, "That channel is not connected")
    try:
        access_token, fresh, mode = await _usable_tokens(target)
        items = await google.fetch_comments(access_token, video_id, max_results=max,
                                            api_key_override=_key_for(mode))
        return {"video_id": video_id, "comments": items, "count": len(items), "mode": mode,
                "channel": google.public_channel(fresh),
                "can_reply": mode == "oauth",
                "fetched_at": _now()}
    except google.GoogleError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.post("/api/youtube/comments/reply")
async def reply_comment(request: Request) -> Dict[str, Any]:
    """Post a reply - text supplied, or written by the Comment Responder agent."""
    user = await get_current_user(request)
    ip = get_client_ip(request)
    if not check_rate_limit(ip, "yt-reply", 20, 60):
        raise HTTPException(429, "Too many replies. Please wait a minute.")
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    video_id = str(body.get("video_id") or "").strip()
    comment_id = str(body.get("comment_id") or "").strip()
    text = str(body.get("text") or "").strip()
    dry_run = str(body.get("dry_run", "no")).lower() in ("yes", "true", "1")
    if not video_id or not comment_id:
        raise HTTPException(400, "video_id and comment_id are required")

    store = await get_store()
    connections = await _load_connections(store, user["id"])
    target = await _find_connection(connections, str(body.get("channel_id") or "")) if body.get("channel_id") \
        else (connections[0] if connections else None)
    if not target:
        raise HTTPException(409, "Connect a channel with 'Continue with Google' before replying.")
    if target["settings"].get("mode") != "oauth":
        raise HTTPException(403, "This channel was connected read-only (API key). Reconnect with Google to post replies.")

    generated_by = "user"
    if not text:
        comment_text = str(body.get("comment") or "")
        envelope = await agent_core.run_agent("comment_responder", {
            "video_topic": str(body.get("video_topic") or ""),
            "comments": comment_text or "(the comment could not be loaded - write a polite generic reply)",
            "tone": str(body.get("tone") or "friendly"),
        })
        replies = (envelope.get("result") or {}).get("replies") or []
        text = str(replies[0].get("reply") or "").strip() if replies else ""
        generated_by = f"agent:{envelope.get('provider')}"
        if not text:
            raise HTTPException(502, "The agent did not produce a reply - write one manually.")

    if dry_run:
        return {"posted": False, "dry_run": True, "reply": text, "generated_by": generated_by,
                "video_id": video_id, "comment_id": comment_id}
    try:
        access_token, _, _ = await _usable_tokens(target, allow_key=False)
        posted = await google.post_comment_reply(access_token, video_id, comment_id, text)
    except google.GoogleError as exc:
        raise HTTPException(exc.status, exc.message) from None
    return {"posted": True, "reply": posted.get("text", text), "comment_id": posted.get("comment_id", ""),
            "generated_by": generated_by, "video_id": video_id, "parent_id": comment_id,
            "channel": target["settings"].get("title", ""), "at": _now()}


# ============================================================================
# AI CHANNEL MANAGER
# ============================================================================
def _manager_config(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Safe defaults: AI prepares work, a human approves public actions."""
    saved = settings.get("ai_manager") or {}
    return {
        "enabled": bool(saved.get("enabled", False)),
        "approval_required": True,
        "goal": str(saved.get("goal") or "grow watch time and subscribers"),
        "audience": str(saved.get("audience") or ""),
        "tone": str(saved.get("tone") or "friendly"),
        "language": str(saved.get("language") or "English"),
        "content_frequency": str(saved.get("content_frequency") or "2 videos per week"),
        "permissions": {
            "analytics": bool((saved.get("permissions") or {}).get("analytics", True)),
            "content_plan": bool((saved.get("permissions") or {}).get("content_plan", True)),
            "comment_drafts": bool((saved.get("permissions") or {}).get("comment_drafts", True)),
            "metadata_drafts": bool((saved.get("permissions") or {}).get("metadata_drafts", True)),
            "publish": False,
            "post_replies": False,
        },
        "last_run": saved.get("last_run"),
    }


@router.get("/api/youtube/manager/status")
async def manager_status(request: Request, channel_id: str = Query("")) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    connections = await _load_connections(store, user["id"])
    target = await _find_connection(connections, channel_id) if channel_id else (connections[0] if connections else None)
    if not target:
        raise HTTPException(409, "Connect a channel with 'Continue with Google' first.")
    return {"channel": google.public_channel(target["settings"]),
            "manager": _manager_config(target["settings"]),
            "capabilities": ["analytics audit", "content strategy", "comment triage + reply drafts",
                             "metadata drafts", "full video package"],
            "safety": "Public replies, uploads and publishing always require your approval."}


@router.post("/api/youtube/manager/config")
async def manager_config(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    body = await request.json()
    store = await get_store()
    connections = await _load_connections(store, user["id"])
    channel_id = str(body.get("channel_id") or "").strip()
    target = await _find_connection(connections, channel_id) if channel_id else (connections[0] if connections else None)
    if not target:
        raise HTTPException(409, "Connect a channel with 'Continue with Google' first.")
    old = _manager_config(target["settings"])
    permissions = dict(old["permissions"])
    requested = body.get("permissions") or {}
    for key in ("analytics", "content_plan", "comment_drafts", "metadata_drafts"):
        if key in requested:
            permissions[key] = bool(requested[key])
    # Deliberately cannot be enabled from this endpoint: generated public actions
    # must go through the existing explicit reply/upload endpoints.
    permissions["publish"] = False
    permissions["post_replies"] = False
    config = {
        "enabled": bool(body.get("enabled", old["enabled"])),
        "approval_required": True,
        "goal": str(body.get("goal") or old["goal"])[:300],
        "audience": str(body.get("audience") or old["audience"])[:300],
        "tone": str(body.get("tone") or old["tone"])[:60],
        "language": str(body.get("language") or old["language"])[:60],
        "content_frequency": str(body.get("content_frequency") or old["content_frequency"])[:100],
        "permissions": permissions,
        "last_run": old.get("last_run"),
    }
    settings = dict(target["settings"])
    settings["ai_manager"] = config
    await store.update_project(target["id"], user["id"], settings=settings)
    return {"saved": True, "channel": google.public_channel(settings), "manager": config}


@router.post("/api/youtube/manager/run")
async def manager_run(request: Request) -> Dict[str, Any]:
    """Run the AI team against real connected-channel data and save the report."""
    user = await get_current_user(request)
    if not check_rate_limit(get_client_ip(request), "yt-ai-manager", 6, 300):
        raise HTTPException(429, "AI Channel Manager limit reached. Try again in a few minutes.")
    body = await request.json()
    store = await get_store()
    connections = await _load_connections(store, user["id"])
    channel_id = str(body.get("channel_id") or "").strip()
    target = await _find_connection(connections, channel_id) if channel_id else (connections[0] if connections else None)
    if not target:
        raise HTTPException(409, "Connect a channel with 'Continue with Google' first.")
    config = _manager_config(target["settings"])
    if not config["enabled"] and not bool(body.get("run_once")):
        raise HTTPException(409, "Enable AI Channel Manager first, or send run_once=true.")

    try:
        access_token, fresh, mode = await _usable_tokens(target)
        videos = await google.fetch_uploads(access_token, fresh.get("uploads_playlist", ""),
                                             max_results=max(3, min(15, int(body.get("max_videos") or 10))),
                                             api_key_override=_key_for(mode))
    except google.GoogleError as exc:
        raise HTTPException(exc.status, exc.message) from None

    stats = fresh.get("stats") or {}
    recent_titles = [str(v.get("title") or "") for v in videos]
    totals = {
        "channelViews": stats.get("views", 0), "subscriberCount": stats.get("subscribers", 0),
        "videoCount": stats.get("videos", 0),
        "recentViews": sum((v.get("stats") or {}).get("views", 0) for v in videos),
        "recentLikes": sum((v.get("stats") or {}).get("likes", 0) for v in videos),
        "recentComments": sum((v.get("stats") or {}).get("comments", 0) for v in videos),
        "recentAverageViews": int(sum((v.get("stats") or {}).get("views", 0) for v in videos) / len(videos))
                              if videos else 0,
    }
    report: Dict[str, Any] = {
        "channel": google.public_channel(fresh), "configuration": config,
        "data": {"totals": totals, "recent_videos": videos}, "generated_at": _now(),
        "approval_required": True,
    }

    if config["permissions"]["analytics"]:
        report["analytics"] = await agent_core.run_agent("analytics", {"goal": config["goal"], "data": totals})
    if config["permissions"]["content_plan"]:
        context = "Recent uploads: " + "; ".join(recent_titles[:10]) if recent_titles else "No recent uploads."
        report["strategy"] = await agent_core.run_agent("strategist", {
            "topic": fresh.get("title") or "YouTube channel", "audience": config["audience"],
            "goal": config["goal"], "count": 10,
            "context": f"{context} Publishing target: {config['content_frequency']}. Avoid repeating recent topics.",
        })

    comment_rows: List[Dict[str, Any]] = []
    if config["permissions"]["comment_drafts"] and mode == "oauth":
        for video in videos[:3]:
            if len(comment_rows) >= 24:
                break
            try:
                rows = await google.fetch_comments(access_token, str(video.get("video_id") or ""),
                                                    max_results=8, api_key_override="")
            except google.GoogleError:
                continue
            for row in rows:
                comment_rows.append({"video_id": video.get("video_id"), "video_title": video.get("title"), **row})
        if comment_rows:
            lines = "\n".join(f"[{i+1}] {row.get('author','Viewer')}: {row.get('text','')}"
                              for i, row in enumerate(comment_rows))
            community = await agent_core.run_agent("comment_responder", {
                "video_topic": " / ".join(recent_titles[:3]), "comments": lines, "tone": config["tone"]})
            report["community"] = community
            report["comment_source"] = comment_rows
        else:
            report["community"] = {"result": {"replies": [], "summary": "No recent comments found."},
                                   "engine": "builtin", "provider": "none"}

    strategy_result = ((report.get("strategy") or {}).get("result") or {})
    ideas = strategy_result.get("ideas") or []
    selected_topic = str(body.get("topic") or (ideas[0].get("title") if ideas else "") or
                         (recent_titles[0] if recent_titles else fresh.get("title") or "Next video"))
    if bool(body.get("build_package")):
        report["video_package"] = await agent_core.run_autopilot({
            "topic": selected_topic, "audience": config["audience"], "goal": config["goal"],
            "tone": config["tone"], "language": config["language"], "length": body.get("length") or "medium",
            "context": "Prepared by AI Channel Manager from connected channel data."
        })

    report["review_queue"] = {
        "comment_replies": len((((report.get("community") or {}).get("result") or {}).get("replies") or [])),
        "video_ideas": len(ideas), "video_package_ready": bool(report.get("video_package")),
        "public_actions_taken": 0,
    }
    report["next_actions"] = [
        "Review analytics and choose one recommended experiment.",
        "Approve/edit comment drafts before posting them from the Comments panel.",
        "Pick one video idea; run again with build_package=true for script, voice, thumbnail and SEO.",
        "Upload only after reviewing the final metadata and video.",
    ]

    run_row = await store.add_project(user_id=user["id"],
                                      name=f"AI Manager: {fresh.get('title', 'YouTube')} - {_now()[:10]}",
                                      project_type=MANAGER_RUN_TYPE,
                                      settings={"channel_id": fresh.get("channel_id"), "report": report,
                                                "created_at": _now()})
    settings = dict(fresh)
    manager_saved = dict(settings.get("ai_manager") or config)
    manager_saved["last_run"] = _now()
    settings["ai_manager"] = manager_saved
    await store.update_project(target["id"], user["id"], settings=settings)
    return {"run_id": run_row.get("id"), **report}


@router.get("/api/youtube/manager/runs")
async def manager_runs(request: Request, channel_id: str = Query(""), limit: int = Query(10)) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    rows = await store.list_projects(user["id"], project_type=MANAGER_RUN_TYPE,
                                     limit=max(1, min(MAX_MANAGER_RUNS, limit)))
    if channel_id:
        rows = [row for row in rows if (row.get("settings") or {}).get("channel_id") == channel_id]
    return {"runs": rows, "count": len(rows)}


# ============================================================================
# publishing
# ============================================================================
@router.get("/api/youtube/categories")
async def categories(request: Request) -> Dict[str, Any]:
    await get_current_user(request)
    return {"categories": google.categories()}


@router.post("/api/youtube/upload-plan")
async def upload_plan(request: Request) -> Dict[str, Any]:
    """Hand the browser everything it needs to upload a video straight to Google.

    Videos are far larger than Vercel's 4.5 MB request limit, so the bytes never
    touch this API: the browser starts a resumable upload with a short-lived
    access token and PUTs the file to Google directly.
    """
    user = await get_current_user(request)
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    title = str(body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title is required")

    store = await get_store()
    connections = await _load_connections(store, user["id"])
    target = await _find_connection(connections, str(body.get("channel_id") or "")) if body.get("channel_id") \
        else (connections[0] if connections else None)
    if not target:
        raise HTTPException(409, "Connect a channel with 'Continue with Google' before publishing.")
    if target["settings"].get("mode") != "oauth":
        raise HTTPException(403, "This channel is connected read-only. Reconnect with Google to upload.")

    try:
        access_token, fresh, _ = await _usable_tokens(target, allow_key=False)
    except google.GoogleError as exc:
        raise HTTPException(exc.status, exc.message) from None
    if fresh.get("tokens") != target["settings"].get("tokens"):
        await store.update_project(target["id"], user["id"], settings=fresh)

    tags = body.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    metadata = {
        "title": title[:100],
        "description": str(body.get("description") or "")[:5000],
        "tags": [str(t)[:30] for t in tags][:30],
        "category": google.category_id(body.get("category")),
        "privacy": str(body.get("privacy") or "private"),
        "publish_at": str(body.get("publish_at") or "") or None,
        "made_for_kids": bool(body.get("made_for_kids")),
        "language": str(body.get("language") or "en"),
    }
    if metadata["privacy"] == "public" and metadata["publish_at"]:
        metadata["privacy"] = "private"  # YouTube requires private + publishAt for scheduling
        metadata["scheduled"] = True
    plan = google.upload_plan(access_token, metadata)

    project = None
    try:
        project = await store.add_project(
            user_id=user["id"], name=f"Upload: {metadata['title'][:70]}", project_type="youtube_upload",
            settings={"channel_id": target["settings"].get("channel_id"),
                      "channel_title": target["settings"].get("title"),
                      "metadata": metadata, "status": "plan_created", "created_at": _now()},
        )
    except StoreError as exc:
        logger.warning("could not record upload plan: %s", exc)

    return {"plan": plan, "metadata": metadata, "channel": google.public_channel(fresh),
            "upload_id": (project or {}).get("id"),
            "instructions": [
                "POST the plan body to plan.url with plan.headers (Content-Type: application/json).",
                "Read the Location header from the 200 response - that is the session URL.",
                "PUT the video bytes to the session URL with Content-Type: video/mp4 (chunked, "
                "Content-Range per chunk).",
                "The final response contains the new video id.",
            ]}


@router.post("/api/youtube/uploads/{upload_id}/status")
async def upload_status(request: Request, upload_id: int) -> Dict[str, Any]:
    """Record what happened after the browser finished (or aborted) an upload."""
    user = await get_current_user(request)
    store = await get_store()
    row = await store.get_project(upload_id, user["id"])
    if not row or row.get("project_type") != "youtube_upload":
        raise HTTPException(404, "Upload not found")
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    settings = dict(row.get("settings") or {})
    settings["status"] = str(body.get("status") or "updated")
    settings["video_id"] = str(body.get("video_id") or settings.get("video_id", ""))
    settings["url"] = (f"https://www.youtube.com/watch?v={settings['video_id']}"
                       if settings.get("video_id") else settings.get("url", ""))
    settings["error"] = str(body.get("error") or "")
    settings["updated_at"] = _now()
    await store.update_project(upload_id, user["id"], settings=settings)
    return {"id": upload_id, "status": settings["status"], "video_id": settings.get("video_id"),
            "url": settings.get("url"), "error": settings.get("error")}


@router.get("/api/youtube/uploads")
async def uploads(request: Request) -> List[Dict[str, Any]]:
    user = await get_current_user(request)
    store = await get_store()
    rows = await store.list_projects(user["id"], project_type="youtube_upload", limit=25)
    return [{"id": row.get("id"), "name": row.get("name"), "created_at": row.get("created_at"),
             **(row.get("settings") or {})} for row in rows]
