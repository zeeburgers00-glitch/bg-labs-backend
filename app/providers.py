"""
app/providers.py - one router in front of every model this platform can reach.

Why a router instead of installing the repos
--------------------------------------------
The repos in scope (ComfyUI, SD-WebUI, InvokeAI, Fooocus, FastSD CPU, ControlNet,
Real-ESRGAN, F5-TTS, GPT-SoVITS, OpenVoice, Chatterbox, Kokoro, ChatTTS, Coqui,
fish-speech, Qwen3-TTS, SadTalker, MuseTalk, LiveTalking, LivePortrait, EchoMimic,
Whisper, FFmpeg, moviepy, Remotion, ViMax, Wan, Hunyuan, Helios, ...) are GPU
projects. Vercel serverless has no GPU, no ffmpeg binary and a 50 MB bundle limit,
so they cannot run *inside* the function. They are reachable in four ways, and this
module supports all four:

1. ``free``      - keyless hosted inference (Pollinations FLUX, edge-tts).
2. ``hosted``    - the same open-source weights served by fal.ai / Replicate /
                   Hugging Face / Google (Veo 3, Wan 2.2, Hunyuan, Seedance, LTX,
                   Real-ESRGAN, Whisper, SadTalker, LivePortrait, EchoMimic).
3. ``space``     - a public or private Hugging Face Space running the repo's own
                   Gradio app (F5-TTS, GPT-SoVITS, Kokoro, ChatTTS, Fooocus...).
4. ``self``      - *your* server: RunPod / Vast / Lambda / HF dedicated Space /
                   local tunnel. You give a base URL, this module speaks its API
                   (ComfyUI, SD-WebUI, InvokeAI, LiveTalking, MuseTalk, ...).

Keys come from the server environment or, per user, from ``app/keyvault.py`` -
runtime keys win, so nothing has to be redeployed to switch a model on.

Every entry is JSON-serialisable and exposes: ``configured`` (can it run now?),
``needs`` (the env var / vault key that turns it on), ``repo`` (the GitHub project
it comes from) and ``notes``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("bglabs.providers")


class ProviderError(Exception):
    """A provider call failed in a way the UI should explain, not hide."""

    def __init__(self, message: str, *, status_code: int = 502, hint: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.hint = hint

    def as_dict(self) -> Dict[str, Any]:
        out = {"error": self.message}
        if self.hint:
            out["hint"] = self.hint
        return out


# --------------------------------------------------------------------------- #
# configuration resolution (server env + per-user vault)
# --------------------------------------------------------------------------- #

def _k(name: str, keys: Optional[Dict[str, str]] = None, default: str = "") -> str:
    """Value of a config name: the user's vault first, then the server env."""
    if keys and keys.get(name):
        return str(keys[name]).strip()
    return (os.getenv(name) or default).strip()


def _provider_key(provider: str, keys: Optional[Dict[str, str]] = None) -> str:
    env_name = {
        "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY", "replicate": "REPLICATE_API_TOKEN",
        "fal": "FAL_KEY", "hf": "HF_TOKEN", "elevenlabs": "ELEVENLABS_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY", "groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY",
        "litellm": "LITELLM_API_KEY", "llmgateway": "LLM_GATEWAY_API_KEY", "yolorouter": "YOLOROUTER_API_KEY",
        "pollinations": "POLLINATIONS_TOKEN",
    }.get(provider, "")
    if provider == "gemini":
        return _k("GEMINI_API_KEY", keys) or _k("GOOGLE_API_KEY", keys)
    return _k(env_name, keys) if env_name else ""


OPENAI_BASE = "https://api.openai.com/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com"
GROQ_BASE = "https://api.groq.com/openai/v1"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
YOLOROUTER_BASE = "https://api.yolorouter.com/v1"
FAL_QUEUE = "https://queue.fal.run"
REPLICATE_BASE = "https://api.replicate.com/v1"
HF_INFERENCE = "https://router.huggingface.co/hf-inference"

CAPABILITIES = ("chat", "tts", "image", "image_edit", "upscale", "video", "avatar",
                "transcribe", "render")

# backends: edge, pollinations, openai, gemini, anthropic, elevenlabs, hf,
#           openai_compat, gradio, comfyui, sdwebui, http_json, fal, replicate, none
SYNC_BACKENDS = ("edge", "pollinations", "openai", "gemini", "anthropic", "elevenlabs",
                 "hf", "openai_compat", "gradio", "sdwebui", "http_json", "none")
QUEUE_BACKENDS = ("fal", "replicate", "comfyui")


def _e(entry_id, capability, label, backend, model, *, free=False, needs=None, quality=3,
       sync=None, repo="", notes="", input_map=None, extra=None, endpoint="", data_template=None,
       response_path="", response_kind="", base=""):
    """Compact catalog entry builder."""
    return {
        "id": entry_id, "capability": capability, "label": label, "backend": backend,
        "model": model, "free": bool(free), "needs": needs, "quality": quality,
        "sync": (backend in SYNC_BACKENDS) if sync is None else bool(sync),
        "repo": repo, "notes": notes, "input_map": input_map or {}, "extra": extra or {},
        "endpoint": endpoint, "data_template": data_template, "response_path": response_path,
        "response_kind": response_kind, "base": base,
    }


