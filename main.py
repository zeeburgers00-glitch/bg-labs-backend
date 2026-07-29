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
from typing import Optional, Dict
from collections import defaultdict
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
# RATE LIMITING (in-memory, per-IP)
# ============================================================
_rate_limits: Dict[str, list] = defaultdict(list)
RATE_LIMIT_GENERATE = 30  # max generations per minute
RATE_LIMIT_AUTH = 10  # max auth attempts per minute

def check_rate_limit(ip: str, action: str = "generate", limit: int = 30, window: int = 60) -> bool:
    now = time.time()
    key = f"{ip}:{action}"
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < window]
    if len(_rate_limits[key]) >= limit:
        return False
    _rate_limits[key].append(now)
    return True

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

def get_client_ip(request: Request) -> str:
    return request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")

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
        "cinematic": "cinematic lighting, dramatic, movie quality",
        "portrait": "portrait photography, studio lighting, detailed face",
        "landscape": "landscape photography, golden hour, scenic",
        "fantasy": "fantasy art, magical, ethereal",
        "minimalist": "minimalist design, clean, simple",
        "comic": "comic book style, bold lines, vibrant",
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
        <defs>
            <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:{clothing_color};stop-opacity:0.15"/>
                <stop offset="100%" style="stop-color:{clothing_color};stop-opacity:0.05"/>
            </linearGradient>
            <radialGradient id="glow">
                <stop offset="0%" style="stop-color:{clothing_color};stop-opacity:0.2"/>
                <stop offset="100%" style="stop-color:{clothing_color};stop-opacity:0"/>
            </radialGradient>
        </defs>
        <circle cx="100" cy="100" r="95" fill="url(#bg)"/>
        <circle cx="100" cy="100" r="80" fill="url(#glow)"/>
        <circle cx="100" cy="85" r="55" fill="{hair_color}"/>
        <circle cx="100" cy="100" r="45" fill="{skin_tone}"/>
        <circle cx="80" cy="92" r="8" fill="white"/>
        <circle cx="120" cy="92" r="8" fill="white"/>
        <circle cx="80" cy="92" r="5" fill="{eye_color}"/>
        <circle cx="120" cy="92" r="5" fill="{eye_color}"/>
        <circle cx="80" cy="90" r="1.5" fill="white"/>
        <circle cx="120" cy="90" r="1.5" fill="white"/>
        <path d="M 85 105 Q 100 115 115 105" stroke="{clothing_color}" fill="none" stroke-width="2.5" stroke-linecap="round"/>
        <ellipse cx="100" cy="145" rx="40" ry="25" fill="{clothing_color}"/>
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
    ip = get_client_ip(request)
    
    if not check_rate_limit(ip, "generate", RATE_LIMIT_GENERATE, 60):
        raise HTTPException(429, "Too many requests. Please wait a moment.")
    
    body = await request.json()
    text = body.get("text", "").strip()
    voice_key = body.get("voice_key", "en-US-AriaNeural")
    rate = body.get("rate", "+0%")
    pitch = body.get("pitch", "+0Hz")

    if not text:
        raise HTTPException(400, "Text is required")
    if len(text) > 10000:
        raise HTTPException(400, "Text too long (max 10,000 chars)")

    try:
        audio_bytes = await edge_tts_generate(text, voice_key, rate=rate, pitch=pitch)
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

@app.get("/api/studio/audio/download/{filename}")
async def download_audio(filename: str):
    filepath = AUDIO_DIR / filename
    if not filepath.exists():
        tmp_path = Path("/tmp/bglabs_audio") / filename
        if tmp_path.exists():
            filepath = tmp_path
        else:
            raise HTTPException(404, "Audio file not found")
    return FileResponse(str(filepath), media_type="audio/mpeg", filename=f"bglabs_{filename}")

@app.get("/api/voices/languages")
async def list_languages():
    langs = {}
    for key, info in EDGE_VOICES.items():
        lang = info.get("lang", "en")
        if lang not in langs:
            langs[lang] = {"code": lang, "name": info.get("accent", lang), "voices": []}
        langs[lang]["voices"].append(key)
    return {"languages": list(langs.values()), "total": len(langs)}

