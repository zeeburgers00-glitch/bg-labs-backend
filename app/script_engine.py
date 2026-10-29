"""
BG LABS - script engine
=======================

Template based script writing (no paid LLM key required). Shared by
``/api/script/write`` (legacy endpoint) and ``/api/script/generate`` (the one the
web UI calls) so both produce identical output.
"""
from __future__ import annotations

from typing import Any, Dict, List

TEMPLATES: Dict[str, Dict[str, Any]] = {
    "youtube": {
        "short": {
            "intro": "Hey! Quick video on {topic}.",
            "body": "Here's what you need to know about {topic}.",
            "outro": "Like & subscribe!",
        },
        "medium": {
            "intro": "Hey everyone! Welcome back. Today we're diving into {topic}.",
            "body": (
                "Let me break this down. {topic} is fascinating. Here's what you need to know. "
                "First, the basics. Then we'll go deeper. And finally, the key takeaways."
            ),
            "outro": "That's it! Smash like and subscribe for more content like this!",
        },
        "long": {
            "intro": (
                "Hey everyone! Welcome back to the channel. Today we're going to do a deep dive into {topic}. "
                "This is something I've been wanting to cover for a while now, and I think you're going to find this really valuable."
            ),
            "body": (
                "Let's start with the basics. {topic} has been gaining a lot of attention recently, and for good reason. "
                "The fundamentals are solid, there's a lot to unpack here.\n\n"
                "First, let's talk about why {topic} matters. In today's landscape, understanding this can give you a significant advantage.\n\n"
                "Now, let's look at the key aspects. There are several important points to consider.\n\n"
                "Finally, let me share my personal take on what the future holds."
            ),
            "outro": (
                "And that wraps up our deep dive into {topic}! If you found this helpful, please hit that like button and subscribe. "
                "Drop a comment below with your thoughts. See you in the next one!"
            ),
        },
    },
    "podcast": {
        "short": "Welcome. Today: {topic}. Let's dive in.",
        "medium": (
            "Welcome to another episode. Today we're exploring {topic}. So {topic} has been on everyone's mind. "
            "Here's what I've discovered through research and experience. The first thing to understand is... "
            "The key point is... And that brings us to the bigger picture. That wraps up today's discussion on {topic}. Thanks for tuning in."
        ),
        "long": (
            "Welcome to another episode of our podcast. I'm your host, and today we have a really exciting topic to discuss: {topic}.\n\n"
            "Now, {topic} is something that's been generating a lot of buzz lately, and I wanted to take some time to really dig into it.\n\n"
            "Let's start from the beginning. {topic} first came to my attention when... Since then, I've been researching extensively.\n\n"
            "The first major insight about {topic} is... This is crucial because it changes how we think about the whole subject.\n\n"
            "Moving on to the second point... This is where things get really interesting.\n\n"
            "And finally, the third key takeaway... This ties everything together nicely.\n\n"
            "That's all for today's episode on {topic}. I hope you found this valuable. If you did, please share it with someone who needs to hear this. Until next time!"
        ),
    },
    "presentation": {
        "short": "Today I'll present on {topic}. Let's begin.",
        "medium": (
            "Good morning everyone. Today I'll be presenting on {topic}. Let's examine the key aspects. "
            "First, the overview. {topic} is a critical area that impacts many industries. The data shows clear trends. "
            "In conclusion, {topic} presents significant opportunities. Thank you for your attention. Questions?"
        ),
        "long": (
            "Good morning everyone, and thank you for being here today. My name is [Name], and I'll be presenting on {topic}.\n\n"
            "Let me start with an overview. {topic} has become increasingly important in recent years, and understanding it is crucial for success.\n\n"
            "First, let's look at the background. {topic} emerged as a key area of focus when... Since then, understanding it has evolved significantly.\n\n"
            "Now, let's examine the current state. The data clearly indicates several important trends.\n\n"
            "Looking at the numbers, we can see that... This represents a significant shift in how we approach the problem.\n\n"
            "Moving forward, the opportunities are substantial. Organizations that embrace {topic} stand to gain a real competitive advantage.\n\n"
            "In conclusion, {topic} is not just a trend, it's a fundamental shift. I recommend we start to proactively capitalize on it.\n\n"
            "Thank you for your attention. I'm happy to take any questions."
        ),
    },
    "ad": {
        "short": "Tired of the ordinary? Try {topic}. Transform your experience today.",
        "medium": (
            "Introducing {topic} - the game changer you've been waiting for. Whether you're a beginner or an expert, "
            "{topic} delivers results. Join thousands who've already made the switch. Don't miss out. Try {topic} today and see the difference."
        ),
        "long": (
            "Are you tired of settling for less? It's time to experience {topic}.\n\n"
            "Here's the thing - most people struggle with this exact problem. And that's exactly why {topic} was created.\n\n"
            "With {topic}, you get unmatched quality that speaks for itself, results you can measure, and support that actually shows up.\n\n"
            "Don't just take our word for it. Join the thousands of satisfied users who've already transformed their experience.\n\n"
            "{topic} - because you deserve better. Try it free today."
        ),
    },
    "explainer": {
        "short": "What is {topic}? Here's the one minute answer.",
        "medium": (
            "So what exactly is {topic}? In simple terms, it's a way of solving a specific problem. "
            "It works in three steps: first you set it up, then you let it run, and finally you review the results. "
            "That's {topic} in a nutshell."
        ),
        "long": (
            "Let's answer the question everyone asks: what is {topic}, really?\n\n"
            "At its core, {topic} is a system for turning a messy problem into a repeatable process. "
            "Instead of guessing, you measure. Instead of starting over, you improve what already works.\n\n"
            "Step one: define the outcome you actually want. Step two: put the simplest version in place. "
            "Step three: measure, adjust, and repeat.\n\n"
            "Most people overcomplicate {topic}. The ones who get results keep it simple and stay consistent. "
            "That's the whole secret."
        ),
    },
    "general": {
        "short": "Today: {topic}. Here's what you need to know.",
        "medium": (
            "Today we're exploring {topic}. Let's dive deeper into this fascinating subject. The fundamentals are clear. "
            "{topic} has evolved significantly. Here are the key points to understand. First, the basics. "
            "Then the advanced concepts. And finally, practical applications."
        ),
        "long": (
            "Today we're going to take an in-depth look at {topic}. This is a subject that many people are curious about, and for good reason.\n\n"
            "Let's start with the fundamentals. {topic} encompasses several key elements that work together.\n\n"
            "The first aspect to consider is context. This is foundational to understanding everything else.\n\n"
            "Next, let's explore execution... This is where things get particularly interesting.\n\n"
            "We should also discuss the trade-offs. Every approach adds another layer of complexity and nuance.\n\n"
            "Finally, the practical applications of {topic} are vast and growing. Understanding them can provide significant advantages.\n\n"
            "That concludes our comprehensive overview of {topic}. I hope this has been informative and valuable."
        ),
    },
}

