"""
app/keyvault.py - bring-your-own-keys vault.

Every provider in ``app/providers.py`` can be unlocked two ways: an environment
variable on the server (set once in Vercel), or a key the user pastes into the UI
and stores here. Runtime keys win over env keys, so a deployment with zero
configured keys still becomes fully usable the moment a user adds his own
Gemini / OpenAI / fal / Replicate / ComfyUI credentials.

Keys are stored in the existing ``bglabs_projects`` table (``project_type =
"provider_key"``) as obfuscated values, never as plain text:

    obfuscate(value) = base64( value XOR keystream(SECRET_KEY, "bglabs:keyvault:1") )

This is deliberate at-rest obfuscation, not a substitute for a KMS - the sandbox
has no crypto library beyond the stdlib. It keeps keys out of plain sight in the
database and out of every log and API response (only the last 4 chars are ever
returned to the client).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bglabs.keyvault")

KEY_TYPE = "provider_key"
_SALT = "bglabs:keyvault:1"

# What a user may store, and which provider each name unlocks.
KNOWN_KEYS: Dict[str, Dict[str, str]] = {
    "OPENAI_API_KEY": {"provider": "openai", "label": "OpenAI", "get": "https://platform.openai.com/api-keys",
                       "unlocks": "GPT Image 1, gpt-4o-mini-tts, GPT chat"},
    "GEMINI_API_KEY": {"provider": "gemini", "label": "Google Gemini", "get": "https://aistudio.google.com/apikey",
                       "unlocks": "Veo 3 video, Nano Banana images, Gemini TTS/chat"},
    "REPLICATE_API_TOKEN": {"provider": "replicate", "label": "Replicate", "get": "https://replicate.com/",
                            "unlocks": "F5-TTS, Wan 2.2, SadTalker, Real-ESRGAN, Whisper"},
    "FAL_KEY": {"provider": "fal", "label": "fal.ai", "get": "https://fal.ai/dashboard/keys",
                "unlocks": "Veo 3, Seedance, Wan, Hunyuan, FLUX Pro, EchoMimic, LivePortrait"},
    "HF_TOKEN": {"provider": "hf", "label": "Hugging Face", "get": "https://huggingface.co/settings/tokens",
                 "unlocks": "FLUX.1 schnell, Whisper, HF Spaces (F5-TTS, Kokoro, GPT-SoVITS)"},
    "ELEVENLABS_API_KEY": {"provider": "elevenlabs", "label": "ElevenLabs", "get": "https://elevenlabs.io/",
                           "unlocks": "Multilingual v2 speech"},
    "ANTHROPIC_API_KEY": {"provider": "anthropic", "label": "Anthropic", "get": "https://console.anthropic.com/",
                          "unlocks": "Claude chat agents"},
    "GROQ_API_KEY": {"provider": "groq", "label": "Groq", "get": "https://console.groq.com/keys",
                     "unlocks": "Llama 3.3 70B chat, whisper-large-v3 transcription"},
    "OPENROUTER_API_KEY": {"provider": "openrouter", "label": "OpenRouter", "get": "https://openrouter.ai/keys",
                           "unlocks": "Any model through one key (ViMax default)"},
    "LITELLM_BASE_URL": {"provider": "litellm", "label": "LiteLLM proxy URL", "get": "https://github.com/BerriAI/litellm",
                         "unlocks": "Your own LiteLLM router"},
    "LITELLM_API_KEY": {"provider": "litellm", "label": "LiteLLM proxy key", "get": "https://github.com/BerriAI/litellm",
                        "unlocks": "Your own LiteLLM router"},
    "LLM_GATEWAY_BASE_URL": {"provider": "llmgateway", "label": "LLM Gateway URL",
                             "get": "https://github.com/theopenco/llmgateway", "unlocks": "Your own LLM Gateway"},
    "LLM_GATEWAY_API_KEY": {"provider": "llmgateway", "label": "LLM Gateway key",
                            "get": "https://github.com/theopenco/llmgateway", "unlocks": "Your own LLM Gateway"},
    "YOLOROUTER_API_KEY": {"provider": "yolorouter", "label": "yolorouter key", "get": "https://github.com/yolorouter/yolorouter",
                           "unlocks": "yolorouter model routing"},
    "POLLINATIONS_TOKEN": {"provider": "pollinations", "label": "Pollinations token (optional)",
                           "get": "https://pollinations.ai/", "unlocks": "Higher free image rate limits"},
    "COMFYUI_URL": {"provider": "comfyui", "label": "ComfyUI server URL", "get": "https://github.com/comfyanonymous/ComfyUI",
                    "unlocks": "Your ComfyUI (RunPod / Vast / local tunnel)"},
    "COMFYUI_WORKFLOW": {"provider": "comfyui", "label": "ComfyUI workflow JSON",
                         "get": "https://github.com/comfyanonymous/ComfyUI", "unlocks": "Default workflow for image/video"},
    "SD_WEBUI_URL": {"provider": "sdwebui", "label": "Stable Diffusion WebUI URL",
                     "get": "https://github.com/AUTOMATIC1111/stable-diffusion-webui", "unlocks": "Your SD WebUI + ControlNet"},
    "INVOKEAI_URL": {"provider": "invokeai", "label": "InvokeAI URL", "get": "https://github.com/invoke-ai/InvokeAI",
                     "unlocks": "Your InvokeAI canvas"},
    "FOOOCUS_URL": {"provider": "fooocus", "label": "Fooocus URL", "get": "https://github.com/lllyasviel/Fooocus",
                    "unlocks": "Your Fooocus server"},
    "FASTSD_URL": {"provider": "fastsd", "label": "FastSD CPU URL", "get": "https://github.com/rupeshs/fastsdcpu",
                   "unlocks": "CPU Stable Diffusion"},
    "LIVETALKING_URL": {"provider": "livetalking", "label": "LiveTalking URL", "get": "https://github.com/lipku/LiveTalking",
                        "unlocks": "Real-time talking avatar"},
    "MUSETALK_URL": {"provider": "musetalk", "label": "MuseTalk server URL", "get": "https://github.com/TMElyralab/MuseTalk",
                     "unlocks": "Your MuseTalk lip-sync"},
    "SADTALKER_URL": {"provider": "sadtalker", "label": "SadTalker server URL", "get": "https://github.com/OpenTalker/SadTalker",
                      "unlocks": "Your SadTalker deployment"},
    "GPTSOVITS_URL": {"provider": "gptsovits", "label": "GPT-SoVITS URL", "get": "https://github.com/RVC-Boss/GPT-SoVITS",
                      "unlocks": "Your GPT-SoVITS voice cloning"},
    "F5_TTS_URL": {"provider": "f5tts", "label": "F5-TTS server/Space URL", "get": "https://github.com/SWivid/F5-TTS",
                   "unlocks": "Your F5-TTS deployment"},
    "OPENVOICE_URL": {"provider": "openvoice", "label": "OpenVoice URL", "get": "https://github.com/myshell-ai/OpenVoice",
                      "unlocks": "Your OpenVoice deployment"},
    "CHATTERBOX_URL": {"provider": "chatterbox", "label": "Chatterbox URL", "get": "https://github.com/resemble-ai/chatterbox",
                       "unlocks": "Your Chatterbox voice cloning"},
    "KOKORO_URL": {"provider": "kokoro", "label": "Kokoro URL", "get": "https://github.com/hexgrad/kokoro",
                   "unlocks": "Your Kokoro TTS"},
    "FISH_SPEECH_URL": {"provider": "fishspeech", "label": "fish-speech URL", "get": "https://github.com/fishaudio/fish-speech",
                        "unlocks": "Your fish-speech deployment"},
    "CHATTS_URL": {"provider": "chattts", "label": "ChatTTS URL", "get": "https://github.com/2noise/ChatTTS",
                   "unlocks": "Your ChatTTS deployment"},
    "COQUI_URL": {"provider": "coqui", "label": "Coqui TTS URL", "get": "https://github.com/coqui-ai/TTS",
                  "unlocks": "Your Coqui/XTTS deployment"},
    "QWEN_TTS_URL": {"provider": "qwentts", "label": "Qwen3-TTS URL", "get": "https://github.com/QwenLM/Qwen3-TTS",
                     "unlocks": "Your Qwen3-TTS deployment"},
    "REALESRGAN_URL": {"provider": "realesrgan", "label": "Real-ESRGAN URL", "get": "https://github.com/xinntao/Real-ESRGAN",
                       "unlocks": "Your upscaler"},
    "RENDER_SERVICE_URL": {"provider": "render_service", "label": "Render/stitch service URL",
                           "get": "https://github.com/Zulko/moviepy", "unlocks": "FFmpeg/moviepy/Remotion render farm"},
    "HF_F5_TTS_SPACE": {"provider": "hf_space", "label": "F5-TTS HF Space id", "get": "https://huggingface.co/spaces",
                        "unlocks": "A specific F5-TTS Space"},
    "HF_F5_TTS_ENDPOINT": {"provider": "hf_space", "label": "F5-TTS gradio endpoint",
                           "get": "https://huggingface.co/spaces", "unlocks": "Gradio api_name override"},
    "HF_F5_TTS_DATA": {"provider": "hf_space", "label": "F5-TTS input JSON template",
                       "get": "https://huggingface.co/spaces", "unlocks": "Gradio input order override"},
}


def _secret() -> bytes:
    secret = os.getenv("SECRET_KEY") or os.getenv("BGLABS_SECRET_KEY") or "bglabs-secret-key-change-in-production"
    return secret.encode()


def _keystream(length: int) -> bytes:
    """Deterministic pseudo-random stream derived from SECRET_KEY (SHA-256 counter mode)."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hashlib.sha256(_secret() + f":{_SALT}:{counter}".encode()).digest())
        counter += 1
    return bytes(out[:length])


