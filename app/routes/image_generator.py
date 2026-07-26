from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime
import uuid
import base64

from app.auth import get_current_active_user
from app.database import get_db
from app.models import User, Project, AudioFile
from app.schemas import ProjectCreate, ProjectUpdate, ProjectResponse
from app.tasks import generate_image_task
from app.services.storage import storage_service

router = APIRouter(prefix="/api/image", tags=["Image Generator"])


@router.post("/generate")
async def generate_image(
    prompt: str,
    model: str = "dall-e-3",
    size: str = "1024x1024",
    quality: str = "standard",
    style: str = "vivid",
    n: int = 1,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    credit_cost = 3 * n
    
    if current_user.credits < credit_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Need {credit_cost}")
    
    task = generate_image_task.delay(
        user_id=current_user.id,
        prompt=prompt,
        model=model,
        size=size
    )
    
    current_user.credits -= credit_cost
    await db.commit()
    
    return {
        "task_id": task.id,
        "status": "processing",
        "credit_cost": credit_cost,
        "estimated_time": "15-30 seconds per image"
    }


@router.get("/status/{task_id}")
async def get_image_generation_status(task_id: str):
    task = generate_image_task.AsyncResult(task_id)
    
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


@router.post("/generate-variations")
async def generate_image_variations(
    image_file: UploadFile = File(...),
    n: int = 3,
    size: str = "1024x1024",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    credit_cost = 2 * n
    
    if current_user.credits < credit_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Need {credit_cost}")
    
    # Read and encode image
    image_bytes = await image_file.read()
    image_base64 = base64.b64encode(image_bytes).decode()
    
    # This would call DALL-E variations API
    # For now, placeholder
    current_user.credits -= credit_cost
    await db.commit()
    
    return {
        "task_id": str(uuid.uuid4()),
        "status": "processing",
        "message": "Variations generation started",
        "credit_cost": credit_cost
    }


@router.post("/edit")
async def edit_image(
    image_file: UploadFile = File(...),
    mask_file: UploadFile = File(None),
    prompt: str = Form(...),
    size: str = "1024x1024",
    n: int = 1,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    credit_cost = 5 * n
    
    if current_user.credits < credit_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Need {credit_cost}")
    
    # Read images
    image_bytes = await image_file.read()
    mask_bytes = await mask_file.read() if mask_file else None
    
    # This would call DALL-E edit API
    current_user.credits -= credit_cost
    await db.commit()
    
    return {
        "task_id": str(uuid.uuid4()),
        "status": "processing",
        "message": "Image editing started",
        "credit_cost": credit_cost
    }


@router.post("/save")
async def save_generated_image(
    prompt: str,
    image_url: str,
    model: str = "dall-e-3",
    size: str = "1024x1024",
    project_id: Optional[int] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    if project_id:
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        
        if not project or project.owner_id != current_user.id:
            raise HTTPException(status_code=404, detail="Project not found")
        
        images = project.settings.get("images", []) if project.settings else []
        images.append({
            "url": image_url,
            "prompt": prompt,
            "model": model,
            "size": size,
            "created_at": datetime.utcnow().isoformat()
        })
        
        project.settings = {**(project.settings or {}), "images": images}
    else:
        project = Project(
            name=f"Image: {prompt[:50]}",
            description=f"AI-generated image: {prompt}",
            project_type="image",
            settings={
                "images": [{
                    "url": image_url,
                    "prompt": prompt,
                    "model": model,
                    "size": size,
                    "created_at": datetime.utcnow().isoformat()
                }]
            },
            owner_id=current_user.id
        )
        db.add(project)
    
    await db.commit()
    await db.refresh(project)
    
    return {
        "project_id": project.id,
        "message": "Image saved successfully"
    }


@router.get("/my-images", response_model=List[ProjectResponse])
async def get_my_images(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(Project).where(
        Project.owner_id == current_user.id,
        Project.project_type == "image"
    ).offset(skip).limit(limit).order_by(Project.created_at.desc())
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/models")
async def get_available_models():
    return {
        "models": [
            {
                "id": "dall-e-3",
                "name": "DALL-E 3",
                "description": "Latest OpenAI image model, high quality",
                "max_size": "1792x1024",
                "credit_cost": 3,
                "features": ["High quality", "Text rendering", "Complex scenes"]
            },
            {
                "id": "dall-e-2",
                "name": "DALL-E 2",
                "description": "Previous generation, faster and cheaper",
                "max_size": "1024x1024",
                "credit_cost": 1,
                "features": ["Fast", "Good for simple images"]
            },
            {
                "id": "stable-diffusion-xl",
                "name": "Stable Diffusion XL",
                "description": "Open source model, highly customizable",
                "max_size": "1024x1024",
                "credit_cost": 2,
                "features": ["Customizable", "NSFW support", "ControlNet"]
            },
            {
                "id": "midjourney-v6",
                "name": "Midjourney v6",
                "description": "Artistic, photorealistic images",
                "max_size": "2048x2048",
                "credit_cost": 5,
                "features": ["Artistic style", "Photorealism", "High detail"]
            }
        ]
    }


@router.get("/styles")
async def get_image_styles():
    return {
        "styles": [
            {"id": "vivid", "name": "Vivid", "description": "Rich, saturated colors"},
            {"id": "natural", "name": "Natural", "description": "Realistic, muted tones"},
            {"id": "cinematic", "name": "Cinematic", "description": "Movie-like lighting"},
            {"id": "anime", "name": "Anime", "description": "Japanese animation style"},
            {"id": "digital-art", "name": "Digital Art", "description": "Modern digital illustration"},
            {"id": "oil-painting", "name": "Oil Painting", "description": "Classic oil paint texture"},
            {"id": "watercolor", "name": "Watercolor", "description": "Soft watercolor effect"},
            {"id": "sketch", "name": "Sketch", "description": "Hand-drawn pencil sketch"},
            {"id": "3d-render", "name": "3D Render", "description": "Photorealistic 3D"},
            {"id": "pixel-art", "name": "Pixel Art", "description": "Retro pixel graphics"}
        ]
    }