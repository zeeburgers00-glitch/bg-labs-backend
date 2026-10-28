"""
BG LABS - TTS Engine
Edge TTS (Primary) + cvoice.ai (Character Browsing Only)
100% FREE, unlimited, no errors
"""
import os
import json
import time
import asyncio
import logging
from typing import Any, Optional, Tuple, List, Dict

import httpx
import edge_tts

logger = logging.getLogger("bglabs.tts")

# ============================================================
# EDGE TTS VOICES
# ============================================================
EDGE_VOICES = {
    "en-US-AriaNeural": {"name": "Aria", "gender": "Female", "lang": "en", "accent": "American", "color": "#f472b6"},
    "en-US-JennyNeural": {"name": "Jenny", "gender": "Female", "lang": "en", "accent": "American", "color": "#e879f9"},
    "en-US-GuyNeural": {"name": "Guy", "gender": "Male", "lang": "en", "accent": "American", "color": "#84cc16"},
    "en-US-BrianNeural": {"name": "Brian", "gender": "Male", "lang": "en", "accent": "American", "color": "#3b82f6"},
    "en-US-AndrewNeural": {"name": "Andrew", "gender": "Male", "lang": "en", "accent": "American", "color": "#06b6d4"},
    "en-US-EmmaNeural": {"name": "Emma", "gender": "Female", "lang": "en", "accent": "American", "color": "#f472b6"},
    "en-US-MichelleNeural": {"name": "Michelle", "gender": "Female", "lang": "en", "accent": "American", "color": "#f59e0b"},
    "en-US-RogerNeural": {"name": "Roger", "gender": "Male", "lang": "en", "accent": "American", "color": "#10b981"},
    "en-US-AvaNeural": {"name": "Ava", "gender": "Female", "lang": "en", "accent": "American", "color": "#c084fc"},
    "en-US-AnaNeural": {"name": "Ana", "gender": "Female", "lang": "en", "accent": "American", "color": "#e879f9"},
    "en-GB-SoniaNeural": {"name": "Sonia", "gender": "Female", "lang": "en", "accent": "British", "color": "#0ea5e9"},
    "en-GB-RyanNeural": {"name": "Ryan", "gender": "Male", "lang": "en", "accent": "British", "color": "#64748b"},
    "en-GB-LibbyNeural": {"name": "Libby", "gender": "Female", "lang": "en", "accent": "British", "color": "#22d3ee"},
    "en-GB-ThomasNeural": {"name": "Thomas", "gender": "Male", "lang": "en", "accent": "British", "color": "#38bdf8"},
    "en-IN-NeerjaNeural": {"name": "Neerja", "gender": "Female", "lang": "en", "accent": "Indian", "color": "#d946ef"},
    "en-IN-PrabhatNeural": {"name": "Prabhat", "gender": "Male", "lang": "en", "accent": "Indian", "color": "#22c55e"},
    "ur-PK-UzmaNeural": {"name": "Uzma", "gender": "Female", "lang": "ur", "accent": "Pakistani", "color": "#ef4444"},
    "ur-PK-SalmanNeural": {"name": "Salman", "gender": "Male", "lang": "ur", "accent": "Pakistani", "color": "#8b5cf6"},
    "hi-IN-SwaraNeural": {"name": "Swara", "gender": "Female", "lang": "hi", "accent": "Indian", "color": "#f59e0b"},
    "hi-IN-MadhurNeural": {"name": "Madhur", "gender": "Male", "lang": "hi", "accent": "Indian", "color": "#10b981"},
    "ar-SA-ZariyahNeural": {"name": "Zariyah", "gender": "Female", "lang": "ar", "accent": "Arabic", "color": "#14b8a6"},
    "ar-SA-HamedNeural": {"name": "Hamed", "gender": "Male", "lang": "ar", "accent": "Arabic", "color": "#6366f1"},
    "zh-CN-XiaoxiaoNeural": {"name": "Xiaoxiao", "gender": "Female", "lang": "zh", "accent": "Chinese", "color": "#f43f5e"},
    "zh-CN-YunxiNeural": {"name": "Yunxi", "gender": "Male", "lang": "zh", "accent": "Chinese", "color": "#22c55e"},
    "ja-JP-NanamiNeural": {"name": "Nanami", "gender": "Female", "lang": "ja", "accent": "Japanese", "color": "#c084fc"},
    "ja-JP-KeitaNeural": {"name": "Keita", "gender": "Male", "lang": "ja", "accent": "Japanese", "color": "#818cf8"},
    "ko-KR-SunHiNeural": {"name": "SunHi", "gender": "Female", "lang": "ko", "accent": "Korean", "color": "#22d3ee"},
    "ko-KR-InJoonNeural": {"name": "InJoon", "gender": "Male", "lang": "ko", "accent": "Korean", "color": "#f97316"},
    "es-ES-ElviraNeural": {"name": "Elvira", "gender": "Female", "lang": "es", "accent": "Spanish", "color": "#e879f9"},
    "es-ES-AlvaroNeural": {"name": "Alvaro", "gender": "Male", "lang": "es", "accent": "Spanish", "color": "#d946ef"},
    "fr-FR-DeniseNeural": {"name": "Denise", "gender": "Female", "lang": "fr", "accent": "French", "color": "#fb923c"},
    "fr-FR-HenriNeural": {"name": "Henri", "gender": "Male", "lang": "fr", "accent": "French", "color": "#0ea5e9"},
    "de-DE-KatjaNeural": {"name": "Katja", "gender": "Female", "lang": "de", "accent": "German", "color": "#22c55e"},
    "de-DE-ConradNeural": {"name": "Conrad", "gender": "Male", "lang": "de", "accent": "German", "color": "#06b6d4"},
    "it-IT-ElsaNeural": {"name": "Elsa", "gender": "Female", "lang": "it", "accent": "Italian", "color": "#f472b6"},
    "it-IT-DiegoNeural": {"name": "Diego", "gender": "Male", "lang": "it", "accent": "Italian", "color": "#10b981"},
    "pt-BR-FranciscaNeural": {"name": "Francisca", "gender": "Female", "lang": "pt", "accent": "Brazilian", "color": "#818cf8"},
    "pt-BR-AntonioNeural": {"name": "Antonio", "gender": "Male", "lang": "pt", "accent": "Brazilian", "color": "#84cc16"},
    "ru-RU-SvetlanaNeural": {"name": "Svetlana", "gender": "Female", "lang": "ru", "accent": "Russian", "color": "#38bdf8"},
    "ru-RU-DmitryNeural": {"name": "Dmitry", "gender": "Male", "lang": "ru", "accent": "Russian", "color": "#a855f7"},
    "tr-TR-EmelNeural": {"name": "Emel", "gender": "Female", "lang": "tr", "accent": "Turkish", "color": "#a3e635"},
    "tr-TR-AhmetNeural": {"name": "Ahmet", "gender": "Male", "lang": "tr", "accent": "Turkish", "color": "#ec4899"},
    "pl-PL-AgnieszkaNeural": {"name": "Agnieszka", "gender": "Female", "lang": "pl", "accent": "Polish", "color": "#d946ef"},
    "pl-PL-MarekNeural": {"name": "Marek", "gender": "Male", "lang": "pl", "accent": "Polish", "color": "#14b8a6"},
    "nl-NL-ColetteNeural": {"name": "Colette", "gender": "Female", "lang": "nl", "accent": "Dutch", "color": "#0891b2"},
    "nl-NL-MaartenNeural": {"name": "Maarten", "gender": "Male", "lang": "nl", "accent": "Dutch", "color": "#6366f1"},
    "sv-SE-SofieNeural": {"name": "Sofie", "gender": "Female", "lang": "sv", "accent": "Swedish", "color": "#f43f5e"},
    "sv-SE-SvanteNeural": {"name": "Svante", "gender": "Male", "lang": "sv", "accent": "Swedish", "color": "#22d3ee"},
    "da-DK-ChristelNeural": {"name": "Christel", "gender": "Female", "lang": "da", "accent": "Danish", "color": "#c084fc"},
    "da-DK-JeppeNeural": {"name": "Jeppe", "gender": "Male", "lang": "da", "accent": "Danish", "color": "#fb923c"},
    "fi-FI-SelmaNeural": {"name": "Selma", "gender": "Female", "lang": "fi", "accent": "Finnish", "color": "#e879f9"},
    "fi-FI-HarriNeural": {"name": "Harri", "gender": "Male", "lang": "fi", "accent": "Finnish", "color": "#a3e635"},
    "id-ID-GadisNeural": {"name": "Gadis", "gender": "Female", "lang": "id", "accent": "Indonesian", "color": "#22d3ee"},
    "id-ID-ArdiNeural": {"name": "Ardi", "gender": "Male", "lang": "id", "accent": "Indonesian", "color": "#a3e635"},
    "th-TH-PremwadeeNeural": {"name": "Premwadee", "gender": "Female", "lang": "th", "accent": "Thai", "color": "#a51931"},
    "th-TH-NiwatNeural": {"name": "Niwat", "gender": "Male", "lang": "th", "accent": "Thai", "color": "#2d2a4a"},
    "vi-VN-HoaiMyNeural": {"name": "Hoai My", "gender": "Female", "lang": "vi", "accent": "Vietnamese", "color": "#da251d"},
    "vi-VN-NamMinhNeural": {"name": "Nam Minh", "gender": "Male", "lang": "vi", "accent": "Vietnamese", "color": "#cd2d37"},
    "ms-MY-YasminNeural": {"name": "Yasmin", "gender": "Female", "lang": "ms", "accent": "Malay", "color": "#010066"},
    "ms-MY-OsmanNeural": {"name": "Osman", "gender": "Male", "lang": "ms", "accent": "Malay", "color": "#cc0001"},
    "fil-PH-RoseNeural": {"name": "Rose", "gender": "Female", "lang": "fil", "accent": "Filipino", "color": "#0038a8"},
    "fil-PH-AngelosNeural": {"name": "Angelos", "gender": "Male", "lang": "fil", "accent": "Filipino", "color": "#ce1126"},
    "bn-BD-TanishaaNeural": {"name": "Tanishaa", "gender": "Female", "lang": "bn", "accent": "Bengali", "color": "#006a4e"},
    "bn-BD-BashirNeural": {"name": "Bashir", "gender": "Male", "lang": "bn", "accent": "Bengali", "color": "#f42a41"},
}


