import stripe
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime, timedelta
import os

from app.auth import get_current_active_user
from app.database import get_db
from app.models import User, UserRole
from app.config import get_settings

router = APIRouter(prefix="/api/billing", tags=["Billing & Subscriptions"])

settings = get_settings()

# Initialize Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY if hasattr(settings, 'STRIPE_SECRET_KEY') else os.getenv("STRIPE_SECRET_KEY", "")

# Subscription plans
PLANS = {
    "free": {
        "name": "Free",
        "price_id": None,
        "monthly_price": 0,
        "credits": 100,
        "features": ["100 credits/month", "Basic voices", "5 projects", "Standard quality"]
    },
    "creator": {
        "name": "Creator",
        "price_id": "price_creator_monthly",  # Replace with actual Stripe price ID
        "monthly_price": 29,
        "credits": 5000,
        "features": ["5,000 credits/month", "All voices", "Unlimited projects", "HD quality", "Voice cloning", "Priority support"]
    },
    "pro": {
        "name": "Pro",
        "price_id": "price_pro_monthly",
        "monthly_price": 79,
        "credits": 20000,
        "features": ["20,000 credits/month", "All voices + custom", "Unlimited projects", "4K quality", "Voice cloning", "API access", "Team collaboration", "Priority support"]
    },
    "enterprise": {
        "name": "Enterprise",
        "price_id": "price_enterprise_monthly",
        "monthly_price": 299,
        "credits": 100000,
        "features": ["100,000 credits/month", "Custom voices", "Unlimited everything", "White-label", "Dedicated support", "SLA", "Custom integrations"]
    }
}

CREDIT_PACKS = {
    "pack_1000": {"credits": 1000, "price": 10, "price_id": "price_pack_1000"},
    "pack_5000": {"credits": 5000, "price": 45, "price_id": "price_pack_5000"},
    "pack_10000": {"credits": 10000, "price": 80, "price_id": "price_pack_10000"},
    "pack_50000": {"credits": 50000, "price": 350, "price_id": "price_pack_50000"},
}


@router.get("/plans")
async def get_subscription_plans():
    return {"plans": PLANS, "credit_packs": CREDIT_PACKS}


