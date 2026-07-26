from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional

from app.auth import get_current_active_user
from app.database import get_db
from app.models import User, Voice, VoiceType
from app.schemas import VoiceCreate, VoiceUpdate, VoiceResponse, VoiceListResponse
from app.services.tts_engine import tts_service, SUPPORTED_LANGUAGES

router = APIRouter(prefix="/api/voices", tags=["Voices"])


@router.get("", response_model=VoiceListResponse)
async def list_voices(
    language: Optional[str] = None,
    gender: Optional[str] = None,
    voice_type: Optional[VoiceType] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    all_voices = tts_service.get_all_voices()

    if language:
        all_voices = [v for v in all_voices if v["language"] == language]
    if gender:
        all_voices = [v for v in all_voices if v["gender"] == gender]
    if voice_type:
        all_voices = [v for v in all_voices if v["type"] == voice_type.value]

    total = len(all_voices)
    paginated = all_voices[skip:skip + limit]

    return VoiceListResponse(
        voices=paginated,
        total=total,
        languages=SUPPORTED_LANGUAGES
    )


@router.get("/builtin")
async def list_builtin_voices(
    language: Optional[str] = None,
    gender: Optional[str] = None,
):
    all_voices = tts_service.get_all_voices()
    builtin = [v for v in all_voices if v["type"] == "built-in"]

    if language:
        builtin = [v for v in builtin if v["language"] == language]
    if gender:
        builtin = [v for v in builtin if v["gender"] == gender]

    return {
        "voices": builtin,
        "total": len(builtin),
        "languages": SUPPORTED_LANGUAGES
    }


@router.get("/custom", response_model=List[dict])
async def list_custom_voices(
    current_user: User = Depends(get_current_active_user)
):
    all_voices = tts_service.get_all_voices()
    custom = [v for v in all_voices if v["type"] == "custom"]
    return custom


@router.post("/clone", response_model=dict, status_code=status.HTTP_201_CREATED)
async def clone_voice(
    name: str = "Cloned Voice",
    description: str = "",
    audio_file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user)
):
    if not audio_file.filename.endswith((".wav", ".mp3", ".ogg", ".flac")):
        raise HTTPException(status_code=400, detail="Audio file must be WAV, MP3, OGG, or FLAC")

    audio_bytes = await audio_file.read()

    if len(audio_bytes) < 10000:
        raise HTTPException(status_code=400, detail="Audio file too short. Minimum 1 second required.")

    try:
        result = await tts_service.clone_voice(
            name=name,
            audio_bytes=audio_bytes,
            description=description
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice cloning failed: {str(e)}")


@router.get("/{voice_key}")
async def get_voice(voice_key: str):
    voice = tts_service.get_voice_info(voice_key)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found")
    return voice


@router.delete("/{voice_key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voice(
    voice_key: str,
    current_user: User = Depends(get_current_active_user)
):
    if not voice_key.startswith("custom_"):
        raise HTTPException(status_code=400, detail="Cannot delete built-in voices")

    if not tts_service.delete_voice(voice_key):
        raise HTTPException(status_code=404, detail="Voice not found")


@router.get("/languages/all")
async def list_languages():
    return {
        "languages": SUPPORTED_LANGUAGES,
        "total": len(SUPPORTED_LANGUAGES)
    }