# ============================================================
# EDGE TTS GENERATION (PRIMARY - FREE, UNLIMITED)
# ============================================================
async def edge_tts_generate(text: str, voice_key: str = "en-US-AriaNeural", rate: str = "+0%", pitch: str = "+0Hz") -> bytes:
    """Generate speech using Edge TTS. Returns audio bytes."""
    voice_info = EDGE_VOICES.get(voice_key)
    if not voice_info:
        voice_key = "en-US-AriaNeural"
    communicate = edge_tts.Communicate(text, voice_key, rate=rate, pitch=pitch)
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    if not audio_data:
        raise Exception("Edge TTS returned empty audio")
    return audio_data


# ============================================================
# cvoice.ai CHARACTER BROWSING (VOICES ONLY, NOT GENERATION)
# ============================================================
CVOICE_SEARCH_URL = "https://cvoice.ai/dataset_search.json"
CVOICE_VOICES_URL = "https://cvoice.ai/dataset_voices.json"

_cvoice_characters_cache: Optional[List[Dict]] = None
_cvoice_voices_cache: Optional[Dict] = None
_cvoice_cache_time: float = 0
CVOICE_CACHE_TTL = 3600


async def cvoice_search_characters(query: str = "", limit: int = 50) -> List[Dict]:
    """Search cvoice.ai characters (for browsing only)."""
    global _cvoice_characters_cache, _cvoice_voices_cache, _cvoice_cache_time

    now = time.time()
    if not _cvoice_characters_cache or (now - _cvoice_cache_time) > CVOICE_CACHE_TTL:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                chars_resp = await client.get(CVOICE_SEARCH_URL)
                if chars_resp.status_code == 200:
                    _cvoice_characters_cache = chars_resp.json()
                    _cvoice_cache_time = now
                    logger.info(f"cvoice.ai loaded: {len(_cvoice_characters_cache)} characters")
        except Exception as e:
            logger.error(f"cvoice.ai fetch failed: {e}")
            _cvoice_characters_cache = []

    chars = _cvoice_characters_cache or []
    if query:
        q = query.lower()
        chars = [c for c in chars if q in c.get("name", "").lower() or any(q in o.lower() for o in c.get("occupations", []))]

    return chars[:limit]


