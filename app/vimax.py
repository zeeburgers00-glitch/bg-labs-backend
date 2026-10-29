"""
app/vimax.py - ViMax's agentic video pipeline, ported to run on Vercel.

Source: https://github.com/HKUDS/ViMax (MIT). ViMax turns one idea into a video by
running a chain of specialised agents:

    global_information_planner -> character_extractor -> character_portraits_generator
      -> scene_extractor -> screenwriter -> storyboard_artist -> camera_image_generator
      -> best_image_selector -> (video generator) -> stitch

Its own runners need moviepy, opencv, faiss and a GPU, so the *agents and their
prompts* are ported here and every heavy step is delegated to ``app/providers.py``:

* reasoning   -> the strongest configured chat model (GPT / Gemini / Claude / Groq /
                 OpenRouter, ViMax's default route) or a deterministic built-in planner
* portraits   -> gpt-image-1 / Nano Banana / FLUX / ComfyUI / SD-WebUI
* keyframes   -> same, with character consistency injected into every prompt
* clips       -> Veo 3 / Wan 2.2 / Hunyuan / Seedance / MiniMax / LTX (async jobs)
* voice       -> F5-TTS / OpenAI / Gemini / edge-tts
* stitching   -> app/timeline.py (FFmpeg / moviepy / Remotion recipes + render farm)

``image_selection.num_candidates`` from ViMax's config is honoured: N keyframes are
generated per shot and the best is picked (VLM when a vision model is configured,
otherwise a deterministic scorer).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app import providers, timeline
from app.providers import ProviderError

logger = logging.getLogger("bglabs.vimax")

PIPELINES = {
    "idea2video": ["plan", "characters", "portraits", "scenes", "script", "storyboard",
                   "keyframes", "voiceover", "clips", "timeline"],
    "script2video": ["script_parse", "storyboard", "keyframes", "voiceover", "clips", "timeline"],
    "novel2movie": ["novel_compress", "scenes", "script", "storyboard", "keyframes", "clips", "timeline"],
}

DEFAULTS = {
    "duration_seconds": 60,
    "aspect_ratio": "16:9",
    "shots": 8,
    "clip_seconds": 6,
    "num_candidates": 2,      # ViMax: image_selection.num_candidates (1 disables VLM selection)
    "style": "cinematic, photoreal, 35mm, shallow depth of field, film grain",
    "max_images": 8,
    "max_clips": 4,
}

NEGATIVE_PROMPT = ("text, watermark, logo, subtitles, captions, extra fingers, deformed hands, "
                   "blurry, lowres, jpeg artifacts, duplicate character, warped face")


class ViMaxError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, hint: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.hint = hint

    def as_dict(self) -> Dict[str, Any]:
        out = {"error": self.message}
        if self.hint:
            out["hint"] = self.hint
        return out


def _text(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any, default: int, lo: int = 1, hi: int = 10000) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def options(req: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise pipeline options with ViMax-shaped defaults."""
    opts = dict(DEFAULTS)
    for key in ("duration_seconds", "aspect_ratio", "shots", "clip_seconds", "num_candidates",
                "style", "max_images", "max_clips"):
        if req.get(key) not in (None, ""):
            opts[key] = req[key]
    opts["duration_seconds"] = _int(opts["duration_seconds"], 60, 5, 3600)
    opts["shots"] = _int(opts["shots"], 8, 1, 60)
    opts["clip_seconds"] = max(2, min(12, int(_num(opts["clip_seconds"], 6))))
    opts["num_candidates"] = max(1, min(4, _int(opts["num_candidates"], 2, 1, 4)))
    opts["max_images"] = _int(opts["max_images"], 8, 0, 40)
    opts["max_clips"] = _int(opts["max_clips"], 4, 0, 40)
    opts["aspect_ratio"] = _text(opts["aspect_ratio"]) or "16:9"
    opts["style"] = _text(opts["style"]) or DEFAULTS["style"]
    return opts


# --------------------------------------------------------------------------- #
# LLM stage driver (with a deterministic fallback so the pipeline never dies)
# --------------------------------------------------------------------------- #

