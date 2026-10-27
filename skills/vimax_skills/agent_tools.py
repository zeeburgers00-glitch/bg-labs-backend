"""Register optional skills without replacing ViMax's builtin or video tools."""
from __future__ import annotations

import json

from .analyzers import lint_title, score_hook, score_idea


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
        return handler

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
    ]