def _catalog() -> List[Dict[str, Any]]:
    C: List[Dict[str, Any]] = []

    # ============================ CHAT / AGENT BRAINS ===================== #
    C.append(_e("openai-chat", "chat", "OpenAI GPT (latest)", "openai_compat",
                _env_model("OPENAI_CHAT_MODEL", "gpt-4o"), needs="OPENAI_API_KEY", quality=5,
                repo="https://github.com/openai/openai-python", base=OPENAI_BASE,
                notes="Strongest general reasoning; used by every agent when this key is present."))
    C.append(_e("gemini-chat", "chat", "Google Gemini 2.5 Pro", "gemini",
                _env_model("GEMINI_CHAT_MODEL", "gemini-2.5-pro"), needs="GEMINI_API_KEY", quality=5,
                repo="https://github.com/googleapis/python-genai",
                notes="Long context (1M tokens) - good for whole transcripts and channel audits."))
    C.append(_e("claude-chat", "chat", "Anthropic Claude Sonnet", "anthropic",
                _env_model("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"), needs="ANTHROPIC_API_KEY", quality=5,
                repo="https://github.com/anthropics/anthropic-sdk-python",
                notes="Best-in-class long-form writing: scripts, packaging, retention analysis."))
    C.append(_e("groq-llama", "chat", "Groq Llama 3.3 70B (fast)", "openai_compat",
                _env_model("GROQ_MODEL", "llama-3.3-70b-versatile"), needs="GROQ_API_KEY", quality=4,
                repo="https://github.com/groq/groq-python", base=GROQ_BASE,
                notes="Hundreds of tokens/second - the right choice for bulk agent runs."))
    C.append(_e("openrouter-any", "chat", "OpenRouter (any model, one key)", "openai_compat",
                _env_model("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"), needs="OPENROUTER_API_KEY",
                quality=5, repo="https://github.com/HKUDS/ViMax", base=OPENROUTER_BASE,
                notes="ViMax's default route. Set OPENROUTER_MODEL to any slug, e.g. "
                      "google/gemini-2.5-pro or openai/gpt-4o."))
    C.append(_e("litellm-proxy", "chat", "Your LiteLLM proxy", "openai_compat",
                _env_model("LITELLM_MODEL", "gpt-4o"), needs="LITELLM_BASE_URL", quality=5,
                repo="https://github.com/BerriAI/litellm",
                notes="Point LITELLM_BASE_URL at your own LiteLLM router; keys/fallbacks stay on your side."))
    C.append(_e("llm-gateway", "chat", "Your LLM Gateway", "openai_compat",
                _env_model("LLM_GATEWAY_MODEL", "openai/gpt-4o"), needs="LLM_GATEWAY_BASE_URL", quality=5,
                repo="https://github.com/theopenco/llmgateway",
                notes="OpenAI-compatible gateway with your own provider mix and budgets."))
    C.append(_e("yolorouter", "chat", "yolorouter", "openai_compat",
                _env_model("YOLOROUTER_MODEL", "gpt-4o"), needs="YOLOROUTER_API_KEY", quality=4,
                repo="https://github.com/yolorouter/yolorouter",
                base=_env_model("YOLOROUTER_BASE_URL", YOLOROUTER_BASE),
                notes="OpenAI-compatible routing; override YOLOROUTER_BASE_URL if your deployment differs."))
    C.append(_e("pollinations-text", "chat", "Pollinations text (free, no key)", "pollinations",
                _env_model("POLLINATIONS_TEXT_MODEL", "openai"), free=True, quality=4,
                repo="https://github.com/pollinations/pollinations",
                notes="Free keyless fallback so agents always work. Rate limited; add a key for reliability."))

    # ================================ TTS ================================= #
    C.append(_e("edge-tts", "tts", "Microsoft Edge TTS (free)", "edge",
                _env_model("EDGE_TTS_MODEL", "en-US-AriaNeural"), free=True, quality=3, sync=True,
                repo="https://github.com/rany2/edge-tts",
                notes="Free, no key, 64 neural voices incl. ur-PK and hi-IN. Always available."))
    C.append(_e("f5-tts-space", "tts", "F5-TTS (open source, HF Space)", "gradio",
                _env_model("HF_F5_TTS_SPACE", "SWivid/F5-TTS"), free=True, quality=5,
                repo="https://github.com/SWivid/F5-TTS",
                endpoint=_env_model("HF_F5_TTS_ENDPOINT", "/predict"),
                data_template=["{ref_audio}", "{ref_text}", "{text}", True, 0, "{speed}", False],
                notes="Zero-shot voice cloning from the official F5-TTS repo on a public Space. "
                      "Override HF_F5_TTS_SPACE / HF_F5_TTS_ENDPOINT / HF_F5_TTS_DATA for your own Space."))
    C.append(_e("f5-tts-self", "tts", "F5-TTS (your server)", "http_json",
                _env_model("F5_TTS_URL", ""), needs="F5_TTS_URL", quality=5,
                repo="https://github.com/SWivid/F5-TTS",
                input_map={"text": "text", "audio_url": "ref_audio", "ref_text": "ref_text", "speed": "speed"},
                response_kind="audio",
                notes="Your own F5-TTS (RunPod/Vast/HF dedicated). POSTs JSON, expects audio bytes, "
                      "base64 or a URL in the response."))
    C.append(_e("f5-tts-replicate", "tts", "F5-TTS (Replicate GPU)", "replicate",
                _env_model("REPLICATE_F5_TTS_MODEL", "SWivid/F5-TTS"), needs="REPLICATE_API_TOKEN", quality=5,
                repo="https://github.com/SWivid/F5-TTS",
                input_map={"text": "text", "audio_url": "ref_audio", "ref_text": "ref_text", "speed": "speed"},
                notes="Set REPLICATE_F5_TTS_MODEL to a slug you have access to."))
    C.append(_e("gpt-sovits-space", "tts", "GPT-SoVITS (HF Space)", "gradio",
                _env_model("HF_GPTSOVITS_SPACE", ""), needs="HF_GPTSOVITS_SPACE", quality=5,
                repo="https://github.com/RVC-Boss/GPT-SoVITS",
                notes="Few-shot voice cloning. Set HF_GPTSOVITS_SPACE to the Space id (owner/name)."))
    C.append(_e("gpt-sovits-self", "tts", "GPT-SoVITS (your server)", "http_json",
                _env_model("GPTSOVITS_URL", ""), needs="GPTSOVITS_URL", quality=5,
                repo="https://github.com/RVC-Boss/GPT-SoVITS",
                input_map={"text": "text", "language": "text_lang", "ref_text": "ref_text",
                           "audio_url": "ref_audio_path", "speed": "speed_factor"},
                response_kind="audio",
                notes="Uses the repo's own /tts endpoint shape (text, text_lang, ref_audio_path, ref_text)."))
    C.append(_e("openvoice-self", "tts", "OpenVoice (your server)", "http_json",
                _env_model("OPENVOICE_URL", ""), needs="OPENVOICE_URL", quality=4,
                repo="https://github.com/myshell-ai/OpenVoice",
                input_map={"text": "text", "language": "language", "speed": "speed"},
                response_kind="audio", notes="Voice cloning plus style/tone control."))
    C.append(_e("chatterbox-self", "tts", "Chatterbox (your server)", "http_json",
                _env_model("CHATTERBOX_URL", ""), needs="CHATTERBOX_URL", quality=5,
                repo="https://github.com/resemble-ai/chatterbox",
                input_map={"text": "text", "audio_url": "audio_url", "speed": "speed"},
                response_kind="audio", notes="Resemble AI's open voice cloning model."))
    C.append(_e("kokoro-space", "tts", "Kokoro 82M (HF Space)", "gradio",
                _env_model("HF_KOKORO_SPACE", "hexgrad/Kokoro-82M"), free=True, quality=4,
                repo="https://github.com/hexgrad/kokoro", endpoint="/predict",
                data_template=["{text}", "{voice}", "{speed}"],
                notes="Tiny, fast, Apache-2.0 voice model. Override HF_KOKORO_SPACE if the Space moves."))
    C.append(_e("kokoro-self", "tts", "Kokoro (your server)", "http_json",
                _env_model("KOKORO_URL", ""), needs="KOKORO_URL", quality=4,
                repo="https://github.com/hexgrad/kokoro",
                input_map={"text": "text", "voice": "voice", "speed": "speed"}, response_kind="audio",
                notes="kokoro-fastapi style server."))
    C.append(_e("fish-speech-self", "tts", "fish-speech (your server)", "http_json",
                _env_model("FISH_SPEECH_URL", ""), needs="FISH_SPEECH_URL", quality=4,
                repo="https://github.com/fishaudio/fish-speech",
                input_map={"text": "text", "audio_url": "reference_audio"}, response_kind="audio",
                notes="OpenAudio S1 / fish-speech API server."))
    C.append(_e("chattts-space", "tts", "ChatTTS (HF Space)", "gradio",
                _env_model("HF_CHATTS_SPACE", ""), needs="HF_CHATTS_SPACE", quality=4,
                repo="https://github.com/2noise/ChatTTS",
                notes="Conversational Chinese/English TTS. Set HF_CHATTS_SPACE to a Space id."))
    C.append(_e("coqui-xtts", "tts", "Coqui XTTS v2 (Replicate)", "replicate",
                _env_model("REPLICATE_XTTS_MODEL", "coqui/xtts"), needs="REPLICATE_API_TOKEN", quality=4,
                repo="https://github.com/coqui-ai/TTS",
                input_map={"text": "text", "language": "language", "audio_url": "speaker"},
                notes="17 languages, 6s voice clone."))
    C.append(_e("coqui-self", "tts", "Coqui TTS (your server)", "http_json",
                _env_model("COQUI_URL", ""), needs="COQUI_URL", quality=4,
                repo="https://github.com/coqui-ai/TTS",
                input_map={"text": "text", "voice": "speaker_wav", "language": "language"},
                response_kind="audio", notes="TTS server (--model_name tts_models/... --port 5002)."))
    C.append(_e("qwen3-tts-self", "tts", "Qwen3-TTS (your server)", "http_json",
                _env_model("QWEN_TTS_URL", ""), needs="QWEN_TTS_URL", quality=5,
                repo="https://github.com/QwenLM/Qwen3-TTS",
                input_map={"text": "text", "voice": "voice", "language": "language"}, response_kind="audio",
                notes="Qwen3-TTS serving endpoint."))
    C.append(_e("openai-tts", "tts", "OpenAI gpt-4o-mini-tts", "openai",
                _env_model("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"), needs="OPENAI_API_KEY", quality=5, sync=True,
                repo="https://github.com/openai/openai-python",
                notes="Latest OpenAI voice model; accepts style instructions."))
    C.append(_e("gemini-tts", "tts", "Gemini TTS", "gemini",
                _env_model("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts"), needs="GEMINI_API_KEY",
                quality=4, sync=True, repo="https://github.com/googleapis/python-genai",
                notes="Multilingual and expressive; free tier applies."))
    C.append(_e("elevenlabs", "tts", "ElevenLabs Multilingual v2", "elevenlabs",
                _env_model("ELEVENLABS_MODEL", "eleven_multilingual_v2"), needs="ELEVENLABS_API_KEY",
                quality=5, sync=True, repo="https://github.com/elevenlabs/elevenlabs-python",
                notes="Best expressiveness; v2 covers Urdu and Hindi."))

    # =============================== IMAGE ================================ #
    C.append(_e("pollinations-flux", "image", "FLUX via Pollinations (free)", "pollinations",
                _env_model("POLLINATIONS_IMAGE_MODEL", "flux"), free=True, quality=4, sync=True,
                repo="https://github.com/black-forest-labs/flux",
                notes="Free, no key. Models: flux, flux-realism, flux-anime, flux-3d, any-dark, turbo."))
    C.append(_e("gpt-image-1", "image", "GPT Image 1 (latest ChatGPT image model)", "openai",
                _env_model("OPENAI_IMAGE_MODEL", "gpt-image-1"), needs="OPENAI_API_KEY", quality=5, sync=True,
                repo="https://github.com/openai/openai-python",
                notes="Best text rendering and prompt adherence - ideal for thumbnails with words on them."))
    C.append(_e("nano-banana", "image", "Gemini 2.5 Flash Image (Nano Banana)", "gemini",
                _env_model("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"), needs="GEMINI_API_KEY", quality=5,
                sync=True, repo="https://github.com/HKUDS/ViMax",
                notes="The image model ViMax uses for character portraits and storyboard keyframes."))
    C.append(_e("fal-flux-pro", "image", "FLUX 1.1 Pro (fal.ai)", "fal",
                _env_model("FAL_IMAGE_MODEL", "fal-ai/flux-pro/v1.1"), needs="FAL_KEY", quality=5,
                repo="https://github.com/black-forest-labs/flux",
                input_map={"prompt": "prompt", "negative_prompt": "negative_prompt", "seed": "seed"},
                notes="Photoreal keyframes; add fal-ai/flux-pro/v1.1-ultra for max quality."))
    C.append(_e("replicate-flux", "image", "FLUX 1.1 Pro (Replicate)", "replicate",
                _env_model("REPLICATE_IMAGE_MODEL", "black-forest-labs/flux-1.1-pro"),
                needs="REPLICATE_API_TOKEN", quality=5,
                repo="https://github.com/black-forest-labs/flux",
                input_map={"prompt": "prompt", "aspect_ratio": "aspect_ratio", "seed": "seed"},
                notes="Any Replicate image slug works: sdxl, ideogram-v2, flux-schnell, recraft-v3."))
    C.append(_e("hf-flux-schnell", "image", "FLUX.1 schnell (HF Inference)", "hf",
                _env_model("HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell"), needs="HF_TOKEN",
                quality=4, sync=True, repo="https://github.com/huggingface/diffusers",
                notes="Open-weights FLUX through the diffusers Inference API; free tier with a token."))
    C.append(_e("fal-sd", "image", "Stable Diffusion (fal.ai)", "fal",
                _env_model("FAL_SD_MODEL", "fal-ai/stable-diffusion"), needs="FAL_KEY", quality=3,
                repo="https://github.com/CompVis/stable-diffusion",
                input_map={"prompt": "prompt", "negative_prompt": "negative_prompt", "seed": "seed"},
                notes="The original SD family, cheap and fast."))
    C.append(_e("comfyui", "image", "ComfyUI (your workflow server)", "comfyui",
                _env_model("COMFYUI_URL", ""), needs="COMFYUI_URL", quality=5,
                repo="https://github.com/comfyanonymous/ComfyUI",
                notes="Full ComfyUI: queues your workflow JSON, polls /history, fetches /view output. "
                      "Workflow comes from COMFYUI_WORKFLOW (vault or env) or the request body; ControlNet, "
                      "IPAdapter, AnimateDiff and video workflows all work because it is your graph."))
    C.append(_e("sdwebui", "image", "Stable Diffusion WebUI A1111 (your server)", "sdwebui",
                _env_model("SD_WEBUI_URL", ""), needs="SD_WEBUI_URL", quality=4,
                repo="https://github.com/AUTOMATIC1111/stable-diffusion-webui",
                notes="Uses /sdapi/v1/txt2img (or /img2img with an input image). ControlNet and extensions "
                      "are available through the alwayson_scripts parameter."))
    C.append(_e("invokeai", "image", "InvokeAI (your server)", "http_json",
                _env_model("INVOKEAI_URL", ""), needs="INVOKEAI_URL", quality=4,
                repo="https://github.com/invoke-ai/InvokeAI",
                input_map={"prompt": "prompt", "negative_prompt": "negative_prompt", "width": "width",
                           "height": "height", "seed": "seed"},
                notes="Point at your InvokeAI REST endpoint; set response_path in params if it differs."))
    C.append(_e("fooocus", "image", "Fooocus (your server)", "http_json",
                _env_model("FOOOCUS_URL", ""), needs="FOOOCUS_URL", quality=4,
                repo="https://github.com/lllyasviel/Fooocus",
                input_map={"prompt": "prompt", "negative_prompt": "negative_prompt", "seed": "seed"},
                notes="Fooocus-API /v1/gen style server."))
    C.append(_e("fastsd-cpu", "image", "FastSD CPU (your server)", "http_json",
                _env_model("FASTSD_URL", ""), needs="FASTSD_URL", quality=2,
                repo="https://github.com/rupeshs/fastsdcpu",
                input_map={"prompt": "prompt", "negative_prompt": "negative_prompt", "seed": "seed",
                           "width": "width", "height": "height"},
                notes="CPU-only Stable Diffusion / LCM - slow but free if you have a spare machine."))

    # ============================ IMAGE EDIT ============================== #
    C.append(_e("gpt-image-edit", "image_edit", "GPT Image 1 edit (inpaint/rewrite)", "openai",
                _env_model("OPENAI_IMAGE_MODEL", "gpt-image-1"), needs="OPENAI_API_KEY", quality=5, sync=True,
                repo="https://github.com/openai/openai-python",
                notes="Send an image plus an instruction; best-in-class edits and text fixes."))
    C.append(_e("gemini-image-edit", "image_edit", "Gemini image edit", "gemini",
                _env_model("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"), needs="GEMINI_API_KEY", quality=5,
                sync=True, repo="https://github.com/googleapis/python-genai",
                notes="Multi-image composition and consistent character edits."))
    C.append(_e("controlnet-sdwebui", "image_edit", "ControlNet via your SD-WebUI", "sdwebui",
                _env_model("SD_WEBUI_URL", ""), needs="SD_WEBUI_URL", quality=4,
                repo="https://github.com/lllyasviel/ControlNet",
                extra={"alwayson_scripts": {"controlnet": {"args": [{"module": "canny", "weight": 0.8}]}}},
                notes="Pose/canny/depth guided edits. Adjust the ControlNet args in params per request."))
    C.append(_e("comfyui-edit", "image_edit", "ComfyUI edit workflow", "comfyui",
                _env_model("COMFYUI_URL", ""), needs="COMFYUI_URL", quality=5,
                repo="https://github.com/comfyanonymous/ComfyUI",
                notes="Any edit graph you can build in ComfyUI: IPAdapter faces, ControlNet, inpaint, upscale."))
    C.append(_e("replicate-edit", "image_edit", "InstructPix2Pix (Replicate)", "replicate",
                _env_model("REPLICATE_EDIT_MODEL", "timothybrooks/instruct-pix2pix"),
                needs="REPLICATE_API_TOKEN", quality=3, repo="https://github.com/timothybrooks/instruct-pix2pix",
                input_map={"prompt": "prompt", "image_url": "image"},
                notes="Instruction-based editing of an existing image."))

    # ============================== UPSCALE =============================== #
    C.append(_e("replicate-esrgan", "upscale", "Real-ESRGAN (Replicate)", "replicate",
                _env_model("REPLICATE_UPSCALE_MODEL", "nightmareai/real-esrgan"),
                needs="REPLICATE_API_TOKEN", quality=5, repo="https://github.com/xinntao/Real-ESRGAN",
                input_map={"image_url": "image", "params": ""},
                notes="4x upscaling for thumbnails and keyframes."))
    C.append(_e("fal-esrgan", "upscale", "Real-ESRGAN (fal.ai)", "fal",
                _env_model("FAL_UPSCALE_MODEL", "fal-ai/esrgan"), needs="FAL_KEY", quality=5,
                repo="https://github.com/xinntao/Real-ESRGAN", input_map={"image_url": "image_url"},
                notes="Fast upscale; also fal-ai/claude-upscale style models if you prefer."))
    C.append(_e("realesrgan-self", "upscale", "Real-ESRGAN (your server)", "http_json",
                _env_model("REALESRGAN_URL", ""), needs="REALESRGAN_URL", quality=5,
                repo="https://github.com/xinntao/Real-ESRGAN", input_map={"image_url": "image_url"},
                response_kind="image", notes="Your own realesrgan-ncnn / inference_realesrgan service."))

    # =============================== VIDEO ================================ #
    C.append(_e("veo-3", "video", "Google Veo 3 (native audio)", "gemini",
                _env_model("GEMINI_VIDEO_MODEL", "veo-3.0-generate-001"), needs="GEMINI_API_KEY", quality=5,
                repo="https://github.com/HKUDS/ViMax",
                input_map={"prompt": "prompt", "aspect_ratio": "aspect_ratio", "duration": "duration",
                           "negative_prompt": "negative_prompt", "image_url": "image"},
                notes="The model ViMax's VideoGeneratorVeoGoogleAPI uses. 8s clips with audio. "
                      "Long-running operation - this returns a job you poll."))
    C.append(_e("fal-veo3", "video", "Veo 3 (fal.ai)", "fal",
                _env_model("FAL_VEO_MODEL", "fal-ai/veo3"), needs="FAL_KEY", quality=5,
                repo="https://github.com/HKUDS/ViMax",
                input_map={"prompt": "prompt", "aspect_ratio": "aspect_ratio", "duration": "duration",
                           "image_url": "image_url"},
                notes="Same model, simpler billing. fal-ai/veo3/fast for cheap drafts."))
    C.append(_e("fal-seedance", "video", "Seedance 1 Pro", "fal",
                _env_model("FAL_SEEDANCE_MODEL", "fal-ai/seedance/v1/pro"), needs="FAL_KEY", quality=4,
                repo="https://github.com/HKUDS/ViMax",
                input_map={"prompt": "prompt", "aspect_ratio": "aspect_ratio", "image_url": "image_url"},
                notes="Fast, cheap, strong motion - ViMax's OpenRouter news mentions Seedance 2.0 too."))
    C.append(_e("replicate-wan", "video", "Wan 2.2 T2V A14B (open source)", "replicate",
                _env_model("REPLICATE_VIDEO_MODEL", "wan-video/wan-2.2-t2v-a14b"),
                needs="REPLICATE_API_TOKEN", quality=4, repo="https://github.com/Wan-Video/Wan2.2",
                input_map={"prompt": "prompt", "aspect_ratio": "aspect_ratio", "image_url": "image"},
                notes="Alibaba's open-weights Wan 2.2, hosted."))
    C.append(_e("fal-wan", "video", "Wan 2.2 5B (fal.ai)", "fal",
                _env_model("FAL_WAN_MODEL", "fal-ai/wan/v2.2/5b"), needs="FAL_KEY", quality=4,
                repo="https://github.com/Wan-Video/Wan2.2",
                input_map={"prompt": "prompt", "aspect_ratio": "aspect_ratio", "image_url": "image_url"},
                notes="Smaller, faster Wan variant - good for animatics."))
    C.append(_e("fal-hunyuan", "video", "Hunyuan Video (open source)", "fal",
                _env_model("FAL_HUNYUAN_MODEL", "fal-ai/hunyuan-video"), needs="FAL_KEY", quality=4,
                repo="https://github.com/Tencent/HunyuanVideo",
                input_map={"prompt": "prompt", "aspect_ratio": "aspect_ratio"},
                notes="Tencent's open-weights video model."))
    C.append(_e("fal-minimax", "video", "MiniMax Hailuo video", "fal",
                _env_model("FAL_MINIMAX_MODEL", "fal-ai/minimax/video-01"), needs="FAL_KEY", quality=4,
                repo="https://github.com/HKUDS/ViMax",
                input_map={"prompt": "prompt", "image_url": "first_frame"},
                notes="MiniMax is one of ViMax's supported providers."))
    C.append(_e("fal-ltx", "video", "LTX Video (fast drafts)", "fal",
                _env_model("FAL_LTX_MODEL", "fal-ai/ltx-video"), needs="FAL_KEY", quality=3,
                repo="https://github.com/Lightricks/LTX-Video",
                input_map={"prompt": "prompt", "aspect_ratio": "aspect_ratio"},
                notes="Very fast - use it to preview a whole ViMax storyboard before spending on Veo."))
    C.append(_e("replicate-helios", "video", "Helios (long video)", "replicate",
                _env_model("REPLICATE_HELIOS_MODEL", ""), needs="REPLICATE_HELIOS_MODEL", quality=4,
                repo="https://github.com/PKU-YuanGroup/Helios",
                input_map={"prompt": "prompt"},
                notes="PKU Helios streaming long-video model. Set REPLICATE_HELIOS_MODEL to the hosted slug "
                      "(or run it on your own GPU and use a self-hosted entry)."))
    C.append(_e("replicate-svi", "video", "Stable Video Infinity", "replicate",
                _env_model("REPLICATE_SVI_MODEL", ""), needs="REPLICATE_SVI_MODEL", quality=4,
                repo="https://github.com/vita-epfl/Stable-Video-Infinity",
                input_map={"prompt": "prompt", "image_url": "input_image"},
                notes="Minute-scale video from image+prompt. Set REPLICATE_SVI_MODEL to a hosted slug."))
    C.append(_e("comfyui-video", "video", "ComfyUI video workflow (AnimateDiff/Wan)", "comfyui",
                _env_model("COMFYUI_URL", ""), needs="COMFYUI_URL", quality=5,
                repo="https://github.com/comfyanonymous/ComfyUI",
                notes="Your own AnimateDiff / Wan / Hunyuan graph on your GPU box. Full control, no per-clip "
                      "API cost beyond your machine."))

    # =============================== AVATAR =============================== #
    C.append(_e("fal-echomimic", "avatar", "EchoMimic v3 (talking avatar)", "fal",
                _env_model("FAL_ECHOMIMIC_MODEL", "fal-ai/echomimic/v3"), needs="FAL_KEY", quality=5,
                repo="https://github.com/BadToBest/EchoMimic",
                input_map={"image_url": "image_url", "audio_url": "audio_url", "prompt": "prompt"},
                notes="Half-body talking avatar with gestures from one photo + one voice track."))
    C.append(_e("fal-liveportrait", "avatar", "LivePortrait (face animation)", "fal",
                _env_model("FAL_LIVEPORTRAIT_MODEL", "fal-ai/liveportrait"), needs="FAL_KEY", quality=4,
                repo="https://github.com/KlingAI/LivePortrait",
                input_map={"image_url": "image_url", "video_url": "driving_video"},
                notes="Kling's portrait animator - drive a photo with a video or expression."))
    C.append(_e("replicate-sadtalker", "avatar", "SadTalker (Replicate)", "replicate",
                _env_model("REPLICATE_SADTALKER_MODEL", "camenduru/sadtalker"),
                needs="REPLICATE_API_TOKEN", quality=4, repo="https://github.com/OpenTalker/SadTalker",
                input_map={"image_url": "source_image", "audio_url": "driven_audio"},
                notes="Photo + audio -> talking head. Set REPLICATE_SADTALKER_MODEL to the slug you can run; "
                      "input key names are overridable with SADTALKER_INPUT_IMAGE / SADTALKER_INPUT_AUDIO."))
    C.append(_e("fal-sadtalker", "avatar", "SadTalker (fal.ai)", "fal",
                _env_model("FAL_SADTALKER_MODEL", "fal-ai/sadtalker"), needs="FAL_KEY", quality=4,
                repo="https://github.com/OpenTalker/SadTalker",
                input_map={"image_url": "image_url", "audio_url": "audio_url"},
                notes="Same model on fal if you already have a fal key."))
    C.append(_e("sadtalker-self", "avatar", "SadTalker (your server)", "http_json",
                _env_model("SADTALKER_URL", ""), needs="SADTALKER_URL", quality=4,
                repo="https://github.com/OpenTalker/SadTalker",
                input_map={"image_url": "source_image", "audio_url": "driven_audio"}, response_kind="video",
                notes="Your own SadTalker (RunPod/Vast). Returns mp4 bytes, base64 or a URL."))
    C.append(_e("musetalk-self", "avatar", "MuseTalk (your server)", "http_json",
                _env_model("MUSETALK_URL", ""), needs="MUSETALK_URL", quality=4,
                repo="https://github.com/TMElyralab/MuseTalk",
                input_map={"video_url": "video_path", "audio_url": "audio_path"}, response_kind="video",
                notes="Tencent's real-time lip-sync; give it a video and a voice track."))
    C.append(_e("replicate-wav2lip", "avatar", "Wav2Lip (lip sync)", "replicate",
                _env_model("REPLICATE_WAV2LIP_MODEL", "devansh04/wav2lip"), needs="REPLICATE_API_TOKEN",
                quality=3, repo="https://github.com/Rudrabha/Wav2Lip",
                input_map={"video_url": "video", "audio_url": "audio"},
                notes="Lip-syncs an existing video to a new voice track."))
    C.append(_e("livetalking-self", "avatar", "LiveTalking (real-time avatar)", "http_json",
                _env_model("LIVETALKING_URL", ""), needs="LIVETALKING_URL", quality=5,
                repo="https://github.com/lipku/LiveTalking",
                input_map={"text": "text"}, response_kind="json",
                notes="Real-time interactive avatar. This starts/queues a session on your server and returns "
                      "its WebRTC/HLS URL for the browser to play - see doc.livetalking.ai/en/docs/usage."))

    # ============================ TRANSCRIBE ============================== #
    C.append(_e("groq-whisper", "transcribe", "Whisper large v3 turbo (Groq)", "openai_compat",
                _env_model("GROQ_TRANSCRIBE_MODEL", "whisper-large-v3-turbo"), needs="GROQ_API_KEY", quality=5,
                repo="https://github.com/openai/whisper", base=GROQ_BASE,
                notes="Extremely fast transcription of your own audio/video files - the fastest way to get a "
                      "transcript into /yt-edit and /yt-chapters."))
    C.append(_e("openai-whisper", "transcribe", "Whisper (OpenAI)", "openai",
                _env_model("OPENAI_TRANSCRIBE_MODEL", "whisper-1"), needs="OPENAI_API_KEY", quality=5, sync=True,
                repo="https://github.com/openai/whisper", notes="Multilingual, timestamps with verbose_json."))
    C.append(_e("replicate-whisper", "transcribe", "Whisper (Replicate)", "replicate",
                _env_model("REPLICATE_WHISPER_MODEL", "openai/whisper"), needs="REPLICATE_API_TOKEN", quality=5,
                repo="https://github.com/openai/whisper", input_map={"audio_url": "audio"},
                notes="Transcribe from a public URL."))
    C.append(_e("hf-whisper-space", "transcribe", "Whisper (HF Space, free)", "gradio",
                _env_model("HF_WHISPER_SPACE", ""), needs="HF_WHISPER_SPACE", quality=4,
                repo="https://github.com/openai/whisper",
                notes="Any Whisper Gradio Space: set HF_WHISPER_SPACE (e.g. openai/whisper) and the endpoint."))

    # =============================== RENDER =============================== #
    C.append(_e("timeline-local", "render", "Timeline / EDL builder (built in)", "none", "", free=True,
                quality=3, sync=True, repo="https://github.com/Zulko/moviepy",
                notes="Turns a ViMax storyboard or a /yt-edit EDL into a render-ready JSON timeline "
                      "(shots, captions, audio cues, transitions) that moviepy / Remotion / FFmpeg / "
                      "OpenMontage can consume. No GPU needed, always available."))
    C.append(_e("render-service", "render", "Your render farm (FFmpeg/moviepy/Remotion)", "http_json",
                _env_model("RENDER_SERVICE_URL", ""), needs="RENDER_SERVICE_URL", quality=5,
                repo="https://github.com/FFmpeg/FFmpeg", response_kind="video",
                notes="POST the timeline JSON to your own FFmpeg/moviepy/Remotion/OpenMontage service and get "
                      "an mp4 URL back. This is how real stitching happens without a GPU on Vercel."))
    return C


