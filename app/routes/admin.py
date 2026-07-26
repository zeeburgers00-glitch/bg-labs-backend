from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.auth import get_current_active_user
from app.database import get_db
from app.models import User, Voice, Project, AudioFile, UserRole
from app.schemas import AdminUserResponse, AdminStatsResponse

router = APIRouter(prefix="/api/admin", tags=["Admin"])


async def verify_admin(current_user: User = Depends(get_current_active_user)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


@router.get("/stats", response_model=AdminStatsResponse)
async def get_admin_stats(
    current_user: User = Depends(verify_admin),
    db: AsyncSession = Depends(get_db)
):
    total_users = await db.scalar(select(func.count(User.id)))
    active_users = await db.scalar(select(func.count(User.id)).where(User.is_active == True))
    total_voices = await db.scalar(select(func.count(Voice.id)))
    total_projects = await db.scalar(select(func.count(Project.id)))
    total_audio = await db.scalar(select(func.count(AudioFile.id)))
    total_credits = await db.scalar(select(func.sum(User.total_credits_used)))
    
    return AdminStatsResponse(
        total_users=total_users or 0,
        active_users=active_users or 0,
        total_voices=total_voices or 0,
        total_projects=total_projects or 0,
        total_audio_generated=total_audio or 0,
        total_credits_used=total_credits or 0
    )


@router.get("/users", response_model=List[AdminUserResponse])
async def list_all_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: str = Query(None),
    role: UserRole = Query(None),
    is_active: bool = Query(None),
    current_user: User = Depends(verify_admin),
    db: AsyncSession = Depends(get_db)
):
    query = select(User)
    
    if search:
        query = query.where(
            (User.email.ilike(f"%{search}%")) |
            (User.username.ilike(f"%{search}%")) |
            (User.full_name.ilike(f"%{search}%"))
        )
    if role:
        query = query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    
    query = query.offset(skip).limit(limit).order_by(User.created_at.desc())
    result = await db.execute(query)
    users = result.scalars().all()
    
    # Add referrals count
    response = []
    for user in users:
        referrals_count = await db.scalar(
            select(func.count(User.id)).where(User.referred_by == user.id)
        )
        user_data = AdminUserResponse.model_validate(user)
        user_data.referrals_count = referrals_count or 0
        response.append(user_data)
    
    return response


@router.get("/users/{user_id}", response_model=AdminUserResponse)
async def get_user_details(
    user_id: int,
    current_user: User = Depends(verify_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    referrals_count = await db.scalar(
        select(func.count(User.id)).where(User.referred_by == user_id)
    )
    user_data = AdminUserResponse.model_validate(user)
    user_data.referrals_count = referrals_count or 0
    return user_data


@router.put("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: int,
    is_active: bool = None,
    role: UserRole = None,
    credits: int = None,
    current_user: User = Depends(verify_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if is_active is not None:
        user.is_active = is_active
    if role is not None:
        user.role = role
    if credits is not None:
        user.credits = credits
    
    await db.commit()
    await db.refresh(user)
    
    referrals_count = await db.scalar(
        select(func.count(User.id)).where(User.referred_by == user_id)
    )
    user_data = AdminUserResponse.model_validate(user)
    user_data.referrals_count = referrals_count or 0
    return user_data


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_user: User = Depends(verify_admin),
    db: AsyncSession = Depends(get_db)
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    await db.delete(user)
    await db.commit()


@router.get("/voices")
async def list_all_voices(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(verify_admin),
    db: AsyncSession = Depends(get_db)
):
    query = select(Voice).offset(skip).limit(limit).order_by(Voice.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/projects")
async def list_all_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(verify_admin),
    db: AsyncSession = Depends(get_db)
):
    query = select(Project).offset(skip).limit(limit).order_by(Project.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()