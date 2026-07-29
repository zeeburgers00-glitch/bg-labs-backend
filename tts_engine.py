"""
BG LABS - Combined TTS Engine
cvoice.ai (20,000+ character voices) + Edge TTS (322+ voices) + F5-TTS (Ultra)
100% FREE - No API keys needed for Edge/F5, cvoice.ai free with API key
"""
import os
import json
import io
import uuid
import time
import asyncio
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, List

import httpx
import edge_tts

logger = logging.getLogger("bglabs.tts")

# ============================================================
# cvoice.ai CONFIG
# ============================================================
CVOICE_API_KEY = os.getenv("CVOICE_API_KEY", "cvai_a5a646efb9409a58296e3c9b960a2b928c30585155cf347a")
CVOICE_API_BASE = "https://cvoice.ai/api"
CVOICE_SEARCH_URL = "https://cvoice.ai/dataset_search.json"
CVOICE_VOICES_URL = "https://cvoice.ai/dataset_voices.json"
CVOICE_TIMEOUT = 30.0

# Cache for cvoice.ai datasets
_cvoice_characters_cache: Optional[List[Dict]] = None
_cvoice_voices_cache: Optional[Dict] = None
_cvoice_cache_time: float = 0
CVOICE_CACHE_TTL = 3600  # 1 hour

# ============================================================
# EDGE TTS CONFIG
# ============================================================
EDGE_VOICES = {
    "en-US-AriaNeural": {"name": "Aria", "voice": "en-US-AriaNeural", "gender": "Female", "lang": "en", "accent": "American", "color": "#a855f7"},
    "en-US-JennyNeural": {"name": "Jenny", "voice": "en-US-JennyNeural", "gender": "Female", "lang": "en", "accent": "American", "color": "#ec4899"},
    "en-US-GuyNeural": {"name": "Guy", "voice": "en-US-GuyNeural", "gender": "Male", "lang": "en", "accent": "American", "color": "#84cc16"},
    "en-US-BrianNeural": {"name": "Brian", "voice": "en-US-BrianNeural", "gender": "Male", "lang": "en", "accent": "American", "color": "#3b82f6"},
    "en-US-AndrewNeural": {"name": "Andrew", "voice": "en-US-AndrewNeural", "gender": "Male", "lang": "en", "accent": "American", "color": "#06b6d4"},
    "en-US-EmmaNeural": {"name": "Emma", "voice": "en-US-EmmaNeural", "gender": "Female", "lang": "en", "accent": "American", "color": "#f472b6"},
    "en-US-MichelleNeural": {"name": "Michelle", "voice": "en-US-MichelleNeural", "gender": "Female", "lang": "en", "accent": "American", "color": "#f59e0b"},
    "en-US-RogerNeural": {"name": "Roger", "voice": "en-US-RogerNeural", "gender": "Male", "lang": "en", "accent": "American", "color": "#10b981"},
    "en-GB-SoniaNeural": {"name": "Sonia", "voice": "en-GB-SoniaNeural", "gender": "Female", "lang": "en", "accent": "British", "color": "#0ea5e9"},
    "en-GB-RyanNeural": {"name": "Ryan", "voice": "en-GB-RyanNeural", "gender": "Male", "lang": "en", "accent": "British", "color": "#64748b"},
    "ur-PK-UzmaNeural": {"name": "Uzma", "voice": "ur-PK-UzmaNeural", "gender": "Female", "lang": "ur", "accent": "Pakistani", "color": "#ef4444"},
    "ur-PK-SalmanNeural": {"name": "Salman", "voice": "ur-PK-SalmanNeural", "gender": "Male", "lang": "ur", "accent": "Pakistani", "color": "#8b5cf6"},
    "hi-IN-SwaraNeural": {"name": "Swara", "voice": "hi-IN-SwaraNeural", "gender": "Female", "lang": "hi", "accent": "Indian", "color": "#f59e0b"},
    "ar-SA-ZariyahNeural": {"name": "Zariyah", "voice": "ar-SA-ZariyahNeural", "gender": "Female", "lang": "ar", "accent": "Arabic", "color": "#14b8a6"},
    "ar-SA-HamedNeural": {"name": "Hamed", "voice": "ar-SA-HamedNeural", "gender": "Male", "lang": "ar", "accent": "Arabic", "color": "#6366f1"},
    "zh-CN-XiaoxiaoNeural": {"name": "Xiaoxiao", "voice": "zh-CN-XiaoxiaoNeural", "gender": "Female", "lang": "zh", "accent": "Chinese", "color": "#f43f5e"},
    "ja-JP-NanamiNeural": {"name": "Nanami", "voice": "ja-JP-NanamiNeural", "gender": "Female", "lang": "ja", "accent": "Japanese", "color": "#c084fc"},
    "ko-KR-SunHiNeural": {"name": "SunHi", "voice": "ko-KR-SunHiNeural", "gender": "Female", "lang": "ko", "accent": "Korean", "color": "#22d3ee"},
    "es-ES-ElviraNeural": {"name": "Elvira", "voice": "es-ES-ElviraNeural", "gender": "Female", "lang": "es", "accent": "Spanish", "color": "#e879f9"},
    "fr-FR-DeniseNeural": {"name": "Denise", "voice": "fr-FR-DeniseNeural", "gender": "Female", "lang": "fr", "accent": "French", "color": "#fb923c"},
    "de-DE-KatjaNeural": {"name": "Katja", "voice": "de-DE-KatjaNeural", "gender": "Female", "lang": "de", "accent": "German", "color": "#22c55e"},
    "it-IT-ElsaNeural": {"name": "Elsa", "voice": "it-IT-ElsaNeural", "gender": "Female", "lang": "it", "accent": "Italian", "color": "#f472b6"},
    "pt-BR-FranciscaNeural": {"name": "Francisca", "voice": "pt-BR-FranciscaNeural", "gender": "Female", "lang": "pt", "accent": "Brazilian", "color": "#818cf8"},
    "tr-TR-EmelNeural": {"name": "Emel", "voice": "tr-TR-EmelNeural", "gender": "Female", "lang": "tr", "accent": "Turkish", "color": "#a3e635"},
    "ru-RU-SvetlanaNeural": {"name": "Svetlana", "voice": "ru-RU-SvetlanaNeural", "gender": "Female", "lang": "ru", "accent": "Russian", "color": "#38bdf8"},
    "pl-PL-AgnieszkaNeural": {"name": "Agnieszka", "voice": "pl-PL-AgnieszkaNeural", "gender": "Female", "lang": "pl", "accent": "Polish", "color": "#d946ef"},
    "nl-NL-ColetteNeural": {"name": "Colette", "voice": "nl-NL-ColetteNeural", "gender": "Female", "lang": "nl", "accent": "Dutch", "color": "#0891b2"},
    "sv-SE-SofieNeural": {"name": "Sofie", "voice": "sv-SE-SofieNeural", "gender": "Female", "lang": "sv", "accent": "Swedish", "color": "#f43f5e"},
    "da-DK-ChristelNeural": {"name": "Christel", "voice": "da-DK-ChristelNeural", "gender": "Female", "lang": "da", "accent": "Danish", "color": "#c084fc"},
    "id-ID-GadisNeural": {"name": "Gadis", "voice": "id-ID-GadisNeural", "gender": "Female", "lang": "id", "accent": "Indonesian", "color": "#22d3ee"},
}