def _env_model(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip()


CATALOG: List[Dict[str, Any]] = _catalog()

DEFAULT_ORDER: Dict[str, List[str]] = {
    "chat": ["openai-chat", "gemini-chat", "claude-chat", "openrouter-any", "groq-llama",
             "litellm-proxy", "llm-gateway", "yolorouter", "pollinations-text"],
    "tts": ["f5-tts-space", "openai-tts", "elevenlabs", "gemini-tts", "gpt-sovits-space",
            "kokoro-space", "f5-tts-self", "f5-tts-replicate", "edge-tts"],
    "image": ["gpt-image-1", "nano-banana", "comfyui", "fal-flux-pro", "replicate-flux", "sdwebui",
              "hf-flux-schnell", "invokeai", "fooocus", "fal-sd", "pollinations-flux", "fastsd-cpu"],
    "image_edit": ["gpt-image-edit", "gemini-image-edit", "comfyui-edit", "controlnet-sdwebui",
                   "replicate-edit"],
    "upscale": ["replicate-esrgan", "fal-esrgan", "realesrgan-self"],
    "video": ["veo-3", "fal-veo3", "fal-seedance", "comfyui-video", "replicate-wan", "fal-wan",
              "fal-hunyuan", "fal-minimax", "replicate-svi", "replicate-helios", "fal-ltx"],
    "avatar": ["fal-echomimic", "livetalking-self", "replicate-sadtalker", "fal-liveportrait",
               "fal-sadtalker", "musetalk-self", "sadtalker-self", "replicate-wav2lip"],
    "transcribe": ["groq-whisper", "openai-whisper", "replicate-whisper", "hf-whisper-space"],
    "render": ["timeline-local", "render-service"],
}


def is_configured(entry: Dict[str, Any], keys: Optional[Dict[str, str]] = None) -> bool:
    if entry.get("free"):
        return True
    needs = entry.get("needs")
    if not needs:
        return False
    value = _k(needs, keys)
    if value:
        return True
    # a self-hosted entry can also be configured through its URL/model env alone
    return bool(entry.get("model")) and entry["backend"] in ("gradio", "comfyui", "sdwebui", "http_json")


def public_entry(entry: Dict[str, Any], keys: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    configured = is_configured(entry, keys)
    return {
        "id": entry["id"], "capability": entry["capability"], "label": entry["label"],
        "backend": entry["backend"], "model": entry["model"] or "(set in vault/env)",
        "free": bool(entry.get("free")), "quality": entry.get("quality", 3),
        "sync": bool(entry.get("sync")), "configured": configured, "needs": entry.get("needs"),
        "repo": entry.get("repo", ""), "notes": entry.get("notes", ""),
        "missing": None if configured else entry.get("needs"),
    }


def catalog(capability: Optional[str] = None, keys: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    caps = [c.strip().lower() for c in capability.split(",")] if capability else list(CAPABILITIES)
    out: List[Dict[str, Any]] = []
    for cap in caps:
        entries = [e for e in CATALOG if e["capability"] == cap]
        order = DEFAULT_ORDER.get(cap, [])
        entries.sort(key=lambda e: (0 if is_configured(e, keys) else 1,
                                    order.index(e["id"]) if e["id"] in order else 99,
                                    -e.get("quality", 0)))
        out.extend(public_entry(e, keys) for e in entries)
    return out


def by_id(entry_id: str) -> Optional[Dict[str, Any]]:
    entry_id = (entry_id or "").strip()
    for entry in CATALOG:
        if entry["id"] == entry_id:
            return entry
    return None


def default_id(capability: str, keys: Optional[Dict[str, str]] = None) -> str:
    for entry_id in DEFAULT_ORDER.get(capability, []):
        entry = by_id(entry_id)
        if entry and is_configured(entry, keys):
            return entry_id
    for entry_id in DEFAULT_ORDER.get(capability, []):
        entry = by_id(entry_id)
        if entry and entry.get("free"):
            return entry_id
    free = [e for e in CATALOG if e["capability"] == capability and e.get("free")]
    return free[0]["id"] if free else ""


def resolve(capability: str, wanted: Optional[str] = None,
            keys: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Find an entry by id, backend, repo name or model slug; else the best usable default."""
    wanted = (wanted or "").strip()
    if not wanted:
        entry = by_id(default_id(capability, keys))
        if not entry:
            raise ProviderError(f"No models are registered for '{capability}'.", status_code=501)
        return entry

    lowered = wanted.lower().rstrip("/")
    tail = lowered.split("/")[-1]
    for entry in CATALOG:
        if entry["capability"] != capability:
            continue
        haystacks = (entry["id"].lower(), entry["backend"].lower(), (entry["model"] or "").lower(),
                     (entry.get("repo") or "").lower())
        if lowered in haystacks or any(tail and tail in h for h in haystacks):
            return entry
    for entry in CATALOG:
        if entry["capability"] == capability and (tail in entry["id"].lower()
                                                  or tail in (entry["label"] or "").lower()):
            return entry
    raise ProviderError(
        f"Unknown {capability} model '{wanted}'.", status_code=400,
        hint="Available: " + ", ".join(e["id"] for e in CATALOG if e["capability"] == capability))


def require_configured(entry: Dict[str, Any], keys: Optional[Dict[str, str]] = None) -> None:
    if is_configured(entry, keys):
        return
    needs = entry.get("needs") or "a key"
    raise ProviderError(
        f"{entry['label']} is not configured.", status_code=503,
        hint=f"Add {needs} in Settings -> AI Keys (stored for your account) or as a Vercel environment "
             f"variable, or pick a free model such as '{default_id(entry['capability'], keys)}'. "
             f"Repo: {entry.get('repo')}")


def provider_status(keys: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    per_cap: Dict[str, Any] = {}
    for cap in CAPABILITIES:
        entries = [e for e in CATALOG if e["capability"] == cap]
        ready = [e["id"] for e in entries if is_configured(e, keys)]
        per_cap[cap] = {"ready": ready, "default": ready[0] if ready else "", "total": len(entries),
                        "best_quality": max((e.get("quality", 0) for e in entries
                                             if is_configured(e, keys)), default=0)}
    missing = sorted({e["needs"] for e in CATALOG if e.get("needs") and not is_configured(e, keys)})
    return {"capabilities": per_cap, "missing": missing,
            "free_ready": [e["id"] for e in CATALOG if e.get("free")],
            "total_models": len(CATALOG),
            "repos": sorted({e["repo"] for e in CATALOG if e.get("repo")})}


# --------------------------------------------------------------------------- #
# http helpers
# --------------------------------------------------------------------------- #

def _client(timeout: float = 120.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=25.0), follow_redirects=True,
                             headers={"User-Agent": "bg-labs-backend/3.0"})


def _b64decode(value: str) -> bytes:
    cleaned = re.sub(r"\s", "", value or "")
    if cleaned.lower().startswith("data:") and "," in cleaned[:128]:
        cleaned = cleaned.split(",", 1)[1]
    try:
        return base64.b64decode(cleaned + "=" * (-len(cleaned) % 4))
    except Exception as exc:
        raise ProviderError(f"Could not decode base64 payload ({exc}).", status_code=502)


def to_data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _mime_for(kind: str) -> str:
    return {"image": "image/png", "audio": "audio/mpeg", "video": "video/mp4",
            "text": "text/plain", "json": "application/json"}.get(kind, "application/octet-stream")


async def _download(url: str, headers: Optional[Dict[str, str]] = None) -> Tuple[bytes, str]:
    async with _client(240.0) as client:
        response = await client.get(url, headers=headers or {})
    if response.status_code >= 400:
        raise ProviderError(f"Downloading the generated file failed (HTTP {response.status_code}).",
                            status_code=502, hint=url[:200])
    mime = (response.headers.get("content-type") or "").split(";")[0].strip() or "application/octet-stream"
    return response.content, mime


def _raise_for(response: httpx.Response, entry: Dict[str, Any], keys=None) -> None:
    if response.status_code < 400:
        return
    detail = (response.text or "")[:400]
    hint = None
    if response.status_code in (401, 403):
        hint = (f"The credential for {entry['label']} was rejected. Re-check "
                f"{entry.get('needs') or 'the key'} in Settings -> AI Keys.")
    elif response.status_code == 404:
        hint = (f"Model/endpoint '{entry.get('model') or entry.get('base')}' was not found on "
                f"{entry['backend']}. Point the matching env/vault value at something you have access to. "
                f"Repo: {entry.get('repo')}")
    elif response.status_code == 429:
        hint = "Rate limit or quota reached - try another model or wait a minute."
    elif response.status_code >= 500:
        hint = f"The upstream service is failing. Repo/docs: {entry.get('repo')}"
    raise ProviderError(f"{entry['label']} failed (HTTP {response.status_code}): {detail}",
                        status_code=502, hint=hint)


def _flatten_urls(output: Any) -> List[str]:
    urls: List[str] = []
    stack = [output]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if item.startswith(("http://", "https://")):
                urls.append(item)
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    seen, ordered = set(), []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def _dig(payload: Any, path: str) -> Any:
    """Fetch ``a.b.0.c`` out of a nested structure."""
    if not path:
        return payload
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    return current


def _extract_file(payload: Any, kind: str = "") -> Optional[Dict[str, Any]]:
    """Find a media reference (base64 or URL) anywhere in a provider payload."""
    exts = {"image": r"\.(png|jpg|jpeg|webp|gif)", "audio": r"\.(mp3|wav|ogg|m4a|flac|opus)",
            "video": r"\.(mp4|webm|mov|mkv)"}
    pattern = exts.get(kind, r"\.(mp4|webm|mov|png|jpg|jpeg|mp3|wav|m4a|flac|gif)")
    b64_keys = ("b64_json", "image", "images", "audio", "video", "data", "output", "result", "base64")
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key in ("url", "uri", "video", "audio", "image", "file", "output", "src", "href"):
                value = item.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://", "data:", "/")):
                    return {"url": value, "mime": item.get("mime_type") or item.get("mimeType") or ""}
            if isinstance(item.get("path"), str) and item["path"]:
                return {"url": item["path"], "mime": item.get("mime_type") or ""}
            for key in b64_keys:
                value = item.get(key)
                if isinstance(value, str) and len(value) > 512 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", value[:200]):
                    return {"b64": value, "mime": item.get("mime_type") or ""}
                if isinstance(value, list) and value and isinstance(value[0], str) and len(value[0]) > 512:
                    return {"b64": value[0], "mime": item.get("mime_type") or ""}
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str):
            if item.startswith(("http://", "https://")) and re.search(pattern + r"(\?|$)", item, re.I):
                return {"url": item, "mime": ""}
            if len(item) > 512 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", item[:200]):
                return {"b64": item, "mime": ""}
    return None


# --------------------------------------------------------------------------- #
# canonical request -> provider payload
# --------------------------------------------------------------------------- #

CANONICAL_FIELDS = ("text", "prompt", "image_url", "audio_url", "video_url", "negative_prompt",
                    "width", "height", "aspect_ratio", "duration", "voice", "speed", "seed",
                    "ref_text", "language", "steps", "guidance")


def normalize_request(req: Dict[str, Any]) -> Dict[str, Any]:
    """Accept loose input from the UI and produce canonical fields."""
    # Preserve capability-specific fields (shots/EDL/workflow/messages/etc.).
    # Canonical fields are normalised below, but dropping unknown fields would
    # silently erase timeline and custom self-hosted model inputs.
    out: Dict[str, Any] = dict(req or {})
    for field in CANONICAL_FIELDS:
        value = req.get(field)
        if isinstance(value, str):
            value = value.strip()
        if value not in (None, "", [], {}):
            out[field] = value
    if "prompt" not in out and "text" in out:
        out["prompt"] = out["text"]
    if "text" not in out and "prompt" in out:
        out["text"] = out["prompt"]
    params = req.get("params") or {}
    if isinstance(params, dict):
        out["params"] = params
        for field in CANONICAL_FIELDS:
            if field not in out and params.get(field) not in (None, ""):
                out[field] = params[field]
    return out


def build_input(entry: Dict[str, Any], req: Dict[str, Any],
                keys: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Map canonical fields onto the provider's own input key names."""
    payload: Dict[str, Any] = dict(entry.get("extra") or {})
    prefix = entry["id"].upper().replace("-", "_")
    for canonical, target in (entry.get("input_map") or {}).items():
        value = req.get(canonical)
        if value in (None, "", [], {}):
            continue
        if canonical == "params" or not target:
            continue
        payload[target] = value
    if not entry.get("input_map"):
        for field in CANONICAL_FIELDS:
            if field in ("text", "params") or field not in req:
                continue
            payload[field] = req[field]
        if "text" in req and "prompt" not in payload:
            payload["prompt"] = req["text"]
    # per-entry input key overrides, e.g. SADTALKER_INPUT_IMAGE=photo
    for key in list(payload):
        override = _k(f"{prefix}_INPUT_{key.upper()}", keys)
        if override and override != key:
            payload[override] = payload.pop(key)
    payload.update(req.get("params") or {})
    return {k: v for k, v in payload.items() if v not in (None, "", [], {})}


def render_data_template(entry: Dict[str, Any], req: Dict[str, Any],
                         keys: Optional[Dict[str, str]] = None) -> List[Any]:
    """Build the positional array a Gradio Space expects."""
    override = _k("HF_F5_TTS_DATA", keys) if entry["id"] == "f5-tts-space" else ""
    template: Any = None
    if override:
        try:
            template = json.loads(override)
        except json.JSONDecodeError as exc:
            raise ProviderError("HF_F5_TTS_DATA is not valid JSON.", status_code=500, hint=str(exc))
    if template is None:
        template = entry.get("data_template") or ["{text}"]

    def sub(value: Any) -> Any:
        if not isinstance(value, str) or "{" not in value:
            return value
        for field in list(CANONICAL_FIELDS) + ["ref_audio"]:
            token = "{" + field + "}"
            if token in value:
                source = req.get(field)
                if source is None and field == "ref_audio":
                    source = req.get("audio_url")
                value = value.replace(token, "" if source is None else str(source))
        return value

    return [sub(item) for item in template]


# --------------------------------------------------------------------------- #
# backends
# --------------------------------------------------------------------------- #

async def _b_edge(entry, req, keys) -> Dict[str, Any]:
    try:
        import edge_tts
    except ImportError as exc:
        raise ProviderError("edge-tts is not installed in this deployment.", status_code=503,
                            hint="Add edge-tts to requirements.txt (small, keyless).") from exc
    text = req.get("text") or req.get("prompt") or ""
    voice = req.get("voice") or entry["model"]
    speed = float(req.get("speed") or 1.0)
    rate = f"{int(round((speed - 1.0) * 100)):+d}%"
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    chunks = [c["data"] async for c in communicate.stream() if c.get("type") == "audio"]
    if not chunks:
        raise ProviderError("edge-tts returned no audio.", status_code=502)
    return {"bytes": b"".join(chunks), "mime": "audio/mpeg", "voice": voice}


async def _b_pollinations(entry, req, keys) -> Dict[str, Any]:
    from urllib.parse import quote
    text = (req.get("prompt") or req.get("text") or "").strip()
    if entry["capability"] == "chat" or not entry["capability"] == "image":
        model = entry["model"] or "openai"
        url = f"https://text.pollinations.ai/{quote(text)}?model={quote(model)}"
        token = _k("POLLINATIONS_TOKEN", keys)
        if token:
            url += f"&token={token}"
        async with _client(120.0) as client:
            response = await client.get(url)
        _raise_for(response, entry, keys)
        return {"text": response.text, "mime": "text/plain"}
    query = [f"model={entry['model']}", f"width={int(req.get('width') or 1024)}",
             f"height={int(req.get('height') or 1024)}", "nologo=true"]
    if req.get("seed"):
        query.append(f"seed={int(req['seed'])}")
    if req.get("negative_prompt"):
        query.append(f"negative_prompt={quote(str(req['negative_prompt']))}")
    token = _k("POLLINATIONS_TOKEN", keys)
    if token:
        query.append(f"token={token}")
    for key, value in (req.get("params") or {}).items():
        if key not in ("size", "quality"):
            query.append(f"{key}={quote(str(value))}")
    url = f"https://image.pollinations.ai/prompt/{quote(text)}?{'&'.join(query)}"
    async with _client(240.0) as client:
        response = await client.get(url)
    if response.status_code >= 400:
        raise ProviderError(f"Pollinations returned HTTP {response.status_code}.", status_code=502,
                            hint="Free public service; retry shortly or use gpt-image-1 / nano-banana.")
    if len(response.content) < 512:
        raise ProviderError("Pollinations returned an empty image (rate limited).", status_code=429,
                            hint="Wait ~30s, or add POLLINATIONS_TOKEN for higher limits.")
    mime = (response.headers.get("content-type") or "image/jpeg").split(";")[0]
    return {"bytes": response.content, "mime": mime, "url": url}


async def _b_openai(entry, req, keys) -> Dict[str, Any]:
    require_configured(entry, keys)
    api_key = _provider_key("openai", keys)
    base = (entry.get("base") or _k("OPENAI_BASE_URL", keys, OPENAI_BASE)).rstrip("/")
    cap = entry["capability"]

    if cap == "image":
        size = (req.get("params") or {}).get("size") or f"{req.get('width') or 1024}x{req.get('height') or 1024}"
        if size not in ("1024x1024", "1536x1024", "1024x1536", "auto"):
            size = "1024x1024"
        payload = {"model": entry["model"], "prompt": req.get("prompt") or req.get("text"), "size": size, "n": 1}
        if entry["model"] == "gpt-image-1":
            payload["quality"] = (req.get("params") or {}).get("quality", "high")
        else:
            payload["response_format"] = "b64_json"
        async with _client(240.0) as client:
            response = await client.post(f"{base}/images/generations",
                                         headers={"Authorization": f"Bearer {api_key}"}, json=payload)
        _raise_for(response, entry, keys)
        item = (response.json().get("data") or [{}])[0]
        if item.get("b64_json"):
            return {"bytes": _b64decode(item["b64_json"]), "mime": "image/png",
                    "revised_prompt": item.get("revised_prompt")}
        if item.get("url"):
            data, mime = await _download(item["url"])
            return {"bytes": data, "mime": mime, "revised_prompt": item.get("revised_prompt")}
        raise ProviderError("OpenAI returned no image data.", status_code=502)

    if cap == "image_edit":
        image = req.get("image_url")
        if not image or not str(image).startswith("data:"):
            raise ProviderError("Send the image as a data URI (base64) for GPT image editing.",
                                status_code=400, hint="The UI uploads your image and passes it as a data URI.")
        mime, _, b64 = str(image).partition(";base64,")
        ext = "png" if "png" in mime else "jpg"
        files = {"image": (f"input.{ext}", _b64decode(b64), mime.split(":")[-1] or "image/png")}
        data = {"model": entry["model"], "prompt": req.get("prompt") or req.get("text") or "", "size": "1024x1024"}
        async with _client(240.0) as client:
            response = await client.post(f"{base}/images/edits",
                                         headers={"Authorization": f"Bearer {api_key}"}, data=data, files=files)
        _raise_for(response, entry, keys)
        item = (response.json().get("data") or [{}])[0]
        if item.get("b64_json"):
            return {"bytes": _b64decode(item["b64_json"]), "mime": "image/png"}
        if item.get("url"):
            data_bytes, mime_out = await _download(item["url"])
            return {"bytes": data_bytes, "mime": mime_out}
        raise ProviderError("OpenAI returned no edited image.", status_code=502)

    if cap == "tts":
        payload = {"model": entry["model"], "input": req.get("text") or req.get("prompt"),
                   "voice": req.get("voice") or "alloy", "response_format": "mp3",
                   "speed": float(req.get("speed") or 1.0)}
        style = (req.get("params") or {}).get("instructions") or (req.get("params") or {}).get("style")
        if style and entry["model"].startswith("gpt-4o"):
            payload["instructions"] = str(style)[:1500]
        async with _client(240.0) as client:
            response = await client.post(f"{base}/audio/speech",
                                         headers={"Authorization": f"Bearer {api_key}"}, json=payload)
        _raise_for(response, entry, keys)
        return {"bytes": response.content, "mime": "audio/mpeg", "voice": payload["voice"]}

    if cap == "transcribe":
        audio = req.get("audio_url")
        if not audio:
            raise ProviderError("An audio file is required.", status_code=400)
        if str(audio).startswith("data:"):
            mime, _, b64 = str(audio).partition(";base64,")
            ext = "mp3" if "mpeg" in mime or "mp3" in mime else "wav"
            files = {"file": (f"audio.{ext}", _b64decode(b64), mime.split(":")[-1] or "audio/mpeg")}
        else:
            data_bytes, mime = await _download(str(audio))
            ext = "mp4" if "mp4" in mime else ("wav" if "wav" in mime else "mp3")
            files = {"file": (f"audio.{ext}", data_bytes, mime)}
        data = {"model": entry["model"], "response_format": (req.get("params") or {}).get("format", "verbose_json")}
        if req.get("language"):
            data["language"] = req["language"]
        async with _client(600.0) as client:
            response = await client.post(f"{base}/audio/transcriptions",
                                         headers={"Authorization": f"Bearer {api_key}"}, data=data, files=files)
        _raise_for(response, entry, keys)
        return {"json": response.json(), "mime": "application/json"}

    raise ProviderError(f"Backend 'openai' does not handle '{cap}'.", status_code=500)


async def _b_gemini(entry, req, keys) -> Dict[str, Any]:
    require_configured(entry, keys)
    api_key = _provider_key("gemini", keys)
    base = _k("GEMINI_BASE_URL", keys, GEMINI_BASE).rstrip("/")
    cap = entry["capability"]
    headers = {"x-goog-api-key": api_key}

    if cap == "chat":
        payload = {"contents": [{"role": "user", "parts": [{"text": req.get("text") or req.get("prompt")}]}]}
        system = (req.get("params") or {}).get("system")
        if system:
            payload["systemInstruction"] = {"parts": [{"text": str(system)}]}
        async with _client(180.0) as client:
            response = await client.post(f"{base}/v1beta/models/{entry['model']}:generateContent",
                                         headers=headers, json=payload)
        _raise_for(response, entry, keys)
        text = ""
        for candidate in response.json().get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                text += part.get("text") or ""
        return {"text": text, "mime": "text/plain"}

    if cap in ("image", "image_edit"):
        text = req.get("prompt") or req.get("text") or ""
        if req.get("negative_prompt"):
            text = f"{text}\n\nAvoid: {req['negative_prompt']}"
        parts: List[Dict[str, Any]] = [{"text": text}]
        if cap == "image_edit" and req.get("image_url"):
            image = str(req["image_url"])
            if image.startswith("data:"):
                mime, _, b64 = image.partition(";base64,")
                parts.insert(0, {"inlineData": {"mimeType": mime.split(":")[-1] or "image/png", "data": b64}})
            else:
                parts.insert(0, {"fileData": {"fileUri": image}})
        generation: Dict[str, Any] = {"responseModalities": ["IMAGE"]}
        aspect = req.get("aspect_ratio") or (req.get("params") or {}).get("aspect_ratio")
        if aspect:
            generation["imageConfig"] = {"aspectRatio": aspect}
        async with _client(240.0) as client:
            response = await client.post(f"{base}/v1beta/models/{entry['model']}:generateContent",
                                         headers=headers,
                                         json={"contents": [{"role": "user", "parts": parts}],
                                               "generationConfig": generation})
        _raise_for(response, entry, keys)
        for candidate in response.json().get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return {"bytes": _b64decode(inline["data"]),
                            "mime": inline.get("mimeType") or inline.get("mime_type") or "image/png"}
        raise ProviderError("Gemini produced no image.", status_code=502,
                            hint="Safety filters may have blocked it - rephrase the prompt.")

    if cap == "tts":
        payload = {"contents": [{"parts": [{"text": req.get("text") or req.get("prompt")}]}],
                   "generationConfig": {"responseModalities": ["AUDIO"],
                                        "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {
                                            "voiceName": req.get("voice") or "Kore"}}}}}
        async with _client(240.0) as client:
            response = await client.post(f"{base}/v1beta/models/{entry['model']}:generateContent",
                                         headers=headers, json=payload)
        _raise_for(response, entry, keys)
        for candidate in response.json().get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return {"bytes": _b64decode(inline["data"]),
                            "mime": inline.get("mimeType") or "audio/wav", "voice": req.get("voice") or "Kore"}
        raise ProviderError("Gemini returned no audio.", status_code=502)

    raise ProviderError(f"Backend 'gemini' does not handle '{cap}'.", status_code=500)


async def _b_anthropic(entry, req, keys) -> Dict[str, Any]:
    require_configured(entry, keys)
    api_key = _provider_key("anthropic", keys)
    base = _k("ANTHROPIC_BASE_URL", keys, "https://api.anthropic.com").rstrip("/")
    payload = {"model": entry["model"], "max_tokens": int((req.get("params") or {}).get("max_tokens", 4096)),
               "messages": [{"role": "user", "content": req.get("text") or req.get("prompt") or ""}]}
    system = (req.get("params") or {}).get("system")
    if system:
        payload["system"] = str(system)
    async with _client(240.0) as client:
        response = await client.post(f"{base}/v1/messages", headers={
            "x-api-key": api_key, "anthropic-version": "2023-06-01",
            "content-type": "application/json"}, json=payload)
    _raise_for(response, entry, keys)
    blocks = response.json().get("content") or []
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    return {"text": text, "mime": "text/plain"}


async def _b_elevenlabs(entry, req, keys) -> Dict[str, Any]:
    require_configured(entry, keys)
    api_key = _provider_key("elevenlabs", keys)
    voice_id = (req.get("params") or {}).get("voice_id") or _k("ELEVENLABS_VOICE_ID", keys,
                                                               "21m00Tcm4TlvDq8ikWAM")
    payload = {"text": req.get("text") or req.get("prompt") or "", "model_id": entry["model"],
               "voice_settings": {"stability": float((req.get("params") or {}).get("stability", 0.5)),
                                  "similarity_boost": float((req.get("params") or {}).get("similarity_boost", 0.75))}}
    async with _client(240.0) as client:
        response = await client.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                                     headers={"xi-api-key": api_key, "content-type": "application/json"},
                                     json=payload)
    _raise_for(response, entry, keys)
    return {"bytes": response.content, "mime": "audio/mpeg", "voice": voice_id}