@router.get("/current")
async def get_current_subscription(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    plan = PLANS.get(current_user.subscription_tier, PLANS["free"])
    
    return {
        "tier": current_user.subscription_tier,
        "plan": plan,
        "credits": current_user.credits,
        "subscription_status": current_user.subscription_status,
        "current_period_end": current_user.subscription_current_period_end,
        "cancel_at_period_end": current_user.subscription_cancel_at_period_end
    }


@router.post("/create-checkout-session")
async def create_checkout_session(
    plan_id: str,
    success_url: str = "https://bglabs.app/billing?success=true",
    cancel_url: str = "https://bglabs.app/billing?canceled=true",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    if plan_id not in PLANS or plan_id == "free":
        raise HTTPException(status_code=400, detail="Invalid plan")
    
    plan = PLANS[plan_id]
    
    if not plan["price_id"]:
        raise HTTPException(status_code=400, detail="Plan not available for purchase")
    
    # Create or get Stripe customer
    if not current_user.stripe_customer_id:
        customer = stripe.Customer.create(
            email=current_user.email,
            name=current_user.full_name or current_user.username,
            metadata={"user_id": current_user.id}
        )
        current_user.stripe_customer_id = customer.id
        await db.commit()
    else:
        customer_id = current_user.stripe_customer_id
    
    # Create checkout session
    try:
        session = stripe.checkout.Session.create(
            customer=current_user.stripe_customer_id,
            payment_method_types=["card"],
            line_items=[{
                "price": plan["price_id"],
                "quantity": 1,
            }],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": current_user.id,
                "plan_id": plan_id
            },
            subscription_data={
                "metadata": {
                    "user_id": current_user.id,
                    "plan_id": plan_id
                }
            }
        )
        
        return {"session_id": session.id, "url": session.url}
    
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/create-credit-pack-session")
async def create_credit_pack_session(
    pack_id: str,
    success_url: str = "https://bglabs.app/billing?success=true",
    cancel_url: str = "https://bglabs.app/billing?canceled=true",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    if pack_id not in CREDIT_PACKS:
        raise HTTPException(status_code=400, detail="Invalid credit pack")
    
    pack = CREDIT_PACKS[pack_id]
    
    if not current_user.stripe_customer_id:
        customer = stripe.Customer.create(
            email=current_user.email,
            name=current_user.full_name or current_user.username,
            metadata={"user_id": current_user.id}
        )
        current_user.stripe_customer_id = customer.id
        await db.commit()
    
    try:
        session = stripe.checkout.Session.create(
            customer=current_user.stripe_customer_id,
            payment_method_types=["card"],
            line_items=[{
                "price": pack["price_id"],
                "quantity": 1,
            }],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": current_user.id,
                "pack_id": pack_id,
                "type": "credit_pack"
            }
        )
        
        return {"session_id": session.id, "url": session.url}
    
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/create-portal-session")
async def create_portal_session(
    return_url: str = "https://bglabs.app/billing",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    if not current_user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found")
    
    try:
        session = stripe.billing_portal.Session.create(
            customer=current_user.stripe_customer_id,
            return_url=return_url
        )
        return {"url": session.url}
    
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    webhook_secret = settings.STRIPE_WEBHOOK_SECRET if hasattr(settings, 'STRIPE_WEBHOOK_SECRET') else os.getenv("STRIPE_WEBHOOK_SECRET", "")
    
    if not webhook_secret:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")
    
    payload = await request.body()
    
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Handle events
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        await handle_checkout_completed(session, db)
    
    elif event["type"] == "customer.subscription.updated":
        subscription = event["data"]["object"]
        await handle_subscription_updated(subscription, db)
    
    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        await handle_subscription_deleted(subscription, db)
    
    elif event["type"] == "invoice.payment_succeeded":
        invoice = event["data"]["object"]
        await handle_payment_succeeded(invoice, db)
    
    elif event["type"] == "invoice.payment_failed":
        invoice = event["data"]["object"]
        await handle_payment_failed(invoice, db)
    
    return {"status": "success"}


async def handle_checkout_completed(session, db: AsyncSession):
    user_id = session["metadata"].get("user_id")
    plan_id = session["metadata"].get("plan_id")
    type_ = session["metadata"].get("type", "subscription")
    
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    
    if not user:
        return
    
    user.stripe_customer_id = session["customer"]
    user.stripe_subscription_id = session.get("subscription")
    
    if type_ == "subscription" and plan_id:
        user.subscription_tier = plan_id
        user.subscription_status = "active"
        user.subscription_current_period_end = datetime.utcnow() + timedelta(days=30)
        
        # Grant credits for the plan
        plan = PLANS.get(plan_id)
        if plan:
            user.credits += plan["credits"]
    
    elif type_ == "credit_pack":
        pack_id = session["metadata"].get("pack_id")
        pack = CREDIT_PACKS.get(pack_id)
        if pack:
            user.credits += pack["credits"]
    
    await db.commit()


async def handle_subscription_updated(subscription, db: AsyncSession):
    user_id = subscription["metadata"].get("user_id")
    
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    
    if not user:
        return
    
    user.subscription_status = subscription["status"]
    user.subscription_current_period_end = datetime.fromtimestamp(
        subscription["current_period_end"]
    )
    user.subscription_cancel_at_period_end = subscription["cancel_at_period_end"]
    
    # Update tier based on price
    price_id = subscription["items"]["data"][0]["price"]["id"]
    for plan_id, plan in PLANS.items():
        if plan.get("price_id") == price_id:
            user.subscription_tier = plan_id
            break
    
    await db.commit()


async def handle_subscription_deleted(subscription, db: AsyncSession):
    user_id = subscription["metadata"].get("user_id")
    
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    
    if not user:
        return
    
    user.subscription_tier = "free"
    user.subscription_status = "canceled"
    user.stripe_subscription_id = None
    
    await db.commit()


async def handle_payment_succeeded(invoice, db: AsyncSession):
    # Handle successful recurring payments
    pass


async def handle_payment_failed(invoice, db: AsyncSession):
    # Handle failed payments
    customer_id = invoice["customer"]
    
    result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
    user = result.scalar_one_or_none()
    
    if user:
        user.subscription_status = "past_due"
        await db.commit()


@router.post("/cancel-subscription")
async def cancel_subscription(
    at_period_end: bool = True,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    if not current_user.stripe_subscription_id:
        raise HTTPException(status_code=400, detail="No active subscription")
    
    try:
        if at_period_end:
            stripe.Subscription.modify(
                current_user.stripe_subscription_id,
                cancel_at_period_end=True
            )
            current_user.subscription_cancel_at_period_end = True
        else:
            stripe.Subscription.delete(current_user.stripe_subscription_id)
            current_user.subscription_tier = "free"
            current_user.subscription_status = "canceled"
            current_user.stripe_subscription_id = None
        
        await db.commit()
        return {"message": "Subscription cancelled"}
    
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reactivate-subscription")
async def reactivate_subscription(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    if not current_user.stripe_subscription_id:
        raise HTTPException(status_code=400, detail="No subscription to reactivate")
    
    try:
        stripe.Subscription.modify(
            current_user.stripe_subscription_id,
            cancel_at_period_end=False
        )
        current_user.subscription_cancel_at_period_end = False
        await db.commit()
        return {"message": "Subscription reactivated"}
    
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/usage")
async def get_usage_stats(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Get usage for current billing period
    period_start = current_user.subscription_current_period_end - timedelta(days=30) if current_user.subscription_current_period_end else datetime.utcnow() - timedelta(days=30)
    
    # This would typically query usage from a separate table
    # For now, return estimated usage
    plan = PLANS.get(current_user.subscription_tier, PLANS["free"])
    
    return {
        "current_credits": current_user.credits,
        "monthly_allowance": plan["credits"],
        "used_this_month": plan["credits"] - current_user.credits if current_user.subscription_tier != "free" else 0,
        "subscription_tier": current_user.subscription_tier,
        "reset_date": current_user.subscription_current_period_end
    }