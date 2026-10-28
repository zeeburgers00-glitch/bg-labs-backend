"""ViMax agentic video studio API."""
from __future__ import annotations

from typing import Any, Dict
from datetime import datetime, timezone
import os

from fastapi import APIRouter, HTTPException, Request

from app import keyvault, providers, timeline, vimax
from app.deps import RATE_LIMIT_GENERATE, check_rate_limit, get_client_ip, get_current_user
from app.store import get_store

router = APIRouter(prefix="/api/vimax", tags=["ViMax Video Studio"])
PROJECT_TYPE = "vimax_project"
MAX_PROJECTS = 50


async def _ctx(request):
    user = await get_current_user(request)
    store = await get_store()
    keys = await keyvault.load_keys(store, user["id"])
    return user, store, keys


def _error(exc):
    if isinstance(exc, (vimax.ViMaxError, providers.ProviderError)):
        raise HTTPException(status_code=exc.status_code, detail=exc.as_dict())
    raise exc


def _project_body(row):
    settings = row.get("settings") or {}
    return {"id": row["id"], "name": row.get("name"), "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"), **settings}


def _find_shot(result: Dict[str, Any], shot_id: str):
    for shot in result.get("shots") or []:
        if str(shot.get("id")) == str(shot_id):
            return shot
    return None



DEFAULT_DAILY_ATTEMPT_CAP = 10
DAILY_ATTEMPT_SCAN_LIMIT = 100


def _daily_cap() -> int:
    """Fail closed to a modest daily cap; a bad setting cannot disable it."""
    try:
        return max(1, min(50, int(os.getenv("VIMAX_DAILY_ATTEMPT_CAP", str(DEFAULT_DAILY_ATTEMPT_CAP)))))
    except (TypeError, ValueError):
        return DEFAULT_DAILY_ATTEMPT_CAP


async def _daily_usage(store, user_id: int):
    """Count this user's ViMax attempts created today (UTC), including failed/running attempts."""
    today = datetime.now(timezone.utc).date().isoformat()
    rows = await store.list_projects(user_id, project_type=PROJECT_TYPE, limit=DAILY_ATTEMPT_SCAN_LIMIT)
    used = 0
    for row in rows:
        settings = row.get("settings") or {}
        attempt_day = settings.get("attempt_date") or str(row.get("created_at") or "")[:10]
        if str(attempt_day)[:10] == today:
            used += 1
    return today, used


async def _reserve_daily_attempt(store, user_id: int, pipeline: str):
    today, used = await _daily_usage(store, user_id)
    cap = _daily_cap()
    if used >= cap:
        raise HTTPException(
            status_code=429,
            detail=f"Daily ViMax attempt cap reached ({used}/{cap} UTC). Try again after midnight UTC.",
        )
    reservation = await store.add_project(
        user_id=user_id,
        name=f"{pipeline} attempt",
        project_type=PROJECT_TYPE,
        settings={"pipeline": pipeline, "status": "running", "attempt": True, "attempt_date": today, "version": 1},
    )
    return reservation, today, used + 1


@router.get("")
async def vimax_home(request: Request):
    user, store, keys = await _ctx(request)
    today, used = await _daily_usage(store, user["id"])
    cap = _daily_cap()
    return {"pipelines": vimax.pipelines(), "defaults": vimax.DEFAULTS,
            "models": {capability: providers.catalog(capability, keys) for capability in ("chat", "image", "tts", "video", "render")},
            "daily_attempts": {"limit": cap, "used_today": used, "remaining": max(0, cap - used),
                               "day_utc": today, "reset": "00:00 UTC"},
            "source": "https://github.com/HKUDS/ViMax",
            "note": "A daily attempt cap is enforced. Planning can use the built-in engine; hosted provider quotas and billing still apply."}


