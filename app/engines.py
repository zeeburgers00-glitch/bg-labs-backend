"""
BG LABS - creative engines
==========================

Free, key-less generation helpers shared by every route:

* images  -> Pollinations.ai (no API key, unlimited)
* avatars -> generated SVG (no external service at all)

Both were previously inlined in ``main.py``; they live here so the API routes and
the automation pipelines (YouTube full-automation) can reuse them.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

import httpx

logger = logging.getLogger("bglabs.engines")

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"
IMAGE_TIMEOUT = float(os.getenv("IMAGE_TIMEOUT", "60"))

# ---------------------------------------------------------------- image styles
# Keys cover both the legacy snake_case ids and the hyphenated ids used by the
# web UI dropdown, so either spelling resolves to the same prompt suffix.
IMAGE_STYLES: Dict[str, str] = {
    "realistic": "photorealistic, high quality, detailed",
    "vivid": "vivid colors, ultra detailed, sharp focus",
    "anime": "anime style, manga, vibrant colors",
    "oil_painting": "oil painting, classical art, textured brush strokes",
    "oil-painting": "oil painting, classical art, textured brush strokes",
    "digital_art": "digital art, concept art, vibrant",
    "digital-art": "digital art, concept art, vibrant",
    "watercolor": "watercolor painting, soft colors, artistic",
    "3d_render": "3D render, octane render, cinematic",
    "3d-render": "3D render, octane render, cinematic",
    "pixel_art": "pixel art, retro, 16-bit style",
    "pixel-art": "pixel art, retro, 16-bit style",
    "cyberpunk": "cyberpunk style, neon lights, futuristic",
    "cinematic": "cinematic lighting, dramatic, movie quality",
    "portrait": "portrait photography, studio lighting, detailed face",
    "landscape": "landscape photography, golden hour, scenic",
    "fantasy": "fantasy art, magical, ethereal",
    "minimalist": "minimalist design, clean, simple",
    "comic": "comic book style, bold lines, vibrant",
    "photorealistic": "photorealistic, 8k, highly detailed",
    "sketch": "pencil sketch, hand drawn, monochrome",
}

# The UI advertises model names; Pollinations has a single flux model, so the
# chosen "model" only nudges the prompt.
MODEL_HINTS: Dict[str, str] = {
    "dall-e-3": "highly detailed, professional composition",
    "stable-diffusion-xl": "sharp details, trending on artstation",
    "midjourney-v6": "artistic, dramatic composition, award winning",
    "flux": "photorealistic, natural lighting",
}

SIZE_PRESETS: Dict[str, Tuple[int, int]] = {
    "square": (1024, 1024),
    "landscape": (1792, 1024),
    "portrait": (1024, 1792),
    "wide": (1792, 1024),
    "tall": (1024, 1792),
    "hd": (1280, 720),
    "fullhd": (1920, 1080),
    "1024x1024": (1024, 1024),
    "1792x1024": (1792, 1024),
    "1024x1792": (1024, 1792),
    "512x512": (512, 512),
    "768x768": (768, 768),
    "1280x720": (1280, 720),
    "1920x1080": (1920, 1080),
}


def parse_size(size: Any = None, width: Optional[int] = None, height: Optional[int] = None) -> Tuple[int, int]:
    """Accept ``1024x1024`` / ``landscape`` / explicit width+height."""
    if width and height:
        return int(width), int(height)
    key = str(size or "").strip().lower().replace(" ", "")
    if key in SIZE_PRESETS:
        return SIZE_PRESETS[key]
    for sep in ("x", "*", ","):
        if sep in key:
            parts = key.split(sep)
            try:
                return max(256, min(2048, int(parts[0]))), max(256, min(2048, int(parts[1])))
            except (ValueError, IndexError):
                break
    return 1024, 1024


def build_image_prompt(prompt: str, style: str = "", model: str = "") -> str:
    parts = [(prompt or "").strip()]
    style_suffix = IMAGE_STYLES.get(str(style or "").strip().lower(), "")
    if style_suffix:
        parts.append(style_suffix)
    model_hint = MODEL_HINTS.get(str(model or "").strip().lower(), "")
    if model_hint:
        parts.append(model_hint)
    return ", ".join(p for p in parts if p)


async def generate_image(prompt: str, style: str = "realistic", width: int = 1024, height: int = 1024,
                         model: str = "", seed: Optional[int] = None) -> bytes:
    """Generate a PNG/JPEG image with Pollinations.ai and return the raw bytes."""
    full_prompt = build_image_prompt(prompt, style, model)
    url = POLLINATIONS_URL.format(prompt=quote(full_prompt))
    params = {
        "width": int(width),
        "height": int(height),
        "seed": int(seed if seed is not None else time.time()),
        "nologo": "true",
        "model": "flux",
    }
    async with httpx.AsyncClient(timeout=IMAGE_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"image generation failed ({resp.status_code})")
        data = resp.content
        if not data or len(data) < 512:
            raise RuntimeError("image generation returned an empty response")
        return data


def guess_content_type(data: bytes, default: str = "image/png") -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return default


def image_extension(content_type: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }.get(content_type, ".png")


# ------------------------------------------------------------------- avatars
# Palette per avatar template from the UI dropdown.
AVATAR_PRESETS: Dict[str, Dict[str, str]] = {
    "news_anchor": {"hair_color": "#1f2937", "eye_color": "#0f172a", "skin_tone": "#f1c9a5", "clothing_color": "#1d4ed8", "background": "news_studio"},
    "youtube_host": {"hair_color": "#3f2a1d", "eye_color": "#22c55e", "skin_tone": "#fdbcb4", "clothing_color": "#ef4444", "background": "home_office"},
    "corporate_presenter": {"hair_color": "#111827", "eye_color": "#334155", "skin_tone": "#e8b894", "clothing_color": "#0f172a", "background": "boardroom"},
    "course_instructor": {"hair_color": "#4b5563", "eye_color": "#0ea5e9", "skin_tone": "#f5d0b0", "clothing_color": "#0d9488", "background": "classroom"},
    "social_media": {"hair_color": "#7c3aed", "eye_color": "#f472b6", "skin_tone": "#fdbcb4", "clothing_color": "#a855f7", "background": "gradient"},
    "default": {"hair_color": "#333333", "eye_color": "#333333", "skin_tone": "#fdbcb4", "clothing_color": "#3b82f6", "background": "studio"},
}

BACKGROUNDS = {
    "news_studio": ("#1e3a8a", "#0f172a"),
    "home_office": ("#3f3f46", "#18181b"),
    "boardroom": ("#334155", "#0f172a"),
    "classroom": ("#065f46", "#022c22"),
    "gradient": ("#6366f1", "#a855f7"),
    "studio": ("#1f2937", "#111827"),
}


def avatar_preset(avatar_type: str = "default", background: Optional[str] = None) -> Dict[str, str]:
    preset = dict(AVATAR_PRESETS.get(avatar_type, AVATAR_PRESETS["default"]))
    if background:
        preset["background"] = background
    return preset


def generate_avatar_svg(hair_color: str = "#333", eye_color: str = "#333", skin_tone: str = "#fdbcb4",
                        clothing_color: str = "#3b82f6", background: str = "studio") -> str:
    """Render a self-contained SVG talking-head avatar."""
    bg_top, bg_bottom = BACKGROUNDS.get(background, BACKGROUNDS["studio"])
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">
    <defs>
        <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" style="stop-color:{bg_top};stop-opacity:0.55"/>
            <stop offset="100%" style="stop-color:{bg_bottom};stop-opacity:0.9"/>
        </linearGradient>
        <radialGradient id="glow">
            <stop offset="0%" style="stop-color:{clothing_color};stop-opacity:0.2"/>
            <stop offset="100%" style="stop-color:{clothing_color};stop-opacity:0"/>
        </radialGradient>
    </defs>
    <rect width="200" height="200" fill="url(#bg)"/>
    <circle cx="100" cy="100" r="80" fill="url(#glow)"/>
    <circle cx="100" cy="85" r="55" fill="{hair_color}"/>
    <circle cx="100" cy="100" r="45" fill="{skin_tone}"/>
    <circle cx="80" cy="92" r="8" fill="white"/>
    <circle cx="120" cy="92" r="8" fill="white"/>
    <circle cx="80" cy="92" r="5" fill="{eye_color}"/>
    <circle cx="120" cy="92" r="5" fill="{eye_color}"/>
    <circle cx="80" cy="90" r="1.5" fill="white"/>
    <circle cx="120" cy="90" r="1.5" fill="white"/>
    <path d="M 85 105 Q 100 115 115 105" stroke="{clothing_color}" fill="none" stroke-width="2.5" stroke-linecap="round"/>
    <ellipse cx="100" cy="145" rx="40" ry="25" fill="{clothing_color}"/>
</svg>'''


__all__ = [
    "IMAGE_STYLES",
    "MODEL_HINTS",
    "SIZE_PRESETS",
    "AVATAR_PRESETS",
    "parse_size",
    "build_image_prompt",
    "generate_image",
    "guess_content_type",
    "image_extension",
    "avatar_preset",
    "generate_avatar_svg",
]