async def cvoice_get_voices(username: str) -> List[Dict]:
    """Get voice IDs for a character (for browsing only)."""
    global _cvoice_voices_cache

    if not _cvoice_voices_cache:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                voices_resp = await client.get(CVOICE_VOICES_URL)
                if voices_resp.status_code == 200:
                    _cvoice_voices_cache = voices_resp.json()
        except Exception as e:
            logger.error(f"cvoice.ai voices fetch failed: {e}")
            _cvoice_voices_cache = {}

    return (_cvoice_voices_cache or {}).get(username, [])


# ============================================================
# VOICE LISTING
# ============================================================
def get_edge_voices() -> List[Dict]:
    """Return all Edge TTS voices."""
    voices = []
    for key, info in EDGE_VOICES.items():
        voices.append({
            "key": key,
            "name": info["name"],
            "engine": "Edge-TTS",
            "gender": info["gender"],
            "lang": info["lang"],
            "accent": info["accent"],
            "color": info["color"],
        })
    return voices


# ============================================================
# VOICE RESOLUTION HELPERS
# ============================================================
DEFAULT_VOICE = "en-US-AriaNeural"

# "aria" -> "en-US-AriaNeural"
VOICE_BY_NAME: Dict[str, str] = {info["name"].lower(): key for key, info in EDGE_VOICES.items()}
VOICE_BY_KEY: Dict[str, str] = {key.lower(): key for key in EDGE_VOICES}
VOICE_BY_SHORT_KEY: Dict[str, str] = {key.lower().replace("neural", ""): key for key in EDGE_VOICES}


