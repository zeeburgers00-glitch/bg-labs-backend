"""
BG LABS - Combined TTS Engine
F5-TTS (HuggingFace Spaces) + Edge TTS = ElevenLabs-level quality
100% FREE - No API keys needed
"""
import os
import io
import uuid
import time
import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import httpx
import edge_tts

logger = logging.getLogger("bglabs.tts")

# ============================================================
# CONFIG
# ============================================================
F5_TTS_SPACE = "mrfakename/E2-F5-TTS"
F5_TTS_API_BASE = f"https://{F5_TTS_SPACE.replace('/', '-').lower()}.hf.space"
F5_TTS_TIMEOUT = 60.0

# Default English reference voices for F5-TTS voice cloning
F5_REF_VOICES = {
    "en_male": {
        "name": "English Male (Professional)",
        "ref_text": "Some call me nature, others call me mother nature.",
        "ref_url": "https://github.com/SWivid/F5-TTS/raw/main/src/f5_tts/infer/examples/basic/basic_ref_en.wav",
    },
    "en_female": {
        "name": "English Female (Warm)",
        "ref_text": "I don't really care what you call me. I've been a silent spectator.",
        "ref_url": "https://github.com/SWivid/F5-TTS/raw/main/src/f5_tts/infer/examples/basic/basic_ref_en.wav",
    },
}

# Edge TTS voices (same as before)
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
    "en-IN-NeerjaNeural": {"name": "Neerja", "voice": "en-IN-NeerjaNeural", "gender": "Female", "lang": "en", "accent": "Indian", "color": "#d946ef"},
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
    "pt-BR-FranciscaNeural": {"name": "Francisca", "voice": "pt-BR-FranciscaNeural", "gender": "Female", "lang": "pt", "accent": "Brazilian", "color": "#818cf8"},
    "it-IT-ElsaNeural": {"name": "Elsa", "voice": "it-IT-ElsaNeural", "gender": "Female", "lang": "it", "accent": "Italian", "color": "#f472b6"},
    "tr-TR-EmelNeural": {"name": "Emel", "voice": "tr-TR-EmelNeural", "gender": "Female", "lang": "tr", "accent": "Turkish", "color": "#a3e635"},
    "ru-RU-SvetlanaNeural": {"name": "Svetlana", "voice": "ru-RU-SvetlanaNeural", "gender": "Female", "lang": "ru", "accent": "Russian", "color": "#38bdf8"},
    "pl-PL-AgnieszkaNeural": {"name": "Agnieszka", "voice": "pl-PL-AgnieszkaNeural", "gender": "Female", "lang": "pl", "accent": "Polish", "color": "#d946ef"},
    "nl-NL-ColetteNeural": {"name": "Colette", "voice": "nl-NL-ColetteNeural", "gender": "Female", "lang": "nl", "accent": "Dutch", "color": "#0891b2"},
    "sv-SE-SofieNeural": {"name": "Sofie", "voice": "sv-SE-SofieNeural", "gender": "Female", "lang": "sv", "accent": "Swedish", "color": "#f43f5e"},
    "da-DK-ChristelNeural": {"name": "Christel", "voice": "da-DK-ChristelNeural", "gender": "Female", "lang": "da", "accent": "Danish", "color": "#c084fc"},
}


