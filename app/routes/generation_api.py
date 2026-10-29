"""Unified model, key-vault, browsing and generation API."""
from __future__ import annotations

import json
import mimetypes
import os
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app import browse, integrations, keyvault, providers
from app.deps import RATE_LIMIT_GENERATE, check_rate_limit, get_client_ip, get_current_user
from app.media import save_media
from app.store import get_store

router = APIRouter(prefix="/api", tags=["AI Models & Generation"])
JOB_TYPE = "generation_job"
MAX_HISTORY = 100


def _fail(exc):
    if isinstance(exc, (providers.ProviderError, browse.BrowseError)):
        raise HTTPException(status_code=exc.status_code, detail=exc.as_dict())
    raise exc


async def _context(request: Request):
    user = await get_current_user(request)
    store = await get_store()
    keys = await keyvault.load_keys(store, user["id"])
    return user, store, keys


def _safe_job(job: Dict[str, Any]) -> Dict[str, Any]:
    clean = dict(job or {})
    # Inputs can contain data URIs. They are not needed for polling and would
    # make project rows huge; metadata and public URLs are enough.
    inputs = clean.get("input")
    if isinstance(inputs, dict):
        clean["input"] = {k: ("[inline media]" if isinstance(v, str) and v.startswith("data:") else v)
                          for k, v in inputs.items()}
    return clean


async def _persist_job(store, user, entry, job, request_body):
    row = await store.add_project(
        user_id=user["id"], name=f"{entry['label']}: {str(request_body.get('prompt') or request_body.get('text') or 'job')[:60]}",
        project_type=JOB_TYPE,
        settings={"job": _safe_job(job), "capability": entry["capability"], "model_id": entry["id"],
                  "request": {k: v for k, v in request_body.items()
                              if k not in ("image_data", "audio_data", "video_data") and
                              not (isinstance(v, str) and v.startswith("data:"))}},
    )
    return row


async def _save_result(store, user, result, capability, prompt=""):
    data = result.pop("bytes", None)
    if not data:
        return result
    mime = result.get("mime") or "application/octet-stream"
    kind = "images" if mime.startswith("image/") else ("audio" if mime.startswith("audio/") else "video")
    ext = mimetypes.guess_extension(mime) or {"images": ".png", "audio": ".mp3", "video": ".mp4"}[kind]
    filename = f"{uuid.uuid4().hex}{ext}"
    saved = await save_media(store, kind, filename, data, mime, inline=len(data) <= 2_000_000)
    result.update({"url": saved.get("url"), "data_uri": saved.get("data_uri"),
                   "stored": saved.get("stored"), "bytes": saved.get("bytes"), "filename": filename})
    try:
        if kind == "images":
            await store.add_image(user_id=user["id"], prompt=prompt[:1000], style="model-router",
                                  filename=filename, url=saved["url"] if saved["stored"] == "storage" else "",
                                  model=result.get("model_id", ""), size="",
                                  data_uri=None if saved["stored"] == "storage" else saved.get("data_uri"))
        elif kind == "audio":
            await store.add_audio(user_id=user["id"], text=prompt[:2000], voice=result.get("voice", ""),
                                  engine=result.get("model_id", ""), filename=filename,
                                  url=saved["url"] if saved["stored"] == "storage" else "",
                                  chars=len(prompt),
                                  data_uri=None if saved["stored"] == "storage" else saved.get("data_uri"))
    except Exception:
        pass
    return result


@router.get("/models")
async def models(request: Request, capability: Optional[str] = None):
    user, store, keys = await _context(request)
    vault, _ = await keyvault.vault_status(store, user["id"])
    return {"models": providers.catalog(capability, keys), "status": providers.provider_status(keys),
            "capabilities": list(providers.CAPABILITIES), "keys": vault,
            "defaults": {c: providers.default_id(c, keys) for c in providers.CAPABILITIES}}


@router.get("/integrations")
async def integration_registry(request: Request, category: Optional[str] = None):
    await get_current_user(request)
    return {"integrations": integrations.catalog(category), "summary": integrations.summary(),
            "deployment_truth": "GPU/desktop repos run through hosted or self-hosted adapters; Vercel runs orchestration and APIs."}


@router.get("/providers/status")
async def provider_status(request: Request):
    user, store, keys = await _context(request)
    vault, _ = await keyvault.vault_status(store, user["id"])
    return {"providers": providers.provider_status(keys), "vault": vault}


