"""
BG LABS - Complete AI Platform Backend
Deploy to Vercel - 100% FREE, unlimited
Edge TTS (generation) + cvoice.ai (character browsing)
"""
import os
import json
import uuid
import time
import asyncio
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from contextlib import asynccontextmanager

import asyncpg
import jwt
import httpx
from fastapi import FastAPI, HTTPException, Request, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from tts_engine import (
    edge_tts_generate,
    cvoice_search_characters,
    cvoice_get_voices,
    get_edge_voices,
    EDGE_VOICES,
)

load_dotenv()

logger = logging.getLogger("bglabs")

# ============================================================
# CONFIG
# ============================================================
BASE_DIR = Path(__file__).parent
STORAGE_DIR = Path("/tmp/bglabs_storage") if os.getenv("VERCEL") else BASE_DIR / "storage"
AUDIO_DIR = STORAGE_DIR / "audio"
IMAGE_DIR = STORAGE_DIR / "images"
VIDEO_DIR = STORAGE_DIR / "videos"
AVATAR_DIR = STORAGE_DIR / "avatars"
SECRET_KEY = os.getenv("SECRET_KEY", "bglabs-secret-key-change-in-production")
ALGORITHM = "HS256"
DATABASE_URL = os.getenv("DATABASE_URL", "")

try:
    for d in [STORAGE_DIR, AUDIO_DIR, IMAGE_DIR, VIDEO_DIR, AVATAR_DIR]:
        d.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

# ============================================================
# DATABASE
# ============================================================
pool: Optional[asyncpg.Pool] = None

