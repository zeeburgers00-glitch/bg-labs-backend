"""
AI Video Generation - Long-form and short-form video creation
Inspired by: OpenMontage, ViMax (HKUDS), OpenCreator, video-shotcraft, short-video-maker
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import json
import asyncio

from app.auth import get_current_active_user
from app.database import get_db
from app.models import User, Project
from app.schemas import ProjectCreate, ProjectResponse

router = APIRouter(prefix="/api/video", tags=["AI Video Generation"])

# ============================================================
# VIDEO GENERATION MODELS & PROVIDERS
# ============================================================

VIDEO_PROVIDERS = {
    "runway-gen2": {"name": "Runway Gen-2", "max_duration": 16, "credit_cost": 10},
    "pika-labs": {"name": "Pika Labs", "max_duration": 12, "credit_cost": 8},
    "luma-dream-machine": {"name": "Luma Dream Machine", "max_duration": 10, "credit_cost": 12},
    "kling-ai": {"name": "Kling AI", "max_duration": 10, "credit_cost": 15},
    "haiper-ai": {"name": "Haiper AI", "max_duration": 8, "credit_cost": 6},
    "stable-video-diffusion": {"name": "Stable Video Diffusion", "max_duration": 5, "credit_cost": 5},
}

VIDEO_STYLES = [
    {"id": "cinematic", "name": "Cinematic", "description": "Movie-like quality"},
    {"id": "anime", "name": "Anime", "description": "Japanese animation style"},
    {"id": "3d-animation", "name": "3D Animation", "description": "Pixar-style 3D"},
    {"id": "realistic", "name": "Realistic", "description": "Photorealistic"},
    {"id": "stylized", "name": "Stylized", "description": "Artistic stylized"},
    {"id": "pixel-art", "name": "Pixel Art", "description": "Retro pixel style"},
    {"id": "claymation", "name": "Claymation", "description": "Stop motion clay"},
]


@router.get("/providers")
async def list_video_providers():
    """List available AI video generation providers"""
    return {"providers": VIDEO_PROVIDERS, "total": len(VIDEO_PROVIDERS)}


@router.get("/styles")
async def list_video_styles():
    """List available video styles"""
    return {"styles": VIDEO_STYLES, "total": len(VIDEO_STYLES)}


# ============================================================
# TEXT-TO-VIDEO GENERATION
# ============================================================

@router.post("/generate/text-to-video", status_code=status.HTTP_201_CREATED)
async def generate_text_to_video(
    prompt: str,
    provider: str = "stable-video-diffusion",
    style: str = "cinematic",
    duration: int = Query(5, ge=1, le=16),
    aspect_ratio: str = "16:9",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate video from text prompt"""
    if provider not in VIDEO_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider. Options: {list(VIDEO_PROVIDERS.keys())}")

    provider_info = VIDEO_PROVIDERS[provider]
    if duration > provider_info["max_duration"]:
        duration = provider_info["max_duration"]

    credit_cost = provider_info["credit_cost"]
    if current_user.credits < credit_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Need {credit_cost}")

    project = Project(
        name=f"Video: {prompt[:50]}",
        description=f"AI-generated video: {prompt}",
        project_type="video",
        settings={
            "prompt": prompt,
            "provider": provider,
            "style": style,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "status": "processing",
            "progress": 0,
        },
        owner_id=current_user.id,
    )
    db.add(project)
    current_user.credits -= credit_cost
    current_user.total_credits_used += credit_cost
    await db.commit()
    await db.refresh(project)

    return {
        "project_id": project.id,
        "task_id": str(uuid.uuid4()),
        "status": "processing",
        "provider": provider,
        "prompt": prompt,
        "duration": duration,
        "credit_cost": credit_cost,
        "estimated_time": f"{duration * 2}-{duration * 5} seconds",
    }


