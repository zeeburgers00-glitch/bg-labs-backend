"""
BG LABS - end-to-end smoke test
===============================

Runs the complete web-UI journey (every endpoint ``index.html`` calls, plus the
legacy ones) against two backends:

* ``memory``           - no environment variables at all
* ``supabase`` (mock)  - SUPABASE_URL pointing at tests/mock_supabase.py, which
                         exercises the real PostgREST/Storage code path

Edge-TTS and Pollinations are stubbed, so no internet access is needed::

    .venv/bin/python tests/smoke_test.py
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAKE_MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x21" + b"\xff\xfb\x90\x00" + b"bglabs-audio-payload" * 40
FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"bglabs-image-payload" * 60

failures: List[str] = []
checks = 0


def check(label: str, condition: bool, detail: Any = "") -> bool:
    global checks
    checks += 1
    if condition:
        print(f"  \033[32mPASS\033[0m {label}")
    else:
        failures.append(f"{label} :: {detail}")
        print(f"  \033[31mFAIL\033[0m {label} -> {detail}")
    return bool(condition)


# ---------------------------------------------------------------- mock servers
def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_mock_supabase(port: int, key: str = "test-key"):
    import uvicorn

    sys.path.insert(0, str(ROOT / "tests"))
    import mock_supabase

    mock_supabase.API_KEY = key
    config = uvicorn.Config(mock_supabase.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 20
    while time.time() < deadline and not server.started:
        time.sleep(0.1)
    if not server.started:
        raise RuntimeError("mock supabase did not start")
    return server, mock_supabase


# --------------------------------------------------------------------- stubs
def install_stubs() -> None:
    """Replace the two network engines with deterministic local stubs."""
    import app.routes.frontend_api as ui
    import main as main_module

    async def fake_edge_tts(text: str, voice: str = "en-US-AriaNeural", rate: str = "+0%", pitch: str = "+0Hz") -> bytes:
        assert isinstance(text, str) and text, "edge_tts called without text"
        return FAKE_MP3

    async def fake_image(prompt: str, style: str = "realistic", width: int = 1024, height: int = 1024,
                         model: str = "", seed: Optional[int] = None) -> bytes:
        assert prompt, "generate_image called without a prompt"
        return FAKE_PNG

    for module in (main_module, ui):
        if hasattr(module, "edge_tts_generate"):
            module.edge_tts_generate = fake_edge_tts
        if hasattr(module, "generate_image"):
            module.generate_image = fake_image


# ------------------------------------------------------------------- journey
def run_journey(client, label: str, expect_backend: str) -> Dict[str, Any]:
    print(f"\n=== {label} ===")

    # Every TestClient request comes from the same IP, so start each journey
    # with empty rate-limit buckets.
    from app import deps

    deps._rate_limits.clear()
    context: Dict[str, Any] = {}

    # --- system / health -------------------------------------------------
    health = client.get("/health").json()
    check("GET /health 200 + store backend", health.get("status") == "healthy", health)
    check(f"store backend is {expect_backend}", health.get("store", {}).get("backend") == expect_backend, health.get("store"))

    status = client.get("/api/system/status").json()
    check("GET /api/system/status", status.get("status") == "running" and status.get("voices", 0) > 50, status.get("voices"))
    check("GET /keep-alive", client.get("/keep-alive").json().get("ok") is True)

    root = client.get("/")
    check("GET / serves the web UI", root.status_code == 200 and ("BG LABS" in root.text or root.headers["content-type"].startswith("application/json")),
          root.status_code)

    # --- auth ------------------------------------------------------------
    unauth = client.get("/api/studio/audio")
    check("unauthenticated request -> 401", unauth.status_code == 401, unauth.status_code)

    email = f"owner_{int(time.time())}@example.com"
    reg = client.post("/api/auth/register", data={
        "email": email, "username": "owner", "full_name": "BG Owner", "password": "secret123",
    })
    check("POST /api/auth/register (first user = admin)", reg.status_code == 200 and reg.json().get("access_token"),
          reg.text[:200])
    token = reg.json()["access_token"]
    context["token"] = token
    check("registered user payload shape", reg.json()["user"]["role"] == "admin" and reg.json()["user"]["email"] == email,
          reg.json().get("user"))

    headers = {"Authorization": f"Bearer {token}"}
    context["headers"] = headers

    dup = client.post("/api/auth/register", data={
        "email": email, "username": "owner", "full_name": "x", "password": "secret123"})
    check("duplicate registration -> 400", dup.status_code == 400, dup.status_code)

    me = client.get("/api/auth/me", headers=headers).json()
    check("GET /api/auth/me", me.get("username") == "owner" and me.get("credits", 0) > 0, me)

    login = client.post("/api/auth/login", data={"username": "owner", "password": "secret123"})
    check("POST /api/auth/login (username)", login.status_code == 200 and login.json().get("access_token"), login.text[:200])
    login_email = client.post("/api/auth/login", data={"username": email, "password": "secret123"})
    check("POST /api/auth/login (email)", login_email.status_code == 200, login_email.text[:200])
    bad_login = client.post("/api/auth/login", data={"username": "owner", "password": "wrong-pass"})
    check("wrong password -> 401", bad_login.status_code == 401, bad_login.status_code)

    updated = client.put("/api/auth/me", headers=headers, json={"full_name": "BG Owner II"})
    check("PUT /api/auth/me", updated.json().get("full_name") == "BG Owner II", updated.text[:200])

    # --- voices ----------------------------------------------------------
    builtin = client.get("/api/voices/builtin").json()
    voices = builtin.get("voices") or []
    check("GET /api/voices/builtin", len(voices) > 50, len(voices))
    check("builtin voice shape (id/name/language/gender)",
          all(v.get("id") and v.get("name") and v.get("language") and v.get("gender") for v in voices[:10]), voices[0] if voices else None)
    check("GET /api/voices (legacy)", len(client.get("/api/voices").json().get("voices", [])) > 50)
    check("GET /api/voices/languages", len(client.get("/api/voices/languages").json().get("languages", [])) > 5)

    check("GET /api/voices/custom empty", client.get("/api/voices/custom", headers=headers).json() == [])

    clone = client.post("/api/voices/clone", headers=headers,
                        data={"name": "My Voice", "description": "test"},
                        files={"audio_file": ("sample.mp3", FAKE_MP3, "audio/mpeg")})
    check("POST /api/voices/clone", clone.status_code == 200 and clone.json().get("id"), clone.text[:200])
    custom = client.get("/api/voices/custom", headers=headers).json()
    check("custom voice listed", len(custom) == 1 and custom[0]["name"] == "My Voice", custom)

    # --- TTS studio ------------------------------------------------------
    gen = client.post("/api/studio/generate", headers=headers, json={
        "text": "Hello from the BG LABS smoke test.", "voice_key": "aria", "language": "en", "speed": 1.2})
    check("POST /api/studio/generate", gen.status_code == 200 and gen.json().get("url"), gen.text[:300])
    audio = gen.json()
    check("generate resolved 'aria' -> en-US-AriaNeural", audio.get("voice_key") == "en-US-AriaNeural", audio.get("voice_key"))
    check("generate returned inline data_uri", str(audio.get("data_uri") or "").startswith("data:audio/mpeg;base64,"),
          str(audio.get("data_uri"))[:40])

    history = client.get("/api/studio/audio", headers=headers).json()
    check("GET /api/studio/audio", isinstance(history, list) and len(history) >= 1, len(history))
    if history:
        item = history[0]
        playable = str(item.get("url", "")).startswith("http") or item.get("data_uri")
        check("history entry is playable (durable url or data_uri)", playable, {k: str(v)[:60] for k, v in item.items()})
        context["audio_id"] = item["id"]
        if str(item.get("url", "")).startswith("/"):
            served = client.get(item["url"])
            check("GET generated audio file", served.status_code == 200 and served.content[:3] == b"ID3", served.status_code)

    empty = client.post("/api/studio/generate", headers=headers, json={"text": "", "voice_key": "aria"})
    check("empty text -> 400", empty.status_code == 400, empty.status_code)

    # --- images ----------------------------------------------------------
    img = client.post("/api/image/generate", headers=headers, json={
        "prompt": "a cyberpunk city at night", "model": "dall-e-3", "style": "vivid", "size": "1792x1024", "n": 1})
    check("POST /api/image/generate", img.status_code == 200 and img.json().get("url"), img.text[:300])
    check("image size parsed", img.json().get("size") == "1792x1024", img.json().get("size"))

    gallery = client.get("/api/image/my-images", headers=headers).json()
    check("GET /api/image/my-images", isinstance(gallery, list) and len(gallery) == 1, gallery if not gallery else gallery[0]["name"])
    if gallery:
        images = gallery[0]["settings"]["images"]
        check("gallery image entry", len(images) >= 1 and (images[0].get("url") or images[0].get("data_uri")), images[0] if images else None)

    saved = client.post("/api/image/save", headers=headers, json={
        "prompt": "saved externally", "image_url": "https://example.com/x.png", "model": "dall-e-3", "size": "1024x1024"})
    check("POST /api/image/save", saved.status_code == 200 and saved.json().get("ok") is True, saved.text[:200])

    styles = client.get("/api/image/styles").json()
    check("GET /api/image/styles", len(styles.get("styles", [])) >= 10, len(styles.get("styles", [])))
    check("GET /api/image/history", isinstance(client.get("/api/image/history", headers=headers).json(), list))

    # --- scripts ---------------------------------------------------------
    script = client.post("/api/script/generate", headers=headers, json={
        "topic": "How solar panels work", "template": "youtube", "style": "conversational",
        "tone": "friendly", "target_length": "medium", "target_audience": "beginners", "language": "english"})
    check("POST /api/script/generate", script.status_code == 200 and script.json().get("script"), script.text[:200])
    check("script word_count", script.json().get("word_count", 0) > 10, script.json().get("word_count"))
    project_id = script.json().get("project_id")
    check("script project_id returned", bool(project_id), script.json().keys())

    projects = client.get("/api/script/projects", headers=headers).json()
    check("GET /api/script/projects", isinstance(projects, list) and len(projects) >= 1, len(projects))
    check("project has topic in settings", projects[0]["settings"].get("topic") == "How solar panels work", projects[0]["settings"].keys())

    one = client.get(f"/api/script/projects/{project_id}", headers=headers).json()
    check("GET /api/script/projects/{id}", bool(one.get("settings", {}).get("script_content")), list(one.keys()))

    edit = client.post(f"/api/script/projects/{project_id}", headers=headers, json={"script_content": "edited script body"})
    check("POST /api/script/projects/{id} (update)", edit.json().get("settings", {}).get("script_content") == "edited script body",
          edit.text[:200])

    export = client.get(f"/api/script/projects/{project_id}/export?format=json", headers=headers).json()
    check("GET export?format=json", export.get("filename", "").endswith(".json") and "edited script body" in export.get("content", ""),
          export.get("filename"))
    export_txt = client.get(f"/api/script/projects/{project_id}/export?format=txt", headers=headers).json()
    check("GET export?format=txt", export_txt.get("filename", "").endswith(".txt"), export_txt.get("filename"))

    legacy_write = client.post("/api/script/write", headers=headers, json={"topic": "AI in Pakistan", "genre": "podcast", "length": "short"})
    check("POST /api/script/write (legacy)", legacy_write.status_code == 200 and legacy_write.json().get("script"), legacy_write.text[:200])

    # --- avatars ---------------------------------------------------------
    avatar = client.post("/api/avatar/create", headers=headers, data={
        "name": "News Anchor Avatar", "description": "smoke test", "avatar_type": "news_anchor", "background": "news_studio"})
    check("POST /api/avatar/create", avatar.status_code == 200 and avatar.json().get("id"), avatar.text[:300])
    check("avatar svg returned", "<svg" in str(avatar.json().get("svg", "")), str(avatar.json().get("svg"))[:40])

    avatar_projects = client.get("/api/avatar/projects", headers=headers).json()
    check("GET /api/avatar/projects", len(avatar_projects) == 1 and avatar_projects[0]["settings"].get("avatar_type") == "news_anchor",
          avatar_projects[0]["settings"].keys() if avatar_projects else None)

    legacy_avatar = client.post("/api/avatar/generate", headers=headers, json={"avatar_type": "social_media"})
    check("POST /api/avatar/generate (legacy)", legacy_avatar.status_code == 200 and "<svg" in legacy_avatar.json().get("svg", ""),
          legacy_avatar.text[:150])

    # --- youtube automation ---------------------------------------------
    yt = client.post("/api/youtube/full-automation", headers=headers, json={
        "topic": "Top 5 AI tools", "voice_key": "guy", "style": "educational", "length": "short", "include_thumbnail": True})
    check("POST /api/youtube/full-automation", yt.status_code == 200 and yt.json().get("project_id"), yt.text[:400])
    yt_json = yt.json()
    check("youtube: script + voiceover", bool(yt_json.get("script")) and bool(yt_json.get("audio_url")), yt_json.get("steps"))
    check("youtube: thumbnail generated", bool(yt_json.get("thumbnail_url")), yt_json.get("steps"))

    yt_projects = client.get("/api/youtube/projects", headers=headers).json()
    check("GET /api/youtube/projects", len(yt_projects) == 1 and yt_projects[0]["settings"].get("topic") == "Top 5 AI tools",
          yt_projects[0]["settings"].keys() if yt_projects else None)

    # --- voice profiles (legacy) ----------------------------------------
    profile = client.post("/api/voice-clone/create", headers=headers, json={"name": "Legacy profile", "base_voice": "jenny"})
    check("POST /api/voice-clone/create", profile.status_code == 200 and profile.json().get("base_voice") == "en-US-JennyNeural",
          profile.text[:200])
    profiles = client.get("/api/voice-clone/list", headers=headers).json()
    check("GET /api/voice-clone/list", len(profiles) >= 2, len(profiles))
    if profiles:
        clone_gen = client.post("/api/voice-clone/generate", headers=headers, json={
            "text": "Speaking with my profile voice.", "profile_id": profiles[0]["id"]})
        check("POST /api/voice-clone/generate", clone_gen.status_code == 200 and clone_gen.json().get("url"), clone_gen.text[:200])

    # --- billing / referral / admin --------------------------------------
    plans = client.get("/api/billing/plans").json()
    check("GET /api/billing/plans", len(plans.get("plans", {})) >= 4 and all("monthly_price" in p and "features" in p for p in plans["plans"].values()),
          list(plans.get("plans", {}).keys()))
    current = client.get("/api/billing/current", headers=headers).json()
    check("GET /api/billing/current", current.get("tier") == "free" and current.get("status") == "active", current)

    ref_code = client.get("/api/referral/my-code", headers=headers).json()
    check("GET /api/referral/my-code", bool(ref_code.get("referral_code")) and "ref=" in ref_code.get("referral_link", ""), ref_code)
    ref_stats = client.get("/api/referral/stats", headers=headers).json()
    check("GET /api/referral/stats", all(k in ref_stats for k in ("total_referrals", "active_referrals", "total_credits_generated", "pending_payout")),
          ref_stats.keys())
    ref_list = client.get("/api/referral/my-referrals", headers=headers).json()
    check("GET /api/referral/my-referrals", isinstance(ref_list.get("referrals"), list), ref_list.keys())
    check("GET /api/referral/code (legacy)", bool(client.get("/api/referral/code", headers=headers).json().get("referral_code")))

    admin_stats = client.get("/api/admin/stats", headers=headers).json()
    check("GET /api/admin/stats", admin_stats.get("total_users", 0) >= 1 and "total_audio_generated" in admin_stats, admin_stats)
    admin_users = client.get("/api/admin/users", headers=headers).json()
    check("GET /api/admin/users", isinstance(admin_users, list) and admin_users[0].get("referrals_count") == 0, admin_users[:1])

    second = client.post("/api/auth/register", data={
        "email": f"member_{int(time.time())}@example.com", "username": "member", "full_name": "Member", "password": "secret123",
        "referral_code": ref_code["referral_code"]})
    check("register second user with referral code", second.status_code == 200 and second.json()["user"]["role"] == "user",
          second.text[:200])
    member_headers = {"Authorization": f"Bearer {second.json()['access_token']}"}
    forbidden = client.get("/api/admin/stats", headers=member_headers)
    check("non-admin -> 403 on admin stats", forbidden.status_code == 403, forbidden.status_code)
    referrers = client.get("/api/referral/my-referrals", headers=headers).json()
    check("referral tracked for the admin", referrers.get("total") == 1, referrers)

    promote = client.put(f"/api/admin/users/{second.json()['user']['id']}", headers=headers, json={"role": "creator", "credits": 500})
    check("PUT /api/admin/users/{id}", promote.json().get("role") == "creator" and promote.json().get("credits") == 500, promote.text[:200])

    dash = client.get("/api/dashboard/stats", headers=headers).json()
    check("GET /api/dashboard/stats", dash.get("projects", 0) >= 3 and "recent" in dash, {k: v for k, v in dash.items() if k != "recent"})

    # --- cleanup ---------------------------------------------------------
    if context.get("audio_id"):
        deleted = client.delete(f"/api/studio/audio/{context['audio_id']}", headers=headers)
        check("DELETE /api/studio/audio/{id}", deleted.status_code == 200, deleted.status_code)
        again = client.delete(f"/api/studio/audio/{context['audio_id']}", headers=headers)
        check("DELETE twice -> 404", again.status_code == 404, again.status_code)

    voice_deleted = client.delete(f"/api/voices/{custom[0]['id']}", headers=headers)
    check("DELETE /api/voices/{id}", voice_deleted.status_code == 200, voice_deleted.status_code)

    return context


def main() -> int:
    from fastapi.testclient import TestClient

    install_stubs()

    # ---------------------------------------------------------- memory run
    for var in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        os.environ.pop(var, None)
    import main as main_module
    from app import store as store_module

    client = TestClient(main_module.app)
    with client:
        run_journey(client, "backend: memory (no database configured)", "memory")

    # -------------------------------------------------------- supabase run
    port = _free_port()
    server, mock = start_mock_supabase(port)
    try:
        os.environ["SUPABASE_URL"] = f"http://127.0.0.1:{port}"
        os.environ["SUPABASE_SERVICE_KEY"] = "test-key"
        os.environ["SUPABASE_STORAGE_BUCKET"] = "bglabs-media"

        import asyncio

        asyncio.run(store_module.reset_store())
        client = TestClient(main_module.app)
        with client:
            context = run_journey(client, "backend: supabase (mock PostgREST + Storage)", "supabase")

        # verify the durable storage path really was used
        import httpx

        stats = httpx.get(f"http://127.0.0.1:{port}/_mock/stats", timeout=10).json()
        check("supabase: rows persisted in tables", stats["tables"]["bglabs_users"] >= 2 and stats["tables"]["bglabs_projects"] >= 3, stats["tables"])
        check("supabase: media uploaded to Storage", stats["objects"] >= 3, stats["objects"])

        public = httpx.get(f"http://127.0.0.1:{port}/storage/v1/object/public/bglabs-media/audio/x.mp3", timeout=10)
        check("supabase: unknown object -> 404", public.status_code == 404, public.status_code)

        bad_key = httpx.get(f"http://127.0.0.1:{port}/rest/v1/bglabs_users?select=*&limit=1",
                            headers={"apikey": "wrong", "Authorization": "Bearer wrong"}, timeout=10)
        check("supabase: wrong api key -> 401", bad_key.status_code == 401, bad_key.status_code)
    finally:
        server.should_exit = True
        time.sleep(0.4)

    print("\n" + "=" * 62)
    print(f"checks: {checks}   failures: {len(failures)}")
    for failure in failures:
        print(f"  - {failure}")
    print("=" * 62)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
