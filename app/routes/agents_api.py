"""
BG LABS - AI agents API
=======================

Endpoints the "AI Agents" page of the web UI uses:

* ``GET    /api/agents``                 -> registry + active provider info
* ``GET    /api/agents/status``          -> provider/model configuration
* ``POST   /api/agents/{agent_id}/run``  -> run one skilled agent
* ``POST   /api/agents/autopilot``       -> multi-agent pipeline
* ``GET    /api/agents/runs``            -> saved agent runs (history)
* ``DELETE /api/agents/runs/{run_id}``   -> delete a run

Agent runs are persisted as project rows with ``project_type='agent_run'`` so the
same store abstraction (Supabase / PostgreSQL / memory) covers them with no
extra schema.

Two agents can also produce real media, because the platform already has free
engines for it:

* ``thumbnail`` with ``render=yes``   -> renders the concept with Pollinations
* ``voice_director`` with ``preview=yes`` -> synthesises a sample with Edge-TTS
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from app import agents as agent_core
from app.deps import (
    RATE_LIMIT_GENERATE,
    check_rate_limit,
    get_client_ip,
    get_current_user,
)
from app.engines import generate_image, guess_content_type, image_extension
from app.media import save_media
from app.store import StoreError, get_store
from tts_engine import edge_tts_generate, resolve_voice_key

logger = logging.getLogger("bglabs.agents.api")

router = APIRouter(tags=["AI Agents"])

RUN_TYPE = "agent_run"
AGENT_RATE_LIMIT = int(os.getenv("RATE_LIMIT_AGENT", str(RATE_LIMIT_GENERATE)))
MAX_HISTORY = 50


# ============================================================================
# helpers
# ============================================================================
def _payload_from_body(body: Dict[str, Any]) -> Dict[str, Any]:
    """Accept both ``{"payload": {...}}`` and flat field maps from the UI."""
    if isinstance(body.get("payload"), dict):
        merged = dict(body["payload"])
        for key, value in body.items():
            if key not in ("payload", "agent", "agent_id", "provider", "model") and key not in merged:
                merged[key] = value
        return merged
    return {k: v for k, v in body.items() if k not in ("agent", "agent_id", "provider", "model", "save")}


def _requested_provider(body: Dict[str, Any]) -> Optional[str]:
    value = str(body.get("provider") or "").strip().lower()
    if not value or value in ("auto", "default"):
        return None
    if value != "builtin" and value not in agent_core.PROVIDER_ORDER:
        raise HTTPException(400, f"Unknown provider '{value}'. "
                                 f"Valid: auto, builtin, {', '.join(agent_core.PROVIDER_ORDER)}")
    return value


async def _remember_run(store: Any, user: Dict[str, Any], envelope: Dict[str, Any],
                        payload: Dict[str, Any]) -> Optional[int]:
    """Persist an agent run so the UI can show history. Never fails the request."""
    if isinstance(store, type(None)):
        return None
    try:
        project = await store.add_project(
            user_id=user["id"],
            name=f"{envelope.get('name', envelope.get('agent', 'agent'))}: "
                 f"{str(payload.get('topic') or payload.get('comments') or payload.get('goal') or 'run')[:60]}",
            project_type=RUN_TYPE,
            settings={
                "agent": envelope.get("agent"),
                "agent_name": envelope.get("name"),
                "emoji": envelope.get("emoji"),
                "engine": envelope.get("engine"),
                "provider": envelope.get("provider"),
                "model": envelope.get("model"),
                "payload": {k: (str(v)[:2000]) for k, v in payload.items()},
                "result": envelope.get("result"),
                "created_at": envelope.get("created_at"),
            },
        )
        return int(project.get("id") or 0) or None
    except (StoreError, ValueError, KeyError, TypeError) as exc:
        logger.warning("could not save agent run: %s", exc)
        return None


async def _render_thumbnail(store: Any, user: Dict[str, Any], result: Dict[str, Any],
                            topic: str) -> Dict[str, Any]:
    prompt = str(result.get("image_prompt") or (result.get("best_concept") or {}).get("prompt") or topic)[:900]
    if not prompt:
        return {"status": "failed", "error": "No image prompt available"}
    try:
        data = await generate_image(prompt, style="cinematic", width=1280, height=720, model="dall-e-3")
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("thumbnail render failed: %s", exc)
        return {"status": "failed", "error": str(exc)}
    content_type = guess_content_type(data)
    filename = f"{uuid.uuid4().hex}{image_extension(content_type)}"
    saved = await save_media(store, "images", filename, data, content_type)
    stored = saved.get("stored") == "storage"
    try:
        await store.add_image(
            user_id=user["id"], prompt=f"AI thumbnail: {topic[:200]}", style="cinematic",
            filename=filename, url=saved["url"] if stored else "", model="dall-e-3", size="1280x720",
            data_uri=None if stored else saved.get("data_uri"),
        )
    except StoreError:
        pass
    return {"status": "done", "url": saved.get("url"), "data_uri": saved.get("data_uri"),
            "filename": filename, "width": 1280, "height": 720}


async def _voice_preview(store: Any, user: Dict[str, Any], result: Dict[str, Any],
                         payload: Dict[str, Any]) -> Dict[str, Any]:
    script = str(payload.get("script") or result.get("direction") or payload.get("topic") or "")[:400]
    if not script:
        return {"status": "failed", "error": "Nothing to speak - add a script or topic"}
    voice_key = resolve_voice_key(result.get("recommended_voice"), payload.get("language") or "en")
    rate = str(result.get("rate") or "+0%")
    pitch = str(result.get("pitch") or "+0Hz")
    try:
        data = await edge_tts_generate(script, voice=voice_key, rate=rate, pitch=pitch)
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("voice preview failed: %s", exc)
        return {"status": "failed", "error": str(exc)}
    filename = f"voice-preview-{uuid.uuid4().hex}.mp3"
    saved = await save_media(store, "audio", filename, data, "audio/mpeg")
    stored = saved.get("stored") == "storage"
    try:
        await store.add_audio(
            user_id=user["id"], text=script, voice=voice_key, engine="edge-tts", filename=filename,
            url=saved["url"] if stored else "", data_uri=None if stored else saved.get("data_uri"),
            chars=len(script),
        )
    except StoreError:
        pass
    return {"status": "done", "url": saved.get("url"), "data_uri": saved.get("data_uri"),
            "filename": filename, "voice_key": voice_key, "rate": rate, "pitch": pitch,
            "chars": len(script)}


# ============================================================================
# routes
# ============================================================================
@router.get("/api/agents")
async def list_agents(request: Request) -> Dict[str, Any]:
    """Agent registry + what is powering them right now."""
    user = await get_current_user(request)
    store = await get_store()
    try:
        runs = await store.list_projects(user["id"], project_type=RUN_TYPE, limit=MAX_HISTORY)
        run_count = len(runs)
    except Exception:  # pragma: no cover - store specific
        run_count = 0
    return {
        "agents": agent_core.public_agents(),
        "provider": agent_core.provider_status(),
        "autopilot": {
            "id": "autopilot",
            "name": "Auto Pilot",
            "emoji": "\U0001f916",
            "tagline": "Runs the whole team on one topic: strategy -> script -> voice -> thumbnail -> SEO.",
            "steps": list(agent_core.AUTOPILOT_STEPS),
        },
        "runs_saved": run_count,
        "storage": store.status() if hasattr(store, "status") else {"name": getattr(store, "name", "unknown")},
    }


@router.get("/api/agents/status")
async def agents_status(request: Request) -> Dict[str, Any]:
    await get_current_user(request)
    return agent_core.provider_status()


@router.post("/api/agents/{agent_id}/run")
async def run_agent(request: Request, agent_id: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    ip = get_client_ip(request)
    if not check_rate_limit(ip, f"agent:{agent_id}", AGENT_RATE_LIMIT, 60):
        raise HTTPException(429, "Too many agent runs. Please wait a minute.")

    agent = agent_core.AGENT_BY_ID.get((agent_id or "").strip().lower())
    if not agent:
        known = ", ".join(sorted(agent_core.AGENT_BY_ID))
        raise HTTPException(404, f"Unknown agent '{agent_id}'. Available: {known}")

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    payload = _payload_from_body(body)
    provider = _requested_provider(body)
    model = str(body.get("model") or "").strip() or None
    store = await get_store()

    try:
        envelope = await agent_core.run_agent(agent["id"], payload, provider=provider, model=model)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None

    result = envelope.get("result") if isinstance(envelope.get("result"), dict) else {}

    # optional real media output
    if agent.get("can_render") and str(payload.get("render", "")).lower() in ("yes", "true", "1"):
        result["rendered"] = await _render_thumbnail(store, user, result, str(payload.get("topic", "")))
        envelope["result"] = result
    if agent.get("can_speak") and str(payload.get("preview", "")).lower() in ("yes", "true", "1"):
        result["sample"] = await _voice_preview(store, user, result, payload)
        envelope["result"] = result

    run_id = None
    if str(body.get("save", "yes")).lower() not in ("no", "false", "0"):
        run_id = await _remember_run(store, user, envelope, payload)
    envelope["run_id"] = run_id
    return envelope


@router.post("/api/agents/autopilot")
async def autopilot(request: Request) -> Dict[str, Any]:
    """The multi-agent pipeline: one topic in, a complete video package out."""
    user = await get_current_user(request)
    ip = get_client_ip(request)
    if not check_rate_limit(ip, "autopilot", 5, 300):
        raise HTTPException(429, "Auto Pilot is limited to 5 runs per 5 minutes.")

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    topic = str(body.get("topic") or "").strip()
    if not topic:
        raise HTTPException(400, "Topic is required for Auto Pilot")

    steps = body.get("steps")
    if isinstance(steps, list):
        steps = [str(s).strip().lower() for s in steps if str(s).strip().lower() in agent_core.AGENT_BY_ID]
    provider = _requested_provider(body)
    store = await get_store()

    try:
        outcome = await agent_core.run_autopilot(
            {
                "topic": topic,
                "audience": body.get("audience"),
                "goal": body.get("goal"),
                "tone": body.get("tone"),
                "mood": body.get("mood"),
                "language": body.get("language"),
                "length": body.get("length"),
                "template": body.get("template"),
                "context": body.get("context"),
                "keyword": body.get("keyword"),
            },
            provider=provider, steps=steps or None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None

    package = outcome.get("package") or {}

    # Optional: actually produce the media the plan describes.
    if str(body.get("generate_voiceover", "")).lower() in ("yes", "true", "1"):
        script_text = str(package.get("script") or "")[:4000]
        if script_text:
            voice = (package.get("voice") or {}).get("voice_key") or "aria"
            try:
                data = await edge_tts_generate(script_text, voice=resolve_voice_key(voice))
                filename = f"autopilot-{uuid.uuid4().hex}.mp3"
                saved = await save_media(store, "audio", filename, data, "audio/mpeg")
                stored = saved.get("stored") == "storage"
                package["audio"] = {"url": saved.get("url"), "data_uri": saved.get("data_uri"),
                                    "filename": filename, "voice": voice}
                try:
                    await store.add_audio(
                        user_id=user["id"], text=script_text, voice=voice, engine="edge-tts",
                        filename=filename, url=saved["url"] if stored else "",
                        data_uri=None if stored else saved.get("data_uri"), chars=len(script_text),
                    )
                except StoreError:
                    pass
                outcome["steps_done"] = (outcome.get("steps_done") or []) + ["voiceover"]
            except Exception as exc:  # pragma: no cover - network dependent
                logger.warning("autopilot voiceover failed: %s", exc)
                package["audio"] = {"status": "failed", "error": str(exc)}

    if str(body.get("generate_thumbnail", "")).lower() in ("yes", "true", "1"):
        prompt = str((package.get("thumbnail") or {}).get("prompt") or "")
        if prompt:
            try:
                data = await generate_image(prompt, style="cinematic", width=1280, height=720, model="dall-e-3")
                content_type = guess_content_type(data)
                filename = f"{uuid.uuid4().hex}{image_extension(content_type)}"
                saved = await save_media(store, "images", filename, data, content_type)
                stored = saved.get("stored") == "storage"
                package["thumbnail"]["url"] = saved.get("url")
                package["thumbnail"]["data_uri"] = saved.get("data_uri")
                package["thumbnail"]["filename"] = filename
                try:
                    await store.add_image(
                        user_id=user["id"], prompt=f"Auto Pilot thumbnail: {topic[:200]}", style="cinematic",
                        filename=filename, url=saved["url"] if stored else "", model="dall-e-3",
                        size="1280x720", data_uri=None if stored else saved.get("data_uri"),
                    )
                except StoreError:
                    pass
                outcome["steps_done"] = (outcome.get("steps_done") or []) + ["thumbnail"]
            except Exception as exc:  # pragma: no cover - network dependent
                logger.warning("autopilot thumbnail failed: %s", exc)
                package["thumbnail"]["error"] = str(exc)

    outcome["package"] = package
    run_id = await _remember_run(store, user, {
        "agent": "autopilot", "name": "Auto Pilot", "emoji": "\U0001f916",
        "engine": "+".join(outcome.get("engine_mix") or ["builtin"]),
        "provider": "+".join(outcome.get("providers") or ["builtin"]),
        "model": outcome.get("model", ""),
        "result": {"package": package, "steps": outcome.get("steps"),
                   "seconds": outcome.get("seconds"), "next_actions": outcome.get("next_actions")},
        "created_at": outcome.get("created_at"),
    }, {"topic": topic})
    outcome["run_id"] = run_id
    return outcome


@router.get("/api/agents/runs")
async def agent_runs(request: Request, limit: int = 20) -> List[Dict[str, Any]]:
    user = await get_current_user(request)
    store = await get_store()
    rows = await store.list_projects(user["id"], project_type=RUN_TYPE, limit=max(1, min(MAX_HISTORY, limit)))
    runs = []
    for row in rows:
        settings = row.get("settings") or {}
        runs.append({
            "id": row.get("id"),
            "agent": settings.get("agent"),
            "agent_name": settings.get("agent_name") or settings.get("agent"),
            "emoji": settings.get("emoji", ""),
            "engine": settings.get("engine"),
            "provider": settings.get("provider"),
            "model": settings.get("model"),
            "title": row.get("name"),
            "payload": settings.get("payload") or {},
            "result": settings.get("result") or {},
            "created_at": row.get("created_at") or settings.get("created_at"),
        })
    return runs


@router.get("/api/agents/runs/{run_id}")
async def agent_run_detail(request: Request, run_id: int) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    row = await store.get_project(run_id, user["id"])
    if not row or row.get("project_type") != RUN_TYPE:
        raise HTTPException(404, "Agent run not found")
    return {"id": row.get("id"), "name": row.get("name"),
            "created_at": row.get("created_at"), "settings": row.get("settings") or {}}


@router.delete("/api/agents/runs/{run_id}")
async def agent_run_delete(request: Request, run_id: int) -> Dict[str, Any]:
    user = await get_current_user(request)
    store = await get_store()
    row = await store.get_project(run_id, user["id"])
    if not row or row.get("project_type") != RUN_TYPE:
        raise HTTPException(404, "Agent run not found")
    await store.delete_project(run_id, user["id"])
    return {"deleted": True, "id": run_id}