async def _b_hf(entry, req, keys) -> Dict[str, Any]:
    require_configured(entry, keys)
    token = _provider_key("hf", keys)
    base = _k("HF_INFERENCE_URL", keys, HF_INFERENCE).rstrip("/")
    cap = entry["capability"]
    if cap in ("image", "image_edit"):
        payload: Dict[str, Any] = {"inputs": req.get("prompt") or req.get("text") or ""}
        parameters: Dict[str, Any] = {}
        if req.get("negative_prompt"):
            parameters["negative_prompt"] = req["negative_prompt"]
        if req.get("width") and req.get("height"):
            parameters.update({"width": int(req["width"]), "height": int(req["height"])})
        if req.get("seed"):
            parameters["seed"] = int(req["seed"])
        if parameters:
            payload["parameters"] = parameters
        async with _client(300.0) as client:
            response = await client.post(f"{base}/models/{entry['model']}",
                                         headers={"Authorization": f"Bearer {token}"}, json=payload)
        _raise_for(response, entry, keys)
        if "application/json" in (response.headers.get("content-type") or ""):
            raise ProviderError(f"HF Inference did not return an image: {response.text[:300]}", status_code=502,
                                hint="The model may be cold-starting - retry in ~20s.")
        return {"bytes": response.content,
                "mime": (response.headers.get("content-type") or "image/png").split(";")[0]}
    if cap == "transcribe":
        audio = req.get("audio_url")
        if not audio:
            raise ProviderError("An audio file is required.", status_code=400)
        data, mime = (None, "")
        if str(audio).startswith("data:"):
            _, _, b64 = str(audio).partition(";base64,")
            data = _b64decode(b64)
        else:
            data, mime = await _download(str(audio))
        async with _client(600.0) as client:
            response = await client.post(f"{base}/models/{entry['model']}",
                                         headers={"Authorization": f"Bearer {token}"},
                                         json={"inputs": base64.b64encode(data).decode()})
        _raise_for(response, entry, keys)
        return {"json": response.json(), "mime": "application/json"}
    raise ProviderError(f"Backend 'hf' does not handle '{cap}'.", status_code=500)


