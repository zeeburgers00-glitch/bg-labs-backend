"""
BG LABS - YouTube agent skills API
==================================

Exposes the eleven vendored skills from
https://github.com/Jakeschincariol/youtube-agent-skill (MIT) over HTTP, so a
slash command like ``/yt-script`` works in the web UI exactly the way it works
inside a coding agent.

Endpoints
---------
``GET  /api/skills``                     -> registry, tools, LLM provider status
``GET  /api/skills/{name}``              -> one skill: instructions + input form
``POST /api/skills/{name}/run``          -> run a skill
``POST /api/skills/command``             -> run ``{"command": "/yt-script my idea"}``
``GET  /api/skills/hooks/formulas``      -> the 21 hook formulas
``POST /api/skills/hooks/score``         -> score your own hook lines with hookscore.py
``GET|POST /yt-script``                  -> the slash command itself (also /yt-package, ...)

Every response ends with the skill's gate: *"ship it, or change it?"* - nothing
here publishes anything.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.deps import check_rate_limit, get_client_ip, get_current_user, get_optional_user
from app.skills import engine as skills_engine

logger = logging.getLogger("bglabs.skills.api")

router = APIRouter(tags=["YouTube Agent Skills"])

RATE_LIMIT = 20
COMMANDS = sorted(skills_engine.RUNNERS)


def _payload(body: Any) -> Dict[str, Any]:
    if isinstance(body, dict):
        if isinstance(body.get("payload"), dict):
            merged = dict(body["payload"])
            merged.update({k: v for k, v in body.items() if k not in ("payload", "skill", "command")})
            return merged
        return {k: v for k, v in body.items() if k not in ("skill", "command")}
    return {}


async def _run(name: str, payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    if not check_rate_limit(get_client_ip(request), f"skill:{name}", RATE_LIMIT, 60):
        raise HTTPException(429, "Too many skill runs. Please wait a minute.")
    try:
        return await skills_engine.run_skill(name, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("skill %s failed", name)
        raise HTTPException(500, f"Skill '{name}' failed: {exc}") from None


# ============================================================================
# registry
# ============================================================================
@router.get("/api/skills")
async def list_skills(request: Request) -> Dict[str, Any]:
    await get_current_user(request)
    return skills_engine.status()


@router.get("/api/skills/hooks/formulas")
async def hook_formulas(request: Request) -> Dict[str, Any]:
    await get_current_user(request)
    formulas = skills_engine.hook_formulas()
    return {"count": len(formulas), "formulas": formulas,
            "scorer": "hookscore.py - five properties 0-100, verdict is 60% mean + 40% weakest"}


@router.post("/api/skills/hooks/score")
async def score_hooks(request: Request) -> Dict[str, Any]:
    await get_current_user(request)
    body = await request.json()
    lines: List[str] = []
    if isinstance(body, dict):
        raw = body.get("hooks")
        if isinstance(raw, list):
            lines = [str(item).strip() for item in raw if str(item).strip()]
        elif body.get("hook"):
            lines = [str(body["hook"]).strip()]
        elif body.get("text"):
            lines = [l.strip() for l in str(body["text"]).splitlines() if l.strip()]
    if not lines:
        raise HTTPException(400, "Send hooks (array), hook (string) or text (one hook per line)")
    scored = skills_engine.score_hooks(lines[:25])
    return {"count": len(scored), "hooks": scored,
            "winner": scored[0] if scored else None, "gate": skills_engine.GATE}


@router.get("/api/skills/{name}")
async def skill_detail(request: Request, name: str) -> Dict[str, Any]:
    await get_current_user(request)
    key = name.strip().lower().lstrip("/")
    skill = skills_engine.SKILLS.get(key)
    if not skill:
        raise HTTPException(404, f"Unknown skill '{name}'. Available: {', '.join(COMMANDS)}")
    return {
        "name": skill["name"], "command": skill["command"], "description": skill["description"],
        "instructions": skill["body"], "inputs": skill.get("inputs", []),
        "tool": skill.get("tool", ""), "installed": True,
        "source": skills_engine.registry_data.SOURCE,
    }


@router.post("/api/skills/{name}/run")
async def run_skill(request: Request, name: str) -> Dict[str, Any]:
    await get_current_user(request)
    key = name.strip().lower().lstrip("/")
    if key not in skills_engine.RUNNERS:
        raise HTTPException(404, f"Unknown skill '{name}'. Available: {', '.join(COMMANDS)}")
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await _run(key, _payload(body), request)


@router.post("/api/skills/command")
async def run_command(request: Request) -> Dict[str, Any]:
    """Run a raw slash command line, e.g. ``/yt-script my idea --length short``."""
    await get_current_user(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    line = str((body or {}).get("command") or (body or {}).get("text") or "").strip()
    if not line:
        raise HTTPException(400, "Send {\"command\": \"/yt-script my video idea\"}")
    try:
        command, payload = skills_engine.parse_command(line)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    if command not in skills_engine.RUNNERS:
        raise HTTPException(404, f"Unknown command '/{command}'. Available: {', '.join('/' + c for c in COMMANDS)}")
    overrides = _payload(body)
    payload.update({k: v for k, v in overrides.items() if v not in (None, "")})
    result = await _run(command, payload, request)
    result["command_line"] = line
    return result


# ============================================================================
# the slash commands themselves, at the site root
# ============================================================================
def _register_root_command(name: str) -> None:
    """Add ``GET|POST /{name}`` so the command works as a URL too."""
    key = name

    async def handler_get(request: Request,
                          topic: str = Query(""), title: str = Query(""), transcript: str = Query(""),
                          comments: str = Query(""), csv: str = Query(""), videos: str = Query(""),
                          niche: str = Query(""), titles: str = Query(""), thumb: str = Query(""),
                          angle: str = Query(""), length: str = Query(""), hours: int = Query(0),
                          target: int = Query(0), floor: float = Query(0), tone: str = Query(""),
                          notes: str = Query("")) -> Dict[str, Any]:
        # Optional auth: commands work anonymously for quick trials, but a logged
        # in user gets their runs rate limited per account as usual.
        await get_optional_user(request)
        payload = {k: v for k, v in {
            "topic": topic, "title": title, "titles": titles, "transcript": transcript,
            "comments": comments, "csv": csv, "videos": videos, "niche": niche, "thumb": thumb,
            "angle": angle, "length": length, "hours": hours, "target": target, "floor": floor,
            "tone": tone, "notes": notes,
        }.items() if v not in ("", 0, None)}
        return await _run(key, payload, request)

    async def handler_post(request: Request) -> Dict[str, Any]:
        await get_optional_user(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        return await _run(key, _payload(body), request)

    handler_get.__name__ = f"root_{key.replace('-', '_')}_get"
    handler_post.__name__ = f"root_{key.replace('-', '_')}_post"
    router.add_api_route(f"/{key}", handler_get, methods=["GET"], include_in_schema=False)
    router.add_api_route(f"/{key}", handler_post, methods=["POST"], include_in_schema=True,
                         summary=f"Run the /{key} skill")


for _command in COMMANDS:
    _register_root_command(_command)


__all__ = ["router", "COMMANDS"]
