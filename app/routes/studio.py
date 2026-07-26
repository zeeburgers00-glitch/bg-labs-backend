from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
import uuid

from app.auth import get_current_active_user
from app.database import get_db
from app.models import User, Voice, Project, AudioFile, ProjectType
from app.schemas import (
    ProjectCreate, ProjectUpdate, ProjectResponse,
    AudioGenerateRequest, AudioFileResponse
)
from app.services.tts_engine import tts_service, SUPPORTED_LANGUAGES

router = APIRouter(prefix="/api/studio", tags=["Studio"])


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project: ProjectCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    db_project = Project(
        name=project.name,
        description=project.description,
        project_type=project.project_type,
        settings=project.settings,
        owner_id=current_user.id
    )
    db.add(db_project)
    await db.commit()
    await db.refresh(db_project)
    return db_project


@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(
    project_type: Optional[ProjectType] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(Project).where(Project.owner_id == current_user.id)
    if project_type:
        query = query.where(Project.project_type == project_type)
    query = query.offset(skip).limit(limit).order_by(Project.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return project


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    project_update: ProjectUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    update_data = project_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    await db.delete(project)
    await db.commit()


@router.post("/generate", response_model=AudioFileResponse, status_code=status.HTTP_201_CREATED)
async def generate_audio(
    request: AudioGenerateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    if request.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Language '{request.language}' not supported. Available: {list(SUPPORTED_LANGUAGES.keys())}"
        )

    voice_key = request.voice_key or "aria"

    try:
        audio_bytes = await tts_service.generate_audio(
            text=request.text,
            voice_id=voice_key,
            language=request.language,
            temperature=request.temperature,
            speed=request.speed,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audio generation failed: {str(e)}")

    filename = f"user_{current_user.id}/{uuid.uuid4().hex}.mp3"
    audio_dir = f"storage/audio/{current_user.id}"
    import os
    os.makedirs(audio_dir, exist_ok=True)
    filepath = os.path.join(audio_dir, f"{uuid.uuid4().hex}.mp3")
    with open(filepath, "wb") as f:
        f.write(audio_bytes)

    audio_url = f"/api/storage/audio/{current_user.id}/{os.path.basename(filepath)}"
    duration = max(1, len(request.text) // 15)

    voice = None
    if request.voice_id:
        result = await db.execute(select(Voice).where(Voice.id == request.voice_id))
        voice = result.scalar_one_or_none()

    audio_file = AudioFile(
        filename=filename,
        url=audio_url,
        duration=duration,
        text_content=request.text,
        voice_id=voice.id if voice else 0,
        project_id=request.project_id,
        owner_id=current_user.id,
        language=request.language,
        settings={"temperature": request.temperature, "speed": request.speed}
    )
    db.add(audio_file)

    current_user.total_credits_used += 1

    await db.commit()
    await db.refresh(audio_file)
    return audio_file


@router.get("/audio", response_model=List[AudioFileResponse])
async def list_audio(
    project_id: Optional[int] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(AudioFile).where(AudioFile.owner_id == current_user.id)
    if project_id:
        query = query.where(AudioFile.project_id == project_id)
    query = query.offset(skip).limit(limit).order_by(AudioFile.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/audio/{audio_id}", response_model=AudioFileResponse)
async def get_audio(
    audio_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(AudioFile).where(AudioFile.id == audio_id)
    )
    audio = result.scalar_one_or_none()
    if not audio:
        raise HTTPException(status_code=404, detail="Audio not found")
    if audio.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return audio


@router.delete("/audio/{audio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_audio(
    audio_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(AudioFile).where(AudioFile.id == audio_id))
    audio = result.scalar_one_or_none()
    if not audio:
        raise HTTPException(status_code=404, detail="Audio not found")
    if audio.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    import os
    filepath = os.path.join("storage/audio", str(current_user.id), audio.filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    await db.delete(audio)
    await db.commit()


@router.get("/languages")
async def list_languages():
    return {
        "languages": SUPPORTED_LANGUAGES,
        "total": len(SUPPORTED_LANGUAGES)
    }
