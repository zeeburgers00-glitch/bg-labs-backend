from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime
import uuid

from app.auth import get_current_active_user
from app.database import get_db
from app.models import User, Project
from app.schemas import ProjectCreate, ProjectUpdate, ProjectResponse
from app.tasks import generate_script_task

router = APIRouter(prefix="/api/script", tags=["Script Writer"])


SCRIPT_TEMPLATES = {
    "youtube": {
        "name": "YouTube Video",
        "structure": ["Hook", "Introduction", "Main Content", "Call to Action", "Outro"],
        "tips": "Keep hook under 15 seconds. Use pattern interrupts every 60-90s."
    },
    "educational": {
        "name": "Educational/Tutorial",
        "structure": ["Learning Objective", "Prerequisites", "Step-by-step", "Common Mistakes", "Summary"],
        "tips": "Break complex topics into small chunks. Use analogies."
    },
    "storytelling": {
        "name": "Storytelling",
        "structure": ["Setup", "Inciting Incident", "Rising Action", "Climax", "Resolution"],
        "tips": "Show, don't tell. Use sensory details."
    },
    "sales": {
        "name": "Sales/Marketing",
        "structure": ["Problem", "Agitation", "Solution", "Proof", "Offer", "Urgency"],
        "tips": "Focus on transformation, not features. Use social proof."
    },
    "podcast": {
        "name": "Podcast Episode",
        "structure": ["Teaser", "Intro", "Segment 1", "Ad Break", "Segment 2", "Outro"],
        "tips": "Plan natural conversation flow. Prepare questions in advance."
    },
    "short_form": {
        "name": "Short Form (Reels/TikTok)",
        "structure": ["Hook", "Value", "Call to Action"],
        "tips": "First 3 seconds critical. Loop the ending to beginning."
    },
    "webinar": {
        "name": "Webinar/Presentation",
        "structure": ["Welcome", "Agenda", "Content Blocks", "Demo", "Q&A", "Pitch", "Close"],
        "tips": "Interactive elements every 10-15 minutes."
    }
}

SCRIPT_STYLES = {
    "conversational": "Natural, friendly, like talking to a friend",
    "professional": "Formal, authoritative, business-like",
    "energetic": "High energy, enthusiastic, engaging",
    "calm": "Soothing, measured, meditative",
    "authoritative": "Expert, confident, commanding",
    "humorous": "Light-hearted, witty, entertaining",
    "inspirational": "Motivational, uplifting, emotional",
    "technical": "Precise, detailed, instructional"
}

TONE_OPTIONS = [
    "friendly", "professional", "casual", "formal", "enthusiastic",
    "serious", "playful", "empathetic", "authoritative", "inspiring"
]


@router.get("/templates")
async def get_script_templates():
    return {"templates": SCRIPT_TEMPLATES}


@router.get("/styles")
async def get_script_styles():
    return {
        "styles": [
            {"id": k, "name": k.capitalize(), "description": v}
            for k, v in SCRIPT_STYLES.items()
        ],
        "tones": TONE_OPTIONS
    }


