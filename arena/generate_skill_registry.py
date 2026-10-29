"""Regenerate the vendored skill data modules from the installed skill files.

Run after updating ``app/skills/definitions/`` (a fresh copy of
https://github.com/Jakeschincariol/youtube-agent-skill)::

    .venv/bin/python arena/generate_skill_registry.py

Writes two pure-Python data modules, because the Vercel Python builder only
uploads traced ``.py`` files - the ``.json``/``.md`` originals stay in the repo
for humans and for Claude Code, but the serverless bundle needs the data as
importable Python:

* ``app/skills/tools/hooks_data.py``    - the 21 hook formulas + rules
* ``app/skills/registry_data.py``       - the eleven skills (SKILL.md bodies, inputs)
"""
from __future__ import annotations

import json
import pathlib
import pprint
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "app/skills/tools"
DEFS = ROOT / "app/skills/definitions"

# Which input fields each skill's runner reads. The SKILL.md files describe the
# work in prose, so the form contract lives here.
INPUTS = {
    "yt-script": [("topic", "Video idea / topic", "text", True, "e.g. why most channels die before video 30"),
                  ("angle", "Angle, notes and proof you have", "textarea", False, "what you actually want to say, real numbers, constraints"),
                  ("length", "Target length", "select", False, "short|medium|long"),
                  ("voice", "Your voice profile (voice.md)", "textarea", False, "how you talk on camera, words you never use")],
    "yt-package": [("titles", "Titles (one per line)", "textarea", True, "paste up to 10 candidate titles"),
                   ("thumb", "Thumbnail text", "text", False, "max 3 words"),
                   ("topic", "Video topic", "text", False, "used to generate titles when none are given")],
    "yt-chapters": [("transcript", "Transcript (srt / vtt / whisper json)", "textarea", True, "paste the transcript"),
                    ("target", "Target chapter count", "number", False, "default 8")],
    "yt-edit": [("transcript", "Transcript (srt / vtt / whisper json)", "textarea", True, "paste the transcript"),
                ("floor", "Dead-air floor (seconds)", "number", False, "default 0.35")],
    "yt-comment": [("comments", "Comments (one per line)", "textarea", True, "paste the comment section"),
                   ("tone", "Tone", "select", False, "friendly|professional|playful"),
                   ("video_topic", "Video topic", "text", False, "")],
    "yt-plan": [("niche", "Niche / channel topic", "text", True, ""),
                ("hours", "Hours per week you really have", "number", False, "default 6"),
                ("idea", "Anchor video idea", "text", False, "")],
    "yt-viral": [("videos", "Collected videos (CSV: title,views,channel)", "textarea", True, "one video per line"),
                 ("niche", "Niche", "text", False, "")],
    "yt-retention": [("csv", "YouTube Studio retention export (CSV)", "textarea", True, "paste the exported CSV")],
    "yt-seo": [("topic", "Video topic", "text", True, ""),
               ("script", "Script (for context)", "textarea", False, "")],
    "yt-shorts": [("transcript", "Long-form transcript or script", "textarea", True, ""),
                  ("topic", "Topic (if no transcript)", "text", False, "")],
    "yt-audit": [("titles", "Last ten titles (one per line)", "textarea", True, ""),
                 ("notes", "Thumbnails / first 15 seconds / upload rhythm notes", "textarea", False, ""),
                 ("channel_url", "Channel URL", "text", False, "")],
}

TOOL = {"yt-script": "hookscore", "yt-package": "title", "yt-chapters": "chapters",
        "yt-edit": "deadair", "yt-retention": "retention", "yt-viral": "swipe"}


def py(value) -> str:
    """A Python literal, not JSON (json.dumps emits true/false/null)."""
    return pprint.pformat(value, width=110, sort_dicts=False)


def write_hooks_data() -> int:
    hooks = json.loads((TOOLS / "hooks.json").read_text(encoding="utf-8"))
    body = "\n".join([
        '"""Vendored copy of the 21 YouTube hook formulas (youtube-agent-skill, MIT).',
        "",
        "The Vercel Python builder only uploads traced .py files, so the JSON data file is",
        "embedded here as the fallback source of truth. ``hookscore.py`` prefers the real",
        "hooks.json when it is present on disk.",
        "",
        "Regenerate with: .venv/bin/python arena/generate_skill_registry.py",
        '"""',
        "",
        f"VERSION = {hooks.get('version', '1.0')!r}",
        f"NOTE = {hooks.get('note', '')!r}",
        f"RULES = {py(hooks.get('rules', []))}",
        f"HOOKS = {py(hooks.get('hooks', []))}",
        "",
    ])
    (TOOLS / "hooks_data.py").write_text(body, encoding="utf-8")
    return len(hooks.get("hooks", []))


def write_registry() -> dict:
    skills = {}
    for folder in sorted(DEFS.iterdir()):
        md = folder / "SKILL.md"
        if not md.is_file():
            continue
        text = md.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
        front, body = (match.group(1), match.group(2)) if match else ("", text)
        name_match = re.search(r"^name:\s*(.+)$", front, re.M)
        name = name_match.group(1).strip() if name_match else folder.name
        desc_match = re.search(r"description:\s*>-?\n((?:\s{2,}.+\n?)+)", front)
        description = " ".join(line.strip() for line in desc_match.group(1).splitlines()) if desc_match else ""
        skills[name] = {
            "name": name,
            "command": f"/{name}",
            "folder": folder.name,
            "description": description.strip(),
            "body": body.strip(),
            "tool": TOOL.get(name, ""),
            "inputs": [{"key": key, "label": label, "type": kind, "required": required, "placeholder": placeholder}
                       for key, label, kind, required, placeholder in INPUTS.get(name, [])],
        }
    body = "\n".join([
        '"""Skill registry generated from the vendored youtube-agent-skill SKILL.md files.',
        "",
        "Source: https://github.com/Jakeschincariol/youtube-agent-skill (MIT).",
        "Generated by arena/generate_skill_registry.py - do not edit by hand, regenerate",
        "after updating app/skills/definitions/.",
        '"""',
        "",
        'SOURCE = "https://github.com/Jakeschincariol/youtube-agent-skill"',
        'LICENSE = "MIT"',
        "",
        f"SKILLS = {py(skills)}",
        "",
    ])
    (ROOT / "app/skills/registry_data.py").write_text(body, encoding="utf-8")
    return skills


def main() -> None:
    count = write_hooks_data()
    skills = write_registry()
    print(f"hooks_data.py  : {count} formulas")
    print(f"registry_data.py: {len(skills)} skills -> {', '.join(sorted(skills))}")


if __name__ == "__main__":
    main()