# ============================================================
# F5-TTS ENGINE (HuggingFace Spaces - FREE)
# ============================================================
async def f5_tts_generate(
    text: str,
    ref_voice_key: str = "en_male",
    custom_ref_audio_url: Optional[str] = None,
    custom_ref_text: Optional[str] = None,
) -> Tuple[bytes, str]:
    """
    Generate speech using F5-TTS via HuggingFace Spaces API.
    Returns (audio_bytes, engine_name).
    """
    ref = F5_REF_VOICES.get(ref_voice_key, F5_REF_VOICES["en_male"])
    ref_text = custom_ref_text or ref["ref_text"]
    ref_url = custom_ref_audio_url or ref["ref_url"]

    async with httpx.AsyncClient(timeout=F5_TTS_TIMEOUT) as client:
        # Step 1: Download reference audio
        try:
            ref_resp = await client.get(ref_url, follow_redirects=True)
            if ref_resp.status_code != 200:
                raise Exception(f"Failed to download ref audio: {ref_resp.status_code}")
            ref_audio_bytes = ref_resp.content
        except Exception as e:
            raise Exception(f"F5-TTS reference audio download failed: {e}")

        # Step 2: Upload reference audio to HF Space
        upload_url = f"{F5_TTS_API_BASE}/gradio_api/upload"
        files = {"files": ("ref.wav", io.BytesIO(ref_audio_bytes), "audio/wav")}
        try:
            upload_resp = await client.post(upload_url, files=files)
            if upload_resp.status_code != 200:
                raise Exception(f"Upload failed: {upload_resp.status_code}")
            upload_data = upload_resp.json()
            ref_file_path = upload_data[0] if isinstance(upload_data, list) else upload_data.get("path", "")
        except Exception as e:
            raise Exception(f"F5-TTS upload failed: {e}")

        # Step 3: Call predict endpoint
        predict_url = f"{F5_TTS_API_BASE}/gradio_api/call/predict"
        payload = {
            "data": [
                {"path": ref_file_path, "meta": {"_type": "gradio.FileData"}},
                ref_text,
                text,
                True,  # remove_silence
            ]
        }
        try:
            predict_resp = await client.post(predict_url, json=payload)
            if predict_resp.status_code != 200:
                raise Exception(f"Predict request failed: {predict_resp.status_code}")
            job_data = predict_resp.json()
            job_id = job_data.get("event_id", "")
        except Exception as e:
            raise Exception(f"F5-TTS predict failed: {e}")

        # Step 4: Poll for result
        result_url = f"{F5_TTS_API_BASE}/gradio_api/call/predict/{job_id}"
        for _ in range(60):  # Max 60 attempts (60 seconds)
            await asyncio.sleep(1)
            try:
                result_resp = await client.get(result_url)
                if result_resp.status_code == 200:
                    result_text = result_resp.text
                    if "completed" in result_text.lower() or "output" in result_text.lower():
                        import json
                        for line in result_text.strip().split("\n"):
                            if line.startswith("data:"):
                                data_str = line[5:].strip()
                                try:
                                    result = json.loads(data_str)
                                    if isinstance(result, list) and len(result) > 0:
                                        audio_info = result[0]
                                        if isinstance(audio_info, dict) and "url" in audio_info:
                                            audio_resp = await client.get(audio_info["url"], follow_redirects=True)
                                            if audio_resp.status_code == 200:
                                                return audio_resp.content, "F5-TTS"
                                        elif isinstance(audio_info, dict) and "path" in audio_info:
                                            audio_resp = await client.get(
                                                f"{F5_TTS_API_BASE}/gradio_api/file={audio_info['path']}",
                                                follow_redirects=True
                                            )
                                            if audio_resp.status_code == 200:
                                                return audio_resp.content, "F5-TTS"
                                except json.JSONDecodeError:
                                    continue
            except Exception:
                continue

        raise Exception("F5-TTS generation timed out")


# ============================================================
# EDGE TTS ENGINE (Microsoft - FREE)
# ============================================================
async def edge_tts_generate(text: str, voice_key: str = "en-US-AriaNeural") -> Tuple[bytes, str]:
    """
    Generate speech using Edge TTS.
    Returns (audio_bytes, engine_name).
    """
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
# SMART TTS ROUTER (Auto-select best engine)
# ============================================================
async def smart_tts_generate(
    text: str,
    engine: str = "auto",
    voice_key: str = "en-US-AriaNeural",
    ref_voice_key: str = "en_male",
    custom_ref_audio_url: Optional[str] = None,
    custom_ref_text: Optional[str] = None,
) -> Tuple[bytes, str, str]:
    """
    Smart TTS router - auto-selects best engine.
    Returns (audio_bytes, engine_used, voice_name).

    Engines:
    - "f5": F5-TTS only (ultra realistic, English best)
    - "edge": Edge TTS only (fast, 75+ languages)
    - "auto": Try F5 first for English, Edge for others
    """
    if not text or not text.strip():
        raise Exception("Text is required")

    text = text.strip()

    # Auto mode: choose engine based on language
    if engine == "auto":
        lang = voice_key.split("-")[0] if "-" in voice_key else "en"
        # F5-TTS is best for English
        if lang.startswith("en"):
            engine = "f5"
        else:
            engine = "edge"

    # F5-TTS engine
    if engine == "f5":
        try:
            audio_bytes, eng = await f5_tts_generate(text, ref_voice_key, custom_ref_audio_url, custom_ref_text)
            voice_name = F5_REF_VOICES.get(ref_voice_key, {}).get("name", "F5 Voice")
            return audio_bytes, eng, voice_name
        except Exception as e:
            logger.warning(f"F5-TTS failed: {e}, falling back to Edge TTS")
            # Fallback to Edge TTS
            audio_bytes, eng = await edge_tts_generate(text, voice_key)
            voice_name = EDGE_VOICES.get(voice_key, {}).get("name", "Edge Voice")
            return audio_bytes, eng, voice_name

    # Edge TTS engine
    audio_bytes, eng = await edge_tts_generate(text, voice_key)
    voice_name = EDGE_VOICES.get(voice_key, {}).get("name", "Edge Voice")
    return audio_bytes, eng, voice_name


# ============================================================
# VOICE LIST (Combined)
# ============================================================
def get_all_voices():
    """Return all voices from both engines."""
    voices = []

    # F5-TTS voices (premium quality)
    for key, info in F5_REF_VOICES.items():
        voices.append({
            "key": f"f5:{key}",
            "name": info["name"],
            "engine": "F5-TTS",
            "quality": "Ultra (ElevenLabs-level)",
            "gender": "Both",
            "lang": "en",
            "accent": "English",
            "color": "#f97316",
            "premium": True,
        })

    # Edge TTS voices (fast, multi-language)
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
            "premium": False,
        })

    return voices