@router.post("/generate", status_code=status.HTTP_201_CREATED)
async def generate_script(
    topic: str,
    template: str = "youtube",
    style: str = "conversational",
    tone: str = "friendly",
    target_length: str = "medium",  # short, medium, long
    target_audience: str = "general",
    key_points: Optional[str] = None,
    language: str = "english",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Validate template
    if template not in SCRIPT_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Invalid template. Options: {list(SCRIPT_TEMPLATES.keys())}")
    
    # Check credits
    credit_cost = {"short": 3, "medium": 5, "long": 8}.get(target_length, 5)
    if current_user.credits < credit_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Need {credit_cost}")
    
    # Create project to store script
    project = Project(
        name=f"Script: {topic[:50]}",
        description=f"AI-generated script for {topic}",
        project_type="script",
        settings={
            "topic": topic,
            "template": template,
            "style": style,
            "tone": tone,
            "target_length": target_length,
            "target_audience": target_audience,
            "key_points": key_points,
            "language": language,
            "status": "generating"
        },
        owner_id=current_user.id
    )
    db.add(project)
    current_user.credits -= credit_cost
    current_user.total_credits_used += credit_cost
    
    await db.commit()
    await db.refresh(project)
    
    # Queue background task
    task = generate_script_task.delay(
        user_id=current_user.id,
        topic=topic,
        style=f"{template}:{style}:{tone}:{target_length}:{target_audience}",
        length=target_length
    )
    
    return {
        "project_id": project.id,
        "task_id": task.id,
        "message": "Script generation started",
        "estimated_time": "30-60 seconds",
        "credits_used": credit_cost
    }


@router.get("/projects", response_model=List[ProjectResponse])
async def list_script_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(Project).where(
        Project.owner_id == current_user.id,
        Project.project_type == "script"
    ).offset(skip).limit(limit).order_by(Project.created_at.desc())
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_script_project(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Script not found")
    
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    return project


@router.put("/projects/{project_id}")
async def update_script(
    project_id: int,
    script_content: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Script not found")
    
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    settings = project.settings or {}
    settings["script_content"] = script_content
    settings["updated_at"] = datetime.utcnow().isoformat()
    settings["status"] = "completed"
    
    project.settings = settings
    await db.commit()
    await db.refresh(project)
    
    return {"message": "Script updated successfully", "project": project}


@router.post("/projects/{project_id}/regenerate-section")
async def regenerate_script_section(
    project_id: int,
    section: str,
    instructions: str = "",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Script not found")
    
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if current_user.credits < 2:
        raise HTTPException(status_code=400, detail="Need 2 credits to regenerate section")
    
    current_user.credits -= 2
    current_user.total_credits_used += 2
    
    # Queue regeneration task
    task = generate_script_task.delay(
        user_id=current_user.id,
        topic=f"Regenerate {section} for: {project.settings.get('topic', '')}",
        style=f"regenerate:{section}:{instructions}",
        length="short"
    )
    
    await db.commit()
    
    return {
        "task_id": task.id,
        "message": f"Regenerating {section} section",
        "credits_used": 2
    }


@router.post("/projects/{project_id}/split-into-scenes")
async def split_script_into_scenes(
    project_id: int,
    max_scene_length: int = 300,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Script not found")
    
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    script = project.settings.get("script_content", "")
    if not script:
        raise HTTPException(status_code=400, detail="No script content to split")
    
    # Simple scene splitting by paragraphs/sentences
    paragraphs = script.split("\n\n")
    scenes = []
    current_scene = ""
    
    for para in paragraphs:
        if len(current_scene) + len(para) > max_scene_length and current_scene:
            scenes.append(current_scene.strip())
            current_scene = para
        else:
            current_scene += "\n\n" + para if current_scene else para
    
    if current_scene:
        scenes.append(current_scene.strip())
    
    settings = project.settings
    settings["scenes"] = [
        {"id": str(uuid.uuid4()), "content": scene, "order": i, "duration_estimate": len(scene) // 15}
        for i, scene in enumerate(scenes)
    ]
    settings["split_at"] = datetime.utcnow().isoformat()
    
    project.settings = settings
    await db.commit()
    await db.refresh(project)
    
    return {"scenes": settings["scenes"], "total_scenes": len(scenes)}


@router.get("/projects/{project_id}/export")
async def export_script(
    project_id: int,
    format: str = "txt",  # txt, json, srt, docx
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(status_code=404, detail="Script not found")
    
    if project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    script = project.settings.get("script_content", "")
    scenes = project.settings.get("scenes", [])
    
    if format == "txt":
        content = f"{project.name}\n\n{script}"
        if scenes:
            content += "\n\n--- SCENES ---\n"
            for i, scene in enumerate(scenes):
                content += f"\nScene {i+1}:\n{scene.get('content', '')}\n"
        return {"content": content, "filename": f"{project.name}.txt"}
    
    elif format == "json":
        return {
            "project": project.name,
            "topic": project.settings.get("topic"),
            "template": project.settings.get("template"),
            "style": project.settings.get("style"),
            "script": script,
            "scenes": scenes
        }
    
    elif format == "srt":
        # Generate SRT subtitle format
        srt_content = ""
        time_offset = 0
        for i, scene in enumerate(scenes):
            content = scene.get("content", "")
            duration = scene.get("duration_estimate", len(content) // 15)
            start_h = time_offset // 3600
            start_m = (time_offset % 3600) // 60
            start_s = time_offset % 60
            end_time = time_offset + duration
            end_h = end_time // 3600
            end_m = (end_time % 3600) // 60
            end_s = end_time % 60
            
            srt_content += f"{i+1}\n"
            srt_content += f"{start_h:02d}:{start_m:02d}:{start_s:02d},000 --> {end_h:02d}:{end_m:02d}:{end_s:02d},000\n"
            srt_content += f"{content}\n\n"
            time_offset = end_time
        
        return {"content": srt_content, "filename": f"{project.name}.srt"}
    
    else:
        raise HTTPException(status_code=400, detail="Unsupported format. Use: txt, json, srt")


@router.post("/optimize-for-platform")
async def optimize_script_for_platform(
    script: str,
    platform: str,  # youtube, tiktok, reels, linkedin, twitter
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.credits < 3:
        raise HTTPException(status_code=400, detail="Need 3 credits")
    
    current_user.credits -= 3
    current_user.total_credits_used += 3
    
    await db.commit()
    
    # Platform-specific optimizations
    optimizations = {
        "youtube": "Add timestamps, chapters, end screen CTAs, community posts",
        "tiktok": "Vertical format, trending sounds, hooks every 3s, loop ending",
        "reels": "9:16 aspect, trending audio, text overlays, saveable content",
        "linkedin": "Professional tone, industry insights, carousel-friendly structure",
        "twitter": "Thread format, 280 chars per tweet, hooks, media attachments"
    }
    
    return {
        "original_script": script,
        "platform": platform,
        "optimization_tips": optimizations.get(platform, "General optimization applied"),
        "credits_used": 3
    }