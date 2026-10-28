"""Register optional skills without replacing ViMax's builtin or video tools."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .analyzers import lint_title, score_hook, score_idea
from .scene_analysis import detect_scenes, generated_video
from .workforce import analyze_funnel, parse_youtube_reference


def build_skill_specs():
    # Import from the installed/pinned ViMax checkout, not a reimplementation.
    from agent_runtime.models import ToolResult
    from agent_runtime.tools import ToolArgumentSchema, ToolSpec

    def wrap(name, operation):
        def handler(args, runtime=None):
            try:
                value = operation(args)
                return ToolResult(name, True, json.dumps(value, ensure_ascii=False), {"advisory_only": True})
            except (ValueError, TypeError) as exc:
                return ToolResult(name, False, str(exc), {"error_type": "invalid_input"})
            except RuntimeError as exc:
                return ToolResult(name, False, str(exc), {"error_type": "unavailable"})
        return handler

    def scene_analysis(args):
        root = Path(os.environ.get("VIMAX_SKILLS_OUTPUT", str(Path.home() / ".vimax-skills" / "jobs")))
        return detect_scenes(generated_video(root, args["job_id"]))

    return [
        ToolSpec(
            name="yt_idea_heuristic",
            description="Score the phrasing of an English video idea locally. This is not market research or a views prediction.",
            handler=wrap("yt_idea_heuristic", lambda a: score_idea(a["idea"])),
            schema={"idea": ToolArgumentSchema(str, required=True)},
            permission_mode="read-only", concurrency_safe=True,
        ),
        ToolSpec(
            name="yt_hook_heuristic",
            description="Score the phrasing of an English-language opening hook locally. The score is advisory, not a performance forecast.",
            handler=wrap("yt_hook_heuristic", lambda a: score_hook(a["hook"])),
            schema={"hook": ToolArgumentSchema(str, required=True)},
            permission_mode="read-only", concurrency_safe=True,
        ),
        ToolSpec(
            name="yt_title_thumbnail_lint",
            description="Lint an English video title and optional thumbnail text locally. This does not publish or guarantee engagement.",
            handler=wrap("yt_title_thumbnail_lint", lambda a: lint_title(a["title"], a.get("thumbnail", ""))),
            schema={"title": ToolArgumentSchema(str, required=True), "thumbnail": ToolArgumentSchema(str, default="")},
            permission_mode="read-only", concurrency_safe=True,
        ),
        ToolSpec(
            name="youtube_reference_parse",
            description="Parse a supplied YouTube reference locally. Does not fetch a URL or verify ownership.",
            handler=wrap("youtube_reference_parse", lambda a: parse_youtube_reference(a["reference"])),
            schema={"reference": ToolArgumentSchema(str, required=True)},
            permission_mode="read-only", concurrency_safe=True,
        ),
        ToolSpec(
            name="youtube_funnel_review",
            description="Review supplied numeric video metrics with simple heuristics; does not fetch Analytics, diagnose causes, or forecast performance.",
            handler=wrap("youtube_funnel_review", lambda a: analyze_funnel(a["input"])),
            schema={"input": ToolArgumentSchema(dict, required=True)},
            permission_mode="read-only", concurrency_safe=True,
        ),
        ToolSpec(
            name="video_scene_cuts",
            description="Estimate visual cuts in a completed local ViMax job's generated video using PySceneDetect. Accepts a job ID, not arbitrary paths; does not publish or upload.",
            handler=wrap("video_scene_cuts", scene_analysis),
            schema={"job_id": ToolArgumentSchema(str, required=True)},
            permission_mode="read-only", concurrency_safe=False,
        ),
    ]
