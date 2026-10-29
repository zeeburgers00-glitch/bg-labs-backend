"""Working talking-avatar generation API for the lightweight FastAPI runtime.

Users can upload a portrait and either a voice sample plus script, or an
already-recorded narration. fal.ai handles optional voice cloning and queues
the long-running lip-synced talking-head model. Provider keys stay server-side.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from typing import Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.deps import SECRET_KEY, get_current_user
from tts_engine import edge_tts_generate, resolve_voice_key, speed_to_rate

router = APIRouter(prefix="/api/avatar", tags=["Avatar Studio"])

FAL_KEY = os.getenv("FAL_KEY", "").strip()
FAL_QUEUE_MODEL = "fal-ai/flashtalk"
FAL_QUEUE_BASE = f"https://queue.fal.run/{FAL_QUEUE_MODEL}"
MAX_IMAGE_BYTES = 2_000_000
MAX_AUDIO_BYTES = 2_000_000
MAX_TOTAL_UPLOAD_BYTES = 3_800_000
MAX_SCRIPT_CHARS = 5_000

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
AUDIO_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/wave",
    "audio/ogg", "audio/flac", "audio/mp4", "audio/aac", "audio/x-m4a",
    "application/octet-stream",
}


def _data_uri(data: bytes, content_type: str) -> str:
    return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"


def _signed_job_id(request_id: str, user_id: object) -> str:
    payload = f"{user_id}:{request_id}".encode("utf-8")
    signature = hmac.new(SECRET_KEY.encode("utf-8"), payload, hashlib.sha256).hexdigest()[:32]
    return f"{request_id}.{signature}"


def _request_id_from_job_id(job_id: str, user_id: object) -> str:
    if "." not in job_id:
        raise HTTPException(400, "Invalid avatar job ID")
    request_id, signature = job_id.rsplit(".", 1)
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", request_id):
        raise HTTPException(400, "Invalid avatar job ID")
    expected = _signed_job_id(request_id, user_id).rsplit(".", 1)[1]
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(404, "Avatar job was not found for this account")
    return request_id


async def _fal_json(url: str, payload: Optional[dict] = None, method: str = "POST") -> dict:
    if not FAL_KEY:
        raise HTTPException(
            503,
            "Talking Avatar needs FAL_KEY. Add it in Vercel Project Settings → Environment Variables, then redeploy.",
        )
    headers = {"Authorization": f"Key {FAL_KEY}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            if method == "GET":
                response = await client.get(url, headers=headers)
            else:
                response = await client.post(
                    url,
                    headers={**headers, "Content-Type": "application/json"},
                    json=payload or {},
                )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not reach the avatar provider: {type(exc).__name__}") from None

    try:
        data = response.json()
    except ValueError:
        data = {"error": response.text[:400]}
    if response.is_error:
        detail = data.get("detail") or data.get("error") or data.get("message") or f"provider returned HTTP {response.status_code}"
        if isinstance(detail, (dict, list)):
            detail = str(detail)
        raise HTTPException(502, f"Avatar provider error: {str(detail)[:500]}")
    if not isinstance(data, dict):
        raise HTTPException(502, "Avatar provider returned an unexpected response")
    return data


def _content_type(upload: UploadFile, allowed: set[str], fallback: str) -> str:
    content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    if content_type == "image/jpg":
        content_type = "image/jpeg"
    if content_type in allowed:
        return content_type
    filename = (upload.filename or "").lower()
    if filename.endswith((".jpg", ".jpeg")) and "image/jpeg" in allowed:
        return "image/jpeg"
    if filename.endswith(".png") and "image/png" in allowed:
        return "image/png"
    if filename.endswith(".webp") and "image/webp" in allowed:
        return "image/webp"
    if filename.endswith((".mp3", ".mpeg")) and "audio/mpeg" in allowed:
        return "audio/mpeg"
    if filename.endswith((".wav",)) and "audio/wav" in allowed:
        return "audio/wav"
    if filename.endswith(".ogg") and "audio/ogg" in allowed:
        return "audio/ogg"
    if filename.endswith(".flac") and "audio/flac" in allowed:
        return "audio/flac"
    if filename.endswith((".m4a", ".mp4")) and "audio/mp4" in allowed:
        return "audio/mp4"
    if filename.endswith(".aac") and "audio/aac" in allowed:
        return "audio/aac"
    return fallback


@router.get("/talking-video/config")
async def talking_video_config():
    return {
        "configured": bool(FAL_KEY),
        "model": FAL_QUEUE_MODEL,
        "needs_fal_key": not bool(FAL_KEY),
        "message": "Ready to generate talking avatars." if FAL_KEY else "Add FAL_KEY in Vercel to enable talking-avatar generation.",
    }


@router.post("/talking-video")
async def create_talking_video(
    request: Request,
    image: UploadFile = File(...),
    script: str = Form(""),
    voice_sample: Optional[UploadFile] = File(None),
    narration_audio: Optional[UploadFile] = File(None),
    voice_key: str = Form("en-US-GuyNeural"),
    language: str = Form("en-US"),
    speed: float = Form(1.0),
    consent: bool = Form(False),
):
    user = await get_current_user(request)
    if not FAL_KEY:
        raise HTTPException(
            503,
            "Talking Avatar is not configured yet. Add FAL_KEY to Vercel Environment Variables and redeploy.",
        )
    if not consent:
        raise HTTPException(400, "Please confirm you understand that avatar generation may use paid provider credits.")
    if voice_sample is not None and narration_audio is not None:
        raise HTTPException(400, "Upload either a voice sample to clone or a finished narration audio file, not both.")
    if not 0.5 <= speed <= 2.0:
        raise HTTPException(400, "Speech speed must be between 0.5 and 2.0.")

    image_type = _content_type(image, IMAGE_TYPES, "")
    if image_type not in IMAGE_TYPES:
        raise HTTPException(400, "Avatar image must be JPG, PNG, or WebP.")
    image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Avatar image must be smaller than 2 MB. Resize/compress it and try again.")
    if len(image_bytes) < 1000:
        raise HTTPException(400, "The uploaded avatar image appears empty or invalid.")

    image_uri = _data_uri(image_bytes, image_type)
    upload_audio_bytes = b""
    upload_audio_type = ""
    if voice_sample is not None or narration_audio is not None:
        audio_upload = voice_sample or narration_audio
        upload_audio_type = _content_type(audio_upload, AUDIO_TYPES, "audio/mpeg")
        upload_audio_bytes = await audio_upload.read(MAX_AUDIO_BYTES + 1)
        if len(upload_audio_bytes) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Audio upload must be smaller than 2 MB.")
        if len(upload_audio_bytes) < 8_000:
            raise HTTPException(400, "Audio file looks empty or too short.")
        if len(image_bytes) + len(upload_audio_bytes) > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(413, "Combined image and audio uploads are too large. Compress them and retry.")

    spoken_text = (script or "").strip()
    if narration_audio is None and not spoken_text:
        raise HTTPException(400, "Enter a script, or upload a finished narration audio file.")
    if len(spoken_text) > MAX_SCRIPT_CHARS:
        raise HTTPException(400, f"Script is too long. Maximum is {MAX_SCRIPT_CHARS} characters.")

    # Existing narration is used exactly as uploaded.
    if narration_audio is not None:
        audio_uri = _data_uri(upload_audio_bytes, upload_audio_type)
        audio_url_for_preview = audio_uri
        audio_source = "uploaded narration"
    elif voice_sample is not None:
        # Voice sample is used only for voice cloning, never for impersonating another person
        # without authorization; the UI requires the user to confirm their right to use it.
        clone_result = await _fal_json(
            "https://fal.run/fal-ai/minimax/voice-clone",
            {
                "audio_url": _data_uri(upload_audio_bytes, upload_audio_type),
                "noise_reduction": True,
                "need_volume_normalization": True,
            },
        )
        custom_voice_id = clone_result.get("custom_voice_id")
        if not custom_voice_id:
            raise HTTPException(502, "Voice cloning did not return a custom voice ID.")
        speech_result = await _fal_json(
            "https://fal.run/fal-ai/minimax/speech-02-hd",
            {
                "text": spoken_text,
                "voice_setting": {
                    "voice_id": custom_voice_id,
                    "speed": speed,
                    "vol": 1,
                    "pitch": 0,
                },
                "audio_setting": {"format": "mp3", "channel": "1", "sample_rate": "32000"},
                "output_format": "url",
            },
        )
        audio = speech_result.get("audio") or {}
        audio_uri = audio.get("url")
        if not audio_uri:
            raise HTTPException(502, "Text-to-speech did not return an audio URL.")
        audio_url_for_preview = audio_uri
        audio_source = "your cloned voice"
    else:
        # Free built-in voices are available for narration; only the lip-sync job uses fal credits.
        try:
            resolved_voice = resolve_voice_key(voice_key, language)
            audio_bytes = await edge_tts_generate(
                spoken_text,
                resolved_voice,
                rate=speed_to_rate(speed),
            )
        except Exception as exc:
            raise HTTPException(502, f"Could not generate narration: {type(exc).__name__}") from None
        audio_uri = _data_uri(audio_bytes, "audio/mpeg")
        audio_url_for_preview = audio_uri
        audio_source = "built-in voice"

    queued = await _fal_json(
        FAL_QUEUE_BASE,
        {"image_url": image_uri, "audio_url": audio_uri},
    )
    request_id = str(queued.get("request_id") or queued.get("requestId") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", request_id):
        raise HTTPException(502, "Avatar provider did not return a valid generation job ID.")

    return {
        "job_id": _signed_job_id(request_id, user.get("id")),
        "status": "in_queue",
        "model": FAL_QUEUE_MODEL,
        "audio_url": audio_url_for_preview,
        "audio_source": audio_source,
        "message": "Narration is ready. Talking-avatar video is queued for lip-sync generation.",
    }


@router.get("/talking-video/{job_id}")
async def get_talking_video_status(job_id: str, request: Request):
    user = await get_current_user(request)
    request_id = _request_id_from_job_id(job_id, user.get("id"))
    status_data = await _fal_json(f"{FAL_QUEUE_BASE}/requests/{request_id}/status", method="GET")
    provider_status = str(status_data.get("status") or "IN_PROGRESS").upper()
    result = {
        "job_id": job_id,
        "status": provider_status.lower(),
        "model": FAL_QUEUE_MODEL,
        "logs": status_data.get("logs") or [],
    }
    if provider_status == "COMPLETED":
        data = await _fal_json(f"{FAL_QUEUE_BASE}/requests/{request_id}", method="GET")
        video = data.get("video") or {}
        video_url = video.get("url") or data.get("video_url")
        if not video_url:
            raise HTTPException(502, "Avatar job completed, but the provider returned no video URL.")
        result.update({
            "status": "completed",
            "video_url": video_url,
            "duration": data.get("duration") or video.get("duration"),
            "seed": data.get("seed"),
        })
    elif provider_status in {"FAILED", "CANCELLED"}:
        result["error"] = status_data.get("error") or status_data.get("message") or "Avatar generation failed."
    return result