async def _llm_json(system: str, user: str, keys: Optional[Dict[str, str]], *,
                    model: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Ask the strongest configured chat model for JSON. None if no model / on error."""
    try:
        entry = providers.resolve("chat", model, keys)
        providers.require_configured(entry, keys)
    except ProviderError:
        return None
    try:
        out = await providers.run(entry, {"text": user, "params": {
            "system": system, "temperature": 0.7, "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }}, keys)
    except ProviderError as exc:
        logger.info("LLM stage fell back to built-in: %s", exc.message)
        return None
    except Exception as exc:
        logger.info("LLM stage error, falling back: %s", exc)
        return None
    text = _text(out.get("text"))
    if not text:
        return None
    return _parse_json(text)


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


# --------------------------------------------------------------------------- #
# stage 1: global information planner
# --------------------------------------------------------------------------- #

PLANNER_SYSTEM = """You are ViMax's global_information_planner. You turn one raw idea into the
global information every later agent depends on. Be concrete and filmable, never generic.
Return ONLY JSON:
{"title": str, "logline": str (one sentence, max 30 words), "genre": str, "tone": [str],
 "visual_style": str, "world": str (where/when it happens, 2 sentences), "themes": [str],
 "audience": str, "target_duration_seconds": int, "aspect_ratio": "16:9"|"9:16"|"1:1",
 "acts": [{"name": str, "purpose": str, "share": float}],
 "palette": [str], "reference_films": [str]}"""


async def stage_plan(idea: str, opts: Dict[str, Any], keys=None, model=None) -> Dict[str, Any]:
    idea = _text(idea)
    if len(idea) < 3:
        raise ViMaxError("An idea is required.", status_code=400)
    user = (f"IDEA: {idea}\nTARGET LENGTH: {opts['duration_seconds']} seconds\n"
            f"ASPECT: {opts['aspect_ratio']}\nSHOTS: {opts['shots']}\nSTYLE: {opts['style']}")
    data = await _llm_json(PLANNER_SYSTEM, user, keys, model=model)
    if data:
        data.setdefault("title", idea[:70])
        data["engine"] = "llm"
        return data
    return _builtin_plan(idea, opts)


def _builtin_plan(idea: str, opts: Dict[str, Any]) -> Dict[str, Any]:
    words = [w for w in re.split(r"\W+", idea.lower()) if len(w) > 3][:6]
    subject = " ".join(words) or idea[:40]
    duration = opts["duration_seconds"]
    return {
        "engine": "builtin",
        "title": idea[:80],
        "logline": f"A {opts['aspect_ratio']} short about {subject}, told in {max(1, duration // 8)} shots.",
        "genre": "documentary-short" if any(w in idea.lower() for w in ("how", "why", "history", "science"))
                 else "narrative-short",
        "tone": ["curious", "grounded", "forward-moving"],
        "visual_style": opts["style"],
        "world": (f"Present day, real locations implied by the idea: {subject}. Natural light, "
                  f"handheld when a person moves, locked-off when something is explained."),
        "themes": words[:4] or [subject],
        "audience": "Viewers who clicked a specific promise and want it paid off fast.",
        "target_duration_seconds": duration,
        "aspect_ratio": opts["aspect_ratio"],
        "acts": [
            {"name": "hook", "purpose": "Confirm the click and open a question", "share": 0.15},
            {"name": "setup", "purpose": "Establish world, character and stakes", "share": 0.25},
            {"name": "escalation", "purpose": "Three beats that raise the cost of failure", "share": 0.40},
            {"name": "payoff", "purpose": "Deliver the promised answer, then one ask", "share": 0.20},
        ],
        "palette": ["warm key", "cool shadow", "one saturated accent"],
        "reference_films": [],
        "idea": idea,
        "note": "No chat model configured - this plan is deterministic. Add an AI key "
                "(Settings -> AI Keys) for a model-written plan.",
    }


# --------------------------------------------------------------------------- #
# stage 2: character extractor  (+ portraits)
# --------------------------------------------------------------------------- #

CHARACTER_SYSTEM = """You are ViMax's character_extractor. Extract every character needed to shoot this
story, keeping the list small (max 5) and each description filmable. Merge duplicates.
Return ONLY JSON: {"characters": [{"name": str, "role": str, "age": str, "appearance": str,
"wardrobe": str, "visual_prompt": str (one dense image prompt, no camera words), "speaks": bool}]}"""


async def stage_characters(plan: Dict[str, Any], idea: str, keys=None, model=None) -> Dict[str, Any]:
    user = f"IDEA: {idea}\nPLAN: {json.dumps({k: plan.get(k) for k in ('logline','genre','tone','world','themes')}, ensure_ascii=False)}"
    data = await _llm_json(CHARACTER_SYSTEM, user, keys, model=model)
    characters = (data or {}).get("characters") if isinstance(data, dict) else None
    if not isinstance(characters, list) or not characters:
        characters = _builtin_characters(plan, idea)
        engine = "builtin"
    else:
        engine = "llm"
    out = []
    for index, character in enumerate(characters[:5]):
        if not isinstance(character, dict):
            character = {"name": _text(character)}
        name = _text(character.get("name")) or f"Character {index + 1}"
        appearance = _text(character.get("appearance")) or "distinct, memorable face and posture"
        wardrobe = _text(character.get("wardrobe")) or "simple contemporary wardrobe"
        visual_prompt = _text(character.get("visual_prompt")) or f"portrait of {name}, {appearance}, {wardrobe}"
        out.append({"id": f"char-{index + 1}", "name": name, "role": _text(character.get("role")) or "supporting",
                    "age": _text(character.get("age")) or "", "appearance": appearance, "wardrobe": wardrobe,
                    "visual_prompt": visual_prompt, "speaks": bool(character.get("speaks", index == 0)),
                    "portrait": None, "portrait_model": None})
    return {"engine": engine, "characters": out}


def _builtin_characters(plan: Dict[str, Any], idea: str) -> List[Dict[str, Any]]:
    themes = plan.get("themes") or []
    subject = _text(themes[0]) if themes else (idea[:30] or "the subject")
    return [
        {"name": "The Guide", "role": "protagonist", "age": "30s",
         "appearance": "clear face, expressive eyes, natural skin texture, short dark hair",
         "wardrobe": "plain dark shirt, no logos",
         "visual_prompt": f"documentary portrait of a guide in their 30s talking about {subject}, "
                          f"clear face, expressive eyes, plain dark shirt",
         "speaks": True},
        {"name": "The Subject", "role": "focus", "age": "",
         "appearance": f"the thing the story is about: {subject}",
         "wardrobe": "",
         "visual_prompt": f"close study of {subject}, natural light, real texture",
         "speaks": False},
    ]


PORTRAIT_SYSTEM = """You are ViMax's character_portraits_generator. Write one image prompt per character that
will produce a consistent, reusable portrait: face, wardrobe, lighting, lens, background. Keep the same
descriptors every time the character appears so shots stay consistent. Return ONLY JSON:
{"prompts": [{"name": str, "prompt": str}]}"""


async def stage_portraits(characters: List[Dict[str, Any]], opts: Dict[str, Any], keys=None,
                          model=None, image_model=None, generate: bool = True) -> Dict[str, Any]:
    if not characters:
        return {"engine": "builtin", "characters": [], "generated": 0}
    data = await _llm_json(PORTRAIT_SYSTEM,
                           json.dumps([{"name": c["name"], "visual_prompt": c["visual_prompt"]}
                                       for c in characters], ensure_ascii=False), keys, model=model)
    prompts: Dict[str, str] = {}
    if isinstance(data, dict):
        for item in data.get("prompts") or []:
            if isinstance(item, dict) and item.get("name"):
                prompts[_text(item["name"])] = _text(item.get("prompt"))

    style = opts["style"]
    for character in characters:
        base = prompts.get(character["name"]) or character["visual_prompt"]
        character["portrait_prompt"] = (f"{base}. {style}. Neutral background, soft key light, 85mm, "
                                        f"consistent face for later shots.")
    if not generate:
        return {"engine": "llm" if prompts else "builtin", "characters": characters, "generated": 0}

    made = 0
    for character in characters:
        if made >= max(1, opts["max_images"] // 2):
            break
        try:
            result = await providers.generate("image", {"prompt": character["portrait_prompt"],
                                                        "negative_prompt": NEGATIVE_PROMPT,
                                                        "aspect_ratio": opts["aspect_ratio"]},
                                              model=image_model, keys=keys)
        except ProviderError as exc:
            character["portrait_error"] = exc.as_dict()
            continue
        character["portrait"] = _media_ref(result)
        character["portrait_model"] = result.get("model_id")
        made += 1
    return {"engine": "llm" if prompts else "builtin", "characters": characters, "generated": made}


def _media_ref(result: Dict[str, Any]) -> Dict[str, Any]:
    """Keep a small, serialisable reference to generated media (never raw bytes)."""
    ref: Dict[str, Any] = {"model": result.get("model_id"), "mime": result.get("mime")}
    if result.get("url"):
        ref["url"] = result["url"]
    if result.get("saved_url"):
        ref["url"] = result["saved_url"]
    if result.get("data_uri"):
        ref["data_uri_len"] = len(result["data_uri"])
        ref["data_uri"] = result["data_uri"][:120] + "..."
    return ref


# --------------------------------------------------------------------------- #
# stage 3: scene extractor
# --------------------------------------------------------------------------- #

SCENE_SYSTEM = """You are ViMax's scene_extractor. Break the story into shootable scenes that fill the target
duration exactly. Every scene needs a purpose, a place, a time of day and the characters in it.
Return ONLY JSON: {"scenes": [{"index": int, "title": str, "location": str, "time_of_day": str,
"characters": [str], "summary": str, "beats": [str], "duration_seconds": int}]}"""


async def stage_scenes(plan: Dict[str, Any], characters: List[Dict[str, Any]], idea: str,
                       opts: Dict[str, Any], keys=None, model=None) -> Dict[str, Any]:
    duration = opts["duration_seconds"]
    user = (f"IDEA: {idea}\nPLAN: {json.dumps({k: plan.get(k) for k in ('logline','genre','tone','world','acts')}, ensure_ascii=False)}\n"
            f"CHARACTERS: {json.dumps([c['name'] for c in characters], ensure_ascii=False)}\n"
            f"TARGET: {duration} seconds total, {opts['shots']} shots, each clip {opts['clip_seconds']}s")
    data = await _llm_json(SCENE_SYSTEM, user, keys, model=model)
    scenes = (data or {}).get("scenes") if isinstance(data, dict) else None
    engine = "llm"
    if not isinstance(scenes, list) or not scenes:
        scenes = _builtin_scenes(plan, characters, opts)
        engine = "builtin"
    out: List[Dict[str, Any]] = []
    names = {c["name"] for c in characters}
    for index, scene in enumerate(scenes[:12]):
        if not isinstance(scene, dict):
            scene = {"title": _text(scene)}
        scene_chars = [c for c in (scene.get("characters") or []) if isinstance(c, str)]
        out.append({
            "index": index + 1,
            "title": _text(scene.get("title")) or f"Scene {index + 1}",
            "location": _text(scene.get("location")) or "practical location",
            "time_of_day": _text(scene.get("time_of_day")) or "day",
            "characters": [c for c in scene_chars if c in names] or [c["name"] for c in characters[:1]],
            "summary": _text(scene.get("summary")) or _text(scene.get("title")),
            "beats": [_text(b) for b in (scene.get("beats") or []) if _text(b)][:5],
            "duration_seconds": _int(scene.get("duration_seconds"), max(4, duration // max(1, len(scenes))), 2, 300),
        })
    _fit_durations(out, duration)
    return {"engine": engine, "scenes": out}


def _builtin_scenes(plan: Dict[str, Any], characters: List[Dict[str, Any]],
                    opts: Dict[str, Any]) -> List[Dict[str, Any]]:
    acts = plan.get("acts") or [{"name": "hook", "purpose": "open", "share": 1.0}]
    duration = opts["duration_seconds"]
    world = _text(plan.get("world")) or "a real, specific location"
    scenes = []
    for index, act in enumerate(acts[:6]):
        share = _num(act.get("share"), 1.0 / len(acts))
        scenes.append({
            "index": index + 1,
            "title": _text(act.get("name")).title() or f"Scene {index + 1}",
            "location": world.split(".")[0][:80] if world else "practical location",
            "time_of_day": "day" if index % 2 == 0 else "golden hour",
            "characters": [c["name"] for c in characters[:1]] or ["The Guide"],
            "summary": _text(act.get("purpose")) or "advance the story",
            "beats": [_text(act.get("purpose")) or "advance the story"],
            "duration_seconds": max(3, int(round(duration * min(share, 1.0)))),
        })
    return scenes or [{"index": 1, "title": "Scene 1", "location": world[:80], "time_of_day": "day",
                       "characters": [c["name"] for c in characters[:1]] or ["The Guide"],
                       "summary": plan.get("logline", ""), "beats": [], "duration_seconds": duration}]


def _fit_durations(scenes: List[Dict[str, Any]], total: int) -> None:
    """Scale scene lengths so they add up to the requested runtime."""
    current = sum(s["duration_seconds"] for s in scenes) or 1
    factor = total / current
    running = 0
    for index, scene in enumerate(scenes):
        scaled = max(2, int(round(scene["duration_seconds"] * factor)))
        scene["duration_seconds"] = scaled
        running += scaled
    if scenes and running != total:
        scenes[-1]["duration_seconds"] = max(2, scenes[-1]["duration_seconds"] + (total - running))


# --------------------------------------------------------------------------- #
# stage 4: screenwriter
# --------------------------------------------------------------------------- #

SCREENWRITER_SYSTEM = """You are ViMax's screenwriter. Write the spoken layer for each scene: what is said, by whom,
and what the viewer sees while it is said. Spoken lines must be sayable at 150 words per minute and must not
invent numbers, studies or results - if a fact is not supplied, write the line without it.
Return ONLY JSON: {"scenes": [{"index": int, "lines": [{"character": str, "line": str}],
"narration": str, "on_screen": str, "word_count": int}]}"""


async def stage_script(scenes: List[Dict[str, Any]], characters: List[Dict[str, Any]], plan: Dict[str, Any],
                       opts: Dict[str, Any], keys=None, model=None, facts: Optional[List[str]] = None) -> Dict[str, Any]:
    user = json.dumps({
        "logline": plan.get("logline"), "tone": plan.get("tone"), "audience": plan.get("audience"),
        "characters": [{"name": c["name"], "role": c["role"]} for c in characters],
        "scenes": [{"index": s["index"], "title": s["title"], "summary": s["summary"],
                    "beats": s["beats"], "duration_seconds": s["duration_seconds"]} for s in scenes],
        "supplied_facts": (facts or [])[:20],
        "wpm": 150,
    }, ensure_ascii=False)
    data = await _llm_json(SCREENWRITER_SYSTEM, user, keys, model=model)
    written = (data or {}).get("scenes") if isinstance(data, dict) else None
    engine = "llm"
    if not isinstance(written, list):
        written = None
        engine = "builtin"

    by_index = {}
    if written:
        for item in written:
            if isinstance(item, dict) and item.get("index"):
                by_index[int(item["index"])] = item

    out = []
    warnings: List[str] = []
    for scene in scenes:
        entry = by_index.get(scene["index"]) or {}
        lines = [l for l in (entry.get("lines") or []) if isinstance(l, dict) and _text(l.get("line"))]
        if not lines:
            budget = max(8, int(scene["duration_seconds"] * 2.5))  # 150 wpm = 2.5 words/second
            lines = [{"character": (scene["characters"] or ["Narrator"])[0],
                      "line": _builtin_line(scene, budget)}]
        narration = _text(entry.get("narration")) or " ".join(_text(l["line"]) for l in lines)
        word_count = len(narration.split())
        allowed = max(6, int(scene["duration_seconds"] * 2.6))
        if word_count > allowed:
            warnings.append(f"Scene {scene['index']} narration is {word_count} words; "
                            f"{scene['duration_seconds']}s holds about {allowed} at 150 wpm.")
        out.append({**scene, "lines": lines, "narration": narration,
                    "on_screen": _text(entry.get("on_screen")) or scene["summary"],
                    "word_count": word_count})
    if engine == "builtin":
        warnings.append("No chat model configured - narration is placeholder-shaped. "
                        "Add an AI key for real dialogue.")
    return {"engine": engine, "scenes": out, "warnings": warnings}


def _builtin_line(scene: Dict[str, Any], budget: int) -> str:
    beats = scene.get("beats") or [scene.get("summary") or scene.get("title") or ""]
    line = f"{_text(beats[0])}."
    if len(line.split()) < max(6, budget // 3):
        line += f" We see it in {scene.get('location', 'this place')}, {scene.get('time_of_day', 'day')}."
    words = line.split()
    return " ".join(words[:max(6, budget)])


async def stage_script_parse(script: str, opts: Dict[str, Any], keys=None,
                             model=None) -> Dict[str, Any]:
    """script2video: split a supplied script into scenes/shots (ViMax's script_planner)."""
    script = _text(script)
    if len(script) < 10:
        raise ViMaxError("A script is required.", status_code=400)
    system = """You are ViMax's script_planner. Split this script into shootable scenes with durations that add
up to the target length. Return ONLY JSON: {"title": str, "scenes": [{"index": int, "title": str,
"location": str, "time_of_day": str, "characters": [str], "summary": str, "beats": [str],
"duration_seconds": int, "narration": str}]}"""
    words = len(script.split())
    estimated = max(5, int(round(words / 150 * 60)))
    data = await _llm_json(system, f"TARGET: {opts['duration_seconds']} seconds\nSCRIPT:\n{script[:12000]}",
                           keys, model=model)
    scenes = (data or {}).get("scenes") if isinstance(data, dict) else None
    if not isinstance(scenes, list) or not scenes:
        chunks = [c.strip() for c in re.split(r"\n\s*\n|(?<=[.!?])\s{2,}", script) if len(c.strip()) > 40]
        if not chunks:
            sentences = re.split(r"(?<=[.!?])\s+", script)
            per = max(1, len(sentences) // max(1, opts["shots"]))
            chunks = [" ".join(sentences[i:i + per]) for i in range(0, len(sentences), per)]
        scenes = [{"index": i + 1, "title": f"Scene {i + 1}", "location": "from script",
                   "time_of_day": "day", "characters": ["Narrator"],
                   "summary": chunk[:200], "beats": [chunk[:200]], "narration": chunk,
                   "duration_seconds": max(3, int(len(chunk.split()) / 2.5))}
                  for i, chunk in enumerate(chunks[:12])]
        engine = "builtin"
    else:
        engine = "llm"
    normalised = []
    for index, scene in enumerate(scenes[:12]):
        if not isinstance(scene, dict):
            scene = {"narration": _text(scene)}
        narration = _text(scene.get("narration")) or _text(scene.get("summary"))
        normalised.append({
            "index": index + 1, "title": _text(scene.get("title")) or f"Scene {index + 1}",
            "location": _text(scene.get("location")) or "from script",
            "time_of_day": _text(scene.get("time_of_day")) or "day",
            "characters": scene.get("characters") or ["Narrator"],
            "summary": _text(scene.get("summary")) or narration[:200],
            "beats": [_text(b) for b in (scene.get("beats") or []) if _text(b)][:5],
            "narration": narration,
            "duration_seconds": _int(scene.get("duration_seconds"),
                                     max(3, int(len(narration.split()) / 2.5)), 2, 300),
            "word_count": len(narration.split()),
            "lines": [{"character": (scene.get("characters") or ["Narrator"])[0], "line": narration}]
                     if narration else [],
            "on_screen": _text(scene.get("on_screen")) or narration[:120],
        })
    _fit_durations(normalised, opts["duration_seconds"])
    return {"engine": engine, "scenes": normalised,
            "title": _text((data or {}).get("title")) or script.split("\n")[0][:80],
            "warnings": [] if engine == "llm" else
                        ["No chat model configured - scenes were split by paragraph/sentence length."]}


async def stage_novel_compress(novel: str, opts: Dict[str, Any], keys=None, model=None) -> Dict[str, Any]:
    """novel2movie: ViMax's novel_compressor - long text down to shootable beats."""
    novel = _text(novel)
    if len(novel) < 50:
        raise ViMaxError("Paste a longer piece of text (a novel chapter, article or story).", status_code=400)
    system = """You are ViMax's novel_compressor. Compress long prose into the story beats that survive a cut to
the target runtime. Keep only what can be shown. Return ONLY JSON: {"title": str, "logline": str,
"beats": [{"index": int, "beat": str, "characters": [str], "location": str, "duration_seconds": int}]}"""
    data = await _llm_json(system, f"TARGET: {opts['duration_seconds']} seconds\nTEXT:\n{novel[:20000]}",
                           keys, model=model)
    beats = (data or {}).get("beats") if isinstance(data, dict) else None
    if not isinstance(beats, list) or not beats:
        paragraphs = [p.strip() for p in novel.split("\n") if len(p.strip()) > 60]
        if not paragraphs:
            sentences = re.split(r"(?<=[.!?])\s+", novel)
            per = max(1, len(sentences) // max(1, opts["shots"]))
            paragraphs = [" ".join(sentences[i:i + per]) for i in range(0, len(sentences), per)]
        beats = [{"index": i + 1, "beat": p[:220], "characters": [], "location": "from text",
                  "duration_seconds": max(3, int(len(p.split()) / 2.5))}
                 for i, p in enumerate(paragraphs[:12])]
        engine = "builtin"
    else:
        engine = "llm"
    scenes = []
    for index, beat in enumerate(beats[:12]):
        if not isinstance(beat, dict):
            beat = {"beat": _text(beat)}
        scenes.append({"index": index + 1, "title": f"Beat {index + 1}",
                       "location": _text(beat.get("location")) or "from text", "time_of_day": "day",
                       "characters": beat.get("characters") or ["Narrator"],
                       "summary": _text(beat.get("beat")), "beats": [_text(beat.get("beat"))],
                       "narration": _text(beat.get("beat")), "lines": [],
                       "on_screen": _text(beat.get("beat"))[:120],
                       "duration_seconds": _int(beat.get("duration_seconds"), 6, 2, 300),
                       "word_count": len(_text(beat.get("beat")).split())})
    _fit_durations(scenes, opts["duration_seconds"])
    return {"engine": engine, "scenes": scenes, "title": _text((data or {}).get("title")) or "Adaptation",
            "logline": _text((data or {}).get("logline")) or "", "warnings": []}


# --------------------------------------------------------------------------- #
# stage 5: storyboard artist
# --------------------------------------------------------------------------- #

STORYBOARD_SYSTEM = """You are ViMax's storyboard_artist. Turn scenes into a shot list a camera operator could
shoot today. Vary shot size and movement; never repeat the same framing twice in a row. Each shot gets an
image prompt that describes ONLY what is visible (no camera words, no 'cinematic').
Return ONLY JSON: {"shots": [{"index": int, "scene_index": int, "shot_size": str, "camera": str,
"movement": str, "action": str, "image_prompt": str, "caption": str, "dialogue": str,
"duration_seconds": int, "characters": [str]}]}"""

SHOT_SIZES = ["extreme wide", "wide", "medium wide", "medium", "medium close-up", "close-up",
              "extreme close-up", "over-the-shoulder", "insert"]
MOVEMENTS = ["locked-off", "slow push-in", "slow pull-out", "handheld follow", "pan left to right",
             "tilt up", "crane down", "static tripod"]


async def stage_storyboard(scenes: List[Dict[str, Any]], characters: List[Dict[str, Any]],
                           plan: Dict[str, Any], opts: Dict[str, Any], keys=None,
                           model=None) -> Dict[str, Any]:
    user = json.dumps({
        "logline": plan.get("logline"), "visual_style": plan.get("visual_style"),
        "palette": plan.get("palette"), "target_shots": opts["shots"],
        "clip_seconds": opts["clip_seconds"], "total_seconds": opts["duration_seconds"],
        "characters": [{"name": c["name"], "visual_prompt": c.get("visual_prompt", "")} for c in characters],
        "scenes": [{"index": s["index"], "title": s["title"], "location": s["location"],
                    "time_of_day": s["time_of_day"], "summary": s["summary"], "beats": s["beats"],
                    "duration_seconds": s["duration_seconds"], "characters": s["characters"]} for s in scenes],
    }, ensure_ascii=False)
    data = await _llm_json(STORYBOARD_SYSTEM, user, keys, model=model)
    shots = (data or {}).get("shots") if isinstance(data, dict) else None
    engine = "llm"
    if not isinstance(shots, list) or not shots:
        shots = _builtin_storyboard(scenes, characters, opts)
        engine = "builtin"

    char_by_name = {c["name"]: c for c in characters}
    out: List[Dict[str, Any]] = []
    for index, shot in enumerate(shots[:opts["shots"] + 6]):
        if not isinstance(shot, dict):
            shot = {"action": _text(shot)}
        scene_index = _int(shot.get("scene_index"), min(len(scenes), index + 1), 1, max(1, len(scenes)))
        scene = scenes[scene_index - 1] if scene_index - 1 < len(scenes) else scenes[-1]
        shot_characters = [c for c in (shot.get("characters") or scene.get("characters") or [])
                           if isinstance(c, str)]
        action = _text(shot.get("action")) or _text(scene.get("summary"))
        image_prompt = _text(shot.get("image_prompt")) or action
        caption = _text(shot.get("caption")) or _text(shot.get("dialogue")) or action[:120]
        out.append({
            "id": f"shot-{index + 1}",
            "index": index + 1,
            "scene_index": scene_index,
            "scene_title": scene.get("title"),
            "shot_size": _text(shot.get("shot_size")) or SHOT_SIZES[index % len(SHOT_SIZES)],
            "camera": _text(shot.get("camera")) or f"{SHOT_SIZES[index % len(SHOT_SIZES)]}, 35mm",
            "movement": _text(shot.get("movement")) or MOVEMENTS[index % len(MOVEMENTS)],
            "action": action,
            "image_prompt": image_prompt,
            "caption": caption,
            "dialogue": _text(shot.get("dialogue")),
            "duration_seconds": _int(shot.get("duration_seconds"), opts["clip_seconds"], 2, 30),
            "characters": shot_characters,
            "keyframe": None, "keyframe_model": None, "candidates": [],
            "clip_job": None, "clip_url": None, "audio_url": None,
        })

    # consistency: bake each character's fixed description into every shot prompt
    for shot in out:
        descriptors = [char_by_name[name]["visual_prompt"] for name in shot["characters"]
                       if name in char_by_name]
        location = ""
        for scene in scenes:
            if scene["index"] == shot["scene_index"]:
                location = f"{scene['location']}, {scene['time_of_day']}"
                break
        shot["full_prompt"] = ", ".join(filter(None, [
            f"{shot['shot_size']} shot: {shot['image_prompt']}",
            "; ".join(descriptors),
            location,
            plan.get("visual_style") or opts["style"],
        ]))
    _fit_durations_shots(out, opts["duration_seconds"])
    return {"engine": engine, "shots": out}


def _builtin_storyboard(scenes: List[Dict[str, Any]], characters: List[Dict[str, Any]],
                        opts: Dict[str, Any]) -> List[Dict[str, Any]]:
    shots: List[Dict[str, Any]] = []
    per_scene = max(1, round(opts["shots"] / max(1, len(scenes))))
    for scene in scenes:
        beats = scene.get("beats") or [scene.get("summary") or scene.get("title")]
        for beat_index in range(min(per_scene, max(1, len(beats)))):
            index = len(shots)
            beat = _text(beats[beat_index % len(beats)])
            shots.append({
                "index": index + 1, "scene_index": scene["index"],
                "shot_size": SHOT_SIZES[index % len(SHOT_SIZES)],
                "camera": f"{SHOT_SIZES[index % len(SHOT_SIZES)]}, 35mm",
                "movement": MOVEMENTS[index % len(MOVEMENTS)],
                "action": beat,
                "image_prompt": beat,
                "caption": beat[:120],
                "dialogue": "",
                "duration_seconds": opts["clip_seconds"],
                "characters": scene.get("characters") or [],
            })
    # ViMax is asked for an explicit shot count. If there are fewer beats than
    # shots, add visual cutaways/B-roll instead of silently shortening the film.
    while shots and len(shots) < opts["shots"]:
        scene = scenes[len(shots) % len(scenes)]
        index = len(shots)
        beat = _text((scene.get("beats") or [scene.get("summary") or scene.get("title")])[0])
        shots.append({
            "index": index + 1, "scene_index": scene["index"],
            "shot_size": SHOT_SIZES[index % len(SHOT_SIZES)],
            "camera": f"{SHOT_SIZES[index % len(SHOT_SIZES)]}, 50mm",
            "movement": MOVEMENTS[index % len(MOVEMENTS)],
            "action": f"Visual detail that proves: {beat}",
            "image_prompt": f"specific visual evidence and environmental detail for {beat}",
            "caption": beat[:120], "dialogue": "",
            "duration_seconds": opts["clip_seconds"],
            "characters": scene.get("characters") or [],
        })
    return shots[:opts["shots"]]


def _fit_durations_shots(shots: List[Dict[str, Any]], total: int) -> None:
    current = sum(s["duration_seconds"] for s in shots) or 1
    factor = total / current
    for shot in shots:
        shot["duration_seconds"] = max(2, min(30, int(round(shot["duration_seconds"] * factor))))


# --------------------------------------------------------------------------- #
# stage 6: keyframes + ViMax's best-of-N image selection
# --------------------------------------------------------------------------- #

async def stage_keyframes(shots: List[Dict[str, Any]], characters: List[Dict[str, Any]],
                          opts: Dict[str, Any], keys=None, image_model=None,
                          model=None, limit: Optional[int] = None) -> Dict[str, Any]:
    """Generate keyframes, ``num_candidates`` per shot, and keep the best one."""
    limit = opts["max_images"] if limit is None else limit
    candidates = max(1, _int(opts["num_candidates"], 2, 1, 4))
    made = 0
    errors: List[Dict[str, Any]] = []
    for shot in shots:
        if made >= limit:
            shot["keyframe_status"] = "skipped (image budget reached)"
            continue
        shot_images: List[Dict[str, Any]] = []
        for candidate_index in range(candidates):
            if made >= limit * candidates:
                break
            seed = int(hashlib.sha256(f"{shot['id']}:{candidate_index}".encode()).hexdigest()[:8], 16) % 10**9
            try:
                result = await providers.generate("image", {
                    "prompt": shot.get("full_prompt") or shot["image_prompt"],
                    "negative_prompt": NEGATIVE_PROMPT, "aspect_ratio": opts["aspect_ratio"],
                    "seed": seed if candidate_index else None,
                    "width": 1280 if opts["aspect_ratio"] == "16:9" else 832,
                    "height": 720 if opts["aspect_ratio"] == "16:9" else 1472,
                }, model=image_model, keys=keys)
            except ProviderError as exc:
                errors.append({"shot": shot["id"], "error": exc.message, "hint": exc.hint})
                break
            ref = _media_ref(result)
            ref["seed"] = seed
            ref["candidate"] = candidate_index + 1
            shot_images.append(ref)
            made += 1
        shot["candidates"] = shot_images
        if shot_images:
            best = await select_best_image(shot, shot_images, keys, model=model)
            shot["keyframe"] = best
            shot["keyframe_model"] = best.get("model")
            shot["keyframe_status"] = "generated"
        else:
            shot["keyframe_status"] = "failed"
    return {"generated": made, "errors": errors, "shots": shots,
            "selection": "vlm" if _has_vision(keys) else "heuristic"}


def _has_vision(keys=None) -> bool:
    try:
        entry = providers.resolve("chat", None, keys)
    except ProviderError:
        return False
    return entry["id"] in ("openai-chat", "gemini-chat", "claude-chat", "openrouter-any", "litellm-proxy",
                           "llm-gateway")


SELECTOR_SYSTEM = """You are ViMax's best_image_selector. You will be given a shot description and the seeds of
candidate images generated for it. Choose which candidate best matches the shot: correct subject, correct shot
size, no extra characters, no text. Return ONLY JSON: {"best": int (1-based), "why": str}"""


async def select_best_image(shot: Dict[str, Any], candidates: List[Dict[str, Any]], keys=None,
                            model=None) -> Dict[str, Any]:
    if len(candidates) == 1:
        return candidates[0]
    if _has_vision(keys) and any(c.get("url") for c in candidates):
        try:
            entry = providers.resolve("chat", model, keys)
            out = await providers.run(entry, {"text": json.dumps({
                "shot": shot.get("action"), "image_prompt": shot.get("image_prompt"),
                "shot_size": shot.get("shot_size"),
                "candidates": [{"n": i + 1, "url": c.get("url"), "seed": c.get("seed")}
                               for i, c in enumerate(candidates)],
            }, ensure_ascii=False), "params": {"system": SELECTOR_SYSTEM, "temperature": 0.2}}, keys)
            data = _parse_json(_text(out.get("text"))) or {}
            pick = _int(data.get("best"), 1, 1, len(candidates)) - 1
            chosen = dict(candidates[pick])
            chosen["selected_by"] = "vlm"
            chosen["why"] = _text(data.get("why"))
            return chosen
        except Exception as exc:
            logger.info("VLM selection fell back to heuristic: %s", exc)
    # deterministic heuristic: prefer the candidate whose seed differs most from the others,
    # i.e. keep variation, and mark it so a human can override in the UI
    scored = sorted(candidates, key=lambda c: -(c.get("seed") or 0))
    chosen = dict(scored[0])
    chosen["selected_by"] = "heuristic"
    chosen["why"] = ("No vision model configured - picked deterministically. Add an AI key to let the "
                     "model choose, or click another candidate in the UI.")
    return chosen


# --------------------------------------------------------------------------- #
# stage 7: voiceover + clips (async jobs)
# --------------------------------------------------------------------------- #

async def stage_voiceover(shots: List[Dict[str, Any]], opts: Dict[str, Any], keys=None,
                          tts_model=None, limit: Optional[int] = None) -> Dict[str, Any]:
    """Speak each shot's dialogue/caption. Free edge-tts by default, F5-TTS if configured."""
    limit = limit if limit is not None else len(shots)
    made = 0
    errors: List[Dict[str, Any]] = []
    for shot in shots[:limit]:
        text = _text(shot.get("dialogue")) or _text(shot.get("caption"))
        if not text:
            continue
        try:
            result = await providers.generate("tts", {"text": text[:1800], "voice": opts.get("voice"),
                                                      "speed": opts.get("speed") or 1.0},
                                              model=tts_model, keys=keys)
        except ProviderError as exc:
            errors.append({"shot": shot["id"], "error": exc.message, "hint": exc.hint})
            continue
        shot["audio"] = _media_ref(result)
        shot["audio_model"] = result.get("model_id")
        made += 1
    return {"generated": made, "errors": errors, "shots": shots}


async def stage_clips(shots: List[Dict[str, Any]], opts: Dict[str, Any], keys=None,
                      video_model=None) -> Dict[str, Any]:
    """Start video jobs for the first ``max_clips`` shots (image-to-video where we have a keyframe)."""
    started: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    budget = opts["max_clips"]
    for shot in shots:
        if len(started) >= budget:
            shot["clip_status"] = "skipped (clip budget reached)"
            continue
        keyframe_url = (shot.get("keyframe") or {}).get("url")
        motion = (f"{shot.get('movement', 'slow push-in')}. {shot.get('action', '')} "
                  f"Camera: {shot.get('camera', '35mm')}. No text on screen.")
        try:
            result = await providers.generate("video", {
                "prompt": motion[:1400], "image_url": keyframe_url,
                "aspect_ratio": opts["aspect_ratio"], "duration": shot["duration_seconds"],
                "negative_prompt": NEGATIVE_PROMPT,
            }, model=video_model, keys=keys)
        except ProviderError as exc:
            errors.append({"shot": shot["id"], "error": exc.message, "hint": exc.hint})
            shot["clip_status"] = "unavailable"
            continue
        job = result.get("job")
        shot["clip_job"] = {"model_id": result.get("model_id"), "status": result.get("status") or
                            (job or {}).get("status") or "queued", "job": job}
        shot["clip_status"] = "queued"
        started.append({"shot": shot["id"], "model": result.get("model_id"),
                        "status": shot["clip_job"]["status"]})
    return {"started": started, "errors": errors, "shots": shots}


# --------------------------------------------------------------------------- #
# stage 8: timeline
# --------------------------------------------------------------------------- #

def stage_timeline(plan: Dict[str, Any], shots: List[Dict[str, Any]], opts: Dict[str, Any],
                   title: str = "") -> Dict[str, Any]:
    payload = {
        "title": title or _text(plan.get("title")) or "ViMax video",
        "aspect_ratio": opts["aspect_ratio"],
        "fps": 30,
        "shots": [{
            "id": shot["id"],
            "prompt": shot.get("full_prompt") or shot.get("image_prompt"),
            "duration": shot["duration_seconds"],
            "image_url": (shot.get("keyframe") or {}).get("url"),
            "video_url": shot.get("clip_url"),
            "caption": shot.get("caption"),
            "dialogue": shot.get("dialogue"),
            "camera": f"{shot.get('shot_size')} / {shot.get('movement')}",
            "transition": "cut" if shot["index"] > 1 else "fade",
        } for shot in shots],
    }
    built = timeline.build_timeline(payload)
    built["meta"]["characters"] = []
    built["meta"]["style"] = opts["style"]
    built["estimate"] = timeline.estimate_render_cost(built)
    return built


# --------------------------------------------------------------------------- #
# pipelines
# --------------------------------------------------------------------------- #

async def idea2video(req: Dict[str, Any], keys=None, *, progress=None) -> Dict[str, Any]:
    """ViMax's idea2video: one idea -> plan, characters, portraits, scenes, script, shots, frames."""
    idea = _text(req.get("idea") or req.get("topic") or req.get("prompt"))
    if len(idea) < 3:
        raise ViMaxError("An idea is required.", status_code=400)
    opts = options(req)
    model = req.get("chat_model") or req.get("model")
    stages: Dict[str, Any] = {}
    facts = req.get("facts") or []

    stages["plan"] = await stage_plan(idea, opts, keys, model=model)
    _report(progress, "plan", stages["plan"].get("engine"))

    characters = await stage_characters(stages["plan"], idea, keys, model=model)
    stages["characters"] = characters
    _report(progress, "characters", characters.get("engine"))

    portraits = await stage_portraits(characters["characters"], opts, keys, model=model,
                                      image_model=req.get("image_model"),
                                      generate=bool(req.get("generate_images", True)))
    stages["portraits"] = portraits
    _report(progress, "portraits", f"{portraits['generated']} images")

    scenes = await stage_scenes(stages["plan"], portraits["characters"], idea, opts, keys, model=model)
    stages["scenes"] = scenes
    _report(progress, "scenes", scenes.get("engine"))

    script = await stage_script(scenes["scenes"], portraits["characters"], stages["plan"], opts, keys,
                                model=model, facts=facts)
    stages["script"] = script
    _report(progress, "script", script.get("engine"))

    storyboard = await stage_storyboard(script["scenes"], portraits["characters"], stages["plan"], opts,
                                        keys, model=model)
    stages["storyboard"] = storyboard
    _report(progress, "storyboard", f"{len(storyboard['shots'])} shots")

    shots = storyboard["shots"]
    if req.get("generate_images", True) and opts["max_images"]:
        keyframes = await stage_keyframes(shots, portraits["characters"], opts, keys,
                                          image_model=req.get("image_model"), model=model)
        stages["keyframes"] = {"generated": keyframes["generated"], "selection": keyframes["selection"],
                               "errors": keyframes["errors"]}
        _report(progress, "keyframes", f"{keyframes['generated']} images")

    if req.get("generate_voiceover") and shots:
        voice = await stage_voiceover(shots, opts, keys, tts_model=req.get("tts_model"),
                                      limit=_int(req.get("voiceover_shots"), len(shots), 0, 60))
        stages["voiceover"] = {"generated": voice["generated"], "errors": voice["errors"]}
        _report(progress, "voiceover", f"{voice['generated']} clips")

    if req.get("render_video") and shots:
        clips = await stage_clips(shots, opts, keys, video_model=req.get("video_model"))
        stages["clips"] = {"started": clips["started"], "errors": clips["errors"]}
        _report(progress, "clips", f"{len(clips['started'])} jobs")

    stages["timeline"] = stage_timeline(stages["plan"], shots, opts, title=_text(req.get("title")))
    _report(progress, "timeline", stages["timeline"]["meta"]["duration_tc"])

    return {
        "pipeline": "idea2video", "idea": idea, "options": opts,
        "plan": stages["plan"], "characters": portraits["characters"], "scenes": script["scenes"],
        "shots": shots, "timeline": stages["timeline"],
        "stages": {name: _stage_summary(stages.get(name)) for name in PIPELINES["idea2video"]
                   if name in stages},
        "engines": {name: (stages[name] or {}).get("engine") for name in ("plan", "characters", "scenes",
                                                                          "script", "storyboard")
                    if isinstance(stages.get(name), dict)},
        "warnings": (script.get("warnings") or []) + _collect_errors(stages),
        "source": "https://github.com/HKUDS/ViMax",
    }


async def script2video(req: Dict[str, Any], keys=None, *, progress=None) -> Dict[str, Any]:
    script_text = _text(req.get("script") or req.get("text"))
    if len(script_text) < 10:
        raise ViMaxError("A script is required.", status_code=400)
    opts = options(req)
    model = req.get("chat_model") or req.get("model")

    parsed = await stage_script_parse(script_text, opts, keys, model=model)
    _report(progress, "script_parse", parsed.get("engine"))
    scenes = parsed["scenes"]
    characters = await stage_characters({"logline": parsed.get("title"), "themes": []},
                                        parsed.get("title") or script_text[:60], keys, model=model)
    plan = await stage_plan(parsed.get("title") or script_text[:120], opts, keys, model=model)
    storyboard = await stage_storyboard(scenes, characters["characters"], plan, opts, keys, model=model)
    shots = storyboard["shots"]
    _report(progress, "storyboard", f"{len(shots)} shots")

    if req.get("generate_images", True) and opts["max_images"]:
        keyframes = await stage_keyframes(shots, characters["characters"], opts, keys,
                                          image_model=req.get("image_model"), model=model)
        stages_keyframes = {"generated": keyframes["generated"], "errors": keyframes["errors"]}
        _report(progress, "keyframes", f"{keyframes['generated']} images")
    else:
        stages_keyframes = {"generated": 0, "errors": []}

    if req.get("generate_voiceover") and shots:
        voice = await stage_voiceover(shots, opts, keys, tts_model=req.get("tts_model"))
        _report(progress, "voiceover", f"{voice['generated']} clips")

    if req.get("render_video") and shots:
        clips = await stage_clips(shots, opts, keys, video_model=req.get("video_model"))
        _report(progress, "clips", f"{len(clips['started'])} jobs")

    built = stage_timeline(plan, shots, opts, title=parsed.get("title"))
    return {"pipeline": "script2video", "options": opts, "plan": plan,
            "characters": characters["characters"], "scenes": scenes, "shots": shots,
            "timeline": built,
            "stages": {"script_parse": {"engine": parsed.get("engine"), "scenes": len(scenes)},
                       "storyboard": {"engine": storyboard.get("engine"), "shots": len(shots)},
                       "keyframes": stages_keyframes},
            "warnings": (parsed.get("warnings") or []) + stages_keyframes.get("errors", []),
            "source": "https://github.com/HKUDS/ViMax"}


async def novel2movie(req: Dict[str, Any], keys=None, *, progress=None) -> Dict[str, Any]:
    novel = _text(req.get("novel") or req.get("text") or req.get("script"))
    if len(novel) < 50:
        raise ViMaxError("Paste the chapter/article/story you want adapted.", status_code=400)
    opts = options(req)
    model = req.get("chat_model") or req.get("model")
    compressed = await stage_novel_compress(novel, opts, keys, model=model)
    _report(progress, "novel_compress", compressed.get("engine"))
    scenes = compressed["scenes"]
    characters = await stage_characters({"logline": compressed.get("logline"), "themes": []},
                                        compressed.get("title") or novel[:120], keys, model=model)
    plan = await stage_plan(compressed.get("logline") or compressed.get("title") or novel[:160], opts,
                            keys, model=model)
    storyboard = await stage_storyboard(scenes, characters["characters"], plan, opts, keys, model=model)
    shots = storyboard["shots"]
    if req.get("generate_images", True) and opts["max_images"]:
        keyframes = await stage_keyframes(shots, characters["characters"], opts, keys,
                                          image_model=req.get("image_model"), model=model)
    built = stage_timeline(plan, shots, opts, title=compressed.get("title"))
    return {"pipeline": "novel2movie", "options": opts, "plan": plan,
            "characters": characters["characters"], "scenes": scenes, "shots": shots,
            "timeline": built, "title": compressed.get("title"),
            "warnings": compressed.get("warnings") or [],
            "source": "https://github.com/HKUDS/ViMax"}


def _report(progress, stage: str, detail: str) -> None:
    if callable(progress):
        try:
            progress(stage, detail)
        except Exception:  # never let reporting break the pipeline
            pass


def _stage_summary(stage: Any) -> Dict[str, Any]:
    if not isinstance(stage, dict):
        return {"ok": bool(stage)}
    summary = {"engine": stage.get("engine")}
    for key in ("generated", "started", "selection"):
        if key in stage:
            value = stage[key]
            summary[key] = len(value) if isinstance(value, list) else value
    if stage.get("errors"):
        summary["errors"] = len(stage["errors"])
    return {k: v for k, v in summary.items() if v is not None}


def _collect_errors(stages: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for name, stage in stages.items():
        if isinstance(stage, dict):
            for error in stage.get("errors") or []:
                if isinstance(error, dict):
                    out.append(f"{name}/{error.get('shot', '')}: {error.get('error')}"
                               + (f" ({error.get('hint')})" if error.get("hint") else ""))
                else:
                    out.append(f"{name}: {error}")
    return out[:12]


def pipelines() -> List[Dict[str, Any]]:
    """What the UI can run, and what each stage needs."""
    return [
        {"id": "idea2video", "label": "Idea -> Video", "stages": PIPELINES["idea2video"],
         "input": [{"key": "idea", "label": "Your idea", "type": "textarea", "required": True,
                    "placeholder": "A one-minute film about the last bookbinder in Lahore"}],
         "source": "https://github.com/HKUDS/ViMax"},
        {"id": "script2video", "label": "Script -> Video", "stages": PIPELINES["script2video"],
         "input": [{"key": "script", "label": "Script", "type": "textarea", "required": True}],
         "source": "https://github.com/HKUDS/ViMax"},
        {"id": "novel2movie", "label": "Novel/Article -> Movie", "stages": PIPELINES["novel2movie"],
         "input": [{"key": "novel", "label": "Long text", "type": "textarea", "required": True}],
         "source": "https://github.com/HKUDS/ViMax"},
    ]


async def shot_keyframe(shot: Dict[str, Any], req: Dict[str, Any], keys=None) -> Dict[str, Any]:
    """Regenerate one shot's keyframe (the UI's 'try again' button)."""
    opts = options(req)
    prompt = _text(req.get("prompt")) or shot.get("full_prompt") or shot.get("image_prompt")
    if not prompt:
        raise ViMaxError("This shot has no prompt.", status_code=400)
    result = await providers.generate("image", {"prompt": prompt, "negative_prompt": NEGATIVE_PROMPT,
                                                "aspect_ratio": opts["aspect_ratio"],
                                                "seed": req.get("seed")},
                                      model=req.get("image_model"), keys=keys)
    return _media_ref(result)


async def shot_clip(shot: Dict[str, Any], req: Dict[str, Any], keys=None) -> Dict[str, Any]:
    """Start one shot's video job (Veo 3 / Wan / Hunyuan / ComfyUI ...)."""
    opts = options(req)
    keyframe_url = _text(req.get("image_url")) or (shot.get("keyframe") or {}).get("url")
    motion = _text(req.get("prompt")) or (f"{shot.get('movement', 'slow push-in')}. {shot.get('action', '')} "
                                          f"Camera: {shot.get('camera', '')}. No text on screen.")
    result = await providers.generate("video", {"prompt": motion[:1400], "image_url": keyframe_url,
                                                "aspect_ratio": opts["aspect_ratio"],
                                                "duration": shot.get("duration_seconds") or opts["clip_seconds"],
                                                "negative_prompt": NEGATIVE_PROMPT},
                                      model=req.get("video_model"), keys=keys)
    return {"job": result.get("job"), "status": result.get("status") or "queued",
            "model_id": result.get("model_id")}


__all__ = ["ViMaxError", "PIPELINES", "DEFAULTS", "options", "pipelines",
           "idea2video", "script2video", "novel2movie", "stage_plan", "stage_characters",
           "stage_portraits", "stage_scenes", "stage_script", "stage_storyboard", "stage_keyframes",
           "stage_voiceover", "stage_clips", "stage_timeline", "shot_keyframe", "shot_clip",
           "select_best_image"]
