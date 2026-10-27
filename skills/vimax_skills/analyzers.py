"""Small adapters around the reviewed, pinned upstream creator scripts."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

VENDOR = Path(__file__).resolve().parents[1] / "vendor"
NOTICE = "English-language text heuristic only; not research, analytics, or a prediction of views."


def _module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, VENDOR / relative)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Vendored skill is unavailable: {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_hook = _module("vimax_youtube_hookscore", "youtube-agent-skill/yt-script/hookscore.py")
_title = _module("vimax_youtube_title", "youtube-agent-skill/yt-package/title.py")
_idea = _module("vimax_youtube_ideascore", "youtube-agent-pro/yt-idea/ideascore.py")


def _text(value: Any, label: str, *, required: bool = True, max_length: int = 400) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{label} is required")
    if len(value) > max_length or "\x00" in value:
        raise ValueError(f"{label} must be at most {max_length} characters and contain no NUL")
    return value


def score_idea(idea: str) -> dict[str, Any]:
    text = _text(idea, "Idea")
    axes, verdict, life = _idea.score(text)
    return {"idea": text, "axes": axes, "score": verdict, "band": _idea.band(verdict), "life": life, "notice": NOTICE}


def score_hook(hook: str) -> dict[str, Any]:
    text = _text(hook, "Hook")
    properties, verdict, formula, _ = _hook.score(text)
    return {"hook": text, "properties": properties, "score": verdict, "band": _hook.band(verdict), "formula": formula, "notice": NOTICE}


def lint_title(title: str, thumbnail: str = "") -> dict[str, Any]:
    clean_title = _text(title, "Title")
    clean_thumb = _text(thumbnail, "Thumbnail text", required=False)
    return {**_title.check(clean_title, clean_thumb or None), "notice": NOTICE}