def obfuscate(value: str) -> str:
    raw = (value or "").encode()
    stream = _keystream(len(raw))
    return base64.urlsafe_b64encode(bytes(b ^ s for b, s in zip(raw, stream))).decode()


def deobfuscate(blob: str) -> str:
    try:
        raw = base64.urlsafe_b64decode((blob or "").encode())
    except Exception:
        return ""
    stream = _keystream(len(raw))
    return bytes(b ^ s for b, s in zip(raw, stream)).decode(errors="replace")


def mask(value: str) -> str:
    value = value or ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * 8}{value[-4:]}"


def key_names() -> List[Dict[str, Any]]:
    """Catalogue of storable keys for the UI."""
    out = []
    for name, meta in KNOWN_KEYS.items():
        out.append({"name": name, "provider": meta["provider"], "label": meta["label"],
                    "where": meta["get"], "unlocks": meta["unlocks"],
                    "is_url": name.endswith("_URL") or name.endswith("_WORKFLOW") or name.endswith("_DATA")
                              or name.endswith("_ENDPOINT") or name.endswith("_SPACE")})
    return out


async def save_key(store, user_id: int, name: str, value: str) -> Dict[str, Any]:
    name = (name or "").strip().upper()
    if name not in KNOWN_KEYS:
        raise ValueError(f"Unknown key '{name}'. Supported: {', '.join(sorted(KNOWN_KEYS))}")
    value = (value or "").strip()
    if not value:
        raise ValueError("A value is required (send an empty string to delete).")
    meta = KNOWN_KEYS[name]
    settings = {"name": name, "provider": meta["provider"], "value": obfuscate(value),
                "masked": mask(value), "source": "user"}
    # One active value per name. Delete an older row first so newest/oldest
    # ordering differences between stores can never expose a stale key.
    for old in await store.list_projects(user_id, project_type=KEY_TYPE, limit=200):
        if (old.get("settings") or {}).get("name") == name:
            await store.delete_project(old["id"], user_id)
    row = await store.add_project(user_id=user_id, name=name, project_type=KEY_TYPE, settings=settings)
    return {"name": name, "provider": meta["provider"], "masked": mask(value), "id": (row or {}).get("id")}


