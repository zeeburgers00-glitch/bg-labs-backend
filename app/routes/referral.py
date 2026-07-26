from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime, timedelta
import secrets

from app.auth import get_current_active_user
from app.database import get_db
from app.models import User, UserRole
from app.schemas import UserResponse

router = APIRouter(prefix="/api/referral", tags=["Referral System"])


@router.get("/my-code")
async def get_my_referral_code(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    return {
        "referral_code": current_user.referral_code,
        "referral_link": f"https://bglabs.app/register?ref={current_user.referral_code}"
    }


@router.post("/apply-code")
async def apply_referral_code(
    referral_code: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.referred_by:
        raise HTTPException(status_code=400, detail="Already referred by someone")
    
    result = await db.execute(select(User).where(User.referral_code == referral_code))
    referrer = result.scalar_one_or_none()
    
    if not referrer:
        raise HTTPException(status_code=404, detail="Invalid referral code")
    
    if referrer.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot refer yourself")
    
    # Apply referral
    current_user.referred_by = referrer.id
    
    # Give bonus credits to both
    current_user.credits += 50  # Referral bonus for new user
    referrer.credits += 100  # Referral bonus for referrer
    referrer.total_credits_used += 0  # Not used, just earned
    
    await db.commit()
    await db.refresh(current_user)
    await db.refresh(referrer)
    
    return {
        "message": "Referral code applied successfully",
        "your_bonus": 50,
        "referrer_bonus": 100
    }


@router.get("/my-referrals")
async def get_my_referrals(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(User).where(User.referred_by == current_user.id)
    query = query.offset(skip).limit(limit).order_by(User.created_at.desc())
    
    result = await db.execute(query)
    referrals = result.scalars().all()
    
    # Get total count
    count_result = await db.execute(
        select(func.count(User.id)).where(User.referred_by == current_user.id)
    )
    total = count_result.scalar()
    
    # Get earnings from referrals
    earnings_result = await db.execute(
        select(func.sum(User.total_credits_used)).where(User.referred_by == current_user.id)
    )
    total_earnings = earnings_result.scalar() or 0
    
    return {
        "referrals": [
            {
                "id": r.id,
                "username": r.username,
                "email": r.email,
                "credits_used": r.total_credits_used,
                "joined_at": r.created_at,
                "is_active": r.is_active
            }
            for r in referrals
        ],
        "total": total,
        "total_earnings": total_earnings * 0.1  # 10% commission
    }


@router.get("/stats")
async def get_referral_stats(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Total referrals
    total_refs = await db.scalar(
        select(func.count(User.id)).where(User.referred_by == current_user.id)
    )
    
    # Active referrals (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    active_refs = await db.scalar(
        select(func.count(User.id)).where(
            User.referred_by == current_user.id,
            User.updated_at >= thirty_days_ago
        )
    )
    
    # Total credits earned from referrals
    total_credits = await db.scalar(
        select(func.sum(User.total_credits_used)).where(User.referred_by == current_user.id)
    )
    total_credits = total_credits or 0
    
    # Pending payouts
    pending = total_credits * 0.1  # 10% commission
    
    # Monthly breakdown
    monthly_breakdown = []
    for i in range(6):
        month_start = datetime.utcnow().replace(day=1) - timedelta(days=30*i)
        month_end = month_start + timedelta(days=30)
        
        month_refs = await db.scalar(
            select(func.count(User.id)).where(
                User.referred_by == current_user.id,
                User.created_at >= month_start,
                User.created_at < month_end
            )
        )
        
        month_credits = await db.scalar(
            select(func.sum(User.total_credits_used)).where(
                User.referred_by == current_user.id,
                User.created_at >= month_start,
                User.created_at < month_end
            )
        )
        
        monthly_breakdown.append({
            "month": month_start.strftime("%Y-%m"),
            "referrals": month_refs or 0,
            "credits": month_credits or 0,
            "earnings": (month_credits or 0) * 0.1
        })
    
    return {
        "total_referrals": total_refs or 0,
        "active_referrals": active_refs or 0,
        "total_credits_generated": total_credits,
        "pending_payout": pending,
        "monthly_breakdown": monthly_breakdown
    }


@router.get("/leaderboard")
async def get_referral_leaderboard(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db)
):
    # Get users with most referrals
    subquery = select(
        User.referred_by,
        func.count(User.id).label("ref_count")
    ).where(User.referred_by.isnot(None)).group_by(User.referred_by).subquery()
    
    query = select(User, subquery.c.ref_count).join(
        subquery, User.id == subquery.c.referred_by
    ).order_by(subquery.c.ref_count.desc()).limit(limit)
    
    result = await db.execute(query)
    rows = result.all()
    
    return {
        "leaderboard": [
            {
                "rank": idx + 1,
                "user_id": user.id,
                "username": user.username,
                "referrals": ref_count,
                "estimated_earnings": ref_count * 10  # Rough estimate
            }
            for idx, (user, ref_count) in enumerate(rows)
        ]
    }