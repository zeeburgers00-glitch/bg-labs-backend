"""Register optional skills without replacing ViMax's builtin or video tools."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .analyzers import (
    chapter_marks,
    edit_decision_list,
    funnel_report,
    lint_title,
    retention_leaks,
    score_hook,
    score_idea,
    sponsor_rate,
    voice_profile,
)
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
        ToolSpec(
            name="yt_edit_deadair",
            description="Produce an edit decision list (dead-air cuts) from a supplied transcript in SRT/VTT text. Advisory local heuristic; does not modify files.",
            handler=wrap("yt_edit_deadair", lambda a: edit_decision_list(a["transcript"], float(a.get("floor", 0.45)))),
            schema={"transcript": ToolArgumentSchema(str, required=True), "floor": ToolArgumentSchema(float, default=0.45)},
            permission_mode="read-only", concurrency_safe=True,
        ),
        ToolSpec(
            name="yt_chapters",
            description="Draft YouTube chapter marks from supplied timestamped transcript text, validated against YouTube's chapter rules. Advisory output; nothing is uploaded.",
            handler=wrap("yt_chapters", lambda a: chapter_marks(a["transcript"], int(a.get("target", 8)))),
            schema={"transcript": ToolArgumentSchema(str, required=True), "target": ToolArgumentSchema(int, default=8)},
            permission_mode="read-only", concurrency_safe=True,
        ),
        ToolSpec(
            name="yt_retention_reader",
            description="Read a pasted YouTube Studio audience-retention CSV export and report hook leak, cliffs and slide. Local heuristic analysis of user-provided data only.",
            handler=wrap("yt_retention_reader", lambda a: retention_leaks(a["export_csv"])),
            schema={"export_csv": ToolArgumentSchema(str, required=True)},
            permission_mode="read-only", concurrency_safe=True,
        ),
        ToolSpec(
            name="yt_sponsor_ratecard",
            description="Produce an illustrative sponsor rate band from a view count, niche and placement. Unverified CPM assumption, not a quote; makes no external calls.",
            handler=wrap("yt_sponsor_ratecard", lambda a: sponsor_rate(int(a["views"]), str(a.get("niche", "general")), str(a.get("placement", "integrated")))),
            schema={"views": ToolArgumentSchema(int, required=True), "niche": ToolArgumentSchema(str, default="general"), "placement": ToolArgumentSchema(str, default="integrated")},
            permission_mode="read-only", concurrency_safe=True,
        ),
        ToolSpec(
            name="yt_voice_profile",
            description="Summarise simple pacing and word-choice statistics of a supplied English transcript (filler rate, sentence length, signature words). Advisory only.",
            handler=wrap("yt_voice_profile", lambda a: voice_profile(a["transcript"])),
            schema={"transcript": ToolArgumentSchema(str, required=True)},
            permission_mode="read-only", concurrency_safe=True,
        ),
        ToolSpec(
            name="yt_funnel_report",
            description="Compute a local CTR/retention funnel report from pasted impressions, CTR, average view duration and video length. Heuristic estimates; not YouTube analytics.",
            handler=wrap("yt_funnel_report", lambda a: funnel_report(int(a["impressions"]), float(a["ctr"]), str(a["avd"]), str(a["length"]), str(a.get("format", "long")), int(a["views"]) if a.get("views") is not None else None)),
            schema={"impressions": ToolArgumentSchema(int, required=True), "ctr": ToolArgumentSchema(float, required=True), "avd": ToolArgumentSchema(str, required=True), "length": ToolArgumentSchema(str, required=True), "format": ToolArgumentSchema(str, default="long"), "views": ToolArgumentSchema(int, default=None)},
            permission_mode="read-only", concurrency_safe=True,
        ),
    ]
