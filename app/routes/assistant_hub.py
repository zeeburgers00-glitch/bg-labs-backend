"""Unified JARVIS/ BG LABS integration hub.

This module intentionally stays lightweight for Vercel serverless. It exposes a
single capability registry and an authenticated OpenAI-compatible chat endpoint.
Windows GUI control remains in a separately installed local agent; a hosted
serverless function cannot directly control the user's PC.
"""
from __future__ import annotations

import os
from typing import List, Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.deps import check_rate_limit, get_client_ip, get_current_user

router = APIRouter(prefix="/api/hub", tags=["JARVIS Integration Hub"])

MODULES = [
    {
        "id": "voice-output",
        "name": "Voice output",
        "status": "available",
        "endpoint": "/api/studio/generate",
        "notes": "Uses the existing Edge-TTS integration.",
    },
    {
        "id": "voice-input",
        "name": "Speech recognition and wake word",
        "status": "desktop-component-required",
        "endpoint": None,
        "notes": "Requires a microphone client and wake-word/STT model in the Windows app.",
    },
    {
        "id": "chat",
        "name": "AI chat",
        "status": "requires-provider-key",
        "endpoint": "/api/hub/chat",
        "notes": "Uses a configured Groq, OpenAI, or OpenRouter API key.",
    },
    {
        "id": "image-generation",
        "name": "Image generation",
        "status": "available",
        "endpoint": "/api/image/generate",
        "notes": "Uses the existing image generation route.",
    },
    {
        "id": "script-generation",
        "name": "Script generation",
        "status": "available",
        "endpoint": "/api/script/write",
        "notes": "Uses the existing script engine.",
    },
    {
        "id": "video",
        "name": "Video generation and editing",
        "status": "partial",
        "endpoint": None,
        "notes": "Long-running FFmpeg work may need a separate worker/container.",
    },
    {
        "id": "memory",
        "name": "Persistent memory and knowledge",
        "status": "depends-on-storage",
        "endpoint": "/api/system/status",
        "notes": "Persistence depends on Supabase/Postgres configuration; in-memory fallback is ephemeral.",
    },
    {
        "id": "browser",
        "name": "Browser automation",
        "status": "desktop-or-worker-required",
        "endpoint": None,
        "notes": "Requires a browser worker or local agent; do not run arbitrary browser actions in the API request.",
    },
    {
        "id": "windows-control",
        "name": "Windows computer control",
        "status": "desktop-component-required",
        "endpoint": "/api/hub/local-agent/status",
        "notes": "Needs a local Windows agent with explicit permissions and user confirmation.",
    },
    {
        "id": "youtube",
        "name": "YouTube automation",
        "status": "partial",
        "endpoint": "/api/youtube/full-automation",
        "notes": "Publishing and channel analytics need YouTube OAuth/API configuration.",
    },
    {
        "id": "mcp-skills",
        "name": "MCP and skills catalog",
        "status": "catalog-and-optional-routers",
        "endpoint": "/api/hub/modules",
        "notes": "Heavy SQLAlchemy-based routers are optional and intentionally not enabled by default on Vercel.",
    },
    {
        "id": "workflows",
        "name": "Workflow automation",
        "status": "worker-required-for-durable-jobs",
        "endpoint": None,
        "notes": "Durable/background work should use a queue or workflow service, not in-memory serverless state.",
    },
    {
        "id": "files",
        "name": "File and project manager",
        "status": "desktop-component-required",
        "endpoint": None,
        "notes": "Local file access must be performed by the paired Windows agent.",
    },
]

PROVIDERS = {
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "default_model": "openai/gpt-4o-mini",
    },
}


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    provider: Optional[str] = None
    model: Optional[str] = Field(default=None, max_length=160)
    history: List[ChatMessage] = Field(default_factory=list, max_length=20)
    temperature: float = Field(default=0.4, ge=0, le=1.5)


@router.get("/modules")
async def list_modules():
    """Return the central capability registry and honest readiness states."""
    return {
        "name": "JARVIS Integration Hub",
        "version": "1.0.0",
        "modules": MODULES,
        "total": len(MODULES),
    }


@router.get("/providers")
async def list_providers():
    """Expose provider names and configuration state, never API key values."""
    configured = []
    for key, provider in PROVIDERS.items():
        configured.append({
            "id": key,
            "name": provider["name"],
            "configured": bool(os.getenv(provider["key_env"])),
            "key_env": provider["key_env"],
            "default_model": provider["default_model"],
        })
    return {
        "default_provider": os.getenv("JARVIS_PROVIDER", "groq"),
        "providers": configured,
        "local_model": {
            "available_from_backend": False,
            "notes": "Ollama/local models run on the user's PC; connect them through the Windows app or a secure local bridge.",
        },
    }


@router.get("/local-agent/status")
async def local_agent_status():
    """Explain local-agent requirement without falsely reporting a connection."""
    return {
        "connected": False,
        "required": True,
        "message": "Install and pair the Windows local agent before enabling computer control.",
        "security": [
            "Use a one-time pairing code or short-lived device token.",
            "Restrict the agent to user-approved folders and applications.",
            "Require confirmation for destructive or sensitive actions.",
        ],
    }


@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    """Authenticated chat through a configured OpenAI-compatible provider."""
    user = await get_current_user(request)
    if not check_rate_limit(get_client_ip(request), f"hub-chat:{user['id']}", limit=30, window=60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in a minute.")

    provider_id = (body.provider or os.getenv("JARVIS_PROVIDER", "groq")).lower()
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Unsupported provider. Choose one of: {', '.join(PROVIDERS)}")

    api_key = os.getenv(provider["key_env"], "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=f"{provider['key_env']} is not configured in Vercel Environment Variables.",
        )

    model = (body.model or os.getenv("JARVIS_MODEL") or provider["default_model"]).strip()
    messages = [{
        "role": "system",
        "content": (
            "You are JARVIS, a helpful assistant inside BG LABS. "
            "Be clear and honest about capabilities. Never claim you performed a computer, "
            "browser, file, or YouTube action unless a connected tool confirms it. "
            "Ask for confirmation before destructive or sensitive actions."
        ),
    }]
    messages.extend([item.model_dump() for item in body.history])
    messages.append({"role": "user", "content": body.message})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": body.temperature,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            response = await client.post(
                f"{provider['base_url']}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="The AI provider timed out. Please try again.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach the configured AI provider.")

    if response.status_code >= 400:
        # Do not forward upstream bodies that might contain internal provider details.
        raise HTTPException(status_code=502, detail=f"The {provider['name']} API returned HTTP {response.status_code}.")

    try:
        data = response.json()
        answer = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail="The AI provider returned an unexpected response.")

    return {
        "provider": provider_id,
        "model": model,
        "reply": answer,
        "user_id": user["id"],
    }