@router.post("/generate/image-to-video")
async def generate_image_to_video(
    image_file: UploadFile = File(...),
    prompt: str = Form(""),
    provider: str = Form("luma-dream-machine"),
    duration: int = Form(5),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate video from image + prompt"""
    if provider not in VIDEO_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider. Options: {list(VIDEO_PROVIDERS.keys())}")

    image_bytes = await image_file.read()
    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 20MB)")

    provider_info = VIDEO_PROVIDERS[provider]
    credit_cost = provider_info["credit_cost"]

    if current_user.credits < credit_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Need {credit_cost}")

    project = Project(
        name=f"Image-to-Video: {image_file.filename[:40]}",
        description=f"Video generated from uploaded image",
        project_type="video",
        settings={
            "image_filename": image_file.filename,
            "prompt": prompt,
            "provider": provider,
            "duration": duration,
            "status": "processing",
            "progress": 0,
        },
        owner_id=current_user.id,
    )
    db.add(project)
    current_user.credits -= credit_cost
    current_user.total_credits_used += credit_cost
    await db.commit()
    await db.refresh(project)

    # Save uploaded image
    import os
    img_dir = os.path.join("storage", "video_inputs", str(current_user.id))
    os.makedirs(img_dir, exist_ok=True)
    img_path = os.path.join(img_dir, f"{uuid.uuid4().hex}_{image_file.filename}")
    with open(img_path, "wb") as f:
        f.write(image_bytes)

    return {
        "project_id": project.id,
        "task_id": str(uuid.uuid4()),
        "status": "processing",
        "provider": provider,
        "image_saved": img_path,
        "duration": duration,
        "credit_cost": credit_cost,
    }


@router.get("/status/{project_id}")
async def get_video_generation_status(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Check video generation status"""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")

    settings = project.settings or {}
    return {
        "project_id": project_id,
        "status": settings.get("status", "unknown"),
        "progress": settings.get("progress", 0),
        "video_url": settings.get("video_url"),
        "thumbnail_url": settings.get("thumbnail_url"),
        "prompt": settings.get("prompt"),
        "provider": settings.get("provider"),
    }


# ============================================================
# LONG-FORM VIDEO (OpenMontage style)
# ============================================================

@router.post("/long-form/create", status_code=status.HTTP_201_CREATED)
async def create_long_form_video(
    topic: str,
    script: Optional[str] = None,
    target_duration: int = Query(600, ge=60, le=3600),  # seconds
    scenes: Optional[int] = Query(10, ge=1, le=100),
    style: str = "cinematic",
    voice_provider: str = "edge-tts",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create long-form video with multiple scenes (OpenMontage style)"""
    credit_cost = 25  # Base cost for long-form
    if current_user.credits < credit_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Need {credit_cost}")

    # Generate scenes
    scene_list = []
    for i in range(scenes):
        scene_list.append({
            "id": str(uuid.uuid4()),
            "order": i + 1,
            "title": f"Scene {i+1}: {topic} - Part {i+1}",
            "prompt": f"Cinematic scene about {topic}, part {i+1}, {style} style",
            "duration": target_duration // scenes,
            "status": "pending",
        })

    project = Project(
        name=f"Long-form: {topic[:50]}",
        description=f"Long-form AI video about {topic}",
        project_type="video",
        settings={
            "topic": topic,
            "script": script or f"Script for {topic}",
            "target_duration": target_duration,
            "scenes": scene_list,
            "style": style,
            "voice_provider": voice_provider,
            "format": "long-form",
            "status": "created",
            "progress": 0,
        },
        owner_id=current_user.id,
    )
    db.add(project)
    current_user.credits -= credit_cost
    current_user.total_credits_used += credit_cost
    await db.commit()
    await db.refresh(project)

    return {
        "project_id": project.id,
        "topic": topic,
        "format": "long-form",
        "target_duration": target_duration,
        "scenes": len(scene_list),
        "style": style,
        "credit_cost": credit_cost,
        "status": "created",
    }


@router.get("/long-form/scenes/{project_id}")
async def get_long_form_scenes(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get scenes for a long-form video project"""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if not project or project.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Project not found")

    settings = project.settings or {}
    scenes = settings.get("scenes", [])
    return {
        "project_id": project_id,
        "total_scenes": len(scenes),
        "scenes": scenes,
    }


# ============================================================
# SHORT VIDEO MAKER (Reels/TikTok/Shorts)
# ============================================================

@router.post("/shorts/create", status_code=status.HTTP_201_CREATED)
async def create_short_video(
    topic: str,
    platform: str = Query("shorts", description="shorts, reels, tiktok"),
    duration: int = Query(30, ge=15, le=60),
    style: str = "energetic",
    include_captions: bool = True,
    include_music: bool = True,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create short-form video for social media"""
    credit_cost = 15
    if current_user.credits < credit_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Need {credit_cost}")

    platform_specs = {
        "shorts": {"aspect": "9:16", "max_duration": 60, "resolution": "1080x1920"},
        "reels": {"aspect": "9:16", "max_duration": 90, "resolution": "1080x1920"},
        "tiktok": {"aspect": "9:16", "max_duration": 60, "resolution": "1080x1920"},
    }

    spec = platform_specs.get(platform, platform_specs["shorts"])

    project = Project(
        name=f"Shorts: {topic[:40]}",
        description=f"{platform.title()} video about {topic}",
        project_type="video",
        settings={
            "topic": topic,
            "platform": platform,
            "duration": duration,
            "style": style,
            "include_captions": include_captions,
            "include_music": include_music,
            "aspect_ratio": spec["aspect"],
            "resolution": spec["resolution"],
            "status": "created",
            "progress": 0,
        },
        owner_id=current_user.id,
    )
    db.add(project)
    current_user.credits -= credit_cost
    current_user.total_credits_used += credit_cost
    await db.commit()
    await db.refresh(project)

    return {
        "project_id": project.id,
        "platform": platform,
        "topic": topic,
        "duration": duration,
        "aspect_ratio": spec["aspect"],
        "resolution": spec["resolution"],
        "credit_cost": credit_cost,
        "status": "created",
    }


# ============================================================
# VIDEO SHOTCRAFT - AI Storyboard & Shot Planning
# ============================================================

@router.post("/shotcraft/storyboard", status_code=status.HTTP_201_CREATED)
async def create_storyboard(
    topic: str,
    script: str,
    num_shots: int = Query(10, ge=1, le=50),
    style: str = "cinematic",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create AI storyboard from script (Video Shotcraft style)"""
    credit_cost = 10
    if current_user.credits < credit_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Need {credit_cost}")

    # Split script into shots
    sentences = [s.strip() for s in script.split(".") if s.strip()]
    shots = []
    for i, sentence in enumerate(sentences[:num_shots]):
        shots.append({
            "id": str(uuid.uuid4()),
            "shot_number": i + 1,
            "dialogue": sentence,
            "visual_prompt": f"{style} shot of: {sentence[:100]}",
            "camera_angle": ["wide", "medium", "close-up", "over-the-shoulder"][i % 4],
            "lighting": ["natural", "cinematic", "dramatic", "soft"][i % 4],
            "duration_estimate": len(sentence) // 10,
            "status": "planned",
        })

    project = Project(
        name=f"Storyboard: {topic[:40]}",
        description=f"AI storyboard for {topic}",
        project_type="video",
        settings={
            "topic": topic,
            "script": script,
            "shots": shots,
            "style": style,
            "total_shots": len(shots),
            "status": "created",
        },
        owner_id=current_user.id,
    )
    db.add(project)
    current_user.credits -= credit_cost
    current_user.total_credits_used += credit_cost
    await db.commit()
    await db.refresh(project)

    return {
        "project_id": project.id,
        "topic": topic,
        "total_shots": len(shots),
        "shots": shots,
        "style": style,
        "credit_cost": credit_cost,
    }


# ============================================================
# LIST USER VIDEOS
# ============================================================

@router.get("/my-videos", response_model=List[ProjectResponse])
async def list_my_videos(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List user's video projects"""
    query = (
        select(Project)
        .where(Project.owner_id == current_user.id, Project.project_type == "video")
        .offset(skip)
        .limit(limit)
        .order_by(desc(Project.created_at))
    )
    result = await db.execute(query)
    return result.scalars().all()