"""
BG LABS - skilled AI agents
===========================

Two layers live in this module:

1. A tiny multi-provider LLM client (:func:`complete`). It talks plain REST with
   ``httpx`` so no extra dependencies are needed, and supports every provider
   the platform can be given a key for:

   ============  =====================  ==========================================
   provider      env var                default model
   ============  =====================  ==========================================
   openai        ``OPENAI_API_KEY``     ``gpt-4o-mini``
   gemini        ``GEMINI_API_KEY``     ``gemini-2.0-flash``
   anthropic     ``ANTHROPIC_API_KEY``  ``claude-3-5-haiku-20241022``
   groq          ``GROQ_API_KEY``       ``llama-3.3-70b-versatile``
   ============  =====================  ==========================================

   The active provider is picked by ``AI_PROVIDER`` if it is set and usable,
   otherwise by the first key found in the order above. With **no key at all**
   the platform falls back to ``builtin`` - deterministic, offline engines that
   still produce complete, usable output, so no feature is ever dead.

2. A registry of skilled agents (:data:`AGENTS`). Each agent declares the form
   fields the UI should render, how to phrase the LLM prompt, and a builtin
   fallback. Adding an agent = adding one entry.

Every agent returns the same envelope::

    {
      "agent": "seo", "name": "SEO Optimizer", "engine": "llm" | "builtin",
      "provider": "gemini", "model": "gemini-2.0-flash",
      "result": {...},              # agent specific
      "created_at": "2026-10-28T12:00:00+00:00"
    }
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("bglabs.agents")

LLM_TIMEOUT = float(os.getenv("AI_TIMEOUT", "90"))
LLM_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "2000"))

# Provider REST endpoints are overridable so tests can point them at a mock.
OPENAI_BASE = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
GEMINI_BASE = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
ANTHROPIC_BASE = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1").rstrip("/")
GROQ_BASE = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
OPENROUTER_BASE = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")

PROVIDER_ORDER = ("openai", "gemini", "anthropic", "groq", "openrouter")


# ===================================================================== providers
def _provider_config() -> Dict[str, Dict[str, Any]]:
    return {
        "openai": {
            "label": "OpenAI GPT",
            "key_env": "OPENAI_API_KEY",
            "model_env": "OPENAI_MODEL",
            "default_model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "style": "openai",
            "url": f"{OPENAI_BASE}/chat/completions",
        },
        "gemini": {
            "label": "Google Gemini",
            "key_env": "GEMINI_API_KEY",
            "model_env": "GEMINI_MODEL",
            "default_model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            "style": "gemini",
            "url": GEMINI_BASE,
        },
        "anthropic": {
            "label": "Anthropic Claude",
            "key_env": "ANTHROPIC_API_KEY",
            "model_env": "ANTHROPIC_MODEL",
            "default_model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"),
            "style": "anthropic",
            "url": f"{ANTHROPIC_BASE}/messages",
        },
        "openrouter": {
            "label": "OpenRouter (any model)",
            "key_env": "OPENROUTER_API_KEY",
            "model_env": "OPENROUTER_MODEL",
            "default_model": os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"),
            "style": "openai",
            "url": f"{OPENROUTER_BASE}/chat/completions",
        },
        "groq": {
            "label": "Groq (Llama)",
            "key_env": "GROQ_API_KEY",
            "model_env": "GROQ_MODEL",
            "default_model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "style": "openai",
            "url": f"{GROQ_BASE}/chat/completions",
        },
    }


def provider_key(name: str) -> str:
    config = _provider_config().get(name)
    return (os.getenv(config["key_env"], "") if config else "").strip()


def detect_provider() -> str:
    """The provider that will actually be used for the next request."""
    forced = (os.getenv("AI_PROVIDER") or "").strip().lower()
    if forced in ("builtin", "none", "off"):
        return "builtin"
    if forced and provider_key(forced):
        return forced
    for name in PROVIDER_ORDER:
        if provider_key(name):
            return name
    return "builtin"


def provider_status() -> Dict[str, Any]:
    active = detect_provider()
    providers = []
    for name in PROVIDER_ORDER:
        config = _provider_config()[name]
        providers.append({
            "id": name,
            "label": config["label"],
            "configured": bool(provider_key(name)),
            "model": os.getenv(config["model_env"], config["default_model"]),
            "active": name == active,
        })
    providers.append({
        "id": "builtin", "label": "BG LABS built-in engine", "configured": True,
        "model": "bglabs-heuristic-v1", "active": active == "builtin",
    })
    return {
        "active": active,
        "engine": "builtin" if active == "builtin" else "llm",
        "model": "bglabs-heuristic-v1" if active == "builtin"
        else os.getenv(_provider_config()[active]["model_env"], _provider_config()[active]["default_model"]),
        "providers": providers,
        "can_upgrade": active == "builtin",
        "note": ("Running on the built-in engine. Add OPENAI_API_KEY, GEMINI_API_KEY, "
                 "ANTHROPIC_API_KEY or GROQ_API_KEY to switch every agent to a real LLM "
                 "- no code change needed.") if active == "builtin" else "",
    }


def _extract_json(text: str) -> Optional[Any]:
    """Pull the first JSON object/array out of an LLM reply."""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except Exception:
                continue
    return None


async def complete(system: str, user: str, *, provider: Optional[str] = None,
                   model: Optional[str] = None, temperature: float = 0.7,
                   max_tokens: Optional[int] = None, json_mode: bool = True,
                   timeout: Optional[float] = None) -> Dict[str, Any]:
    """One chat completion. Returns ``{text, provider, model, ok, error}``.

    Never raises - callers fall back to the builtin engine when ``ok`` is False.
    """
    name = (provider or detect_provider()).strip().lower()
    if name in ("builtin", "none", "off", ""):
        return {"text": "", "provider": "builtin", "model": "bglabs-heuristic-v1", "ok": False,
                "error": "builtin provider selected"}
    config = _provider_config().get(name)
    if not config:
        return {"text": "", "provider": name, "model": model or "", "ok": False, "error": f"unknown provider {name}"}
    api_key = provider_key(name)
    if not api_key:
        return {"text": "", "provider": name, "model": model or "", "ok": False,
                "error": f"{config['key_env']} is not set"}

    chosen_model = model or os.getenv(config["model_env"], config["default_model"])
    limit = int(max_tokens or LLM_MAX_TOKENS)
    json_hint = "\n\nRespond with a single valid JSON object only - no prose, no code fences." if json_mode else ""

    try:
        async with httpx.AsyncClient(timeout=timeout or LLM_TIMEOUT) as client:
            if config["style"] == "openai":
                payload = {
                    "model": chosen_model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user + json_hint}],
                    "temperature": temperature,
                    "max_tokens": limit,
                }
                if json_mode:
                    payload["response_format"] = {"type": "json_object"}
                response = await client.post(
                    config["url"], json=payload,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                )
                response.raise_for_status()
                data = response.json()
                text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
                usage = data.get("usage") or {}
            elif config["style"] == "gemini":
                url = f"{config['url']}/models/{chosen_model}:generateContent"
                payload = {
                    "system_instruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user + json_hint}]}],
                    "generationConfig": {"temperature": temperature, "maxOutputTokens": limit},
                }
                if json_mode:
                    payload["generationConfig"]["responseMimeType"] = "application/json"
                response = await client.post(
                    url, json=payload,
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                )
                response.raise_for_status()
                data = response.json()
                parts = ((data.get("candidates") or [{}])[0].get("content", {}) or {}).get("parts") or []
                text = "".join(part.get("text", "") for part in parts)
                usage = data.get("usageMetadata") or {}
            else:  # anthropic
                payload = {
                    "model": chosen_model,
                    "system": system,
                    "messages": [{"role": "user", "content": user + json_hint}],
                    "temperature": temperature,
                    "max_tokens": limit,
                }
                response = await client.post(
                    config["url"], json=payload,
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                             "Content-Type": "application/json"},
                )
                response.raise_for_status()
                data = response.json()
                text = "".join(block.get("text", "") for block in data.get("content") or [])
                usage = data.get("usage") or {}
        return {
            "text": text or "", "provider": name, "model": chosen_model,
            "ok": bool(text), "error": "" if text else "empty completion",
            "usage": {
                "input_tokens": usage.get("prompt_tokens") or usage.get("promptTokenCount") or usage.get("input_tokens") or 0,
                "output_tokens": usage.get("completion_tokens") or usage.get("candidatesTokenCount") or usage.get("output_tokens") or 0,
            },
        }
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300]
        logger.warning("LLM %s returned %s: %s", name, exc.response.status_code, body)
        return {"text": "", "provider": name, "model": chosen_model, "ok": False,
                "error": f"HTTP {exc.response.status_code}: {body}"}
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("LLM %s failed: %s", name, exc)
        return {"text": "", "provider": name, "model": chosen_model, "ok": False, "error": str(exc)}


# ==================================================================== utilities
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, default: str = "") -> str:
    return str(value).strip() if value is not None and str(value).strip() else default


def _number(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    return max(low, min(high, _number(value, default)))


def _keywords(topic: str, extra: str = "", limit: int = 24) -> List[str]:
    stop = {
        "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "is", "are",
        "how", "why", "what", "my", "your", "you", "i", "we", "it", "this", "that", "be",
        "about", "into", "from", "by", "at", "as", "if", "but", "not", "can", "will", "do",
        "does", "kar", "karna", "hai", "ka", "ki", "ke", "aur", "mein", "par", "liye", "ek",
    }
    words = re.findall(r"[A-Za-z0-9\u0600-\u06FF\u0900-\u097F]{3,}", f"{topic} {extra}".lower())
    seen: List[str] = []
    for word in words:
        if word in stop or word in seen:
            continue
        seen.append(word)
        if len(seen) >= limit:
            break
    return seen


def _title_case(value: str) -> str:
    small = {"a", "an", "the", "and", "or", "but", "for", "of", "to", "in", "on", "with", "at", "by"}
    out = []
    for index, word in enumerate(value.split()):
        out.append(word if (index > 0 and word.lower() in small) else word[:1].upper() + word[1:])
    return " ".join(out)


# ============================================================ agent: strategist
STRATEGIST_FORMATS = [
    ("{n} {topic} mistakes that are costing you views", "listicle", "High CTR - people fear mistakes more than they want tips."),
    ("How to {topic} in {minutes} minutes (step by step)", "tutorial", "Search-driven; ranks for 'how to' queries."),
    ("I tried {topic} for 30 days - here's what happened", "experiment", "Story-driven; strong retention and shareability."),
    ("{topic}: the complete beginner's guide for {year}", "guide", "Evergreen; long watch time and good for playlists."),
    ("Why nobody talks about this in {topic}", "contrarian", "Curiosity gap; great for suggested traffic."),
    ("Cheap vs expensive {topic} - is it worth it?", "comparison", "Buyer intent; attracts sponsors and affiliate clicks."),
    ("{topic} explained in 60 seconds", "short", "Shorts/Reels funnel; feeds subscribers to long-form."),
    ("The truth about {topic} (honest review)", "review", "Trust-building; converts viewers into subscribers."),
    ("{topic} tips only pros know", "insider", "Aspirational; performs well with returning audiences."),
    ("Reacting to the worst {topic} advice on the internet", "reaction", "Low production cost, high engagement and comments."),
    ("From zero to {goal} with {topic} - full roadmap", "roadmap", "Series potential; builds binge sessions."),
    ("{topic} myths I believed for years", "myths", "Emotional hook; comment bait in a healthy way."),
]

STRATEGIST_SCHEDULE = [
    {"day": "Tuesday", "time": "16:00", "reason": "Midweek afternoon: people are done with work/school and start browsing."},
    {"day": "Thursday", "time": "18:00", "reason": "Pre-weekend evening; strong for tutorials and reviews."},
    {"day": "Saturday", "time": "11:00", "reason": "Weekend morning; long-form watch time is at its peak."},
]


def strategist_fallback(payload: Dict[str, Any]) -> Dict[str, Any]:
    topic = _text(payload.get("topic") or payload.get("niche"), "your niche")
    audience = _text(payload.get("audience"), "general audience")
    goal = _text(payload.get("goal"), "grow subscribers and watch time")
    count = _clamp(payload.get("count"), 3, 20, 10)
    year = datetime.now(timezone.utc).year
    words = _keywords(topic, audience)
    seed = ", ".join(words[:3]) or topic

    ideas = []
    for index, (template, kind, why) in enumerate(STRATEGIST_FORMATS[:count]):
        ideas.append({
            "rank": index + 1,
            "title": _title_case(template.format(topic=topic, n=index + 3, minutes=10 + index, year=year, goal=goal)),
            "format": kind,
            "hook": why,
            "first_line": f"Most people get {topic} wrong in one specific way - and it is the reason {seed} never works for them.",
            "estimated_length": "6-10 min" if kind not in ("short",) else "45-60 sec",
            "difficulty": "easy" if kind in ("reaction", "listicle", "short") else "medium",
            "score": max(55, 96 - index * 4),
        })

    return {
        "niche": topic,
        "audience": audience,
        "goal": goal,
        "positioning": f"A {topic} channel for {audience} that promises one clear outcome per video: {goal}.",
        "content_pillars": [
            {"name": f"{_title_case(topic)} fundamentals", "share": "40%", "why": "Search traffic and new viewers."},
            {"name": "Real experiments & results", "share": "30%", "why": "Trust and retention; gives you unique proof."},
            {"name": "Tools, gear & reviews", "share": "20%", "why": "Buyer intent, sponsor and affiliate revenue."},
            {"name": "Community Q&A / reactions", "share": "10%", "why": "Cheap to produce, drives comments and loyalty."},
        ],
        "ideas": ideas,
        "posting_schedule": STRATEGIST_SCHEDULE,
        "first_30_days": [
            f"Week 1: publish 2 fundamentals videos about {topic} and 1 Short cut from each.",
            "Week 2: run one experiment video, reply to every comment within 12 hours.",
            "Week 3: publish a comparison/review video and pin a community post asking what to test next.",
            "Week 4: make a roadmap video that links the previous three as a playlist.",
        ],
        "kpis": [
            {"metric": "Click-through rate", "target": "> 5%", "fix_if_low": "Rework title + thumbnail contrast before anything else."},
            {"metric": "Average view duration", "target": "> 45%", "fix_if_low": "Cut the intro to 15 seconds and add a pattern interrupt every 60-90s."},
            {"metric": "Subscriber conversion", "target": "> 1.5%", "fix_if_low": "Ask once, mid-video, tied to the next video's promise."},
        ],
    }


def strategist_prompt(payload: Dict[str, Any]) -> str:
    return (
        f"Niche/topic: {payload.get('topic') or payload.get('niche') or 'not given'}\n"
        f"Target audience: {payload.get('audience') or 'general'}\n"
        f"Channel goal: {payload.get('goal') or 'growth'}\n"
        f"Number of video ideas: {_clamp(payload.get('count'), 3, 20, 10)}\n"
        f"Extra context: {payload.get('context') or 'none'}\n\n"
        "Return JSON: {\"niche\":str,\"audience\":str,\"goal\":str,\"positioning\":str,"
        "\"content_pillars\":[{\"name\":str,\"share\":str,\"why\":str}],"
        "\"ideas\":[{\"rank\":int,\"title\":str,\"format\":str,\"hook\":str,\"first_line\":str,"
        "\"estimated_length\":str,\"difficulty\":str,\"score\":int}],"
        "\"posting_schedule\":[{\"day\":str,\"time\":str,\"reason\":str}],"
        "\"first_30_days\":[str],\"kpis\":[{\"metric\":str,\"target\":str,\"fix_if_low\":str}]}"
    )


# =========================================================== agent: scriptwriter
def scriptwriter_fallback(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Reuse the platform's template engine so output matches /api/script/generate."""
    from app.script_engine import generate_script

    topic = _text(payload.get("topic"), "your topic")
    try:
        generated = generate_script(
            topic,
            template=_text(payload.get("template"), "youtube"),
            style=_text(payload.get("style"), ""),
            tone=_text(payload.get("tone"), "conversational"),
            length=_text(payload.get("length"), "medium"),
            audience=_text(payload.get("audience"), "general"),
            language=_text(payload.get("language"), "english"),
        )
    except ValueError:
        generated = generate_script(topic)

    script = generated["script"]
    words = max(1, generated["word_count"])
    seconds = generated["estimated_seconds"]
    sections = generated.get("sections") or []
    beats = []
    per = max(1, seconds // max(1, len(sections)))
    for index, section in enumerate(sections):
        beats.append({
            "start": f"{(index * per) // 60:02d}:{(index * per) % 60:02d}",
            "beat": section.split("\n")[0][:70] or f"Section {index + 1}",
            "direction": "B-roll + on-screen text" if index % 2 else "Talking head, punch in on the key line",
        })
    return {
        **generated,
        "hook": sections[0][:220] if sections else f"Stop - if you are still doing {topic} the old way, this changes everything.",
        "cta": f"If this helped, subscribe - the next video goes deeper on {topic}.",
        "timeline": beats,
        "speaking_rate_wpm": round(words / max(0.2, seconds / 60)),
        "retention_notes": [
            "Deliver the promised payoff before 40% of the runtime.",
            "Open a second loop at the halfway mark ('and the third mistake is the worst').",
            "Keep sentences under 18 words so the voiceover breathes.",
        ],
        "words": words,
    }


def scriptwriter_prompt(payload: Dict[str, Any]) -> str:
    return (
        f"Write a {payload.get('length') or 'medium'} length {payload.get('template') or 'YouTube'} video script.\n"
        f"Topic: {payload.get('topic')}\n"
        f"Tone: {payload.get('tone') or 'conversational'}\n"
        f"Audience: {payload.get('audience') or 'general'}\n"
        f"Language: {payload.get('language') or 'english'}\n"
        f"Extra instructions: {payload.get('context') or 'none'}\n\n"
        "Return JSON: {\"script\":str (full spoken script with blank lines between sections),"
        "\"hook\":str,\"cta\":str,\"sections\":[str],"
        "\"timeline\":[{\"start\":str,\"beat\":str,\"direction\":str}],"
        "\"title_suggestion\":str,\"word_count\":int,\"estimated_seconds\":int,\"retention_notes\":[str]}"
    )


# ================================================================== agent: seo
TITLE_FORMULAS = [
    "{topic}: {benefit} (Without {pain})",
    "How I {benefit} with {topic} in {days} Days",
    "{number} {topic} Secrets Nobody Tells You",
    "The {topic} Mistake That Killed My {result}",
    "{topic} in {year}: What Actually Works",
    "Stop Doing {topic} Like This",
]

TAG_BASE = [
    "youtube", "video", "tips", "guide", "tutorial", "how to", "beginners", "2026",
    "explained", "step by step", "review", "hindi", "urdu", "english",
]


def seo_fallback(payload: Dict[str, Any]) -> Dict[str, Any]:
    topic = _text(payload.get("topic"), "your video topic")
    script = _text(payload.get("script"), "")
    words = _keywords(topic, f"{payload.get('audience','')} {payload.get('keyword','')} {script[:600]}", limit=30)
    primary = words[0] if words else topic
    year = datetime.now(timezone.utc).year

    titles = []
    for index, formula in enumerate(TITLE_FORMULAS):
        title = _title_case(formula.format(
            topic=topic, benefit="real results", pain="wasting time", days=30,
            number=index + 5, result="views", year=year,
        ))
        titles.append({"title": title[:95], "chars": min(95, len(title)),
                       "why": ["Curiosity + benefit", "Personal proof", "Numbered list", "Fear of loss",
                               "Recency", "Contrarian"][index % 6]})

    description_lines = [
        f"In this video we break down {topic} step by step, so you can get results without the guesswork.",
        "",
        "TIMESTAMPS",
        "00:00 Intro & what you will learn",
        "00:45 The problem with most advice",
        "02:10 Step 1 - the foundation",
        "04:30 Step 2 - the shortcut that works",
        "06:50 Step 3 - avoid this mistake",
        "08:20 Results & what to do next",
        "",
        "If this helped, subscribe for more practical videos like this one.",
    ]
    tags = list(dict.fromkeys([primary, topic.lower()] + [f"{primary} {w}" for w in words[:8]] + TAG_BASE))[:30]
    hashtags = [f"#{w.replace(' ', '')}" for w in ([primary] + words[:4])]

    return {
        "topic": topic,
        "primary_keyword": primary,
        "secondary_keywords": words[1:8],
        "titles": titles,
        "best_title": titles[0]["title"],
        "description": "\n".join(description_lines),
        "tags": tags,
        "hashtags": hashtags,
        "category": _guess_category(topic),
        "thumbnail_text": [w.upper() for w in (words[:2] or [topic[:12]])],
        "checklist": [
            {"item": "Keyword in the first 60 characters of the title", "status": "pass"},
            {"item": "Description starts with the value promise (first 150 chars show in search)", "status": "pass"},
            {"item": f"{len(tags)} tags, primary keyword first", "status": "pass"},
            {"item": "Chapters/timestamps present (enables key moments in search)", "status": "pass"},
            {"item": "End screen + pinned comment planned", "status": "todo"},
        ],
        "search_intent": "informational",
    }


def _guess_category(topic: str) -> str:
    lowered = topic.lower()
    table = {
        "Education": ["study", "learn", "course", "school", "tutorial", "guide", "class"],
        "Science & Technology": ["tech", "ai", "code", "software", "gadget", "phone", "app", "programming"],
        "Gaming": ["game", "gaming", "playthrough", "minecraft", "fps"],
        "Howto & Style": ["how to", "diy", "recipe", "fashion", "makeup", "style", "cooking"],
        "Entertainment": ["funny", "reaction", "vlog", "prank", "story"],
        "Film & Animation": ["animation", "film", "movie", "edit"],
        "Music": ["music", "song", "guitar", "beat"],
        "News & Politics": ["news", "politics", "election"],
        "People & Blogs": ["vlog", "life", "family"],
        "Sports": ["sport", "cricket", "football", "gym", "fitness"],
        "Autos & Vehicles": ["car", "bike", "vehicle", "review car"],
        "Travel & Events": ["travel", "trip", "tour"],
        "Nonprofits & Activism": ["charity", "ngo"],
        "Pets & Animals": ["pet", "cat", "dog"],
        "Comedy": ["comedy", "sketch"],
    }
    for category, needles in table.items():
        if any(needle in lowered for needle in needles):
            return category
    return "Education"


def seo_prompt(payload: Dict[str, Any]) -> str:
    script = _text(payload.get("script"), "")[:3000]
    return (
        f"Optimise YouTube SEO for a video about: {payload.get('topic')}\n"
        f"Audience/language: {payload.get('audience') or 'general'} / {payload.get('language') or 'english'}\n"
        f"Target keyword (optional): {payload.get('keyword') or 'choose the best one'}\n"
        f"Script (may be empty):\n{script}\n\n"
        "Return JSON: {\"primary_keyword\":str,\"secondary_keywords\":[str],"
        "\"titles\":[{\"title\":str,\"chars\":int,\"why\":str}],\"best_title\":str,"
        "\"description\":str (with TIMESTAMPS block),\"tags\":[str] (max 30),"
        "\"hashtags\":[str],\"category\":str (a real YouTube category),\"thumbnail_text\":[str],"
        "\"checklist\":[{\"item\":str,\"status\":\"pass\"|\"todo\"}],\"search_intent\":str}"
    )


# ============================================================= agent: thumbnail
THUMBNAIL_CONCEPTS = [
    {"style": "Before / After split", "composition": "Left half grey and messy, right half bright and clean, arrow between them.",
     "emotion": "transformation", "text_overlay": "BEFORE → AFTER"},
    {"style": "Extreme close-up reaction", "composition": "Face at 1/3 right, eyes wide, blurred background, one bold word top-left.",
     "emotion": "shock", "text_overlay": "REALLY?"},
    {"style": "Number-driven listicle", "composition": "Giant number on the left (fills 40% of frame), three small icons stacked right.",
     "emotion": "curiosity", "text_overlay": "5 SECRETS"},
    {"style": "Object of desire", "composition": "Product/result centred with rim light, hand reaching in, dark vignette.",
     "emotion": "want", "text_overlay": "WORTH IT?"},
    {"style": "Versus battle", "composition": "Diagonal split, two subjects facing each other, 'VS' badge in the middle.",
     "emotion": "conflict", "text_overlay": "VS"},
]

THUMBNAIL_PALETTES = [
    {"name": "High contrast pop", "colors": ["#FFD400", "#111827", "#FF3B30"], "use": "Tech, finance, listicles"},
    {"name": "Neon night", "colors": ["#22D3EE", "#0F172A", "#F472B6"], "use": "Gaming, crypto, AI"},
    {"name": "Warm creator", "colors": ["#F97316", "#FFF7ED", "#1F2937"], "use": "Vlogs, food, lifestyle"},
    {"name": "Trust blue", "colors": ["#2563EB", "#F8FAFC", "#0F172A"], "use": "Education, business, reviews"},
]


def thumbnail_fallback(payload: Dict[str, Any]) -> Dict[str, Any]:
    topic = _text(payload.get("topic"), "your video")
    mood = _text(payload.get("mood"), "curiosity")
    style = _text(payload.get("style"), "cinematic")
    words = _keywords(topic, mood, limit=6)
    overlay = (words[0] if words else topic.split()[0]).upper()[:14]

    concepts = []
    for index, concept in enumerate(THUMBNAIL_CONCEPTS[:3]):
        palette = THUMBNAIL_PALETTES[index % len(THUMBNAIL_PALETTES)]
        concepts.append({
            **concept,
            "text_overlay": overlay if index == 0 else concept["text_overlay"],
            "palette": palette,
            "prompt": (f"YouTube thumbnail, {style} style, {concept['composition']} subject: {topic}, "
                       f"mood {mood}, bold {overlay} text overlay, {palette['name']} palette "
                       f"({', '.join(palette['colors'])}), 1280x720, high contrast, sharp focus, no watermark"),
            "why_it_works": f"{concept['emotion'].title()} thumbnails outperform neutral ones in {topic} because the emotion is readable at 120px wide.",
        })

    return {
        "topic": topic,
        "mood": mood,
        "style": style,
        "spec": {"width": 1280, "height": 720, "max_bytes": 2 * 1024 * 1024, "format": "jpg/png/webp"},
        "concepts": concepts,
        "best_concept": concepts[0],
        "image_prompt": concepts[0]["prompt"],
        "text_rules": [
            "Max 4 words, 80pt+ bold sans-serif, stroke or drop shadow for separation.",
            "Face must occupy at least 25% of frame height if a person is shown.",
            "Test at 120x68 px - if the subject is unreadable, simplify.",
        ],
        "ab_test_plan": "Render concept 1 and concept 2, run each for 48h or 1000 impressions, keep the higher CTR.",
    }


def thumbnail_prompt(payload: Dict[str, Any]) -> str:
    return (
        f"Design YouTube thumbnails for a video about: {payload.get('topic')}\n"
        f"Mood: {payload.get('mood') or 'curiosity'}   Visual style: {payload.get('style') or 'cinematic'}\n"
        f"Notes: {payload.get('context') or 'none'}\n\n"
        "Return JSON: {\"topic\":str,\"mood\":str,\"style\":str,"
        "\"concepts\":[{\"style\":str,\"composition\":str,\"emotion\":str,\"text_overlay\":str,"
        "\"palette\":{\"name\":str,\"colors\":[str],\"use\":str},\"prompt\":str (a ready-to-use image generation prompt),\"why_it_works\":str}],"
        "\"best_concept\":{...same shape...},\"image_prompt\":str,\"text_rules\":[str],\"ab_test_plan\":str}"
    )


# ========================================================= agent: voice director
MOOD_VOICE_MAP = {
    "energetic": {"rate": "+12%", "pitch": "+4Hz", "voices": ["Aria", "Guy", "Emma", "Brian"]},
    "calm": {"rate": "-8%", "pitch": "-2Hz", "voices": ["Michelle", "Andrew", "Jenny", "Roger"]},
    "professional": {"rate": "+0%", "pitch": "+0Hz", "voices": ["Andrew", "Sonia", "Ryan", "Libby"]},
    "storytelling": {"rate": "-4%", "pitch": "-1Hz", "voices": ["Ava", "Thomas", "Emma", "Libby"]},
    "authoritative": {"rate": "+2%", "pitch": "-3Hz", "voices": ["Roger", "Ryan", "Brian", "Thomas"]},
    "friendly": {"rate": "+4%", "pitch": "+2Hz", "voices": ["Jenny", "Guy", "Aria", "Michelle"]},
}


def voice_director_fallback(payload: Dict[str, Any]) -> Dict[str, Any]:
    from tts_engine import EDGE_VOICES, resolve_voice_key, voices_for_language

    mood = _text(payload.get("mood"), "professional").lower()
    language = _text(payload.get("language"), "en").lower()[:2]
    gender = _text(payload.get("gender"), "").lower()
    script = _text(payload.get("script"), "")
    topic = _text(payload.get("topic"), "")
    tuning = MOOD_VOICE_MAP.get(mood, MOOD_VOICE_MAP["professional"])

    pool = voices_for_language(language) or list(EDGE_VOICES)
    preferred: List[str] = []
    for name in tuning["voices"]:
        key = resolve_voice_key(name, language)
        if key in EDGE_VOICES and key not in preferred:
            preferred.append(key)
    candidates = [key for key in preferred if key in pool] or pool[:6]
    if gender in ("male", "m"):
        candidates = [k for k in candidates if EDGE_VOICES[k]["gender"].lower() == "male"] or candidates
    elif gender in ("female", "f"):
        candidates = [k for k in candidates if EDGE_VOICES[k]["gender"].lower() == "female"] or candidates

    options = []
    for key in candidates[:4]:
        info = EDGE_VOICES[key]
        options.append({
            "voice_key": key, "name": info["name"], "gender": info["gender"],
            "language": info["lang"], "accent": info.get("accent", ""),
            "rate": tuning["rate"], "pitch": tuning["pitch"],
            "why": f"{info['name']} ({info.get('accent')}) reads {mood} copy naturally at {tuning['rate']}.",
            "score": max(60, 95 - 6 * len(options)),
        })

    words = len(script.split()) if script else 0
    pauses = []
    for index, line in enumerate([s for s in re.split(r"(?<=[.!?])\s+", script) if s][:6]):
        pauses.append({"after": line[:80], "pause_ms": 500 if index == 0 else 300,
                       "emphasis": line.split()[-1] if line.split() else ""})

    return {
        "topic": topic,
        "mood": mood,
        "language": language,
        "recommended_voice": options[0]["voice_key"] if options else resolve_voice_key(None, language),
        "recommended_name": options[0]["name"] if options else "Aria",
        "rate": tuning["rate"],
        "pitch": tuning["pitch"],
        "speed_multiplier": round(1.0 + int(tuning["rate"].replace("%", "").replace("+", "")) / 100, 2),
        "options": options,
        "pauses": pauses,
        "pronunciation_notes": [
            "Spell out tricky brand names phonetically in the script before generating.",
            "Add a comma where you want a breath; TTS respects punctuation.",
            "Keep numbers as digits for dates, as words for emphasis ('three reasons').",
        ],
        "estimated_seconds": max(1, int(words / 2.6)) if words else 0,
        "direction": f"Read {mood}: {tuning['rate']} rate, {tuning['pitch']} pitch, lift on questions, drop at section ends.",
    }


def voice_director_prompt(payload: Dict[str, Any]) -> str:
    script = _text(payload.get("script"), "")[:2500]
    return (
        f"Direct the voiceover for this video.\nTopic: {payload.get('topic') or 'not given'}\n"
        f"Mood: {payload.get('mood') or 'professional'}   Language: {payload.get('language') or 'en'}   "
        f"Preferred gender: {payload.get('gender') or 'any'}\nScript:\n{script}\n\n"
        "Return JSON: {\"recommended_voice\":str,\"recommended_name\":str,\"rate\":str (Edge-TTS form e.g. '+10%'),"
        "\"pitch\":str (e.g. '+2Hz'),\"speed_multiplier\":float,"
        "\"options\":[{\"voice_key\":str,\"name\":str,\"gender\":str,\"language\":str,\"accent\":str,\"rate\":str,\"pitch\":str,\"why\":str,\"score\":int}],"
        "\"pauses\":[{\"after\":str,\"pause_ms\":int,\"emphasis\":str}],\"pronunciation_notes\":[str],"
        "\"estimated_seconds\":int,\"direction\":str}"
    )


# ====================================================== agent: comment responder
def _classify_comment(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\b(buy|click here|http|promo|casino|crypto signal)\b", lowered):
        return "spam"
    if "?" in text or re.search(r"\b(how|why|what|when|where|can i|could you|please)\b", lowered):
        return "question"
    if re.search(r"\b(bad|wrong|stupid|hate|fake|dislike|useless|boring)\b", lowered):
        return "criticism"
    if re.search(r"\b(love|great|amazing|best|thank|thanks|awesome|nice|helpful)\b", lowered):
        return "praise"
    if re.search(r"\b(first|subscribe|notification)\b", lowered):
        return "engagement"
    return "general"


COMMENT_REPLIES = {
    "question": "Good question! {answer_lead} If you want, I can cover this in a full video - tell me which part to go deeper on.",
    "praise": "Thank you, that means a lot! {next_lead}",
    "criticism": "Appreciate the honest feedback. {fix_lead} What would you have liked to see covered instead?",
    "spam": "",  # hidden, never replied to
    "engagement": "Welcome! {next_lead}",
    "general": "Thanks for watching! {next_lead}",
}


def comment_responder_fallback(payload: Dict[str, Any]) -> Dict[str, Any]:
    tone = _text(payload.get("tone"), "friendly")
    topic = _text(payload.get("video_topic") or payload.get("topic"), "this topic")
    raw = _text(payload.get("comments"), "")
    lines = [line.strip(" -\u2022\t") for line in re.split(r"[\n\r]+", raw) if line.strip()]
    if not lines:
        lines = ["Great video, thanks for sharing!", "How do I start with this as a beginner?", "This did not work for me."]

    leads = {
        "answer_lead": f"The short version is in the video at the step where we set up {topic} - the detail most people miss is doing it in order.",
        "next_lead": f"The next video goes deeper into {topic}, so make sure you are subscribed.",
        "fix_lead": f"You are right that {topic} can be done differently - I showed the method that works for most setups.",
    }
    replies = []
    for index, line in enumerate(lines[:25]):
        kind = _classify_comment(line)
        template = COMMENT_REPLIES[kind]
        reply = ""
        if template:
            reply = template.format(**leads)
            if tone == "professional":
                reply = reply.replace("!", ".").replace("Thank you", "Thank you for the feedback -")
            elif tone == "playful":
                reply = reply + " \U0001f64c"
        replies.append({
            "index": index + 1,
            "comment": line[:280],
            "sentiment": kind,
            "should_reply": kind != "spam",
            "reply": reply,
            "priority": "high" if kind in ("question", "criticism") else "normal",
        })

    return {
        "video_topic": topic,
        "tone": tone,
        "total": len(replies),
        "replies": replies,
        "summary": {
            "questions": sum(1 for r in replies if r["sentiment"] == "question"),
            "praise": sum(1 for r in replies if r["sentiment"] == "praise"),
            "criticism": sum(1 for r in replies if r["sentiment"] == "criticism"),
            "spam": sum(1 for r in replies if r["sentiment"] == "spam"),
        },
        "video_ideas_from_comments": [
            f"A follow-up answering: '{next((r['comment'] for r in replies if r['sentiment'] == 'question'), 'your top question')}'",
            f"{_title_case(topic)} - common mistakes viewers mentioned in the comments",
        ],
        "moderation": [r["comment"] for r in replies if r["sentiment"] == "spam"],
    }


def comment_responder_prompt(payload: Dict[str, Any]) -> str:
    return (
        f"Reply to these YouTube comments in a {payload.get('tone') or 'friendly'} tone.\n"
        f"Video topic: {payload.get('video_topic') or payload.get('topic') or 'not given'}\n"
        f"Comments (one per line):\n{_text(payload.get('comments'), '')[:2500]}\n\n"
        "Return JSON: {\"total\":int,\"replies\":[{\"index\":int,\"comment\":str,\"sentiment\":\"question\"|\"praise\"|"
        "\"criticism\"|\"spam\"|\"engagement\"|\"general\",\"should_reply\":bool,\"reply\":str,\"priority\":\"high\"|\"normal\"}],"
        "\"summary\":{\"questions\":int,\"praise\":int,\"criticism\":int,\"spam\":int},"
        "\"video_ideas_from_comments\":[str],\"moderation\":[str]}"
    )


# ============================================================ agent: analytics
def analytics_fallback(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = payload.get("data") or payload.get("stats") or {}
    if isinstance(data, str):
        parsed = _extract_json(data)
        data = parsed if isinstance(parsed, dict) else {}
    goal = _text(payload.get("goal"), "grow watch time and subscribers")

    def num(*keys: Any) -> float:
        for key in keys:
            for source in (data, data.get("statistics") or {}, data.get("channel") or {}):
                if isinstance(source, dict) and source.get(key) not in (None, ""):
                    try:
                        return float(source[key])
                    except (TypeError, ValueError):
                        continue
        return 0.0

    views = num("viewCount", "views")
    subs = num("subscriberCount", "subscribers")
    videos = num("videoCount", "videos")
    likes = num("likeCount", "likes")
    comments = num("commentCount", "comments")
    avg_view = num("averageViewDuration", "avg_duration")
    ctr = num("ctr", "clickThroughRate")

    insights, actions = [], []
    if videos:
        per_video = views / videos
        insights.append({"metric": "Views per video", "value": f"{per_video:,.0f}",
                         "read": "Healthy" if per_video > 500 else "Below par",
                         "detail": "Each upload carries this much reach on average."})
        if per_video < 500:
            actions.append("Fix packaging first: 3 title/thumbnail variants per video before publishing.")
    if views and subs:
        ratio = subs / views * 100
        insights.append({"metric": "Subscriber conversion", "value": f"{ratio:.2f}%",
                         "read": "Strong" if ratio > 1.5 else "Weak",
                         "detail": "Share of total views that turned into subscribers."})
        if ratio < 1.5:
            actions.append("Add one mid-video subscribe ask tied to the next video's promise (not a generic 'please subscribe').")
    if ctr:
        insights.append({"metric": "CTR", "value": f"{ctr:.1f}%", "read": "Good" if ctr > 5 else "Low",
                         "detail": "Impressions that became clicks."})
        if ctr < 5:
            actions.append("Raise thumbnail contrast and cut the title under 55 characters.")
    if avg_view:
        insights.append({"metric": "Avg view duration", "value": f"{int(avg_view // 60)}m{int(avg_view % 60)}s",
                         "read": "OK" if avg_view > 120 else "Short", "detail": "How long viewers stay."})
        if avg_view < 120:
            actions.append("Move the payoff into the first 30 seconds and cut the intro sting.")
    if likes and views:
        insights.append({"metric": "Like rate", "value": f"{likes / views * 100:.2f}%",
                         "read": "Good" if likes / views > 0.03 else "Low", "detail": "Engagement signal for the recommender."})
    if comments and views:
        insights.append({"metric": "Comment rate", "value": f"{comments / views * 100:.3f}%",
                         "read": "Good" if comments / views > 0.002 else "Low", "detail": "Ask a specific question to lift this."})
    if not insights:
        insights.append({"metric": "Data", "value": "not supplied", "read": "Connect your channel",
                         "detail": "Connect YouTube to pull live numbers, or paste a JSON stats blob into the data field."})
    if not actions:
        actions = [
            "Publish consistently on the same two days each week.",
            "Turn every long video into 2 Shorts to feed the subscriber loop.",
            "Reply to every comment in the first 12 hours to boost early engagement.",
        ]

    return {
        "goal": goal,
        "source": "youtube_api" if data else "manual",
        "numbers": {"views": int(views), "subscribers": int(subs), "videos": int(videos),
                    "likes": int(likes), "comments": int(comments), "ctr": ctr,
                    "average_view_duration_seconds": int(avg_view)},
        "insights": insights,
        "next_actions": actions,
        "experiment": {"hypothesis": "Better packaging lifts CTR above 5%",
                       "test": "Re-do the thumbnail + title of the last 3 videos",
                       "window": "7 days", "success_metric": "CTR and views per video"},
        "forecast": {"next_30_days_views": int(views * 0.12) if views else 0,
                     "assumption": "Assumes current upload cadence and a packaging improvement."},
    }


def analytics_prompt(payload: Dict[str, Any]) -> str:
    data = payload.get("data") or payload.get("stats") or {}
    if not isinstance(data, str):
        data = json.dumps(data, ensure_ascii=False)[:2500]
    return (
        f"Interpret this channel/video analytics data and give the next actions.\n"
        f"Goal: {payload.get('goal') or 'growth'}\nData: {data}\n\n"
        "Return JSON: {\"goal\":str,\"numbers\":{...as given, numeric...},"
        "\"insights\":[{\"metric\":str,\"value\":str,\"read\":str,\"detail\":str}],"
        "\"next_actions\":[str],\"experiment\":{\"hypothesis\":str,\"test\":str,\"window\":str,\"success_metric\":str},"
        "\"forecast\":{\"next_30_days_views\":int,\"assumption\":str}}"
    )


# ============================================================== agent: title A/B
def title_ab_fallback(payload: Dict[str, Any]) -> Dict[str, Any]:
    topic = _text(payload.get("topic"), "your video")
    audience = _text(payload.get("audience"), "general audience")
    keyword = _text(payload.get("keyword"), "")
    words = _keywords(topic, f"{audience} {keyword}", limit=8)
    year = datetime.now(timezone.utc).year

    variants = [
        {"id": "A", "title": f"{_title_case(topic)}: The Only Guide {audience} Needs", "angle": "authority",
         "predicted_ctr": 5.4, "reason": "Clear promise + audience callout; strong for search."},
        {"id": "B", "title": f"I Tested {topic} So You Don't Have To", "angle": "personal proof",
         "predicted_ctr": 6.8, "reason": "Curiosity + saved effort; performs well in suggested feeds."},
        {"id": "C", "title": f"{_number(len(words) + 3, 5)} {topic} Mistakes Killing Your {words[0] if words else 'results'}",
         "angle": "fear of loss", "predicted_ctr": 7.2, "reason": "Numbers + loss aversion = highest CTR pattern."},
        {"id": "D", "title": f"{topic} in {year} - What Actually Works", "angle": "recency",
         "predicted_ctr": 5.9, "reason": "Date makes old competitors look stale."},
        {"id": "E", "title": f"Stop Doing {topic} Like This", "angle": "contrarian",
         "predicted_ctr": 6.4, "reason": "Pattern interrupt; short enough to never truncate."},
        {"id": "F", "title": f"How to {topic} (Even If You Are a Beginner)", "angle": "how-to + objection handling",
         "predicted_ctr": 5.6, "reason": "Evergreen search intent with an objection removed."},
    ]
    for variant in variants:
        variant["chars"] = len(variant["title"])
        variant["truncates_on_mobile"] = variant["chars"] > 55
    ranked = sorted(variants, key=lambda item: -item["predicted_ctr"])
    return {
        "topic": topic, "audience": audience, "keyword": keyword or (words[0] if words else topic),
        "variants": variants, "ranking": [v["id"] for v in ranked],
        "winner": ranked[0], "runner_up": ranked[1],
        "test_plan": {
            "method": "Run the winner for 72h, then swap to the runner-up for 72h on the same video.",
            "metric": "CTR at >1000 impressions each",
            "decision_rule": "Keep whichever has the higher CTR; if within 0.3%, keep the shorter title.",
        },
        "thumbnail_pairing": f"Pair '{ranked[0]['title']}' with a face + one bold word overlay matching the {ranked[0]['angle']} angle.",
    }


def title_ab_prompt(payload: Dict[str, Any]) -> str:
    return (
        f"Generate A/B test title variants for a YouTube video.\n"
        f"Topic: {payload.get('topic')}\nAudience: {payload.get('audience') or 'general'}\n"
        f"Keyword: {payload.get('keyword') or 'optional'}\n\n"
        "Return JSON: {\"variants\":[{\"id\":str,\"title\":str,\"angle\":str,\"predicted_ctr\":float,\"reason\":str,\"chars\":int}],"
        "\"ranking\":[str],\"winner\":{...},\"runner_up\":{...},"
        "\"test_plan\":{\"method\":str,\"metric\":str,\"decision_rule\":str},\"thumbnail_pairing\":str}"
    )


# ================================================================= agent registry
def _field(key: str, label: str, kind: str = "text", placeholder: str = "",
           required: bool = False, options: Optional[List[str]] = None, default: Any = "") -> Dict[str, Any]:
    field: Dict[str, Any] = {"key": key, "label": label, "type": kind, "placeholder": placeholder,
                             "required": required, "default": default}
    if options:
        field["options"] = options
    return field


AGENTS: List[Dict[str, Any]] = [
    {
        "id": "strategist", "name": "Content Strategist", "emoji": "\U0001f9e0",
        "tagline": "Niche positioning, 10 ranked video ideas, pillars and a 30-day plan.",
        "skills": ["niche research", "idea ranking", "content pillars", "posting schedule", "KPI targets"],
        "system": "You are a YouTube growth strategist who has scaled channels from 0 to 1M subscribers. "
                  "You are specific, numbers-driven and never generic. Always output valid JSON only.",
        "fields": [
            _field("topic", "Niche / topic", placeholder="e.g. home cooking for students", required=True),
            _field("audience", "Target audience", placeholder="e.g. beginners aged 18-25"),
            _field("goal", "Channel goal", placeholder="e.g. 10k subscribers in 6 months"),
            _field("count", "Number of ideas", "number", default=10),
            _field("context", "Extra context", "textarea", placeholder="Competitors, what you already posted, constraints..."),
        ],
        "prompt": strategist_prompt, "fallback": strategist_fallback,
    },
    {
        "id": "scriptwriter", "name": "Script Writer", "emoji": "\u270d\ufe0f",
        "tagline": "Full spoken script with hook, timeline beats and retention notes.",
        "skills": ["hooks", "story structure", "pacing", "CTA writing", "timeline beats"],
        "system": "You are a professional YouTube scriptwriter. You write spoken-word copy that keeps viewers watching: "
                  "short sentences, a payoff in the first 15 seconds, one open loop, no filler. Output valid JSON only.",
        "fields": [
            _field("topic", "Video topic", placeholder="e.g. 5 AI tools that save 10 hours a week", required=True),
            _field("template", "Format", "select", options=["youtube", "educational", "storytelling", "sales",
                                                            "podcast", "short_form", "webinar"], default="youtube"),
            _field("tone", "Tone", "select", options=["conversational", "professional", "energetic", "calm",
                                                      "authoritative"], default="conversational"),
            _field("length", "Length", "select", options=["short", "medium", "long"], default="medium"),
            _field("audience", "Audience", placeholder="e.g. small business owners"),
            _field("language", "Language", placeholder="english"),
            _field("context", "Extra instructions", "textarea", placeholder="Points to cover, sponsors, links..."),
        ],
        "prompt": scriptwriter_prompt, "fallback": scriptwriter_fallback,
    },
    {
        "id": "seo", "name": "SEO Optimizer", "emoji": "\U0001f50d",
        "tagline": "Titles, description with chapters, 30 tags, hashtags and an audit checklist.",
        "skills": ["keyword research", "title formulas", "description chapters", "tag strategy", "SEO audit"],
        "system": "You are a YouTube SEO specialist. You optimise for both search and the recommendation feed, "
                  "never keyword-stuff, and always keep titles under 60 characters where possible. Output valid JSON only.",
        "fields": [
            _field("topic", "Video topic", required=True),
            _field("keyword", "Target keyword", placeholder="optional - leave blank to auto-pick"),
            _field("script", "Script (for context)", "textarea", placeholder="Paste the script to align metadata with content"),
            _field("audience", "Audience / language", placeholder="e.g. Urdu speakers, beginners"),
        ],
        "prompt": seo_prompt, "fallback": seo_fallback,
    },
    {
        "id": "thumbnail", "name": "Thumbnail Designer", "emoji": "\U0001f3a8",
        "tagline": "Three concepts with palettes, overlay text and a ready image-generation prompt.",
        "skills": ["composition", "colour psychology", "overlay typography", "A/B testing", "image prompts"],
        "system": "You are a thumbnail artist who designs for 120px-wide readability. You think in contrast, faces and "
                  "a maximum of four words. You also write excellent image-generation prompts. Output valid JSON only.",
        "fields": [
            _field("topic", "Video topic", required=True),
            _field("mood", "Mood", "select", options=["curiosity", "shock", "calm", "energetic", "luxury", "funny"],
                   default="curiosity"),
            _field("style", "Visual style", "select", options=["cinematic", "vivid", "anime", "digital-art",
                                                               "oil-painting", "minimal"], default="cinematic"),
            _field("context", "Notes", "textarea", placeholder="Brand colours, must-show object, face or no face..."),
            _field("render", "Also generate the image", "select", options=["no", "yes"], default="no"),
        ],
        "prompt": thumbnail_prompt, "fallback": thumbnail_fallback, "can_render": True,
    },
    {
        "id": "voice_director", "name": "Voice Director", "emoji": "\U0001f399\ufe0f",
        "tagline": "Picks the best neural voice, rate, pitch and pause map for your script.",
        "skills": ["voice casting", "pacing", "emotion mapping", "pronunciation notes", "TTS settings"],
        "system": "You are a voice-over director working with Microsoft Edge neural TTS voices. You choose voices by "
                  "accent and mood and specify rate/pitch in Edge-TTS syntax ('+10%', '-2Hz'). Output valid JSON only.",
        "fields": [
            _field("topic", "Video topic", placeholder="optional if you paste the script"),
            _field("script", "Script", "textarea", placeholder="Paste the script to get pause marks and timing"),
            _field("mood", "Mood", "select", options=list(MOOD_VOICE_MAP) + ["neutral"], default="professional"),
            _field("language", "Language", "select", options=["en", "ur", "hi", "es", "fr", "de", "ar"], default="en"),
            _field("gender", "Preferred gender", "select", options=["any", "male", "female"], default="any"),
        ],
        "prompt": voice_director_prompt, "fallback": voice_director_fallback, "can_speak": True,
    },
    {
        "id": "comment_responder", "name": "Comment Responder", "emoji": "\U0001f4ac",
        "tagline": "Classifies comments and writes on-brand replies; flags spam for moderation.",
        "skills": ["sentiment analysis", "reply writing", "spam detection", "idea mining", "community management"],
        "system": "You are a community manager for a YouTube channel. You reply in the creator's voice, turn questions "
                  "into content ideas, never argue with criticism and never reply to spam. Output valid JSON only.",
        "fields": [
            _field("video_topic", "Video topic", placeholder="e.g. budget smartphones 2026"),
            _field("comments", "Comments (one per line)", "textarea", required=True,
                   placeholder="Paste comments, or leave blank after connecting YouTube to fetch them automatically"),
            _field("tone", "Tone", "select", options=["friendly", "professional", "playful"], default="friendly"),
        ],
        "prompt": comment_responder_prompt, "fallback": comment_responder_fallback,
    },
    {
        "id": "analytics", "name": "Analytics Interpreter", "emoji": "\U0001f4c8",
        "tagline": "Turns channel/video stats into insights, next actions and one experiment.",
        "skills": ["metric diagnosis", "CTR & retention", "action plans", "experiments", "forecasting"],
        "system": "You are a YouTube analytics consultant. You diagnose the funnel (impressions -> CTR -> retention -> "
                  "subscribers) and prescribe the single highest-leverage action. Output valid JSON only.",
        "fields": [
            _field("goal", "Goal", placeholder="e.g. double watch time in 90 days"),
            _field("data", "Stats (JSON or numbers)", "textarea",
                   placeholder='{"views":12000,"subscribers":340,"ctr":3.1,"averageViewDuration":95} - or connect YouTube to auto-fill'),
        ],
        "prompt": analytics_prompt, "fallback": analytics_fallback,
    },
    {
        "id": "title_ab", "name": "Title A/B Tester", "emoji": "\U0001f9ea",
        "tagline": "Six ranked title variants with predicted CTR and a test plan.",
        "skills": ["title formulas", "CTR prediction", "A/B methodology", "thumbnail pairing"],
        "system": "You are a packaging expert who A/B tests YouTube titles. You balance search intent against "
                  "suggested-feed curiosity and always keep titles under 60 characters. Output valid JSON only.",
        "fields": [
            _field("topic", "Video topic", required=True),
            _field("audience", "Audience", placeholder="e.g. freelance designers"),
            _field("keyword", "Keyword", placeholder="optional"),
        ],
        "prompt": title_ab_prompt, "fallback": title_ab_fallback,
    },
]

AGENT_BY_ID: Dict[str, Dict[str, Any]] = {agent["id"]: agent for agent in AGENTS}

# Order the Auto Pilot runs its agents in.
AUTOPILOT_STEPS: Tuple[str, ...] = ("strategist", "scriptwriter", "voice_director", "thumbnail", "seo")


def public_agents() -> List[Dict[str, Any]]:
    """Agent metadata for the UI (no prompts, no callables)."""
    return [{
        "id": agent["id"], "name": agent["name"], "emoji": agent["emoji"],
        "tagline": agent["tagline"], "skills": agent["skills"], "fields": agent["fields"],
        "can_render": bool(agent.get("can_render")), "can_speak": bool(agent.get("can_speak")),
    } for agent in AGENTS]


def build_envelope(agent: Dict[str, Any], result: Dict[str, Any], *, engine: str,
                   provider: str, model: str, error: str = "",
                   usage: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "agent": agent["id"], "name": agent["name"], "emoji": agent["emoji"],
        "engine": engine, "provider": provider, "model": model,
        "result": result, "error": error, "usage": usage or {},
        "created_at": _now(),
    }


async def run_agent(agent_id: str, payload: Optional[Dict[str, Any]] = None, *,
                    provider: Optional[str] = None, model: Optional[str] = None) -> Dict[str, Any]:
    """Run one agent: try the LLM first, always fall back to the builtin engine."""
    agent = AGENT_BY_ID.get((agent_id or "").strip().lower())
    if not agent:
        raise KeyError(f"unknown agent '{agent_id}'")
    payload = dict(payload or {})
    for field in agent["fields"]:
        if field.get("required") and not _text(payload.get(field["key"])):
            raise ValueError(f"'{field['label']}' is required for the {agent['name']} agent")

    chosen = (provider or detect_provider()).strip().lower()
    fallback = agent["fallback"](payload)

    if chosen == "builtin":
        return build_envelope(agent, fallback, engine="builtin", provider="builtin",
                              model="bglabs-heuristic-v1")

    try:
        completion = await complete(agent["system"], agent["prompt"](payload), provider=chosen,
                                    model=model, json_mode=True)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("agent %s LLM call crashed: %s", agent_id, exc)
        completion = {"text": "", "provider": chosen, "model": model or "", "ok": False, "error": str(exc)}

    if not completion.get("ok"):
        return build_envelope(agent, fallback, engine="builtin", provider="builtin",
                              model="bglabs-heuristic-v1", error=completion.get("error", ""))

    parsed = _extract_json(completion["text"])
    if not isinstance(parsed, dict):
        # Some models wrap the object in a list or return prose - keep the builtin result.
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            parsed = parsed[0]
        else:
            return build_envelope(agent, fallback, engine="builtin", provider=completion["provider"],
                                  model=completion["model"], error="LLM returned non-JSON output")

    merged = dict(fallback)
    merged.update({k: v for k, v in parsed.items() if v not in (None, "", [], {})})
    return build_envelope(agent, merged, engine="llm", provider=completion["provider"],
                          model=completion["model"], usage=completion.get("usage"))


async def run_autopilot(payload: Optional[Dict[str, Any]] = None, *, provider: Optional[str] = None,
                        steps: Optional[List[str]] = None) -> Dict[str, Any]:
    """Multi-agent pipeline: strategist -> scriptwriter -> voice -> thumbnail -> SEO.

    Each step is fed the previous step's output, exactly like a small production
    team handing work down the line. Steps run sequentially because they depend
    on each other; independent agents would be gathered.
    """
    payload = dict(payload or {})
    topic = _text(payload.get("topic"), "")
    if not topic:
        raise ValueError("'topic' is required for Auto Pilot")
    wanted = [s for s in (steps or AUTOPILOT_STEPS) if s in AGENT_BY_ID]

    outputs: Dict[str, Any] = {}
    envelopes: List[Dict[str, Any]] = []
    started = datetime.now(timezone.utc)

    for step in wanted:
        step_payload: Dict[str, Any] = {"topic": topic, "audience": payload.get("audience"),
                                        "goal": payload.get("goal"), "mood": payload.get("mood"),
                                        "language": payload.get("language"), "tone": payload.get("tone"),
                                        "context": payload.get("context")}
        if step == "scriptwriter":
            script = outputs.get("strategist", {})
            step_payload["length"] = payload.get("length") or "medium"
            step_payload["template"] = payload.get("template") or "youtube"
            if isinstance(script, dict) and script.get("ideas"):
                step_payload["topic"] = _text(payload.get("topic"), topic)
                step_payload["context"] = f"Angle: {script['ideas'][0].get('title', '')}. " \
                                          f"Hook: {script['ideas'][0].get('hook', '')}"
        elif step in ("voice_director", "seo", "thumbnail"):
            written = outputs.get("scriptwriter", {})
            if isinstance(written, dict):
                step_payload["script"] = written.get("script") or written.get("content") or ""
            if step == "seo" and isinstance(written, dict) and written.get("title_suggestion"):
                step_payload["keyword"] = payload.get("keyword") or ""
        step_payload = {k: v for k, v in step_payload.items() if v not in (None, "")}

        envelope = await run_agent(step, step_payload, provider=provider)
        envelopes.append(envelope)
        outputs[step] = envelope["result"]

    script_result = outputs.get("scriptwriter") or {}
    seo_result = outputs.get("seo") or {}
    voice_result = outputs.get("voice_director") or {}
    thumb_result = outputs.get("thumbnail") or {}

    package = {
        "topic": topic,
        "title": seo_result.get("best_title") or (script_result.get("title_suggestion") if isinstance(script_result, dict) else "") or topic,
        "script": script_result.get("script") or script_result.get("content") or "",
        "description": seo_result.get("description") or "",
        "tags": seo_result.get("tags") or [],
        "hashtags": seo_result.get("hashtags") or [],
        "category": seo_result.get("category") or "Education",
        "voice": {"voice_key": voice_result.get("recommended_voice"), "name": voice_result.get("recommended_name"),
                  "rate": voice_result.get("rate"), "pitch": voice_result.get("pitch")},
        "thumbnail": {"prompt": thumb_result.get("image_prompt") or "",
                      "text_overlay": (thumb_result.get("best_concept") or {}).get("text_overlay", ""),
                      "concepts": thumb_result.get("concepts") or []},
        "duration_seconds": _number(script_result.get("estimated_seconds"), 0),
        "word_count": _number(script_result.get("word_count") or script_result.get("words"), 0),
    }

    return {
        "topic": topic,
        "steps": [e["agent"] for e in envelopes],
        "agents": envelopes,
        "package": package,
        "engine_mix": sorted({e["engine"] for e in envelopes}),
        "providers": sorted({e["provider"] for e in envelopes}),
        "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
        "created_at": _now(),
        "next_actions": [
            "Generate the voiceover from the script (AI Voiceover studio, voice pre-selected).",
            "Render the thumbnail from the image prompt (AI Image studio).",
            "Connect a YouTube channel and publish with the prepared title/description/tags.",
        ],
    }


__all__ = [
    "AGENTS", "AGENT_BY_ID", "AUTOPILOT_STEPS", "PROVIDER_ORDER",
    "complete", "detect_provider", "provider_status", "public_agents",
    "run_agent", "run_autopilot", "build_envelope",
]