@router.get("/providers/keys")
async def keys_status(request: Request):
    user, store, _ = await _context(request)
    rows, _ = await keyvault.vault_status(store, user["id"])
    return {"keys": rows, "count": len(rows), "warning": "Values are never returned; only masked last four characters."}


@router.put("/providers/keys/{name}")
async def put_key(name: str, request: Request):
    user, store, _ = await _context(request)
    body = await request.json()
    try:
        saved = await keyvault.save_key(store, user["id"], name, str(body.get("value") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"saved": saved, "message": f"{name.upper()} active for your account."}


@router.delete("/providers/keys/{name}")
async def remove_key(name: str, request: Request):
    user, store, _ = await _context(request)
    deleted = await keyvault.delete_key(store, user["id"], name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"deleted": True, "name": name.upper()}


@router.get("/models/{model_id}/voices")
async def model_voices(model_id: str, request: Request):
    await get_current_user(request)
    entry = providers.by_id(model_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Model not found")
    return {"model_id": model_id, "voices": providers.voices_for(model_id),
            "languages": providers.languages_for(model_id)}


@router.post("/generate/{capability}")
async def generate(capability: str, request: Request):
    user, store, keys = await _context(request)
    if capability not in providers.CAPABILITIES:
        raise HTTPException(status_code=404, detail=f"Unknown capability: {capability}")
    if not check_rate_limit(get_client_ip(request), f"generate:{capability}", RATE_LIMIT_GENERATE, 60):
        raise HTTPException(status_code=429, detail="Generation rate limit reached")
    body = await request.json()
    model = body.pop("model", None) or body.pop("model_id", None)
    try:
        entry = providers.resolve(capability, model, keys)
        result = await providers.run(entry, body, keys, {"user_id": user["id"]})
    except Exception as exc:
        _fail(exc)
    if result.get("job"):
        row = await _persist_job(store, user, entry, result["job"], body)
        result["job_id"] = row["id"]
    result = await _save_result(store, user, result, capability,
                                str(body.get("prompt") or body.get("text") or ""))
    result.setdefault("model_id", entry["id"])
    result.setdefault("label", entry["label"])
    return result


@router.get("/generation/jobs")
async def list_jobs(request: Request, limit: int = 50):
    user, store, _ = await _context(request)
    rows = await store.list_projects(user["id"], project_type=JOB_TYPE, limit=max(1, min(MAX_HISTORY, limit)))
    return {"jobs": rows, "count": len(rows)}


@router.get("/generation/jobs/{job_id}")
async def poll_generation_job(job_id: int, request: Request):
    user, store, keys = await _context(request)
    row = await store.get_project(job_id, user["id"])
    if not row or row.get("project_type") != JOB_TYPE:
        raise HTTPException(status_code=404, detail="Job not found")
    settings = row.get("settings") or {}
    try:
        job = await providers.poll_job(settings.get("job") or {}, keys)
    except Exception as exc:
        _fail(exc)
    settings["job"] = _safe_job(job)
    await store.update_project(job_id, user["id"], settings=settings)
    return {"id": job_id, "job": job, "done": job.get("status") in ("succeeded", "failed", "canceled")}


@router.delete("/generation/jobs/{job_id}")
async def delete_generation_job(job_id: int, request: Request):
    user, store, _ = await _context(request)
    row = await store.get_project(job_id, user["id"])
    if not row or row.get("project_type") != JOB_TYPE:
        raise HTTPException(status_code=404, detail="Job not found")
    await store.delete_project(job_id, user["id"])
    return {"deleted": True}


@router.post("/browse/snapshot")
async def browse_snapshot(request: Request):
    await get_current_user(request)
    body = await request.json()
    try:
        return await browse.snapshot(str(body.get("url") or ""), max_chars=int(body.get("max_chars") or 20000))
    except Exception as exc:
        _fail(exc)


@router.post("/browse/search")
async def browse_search(request: Request):
    await get_current_user(request)
    body = await request.json()
    try:
        results = await browse.search(str(body.get("query") or ""), max_results=min(12, int(body.get("limit") or 8)))
        return {"query": body.get("query"), "results": results, "count": len(results)}
    except Exception as exc:
        _fail(exc)


@router.post("/browse/research")
async def browse_research(request: Request):
    await get_current_user(request)
    body = await request.json()
    try:
        return await browse.research(str(body.get("topic") or ""), urls=body.get("urls"),
                                     max_pages=min(8, int(body.get("max_pages") or 4)),
                                     angle=str(body.get("angle") or ""))
    except Exception as exc:
        _fail(exc)