async def init_db():
    global pool
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set")
        return
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL, username TEXT UNIQUE NOT NULL,
                    full_name TEXT DEFAULT '', password_hash TEXT NOT NULL, role TEXT DEFAULT 'user',
                    is_active BOOLEAN DEFAULT TRUE, credits INTEGER DEFAULT 999999,
                    total_used INTEGER DEFAULT 0, referral_code TEXT, created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS audio_history (
                    id SERIAL PRIMARY KEY, user_id INTEGER, text TEXT, voice TEXT,
                    engine TEXT, filename TEXT, url TEXT, chars INTEGER, created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS image_history (
                    id SERIAL PRIMARY KEY, user_id INTEGER, prompt TEXT, style TEXT,
                    filename TEXT, url TEXT, created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS voice_profiles (
                    id SERIAL PRIMARY KEY, user_id INTEGER, name TEXT,
                    voice_key TEXT, settings TEXT, created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS scripts (
                    id SERIAL PRIMARY KEY, user_id INTEGER, topic TEXT, genre TEXT,
                    mood TEXT, content TEXT, word_count INTEGER, created_at TIMESTAMP DEFAULT NOW()
                );
            """)
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database init failed: {e}")
        pool = None

# ============================================================
# AUTH HELPERS
# ============================================================
def hash_pass(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()

def verify_pass(p: str, h: str) -> bool:
    return hash_pass(p) == h

def create_token(user_id: int) -> str:
    return jwt.encode({"user_id": user_id, "exp": datetime.utcnow() + timedelta(days=30)}, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[int]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]).get("user_id")
    except Exception:
        return None

async def get_current_user(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "No token provided")
    user_id = decode_token(auth.replace("Bearer ", ""))
    if not user_id:
        raise HTTPException(401, "Invalid token")
    if not pool:
        raise HTTPException(503, "Database not available")
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
    if not user or not user["is_active"]:
        raise HTTPException(401, "User not found or blocked")
    return dict(user)

# ============================================================
# IMAGE GENERATION - Pollinations.ai
# ============================================================
async def generate_image_pollinations(prompt: str, style: str = "realistic", width: int = 1024, height: int = 1024) -> bytes:
    style_prompts = {
        "realistic": "photorealistic, high quality, detailed",
        "anime": "anime style, manga, vibrant colors",
        "oil_painting": "oil painting, classical art, textured",
        "digital_art": "digital art, concept art, vibrant",
        "watercolor": "watercolor painting, soft colors, artistic",
        "3d_render": "3D render, octane render, cinematic",
        "pixel_art": "pixel art, retro, 16-bit style",
        "cyberpunk": "cyberpunk style, neon lights, futuristic",
    }
    style_suffix = style_prompts.get(style, "")
    full_prompt = f"{prompt}, {style_suffix}" if style_suffix else prompt
    encoded_prompt = full_prompt.replace(" ", "%20")
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&seed={int(time.time())}&nologo=true"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code != 200:
            raise Exception(f"Image generation failed: {resp.status_code}")
        return resp.content

# ============================================================
# AVATAR GENERATION - SVG
# ============================================================
def generate_avatar_svg(hair_color: str = "#333", eye_color: str = "#333", skin_tone: str = "#fdbcb4", clothing_color: str = "#3b82f6") -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">
        <circle cx="100" cy="100" r="95" fill="{skin_tone}"/>
        <circle cx="100" cy="85" r="55" fill="{hair_color}"/>
        <circle cx="80" cy="85" r="8" fill="{eye_color}"/>
        <circle cx="120" cy="85" r="8" fill="{eye_color}"/>
        <ellipse cx="100" cy="110" rx="15" ry="8" fill="{clothing_color}"/>
        <path d="M 85 95 Q 100 105 115 95" stroke="{skin_tone}" fill="none" stroke-width="2"/>
    </svg>'''

# ============================================================
# FASTAPI APP
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
    except Exception as e:
        logger.error(f"Startup error: {e}")
    yield

app = FastAPI(title="BG LABS API", version="9.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    app.mount("/api/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")
except Exception:
    pass

# ============================================================
# ROOT
# ============================================================
@app.get("/")
async def root():
    html_path = BASE_DIR / "bglabs_complete.html"
    if html_path.exists():
        return FileResponse(str(html_path), media_type="text/html")
    return {"name": "BG LABS API", "version": "9.0.0", "status": "running"}

@app.get("/health")
async def health():
    return {"status": "healthy", "version": "9.0.0"}

# ============================================================
# AUTH
# ============================================================
@app.post("/api/auth/register")
async def register(email: str = Form(...), username: str = Form(...), full_name: str = Form(""), password: str = Form(...)):
    if not pool:
        raise HTTPException(503, "Database not available")
    code = uuid.uuid4().hex[:8]
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT 1 FROM users WHERE email=$1 OR username=$2", email, username)
        if existing:
            raise HTTPException(400, "Email or username already exists")
        row = await conn.fetchrow(
            "INSERT INTO users (email, username, full_name, password_hash, referral_code) VALUES ($1,$2,$3,$4,$5) RETURNING *",
            email, username, full_name, hash_pass(password), code
        )
    user = dict(row)
    token = create_token(user["id"])
    return {"access_token": token, "token_type": "bearer", "user": {
        "id": user["id"], "email": user["email"], "username": user["username"],
        "full_name": user["full_name"], "role": user["role"], "credits": user["credits"],
        "total_credits_used": user["total_used"], "is_active": user["is_active"]
    }}

@app.post("/api/auth/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if not pool:
        raise HTTPException(503, "Database not available")
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE username=$1 OR email=$1", username)
    if not user:
        raise HTTPException(401, "User not found")
    if not verify_pass(password, user["password_hash"]):
        raise HTTPException(401, "Incorrect password")
    if not user["is_active"]:
        raise HTTPException(403, "Account blocked")
    token = create_token(user["id"])
    return {"access_token": token, "token_type": "bearer", "user": {
        "id": user["id"], "email": user["email"], "username": user["username"],
        "full_name": user["full_name"], "role": user["role"], "credits": user["credits"],
        "total_credits_used": user["total_used"], "is_active": user["is_active"]
    }}

@app.get("/api/auth/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    return {"id": user["id"], "email": user["email"], "username": user["username"],
        "full_name": user["full_name"], "role": user["role"], "is_active": bool(user["is_active"]),
        "credits": user["credits"], "total_credits_used": user["total_used"]}

# ============================================================
# VOICES
# ============================================================
@app.get("/api/voices")
async def list_voices():
    return {"voices": get_edge_voices(), "total": len(EDGE_VOICES), "engine": "Edge-TTS"}

@app.get("/api/voices/characters")
async def search_characters(q: str = Query(""), limit: int = Query(50, ge=1, le=200)):
    try:
        chars = await cvoice_search_characters(q, limit)
        return {"characters": chars, "total": len(chars)}
    except Exception as e:
        return {"characters": [], "total": 0, "error": str(e)}

@app.get("/api/voices/characters/{username}")
async def get_character_voices(username: str):
    try:
        voices = await cvoice_get_voices(username)
        return {"username": username, "voices": voices, "total": len(voices)}
    except Exception as e:
        return {"username": username, "voices": [], "total": 0, "error": str(e)}

# ============================================================
# TTS GENERATION - Edge TTS (FREE, UNLIMITED)
# ============================================================
@app.post("/api/studio/generate")
async def generate_audio(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    text = body.get("text", "").strip()
    voice_key = body.get("voice_key", "en-US-AriaNeural")

    if not text:
        raise HTTPException(400, "Text is required")
    if len(text) > 10000:
        raise HTTPException(400, "Text too long (max 10,000 chars)")

    try:
        audio_bytes = await edge_tts_generate(text, voice_key)
    except Exception as e:
        raise HTTPException(500, f"TTS failed: {str(e)}")

    filename = f"{uuid.uuid4().hex}.mp3"
    try:
        (AUDIO_DIR / filename).write_bytes(audio_bytes)
    except OSError:
        tmp_dir = Path("/tmp/bglabs_audio")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        (tmp_dir / filename).write_bytes(audio_bytes)

    voice_info = EDGE_VOICES.get(voice_key, {"name": "Unknown", "lang": "en"})

    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO audio_history (user_id, text, voice, engine, filename, url, chars) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                    user["id"], text[:500], voice_info.get("name", voice_key), "Edge-TTS", filename, f"/api/storage/audio/{filename}", len(text)
                )
                await conn.execute("UPDATE users SET total_used = total_used + $1 WHERE id = $2", len(text), user["id"])
        except Exception:
            pass

    return {"url": f"/api/storage/audio/{filename}", "filename": filename, "engine": "Edge-TTS", "voice": voice_info.get("name", voice_key), "chars": len(text)}

@app.get("/api/studio/audio")
async def list_audio(request: Request):
    user = await get_current_user(request)
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM audio_history WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50", user["id"])
    return [dict(r) for r in rows]

# ============================================================
# IMAGE GENERATION
# ============================================================
@app.post("/api/image/generate")
async def generate_image(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    style = body.get("style", "realistic")
    if not prompt:
        raise HTTPException(400, "Prompt is required")
    try:
        image_bytes = await generate_image_pollinations(prompt, style)
    except Exception as e:
        raise HTTPException(500, f"Image generation failed: {str(e)}")
    filename = f"{uuid.uuid4().hex}.png"
    try:
        (IMAGE_DIR / filename).write_bytes(image_bytes)
    except OSError:
        tmp_dir = Path("/tmp/bglabs_images")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        (tmp_dir / filename).write_bytes(image_bytes)
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute("INSERT INTO image_history (user_id, prompt, style, filename, url) VALUES ($1,$2,$3,$4,$5)",
                    user["id"], prompt[:500], style, filename, f"/api/storage/images/{filename}")
        except Exception:
            pass
    return {"url": f"/api/storage/images/{filename}", "filename": filename, "prompt": prompt, "style": style}

@app.get("/api/image/history")
async def image_history(request: Request):
    user = await get_current_user(request)
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM image_history WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50", user["id"])
    return [dict(r) for r in rows]

# ============================================================
# AVATAR STUDIO
# ============================================================
@app.post("/api/avatar/generate")
async def generate_avatar(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    svg = generate_avatar_svg(body.get("hair_color", "#333"), body.get("eye_color", "#333"), body.get("skin_tone", "#fdbcb4"), body.get("clothing_color", "#3b82f6"))
    filename = f"{uuid.uuid4().hex}.svg"
    try:
        (AVATAR_DIR / filename).write_text(svg)
    except OSError:
        tmp_dir = Path("/tmp/bglabs_avatars")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        (tmp_dir / filename).write_text(svg)
    return {"url": f"/api/storage/avatars/{filename}", "filename": filename, "svg": svg}

# ============================================================
# VOICE CLONING
# ============================================================
@app.post("/api/voice-clone/create")
async def create_voice_clone(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    name = body.get("name", "My Voice")
    base_voice = body.get("base_voice", "en-US-AriaNeural")
    settings = {"base_voice": base_voice, "name": name}
    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow("INSERT INTO voice_profiles (user_id, name, voice_key, settings) VALUES ($1,$2,$3,$4) RETURNING id", user["id"], name, base_voice, json.dumps(settings))
                return {"id": row["id"], "name": name, "base_voice": base_voice}
        except Exception:
            pass
    return {"id": 0, "name": name, "base_voice": base_voice}

@app.get("/api/voice-clone/list")
async def list_voice_clones(request: Request):
    user = await get_current_user(request)
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM voice_profiles WHERE user_id=$1 ORDER BY created_at DESC", user["id"])
    return [dict(r) for r in rows]

@app.post("/api/voice-clone/generate")
async def generate_with_clone(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    text = body.get("text", "").strip()
    profile_id = body.get("profile_id")
    if not text:
        raise HTTPException(400, "Text is required")
    if not pool:
        raise HTTPException(503, "Database not available")
    async with pool.acquire() as conn:
        profile = await conn.fetchrow("SELECT * FROM voice_profiles WHERE id=$1 AND user_id=$2", profile_id, user["id"])
    if not profile:
        raise HTTPException(404, "Voice profile not found")
    settings = json.loads(profile["settings"])
    voice_key = settings.get("base_voice", "en-US-AriaNeural")
    try:
        audio_bytes = await edge_tts_generate(text, voice_key)
    except Exception as e:
        raise HTTPException(500, f"Voice generation failed: {str(e)}")
    filename = f"{uuid.uuid4().hex}.mp3"
    try:
        (AUDIO_DIR / filename).write_bytes(audio_bytes)
    except OSError:
        tmp_dir = Path("/tmp/bglabs_audio")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        (tmp_dir / filename).write_bytes(audio_bytes)
    return {"url": f"/api/storage/audio/{filename}", "filename": filename, "profile_name": profile["name"]}

# ============================================================
# SCRIPT WRITER
# ============================================================
@app.post("/api/script/write")
async def write_script(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    topic = body.get("topic", "").strip()
    genre = body.get("genre", "general")
    mood = body.get("mood", "neutral")
    if not topic:
        raise HTTPException(400, "Topic is required")
    templates = {
        "youtube": {"intro": f"Hey everyone! Welcome back. Today we're diving into {topic}.", "body": f"Let me break this down. {topic} is fascinating. Here's what you need to know.", "outro": f"That's it! Smash like and subscribe!"},
        "podcast": {"intro": f"Welcome to another episode. Today: {topic}.", "body": f"So {topic} has been on everyone's mind. Here's what I've discovered.", "outro": f"That wraps up today's discussion. Thanks for tuning in."},
        "presentation": {"intro": f"Good morning. Today I'll present on {topic}.", "body": f"Let's examine {topic}. The data shows clear trends we need to address.", "outro": f"In conclusion, {topic} presents opportunities. Questions?"},
        "general": {"intro": f"Today we're exploring {topic}.", "body": f"Let's dive deeper into {topic}. The fundamentals are clear.", "outro": f"That concludes our overview of {topic}."}
    }
    t = templates.get(genre, templates["general"])
    script = f"{t['intro']}\n\n{t['body']}\n\n{t['outro']}"
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute("INSERT INTO scripts (user_id, topic, genre, mood, content, word_count) VALUES ($1,$2,$3,$4,$5,$6)",
                    user["id"], topic, genre, mood, script[:2000], len(script.split()))
        except Exception:
            pass
    return {"script": script, "topic": topic, "genre": genre, "word_count": len(script.split())}

# ============================================================
# ADMIN
# ============================================================
@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    user = await get_current_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    if not pool:
        return {"total_users": 0, "total_voices": len(EDGE_VOICES), "total_audio": 0, "total_images": 0}
    async with pool.acquire() as conn:
        users = await conn.fetchval("SELECT COUNT(*) FROM users")
        audio_count = await conn.fetchval("SELECT COUNT(*) FROM audio_history")
        image_count = await conn.fetchval("SELECT COUNT(*) FROM image_history")
    return {"total_users": users, "total_voices": len(EDGE_VOICES), "total_audio": audio_count, "total_images": image_count}

@app.get("/api/admin/users")
async def admin_users(request: Request):
    user = await get_current_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM users ORDER BY created_at DESC")
    return [dict(r) for r in rows]

# ============================================================
# BILLING / REFERRAL
# ============================================================
@app.get("/api/billing/plans")
async def plans():
    return {"plans": {"free": {"name": "FREE", "price": 0, "credits": "Unlimited"}}}

@app.get("/api/billing/current")
async def current_sub(request: Request):
    user = await get_current_user(request)
    return {"tier": "free", "credits": user["credits"], "status": "active"}

@app.get("/api/referral/code")
async def get_referral_code(request: Request):
    user = await get_current_user(request)
    code = user.get("referral_code", "UNKNOWN")
    return {"referral_code": code, "referral_link": f"https://bglabs.app?ref={code}"}
