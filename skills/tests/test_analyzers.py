import asyncio
import json
import os
from pathlib import Path
import sys

import pytest

from vimax_skills.analyzers import lint_title, score_hook, score_idea


def test_vendored_tools_produce_real_deterministic_results():
    idea = score_idea("How to grow 5 herbs at home")
    hook = score_hook("Why do your seedlings die after only seven days?")
    title = lint_title("5 ways to start a garden", "FIRST SEEDS")
    assert idea["score"] == 51 and idea["axes"]["SEARCH"] == 46
    assert hook["score"] == 52 and hook["formula"] == "The Question"
    assert title["score"] == 100 and title["issues"] == []
    assert "not" in idea["notice"] and "prediction" in hook["notice"]


def test_analyzers_reject_empty_and_oversized_text():
    with pytest.raises(ValueError): score_idea("   ")
    with pytest.raises(ValueError): score_hook("x" * 401)
    with pytest.raises(ValueError): lint_title("x\0y")


def test_skill_specs_use_real_vimax_registry_when_source_is_available():
    source = os.environ.get("VIMAX_TEST_SOURCE")
    if not source:
        pytest.skip("set VIMAX_TEST_SOURCE to the pinned ViMax checkout")
    sys.path.insert(0, source)
    from agent_runtime.models import ToolResult
    from agent_runtime.tools import ToolRegistry, ToolSpec
    from vimax_skills.agent_tools import build_skill_specs
    existing = ToolSpec("existing", "Original ViMax tool", lambda args: ToolResult("existing", True, "kept"))
    registry = ToolRegistry([existing])
    for spec in build_skill_specs(): registry.register(spec)
    assert registry.get_spec("existing") is existing
    assert {x["name"] for x in registry.list_tools()} >= {"existing", "yt_idea_heuristic", "yt_hook_heuristic", "yt_title_thumbnail_lint"}
    result = asyncio.run(registry.execute("yt_idea_heuristic", {"idea":"How to grow 5 herbs at home"}))
    assert result.ok and json.loads(result.content)["score"] == 51
    result = asyncio.run(registry.execute("yt_hook_heuristic", {"hook":""}))
    assert not result.ok and "required" in result.content


def test_runtime_wrapper_adds_without_replacing_and_rejects_collisions(monkeypatch):
    source = os.environ.get('VIMAX_TEST_SOURCE')
    if not source:
        pytest.skip('set VIMAX_TEST_SOURCE to the pinned ViMax checkout')
    sys.path.insert(0, source)
    from types import SimpleNamespace
    from agent_runtime.models import ToolResult
    from agent_runtime.tools import ToolRegistry, ToolSpec
    from vimax_skills import agent_entry
    original = ToolSpec('existing', 'Existing tool', lambda args: ToolResult('existing', True, 'ok'))
    registry = ToolRegistry([original])
    monkeypatch.setattr(agent_entry, '_original_build', lambda *args, **kwargs: SimpleNamespace(tool_registry=registry))
    runtime = agent_entry._build_with_skills('.')
    assert runtime.tool_registry.get_spec('existing') is original
    assert runtime.tool_registry.get_spec('yt_hook_heuristic') is not None
    with pytest.raises(RuntimeError, match='already registered'):
        agent_entry._build_with_skills('.')