async def _b_openai_compat(entry, req, keys) -> Dict[str, Any]:
    """OpenAI-compatible routers: OpenAI, Groq, OpenRouter, LiteLLM, LLM Gateway, yolorouter."""
    require_configured(entry, keys)
    provider = entry["id"].split("-")[0]
    api_key = _provider_key(provider, keys) or _provider_key(entry["backend"], keys)
    base = (entry.get("base") or "").strip()
    if not base:
        base = {"openai": OPENAI_BASE, "groq": GROQ_BASE, "openrouter": OPENROUTER_BASE,
                "yolorouter": YOLOROUTER_BASE}.get(provider, "")
    if entry["id"] == "litellm-proxy":
        base = _k("LITELLM_BASE_URL", keys)
        api_key = _provider_key("litellm", keys) or api_key
    elif entry["id"] == "llm-gateway":
        base = _k("LLM_GATEWAY_BASE_URL", keys)
        api_key = _provider_key("llmgateway", keys) or api_key
    elif entry["id"] == "yolorouter":
        base = _k("YOLOROUTER_BASE_URL", keys, YOLOROUTER_BASE)
    base = (base or OPENAI_BASE).rstrip("/")
    if not api_key:
        raise ProviderError(f"{entry['label']} needs an API key.", status_code=503,
                            hint=f"Set {entry.get('needs')} in Settings -> AI Keys.")
    cap = entry["capability"]
    headers = {"Authorization": f"Bearer {api_key}", "content-type": "application/json"}
    if entry["id"] == "openrouter-any":
        headers["HTTP-Referer"] = _k("APP_BASE_URL", keys, "https://bg-labs-backend.vercel.app")
        headers["X-Title"] = "BG Labs"

    if cap == "chat":
        messages = (req.get("params") or {}).get("messages")
        if not messages:
            messages = []
            system = (req.get("params") or {}).get("system")
            if system:
                messages.append({"role": "system", "content": str(system)})
            messages.append({"role": "user", "content": req.get("text") or req.get("prompt") or ""})
        payload: Dict[str, Any] = {"model": entry["model"], "messages": messages}
        for field in ("temperature", "max_tokens", "top_p", "response_format", "tools", "tool_choice"):
            value = (req.get("params") or {}).get(field)
            if value is not None:
                payload[field] = value
        async with _client(300.0) as client:
            response = await client.post(f"{base}/chat/completions", headers=headers, json=payload)
        _raise_for(response, entry, keys)
        body = response.json()
        choice = (body.get("choices") or [{}])[0]
        return {"text": (choice.get("message") or {}).get("content") or "", "mime": "text/plain",
                "json": body, "usage": body.get("usage")}

    if cap == "transcribe":
        audio = req.get("audio_url")
        if not audio:
            raise ProviderError("An audio file is required.", status_code=400)
        if str(audio).startswith("data:"):
            mime, _, b64 = str(audio).partition(";base64,")
            ext = "wav" if "wav" in mime else ("mp4" if "mp4" in mime else "mp3")
            files = {"file": (f"audio.{ext}", _b64decode(b64), mime.split(":")[-1] or "audio/mpeg")}
        else:
            data_bytes, mime = await _download(str(audio))
            ext = "mp4" if "mp4" in mime else ("wav" if "wav" in mime else "mp3")
            files = {"file": (f"audio.{ext}", data_bytes, mime)}
        data = {"model": entry["model"], "response_format": (req.get("params") or {}).get("format", "verbose_json")}
        if req.get("language"):
            data["language"] = req["language"]
        async with _client(600.0) as client:
            response = await client.post(f"{base}/audio/transcriptions",
                                         headers={"Authorization": f"Bearer {api_key}"}, data=data, files=files)
        _raise_for(response, entry, keys)
        return {"json": response.json(), "mime": "application/json"}

    raise ProviderError(f"Backend 'openai_compat' does not handle '{cap}'.", status_code=500)


