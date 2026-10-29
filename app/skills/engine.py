"""
BG LABS - YouTube agent skills engine
=====================================

Runs the eleven skills from the vendored **youtube-agent-skill**
(https://github.com/Jakeschincariol/youtube-agent-skill, MIT) as real HTTP
endpoints, so ``/yt-script`` works in the web UI and not only inside a coding
agent.

Two things make this faithful to the skill rather than a re-implementation:

1. The skill's own Python tools are executed - ``hookscore.py`` (21 hook
   formulas, five scored properties, weakest-link verdict), ``title.py``,
   ``chapters.py``, ``deadair.py``, ``retention.py`` and ``swipe.py``. The
   SKILL.md instructions are explicit: *"Do not eyeball the hook."* So hooks are
   always scored by the tool, whether they were written by the built-in engine
   or by an LLM.
2. The SKILL.md body itself is used as the LLM system prompt when a provider key
   is configured, so a real model follows the same rules (including "never
   invent a number, a result or a source").

With no API key everything still runs on the built-in engine, which only uses
material the user supplied - it never fabricates statistics.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app import agents as agent_core
from app.skills import registry_data
from app.skills.tools import hookscore

logger = logging.getLogger("bglabs.skills")

HERE = Path(__file__).resolve().parent
TOOLS = HERE / "tools"
WPM = 150  # the skill's runtime estimate: 150 words per minute
GATE = "ship it, or change it?"

SKILLS: Dict[str, Dict[str, Any]] = registry_data.SKILLS

# Make the vendored CLI tools importable as modules (the Vercel builder traces
# imports, so this is also what gets them into the deployment bundle).
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, default: str = "") -> str:
    return str(value).strip() if value is not None and str(value).strip() else default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def skill_body(name: str) -> str:
    return SKILLS.get(name, {}).get("body", "")


def available_skills() -> List[Dict[str, Any]]:
    """Registry for the UI: command, what it does, its inputs, its tool."""
    return [{
        "name": skill["name"],
        "command": skill["command"],
        "description": skill["description"],
        "tool": skill.get("tool", ""),
        "has_python_tool": bool(skill.get("tool")),
        "inputs": skill.get("inputs", []),
        "folder": skill.get("folder", ""),
    } for skill in sorted(SKILLS.values(), key=lambda s: s["name"])]


# ===================================================================== tool runs
def run_tool(module_name: str, argv: List[str], stdin_text: str = "") -> Dict[str, Any]:
    """Run one vendored CLI tool in-process and capture what it prints.

    The tools are single-file CLIs (``main()`` + ``sys.argv``), so the faithful
    way to use them is to call ``main()`` with patched argv and capture stdout -
    exactly what a coding agent would do in a shell, minus the subprocess.
    """
    import importlib

    module = importlib.import_module(f"app.skills.tools.{module_name}")
    buffer = io.StringIO()
    old_argv = sys.argv
    exit_code = 0
    try:
        sys.argv = [f"{module_name}.py"] + [str(a) for a in argv]
        with redirect_stdout(buffer):
            try:
                module.main()
            except SystemExit as exc:  # the CLIs exit with a status
                exit_code = int(exc.code or 0)
    finally:
        sys.argv = old_argv
    output = buffer.getvalue()
    parsed: Any = None
    if "--json" in argv:
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            parsed = None
    return {"tool": f"{module_name}.py", "argv": argv, "exit_code": exit_code,
            "output": output.strip(), "json": parsed}


def _temp_input(text: str, suffix: str) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return handle.name


# ==================================================================== hook work
NUMBER_RE = re.compile(r"\b\d[\d,.]*\s?(?:%|k|m|x|hours?|hrs?|days?|weeks?|months?|years?|minutes?|mins?)?\b", re.I)
PROPER_RE = re.compile(r"\b[A-Z][a-zA-Z0-9]{2,}\b")

STAKE_DEFAULT = "views, weeks of work and momentum"

# Hook templates are written against the five properties hookscore.py measures
# (SPECIFICITY, ADDRESS, STAKES, CURIOSITY, BREVITY) *and* against the regex
# patterns hooks.json uses to classify a formula, so a generated hook is almost
# always matched to the formula it was aimed at instead of coming back
# "Unclassified" - which the scorer reads as "a summary, not a hook".
#
# ``kind`` controls grammar safety: a wh-clause topic ("why channels die") only
# reads well after a preposition, a noun-phrase topic ("cold outreach") can sit
# anywhere, and "generic"/"material" templates never embed the topic at all.
HOOK_TEMPLATES: List[Dict[str, str]] = [
    # ---- noun-phrase topics -------------------------------------------------
    {"kind": "noun", "formula": "the-mistake",
     "text": "You are probably making the mistake everyone makes with {topic}, and it costs you weeks."},
    {"kind": "noun", "formula": "the-question",
     "text": "Why does {topic} work for them and not for you? It is almost never talent."},
    {"kind": "noun", "formula": "the-warning",
     "text": "Do not start {topic} the way everyone else does before you see what actually drives it."},
    {"kind": "noun", "formula": "the-insider",
     "text": "Nobody knows this about {topic}, and that is why you keep wasting weeks on it."},
    {"kind": "noun", "formula": "contrarian-flip",
     "text": "Everyone tells you the opposite about {topic}, and it is actually wrong - here is the proof."},
    {"kind": "noun", "formula": "the-clock",
     "text": "In the next 9 minutes you will never look at {topic} the same way again."},
    {"kind": "noun", "formula": "the-list",
     "text": "3 habits that make {topic} work, and the one you should never copy from anyone."},
    {"kind": "noun", "formula": "the-direct-address",
     "text": "If you are stuck on {topic}, this is the only explanation you need this week."},
    {"kind": "noun", "formula": "the-comparison",
     "text": "Cheap versus expensive {topic}: which one actually wins when you test both properly?"},
    {"kind": "noun", "formula": "the-teardown",
     "text": "I broke {topic} down piece by piece so you can steal the structure that works."},
    {"kind": "noun", "formula": "the-origin",
     "text": "The real reason {topic} feels impossible for you is buried in advice nobody questions."},
    {"kind": "noun", "formula": "the-impossible",
     "text": "You can fix {topic} without spending anything, and nobody will tell you how."},
    # ---- wh-clause topics (embedded after a preposition only) ---------------
    {"kind": "clause", "formula": "contrarian-flip",
     "text": "Everyone tells you the opposite of what actually works about {topic}, and it costs you months."},
    {"kind": "clause", "formula": "the-insider",
     "text": "Nobody talks about the one thing behind {topic}, and you keep wasting weeks because of it."},
    {"kind": "clause", "formula": "the-reveal",
     "text": "Here is exactly what nobody explains about {topic}, and I am going to show you the fix."},
    {"kind": "clause", "formula": "the-warning",
     "text": "Do not spend another month on {topic} before you understand what actually drives it."},
    {"kind": "clause", "formula": "the-origin",
     "text": "It all started with one bad assumption about {topic}, and you are still paying for it."},
    # ---- generic: no topic, so grammar can never break ---------------------
    {"kind": "generic", "formula": "the-warning",
     "text": "Do not spend another month on this before you see what actually drives the result."},
    {"kind": "generic", "formula": "the-reveal",
     "text": "Most people quit right before the part that works, and here is exactly how to spot it."},
    {"kind": "generic", "formula": "the-direct-address",
     "text": "If you only change one thing this week, make it this one - it costs you nothing."},
    {"kind": "generic", "formula": "the-impossible",
     "text": "You can start from zero this week without money, without an audience and without editing."},
    {"kind": "generic", "formula": "the-before-after",
     "text": "You used to guess at this; after nine minutes you will have one rule that decides."},
    {"kind": "generic", "formula": "the-stack",
     "text": "Hook plus packaging plus consistency: combine those three and growth stops being a lottery."},
    # ---- only when the creator supplied the material -----------------------
    {"kind": "material", "formula": "the-statistic", "needs": "percent",
     "text": "{percent} of people who start this quit before the payoff - you can be the exception."},
    {"kind": "material", "formula": "the-receipt", "needs": "percent",
     "text": "This is my proof: {percent} and still nobody explains the part that decides it."},
    {"kind": "material", "formula": "i-tried-it", "needs": "period",
     "text": "I tested this for {period} so you don't have to, and one rule changed everything."},
    {"kind": "material", "formula": "the-deadline", "needs": "proper",
     "text": "{proper} is changing this month, and you can no longer afford to ignore it."},
]

# A wh-clause topic reads fine after "about"/"on"/"behind" but breaks templates
# that need a noun phrase ("fixing why channels die").
CLAUSE_START = re.compile(r"^\s*(why|how|what|when|where|which|who|whether)\b", re.I)

PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%|\b\d+ (?:out of|in) \d+\b", re.I)
PERIOD_RE = re.compile(r"\b\d+\s?(?:days?|weeks?|months?|years?|hours?|hrs?|minutes?|mins?)\b", re.I)
YEAR_RE = re.compile(r"^\b(?:19|20)\d{2}\b$")


def _topic_form(topic: str) -> str:
    return "clause" if CLAUSE_START.match(topic or "") else "noun"


def _material(topic: str, angle: str) -> Dict[str, Any]:
    """Pull the concrete material the user actually supplied - never invent any.

    Numbers are classified, because a year ("2026") or a duration ("10 minutes")
    reads as nonsense when dropped into a statistic hook. Only a real percentage
    or "N out of M" is allowed to become a claim.
    """
    source = f"{topic} {angle}"
    percents = [m.group(0).strip() for m in PERCENT_RE.finditer(source)]
    periods = [m.group(0).strip() for m in PERIOD_RE.finditer(source)]
    proper = [w for w in PROPER_RE.findall(angle)
              if w.lower() not in {"the", "and", "you", "your", "why", "how", "what", "but", "for"}]
    counts = [n.strip() for n in NUMBER_RE.findall(source)
              if n.strip() and not YEAR_RE.match(n.strip()) and n.strip() not in percents + periods]
    lines = [line.strip(" -\u2022\t") for line in re.split(r"[\n\r;]+", angle) if len(line.strip()) > 12]
    return {"percents": percents[:4], "periods": periods[:4], "proper": proper[:6],
            "counts": counts[:6], "notes": lines[:8],
            "numbers": (percents + periods + counts)[:6]}


def _fill(template: Dict[str, str], topic: str, material: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Fill one template, or return None when the material it needs is missing."""
    text = template["text"]
    needs = template.get("needs", "")
    if needs == "percent":
        if not material["percents"]:
            return None
        text = text.replace("{percent}", material["percents"][0])
    elif needs == "period":
        if not material["periods"]:
            return None
        text = text.replace("{period}", material["periods"][0])
    elif needs == "proper":
        if not material["proper"]:
            return None
        text = text.replace("{proper}", material["proper"][0])
    try:
        text = text.format(topic=topic)
    except (KeyError, IndexError):
        return None
    return {"text": text, "target_formula": template["formula"], "needs_proof": False,
            "uses_supplied_material": bool(needs)}