@router.post("/{pipeline}/run")
async def run_pipeline(pipeline: str, request: Request):
    user, store, keys = await _ctx(request)
    if pipeline not in vimax.PIPELINES:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    if not check_rate_limit(get_client_ip(request), f"vimax:{pipeline}", max(4, RATE_LIMIT_GENERATE // 3), 60):
        raise HTTPException(status_code=429, detail="ViMax rate limit reached")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON request body.") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="ViMax request body must be a JSON object.")
    # A full project is expensive; explicit flags control GPU work. Planning,
    # script and storyboard always run and remain useful with zero keys.
    body.setdefault("generate_images", False)
    body.setdefault("render_video", False)
    body.setdefault("generate_voiceover", False)
    attempt_row, attempt_day, used_today = await _reserve_daily_attempt(store, user["id"], pipeline)
    try:
        if pipeline == "idea2video":
            result = await vimax.idea2video(body, keys)
        elif pipeline == "script2video":
            result = await vimax.script2video(body, keys)
        else:
            result = await vimax.novel2movie(body, keys)
    except Exception as exc:
        safe_error = getattr(exc, "message", None) or "Pipeline failed. Check selected providers and their quota."
        try:
            await store.update_project(
                attempt_row["id"], user["id"],
                settings={"pipeline": pipeline, "request": body, "status": "failed",
                          "attempt": True, "attempt_date": attempt_day, "error": str(safe_error)[:500], "version": 1},
            )
        except Exception:
            pass
        _error(exc)
    title = str(body.get("title") or (result.get("plan") or {}).get("title") or result.get("title") or pipeline)[:120]
    await store.update_project(
        attempt_row["id"], user["id"], name=title,
        settings={"pipeline": pipeline, "request": body, "result": result, "status": "ready",
                  "attempt": True, "attempt_date": attempt_day, "version": 1},
    )
    return {"project_id": attempt_row["id"], "status": "ready", **result}


@router.get("/projects/list")
async def list_projects(request: Request, limit: int = 30):
    user, store, _ = await _ctx(request)
    rows = await store.list_projects(user["id"], project_type=PROJECT_TYPE, limit=max(1, min(MAX_PROJECTS, limit)))
    projects = []
    for row in rows:
        settings = row.get("settings") or {}
        result = settings.get("result") or {}
        projects.append({"id": row["id"], "name": row.get("name"), "pipeline": settings.get("pipeline"),
                         "status": settings.get("status"), "created_at": row.get("created_at"),
                         "shots": len(result.get("shots") or []),
                         "duration": ((result.get("timeline") or {}).get("meta") or {}).get("duration")})
    return {"projects": projects, "count": len(projects)}


@router.get("/projects/{project_id}")
async def get_project(project_id: int, request: Request):
    user, store, _ = await _ctx(request)
    row = await store.get_project(project_id, user["id"])
    if not row or row.get("project_type") != PROJECT_TYPE:
        raise HTTPException(status_code=404, detail="ViMax project not found")
    return _project_body(row)


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, request: Request):
    user, store, _ = await _ctx(request)
    row = await store.get_project(project_id, user["id"])
    if not row or row.get("project_type") != PROJECT_TYPE:
        raise HTTPException(status_code=404, detail="ViMax project not found")
    await store.delete_project(project_id, user["id"])
    return {"deleted": True}


@router.get("/projects/{project_id}/timeline")
async def project_timeline(project_id: int, request: Request):
    user, store, _ = await _ctx(request)
    row = await store.get_project(project_id, user["id"])
    if not row or row.get("project_type") != PROJECT_TYPE:
        raise HTTPException(status_code=404, detail="ViMax project not found")
    result = (row.get("settings") or {}).get("result") or {}
    built = result.get("timeline") or vimax.stage_timeline(result.get("plan") or {}, result.get("shots") or [],
                                                            (result.get("options") or vimax.DEFAULTS), row.get("name"))
    return built


@router.post("/projects/{project_id}/shots/{shot_id}/keyframe")
async def regenerate_keyframe(project_id: int, shot_id: str, request: Request):
    user, store, keys = await _ctx(request)
    row = await store.get_project(project_id, user["id"])
    if not row or row.get("project_type") != PROJECT_TYPE:
        raise HTTPException(status_code=404, detail="ViMax project not found")
    settings = row.get("settings") or {}
    result = settings.get("result") or {}
    shot = _find_shot(result, shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="Shot not found")
    body = await request.json()
    body.update(result.get("options") or {})
    try:
        shot["keyframe"] = await vimax.shot_keyframe(shot, body, keys)
    except Exception as exc:
        _error(exc)
    result["timeline"] = vimax.stage_timeline(result.get("plan") or {}, result.get("shots") or [],
                                               result.get("options") or vimax.DEFAULTS, row.get("name"))
    settings["result"] = result
    settings["version"] = int(settings.get("version") or 1) + 1
    await store.update_project(project_id, user["id"], settings=settings)
    return {"shot": shot, "version": settings["version"]}


@router.post("/projects/{project_id}/shots/{shot_id}/clip")
async def generate_clip(project_id: int, shot_id: str, request: Request):
    user, store, keys = await _ctx(request)
    row = await store.get_project(project_id, user["id"])
    if not row or row.get("project_type") != PROJECT_TYPE:
        raise HTTPException(status_code=404, detail="ViMax project not found")
    settings = row.get("settings") or {}
    result = settings.get("result") or {}
    shot = _find_shot(result, shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="Shot not found")
    body = await request.json()
    body.update(result.get("options") or {})
    try:
        clip = await vimax.shot_clip(shot, body, keys)
    except Exception as exc:
        _error(exc)
    job_row = await store.add_project(user_id=user["id"], name=f"{row.get('name')}: {shot_id}",
                                      project_type="generation_job",
                                      settings={"job": clip.get("job"), "capability": "video",
                                                "model_id": clip.get("model_id"), "vimax_project": project_id,
                                                "shot_id": shot_id})
    shot["clip_job_id"] = job_row["id"]
    shot["clip_job"] = clip
    settings["result"] = result
    await store.update_project(project_id, user["id"], settings=settings)
    return {"job_id": job_row["id"], **clip}


@router.post("/timeline/build")
async def build_timeline(request: Request):
    await get_current_user(request)
    body = await request.json()
    return timeline.build_timeline(body)


@router.post("/timeline/edl")
async def parse_edl(request: Request):
    await get_current_user(request)
    body = await request.json()
    edits = timeline.parse_edl(str(body.get("edl") or body.get("text") or ""))
    built = timeline.edl_to_timeline(edits, total_duration=body.get("total_duration"),
                                     source=str(body.get("source") or "source.mp4"),
                                     title=str(body.get("title") or "Edited cut"))
    built["render"] = timeline.render_instructions(built)
    return {"edits": edits, "timeline": built}