# ============================================================
# IMAGE GENERATION
# ============================================================
@app.post("/api/image/generate")
async def generate_image(request: Request):
    user = await get_current_user(request)
    ip = get_client_ip(request)
    
    if not check_rate_limit(ip, "image", 10, 60):
        raise HTTPException(429, "Too many image requests. Please wait.")
    
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

@app.get("/api/image/styles")
async def list_image_styles():
    return {"styles": [
        {"id": "realistic", "name": "Realistic", "icon": "📷", "desc": "Photorealistic images"},
        {"id": "anime", "name": "Anime", "icon": "🎌", "desc": "Japanese anime style"},
        {"id": "oil_painting", "name": "Oil Painting", "icon": "🎨", "desc": "Classical oil painting"},
        {"id": "digital_art", "name": "Digital Art", "icon": "💻", "desc": "Digital concept art"},
        {"id": "watercolor", "name": "Watercolor", "icon": "🖌️", "desc": "Soft watercolor painting"},
        {"id": "3d_render", "name": "3D Render", "icon": "🧊", "desc": "3D rendered scenes"},
        {"id": "pixel_art", "name": "Pixel Art", "icon": "👾", "desc": "Retro pixel art"},
        {"id": "cyberpunk", "name": "Cyberpunk", "icon": "🌃", "desc": "Futuristic neon style"},
        {"id": "cinematic", "name": "Cinematic", "icon": "🎬", "desc": "Movie-quality stills"},
        {"id": "portrait", "name": "Portrait", "icon": "👤", "desc": "Studio portrait photos"},
        {"id": "landscape", "name": "Landscape", "icon": "🌄", "desc": "Scenic landscape photos"},
        {"id": "fantasy", "name": "Fantasy", "icon": "🧙", "desc": "Magical fantasy art"},
        {"id": "minimalist", "name": "Minimalist", "icon": "⬜", "desc": "Clean minimal design"},
        {"id": "comic", "name": "Comic Book", "icon": "💥", "desc": "Bold comic book style"},
    ]}

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
    length = body.get("length", "medium")
    if not topic:
        raise HTTPException(400, "Topic is required")
    
    templates = {
        "youtube": {
            "short": {"intro": f"Hey! Quick video on {topic}.", "body": f"Here's what you need to know about {topic}.", "outro": "Like & subscribe!"},
            "medium": {"intro": f"Hey everyone! Welcome back. Today we're diving into {topic}.", "body": f"Let me break this down. {topic} is fascinating. Here's what you need to know. First, the basics. Then we'll go deeper. And finally, the key takeaways.", "outro": f"That's it! Smash like and subscribe for more content like this!"},
            "long": {"intro": f"Hey everyone! Welcome back to the channel. Today we're going to do a deep dive into {topic}. This is something I've been wanting to cover for a while now, and I think you're going to find this really valuable.", "body": f"Let's start with the basics. {topic} has been gaining a lot of attention recently, and for good reason. The fundamentals are solid, and there's a lot to unpack here.\n\nFirst, let's talk about why {topic} matters. In today's landscape, understanding this can give you a significant advantage.\n\nNow, let's look at the key aspects. There are several important points to consider.\n\nFinally, let me share my personal take on {topic} and what I think the future holds.", "outro": f"And that wraps up our deep dive into {topic}! If you found this helpful, please hit that like button and subscribe. Drop a comment below with your thoughts. See you in the next one!"}
        },
        "podcast": {
            "short": f"Welcome. Today: {topic}. Let's dive in.",
            "medium": f"Welcome to another episode. Today we're exploring {topic}. So {topic} has been on everyone's mind. Here's what I've discovered through research and experience. The first thing to understand is... The second key point is... And that brings us to the bigger picture. That wraps up today's discussion on {topic}. Thanks for tuning in.",
            "long": f"Welcome to another episode of our podcast. I'm your host, and today we have a really exciting topic to discuss: {topic}.\n\nNow, {topic} is something that's been generating a lot of buzz lately, and I wanted to take some time to really dig into it.\n\nLet's start from the beginning. {topic} first came to my attention when... Since then, I've been researching extensively, and here's what I've found.\n\nThe first major insight about {topic} is... This is crucial because...\n\nMoving on to the second point... This is where things get really interesting.\n\nAnd finally, the third key takeaway... This ties everything together nicely.\n\nThat's all for today's episode on {topic}. I hope you found this valuable. If you did, please share it with someone who needs to hear this. Until next time!"
        },
        "presentation": {
            "short": f"Today I'll present on {topic}. Let's begin.",
            "medium": f"Good morning everyone. Today I'll be presenting on {topic}. Let's examine the key aspects. First, the overview. {topic} is a critical area that impacts many industries. The data shows clear trends. Let's look at the numbers. In conclusion, {topic} presents significant opportunities. Thank you for your attention. Questions?",
            "long": f"Good morning everyone, and thank you for being here today. My name is [Name], and I'll be presenting on {topic}.\n\nLet me start with an overview. {topic} has become increasingly important in recent years, and understanding it is crucial for success.\n\nFirst, let's look at the background. {topic} emerged as a key area of focus when... The initial research showed promising results.\n\nNow, let's examine the current state. The data clearly indicates several important trends.\n\nLooking at the numbers, we can see that... This represents a significant shift in how we approach {topic}.\n\nMoving forward, the opportunities are substantial. Organizations that embrace {topic} stand to gain a competitive advantage.\n\nIn conclusion, {topic} is not just a trend, it's a fundamental shift. I recommend we take proactive steps to capitalize on these opportunities.\n\nThank you for your attention. I'm happy to take any questions."
        },
        "ad": {
            "short": f"Tired of the ordinary? Try {topic}. Transform your experience today.",
            "medium": f"Introducing {topic} - the game changer you've been waiting for. Whether you're a beginner or expert, {topic} delivers results. Join thousands who've already made the switch. Don't miss out. Try {topic} today and see the difference.",
            "long": f"Are you tired of settling for less? It's time to experience {topic}.\n\nHere's the thing - most people struggle with this exact problem. And that's exactly why {topic} was created.\n\nWith {topic}, you get: First, unmatched quality that speaks for itself. Second, a seamless experience from start to finish. And third, results that speak louder than words.\n\nDon't just take our word for it. Join the thousands of satisfied users who've already transformed their experience.\n\n{topic} - because you deserve better. Try it free today."
        },
        "general": {
            "short": f"Today: {topic}. Here's what you need to know.",
            "medium": f"Today we're exploring {topic}. Let's dive deeper into this fascinating subject. The fundamentals are clear. {topic} has evolved significantly. Here are the key points to understand. First, the basics. Then the advanced concepts. And finally, practical applications. That concludes our overview of {topic}.",
            "long": f"Today we're going to take an in-depth look at {topic}. This is a subject that many people are curious about, and for good reason.\n\nLet's start with the fundamentals. {topic} encompasses several key elements that work together.\n\nThe first aspect to consider is... This is foundational to understanding the bigger picture.\n\nNext, let's explore... This is where things get particularly interesting.\n\nWe should also discuss... This adds another layer of complexity and nuance.\n\nFinally, the practical applications of {topic} are vast and growing. Understanding these can provide significant advantages.\n\nThat concludes our comprehensive overview of {topic}. I hope this has been informative and valuable."
        }
    }
    
    t = templates.get(genre, templates["general"])
    if isinstance(t, dict):
        script = t.get(length, t.get("medium", ""))
    else:
        script = t
    
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute("INSERT INTO scripts (user_id, topic, genre, mood, content, word_count) VALUES ($1,$2,$3,$4,$5,$6)",
                    user["id"], topic, genre, mood, script[:2000], len(script.split()))
        except Exception:
            pass
    return {"script": script, "topic": topic, "genre": genre, "mood": mood, "length": length, "word_count": len(script.split())}

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
