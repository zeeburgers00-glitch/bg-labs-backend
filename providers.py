"""TTS provider abstraction: pluggable engines (Edge-TTS, F5-TTS)."""
import os
import logging
from typing import Optional, Tuple

import httpx

from tts_engine import edge_tts_generate, EDGE_VOICES

logger = logging.getLogger("bglabs.providers")


class TTSProviderError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class TTSProvider:
    name = "base"
    is_gpu = False

    async def generate(self, text: str, voice: dict, settings: dict) -> Tuple[bytes, float]:
        raise NotImplementedError

    async def health(self) -> dict:
        raise NotImplementedError


class EdgeTTSProvider(TTSProvider):
    name = "edge-tts"
    is_gpu = False

    async def generate(self, text: str, voice: dict, settings: dict) -> Tuple[bytes, float]:
        voice_key = voice.get("key") or voice.get("voice_key") or "en-US-AriaNeural"
        rate = settings.get("rate", "+0%")
        pitch = settings.get("pitch", "+0Hz")
        audio = await edge_tts_generate(text, voice_key, rate=rate, pitch=pitch)
        if not audio:
            raise TTSProviderError("EDGE_TTS_EMPTY", "Edge TTS returned empty audio.")
        return audio, 0.0

    async def health(self) -> dict:
        return {"status": "healthy", "model": "Edge-TTS", "gpu": False}


class F5TTSProvider(TTSProvider):
    name = "f5-tts"
    is_gpu = True

    def __init__(self):
        url = os.getenv("F5_TTS_API_URL", "").strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
        self.base_url = url
        self.api_key = os.getenv("F5_TTS_API_KEY", "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict:
        h = {}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def generate(self, text: str, voice: dict, settings: dict) -> Tuple[bytes, float]:
        if not self.configured:
            raise TTSProviderError("F5_TTS_NOT_CONFIGURED", "F5-TTS service is not configured. Add F5_TTS_API_URL.")
        reference_audio = voice.get("reference_audio_url", "")
        reference_text = voice.get("reference_text", "")
        if not reference_audio:
            raise TTSProviderError("F5_TTS_NO_REFERENCE", "Cloned voice has no reference audio.")
        body = {
            "text": text,
            "reference_audio": reference_audio,
            "reference_text": reference_text,
            "settings": {"speed": float(settings.get("speed", 1.0))},
        }
        try:
            async with httpx.AsyncClient(timeout=200.0) as client:
                resp = await client.post(f"{self.base_url}/generate", json=body, headers=self._headers())
                if resp.status_code != 200:
                    raise TTSProviderError("F5_TTS_FAILED", f"F5-TTS returned HTTP {resp.status_code}.")
                data = resp.json()
        except httpx.RequestError as e:
            raise TTSProviderError("F5_TTS_UNREACHABLE", f"Cannot reach F5-TTS service: {e}")
        if not data.get("success", True) and data.get("audio_url") is None:
            raise TTSProviderError("F5_TTS_FAILED", data.get("error") or data.get("message") or "F5-TTS generation failed.")
        audio_url = data.get("audio_url")
        duration = float(data.get("duration") or 0.0)
        # Fetch the generated audio bytes so we can store them securely.
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                ar = await client.get(audio_url, headers=self._headers())
                if ar.status_code != 200:
                    raise TTSProviderError("F5_TTS_FETCH_FAILED", "Could not download generated audio.")
                audio = ar.content
        except httpx.RequestError as e:
            raise TTSProviderError("F5_TTS_FETCH_FAILED", f"Could not download generated audio: {e}")
        if not audio:
            raise TTSProviderError("F5_TTS_EMPTY", "F5-TTS returned empty audio.")
        return audio, duration

    async def health(self) -> dict:
        if not self.configured:
            return {"status": "unavailable", "model": "F5-TTS", "gpu": False, "detail": "not configured"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/health", headers=self._headers())
                if resp.status_code == 200:
                    out = {"status": "healthy", "model": "F5-TTS", "gpu": True}
                    try:
                        out.update(resp.json())
                    except Exception:
                        pass
                    return out
                return {"status": "unhealthy", "model": "F5-TTS", "gpu": True, "detail": f"HTTP {resp.status_code}"}
        except httpx.RequestError as e:
            return {"status": "unreachable", "model": "F5-TTS", "gpu": True, "detail": str(e)}


_edge = EdgeTTSProvider()
_f5 = F5TTSProvider()


def get_provider(engine: str) -> TTSProvider:
    if engine == "f5-tts":
        return _f5
    return _edge


def f5_provider() -> F5TTSProvider:
    return _f5