async def _hf_space_call(space: str, endpoint: str, data: List[Any], *, token: str = "",
                         timeout: float = 300.0) -> Any:
    """Call a Gradio Space using the two-step gradio_api protocol (falls back to /run/predict)."""
    clean = space.strip().strip("/")
    clean = re.sub(r"^https?://", "", clean)
    base = clean if clean.endswith(".hf.space") else f"https://{clean}.hf.space"
    if clean.count("/") == 1 and not clean.endswith(".hf.space"):
        base = f"https://{clean.replace('/', '--')}.hf.space"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    api = (endpoint or "/predict").strip("/")
    async with _client(timeout) as client:
        response = await client.post(f"{base}/gradio_api/call/{api}", json={"data": data}, headers=headers)
        if response.status_code == 404:
            legacy = await client.post(f"{base}/run/predict", json={"data": data}, headers=headers)
            if legacy.status_code < 400:
                return legacy.json()
            raise ProviderError(f"Space '{space}' exposes neither /gradio_api/call/{api} nor /run/predict.",
                                status_code=502,
                                hint="Set the Space id and endpoint (HF_*_SPACE / HF_*_ENDPOINT) to match the "
                                     "repo's Gradio app, or deploy your own copy.")
        if response.status_code >= 400:
            raise ProviderError(f"Space '{space}' rejected the request (HTTP {response.status_code}): "
                                f"{response.text[:250]}", status_code=502,
                                hint="Public Spaces rate limit and sleep when idle. Duplicate the Space to your "
                                     "own account and set HF_*_SPACE + HF_TOKEN.")
        event_id = (response.json() or {}).get("event_id")
        if not event_id:
            raise ProviderError(f"Space '{space}' did not return an event id.", status_code=502)
        result: Any = None
        async with client.stream("GET", f"{base}/gradio_api/call/{api}/{event_id}", headers=headers) as stream:
            if stream.status_code >= 400:
                raise ProviderError(f"Space '{space}' stream failed (HTTP {stream.status_code}).", status_code=502)
            async for line in stream.aiter_lines():
                line = (line or "").strip()
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw in ("", "null"):
                    continue
                try:
                    result = json.loads(raw)
                except json.JSONDecodeError:
                    continue
        if result is None:
            raise ProviderError(f"Space '{space}' returned no result.", status_code=502)
        return result


async def _b_gradio(entry, req, keys) -> Dict[str, Any]:
    space = entry["model"] or _k(f"HF_{entry['id'].split('-')[0].upper()}_SPACE", keys)
    if not space:
        raise ProviderError(f"{entry['label']} needs a Hugging Face Space id.", status_code=503,
                            hint=f"Set {entry.get('needs')} (e.g. owner/space-name). Repo: {entry.get('repo')}")
    endpoint = entry.get("endpoint") or _k("HF_ENDPOINT_OVERRIDE", keys) or "/predict"
    data = render_data_template(entry, req, keys)
    # a reference audio data URI cannot be posted to a Space - upload it first if we can
    for index, item in enumerate(data):
        if isinstance(item, str) and item.startswith("data:"):
            stored = await _upload_data_uri(item, kind="audio")
            if stored:
                data[index] = stored
    payload = await _hf_space_call(space, endpoint, data, token=_provider_key("hf", keys),
                                   timeout=float(_k("HF_SPACE_TIMEOUT", keys, "300")))
    kind = {"tts": "audio", "transcribe": "audio", "image": "image", "video": "video"}.get(
        entry["capability"], "")
    if entry["capability"] in ("chat", "transcribe") and not _extract_file(payload, kind):
        return {"json": payload, "text": _flatten_text(payload), "mime": "text/plain"}
    found = _extract_file(payload, kind)
    if not found:
        raise ProviderError(f"{entry['label']} returned no media file.", status_code=502,
                            hint=f"Raw result: {json.dumps(payload)[:400]}. Adjust the input template "
                                 f"(HF_F5_TTS_DATA or the entry's data_template) to match the Space UI.")
    return await _resolve_found(found, space=space, token=_provider_key("hf", keys), kind=kind)


def _flatten_text(payload: Any) -> str:
    parts: List[str] = []
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return "\n".join(p for p in parts if p and not p.startswith(("http", "/tmp", "data:")))[:20000]


async def _upload_data_uri(data_uri: str, kind: str = "audio") -> Optional[str]:
    """Store a data URI in project storage so an external service can fetch it by URL."""
    try:
        from app import media
        header, _, b64 = data_uri.partition(";base64,")
        mime = header.replace("data:", "") or _mime_for(kind)
        saved = await media.save_media(kind=kind, data=_b64decode(b64), content_type=mime, prefix="ref")
        return (saved or {}).get("url")
    except Exception as exc:
        logger.debug("data URI upload skipped: %s", exc)
        return None