def voices_for_language(language: str) -> List[str]:
    """Voice keys whose language code starts with ``language`` (``en`` -> en-US/en-GB/...)."""
    lang = (language or "").strip().lower()
    if not lang:
        return []
    return [key for key, info in EDGE_VOICES.items() if str(info.get("lang", "")).lower() == lang]


def resolve_voice_key(value: Optional[str] = None, language: Optional[str] = None) -> str:
    """Best-effort mapping of whatever the client sent onto a real Edge-TTS voice.

    Accepts a full key (``en-US-AriaNeural``), a friendly name (``Aria``), a
    short form (``en-US-Aria``, ``aria``) or nothing at all - in which case the
    first voice for ``language`` (or the default voice) is used.
    """
    candidate = (value or "").strip()
    if candidate:
        if candidate in EDGE_VOICES:
            return candidate
        lowered = candidate.lower()
        for table in (VOICE_BY_KEY, VOICE_BY_NAME, VOICE_BY_SHORT_KEY):
            if lowered in table:
                return table[lowered]
        matches = [key for key in EDGE_VOICES if key.lower().startswith(lowered)]
        if matches:
            return matches[0]
        matches = [key for key in EDGE_VOICES if lowered in key.lower()]
        if matches:
            return matches[0]

    for key in voices_for_language(language or ""):
        return key
    return DEFAULT_VOICE


def speed_to_rate(speed: Any = None, rate: Optional[str] = None) -> str:
    """Convert a UI speed multiplier (0.5-2.0) into an Edge-TTS rate string."""
    if rate:
        return str(rate)
    try:
        value = float(speed)
    except (TypeError, ValueError):
        return "+0%"
    value = max(0.5, min(2.0, value))
    percent = int(round((value - 1.0) * 100))
    return f"{percent:+d}%"


def pitch_to_offset(pitch: Any = None) -> str:
    """Normalise pitch into Edge-TTS' ``+0Hz`` form."""
    if isinstance(pitch, str) and pitch.strip().lower().endswith("hz"):
        return pitch.strip()
    try:
        value = int(round(float(pitch)))
    except (TypeError, ValueError):
        return "+0Hz"
    value = max(-50, min(50, value))
    return f"{value:+d}Hz"
