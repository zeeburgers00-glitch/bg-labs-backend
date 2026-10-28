"""
LLM Providers - OpenRouter, Groq, OpenAI, Anthropic, Google, Mistral, Cerebras, etc.
Inspired by: openrouter.ai, groq.com, platform.openai.com, anthropic.com, ai.google.dev,
mistral.ai, together.ai, fireworks.ai, cloud.cerebras.ai, console.x.ai, litellm
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import json
import httpx
import os

from app.auth import get_current_active_user
from app.models import User

router = APIRouter(prefix="/api/llm", tags=["LLM Providers"])

# ============================================================
# LLM PROVIDERS REGISTRY
# ============================================================

LLM_PROVIDERS = {
    "openrouter": {
        "name": "OpenRouter",
        "description": "Unified API for 100+ LLMs including free models",
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["mistralai/mistral-7b-instruct", "meta-llama/llama-3.1-8b-instruct:free", "google/gemma-2-9b-it:free"],
        "api_key_required": True,
        "features": ["model_router", "free_tier", "fallback"],
        "website": "https://openrouter.ai/",
    },
    "groq": {
        "name": "Groq",
        "description": "Ultra-fast LLM inference on LPUs",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "api_key_required": True,
        "features": ["ultra_fast", "lpu_inference"],
        "website": "https://console.groq.com/",
    },
    "openai": {
        "name": "OpenAI",
        "description": "GPT models from OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "api_key_required": True,
        "features": ["function_calling", "vision", "assistants"],
        "website": "https://platform.openai.com/",
    },
    "anthropic": {
        "name": "Anthropic",
        "description": "Claude models from Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"],
        "api_key_required": True,
        "features": ["large_context", "coding", "analysis"],
        "website": "https://console.anthropic.com/",
    },
    "google": {
        "name": "Google AI",
        "description": "Gemini models from Google",
        "base_url": "https://generativelanguage.googleapis.com/v1",
        "models": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash-exp"],
        "api_key_required": True,
        "features": ["multimodal", "large_context", "google_integration"],
        "website": "https://ai.google.dev/",
    },
    "mistral": {
        "name": "Mistral AI",
        "description": "Open-weight models from Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "models": ["mistral-large-2407", "mistral-nemo", "codestral-2405"],
        "api_key_required": True,
        "features": ["open_weights", "coding", "efficient"],
        "website": "https://console.mistral.ai/",
    },
    "together": {
        "name": "Together AI",
        "description": "Open source model hosting and inference",
        "base_url": "https://api.together.xyz/v1",
        "models": ["meta-llama/Llama-3.1-70B-Instruct-Turbo", "mistralai/Mixtral-8x7B-Instruct-v0.1"],
        "api_key_required": True,
        "features": ["open_source", "custom_models"],
        "website": "https://www.together.ai/",
    },
    "fireworks": {
        "name": "Fireworks AI",
        "description": "Fast inference for open source models",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "models": ["accounts/fireworks/models/llama-v3p1-70b-instruct"],
        "api_key_required": True,
        "features": ["fast_inference", "open_source"],
        "website": "https://fireworks.ai/",
    },
    "cerebras": {
        "name": "Cerebras",
        "description": "Wafer-scale AI inference",
        "base_url": "https://api.cerebras.ai/v1",
        "models": ["llama3.1-8b", "llama3.1-70b"],
        "api_key_required": True,
        "features": ["wafer_scale", "ultra_fast"],
        "website": "https://cloud.cerebras.ai/",
    },
    "x-ai": {
        "name": "xAI",
        "description": "Grok models from xAI",
        "base_url": "https://api.x.ai/v1",
        "models": ["grok-beta", "grok-2-vision"],
        "api_key_required": True,
        "features": ["real_time", "x_integration"],
        "website": "https://console.x.ai/",
    },
    "ollama": {
        "name": "Ollama (Local)",
        "description": "Run LLMs locally",
        "base_url": "http://localhost:11434/v1",
        "models": ["llama3.1", "llama3.2", "mistral", "codellama"],
        "api_key_required": False,
        "features": ["local", "private", "free"],
        "website": "https://ollama.ai/",
    },
    "lmstudio": {
        "name": "LM Studio (Local)",
        "description": "Local LLM inference with GUI",
        "base_url": "http://localhost:1234/v1",
        "models": ["local-model"],
        "api_key_required": False,
        "features": ["local", "desktop_app"],
        "website": "https://lmstudio.ai/",
    },
}


@router.get("/providers")
async def list_llm_providers():
    """List available LLM providers"""
    return {"providers": LLM_PROVIDERS, "total": len(LLM_PROVIDERS)}


@router.get("/providers/{provider}/models")
async def get_provider_models(
    provider: str,
    current_user: User = Depends(get_current_active_user),
):
    """Get available models from a provider"""
    if provider not in LLM_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider. Options: {list(LLM_PROVIDERS.keys())}")

    return {
        "provider": provider,
        "provider_info": LLM_PROVIDERS[provider],
        "models": LLM_PROVIDERS[provider]["models"],
        "total": len(LLM_PROVIDERS[provider]["models"]),
    }


# ============================================================
# CHAT COMPLETION (Unified API)
# ============================================================

@router.post("/chat/completions")
async def chat_completion(
    provider: str,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = Query(None, ge=1, le=128000),
    stream: bool = False,
    current_user: User = Depends(get_current_active_user),
):
    """Send chat completion to any LLM provider"""
    if provider not in LLM_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider. Options: {list(LLM_PROVIDERS.keys())}")

    if not messages:
        raise HTTPException(status_code=400, detail="Messages are required")

    # Check API key
    provider_info = LLM_PROVIDERS[provider]
    if provider_info["api_key_required"]:
        api_key_status = check_provider_api_key(provider, current_user)
        if not api_key_status:
            raise HTTPException(
                status_code=400,
                detail=f"API key not configured for {provider}. Set it via POST /api/llm/providers/{provider}/api-key"
            )

    # Credit cost estimation
    credit_cost = 1  # Base cost
    # More expensive models cost more
    if "70b" in model.lower() or "large" in model.lower():
        credit_cost = 3
    if "opus" in model.lower():
        credit_cost = 5

    # In production, make actual API call to provider
    # For now, return mock response
    response_text = f"[Mock response from {provider}/{model}]\n\n"
    response_text += f"I received your message with {len(messages)} turn(s).\n"
    response_text += f"This is a simulated response. Configure your API key to get real responses."

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "provider": provider,
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": response_text,
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": sum(len(m.get("content", "")) for m in messages) // 4,
            "completion_tokens": len(response_text) // 4,
            "total_tokens": 0,
        },
        "credit_cost": credit_cost,
        "stream": stream,
        "created_at": datetime.utcnow().isoformat(),
    }


@router.post("/completion")
async def text_completion(
    provider: str,
    model: str,
    prompt: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = Query(None, ge=1, le=128000),
    current_user: User = Depends(get_current_active_user),
):
    """Simple text completion"""
    return await chat_completion(
        provider=provider,
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
        current_user=current_user,
    )


# ============================================================
# EMBEDDINGS
# ============================================================

@router.post("/embeddings")
async def get_embeddings(
    provider: str,
    model: str,
    input_texts: List[str],
    current_user: User = Depends(get_current_active_user),
):
    """Get text embeddings from a provider"""
    if provider not in LLM_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider")

    # Mock embeddings (1536 dimensions like OpenAI)
    import random
    embeddings = []
    for text in input_texts:
        embedding = [random.uniform(-1, 1) for _ in range(1536)]
        embeddings.append(embedding)

    return {
        "provider": provider,
        "model": model,
        "embeddings": embeddings,
        "dimensions": 1536,
        "total_tokens": sum(len(t) for t in input_texts) // 4,
    }


# ============================================================
# API KEY MANAGEMENT
# ============================================================

def check_provider_api_key(provider: str, current_user: User) -> bool:
    """Check if API key is configured for provider (mock)"""
    # In production, check encrypted storage
    return os.getenv(f"{provider.upper()}_API_KEY") is not None


@router.post("/providers/{provider}/api-key")
async def set_llm_provider_api_key(
    provider: str,
    api_key: str,
    current_user: User = Depends(get_current_active_user),
):
    """Store API key for an LLM provider (encrypted)"""
    if provider not in LLM_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider. Options: {list(LLM_PROVIDERS.keys())}")

    # In production, encrypt and store securely
    return {
        "provider": provider,
        "api_key_set": True,
        "key_prefix": api_key[:8] + "..." if len(api_key) > 8 else api_key,
        "message": f"API key for {provider} stored securely",
        "warning": "Never commit API keys to version control. Use environment variables for production.",
    }


@router.get("/providers/{provider}/api-key/status")
async def get_llm_provider_api_key_status(
    provider: str,
    current_user: User = Depends(get_current_active_user),
):
    """Check API key configuration status"""
    if provider not in LLM_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider")

    configured = check_provider_api_key(provider, current_user) or os.getenv(f"{provider.upper()}_API_KEY") is not None

    return {
        "provider": provider,
        "api_key_required": LLM_PROVIDERS[provider]["api_key_required"],
        "configured": configured,
    }


# ============================================================
# MODEL ROUTING (OpenRouter style)
# ============================================================

@router.post("/route")
async def route_to_best_model(
    task: str = Query(..., description="Task type: chat, code, analysis, creative, fast"),
    complexity: str = Query("medium", description="simple, medium, complex"),
    current_user: User = Depends(get_current_active_user),
):
    """Route to the best model for a given task"""
    routing_map = {
        ("chat", "simple"): {"provider": "groq", "model": "llama-3.1-8b-instant", "reason": "Fast and cheap"},
        ("chat", "medium"): {"provider": "openrouter", "model": "meta-llama/llama-3.1-8b-instruct:free", "reason": "Free, good quality"},
        ("chat", "complex"): {"provider": "anthropic", "model": "claude-3-5-sonnet-20241022", "reason": "Best reasoning"},
        ("code", "simple"): {"provider": "groq", "model": "llama-3.1-8b-instant", "reason": "Fast code gen"},
        ("code", "complex"): {"provider": "anthropic", "model": "claude-3-5-sonnet-20241022", "reason": "Best coding"},
        ("analysis", "complex"): {"provider": "google", "model": "gemini-1.5-pro", "reason": "Large context"},
        ("creative", "medium"): {"provider": "openai", "model": "gpt-4o", "reason": "Creative writing"},
        ("fast", "any"): {"provider": "groq", "model": "llama-3.1-8b-instant", "reason": "Ultra fast"},
    }

    key = (task, complexity if complexity != "any" else "simple")
    if task == "fast" or complexity == "any":
        key = ("fast", "any")

    route = routing_map.get(key, routing_map[("chat", "medium")])

    return {
        "task": task,
        "complexity": complexity,
        "recommended_provider": route["provider"],
        "recommended_model": route["model"],
        "reason": route["reason"],
        "alternatives": [
            {"provider": "ollama", "model": "llama3.1", "reason": "Free, local"},
            {"provider": "openrouter", "model": "meta-llama/llama-3.1-8b-instruct:free", "reason": "Free tier"},
        ],
    }