# ============================================================
# cvoice.ai ENGINE
# ============================================================
async def _fetch_cvoice_datasets() -> Tuple[List[Dict], Dict]:
    """Fetch and cache cvoice.ai character + voice datasets."""
    global _cvoice_characters_cache, _cvoice_voices_cache, _cvoice_cache_time

    now = time.time()
    if _cvoice_characters_cache and _cvoice_voices_cache and (now - _cvoice_cache_time) < CVOICE_CACHE_TTL:
        return _cvoice_characters_cache, _cvoice_voices_cache

    async with httpx.AsyncClient(timeout=CVOICE_TIMEOUT) as client:
        try:
            chars_resp = await client.get(CVOICE_SEARCH_URL)
            voices_resp = await client.get(CVOICE_VOICES_URL)
            if chars_resp.status_code == 200 and voices_resp.status_code == 200:
                _cvoice_characters_cache = chars_resp.json()
                _cvoice_voices_cache = voices_resp.json()
                _cvoice_cache_time = now
                logger.info(f"cvoice.ai datasets loaded: {len(_cvoice_characters_cache)} characters")
        except Exception as e:
            logger.error(f"Failed to fetch cvoice.ai datasets: {e}")

    return _cvoice_characters_cache or [], _cvoice_voices_cache or {}


