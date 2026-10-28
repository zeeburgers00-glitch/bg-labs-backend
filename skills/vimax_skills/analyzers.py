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


# --- Additional pinned, dependency-free vendored tools (session 2026-10-28). ---
# Transcript/CSV tools run as their reviewed upstream CLIs with --json so no
# upstream logic is re-implemented here.

_deadair = _module("vimax_youtube_deadair", "youtube-agent-skill/yt-edit/deadair.py")
_chapters = _module("vimax_youtube_chapters", "youtube-agent-skill/yt-chapters/chapters.py")
_retention = _module("vimax_youtube_retention", "youtube-agent-skill/yt-retention/retention.py")
_ratecard = _module("vimax_youtube_ratecard", "youtube-agent-pro/yt-sponsor/ratecard.py")
_voiceprint = _module("vimax_youtube_voiceprint", "youtube-agent-pro/yt-voice/voiceprint.py")
_funnel = _module("vimax_youtube_funnel", "youtube-agent-pro/yt-analytics/funnel.py")

_MAX_TRANSCRIPT = 40_000
_NICHES = {"finance", "b2b", "tech", "education", "health", "marketing", "general", "lifestyle", "gaming", "entertainment"}
# Upstream ratecard.py offers --placement all in argparse but its PLACEMENT table
# has no "all" key (upstream bug); we only allow the three keys the table defines.
_PLACEMENTS = {"mention", "integrated", "dedicated"}


def _json_safe(value: Any) -> Any:
    import json as _json
    return _json.loads(_json.dumps(value, default=str))


def _cli_json(relative: str, filename: str, content: str, extra: list[str]) -> dict[str, Any]:
    """Run a vendored upstream CLI on supplied text via a private temp file."""
    import json as _json
    import subprocess
    import sys
    import tempfile
    with tempfile.TemporaryDirectory(prefix="vimax-skill-") as tmp:
        path = Path(tmp) / filename
        path.write_text(content, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, str(VENDOR / relative), str(path), *extra, "--json"],
                capture_output=True, text=True, timeout=20,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("vendored tool timed out") from exc
    if proc.returncode != 0:
        raise ValueError((proc.stderr or proc.stdout or "tool failed").strip()[:300])
    try:
        return _json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError("vendored tool returned unreadable output") from exc


def edit_decision_list(transcript: str, floor: float = 0.45) -> dict[str, Any]:
    text = _text(transcript, "Transcript", max_length=_MAX_TRANSCRIPT)
    try:
        gap = float(floor)
    except (TypeError, ValueError) as exc:
        raise ValueError("floor must be a number of seconds") from exc
    if not 0.05 <= gap <= 5.0:
        raise ValueError("floor must be between 0.05 and 5 seconds")
    value = _cli_json("youtube-agent-skill/yt-edit/deadair.py", "transcript.srt", text, ["--floor", str(gap)])
    return {**_json_safe(value), "notice": NOTICE}


def chapter_marks(transcript: str, target: int = 8) -> dict[str, Any]:
    text = _text(transcript, "Transcript", max_length=_MAX_TRANSCRIPT)
    try:
        count = int(target)
    except (TypeError, ValueError) as exc:
        raise ValueError("target must be an integer") from exc
    if not 3 <= count <= 30:
        raise ValueError("target must be between 3 and 30 chapters")
    value = _cli_json("youtube-agent-skill/yt-chapters/chapters.py", "transcript.srt", text, ["--target", str(count)])
    return {**_json_safe(value), "notice": NOTICE}


def retention_leaks(export_csv: str) -> dict[str, Any]:
    text = _text(export_csv, "Retention export", max_length=_MAX_TRANSCRIPT)
    if "," not in text:
        raise ValueError("retention export must be CSV content")
    value = _cli_json("youtube-agent-skill/yt-retention/retention.py", "retention.csv", text, [])
    return {**_json_safe(value), "notice": NOTICE}


def sponsor_rate(views: int, niche: str = "general", placement: str = "integrated") -> dict[str, Any]:
    try:
        v = int(views)
    except (TypeError, ValueError) as exc:
        raise ValueError("views must be an integer") from exc
    if v <= 0 or v > 10_000_000_000:
        raise ValueError("views must be a positive, plausible count")
    if niche not in _NICHES:
        raise ValueError(f"niche must be one of {sorted(_NICHES)}")
    if placement not in _PLACEMENTS:
        raise ValueError(f"placement must be one of {sorted(_PLACEMENTS)}")
    value = _json_safe(_ratecard.card(v, niche, placement))
    return {**value, "notice": NOTICE}


def voice_profile(transcript: str) -> dict[str, Any]:
    text = _text(transcript, "Transcript", max_length=_MAX_TRANSCRIPT)
    return {**_json_safe(_voiceprint.analyse(text)), "notice": NOTICE}


def funnel_report(impressions: int, ctr: float, avd: str, length: str, video_format: str = "long", views: int | None = None) -> dict[str, Any]:
    try:
        impr = int(impressions)
        click = float(ctr)
    except (TypeError, ValueError) as exc:
        raise ValueError("impressions must be an integer and ctr a number") from exc
    if impr <= 0 or impr > 10_000_000_000:
        raise ValueError("impressions must be a positive, plausible count")
    if not 0.0 <= click <= 100.0:
        raise ValueError("ctr must be between 0 and 100")
    if video_format not in ("long", "shorts"):
        raise ValueError("video_format must be 'long' or 'shorts'")
    if not isinstance(avd, (str, int, float)):
        raise ValueError("avd must be a duration like '2:10' or seconds")
    if not isinstance(length, (str, int, float)):
        raise ValueError("length must be a duration like '9:40' or seconds")
    v = int(views) if views is not None else None
    if v is not None and v <= 0:
        raise ValueError("views must be positive when supplied")
    avd_s = _funnel.dur(avd) if isinstance(avd, str) else float(avd)
    len_s = _funnel.dur(length) if isinstance(length, str) else float(length)
    if avd_s is None or len_s is None or avd_s <= 0 or len_s <= 0:
        raise ValueError("avd and length must be positive durations like '2:10' or seconds")
    value = _json_safe(_funnel.diagnose(impr, click, avd_s, len_s, views=v, video_format=video_format))
    return {**value, "notice": NOTICE}
