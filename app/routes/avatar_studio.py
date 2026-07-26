from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime
import uuid

from app.auth import get_current_active_user
from app.database import get_db
from app.models import User, Project, Voice
from app.schemas import ProjectCreate, ProjectUpdate, ProjectResponse
from app.services.tts_engine import tts_service
from app.services.storage import storage_service

router = APIRouter(prefix="/api/avatar", tags=["Avatar Studio"])


@router.post("/create", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_avatar_project(
    name: str = Form(...),
    description: str = Form(""),
    avatar_type: str = Form("talking_head"),
    background: str = Form("studio"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    project = Project(
        name=name,
        description=description,
        project_type="avatar",
        settings={
            "avatar_type": avatar_type,
            "background": background,
            "status": "draft",
            "scenes": []
        },
        owner_id=current_user.id
    )
    db.add(project)
    current_user.total_credits_used += 1

    await db.commit()
    await db.refresh(project)
    return project


@router.get("/projects", response_model=List[ProjectResponse])
async def list_avatar_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: str = Query(None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(Project).where(
        Project.owner_id == current_user.id,
        Project.project_type == "avatar"
    )

    if status_filter:
        query = query.where(Project.settings["status"].astext == status_filter)

    query = query.offset(skip).limit(limit).order_by(Project.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_avatar_project(
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

    return project


@router.put("/projects/{project_id}/scene")
async def add_scene_to_avatar_project(
    project_id: int,
    text: str = Form(...),
    voice_id: int = Form(...),
    avatar_image: Optional[UploadFile] = File(None),
    background_image: Optional[UploadFile] = File(None),
    duration: Optional[int] = Form(None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    avatar_url = None
    if avatar_image:
        avatar_bytes = await avatar_image.read()
        avatar_filename = f"avatar_{current_user.id}/{uuid.uuid4().hex}.png"
        avatar_url = await storage_service.upload_audio(avatar_bytes, avatar_filename)

    background_url = None
    if background_image:
        background_bytes = await background_image.read()
        background_filename = f"background_{current_user.id}/{uuid.uuid4().hex}.png"
        background_url = await storage_service.upload_audio(background_bytes, background_filename)

    scene = {
        "id": str(uuid.uuid4()),
        "text": text,
        "voice_id": voice_id,
        "avatar_url": avatar_url,
        "background_url": background_url,
        "duration": duration or len(text) // 10,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }

    scenes = project.settings.get("scenes", []) if project.settings else []
    scenes.append(scene)
    project.settings = {**project.settings, "scenes": scenes}

    await db.commit()
    await db.refresh(project)

    return {"scene": scene, "project": project}


@router.post("/projects/{project_id}/generate")
async def generate_avatar_video(
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

    scenes = project.settings.get("scenes", []) if project.settings else []
    if not scenes:
        raise HTTPException(status_code=400, detail="No scenes to generate")

    generated_scenes = []
    for scene in scenes:
        if scene.get("status") == "completed":
            generated_scenes.append(scene)
            continue

        try:
            voice_result = await db.execute(select(Voice).where(Voice.id == scene["voice_id"]))
            voice = voice_result.scalar_one()

            voice_key = voice.voice_key or "aria"
            audio_bytes = await tts_service.generate_audio(
                text=scene["text"],
                voice_id=voice_key,
                language=voice.language or "en",
            )

            audio_filename = f"avatar_{project_id}/scene_{scene['id']}.mp3"
            audio_url = await storage_service.upload_audio(audio_bytes, audio_filename)

            scene["audio_url"] = audio_url
            scene["status"] = "completed"
            scene["generated_at"] = datetime.utcnow().isoformat()

        except Exception as e:
            scene["status"] = "failed"
            scene["error"] = str(e)

        generated_scenes.append(scene)

    project.settings = {**project.settings, "scenes": generated_scenes, "status": "generating"}
    current_user.total_credits_used += len(scenes)

    await db.commit()
    await db.refresh(project)

    return {
        "message": "Avatar video generation started",
        "scenes": generated_scenes,
        "credits_used": len(scenes)
    }


@router.get("/templates")
async def get_avatar_templates():
    return {
        "templates": [
            {
                "id": "news_anchor",
                "name": "News Anchor",
                "description": "Professional news desk setup",
                "avatar_type": "talking_head",
                "background": "news_studio",
            },
            {
                "id": "youtube_host",
                "name": "YouTube Host",
                "description": "Casual YouTube-style setup",
                "avatar_type": "talking_head",
                "background": "home_office",
            },
            {
                "id": "corporate_presenter",
                "name": "Corporate Presenter",
                "description": "Professional business presentation",
                "avatar_type": "full_body",
                "background": "boardroom",
            },
            {
                "id": "course_instructor",
                "name": "Course Instructor",
                "description": "Educational content with whiteboard",
                "avatar_type": "full_body",
                "background": "classroom",
            },
            {
                "id": "social_media",
                "name": "Social Media Creator",
                "description": "Vertical video for Reels/TikTok",
                "avatar_type": "talking_head",
                "background": "gradient",
            }
        ]
    }


@router.get("/backgrounds")
async def get_backgrounds():
    return {
        "backgrounds": [
            {"id": "studio", "name": "Professional Studio", "category": "indoor"},
            {"id": "news_studio", "name": "News Studio", "category": "indoor"},
            {"id": "home_office", "name": "Home Office", "category": "indoor"},
            {"id": "boardroom", "name": "Boardroom", "category": "indoor"},
            {"id": "classroom", "name": "Classroom", "category": "indoor"},
            {"id": "living_room", "name": "Living Room", "category": "indoor"},
            {"id": "outdoor_park", "name": "Park", "category": "outdoor"},
            {"id": "outdoor_city", "name": "City Street", "category": "outdoor"},
            {"id": "gradient_blue", "name": "Blue Gradient", "category": "abstract"},
            {"id": "gradient_purple", "name": "Purple Gradient", "category": "abstract"},
            {"id": "solid_white", "name": "Solid White", "category": "solid"},
            {"id": "solid_black", "name": "Solid Black", "category": "solid"},
            {"id": "green_screen", "name": "Green Screen", "category": "special"}
        ]
    }


@router.get("/voices-for-avatar")
async def get_voices_for_avatar(
    current_user: User = Depends(get_current_active_user),
):
    all_voices = tts_service.get_all_voices()
    return {"voices": all_voices}