async def _resolve_found(found: Dict[str, Any], *, space: str = "", token: str = "",
                         kind: str = "") -> Dict[str, Any]:
    if found.get("b64"):
        return {"bytes": _b64decode(found["b64"]), "mime": found.get("mime") or _mime_for(kind)}
    url = found.get("url") or ""
    if url.startswith("data:"):
        header, _, b64 = url.partition(";base64,")
        return {"bytes": _b64decode(b64), "mime": header.replace("data:", "") or _mime_for(kind)}
    if url.startswith("/"):
        if space:
            url = f"https://{space}.hf.space/file={url.lstrip('/')}"
        else:
            raise ProviderError(f"Provider returned a relative path we cannot resolve: {url}", status_code=502)
    headers = {"Authorization": f"Bearer {token}"} if token else None
    data, mime = await _download(url, headers=headers)
    return {"bytes": data, "mime": mime or _mime_for(kind), "url": url}


async def _b_sdwebui(entry, req, keys) -> Dict[str, Any]:
    require_configured(entry, keys)
    base = (entry["model"] or _k("SD_WEBUI_URL", keys)).rstrip("/")
    if not base:
        raise ProviderError("Set SD_WEBUI_URL to your Stable Diffusion WebUI server.", status_code=503,
                            hint="Launch with --api --listen 0.0.0.0 and expose it (RunPod/Vast/tunnel).")
    payload: Dict[str, Any] = {
        "prompt": req.get("prompt") or req.get("text") or "",
        "negative_prompt": req.get("negative_prompt") or "",
        "steps": int((req.get("params") or {}).get("steps", req.get("steps") or 25)),
        "width": int(req.get("width") or 1024), "height": int(req.get("height") or 1024),
        "cfg_scale": float((req.get("params") or {}).get("guidance", req.get("guidance") or 7)),
        "sampler_name": (req.get("params") or {}).get("sampler", "DPM++ 2M Karras"),
    }
    if req.get("seed"):
        payload["seed"] = int(req["seed"])
    payload.update((req.get("params") or {}).get("extra") or {})
    endpoint = "/sdapi/v1/img2img" if req.get("image_url") else "/sdapi/v1/txt2img"
    if req.get("image_url"):
        image = str(req["image_url"])
        if image.startswith("data:"):
            payload["init_images"] = [image]
        else:
            data, _ = await _download(image)
            payload["init_images"] = [to_data_uri(data, "image/png")]
        payload["denoising_strength"] = float((req.get("params") or {}).get("denoising_strength", 0.6))
    async with _client(600.0) as client:
        response = await client.post(f"{base}{endpoint}", json=payload)
    _raise_for(response, entry, keys)
    body = response.json()
    images = body.get("images") or []
    if not images:
        raise ProviderError("SD WebUI returned no image.", status_code=502,
                            hint=json.dumps(body)[:300])
    return {"bytes": _b64decode(images[0]), "mime": "image/png", "info": body.get("info")}


async def _b_comfyui(entry, req, keys) -> Dict[str, Any]:
    """Queue a ComfyUI workflow, poll /history, fetch the output from /view."""
    require_configured(entry, keys)
    base = (entry["model"] or _k("COMFYUI_URL", keys)).rstrip("/")
    if not base:
        raise ProviderError("Set COMFYUI_URL to your ComfyUI server.", status_code=503,
                            hint="Run ComfyUI with --listen 0.0.0.0 --port 8188 on a GPU box and expose it. "
                                 "Repo: https://github.com/comfyanonymous/ComfyUI")
    workflow_raw = (req.get("params") or {}).get("workflow") or _k("COMFYUI_WORKFLOW", keys)
    if not workflow_raw:
        raise ProviderError("No ComfyUI workflow supplied.", status_code=400,
                            hint="Paste your workflow JSON (API format) in the request, or store it as "
                                 "COMFYUI_WORKFLOW in Settings -> AI Keys. Save it from ComfyUI with "
                                 "'Save (API Format)'.")
    if isinstance(workflow_raw, str):
        if workflow_raw.strip().startswith(("http://", "https://")):
            data_bytes, _ = await _download(workflow_raw.strip())
            workflow = json.loads(data_bytes.decode())
        else:
            try:
                workflow = json.loads(workflow_raw)
            except json.JSONDecodeError as exc:
                raise ProviderError("COMFYUI_WORKFLOW is not valid JSON.", status_code=400, hint=str(exc))
    else:
        workflow = workflow_raw
    text = req.get("prompt") or req.get("text") or ""
    prompt_field = (req.get("params") or {}).get("prompt_node")  # e.g. "6.text"
    injected = False
    if prompt_field and "." in str(prompt_field):
        node, _, field = str(prompt_field).partition(".")
        if node in workflow and isinstance(workflow[node], dict):
            workflow[node].setdefault("inputs", {})[field] = text
            injected = True
    if not injected and text:
        # no explicit mapping: fill the first positive-prompt-looking input
        for node in workflow.values():
            inputs = (node or {}).get("inputs") if isinstance(node, dict) else None
            if isinstance(inputs, dict):
                for key in ("text", "prompt", "positive_prompt"):
                    if key in inputs and isinstance(inputs[key], str):
                        inputs[key] = text
                        injected = True
                        break
            if injected:
                break
    seed = req.get("seed")
    if seed:
        for node in workflow.values():
            inputs = (node or {}).get("inputs") if isinstance(node, dict) else None
            if isinstance(inputs, dict) and "seed" in inputs:
                inputs["seed"] = int(seed)
    client_id = f"bglabs-{abs(hash(text)) % 10**8}"
    async with _client(120.0) as client:
        response = await client.post(f"{base}/prompt", json={"prompt": workflow, "client_id": client_id})
    _raise_for(response, entry, keys)
    prompt_id = (response.json() or {}).get("prompt_id")
    if not prompt_id:
        raise ProviderError("ComfyUI accepted the workflow but returned no prompt_id.", status_code=502)
    return {"job": {"kind": "comfyui", "backend": "comfyui", "model": entry["model"], "model_id": entry["id"],
                    "capability": entry["capability"], "status": "running", "prompt_id": prompt_id,
                    "base": base, "client_id": client_id, "input": {"prompt": text}}}


async def _b_http_json(entry, req, keys) -> Dict[str, Any]:
    """Generic self-hosted service: POST JSON, get media back (bytes / base64 / URL)."""
    require_configured(entry, keys)
    base = (entry["model"] or _k(entry.get("needs") or "", keys)).rstrip("/")
    if not base:
        raise ProviderError(f"{entry['label']} needs a server URL.", status_code=503,
                            hint=f"Set {entry.get('needs')} to your deployment (RunPod / Vast / HF dedicated "
                                 f"Space / local tunnel). Repo: {entry.get('repo')}")
    path = (req.get("params") or {}).get("path") or entry.get("endpoint") or ""
    url = f"{base}{path}" if path and not path.startswith("http") else (path or base)
    payload = build_input(entry, req, keys)
    timeout = float((req.get("params") or {}).get("timeout", _k("SELF_HOSTED_TIMEOUT", keys, "600")))
    async with _client(timeout) as client:
        response = await client.post(url, json=payload)
    _raise_for(response, entry, keys)
    ctype = (response.headers.get("content-type") or "").split(";")[0]
    if ctype.startswith(("audio/", "image/", "video/")):
        return {"bytes": response.content, "mime": ctype}
    if ctype == "application/octet-stream" and len(response.content) > 1024:
        return {"bytes": response.content, "mime": _mime_for(entry.get("response_kind") or "video")}
    try:
        body = response.json()
    except json.JSONDecodeError:
        return {"text": response.text[:20000], "mime": "text/plain"}
    path_hint = (req.get("params") or {}).get("response_path") or entry.get("response_path")
    if path_hint:
        value = _dig(body, path_hint)
        if isinstance(value, str) and value.startswith(("http://", "https://", "data:", "/")):
            value = value if value.startswith("http") else f"{base}{value}"
            found = {"url": value}
        elif isinstance(value, str):
            found = {"b64": value}
        else:
            found = _extract_file(value, entry.get("response_kind") or "")
    else:
        found = _extract_file(body, entry.get("response_kind") or "")
    if not found:
        return {"json": body, "text": _flatten_text(body), "mime": "application/json"}
    return await _resolve_found(found, kind=entry.get("response_kind") or "")


async def _b_none(entry, req, keys) -> Dict[str, Any]:
    """Built-in, model-free capability: the timeline/EDL builder."""
    if entry["id"] == "timeline-local":
        from app.timeline import build_timeline
        return {"json": build_timeline(req), "mime": "application/json"}
    raise ProviderError(f"No built-in implementation for '{entry['id']}'.", status_code=501)


# --------------------------------------------------------------------------- #
# queue backends: fal / replicate / comfyui (start + poll)
# --------------------------------------------------------------------------- #