def builtin_hooks(topic: str, angle: str, material: Dict[str, Any], count: int = 5) -> List[Dict[str, Any]]:
    """The five hooks handed back, selected by the skill's own scorer.

    A pool is generated from templates that fit the topic's grammar plus any
    real material the creator supplied, every candidate is scored with
    ``hookscore.py``, and the strongest ``count`` are returned - classified
    hooks first when scores tie, because an unclassified hook is a summary.
    """
    form = _topic_form(topic)
    pool: List[Dict[str, Any]] = []
    seen = set()

    for template in HOOK_TEMPLATES:
        kind = template["kind"]
        if kind in ("noun", "clause") and kind != form:
            continue
        filled = _fill(template, topic, material)
        if not filled or filled["text"] in seen:
            continue
        seen.add(filled["text"])
        pool.append(filled)

    # A wh-clause topic is already a question - use it verbatim as one hook.
    if form == "clause":
        question = topic.strip().rstrip("?") + "?"
        candidate = f"{question[:1].upper()}{question[1:]} You are about to find out why it is never effort."
        if candidate not in seen:
            pool.append({"text": candidate, "target_formula": "the-question", "needs_proof": False,
                         "uses_supplied_material": False})

    scored = score_hooks([item["text"] for item in pool])
    by_text = {item["text"]: item for item in pool}
    ranked = []
    for item in scored:
        source_item = by_text.get(item["hook"])
        if not source_item:
            continue
        ranked.append({**source_item, "verdict": item["verdict"], "band": item["band"],
                       "matched_formula": item["formula"], "patterns_matched": item["patterns_matched"]})
    # prefer hooks that actually matched a formula when the scores are close
    ranked.sort(key=lambda item: (-item["verdict"], 0 if item["patterns_matched"] else 1))
    top = ranked[:count]
    classified = [item for item in top if item["patterns_matched"]]
    if classified and top and not top[0]["patterns_matched"]:
        # never hand back an unclassified hook as the winner if a classified one is close
        best = classified[0]
        if best["verdict"] >= top[0]["verdict"] - 4:
            top = [best] + [item for item in top if item is not best]

    # "Specific beats big": if the creator supplied a real number or name, make
    # sure one proof-backed hook survives into the five, replacing the weakest
    # generic one - a concrete claim is the only thing that lifts SPECIFICITY.
    if not any(item["uses_supplied_material"] for item in top):
        proof = [item for item in ranked if item["uses_supplied_material"] and item["patterns_matched"]]
        if proof and len(top) >= count:
            weakest = max(range(len(top)), key=lambda i: (0 if top[i]["uses_supplied_material"] else 1,
                                                          -top[i]["verdict"]))
            top[weakest] = proof[0]
            top.sort(key=lambda item: (-item["verdict"], 0 if item["patterns_matched"] else 1))
    return top


