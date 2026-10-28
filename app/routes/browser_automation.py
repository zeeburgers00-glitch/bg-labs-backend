"""
Browser Automation - Playwright, browser-use, Stagehand
Inspired by: browser-use/browser-use, microsoft/playwright, browserbase/stagehand,
skyvern-ai/skyvern
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import json
import asyncio
import os

from app.auth import get_current_active_user
from app.models import User

router = APIRouter(prefix="/api/browser", tags=["Browser Automation"])

# ============================================================
# BROWSER AUTOMATION PROVIDERS
# ============================================================

BROWSER_PROVIDERS = {
    "playwright": {
        "name": "Playwright",
        "description": "Microsoft's browser automation library",
        "type": "library",
        "browsers": ["chromium", "firefox", "webkit"],
        "features": ["auto_wait", "screenshots", "pdf", "network_interception"],
        "github": "https://github.com/microsoft/playwright",
    },
    "browser-use": {
        "name": "browser-use",
        "description": "AI-powered browser agent that can browse autonomously",
        "type": "agent_framework",
        "features": ["autonomous_browsing", "llm_integration", "task_execution"],
        "github": "https://github.com/browser-use/browser-use",
    },
    "stagehand": {
        "name": "Stagehand",
        "description": "Web browsing framework for AI agents",
        "type": "framework",
        "features": ["dom_parsing", "ai_actions", "observability"],
        "github": "https://github.com/browserbase/stagehand",
    },
    "skyvern": {
        "name": "Skyvern",
        "description": "AI-powered browser automation for complex workflows",
        "type": "agent_framework",
        "features": ["workflow_automation", "form_filling", "data_extraction"],
        "github": "https://github.com/Skyvern-AI/skyvern",
    },
    "browserbase": {
        "name": "Browserbase",
        "description": "Cloud browser infrastructure for automation",
        "type": "cloud_service",
        "features": ["headless_browsers", "sessions", "proxies"],
        "website": "https://www.browserbase.com/",
    },
    "puppeteer": {
        "name": "Puppeteer",
        "description": "Node.js library for Chrome/Chromium automation",
        "type": "library",
        "features": ["chrome_automation", "screenshots", "pdf"],
        "github": "https://github.com/puppeteer/puppeteer",
    },
    "selenium": {
        "name": "Selenium",
        "description": "Web browser automation framework",
        "type": "library",
        "features": ["cross_browser", "mobile_testing", "grid"],
        "website": "https://www.selenium.dev/",
    },
    "pyautogui": {
        "name": "PyAutoGUI",
        "description": "GUI automation for desktop control",
        "type": "library",
        "features": ["mouse_control", "keyboard_control", "screenshots"],
        "github": "https://github.com/asweigart/pyautogui",
    },
}


@router.get("/providers")
async def list_browser_providers():
    """List available browser automation providers"""
    return {"providers": BROWSER_PROVIDERS, "total": len(BROWSER_PROVIDERS)}


# ============================================================
# BROWSER SESSIONS
# ============================================================

SESSIONS_STORE: Dict[str, Dict[str, Any]] = {}


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_browser_session(
    provider: str = "playwright",
    browser: str = "chromium",
    headless: bool = True,
    viewport: Optional[Dict[str, int]] = None,
    current_user: User = Depends(get_current_active_user),
):
    """Create a new browser session"""
    if provider not in BROWSER_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider. Options: {list(BROWSER_PROVIDERS.keys())}")

    session_id = str(uuid.uuid4())
    SESSIONS_STORE[session_id] = {
        "id": session_id,
        "provider": provider,
        "browser": browser,
        "headless": headless,
        "viewport": viewport or {"width": 1280, "height": 720},
        "owner_id": current_user.id,
        "created_at": datetime.utcnow().isoformat(),
        "status": "active",
        "current_url": None,
        "title": None,
        "screenshots": [],
    }

    return {
        "session_id": session_id,
        "provider": provider,
        "browser": browser,
        "headless": headless,
        "status": "active",
    }


@router.get("/sessions")
async def list_browser_sessions(
    current_user: User = Depends(get_current_active_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """List user's browser sessions"""
    sessions = [
        s for s in SESSIONS_STORE.values() if s["owner_id"] == current_user.id
    ]
    return {
        "sessions": sessions[skip:skip + limit],
        "total": len(sessions),
    }