GENRE_ALIASES = {
    # legacy / generic
    "video": "youtube",
    "youtube_short": "youtube",
    "youtube_video": "youtube",
    "shorts": "youtube",
    "short_form": "youtube",
    "reel": "youtube",
    "tiktok": "youtube",
    "entertainment": "youtube",
    "review": "youtube",
    "audio": "podcast",
    "radio": "podcast",
    "interview": "podcast",
    "pitch": "presentation",
    "lecture": "presentation",
    "class": "presentation",
    "webinar": "presentation",
    "conference": "presentation",
    "course": "explainer",
    "educational": "explainer",
    "education": "explainer",
    "tutorial": "explainer",
    "howto": "explainer",
    "how_to": "explainer",
    "commercial": "ad",
    "promo": "ad",
    "marketing": "ad",
    "sales": "ad",
    "article": "general",
    "blog": "general",
    "essay": "general",
    "story": "general",
    "storytelling": "general",
    "narrative": "general",
}

TONE_LINES = {
    "friendly": "Let's keep this conversational and easy to follow.",
    "professional": "The delivery should stay precise and professional throughout.",
    "energetic": "Keep the energy high and the pace brisk.",
    "calm": "Keep the tone calm, measured and reassuring.",
    "humorous": "Feel free to land a light joke or two along the way.",
    "serious": "The tone stays serious and factual from start to finish.",
    "inspiring": "Close on an uplifting, motivating note.",
    "neutral": "",
}

LENGTH_ALIASES = {
    "short": "short", "30s": "short", "60s": "short", "1min": "short", "small": "short", "brief": "short",
    "medium": "medium", "2min": "medium", "3min": "medium", "5min": "medium", "standard": "medium", "normal": "medium",
    "long": "long", "10min": "long", "15min": "long", "detailed": "long", "extended": "long", "deep": "long", "deep_dive": "long",
}


def resolve_genre(template: str) -> str:
    key = (template or "general").strip().lower().replace(" ", "_").replace("-", "_")
    key = GENRE_ALIASES.get(key, key)
    return key if key in TEMPLATES else "general"


def resolve_length(length: str) -> str:
    key = (length or "medium").strip().lower().replace(" ", "_").replace("-", "_")
    return LENGTH_ALIASES.get(key, key if key in ("short", "medium", "long") else "medium")


def build_script(topic: str, genre: str, length: str, tone: str = "neutral",
                 audience: str = "general", style: str = "") -> str:
    """Render a template into the final script text."""
    template = TEMPLATES[genre][length]
    if isinstance(template, dict):
        parts: List[str] = [
            template.get("intro", "").format(topic=topic),
            template.get("body", "").format(topic=topic),
            template.get("outro", "").format(topic=topic),
        ]
        script = "\n\n".join(p for p in parts if p)
    else:
        script = template.format(topic=topic)

    tone_line = TONE_LINES.get((tone or "neutral").lower(), "")
    if audience and audience.lower() not in ("general", "everyone", ""):
        tone_line = f"{tone_line} Written for {audience}.".strip()
    if style and style.lower() not in ("default", "standard", ""):
        tone_line = f"{tone_line} Style: {style}.".strip()
    if tone_line:
        script = f"{script}\n\n[Direction] {tone_line}"
    return script.strip()


def generate_script(topic: str, template: str = "general", style: str = "", tone: str = "neutral",
                    length: str = "medium", audience: str = "general", language: str = "english") -> Dict[str, Any]:
    """Full generation entrypoint used by the API routes."""
    topic = (topic or "").strip()
    genre = resolve_genre(template)
    resolved_length = resolve_length(length)
    if not topic:
        raise ValueError("Topic is required")

    script = build_script(topic, genre, resolved_length, tone=tone, audience=audience, style=style)
    words = len(script.split())
    return {
        "script": script,
        "content": script,
        "topic": topic,
        "genre": genre,
        "template": template or genre,
        "style": style or "default",
        "tone": tone or "neutral",
        "length": resolved_length,
        "target_audience": audience or "general",
        "language": language or "english",
        "word_count": words,
        "char_count": len(script),
        "estimated_seconds": max(15, int(words / 2.6)),
        "sections": [s.strip() for s in script.split("\n\n") if s.strip()],
    }


__all__ = ["TEMPLATES", "generate_script", "build_script", "resolve_genre", "resolve_length"]
