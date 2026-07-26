from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from datetime import datetime
import uuid
import json

from app.auth import get_current_active_user
from app.database import get_db
from app.models import User, Project, AudioFile
from app.schemas import ProjectCreate, ProjectUpdate, ProjectResponse
from app.services.storage import storage_service
from app.tasks import generate_script_task, generate_audio_task, generate_image_task, process_youtube_automation_task

router = APIRouter(prefix="/api/youtube", tags=["YouTube Automation"])


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_youtube_project(
    project: ProjectCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    db_project = Project(
        name=project.name,
        description=project.description,
        project_type="automation",
        settings=project.settings,
        owner_id=current_user.id
    )
    db.add(db_project)
    current_user.total_credits_used += 1
    await db.commit()
    await db.refresh(db_project)
    return db_project


@router.post("/generate-script")
async def generate_youtube_script(
    topic: str,
    style: str = "educational",
    length: str = "medium",
    target_audience: str = "general",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    task = generate_script_task.delay(
        user_id=current_user.id,
        topic=topic,
        style=style,
        length=length
    )

    current_user.total_credits_used += 1
    await db.commit()

    return {
        "task_id": task.id,
        "status": "processing",
        "message": "Script generation started. Check task status for results."
    }


@router.get("/script-status/{task_id}")
async def get_script_status(task_id: str):
    task = generate_script_task.AsyncResult(task_id)

    if task.ready():
        result = task.result
        return {
            "status": "completed" if task.successful() else "failed",
            "result": result
        }
    else:
        return {
            "status": "processing",
            "result": None
        }


@router.post("/generate-voiceover")
async def generate_youtube_voiceover(
    project_id: int,
    script: str,
    voice_key: str = "aria",
    language: str = "en",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")

    task = generate_audio_task.delay(
        user_id=current_user.id,
        voice_id=0,
        text=script,
        project_id=project_id,
        language=language,
        voice_settings={"voice_key": voice_key}
    )

    return {
        "task_id": task.id,
        "status": "processing",
    }


@router.post("/generate-thumbnail")
async def generate_youtube_thumbnail(
    prompt: str,
    style: str = "professional",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    task = generate_image_task.delay(
        user_id=current_user.id,
        prompt=f"YouTube thumbnail: {prompt}, {style} style, high quality, 1280x720",
        model="dall-e-3",
        size="1280x720"
    )

    current_user.total_credits_used += 1
    await db.commit()

    return {
        "task_id": task.id,
        "status": "processing"
    }


@router.post("/full-automation")
async def create_full_youtube_automation(
    topic: str,
    voice_key: str = "aria",
    style: str = "educational",
    length: str = "medium",
    include_thumbnail: bool = True,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    project = Project(
        name=f"YouTube: {topic}",
        description=f"Auto-generated YouTube video about {topic}",
        project_type="automation",
        settings={"topic": topic, "style": style, "length": length},
        owner_id=current_user.id
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    task = process_youtube_automation_task.delay(
        user_id=current_user.id,
        project_id=project.id,
        config={
            "topic": topic,
            "voice_key": voice_key,
            "style": style,
            "length": length,
            "include_thumbnail": include_thumbnail
        }
    )

    return {
        "project_id": project.id,
        "task_id": task.id,
        "status": "processing",
        "steps": [
            "Script generation",
            "Voiceover generation",
            "Thumbnail generation" if include_thumbnail else None,
            "Video assembly"
        ]
    }


@router.get("/projects", response_model=List[ProjectResponse])
async def list_youtube_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(Project).where(
        Project.owner_id == current_user.id,
        Project.project_type == "automation"
    ).offset(skip).limit(limit).order_by(Project.created_at.desc())

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/projects/{project_id}/assets")
async def get_youtube_project_assets(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")

    audio_result = await db.execute(
        select(AudioFile).where(AudioFile.project_id == project_id)
    )
    audio_files = audio_result.scalars().all()

    return {
        "project": project,
        "audio_files": audio_files,
        "script": project.settings.get("script") if project.settings else None,
        "thumbnail_url": project.settings.get("thumbnail_url") if project.settings else None
    }