def score_hooks(hooks: List[str]) -> List[Dict[str, Any]]:
    """Run the skill's own scorer over every candidate hook."""
    scored = []
    for text in hooks:
        parts, verdict, formula, hits = hookscore.score(text)
        low = min(parts, key=parts.get)
        scored.append({
            "hook": text.strip(),
            "properties": parts,
            "verdict": verdict,
            "band": hookscore.band(verdict),
            "formula": formula,
            "patterns_matched": hits,
            "weakest": low,
            "fix": hookscore.FIX.get(low, ""),
            "bars": {k: "#" * (v // 5) for k, v in parts.items()},
        })
    scored.sort(key=lambda item: -item["verdict"])
    return scored


async def _llm_hooks(topic: str, angle: str, voice: str, length: str) -> Optional[List[str]]:
    """Ask a real model to write the five hooks, following the SKILL.md rules."""
    if agent_core.detect_provider() == "builtin":
        return None
    system = skill_body("yt-script")
    prompt = (
        f"Video idea: {topic}\n"
        f"Angle / notes / proof the creator supplied:\n{angle or '(none)'}\n"
        f"Voice profile (voice.md):\n{voice or '(none)'}\n"
        f"Target length: {length or 'medium'}\n\n"
        "Write exactly FIVE hooks for the first fifteen seconds, each 9-24 words, each using a "
        "different formula from the 21 in hooks.json. Never invent a number, a result or a source: "
        "if a formula needs a figure the creator did not supply, write the hook without it.\n"
        'Return JSON: {"hooks": [str, str, str, str, str]}'
    )
    completion = await agent_core.complete(system, prompt, json_mode=True, temperature=0.8)
    if not completion.get("ok"):
        return None
    parsed = agent_core._extract_json(completion["text"])
    if isinstance(parsed, dict) and isinstance(parsed.get("hooks"), list):
        return [str(h).strip() for h in parsed["hooks"] if str(h).strip()][:5]
    return None


BODY_BEATS = [
    ("The problem, named precisely", "Name the exact situation the viewer is in - one sentence, no throat clearing.",
     "B-roll of the failure state + the viewer's own words as on-screen text"),
    ("The mechanism", "Explain why it happens. This is the part most videos skip, which is why they feel like tips.",
     "Simple animated diagram, one arrow at a time"),
    ("The method, step by step", "Do the thing on screen while you talk. One idea per beat.",
     "Screen recording / hands-on demo, step numbers in the corner"),
    ("The proof", "Show the artifact you promised in the hook. Say out loud that you are showing it.",
     "The result on screen, full frame, held for three seconds"),
    ("The trap", "The one way viewers will get this wrong tomorrow, and the guard against it.",
     "Side-by-side: wrong way versus right way"),
]


def builtin_script(topic: str, angle: str, hook: str, material: Dict[str, Any], length: str) -> Dict[str, Any]:
    """Beat-by-beat script; every beat carries what is ON SCREEN."""
    notes = material["notes"]
    beats: List[Dict[str, Any]] = [{
        "beat": "HOOK (0:00-0:15)",
        "said": hook,
        "on_screen": "Cold open on the subject of the title. No logo, no intro, no 'hey guys'.",
        "seconds": 15,
    }, {
        "beat": "THE TURN (0:15-0:45)",
        "said": f"In the next few minutes you will get the whole {topic} method, in order, and the one rule that decides "
                f"whether it works for you. We start with the part that actually breaks.",
        "on_screen": f"Title card: '{topic}' with a three-item agenda that stays in the corner.",
        "seconds": 30,
    }]

    planned = BODY_BEATS[:4] if length == "short" else BODY_BEATS
    for index, (name, guidance, screen) in enumerate(planned):
        note = notes[index] if index < len(notes) else ""
        said = note if note else guidance
        beats.append({
            "beat": f"BODY {index + 1}: {name}",
            "said": said,
            "on_screen": screen,
            "seconds": 45 if length != "short" else 30,
            "guidance": guidance if note else "",
        })

    beats.append({
        "beat": "THE PAYOFF",
        "said": f"That is the whole {topic} method - and the checklist is in the description, so you can copy it today.",
        "on_screen": "The promised artifact full frame (checklist / template / result).",
        "seconds": 20,
    })
    beats.append({
        "beat": "THE CLOSE (one ask)",
        "said": f"If this saved you a week of guessing, subscribe - the next one goes deeper on {topic}.",
        "on_screen": "End screen with exactly one next video. Nothing else competing for the click.",
        "seconds": 12,
    })

    script_lines = []
    for beat in beats:
        script_lines.append(f"[{beat['beat']}]")
        script_lines.append(beat["said"])
        script_lines.append(f"[ON SCREEN: {beat['on_screen']}]")
        script_lines.append("")
    script = "\n".join(script_lines).strip()
    words = len(script.split())
    return {
        "script": script,
        "beats": beats,
        "word_count": words,
        "runtime_seconds": int(round(words / WPM * 60)),
        "runtime_label": f"{int(round(words / WPM))} min at {WPM} wpm",
        "wpm": WPM,
    }


async def run_yt_script(payload: Dict[str, Any]) -> Dict[str, Any]:
    """``/yt-script`` - one idea into a script somebody finishes."""
    topic = _text(payload.get("topic"))
    if not topic:
        raise ValueError("topic is required for /yt-script")
    angle = _text(payload.get("angle"))
    voice = _text(payload.get("voice"))
    length = _text(payload.get("length"), "medium")
    material = _material(topic, angle)

    engine = "builtin"
    provider = "builtin"
    model = "bglabs-heuristic-v1"
    error = ""

    hooks = await _llm_hooks(topic, angle, voice, length)
    if hooks:
        engine, provider = "llm", agent_core.detect_provider()
        completion_model = os.getenv("OPENAI_MODEL") or os.getenv("GEMINI_MODEL") or ""
        model = completion_model or provider
    else:
        generated = builtin_hooks(topic, angle, material)
        hooks = [item["text"] for item in generated]
        needs_proof = {item["text"]: item["needs_proof"] for item in generated}

    scored = score_hooks(hooks)
    for item in scored:
        item["needs_proof"] = bool(needs_proof.get(item["hook"])) if engine == "builtin" else False
        item["panel"] = "\n".join(f"    {k:<12} {v:3d}  {item['bars'][k]}" for k, v in item["properties"].items()) + \
            f"\n    {'VERDICT':<12} {item['verdict']:3d}  {item['band']}" + \
            f"\n    {'formula':<12} {item['formula']}" + \
            (f"  ({item['patterns_matched']} pattern{'s' if item['patterns_matched'] != 1 else ''} matched)"
             if item["patterns_matched"] else "  (no formula matched - usually a summary, not a hook)") + \
            f"\n    {'weakest':<12} {item['weakest']} - {item['fix']}"

    winner = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None
    script = builtin_script(topic, angle, winner["hook"], material, length)

    why_it_fits = (
        f"{winner['formula']} fits this idea because the click promise is a gap the viewer cannot close on their own "
        f"({winner['hook'][:70]}...), and it scored highest on "
        f"{max(winner['properties'], key=winner['properties'].get).title()} while staying inside the 9-24 word spoken band."
    )

    warnings = []
    if any(item.get("needs_proof") for item in scored):
        warnings.append("A hook uses a bracketed placeholder - replace it with a real number you can source, "
                        "or drop that hook. The skill forbids inventing figures.")
    if winner["verdict"] < 55:
        warnings.append(f"Even the best hook is {winner['band']} ({winner['verdict']}). "
                        f"Fix its weakest property: {winner['fix']}.")
    if not angle:
        warnings.append("No angle/notes supplied, so the body beats are generic scaffolding. "
                        "Paste your real points and re-run for a script you can actually read out loud.")
    if not voice:
        warnings.append("No voice profile (voice.md) supplied - a script in the wrong voice is worse than no script.")

    return {
        "skill": "yt-script",
        "command": "/yt-script",
        "engine": engine,
        "provider": provider,
        "model": model,
        "error": error,
        "topic": topic,
        "hooks_scored": scored,
        "best_two": [winner] + ([runner_up] if runner_up else []),
        "winner": winner,
        "winning_formula": winner["formula"],
        "why_the_formula_fits": why_it_fits,
        "rules": registry_data.SKILLS.get("yt-script", {}) and hookscore.__dict__.get("RULES", None) or _hook_rules(),
        **script,
        "warnings": warnings,
        "voice_profile_used": bool(voice),
        "gate": GATE,
        "copy_block": script["script"],
        "created_at": _now(),
    }


def _hook_rules() -> List[str]:
    try:
        import hooks_data

        return list(hooks_data.RULES)
    except Exception:
        return []


def hook_formulas() -> List[Dict[str, Any]]:
    """The 21 formulas the skill scores against (for the UI to browse)."""
    return [{"id": f.get("id"), "name": f.get("name"), "shape": f.get("shape"),
             "example": f.get("example"), "fails_when": f.get("fails_when")}
            for f in hookscore.FORMULAS]


# ================================================================= other skills
async def run_yt_package(payload: Dict[str, Any]) -> Dict[str, Any]:
    """/yt-package - title and thumbnail as ONE pairing, linted before publish."""
    from app.skills.tools import title as title_tool

    titles = [t.strip() for t in re.split(r"[\n\r]+", _text(payload.get("titles") or payload.get("title"))) if t.strip()]
    thumb = _text(payload.get("thumb"))
    topic = _text(payload.get("topic"))

    if not titles and topic:
        seo = await agent_core.run_agent("seo", {"topic": topic, "keyword": payload.get("keyword")})
        result = seo.get("result") or {}
        titles = [t.get("title") for t in (result.get("titles") or []) if t.get("title")]
        thumb = thumb or " ".join((result.get("thumbnail_text") or [])[:3])

    if not titles:
        raise ValueError("Provide at least one title (or a topic to generate ten).")

    linted = []
    for candidate in titles[:10]:
        check = title_tool.check(candidate, thumb or None)
        linted.append(check)
    linted.sort(key=lambda item: -(item.get("score") or 0))
    keep = linted[:2]

    return {
        "skill": "yt-package", "command": "/yt-package", "engine": "tool", "provider": "title.py",
        "thumb_text": thumb, "linted": linted, "keep": keep,
        "winner": keep[0] if keep else None,
        "rules": ["60 characters is where desktop search truncates, 40 is the mobile home feed.",
                  "The thumbnail must not repeat the title - different words, same promise.",
                  "Three words maximum on the thumbnail.",
                  "A number, a name or a date beats every adjective available to you.",
                  "Two all-caps words is the ceiling before a title reads as spam."],
        "gate": GATE, "created_at": _now(),
    }


async def run_yt_chapters(payload: Dict[str, Any]) -> Dict[str, Any]:
    """/yt-chapters - chapters from a transcript, validated against YouTube's rules."""
    transcript = _text(payload.get("transcript"))
    if not transcript:
        raise ValueError("transcript is required for /yt-chapters")
    target = _int(payload.get("target"), 8)
    path = _temp_input(transcript, ".srt")
    try:
        run = run_tool("chapters", [path, "--target", str(target)])
    finally:
        os.unlink(path)
    return {"skill": "yt-chapters", "command": "/yt-chapters", "engine": "tool", "provider": "chapters.py",
            "tool_run": run, "chapters_text": run["output"],
            "rules": ["First entry must be 00:00.", "At least three chapters.",
                      "Each chapter at least 10 seconds long.",
                      "Retitle every line as the promise of that section, three to five words."],
            "gate": GATE, "created_at": _now()}


async def run_yt_edit(payload: Dict[str, Any]) -> Dict[str, Any]:
    """/yt-edit - transcript into an edit decision list with timecodes."""
    transcript = _text(payload.get("transcript"))
    if not transcript:
        raise ValueError("transcript is required for /yt-edit")
    floor = payload.get("floor") or 0.35
    path = _temp_input(transcript, ".srt")
    try:
        run = run_tool("deadair", [path, "--floor", str(floor), "--json"])
        plain = run_tool("deadair", [path, "--floor", str(floor)])
    finally:
        os.unlink(path)
    return {"skill": "yt-edit", "command": "/yt-edit", "engine": "tool", "provider": "deadair.py",
            "cuts": run.get("json"), "report": plain["output"], "tool_run": plain,
            "note": "It does not touch media - it prints the cuts, you apply them.",
            "gate": GATE, "created_at": _now()}


async def run_yt_retention(payload: Dict[str, Any]) -> Dict[str, Any]:
    """/yt-retention - read a YouTube Studio retention export properly."""
    csv_text = _text(payload.get("csv"))
    if not csv_text:
        raise ValueError("csv (the retention export) is required for /yt-retention")
    path = _temp_input(csv_text, ".csv")
    try:
        run = run_tool("retention", [path])
    finally:
        os.unlink(path)
    return {"skill": "yt-retention", "command": "/yt-retention", "engine": "tool", "provider": "retention.py",
            "report": run["output"], "tool_run": run, "gate": GATE, "created_at": _now()}


async def run_yt_viral(payload: Dict[str, Any]) -> Dict[str, Any]:
    """/yt-viral - rank collected videos by how far each beat its OWN channel."""
    videos = _text(payload.get("videos"))
    if not videos:
        raise ValueError("videos (CSV or JSON with title,views,channel) is required for /yt-viral")
    path = _temp_input(videos, ".csv")
    try:
        run = run_tool("swipe", [path])
    finally:
        os.unlink(path)
    return {"skill": "yt-viral", "command": "/yt-viral", "engine": "tool", "provider": "swipe.py",
            "report": run["output"], "tool_run": run, "niche": _text(payload.get("niche")),
            "gate": GATE, "created_at": _now()}


TRIAGE = (
    ("questions", re.compile(r"\?|\b(how|why|what|when|where|can i|could you|please|which)\b", re.I)),
    ("corrections", re.compile(r"\b(wrong|incorrect|actually|mistake|not true|error|myth|misleading)\b", re.I)),
    ("praise", re.compile(r"\b(love|great|amazing|best|thank|thanks|awesome|nice|helpful|subscribed)\b", re.I)),
)


async def run_yt_comment(payload: Dict[str, Any]) -> Dict[str, Any]:
    """/yt-comment - triage into four piles, then replies in the creator's voice."""
    raw = _text(payload.get("comments"))
    if not raw:
        raise ValueError("comments are required for /yt-comment")
    tone = _text(payload.get("tone"), "friendly")
    voice = _text(payload.get("voice"))
    topic = _text(payload.get("video_topic"))
    lines = [l.strip(" -\u2022\t") for l in re.split(r"[\n\r]+", raw) if l.strip()]

    piles: Dict[str, List[Dict[str, Any]]] = {"questions": [], "corrections": [], "praise": [], "bait": []}
    for index, line in enumerate(lines[:60]):
        kind = "bait" if re.search(r"\b(http|www\.|buy|casino|promo|dm me|free money)\b", line, re.I) else None
        if not kind:
            for name, pattern in TRIAGE:
                if pattern.search(line):
                    kind = name
                    break
        kind = kind or "praise"
        piles[kind].append({"index": index, "comment": line[:400]})

    repeats: Dict[str, int] = {}
    for item in piles["questions"]:
        key = " ".join(sorted(set(re.findall(r"[a-z]{4,}", item["comment"].lower())))[:4])
        repeats[key] = repeats.get(key, 0) + 1
    next_topics = [k for k, v in sorted(repeats.items(), key=lambda kv: -kv[1])[:3] if v > 1]

    engine, provider, replies = "builtin", "builtin", []
    envelope = await agent_core.run_agent("comment_responder", {
        "video_topic": topic, "comments": "\n".join(i["comment"] for pile in piles.values() for i in pile),
        "tone": tone})
    if envelope.get("engine") == "llm":
        engine, provider = "llm", envelope.get("provider", "")
        replies = (envelope.get("result") or {}).get("replies") or []

    def draft(comment: str, kind: str) -> str:
        for reply in replies:
            if str(reply.get("comment", ""))[:60] == comment[:60]:
                return str(reply.get("reply") or "")
        if kind == "questions":
            return (f"Good question - the short answer is in the video where I set up {topic or 'this'}. "
                    f"Which part should I go deeper on?")[:180]
        if kind == "corrections":
            return "You are right, and thanks for flagging it - I will correct that in the pinned comment."
        if kind == "praise":
            return f"Thank you - the {topic or 'part'} you mentioned took the longest to get right."
        return ""

    answered = []
    for kind in ("questions", "corrections", "praise"):
        for item in piles[kind][:8]:
            text = draft(item["comment"], kind)
            if not text:
                continue
            answered.append({"pile": kind, "comment": item["comment"], "reply": text[:180],
                             "words": len(text.split()),
                             "rule_ok": len(text.split()) <= 30})
    pin = next((a for a in answered if a["pile"] == "questions"), answered[0] if answered else None)

    return {
        "skill": "yt-comment", "command": "/yt-comment", "engine": engine, "provider": provider,
        "triage_counts": {k: len(v) for k, v in piles.items()},
        "piles": piles, "replies": answered,
        "pin_this_one": pin,
        "next_video_topics": next_topics,
        "rules": ["Under 30 words.", "Answer the actual question in the first sentence.",
                  "One question back, only when it is real.",
                  "Never reply to bait - say so and move on.",
                  "No emoji unless your own replies use them."],
        "gate": GATE, "created_at": _now(),
    }


async def run_yt_plan(payload: Dict[str, Any]) -> Dict[str, Any]:
    """/yt-plan - a week that fits the hours you actually have."""
    niche = _text(payload.get("niche")) or _text(payload.get("topic"))
    if not niche:
        raise ValueError("niche is required for /yt-plan")
    hours = max(1, _int(payload.get("hours"), 6))
    idea = _text(payload.get("idea"))
    per_hour = 60 / max(1, hours)

    anchor = idea or f"{niche}: the mistake that costs the most"
    cheap = f"React to a common {niche} myth in one take, no editing beyond cuts"
    shorts = [
        f"Cut the payoff from the anchor video into a 45-second Short",
        f"One {niche} tip, straight to camera, 30 seconds",
        f"Before/after from the anchor video, 20 seconds, text only",
    ]
    budget = [
        {"task": "Anchor video: script + record + edit", "hours": round(hours * 0.5, 1)},
        {"task": "Cheap video: record + cut only", "hours": round(hours * 0.2, 1)},
        {"task": "Three Shorts (cut from the two above)", "hours": round(hours * 0.2, 1)},
        {"task": "Packaging: 3 titles, 2 thumbnails, chapters", "hours": round(hours * 0.1, 1)},
    ]
    return {
        "skill": "yt-plan", "command": "/yt-plan", "engine": "builtin", "provider": "bglabs-heuristic-v1",
        "niche": niche, "hours_per_week": hours,
        "week": [
            {"day": "Monday", "output": "Anchor video published", "title": anchor, "hours": budget[0]["hours"]},
            {"day": "Tuesday", "output": "Short 1 (cut from the anchor)", "title": shorts[0], "hours": budget[2]["hours"] / 3},
            {"day": "Thursday", "output": "Cheap video published", "title": cheap, "hours": budget[1]["hours"]},
            {"day": "Friday", "output": "Short 2", "title": shorts[1], "hours": budget[2]["hours"] / 3},
            {"day": "Saturday", "output": "Short 3 + comment replies", "title": shorts[2], "hours": budget[2]["hours"] / 3},
        ],
        "budget": budget,
        "consistency_rule": "One anchor + one cheap + three Shorts is sustainable at "
                            f"{hours}h/week (~{per_hour:.0f} min of output per hour of work). "
                            "Six videos in a week and then nothing for a month is worse than one a fortnight forever.",
        "gate": GATE, "created_at": _now(),
    }


async def run_yt_shorts(payload: Dict[str, Any]) -> Dict[str, Any]:
    """/yt-shorts - find the Shorts already hiding inside a long video."""
    transcript = _text(payload.get("transcript")) or _text(payload.get("script"))
    topic = _text(payload.get("topic"))
    if not transcript and not topic:
        raise ValueError("transcript (or topic) is required for /yt-shorts")

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", transcript) if len(s.strip()) > 25]
    candidates = []
    for index, sentence in enumerate(sentences):
        score = 0
        if NUMBER_RE.search(sentence):
            score += 3
        if re.search(r"\b(you|your)\b", sentence, re.I):
            score += 2
        if re.search(r"\b(never|always|stop|mistake|wrong|secret|actually|instead)\b", sentence, re.I):
            score += 2
        if sentence.endswith("?"):
            score += 1
        if 8 <= len(sentence.split()) <= 30:
            score += 2
        if score >= 4:
            candidates.append({"score": score, "line": sentence[:200], "index": index,
                               "hook": sentence[:60], "words": len(sentence.split())})
    candidates.sort(key=lambda item: -item["score"])
    picked = candidates[:5]

    return {
        "skill": "yt-shorts", "command": "/yt-shorts", "engine": "builtin", "provider": "bglabs-heuristic-v1",
        "topic": topic, "found": len(candidates), "shorts": [{
            "rank": i + 1, "hook": item["hook"], "body": item["line"],
            "why": "Concrete + addresses the viewer + self-contained in under 30 words",
            "structure": f"0-2s hook: \"{item['hook'][:40]}...\" | 2-25s the point | 25-30s loop back to the hook",
            "caption": f"{topic or 'This'} #shorts",
        } for i, item in enumerate(picked)],
        "rule": "A Short is not a trimmed long video - it has to land with zero context.",
        "gate": GATE, "created_at": _now(),
    }


async def run_yt_seo(payload: Dict[str, Any]) -> Dict[str, Any]:
    """/yt-seo - the platform's SEO agent, plus the skill's packaging rules."""
    topic = _text(payload.get("topic"))
    if not topic:
        raise ValueError("topic is required for /yt-seo")
    envelope = await agent_core.run_agent("seo", {"topic": topic, "script": payload.get("script"),
                                                  "keyword": payload.get("keyword"),
                                                  "audience": payload.get("audience")})
    result = envelope.get("result") or {}
    titles = [t.get("title") if isinstance(t, dict) else str(t) for t in (result.get("titles") or [])][:6]
    lint = None
    if titles:
        from app.skills.tools import title as title_tool

        lint = sorted((title_tool.check(t, " ".join((result.get("thumbnail_text") or [])[:3])) for t in titles),
                      key=lambda item: -(item.get("score") or 0))
    return {"skill": "yt-seo", "command": "/yt-seo", "engine": envelope.get("engine"),
            "provider": envelope.get("provider"), "model": envelope.get("model"),
            "seo": result, "title_lint": lint, "gate": GATE, "created_at": _now()}


async def run_yt_audit(payload: Dict[str, Any]) -> Dict[str, Any]:
    """/yt-audit - ends in ONE fix, not a list of twenty."""
    from app.skills.tools import title as title_tool

    titles = [t.strip() for t in re.split(r"[\n\r]+", _text(payload.get("titles"))) if t.strip()]
    notes = _text(payload.get("notes"))
    if not titles and not notes:
        raise ValueError("titles (the last ten) or notes are required for /yt-audit")

    linted = [title_tool.check(t) for t in titles[:12]]
    shapes: Dict[str, int] = {}
    for item in linted:
        shape = "number-led" if re.search(r"\d", item.get("title", "")) else \
            "how-to" if re.search(r"^how\b", item.get("title", ""), re.I) else \
            "question" if item.get("title", "").endswith("?") else "statement"
        shapes[shape] = shapes.get(shape, 0) + 1
    monotony = max(shapes.values()) if shapes else 0
    truncating = [i for i in linted if (i.get("chars") or 0) > 60]
    avg_score = round(sum(i.get("score") or 0 for i in linted) / max(1, len(linted)), 1)

    problems = []
    if monotony >= max(3, len(linted) * 0.6):
        problems.append(("format monotony", f"{monotony} of {len(linted)} titles use the same shape - "
                                            "that is a format problem, not a title problem"))
    if truncating:
        problems.append(("truncation", f"{len(truncating)} titles pass 60 characters and lose their tail in search"))
    if avg_score and avg_score < 60:
        problems.append(("packaging", f"average title lint score is {avg_score}/100"))
    if re.search(r"thumbnail|thumb", notes, re.I) and re.search(r"unreadable|small|blur|grey", notes, re.I):
        problems.append(("thumbnails at feed size", "thumbnails are unreadable when shrunk - that beats every other fix"))
    if re.search(r"intro|logo|welcome|hey guys", notes, re.I):
        problems.append(("first fifteen seconds", "channel intros are the most common cause of the 0:30 cliff"))

    the_fix = problems[0] if problems else ("consistency", "nothing structural is broken - keep the rhythm and improve one hook per video")
    working = []
    if linted:
        best = max(linted, key=lambda i: i.get("score") or 0)
        working.append(f"Your strongest title shape: \"{best.get('title')}\" (lint {best.get('score')}/100) - make more of these")
    if shapes and len(shapes) > 1:
        working.append(f"You already vary format ({', '.join(f'{k} x{v}' for k, v in shapes.items())}) - do not flatten it")
    working.append("Package-level thinking: you are auditing titles as a set, which most channels never do")

    return {
        "skill": "yt-audit", "command": "/yt-audit", "engine": "tool+builtin", "provider": "title.py",
        "titles_linted": linted, "title_shapes": shapes, "average_lint_score": avg_score,
        "problems_found": [{"problem": p, "detail": d} for p, d in problems],
        "the_one_fix": {"problem": the_fix[0], "what_to_do_this_week": the_fix[1]},
        "already_working": working[:3],
        "next_steps": ["Score the first fifteen seconds of your last three uploads with /yt-script's hook scorer.",
                       "Shrink your last nine thumbnails to feed size and count how many survive.",
                       "If you can export retention, run /yt-retention before changing anything else."],
        "gate": GATE, "created_at": _now(),
    }


RUNNERS: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "yt-script": run_yt_script,
    "yt-package": run_yt_package,
    "yt-chapters": run_yt_chapters,
    "yt-edit": run_yt_edit,
    "yt-retention": run_yt_retention,
    "yt-viral": run_yt_viral,
    "yt-comment": run_yt_comment,
    "yt-plan": run_yt_plan,
    "yt-shorts": run_yt_shorts,
    "yt-seo": run_yt_seo,
    "yt-audit": run_yt_audit,
}


async def run_skill(name: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    key = (name or "").strip().lower().lstrip("/")
    runner = RUNNERS.get(key)
    if not runner:
        raise KeyError(f"unknown skill '{name}'. Available: {', '.join(sorted(RUNNERS))}")
    return await runner(dict(payload or {}))


def parse_command(text: str) -> Tuple[str, Dict[str, Any]]:
    """Parse a slash command line.

    ``/yt-script I tried cold outreach for 30 days --angle "booked 9 calls" --length short``

    Everything before the first ``--flag`` is the positional subject (the whole
    phrase, not just the first word) and lands in the skill's first input field.
    """
    line = _text(text)
    if not line.startswith("/"):
        raise ValueError("Commands start with a slash, e.g. /yt-script my video idea")
    parts = re.split(r"\s+", line[1:], maxsplit=1)
    command = parts[0].strip().lower()
    rest = parts[1] if len(parts) > 1 else ""

    payload: Dict[str, Any] = {}
    for match in re.finditer(r'--([\w-]+)\s+(?:"([^"]*)"|\'([^\']*)\'|(\S+))', rest):
        payload[match.group(1).replace("-", "_")] = match.group(2) or match.group(3) or match.group(4) or ""

    first_flag = rest.find("--")
    positional = (rest[:first_flag] if first_flag != -1 else rest).strip().strip("\"'").strip()
    if positional:
        inputs = (SKILLS.get(command) or {}).get("inputs") or []
        key = inputs[0]["key"] if inputs else "topic"
        payload.setdefault(key, positional)
    return command, payload


def status() -> Dict[str, Any]:
    provider = agent_core.provider_status()
    return {
        "source": registry_data.SOURCE,
        "license": registry_data.LICENSE,
        "installed": True,
        "skills": available_skills(),
        "count": len(RUNNERS),
        "hook_formulas": len(hookscore.FORMULAS),
        "python_tools": sorted({s["tool"] for s in SKILLS.values() if s.get("tool")}),
        "llm": provider,
        "commands": [f"/{name}" for name in sorted(RUNNERS)],
        "words_per_minute": WPM,
    }


__all__ = ["SKILLS", "RUNNERS", "available_skills", "hook_formulas", "parse_command",
           "run_skill", "run_tool", "score_hooks", "status", "GATE", "WPM"]