async def start_job(entry: Dict[str, Any], req: Dict[str, Any],
                    keys: Optional[Dict[str, str]] = None,
                    meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    require_configured(entry, keys)
    backend = entry["backend"]
    payload = build_input(entry, req, keys)

    if backend == "comfyui":
        out = await _b_comfyui(entry, req, keys)
        job = out["job"]
        job["meta"] = meta or {}
        return job

    job: Dict[str, Any] = {"kind": backend, "backend": backend, "model": entry["model"],
                           "model_id": entry["id"], "capability": entry["capability"],
                           "input": payload, "meta": meta or {}, "status": "queued"}

    if backend == "fal":
        api_key = _provider_key("fal", keys)
        queue_base = _k("FAL_QUEUE_URL", keys, FAL_QUEUE).rstrip("/")
        async with _client(120.0) as client:
            response = await client.post(f"{queue_base}/{entry['model']}",
                                         headers={"Authorization": f"Key {api_key}"}, json=payload)
        _raise_for(response, entry, keys)
        body = response.json()
        job.update({"request_id": body.get("request_id"), "status_url": body.get("status_url"),
                    "response_url": body.get("response_url")})
        if job.get("request_id") and not job.get("status_url"):
            job["status_url"] = f"{queue_base}/{entry['model']}/requests/{job['request_id']}/status"
        if job.get("request_id") and not job.get("response_url"):
            job["response_url"] = f"{queue_base}/{entry['model']}/requests/{job['request_id']}"
        return job

    if backend == "replicate":
        token = _provider_key("replicate", keys)
        base = _k("REPLICATE_BASE_URL", keys, REPLICATE_BASE).rstrip("/")
        async with _client(120.0) as client:
            response = await client.post(f"{base}/models/{entry['model']}/predictions",
                                         headers={"Authorization": f"Bearer {token}", "Prefer": "wait"},
                                         json={"input": payload})
        if response.status_code == 200:
            body = response.json()
            if body.get("status") in ("succeeded", "failed"):
                job.update({"status": body["status"], "output": body.get("output"),
                            "urls": _flatten_urls(body.get("output")), "raw": body})
                return job
        _raise_for(response, entry, keys)
        body = response.json()
        job.update({"id": body.get("id"), "status_url": (body.get("urls") or {}).get("get"),
                    "status": body.get("status", "starting")})
        return job

    if backend == "gemini":
        api_key = _provider_key("gemini", keys)
        base = _k("GEMINI_BASE_URL", keys, GEMINI_BASE).rstrip("/")
        instances: Dict[str, Any] = {"prompt": payload.get("prompt", "")}
        parameters: Dict[str, Any] = {}
        for key, value in payload.items():
            if key == "prompt":
                continue
            if key in ("aspect_ratio", "aspectRatio"):
                parameters["aspectRatio"] = value
            elif key in ("duration", "durationSeconds"):
                parameters["durationSeconds"] = value
            elif key in ("negative_prompt", "negativePrompt"):
                parameters["negativePrompt"] = value
            elif key in ("image", "image_url"):
                if isinstance(value, str) and value.startswith("data:"):
                    mime, _, b64 = value.partition(";base64,")
                    instances["image"] = {"bytesBase64Encoded": b64, "mimeType": mime.split(":")[-1]}
                else:
                    instances["image"] = {"gcsUri": value}
            else:
                parameters[key] = value
        async with _client(180.0) as client:
            response = await client.post(f"{base}/v1beta/models/{entry['model']}:predictLongRunning",
                                         headers={"x-goog-api-key": api_key},
                                         json={"instances": [instances], "parameters": parameters})
        _raise_for(response, entry, keys)
        operation = (response.json() or {}).get("name")
        if not operation:
            raise ProviderError("Gemini did not return an operation name.", status_code=502)
        job.update({"operation": operation, "status": "running",
                    "status_url": f"{base}/v1beta/{operation}"})
        return job

    raise ProviderError(f"Backend '{backend}' does not support queued jobs.", status_code=500)


async def poll_job(job: Dict[str, Any], keys: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Refresh a job handle. Credentials are re-read from env/vault - never stored in the job."""
    kind = job.get("kind") or job.get("backend")
    if job.get("status") in ("succeeded", "failed", "canceled") and (job.get("urls") or job.get("error")):
        return job

    if kind == "fal":
        status_url = job.get("status_url")
        if not status_url:
            raise ProviderError("This fal job has no status URL.", status_code=500)
        api_key = _provider_key("fal", keys)
        async with _client(60.0) as client:
            response = await client.get(status_url, headers={"Authorization": f"Key {api_key}"})
        if response.status_code >= 400:
            raise ProviderError(f"fal status check failed (HTTP {response.status_code}).", status_code=502)
        body = response.json()
        state = (body.get("status") or "").lower()
        job["status"] = {"in_queue": "queued", "in_progress": "running", "completed": "succeeded",
                         "error": "failed"}.get(state, state or "running")
        job["queue_position"] = body.get("queue_position")
        if job["status"] == "succeeded" and job.get("response_url"):
            async with _client(60.0) as client:
                result = await client.get(job["response_url"], headers={"Authorization": f"Key {api_key}"})
            if result.status_code >= 400:
                raise ProviderError(f"fal result fetch failed (HTTP {result.status_code}).", status_code=502)
            output = result.json()
            job["output"] = output
            job["urls"] = _flatten_urls(output)
        elif job["status"] == "failed":
            job["error"] = body.get("error") or "fal job failed"

    elif kind == "replicate":
        token = _provider_key("replicate", keys)
        status_url = job.get("status_url") or (
            f"{_k('REPLICATE_BASE_URL', keys, REPLICATE_BASE).rstrip('/')}/predictions/{job.get('id')}"
            if job.get("id") else "")
        if not status_url:
            raise ProviderError("This Replicate job has no status URL.", status_code=500)
        async with _client(60.0) as client:
            response = await client.get(status_url, headers={"Authorization": f"Bearer {token}"})
        if response.status_code >= 400:
            raise ProviderError(f"Replicate status check failed (HTTP {response.status_code}).", status_code=502)
        body = response.json()
        job["status"] = body.get("status", "running")
        job["logs"] = (body.get("logs") or "")[-600:]
        if body.get("output") is not None:
            job["output"] = body["output"]
            job["urls"] = _flatten_urls(body["output"])
        if body.get("error"):
            job["status"] = "failed"
            job["error"] = body["error"]

    elif kind == "gemini":
        status_url = job.get("status_url")
        if not status_url:
            raise ProviderError("This Veo job has no operation name.", status_code=500)
        api_key = _provider_key("gemini", keys)
        async with _client(60.0) as client:
            response = await client.get(status_url, headers={"x-goog-api-key": api_key})
        if response.status_code >= 400:
            raise ProviderError(f"Veo status check failed (HTTP {response.status_code}).", status_code=502)
        body = response.json()
        if not body.get("done"):
            job["status"] = "running"
            job["progress"] = body.get("metadata") or {}
            return job
        if body.get("error"):
            job["status"] = "failed"
            job["error"] = (body["error"] or {}).get("message", "Veo operation failed")
            return job
        response_body = body.get("response") or {}
        video_response = response_body.get("generateVideoResponse") or response_body
        samples = (video_response.get("generatedSamples") or video_response.get("generated_samples")
                   or video_response.get("generatedVideos") or video_response.get("generated_videos") or [])
        urls: List[str] = []
        for sample in samples:
            video = sample.get("video") or sample
            uri = video.get("uri") or video.get("url")
            if uri:
                urls.append(uri)
        urls.extend(u for u in _flatten_urls(video_response) if u not in urls)
        job["output"] = response_body
        job["urls"] = urls
        job["status"] = "succeeded" if urls else "failed"
        if not urls:
            job["error"] = "Veo finished but returned no video URI."
        job["needs_key_to_download"] = True

    elif kind == "comfyui":
        base = (job.get("base") or _k("COMFYUI_URL", keys)).rstrip("/")
        prompt_id = job.get("prompt_id")
        if not base or not prompt_id:
            raise ProviderError("This ComfyUI job is missing its server or prompt id.", status_code=500)
        async with _client(60.0) as client:
            response = await client.get(f"{base}/history/{prompt_id}")
        if response.status_code >= 400:
            job["status"] = "running"
            return job
        history = response.json() or {}
        record = history.get(prompt_id)
        if not record:
            job["status"] = "running"
            return job
        status = (record.get("status") or {})
        if status.get("status_str") == "error" or not status.get("completed", True):
            job["status"] = "failed" if status.get("status_str") == "error" else "running"
            job["error"] = "ComfyUI reported an execution error" if job["status"] == "failed" else None
            return job
        outputs = record.get("outputs") or {}
        files: List[Dict[str, str]] = []
        for node_output in outputs.values():
            for group in ("images", "gifs", "videos", "audio"):
                for item in node_output.get(group) or []:
                    if item.get("filename"):
                        files.append({"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                                      "type": item.get("type", "output"), "group": group})
        if not files:
            job["status"] = "running"
            return job
        urls = [f"{base}/view?filename={f['filename']}&subfolder={f['subfolder']}&type={f['type']}"
                for f in files]
        job["status"] = "succeeded"
        job["urls"] = urls
        job["output"] = {"files": files}

    else:
        raise ProviderError(f"Unknown job kind '{kind}'.", status_code=500)
    return job


async def await_job(job: Dict[str, Any], *, timeout: float = 240.0, interval: float = 4.0,
                    keys: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Poll until finished (or timeout), then download the first output file."""
    waited = 0.0
    while waited < timeout:
        job = await poll_job(job, keys)
        if job.get("status") in ("succeeded", "failed", "canceled"):
            break
        await asyncio.sleep(interval)
        waited += interval
    if job.get("status") == "failed":
        raise ProviderError(f"{job.get('model')} failed: {job.get('error') or 'unknown error'}", status_code=502)
    if job.get("status") != "succeeded":
        return {"status": job.get("status", "running"), "job": job, "bytes": None, "mime": None}
    urls = job.get("urls") or []
    if not urls:
        raise ProviderError("The job succeeded but returned no file URL.", status_code=502,
                            hint=json.dumps(job.get("output"))[:300])
    headers = {"x-goog-api-key": _provider_key("gemini", keys)} if job.get("kind") == "gemini" else None
    data, mime = await _download(urls[0], headers=headers)
    return {"status": "succeeded", "job": job, "bytes": data, "mime": mime, "url": urls[0],
            "all_urls": urls}


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #

BACKEND_RUNNERS = {
    "edge": _b_edge,
    "pollinations": _b_pollinations,
    "openai": _b_openai,
    "gemini": _b_gemini,
    "anthropic": _b_anthropic,
    "elevenlabs": _b_elevenlabs,
    "hf": _b_hf,
    "openai_compat": _b_openai_compat,
    "gradio": _b_gradio,
    "sdwebui": _b_sdwebui,
    "comfyui": _b_comfyui,
    "http_json": _b_http_json,
    "none": _b_none,
}


async def run(entry: Dict[str, Any], req: Dict[str, Any], keys: Optional[Dict[str, str]] = None,
              meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run any catalog entry. Returns bytes, text, JSON, or a job handle."""
    req = normalize_request(req or {})
    backend = entry["backend"]

    if backend in ("fal", "replicate"):
        job = await start_job(entry, req, keys, meta)
        if entry.get("sync") or entry["capability"] in ("image", "image_edit", "upscale", "tts", "transcribe"):
            timeout = float(_k("SYNC_JOB_TIMEOUT", keys, "280"))
            out = await await_job(job, timeout=timeout, keys=keys)
            if out.get("bytes"):
                return {"bytes": out["bytes"], "mime": out["mime"], "url": out.get("url"),
                        "urls": out.get("all_urls"), "job": job}
            return {"status": out.get("status", "running"), "job": job}
        return {"job": job, "status": job.get("status", "queued")}

    if backend == "gemini" and entry["capability"] == "video":
        job = await start_job(entry, req, keys, meta)
        return {"job": job, "status": job.get("status", "running")}

    if backend == "comfyui":
        job = await start_job(entry, req, keys, meta)
        if entry["capability"] in ("image", "image_edit", "upscale"):
            out = await await_job(job, timeout=float(_k("SYNC_JOB_TIMEOUT", keys, "280")), keys=keys)
            if out.get("bytes"):
                return {"bytes": out["bytes"], "mime": out["mime"], "url": out.get("url"),
                        "urls": out.get("all_urls"), "job": job}
            return {"status": out.get("status", "running"), "job": job}
        return {"job": job, "status": job.get("status", "running")}

    runner = BACKEND_RUNNERS.get(backend)
    if not runner:
        raise ProviderError(f"Unsupported backend '{backend}'.", status_code=500)
    out = await runner(entry, req, keys)
    if isinstance(out, dict) and out.get("job"):
        return out
    out.setdefault("provider", backend)
    out["model"] = entry["model"]
    out["model_id"] = entry["id"]
    out["capability"] = entry["capability"]
    return out


async def generate(capability: str, req: Dict[str, Any], *, model: Optional[str] = None,
                   keys: Optional[Dict[str, str]] = None,
                   meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resolve a model for a capability and run it."""
    entry = resolve(capability, model, keys)
    require_configured(entry, keys)
    out = await run(entry, req, keys, meta)
    out.setdefault("model_id", entry["id"])
    out.setdefault("capability", capability)
    out.setdefault("label", entry["label"])
    return out


def voices_for(entry_id: str) -> List[str]:
    """Voice names per TTS model so the UI offers real choices."""
    if entry_id == "edge-tts":
        return ["en-US-AriaNeural", "en-US-GuyNeural", "en-GB-SoniaNeural", "en-IN-NeerjaNeural",
                "en-IN-PrabhatNeural", "ur-PK-UzmaNeural", "ur-PK-AsadNeural", "hi-IN-SwaraNeural",
                "hi-IN-MadhurNeural", "ar-SA-ZariyahNeural", "es-ES-ElviraNeural", "fr-FR-DeniseNeural"]
    if entry_id == "openai-tts":
        return ["alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse"]
    if entry_id == "gemini-tts":
        return ["Kore", "Puck", "Charon", "Fenrir", "Leda", "Orus", "Aoede", "Callirrhoe", "Autonoe",
                "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina", "Erinome", "Algenib", "Rasalgethi",
                "Laomedeia", "Achernar", "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird"]
    if entry_id == "kokoro-space" or entry_id == "kokoro-self":
        return ["af_heart", "af_bella", "af_sky", "am_adam", "am_michael", "bf_emma", "bm_george",
                "zf_xiaoxiao", "zm_yunjian"]
    if entry_id.startswith("f5") or entry_id.startswith("gpt-sovits") or entry_id.startswith("openvoice") \
            or entry_id.startswith("chatterbox") or entry_id.startswith("coqui"):
        return ["clone-from-reference", "no-reference"]
    if entry_id == "elevenlabs":
        return ["21m00Tcm4TlvDq8ikWAM (Rachel)", "EXAVITQu4vr4xnSDxMaL (Bella)",
                "JBFqnCBsd6RMkjVDRZzb (George)", "onwK4e9ZLuTAKqWW03F9 (Daniel)"]
    return []


def languages_for(entry_id: str) -> List[str]:
    if entry_id in ("edge-tts", "elevenlabs", "coqui-xtts", "gemini-tts", "openai-tts"):
        return ["en", "ur", "hi", "ar", "es", "fr", "de", "zh", "tr", "id"]
    return ["en"]


__all__ = [
    "ProviderError", "CATALOG", "CAPABILITIES", "DEFAULT_ORDER", "SYNC_BACKENDS", "QUEUE_BACKENDS",
    "catalog", "resolve", "by_id", "default_id", "is_configured", "public_entry", "provider_status",
    "require_configured", "normalize_request", "build_input",
    "run", "generate", "start_job", "poll_job", "await_job", "voices_for", "languages_for",
    "to_data_uri",
]
