"""ViMax entry point that adds skills to its real registry at runtime.

The upstream web server appends ``main_agent.py`` to the configured command.
Using ``python -m vimax_skills.agent_entry`` preserves all original behavior and
only adds three read-only ToolSpecs after ViMax has built its existing runtime.
"""
from __future__ import annotations

import sys
import agent_runtime

from .agent_tools import build_skill_specs

_original_build = agent_runtime.build_runtime


def _build_with_skills(*args, **kwargs):
    runtime = _original_build(*args, **kwargs)
    for spec in build_skill_specs():
        # Do not silently replace upstream or another extension's tool.
        if runtime.tool_registry.get_spec(spec.name) is not None:
            raise RuntimeError(f"ViMax tool already registered: {spec.name}")
        runtime.tool_registry.register(spec)
    return runtime


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "main_agent.py":
        del sys.argv[1]
    agent_runtime.build_runtime = _build_with_skills
    from main_agent import main as upstream_main
    upstream_main()


if __name__ == "__main__":
    main()