async def delete_key(store, user_id: int, name: str) -> bool:
    name = (name or "").strip().upper()
    for row in await store.list_projects(user_id, project_type=KEY_TYPE, limit=200):
        settings = row.get("settings") or {}
        if settings.get("name") == name:
            return await store.delete_project(row["id"], user_id)
    return False


async def load_keys(store, user_id: Optional[int]) -> Dict[str, str]:
    """All stored keys for a user as ``{ENV_NAME: value}`` - ready to hand to providers."""
    if not user_id:
        return {}
    out: Dict[str, str] = {}
    try:
        rows = await store.list_projects(user_id, project_type=KEY_TYPE, limit=200)
    except Exception as exc:
        logger.warning("key vault unavailable: %s", exc)
        return {}
    for row in rows:
        settings = row.get("settings") or {}
        name = settings.get("name")
        blob = settings.get("value")
        if not name or not blob:
            continue
        value = deobfuscate(blob)
        if value:
            out[name] = value
    return out


async def vault_status(store, user_id: Optional[int]) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Per-key status for the UI, plus the resolved key map."""
    keys = await load_keys(store, user_id)
    rows = []
    for name, meta in KNOWN_KEYS.items():
        stored = name in keys
        from_env = bool((os.getenv(name) or "").strip())
        rows.append({"name": name, "provider": meta["provider"], "label": meta["label"], "where": meta["get"],
                     "unlocks": meta["unlocks"], "stored_by_you": stored, "set_on_server": from_env,
                     "active": stored or from_env, "source": "user" if stored else ("server" if from_env else None),
                     "masked": mask(keys[name]) if stored else None})
    return rows, keys


__all__ = ["KNOWN_KEYS", "KEY_TYPE", "key_names", "save_key", "delete_key", "load_keys", "vault_status",
           "obfuscate", "deobfuscate", "mask"]
