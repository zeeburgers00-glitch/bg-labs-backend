"""
BG LABS - Complete AI Platform Backend
Deploy to Vercel / any cloud - 100% FREE
cvoice.ai (20,000+ character voices) + Edge TTS + F5-TTS
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
from fastapi.responses import FileResponse, Response
import uvicorn
from dotenv import load_dotenv

from tts_engine import (
    smart_tts_generate, get_edge_voices,
    cvoice_search_characters, cvoice_get_voices,
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
VOICE_DIR = STORAGE_DIR / "voices"
SECRET_KEY = os.getenv("SECRET_KEY", "bglabs-secret-key-change-in-production")
ALGORITHM = "HS256"
DATABASE_URL = os.getenv("DATABASE_URL", "")

try:
    for d in [STORAGE_DIR, AUDIO_DIR, IMAGE_DIR, VIDEO_DIR, AVATAR_DIR, VOICE_DIR]:
        d.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

# ============================================================
# DATABASE - Neon PostgreSQL (asyncpg)
# ============================================================
pool: Optional[asyncpg.Pool] = None

async def init_db():
    global pool
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set - running without persistent database")
        return
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    username TEXT UNIQUE NOT NULL,
                    full_name TEXT DEFAULT '',
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    is_active BOOLEAN DEFAULT TRUE,
                    credits INTEGER DEFAULT 999999,
                    total_used INTEGER DEFAULT 0,
                    referral_code TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS audio_history (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    text TEXT,
                    voice TEXT,
                    language TEXT,
                    model TEXT,
                    filename TEXT,
                    url TEXT,
                    chars INTEGER,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS image_history (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    prompt TEXT,
                    style TEXT,
                    filename TEXT,
                    url TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS video_history (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    script TEXT,
                    scenes TEXT,
                    filename TEXT,
                    url TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS voice_profiles (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    name TEXT,
                    voice_key TEXT,
                    settings TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS scripts (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    topic TEXT,
                    genre TEXT,
                    mood TEXT,
                    content TEXT,
                    word_count INTEGER,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            await conn.execute("""
                INSERT INTO users (email, username, full_name, password_hash, role, referral_code)
                SELECT 'admin@bglabs.io', 'admin', 'Admin', $1, 'admin', 'ADMIN001'
                WHERE NOT EXISTS (SELECT 1 FROM users WHERE email = 'admin@bglabs.io')
            """, hashlib.sha256("BgLabs@Admin2024".encode()).hexdigest())
        logger.info("Database initialized with Neon PostgreSQL")
    except Exception as e:
        logger.error(f"Database init failed: {e}")
        pool = None

async def get_conn():
    if not pool:
        raise HTTPException(503, "Database not configured")
    return await pool.acquire()

def hash_pass(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()

def verify_pass(p: str, h: str) -> bool:
    return hash_pass(p) == h

def create_token(user_id: int) -> str:
    return jwt.encode(
        {"user_id": user_id, "exp": datetime.utcnow() + timedelta(days=30), "iat": datetime.utcnow()},
        SECRET_KEY, algorithm=ALGORITHM
    )

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
    if not user:
        raise HTTPException(401, "User not found")
    if not user["is_active"]:
        raise HTTPException(403, "Account blocked")
    return dict(user)

# ============================================================
# VOICES - Combined F5-TTS + Edge TTS
# ============================================================

# ============================================================
# IMAGE GENERATION - Pollinations.ai (FREE, no API key)
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
# VIDEO GENERATION - FFmpeg (FREE)
# ============================================================
async def create_video_from_scenes(scenes: list, output_path: str) -> str:
    if not scenes:
        raise Exception("No scenes provided")
    title = scenes[0].get("text", "BG LABS Video")[:50]
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s=1280x720:d=5",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
        "-vf", f"drawtext=text='{title}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2",
        "-c:v", "libx264", "-c:a", "aac",
        "-shortest", "-pix_fmt", "yuv420p",
        output_path
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise Exception(f"FFmpeg failed: {stderr.decode()}")
    except FileNotFoundError:
        raise Exception("FFmpeg not installed")
    return output_path

# ============================================================
# AVATAR GENERATION - SVG (FREE)
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
# KEEP-ALIVE SYSTEM
# ============================================================
keep_alive_task = None

# ============================================================
# FASTAPI APP
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
    except Exception as e:
        logger.error(f"Startup DB init failed: {e}")
    logger.info("BG LABS API started - All features FREE!")
    yield

app = FastAPI(title="BG LABS API", version="6.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/api/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")
except Exception:
    pass

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
    return {
        "access_token": token, "token_type": "bearer",
        "user": {
            "id": user["id"], "email": user["email"], "username": user["username"],
            "full_name": user["full_name"], "role": user["role"],
            "credits": user["credits"], "total_credits_used": user["total_used"],
            "is_active": user["is_active"]
        }
    }

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
    return {
        "access_token": token, "token_type": "bearer",
        "user": {
            "id": user["id"], "email": user["email"], "username": user["username"],
            "full_name": user["full_name"], "role": user["role"],
            "credits": user["credits"], "total_credits_used": user["total_used"],
            "is_active": user["is_active"]
        }
    }

@app.get("/api/auth/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    return {
        "id": user["id"], "email": user["email"], "username": user["username"],
        "full_name": user["full_name"], "role": user["role"],
        "is_active": bool(user["is_active"]), "credits": user["credits"],
        "total_credits_used": user["total_used"],
        "referral_code": user.get("referral_code", ""),
        "created_at": str(user.get("created_at", ""))
    }

@app.put("/api/auth/me")
async def update_me(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    if not pool:
        raise HTTPException(503, "Database not available")
    async with pool.acquire() as conn:
        if "full_name" in body:
            await conn.execute("UPDATE users SET full_name=$1 WHERE id=$2", body["full_name"], user["id"])
        updated = await conn.fetchrow("SELECT * FROM users WHERE id=$1", user["id"])
    u = dict(updated)
    return {
        "id": u["id"], "email": u["email"], "username": u["username"],
        "full_name": u["full_name"], "role": u["role"], "credits": u["credits"],
        "total_credits_used": u["total_used"], "is_active": u["is_active"]
    }

# ============================================================
# VOICES - cvoice.ai (20,000+) + Edge TTS (322+)
# ============================================================
@app.get("/api/voices")
async def list_voices():
    edge = get_edge_voices()
    return {"edge_voices": edge, "total_edge": len(edge), "engine": "cvoice.ai + Edge TTS"}

@app.get("/api/voices/characters")
async def search_characters(q: str = Query("", description="Search query"), limit: int = Query(50, ge=1, le=200)):
    try:
        chars = await cvoice_search_characters(q, limit)
        return {"characters": chars, "total": len(chars)}
    except Exception as e:
        raise HTTPException(500, f"Failed to load characters: {e}")

@app.get("/api/voices/characters/{username}")
async def get_character_voices(username: str):
    try:
        voices = await cvoice_get_voices(username)
        return {"username": username, "voices": voices, "total": len(voices)}
    except Exception as e:
        raise HTTPException(500, f"Failed to load voices: {e}")

# ============================================================
# TTS - cvoice.ai (Primary) + Edge TTS (Fallback)
# ============================================================
@app.post("/api/studio/generate")
async def generate_audio(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    text = body.get("text", "").strip()
    engine = body.get("engine", "cvoice")
    voice_key = body.get("voice_key", "en-US-AriaNeural")
    voice_id = body.get("voice_id", None)
    person_slug = body.get("person_slug", "")
    person_name = body.get("person_name", "")

    if not text:
        raise HTTPException(400, "Text is required")
    if len(text) > 500:
        raise HTTPException(400, "Text too long (max 500 chars for cvoice.ai)")

    try:
        audio_bytes, engine_used, voice_name = await smart_tts_generate(
            text=text,
            engine=engine,
            voice_key=voice_key,
            voice_id=voice_id,
            person_slug=person_slug,
            person_name=person_name,
        )
    except Exception as e:
        raise HTTPException(500, f"TTS failed: {str(e)}")

    filename = f"{uuid.uuid4().hex}.mp3"
    try:
        (AUDIO_DIR / filename).write_bytes(audio_bytes)
    except OSError:
        tmp_path = Path(f"/tmp/bglabs_audio/{filename}")
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_bytes(audio_bytes)

    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO audio_history (user_id, text, voice, language, model, filename, url, chars) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                    user["id"], text[:500], voice_name, "multi", engine_used, filename, f"/api/storage/audio/{filename}", len(text)
                )
                await conn.execute("UPDATE users SET total_used = total_used + $1 WHERE id = $2", len(text), user["id"])
        except Exception:
            pass

    return {
        "url": f"/api/storage/audio/{filename}",
        "filename": filename,
        "engine": engine_used,
        "voice": voice_name,
        "chars": len(text),
    }

@app.get("/api/studio/audio")
async def list_audio(request: Request):
    user = await get_current_user(request)
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM audio_history WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50", user["id"]
        )
    return [dict(r) for r in rows]

# ============================================================
# IMAGE GENERATION - FREE
# ============================================================
@app.post("/api/image/generate")
async def generate_image(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    style = body.get("style", "realistic")
    width = body.get("width", 1024)
    height = body.get("height", 1024)
    if not prompt:
        raise HTTPException(400, "Prompt is required")
    try:
        image_bytes = await generate_image_pollinations(prompt, style, width, height)
    except Exception as e:
        raise HTTPException(500, f"Image generation failed: {str(e)}")
    filename = f"{uuid.uuid4().hex}.png"
    (IMAGE_DIR / filename).write_bytes(image_bytes)
    if pool:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO image_history (user_id, prompt, style, filename, url) VALUES ($1,$2,$3,$4,$5)",
                user["id"], prompt[:500], style, filename, f"/api/storage/images/{filename}"
            )
    return {"url": f"/api/storage/images/{filename}", "filename": filename, "prompt": prompt, "style": style}

@app.get("/api/image/history")
async def image_history(request: Request):
    user = await get_current_user(request)
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM image_history WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50", user["id"]
        )
    return [dict(r) for r in rows]

# ============================================================
# VIDEO GENERATION - FREE
# ============================================================
@app.post("/api/video/generate")
async def generate_video(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    script = body.get("script", "").strip()
    scenes_text = body.get("scenes", script)
    if not script:
        raise HTTPException(400, "Script is required")
    scenes = [{"text": s.strip()} for s in scenes_text.split("\n\n") if s.strip()]
    if not scenes:
        scenes = [{"text": script}]
    filename = f"{uuid.uuid4().hex}.mp4"
    output_path = str(VIDEO_DIR / filename)
    try:
        await create_video_from_scenes(scenes, output_path)
    except Exception as e:
        filename = f"{uuid.uuid4().hex}.txt"
        (VIDEO_DIR / filename).write_text(f"Video Script:\n{script}\n\nScenes: {len(scenes)}")
        return {"url": f"/api/storage/videos/{filename}", "filename": filename, "script": script, "scenes": len(scenes), "note": "FFmpeg not available - script saved as text"}
    if pool:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO video_history (user_id, script, scenes, filename, url) VALUES ($1,$2,$3,$4,$5)",
                user["id"], script[:500], json.dumps(scenes), filename, f"/api/storage/videos/{filename}"
            )
    return {"url": f"/api/storage/videos/{filename}", "filename": filename, "script": script, "scenes": len(scenes)}

# ============================================================
# AVATAR STUDIO - FREE
# ============================================================
@app.post("/api/avatar/generate")
async def generate_avatar(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    hair_color = body.get("hair_color", "#333333")
    eye_color = body.get("eye_color", "#333333")
    skin_tone = body.get("skin_tone", "#fdbcb4")
    clothing_color = body.get("clothing_color", "#3b82f6")
    svg = generate_avatar_svg(hair_color, eye_color, skin_tone, clothing_color)
    filename = f"{uuid.uuid4().hex}.svg"
    (AVATAR_DIR / filename).write_text(svg)
    return {"url": f"/api/storage/avatars/{filename}", "filename": filename, "svg": svg}

# ============================================================
# VOICE CLONING - Profile-based (FREE)
# ============================================================
@app.post("/api/voice-clone/create")
async def create_voice_clone(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    name = body.get("name", "My Voice")
    base_voice = body.get("base_voice", "en-US-AriaNeural")
    settings = {"pitch": body.get("pitch", 1.0), "speed": body.get("speed", 1.0), "base_voice": base_voice, "name": name}
    if pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO voice_profiles (user_id, name, voice_key, settings) VALUES ($1,$2,$3,$4) RETURNING id",
                user["id"], name, base_voice, json.dumps(settings)
            )
            profile_id = row["id"]
    else:
        profile_id = 0
    return {"id": profile_id, "name": name, "base_voice": base_voice, "settings": settings}

@app.get("/api/voice-clone/list")
async def list_voice_clones(request: Request):
    user = await get_current_user(request)
    if not pool:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM voice_profiles WHERE user_id=$1 ORDER BY created_at DESC", user["id"]
        )
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
        profile = await conn.fetchrow(
            "SELECT * FROM voice_profiles WHERE id=$1 AND user_id=$2", profile_id, user["id"]
        )
    if not profile:
        raise HTTPException(404, "Voice profile not found")
    settings = json.loads(profile["settings"])
    voice_key = settings.get("base_voice", "en-US-AriaNeural")
    try:
        audio_bytes, engine_used, voice_name = await smart_tts_generate(text, engine="edge", voice_key=voice_key)
    except Exception as e:
        raise HTTPException(500, f"Voice generation failed: {str(e)}")
    filename = f"{uuid.uuid4().hex}.mp3"
    (AUDIO_DIR / filename).write_bytes(audio_bytes)
    return {"url": f"/api/storage/audio/{filename}", "filename": filename, "profile_name": profile["name"], "base_voice": voice_key}

# ============================================================
# SCRIPT WRITER - Template-based (FREE)
# ============================================================
@app.post("/api/script/write")
async def write_script(request: Request):
    user = await get_current_user(request)
    body = await request.json()
    topic = body.get("topic", "").strip()
    genre = body.get("genre", "general")
    mood = body.get("mood", "neutral")
    duration = body.get("duration", "medium")
    if not topic:
        raise HTTPException(400, "Topic is required")
    templates = {
        "youtube": {
            "intro": f"Hey everyone! Welcome back to the channel. Today we're diving into {topic}.",
            "body": f"Let me break this down for you. {topic} is something really fascinating. First, let's talk about why this matters. The key points you need to know are quite simple but powerful.",
            "outro": f"And that's it for today's video! If you found this helpful, smash that like button and subscribe for more content like this. See you in the next one!"
        },
        "podcast": {
            "intro": f"Welcome to another episode. Today's topic is {topic}. I've been thinking about this a lot lately and I have some really interesting insights to share.",
            "body": f"So let's get into it. {topic} has been on everyone's mind lately. Here's what I've discovered: the fundamentals are actually quite straightforward once you understand the core concepts.",
            "outro": f"That wraps up today's discussion on {topic}. Thanks for tuning in. Don't forget to leave a review and share this episode with someone who needs to hear it."
        },
        "presentation": {
            "intro": f"Good morning everyone. Today I'll be presenting on {topic}. This is a subject that's critical for our understanding going forward.",
            "body": f"Let's examine the key aspects of {topic}. The data shows clear trends that we need to address. Our analysis reveals three main takeaways that should guide our strategy.",
            "outro": f"In conclusion, {topic} presents both challenges and opportunities. I'm happy to take any questions at this point."
        },
        "general": {
            "intro": f"Today we're exploring {topic}. This is an important subject that affects many people.",
            "body": f"Let's dive deeper into {topic}. The fundamentals are clear: understanding this topic can make a significant difference in how we approach related challenges.",
            "outro": f"That concludes our overview of {topic}. I hope this was informative and helpful."
        }
    }
    template = templates.get(genre, templates["general"])
    word_counts = {"short": 150, "medium": 300, "long": 600}
    target_words = word_counts.get(duration, 300)
    script = f"{template['intro']}\n\n{template['body']}\n\n{template['outro']}"
    words = script.split()
    if len(words) < target_words:
        extra = f"\n\nTo elaborate further on {topic}, there are several additional aspects worth discussing. The implications are far-reaching and continue to evolve as we learn more."
        script += extra
    if pool:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO scripts (user_id, topic, genre, mood, content, word_count) VALUES ($1,$2,$3,$4,$5,$6)",
                user["id"], topic, genre, mood, script[:2000], len(script.split())
            )
    return {"script": script, "topic": topic, "genre": genre, "mood": mood, "word_count": len(script.split()), "scenes": script.split("\n\n")}

# ============================================================
# ADMIN
# ============================================================
@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    user = await get_current_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    if not pool:
        return {"total_users": 0, "active_users": 0, "total_voices": len(EDGE_VOICES), "total_audio": 0, "total_images": 0, "total_videos": 0, "total_credits_used": 0}
    async with pool.acquire() as conn:
        users = await conn.fetchval("SELECT COUNT(*) FROM users")
        audio_count = await conn.fetchval("SELECT COUNT(*) FROM audio_history")
        image_count = await conn.fetchval("SELECT COUNT(*) FROM image_history")
        video_count = await conn.fetchval("SELECT COUNT(*) FROM video_history")
        total_chars = await conn.fetchval("SELECT COALESCE(SUM(total_used), 0) FROM users")
    return {
        "total_users": users, "active_users": users, "total_voices": len(EDGE_VOICES),
        "total_audio": audio_count, "total_images": image_count, "total_videos": video_count,
        "total_credits_used": total_chars
    }

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

@app.put("/api/admin/users/{user_id}")
async def admin_update_user(user_id: int, request: Request):
    admin = await get_current_user(request)
    if admin["role"] != "admin":
        raise HTTPException(403, "Admin only")
    body = await request.json()
    if not pool:
        raise HTTPException(503, "Database not available")
    async with pool.acquire() as conn:
        if "credits" in body:
            await conn.execute("UPDATE users SET credits=$1 WHERE id=$2", body["credits"], user_id)
        if "is_active" in body:
            await conn.execute("UPDATE users SET is_active=$1 WHERE id=$2", body["is_active"], user_id)
        user = await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return dict(user)

# ============================================================
# BILLING
# ============================================================
@app.get("/api/billing/plans")
async def plans():
    return {
        "plans": {
            "free": {"name": "FREE", "price": 0, "credits": "Unlimited"},
            "pro": {"name": "PRO", "price": 9.99, "credits": "Unlimited + Priority"},
            "enterprise": {"name": "ENTERPRISE", "price": 49.99, "credits": "Unlimited + API + Custom"}
        }
    }

@app.get("/api/billing/current")
async def current_sub(request: Request):
    user = await get_current_user(request)
    return {"tier": "free", "credits": user["credits"], "status": "active"}

# ============================================================
# REFERRAL
# ============================================================
@app.get("/api/referral/code")
async def get_referral_code(request: Request):
    user = await get_current_user(request)
    code = user.get("referral_code", "UNKNOWN")
    return {"referral_code": code, "referral_link": f"https://bglabs.app?ref={code}"}

# ============================================================
# KEEP-ALIVE ENDPOINT
# ============================================================
@app.get("/keep-alive")
async def keep_alive():
    return {"status": "alive", "timestamp": datetime.utcnow().isoformat(), "version": "6.0.0"}

# ============================================================
# ROOT & HEALTH
# ============================================================
@app.get("/")
async def root():
    html_path = BASE_DIR / "bglabs_complete.html"
    if html_path.exists():
        return FileResponse(str(html_path), media_type="text/html")
    return {
        "name": "BG LABS API", "version": "8.0.0", "status": "running",
        "engines": ["cvoice.ai (20,000+ character voices)", "Edge-TTS (322+ voices)"],
        "features": [
            "Character TTS (cvoice.ai - 20,000+ voices)",
            "Edge TTS (322+ neural voices)",
            "Voice Cloning",
            "Image Gen (Pollinations.ai - FREE)",
            "Video Gen (FFmpeg)",
            "Avatar Studio",
            "Script Writer"
        ],
        "voices": "20,000+",
        "database": "Neon PostgreSQL" if pool else "Not connected"
    }

@app.get("/health")
async def health():
    db_ok = False
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_ok = True
        except Exception:
            pass
    return {"status": "healthy", "version": "6.0.0", "database": db_ok}

# ============================================================
if __name__ == "__main__":
    print("BG LABS v6.0 - Starting with Neon PostgreSQL...")
    port = int(os.getenv("PORT", 7860))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