async def cvoice_search_characters(query: str = "", limit: int = 50) -> List[Dict]:
    """Search cvoice.ai characters by name/occupation."""
    chars, _ = await _fetch_cvoice_datasets()
    if not chars:
        return []

    if query:
        q = query.lower()
        chars = [c for c in chars if q in c.get("name", "").lower() or any(q in o.lower() for o in c.get("occupations", []))]

    return chars[:limit]


async def cvoice_get_voices(username: str) -> List[Dict]:
    """Get voice IDs for a specific character."""
    _, voices_map = await _fetch_cvoice_datasets()
    return voices_map.get(username, [])


async def cvoice_tts_generate(text: str, voice_id: Optional[str] = None, person_slug: str = "", person_name: str = "") -> Tuple[bytes, str]:
    """
    Generate speech using cvoice.ai API.
    Returns (audio_bytes, "cvoice.ai").
    """
    if not CVOICE_API_KEY:
        raise Exception("CVOICE_API_KEY not configured")

    payload = {"text": text}
    if voice_id:
        payload["voice_id"] = voice_id
    if person_slug:
        payload["person_slug"] = person_slug
    if person_name:
        payload["person_name"] = person_name

    async with httpx.AsyncClient(timeout=CVOICE_TIMEOUT) as client:
        resp = await client.post(
            f"{CVOICE_API_BASE}/tts",
            headers={"Content-Type": "application/json", "X-API-Key": CVOICE_API_KEY},
            json=payload,
        )
        if resp.status_code != 200:
            raise Exception(f"cvoice.ai API error: {resp.status_code} - {resp.text}")

        data = resp.json()
        audio_url = data.get("url", "")
        if not audio_url:
            raise Exception("cvoice.ai returned no audio URL")

        audio_resp = await client.get(audio_url, follow_redirects=True)
        if audio_resp.status_code != 200:
            raise Exception(f"Failed to download audio from cvoice.ai: {audio_resp.status_code}")

        return audio_resp.content, "cvoice.ai"


# ============================================================
# EDGE TTS ENGINE
# ============================================================
async def edge_tts_generate(text: str, voice_key: str = "en-US-AriaNeural") -> Tuple[bytes, str]:
    """Generate speech using Edge TTS."""
    voice_info = EDGE_VOICES.get(voice_key, EDGE_VOICES["en-US-AriaNeural"])
    communicate = edge_tts.Communicate(text, voice_info["voice"])
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    if not audio_data:
        raise Exception("Edge TTS returned empty audio")
    return audio_data, "Edge-TTS"


# ============================================================
# SMART TTS ROUTER
# ============================================================
async def smart_tts_generate(
    text: str,
    engine: str = "cvoice",
    voice_key: str = "en-US-AriaNeural",
    voice_id: Optional[str] = None,
    person_slug: str = "",
    person_name: str = "",
) -> Tuple[bytes, str, str]:
    """
    Smart TTS router.
    Returns (audio_bytes, engine_used, voice_name).

    Engines:
    - "cvoice": cvoice.ai character voices (20,000+)
    - "edge": Edge TTS (322+ voices)
    - "auto": Try cvoice first, then Edge TTS fallback
    """
    if not text or not text.strip():
        raise Exception("Text is required")
    text = text.strip()

    if engine == "auto":
        engine = "cvoice" if voice_id else "edge"

    if engine == "cvoice":
        try:
            audio_bytes, eng = await cvoice_tts_generate(text, voice_id, person_slug, person_name)
            return audio_bytes, eng, person_name or "cvoice Character"
        except Exception as e:
            logger.warning(f"cvoice.ai failed: {e}, falling back to Edge TTS")
            audio_bytes, eng = await edge_tts_generate(text, voice_key)
            voice_name = EDGE_VOICES.get(voice_key, {}).get("name", "Edge Voice")
            return audio_bytes, eng, voice_name

    audio_bytes, eng = await edge_tts_generate(text, voice_key)
    voice_name = EDGE_VOICES.get(voice_key, {}).get("name", "Edge Voice")
    return audio_bytes, eng, voice_name


# ============================================================
# VOICE LISTING
# ============================================================
def get_edge_voices() -> List[Dict]:
    """Return Edge TTS voices."""
    voices = []
    for key, info in EDGE_VOICES.items():
        voices.append({
            "key": f"edge:{key}",
            "name": info["name"],
            "engine": "Edge-TTS",
            "quality": "High",
            "gender": info["gender"],
            "lang": info["lang"],
            "accent": info["accent"],
            "color": info["color"],
        })
    return voices