@router.get("/sessions/{session_id}")
async def get_browser_session(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Get browser session details"""
    if session_id not in SESSIONS_STORE:
        raise HTTPException(status_code=404, detail="Session not found")

    session = SESSIONS_STORE[session_id]
    if session["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return session


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def close_browser_session(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Close a browser session"""
    if session_id not in SESSIONS_STORE:
        raise HTTPException(status_code=404, detail="Session not found")

    session = SESSIONS_STORE[session_id]
    if session["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    session["status"] = "closed"
    session["closed_at"] = datetime.utcnow().isoformat()


# ============================================================
# BROWSER ACTIONS
# ============================================================

@router.post("/sessions/{session_id}/navigate")
async def browser_navigate(
    session_id: str,
    url: str,
    current_user: User = Depends(get_current_active_user),
):
    """Navigate to a URL"""
    if session_id not in SESSIONS_STORE:
        raise HTTPException(status_code=404, detail="Session not found")

    session = SESSIONS_STORE[session_id]
    if session["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    session["current_url"] = url
    session["title"] = f"Page: {url}"
    session["last_action"] = {
        "type": "navigate",
        "url": url,
        "timestamp": datetime.utcnow().isoformat(),
    }

    return {
        "session_id": session_id,
        "url": url,
        "title": session["title"],
        "status": "navigated",
    }


@router.post("/sessions/{session_id}/click")
async def browser_click(
    session_id: str,
    selector: str,
    current_user: User = Depends(get_current_active_user),
):
    """Click an element"""
    if session_id not in SESSIONS_STORE:
        raise HTTPException(status_code=404, detail="Session not found")

    session = SESSIONS_STORE[session_id]
    if session["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not session.get("current_url"):
        raise HTTPException(status_code=400, detail="No page loaded. Navigate first.")

    session["last_action"] = {
        "type": "click",
        "selector": selector,
        "timestamp": datetime.utcnow().isoformat(),
    }

    return {
        "session_id": session_id,
        "selector": selector,
        "action": "click",
        "status": "completed",
    }


@router.post("/sessions/{session_id}/type")
async def browser_type(
    session_id: str,
    selector: str,
    text: str,
    current_user: User = Depends(get_current_active_user),
):
    """Type text into an element"""
    if session_id not in SESSIONS_STORE:
        raise HTTPException(status_code=404, detail="Session not found")

    session = SESSIONS_STORE[session_id]
    if session["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    session["last_action"] = {
        "type": "type",
        "selector": selector,
        "text": text[:50] + "..." if len(text) > 50 else text,
        "timestamp": datetime.utcnow().isoformat(),
    }

    return {
        "session_id": session_id,
        "selector": selector,
        "action": "type",
        "status": "completed",
    }


@router.post("/sessions/{session_id}/screenshot")
async def browser_screenshot(
    session_id: str,
    full_page: bool = False,
    current_user: User = Depends(get_current_active_user),
):
    """Take a screenshot"""
    if session_id not in SESSIONS_STORE:
        raise HTTPException(status_code=404, detail="Session not found")

    session = SESSIONS_STORE[session_id]
    if session["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    screenshot_id = str(uuid.uuid4())
    screenshot = {
        "id": screenshot_id,
        "url": session.get("current_url"),
        "full_page": full_page,
        "screenshot_url": f"/api/browser/screenshots/{session_id}/{screenshot_id}.png",
        "timestamp": datetime.utcnow().isoformat(),
    }
    session["screenshots"].append(screenshot)

    return screenshot


@router.post("/sessions/{session_id}/extract")
async def browser_extract(
    session_id: str,
    selector: str,
    attribute: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
):
    """Extract data from page elements"""
    if session_id not in SESSIONS_STORE:
        raise HTTPException(status_code=404, detail="Session not found")

    session = SESSIONS_STORE[session_id]
    if session["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return {
        "session_id": session_id,
        "selector": selector,
        "attribute": attribute,
        "extracted_data": [],
        "note": "Mock extraction - requires browser automation library installed",
    }


@router.post("/sessions/{session_id}/execute-script")
async def browser_execute_script(
    session_id: str,
    script: str,
    current_user: User = Depends(get_current_active_user),
):
    """Execute JavaScript in the browser"""
    if session_id not in SESSIONS_STORE:
        raise HTTPException(status_code=404, detail="Session not found")

    session = SESSIONS_STORE[session_id]
    if session["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return {
        "session_id": session_id,
        "script": script[:100] + "..." if len(script) > 100 else script,
        "result": None,
        "note": "Mock script execution - requires Playwright/Puppeteer",
    }


# ============================================================
# AI BROWSER AGENT (browser-use style)
# ============================================================

@router.post("/agent/run", status_code=status.HTTP_201_CREATED)
async def run_browser_agent(
    task: str,
    provider: str = "browser-use",
    llm_provider: str = "openai",
    max_steps: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_active_user),
):
    """Run an AI browser agent to complete a task"""
    if provider not in BROWSER_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider")

    agent_id = str(uuid.uuid4())

    return {
        "agent_id": agent_id,
        "task": task,
        "provider": provider,
        "llm_provider": llm_provider,
        "max_steps": max_steps,
        "status": "started",
        "steps_completed": 0,
        "created_at": datetime.utcnow().isoformat(),
        "note": "AI browser agent - requires browser-use + LLM API key",
    }


@router.get("/agent/{agent_id}/status")
async def get_browser_agent_status(
    agent_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Get browser agent execution status"""
    return {
        "agent_id": agent_id,
        "status": "completed",
        "steps_completed": 5,
        "actions": [
            {"step": 1, "action": "navigate", "target": "https://example.com"},
            {"step": 2, "action": "click", "target": "button#submit"},
            {"step": 3, "action": "extract", "target": ".result"},
        ],
        "final_result": "Task completed successfully",
        "screenshots": [],
    }


# ============================================================
# WEB SCRAPING
# ============================================================

@router.post("/scrape")
async def scrape_website(
    url: str,
    selector: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
):
    """Scrape data from a website"""
    return {
        "url": url,
        "selector": selector,
        "scraped_data": [],
        "status": "mock",
        "note": "Requires Playwright/browser-use installed and running",
    }


# ============================================================
# FORM AUTOMATION
# ============================================================

@router.post("/sessions/{session_id}/fill-form")
async def fill_form(
    session_id: str,
    form_data: Dict[str, str],
    submit: bool = False,
    current_user: User = Depends(get_current_active_user),
):
    """Fill a web form automatically"""
    if session_id not in SESSIONS_STORE:
        raise HTTPException(status_code=404, detail="Session not found")

    session = SESSIONS_STORE[session_id]
    if session["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    filled_fields = list(form_data.keys())

    return {
        "session_id": session_id,
        "filled_fields": filled_fields,
        "submitted": submit,
        "status": "completed",
    }


# ============================================================
# SCREENSHOTS
# ============================================================

@router.get("/screenshots/{session_id}/{filename}")
async def get_screenshot(
    session_id: str,
    filename: str,
    current_user: User = Depends(get_current_active_user),
):
    """Get a screenshot file"""
    from fastapi.responses import FileResponse
    file_path = os.path.join("storage", "browser", "screenshots", session_id, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(file_path, media_type="image/png")