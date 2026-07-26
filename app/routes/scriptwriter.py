from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime
import uuid

from app.auth import get_current_active_user
from app.database import get_db
from app.models import User, Project, AudioFile
from app.schemas import ProjectCreate, ProjectUpdate, ProjectResponse
from app.tasks import generate_script_task

router = APIRouter(prefix="/api/scriptwriter", tags=["Script Writer"])


@router.post("/generate")
async def generate_script(
    topic: str,
    style: str = "educational",
    length: str = "medium",
    tone: str = "professional",
    target_audience: str = "general",
    language: str = "english",
    outline: str = "",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    credit_cost = 10
    
    if current_user.credits < credit_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Need {credit_cost}")
    
    task = generate_script_task.delay(
        user_id=current_user.id,
        topic=topic,
        style=style,
        length=length
    )
    
    current_user.credits -= credit_cost
    await db.commit()
    
    return {
        "task_id": task.id,
        "status": "processing",
        "estimated_time": "30-60 seconds",
        "credit_cost": credit_cost
    }


@router.get("/status/{task_id}")
async def get_script_generation_status(task_id: str):
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
            "progress": "Generating script...",
            "result": None
        }


@router.post("/save")
async def save_script(
    topic: str,
    script: str,
    style: str = "educational",
    length: str = "medium",
    project_id: Optional[int] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    if project_id:
        # Update existing project
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        
        if not project or project.owner_id != current_user.id:
            raise HTTPException(status_code=404, detail="Project not found")
        
        project.settings = {
            **(project.settings or {}),
            "script": script,
            "topic": topic,
            "style": style,
            "length": length,
            "updated_at": datetime.utcnow().isoformat()
        }
    else:
        # Create new project
        project = Project(
            name=f"Script: {topic[:50]}",
            description=f"AI-generated script about {topic}",
            project_type="script",
            settings={
                "script": script,
                "topic": topic,
                "style": style,
                "length": length
            },
            owner_id=current_user.id
        )
        db.add(project)
    
    await db.commit()
    await db.refresh(project)
    
    return {
        "project_id": project.id,
        "message": "Script saved successfully"
    }


@router.get("/templates")
async def get_script_templates():
    return {
        "templates": [
            {
                "id": "educational",
                "name": "Educational/How-to",
                "description": "Step-by-step tutorial or educational content",
                "structure": ["Hook", "Introduction", "Main Points (3-5)", "Examples", "Summary", "Call to Action"]
            },
            {
                "id": "storytelling",
                "name": "Storytelling",
                "description": "Narrative-driven content with emotional arc",
                "structure": ["Hook", "Setup", "Conflict", "Climax", "Resolution", "Lesson/Message"]
            },
            {
                "id": "listicle",
                "name": "Listicle/Top 10",
                "description": "Numbered list format for easy consumption",
                "structure": ["Hook", "Intro", "Items 1-10", "Bonus Item", "Conclusion", "CTA"]
            },
            {
                "id": "review",
                "name": "Product Review",
                "description": "Honest product review with pros/cons",
                "structure": ["Hook", "Quick Verdict", "Features", "Pros/Cons", "Comparison", "Final Verdict", "Where to Buy"]
            },
            {
                "id": "vlog",
                "name": "Personal Vlog",
                "description": "Casual, personal storytelling",
                "structure": ["Opening", "Day Overview", "Main Event", "Reflection", "Closing", "Next Video Teaser"]
            },
            {
                "id": "documentary",
                "name": "Mini Documentary",
                "description": "In-depth exploration of a topic",
                "structure": ["Cold Open", "Context/Background", "Investigation", "Expert Voices", "Revelation", "Impact", "Closing"]
            }
        ]
    }


@router.post("/improve")
async def improve_script(
    script: str,
    improvements: List[str] = ["clarity", "engagement", "flow", "conciseness"],
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    credit_cost = 5
    
    if current_user.credits < credit_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Need {credit_cost}")
    
    # This would use an LLM to improve the script
    # For now, return a placeholder
    improved_script = f"[IMPROVED VERSION]\n{script}\n\n[Improvements applied: {', '.join(improvements)}]"
    
    current_user.credits -= credit_cost
    await db.commit()
    
    return {
        "original_script": script,
        "improved_script": improved_script,
        "improvements_applied": improvements,
        "credit_cost": credit_cost
    }


@router.post("/translate")
async def translate_script(
    script: str,
    target_language: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    credit_cost = 5
    
    if current_user.credits < credit_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Need {credit_cost}")
    
    # Placeholder for translation
    translated_script = f"[TRANSLATED TO {target_language.upper()}]\n{script}"
    
    current_user.credits -= credit_cost
    await db.commit()
    
    return {
        "original_script": script,
        "translated_script": translated_script,
        "target_language": target_language,
        "credit_cost": credit_cost
    }


@router.get("/my-scripts", response_model=List[ProjectResponse])
async def get_my_scripts(
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