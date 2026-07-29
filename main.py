"""
BG LABS - Complete AI Platform Backend
Deploy to Hugging Face Spaces
FREE Unlimited: TTS, Image Gen, Video, Voice Cloning, Avatars
"""
import os
import json
import uuid
import time
import asyncio
import hashlib
import sqlite3
import jwt
import edge_tts
import httpx
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from io import BytesIO

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

# ============================================================
# CONFIG
# ============================================================
BASE_DIR = Path(__file__).parent
STORAGE_DIR = BASE_DIR / "storage"
AUDIO_DIR = STORAGE_DIR / "audio"
IMAGE_DIR = STORAGE_DIR / "images"
VIDEO_DIR = STORAGE_DIR / "videos"
AVATAR_DIR = STORAGE_DIR / "avatars"
VOICE_DIR = STORAGE_DIR / "voices"
DB_PATH = BASE_DIR / "bg_labs.db"
SECRET_KEY = os.getenv("SECRET_KEY", "bglabs-secret-key-2024-free-unlimited")
ALGORITHM = "HS256"

for d in [STORAGE_DIR, AUDIO_DIR, IMAGE_DIR, VIDEO_DIR, AVATAR_DIR, VOICE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# DATABASE
# ============================================================
def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT DEFAULT '',
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            is_active INTEGER DEFAULT 1,
            credits INTEGER DEFAULT 999999,
            total_used INTEGER DEFAULT 0,
            referral_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS audio_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, text TEXT, voice TEXT, language TEXT,
            model TEXT, filename TEXT, url TEXT, chars INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS image_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, prompt TEXT, style TEXT,
            filename TEXT, url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS video_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, script TEXT, scenes TEXT,
            filename TEXT, url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS voice_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, name TEXT, voice_key TEXT,
            settings TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def hash_pass(p): return hashlib.sha256(p.encode()).hexdigest()
def verify_pass(p, h): return hash_pass(p) == h

def create_token(user_id: int) -> str:
    return jwt.encode({"user_id": user_id, "exp": datetime.utcnow() + timedelta(days=30), "iat": datetime.utcnow()}, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[int]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]).get("user_id")
    except: return None

def get_current_user(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "): raise HTTPException(401, "No token")
    user_id = decode_token(auth.replace("Bearer ", ""))
    if not user_id: raise HTTPException(401, "Invalid token")
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if not user: raise HTTPException(401, "User not found")
    if not user["is_active"]: raise HTTPException(403, "Blocked")
    return dict(user)

# ============================================================
# EDGE TTS - FREE UNLIMITED
# ============================================================
EDGE_VOICES = {
    "aria": {"name": "Aria", "voice": "en-US-AriaNeural", "gender": "Female", "lang": "en", "accent": "American", "color": "#a855f7"},
    "jenny": {"name": "Jenny", "voice": "en-US-JennyNeural", "gender": "Female", "lang": "en", "accent": "American", "color": "#ec4899"},
    "sara": {"name": "Sara", "voice": "en-US-SaraNeural", "gender": "Female", "lang": "en", "accent": "American", "color": "#f97316"},
    "tony": {"name": "Tony", "voice": "en-US-TonyNeural", "gender": "Male", "lang": "en", "accent": "American", "color": "#06b6d4"},
    "guy": {"name": "Guy", "voice": "en-US-GuyNeural", "gender": "Male", "lang": "en", "accent": "American", "color": "#84cc16"},
    "davis": {"name": "Davis", "voice": "en-US-DavisNeural", "gender": "Male", "lang": "en", "accent": "American", "color": "#3b82f6"},
    "sonia": {"name": "Sonia", "voice": "en-GB-SoniaNeural", "gender": "Female", "lang": "en", "accent": "British", "color": "#0ea5e9"},
    "ryan": {"name": "Ryan", "voice": "en-GB-RyanNeural", "gender": "Male", "lang": "en", "accent": "British", "color": "#64748b"},
    "urdu_female": {"name": "Asma", "voice": "ur-PK-UzmaNeural", "gender": "Female", "lang": "ur", "accent": "Pakistani", "color": "#ef4444"},
    "urdu_male": {"name": "Salman", "voice": "ur-PK-SalmanNeural", "gender": "Male", "lang": "ur", "accent": "Pakistani", "color": "#8b5cf6"},
    "hindi_female": {"name": "Swara", "voice": "hi-IN-SwaraNeural", "gender": "Female", "lang": "hi", "accent": "Indian", "color": "#f59e0b"},
    "hindi_male": {"name": "Madhur", "voice": "hi-IN-MadhurNeural", "gender": "Male", "lang": "hi", "accent": "Indian", "color": "#10b981"},
    "arabic_female": {"name": "Fatima", "voice": "ar-SA-FatimaNeural", "gender": "Female", "lang": "ar", "accent": "Arabic", "color": "#14b8a6"},
    "arabic_male": {"name": "Hamed", "voice": "ar-SA-HamedNeural", "gender": "Male", "lang": "ar", "accent": "Arabic", "color": "#6366f1"},
    "chinese_female": {"name": "Xiaoxiao", "voice": "zh-CN-XiaoxiaoNeural", "gender": "Female", "lang": "zh", "accent": "Chinese", "color": "#f43f5e"},
    "japanese_female": {"name": "Nanami", "voice": "ja-JP-NanamiNeural", "gender": "Female", "lang": "ja", "accent": "Japanese", "color": "#c084fc"},
    "korean_female": {"name": "SunHi", "voice": "ko-KR-SunHiNeural", "gender": "Female", "lang": "ko", "accent": "Korean", "color": "#22d3ee"},
    "spanish_female": {"name": "Elvira", "voice": "es-ES-ElviraNeural", "gender": "Female", "lang": "es", "accent": "Spanish", "color": "#e879f9"},
    "french_female": {"name": "Denise", "voice": "fr-FR-DeniseNeural", "gender": "Female", "lang": "fr", "accent": "French", "color": "#fb923c"},
    "german_female": {"name": "Katja", "voice": "de-DE-KatjaNeural", "gender": "Female", "lang": "de", "accent": "German", "color": "#22c55e"},
    "portuguese_female": {"name": "Francisca", "voice": "pt-BR-FranciscaNeural", "gender": "Female", "lang": "pt", "accent": "Brazilian", "color": "#818cf8"},
    "italian_female": {"name": "Elsa", "voice": "it-IT-ElsaNeural", "gender": "Female", "lang": "it", "accent": "Italian", "color": "#f472b6"},
    "turkish_female": {"name": "Emel", "voice": "tr-TR-EmelNeural", "gender": "Female", "lang": "tr", "accent": "Turkish", "color": "#a3e635"},
    "russian_female": {"name": "Svetlana", "voice": "ru-RU-SvetlanaNeural", "gender": "Female", "lang": "ru", "accent": "Russian", "color": "#38bdf8"},
}

async def edge_tts_generate(text: str, voice_key: str = "aria") -> bytes:
    voice_info = EDGE_VOICES.get(voice_key, EDGE_VOICES["aria"])
    communicate = edge_tts.Communicate(text, voice_info["voice"])
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    if not audio_data: raise Exception("TTS returned empty audio")
    return audio_data

# ============================================================
# IMAGE GENERATION - Pollinations.ai (FREE)
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
    """Create video from scenes (images + audio) using FFmpeg"""
    if not scenes:
        raise Exception("No scenes provided")
    
    # Create a simple slideshow video with TTS audio
    # For now, create a title card video with text overlay
    title = scenes[0].get("text", "BG LABS Video")[:50]
    
    # Use FFmpeg to create a simple video
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
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise Exception(f"FFmpeg failed: {stderr.decode()}")
    except FileNotFoundError:
        # FFmpeg not installed - create placeholder
        raise Exception("FFmpeg not installed. Video generation requires FFmpeg.")
    
    return output_path

# ============================================================
# AVATAR GENERATION - SVG-based (FREE)
# ============================================================
def generate_avatar_svg(hair_color: str = "#333", eye_color: str = "#333", skin_tone: str = "#fdbcb4", clothing_color: str = "#3b82f6") -> str:
    """Generate SVG avatar"""
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
app = FastAPI(title="BG LABS API", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/api/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")

@app.on_event("startup")
async def startup():
    init_db()
    print("BG LABS API v5.0 started - All features FREE!")

# ============================================================
# AUTH
# ============================================================
@app.post("/api/auth/register")
async def register(email: str = Form(...), username: str = Form(...), full_name: str = Form(""), password: str = Form(...)):
    conn = get_db()
    try:
        existing = conn.execute("SELECT 1 FROM users WHERE email=? OR username=?", (email, username)).fetchone()
        if existing: raise HTTPException(400, "Email or username already exists")
        code = uuid.uuid4().hex[:8]
        cursor = conn.execute("INSERT INTO users (email, username, full_name, password_hash, referral_code) VALUES (?,?,?,?,?)",
            (email, username, full_name, hash_pass(password), code))
        conn.commit()
        user_id = cursor.lastrowid
        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        conn.close()
        token = create_token(user_id)
        return {"access_token": token, "token_type": "bearer",
                "user": {"id": user["id"], "email": user["email"], "username": user["username"],
                         "full_name": user["full_name"], "role": user["role"], "credits": user["credits"]}}
    except HTTPException: raise
    except Exception as e:
        conn.close(); raise HTTPException(500, str(e))

@app.post("/api/auth/login")
async def login(username: str = Form(...), password: str = Form(...)):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username=? OR email=?", (username, username)).fetchone()
    conn.close()
    if not user: raise HTTPException(401, "User not found")
    if not verify_pass(password, user["password_hash"]): raise HTTPException(401, "Incorrect password")
    if not user["is_active"]: raise HTTPException(403, "Account blocked")
    token = create_token(user["id"])
    return {"access_token": token, "token_type": "bearer",
            "user": {"id": user["id"], "email": user["email"], "username": user["username"],
                     "full_name": user["full_name"], "role": user["role"], "credits": user["credits"]}}

@app.get("/api/auth/me")
async def get_me(request: Request):
    user = get_current_user(request)
    return {"id": user["id"], "email": user["email"], "username": user["username"],
            "full_name": user["full_name"], "role": user["role"], "is_active": bool(user["is_active"]),
            "credits": user["credits"], "total_credits_used": user["total_used"],
            "referral_code": user["referral_code"], "created_at": user["created_at"]}

@app.put("/api/auth/me")
async def update_me(request: Request):
    user = get_current_user(request)
    body = await request.json()
    conn = get_db()
    if "full_name" in body: conn.execute("UPDATE users SET full_name=? WHERE id=?", (body["full_name"], user["id"]))
    conn.commit()
    updated = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    conn.close()
    return {"id": updated["id"], "email": updated["email"], "username": updated["username"],
            "full_name": updated["full_name"], "role": updated["role"], "credits": updated["credits"]}

# ============================================================
# VOICES
# ============================================================
@app.get("/api/voices")
async def list_voices():
    voices = [{"key": k, "name": v["name"], "gender": v["gender"], "accent": v["accent"],
               "lang": v["lang"], "color": v["color"], "desc": f"{v['gender']} {v['accent']} voice"}
              for k, v in EDGE_VOICES.items()]
    return {"voices": voices, "total": len(voices), "engine": "Edge TTS (FREE)"}

# ============================================================
# TTS - FREE UNLIMITED
# ============================================================
@app.post("/api/studio/generate")
async def generate_audio(request: Request):
    user = get_current_user(request)
    body = await request.json()
    text = body.get("text", "").strip()
    voice_key = body.get("voice_key", "aria")
    if not text: raise HTTPException(400, "Text is required")
    if len(text) > 10000: raise HTTPException(400, "Text too long (max 10,000 chars)")
    
    try:
        audio_bytes = await edge_tts_generate(text, voice_key)
    except Exception as e:
        raise HTTPException(500, f"TTS failed: {str(e)}")
    
    filename = f"{uuid.uuid4().hex}.mp3"
    (AUDIO_DIR / filename).write_bytes(audio_bytes)
    
    voice_info = EDGE_VOICES.get(voice_key, EDGE_VOICES["aria"])
    conn = get_db()
    conn.execute("INSERT INTO audio_history (user_id, text, voice, language, model, filename, url, chars) VALUES (?,?,?,?,?,?,?,?)",
        (user["id"], text[:500], voice_key, voice_info["lang"], "Edge TTS", filename, f"/api/storage/audio/{filename}", len(text)))
    conn.execute("UPDATE users SET total_used = total_used + ? WHERE id = ?", (len(text), user["id"]))
    conn.commit(); conn.close()
    
    return {"url": f"/api/storage/audio/{filename}", "filename": filename,
            "model_used": "Edge TTS (FREE)", "chars": len(text), "voice": voice_info["name"]}

@app.get("/api/studio/audio")
async def list_audio(request: Request):
    user = get_current_user(request)
    conn = get_db()
    history = conn.execute("SELECT * FROM audio_history WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (user["id"],)).fetchall()
    conn.close()
    return [dict(h) for h in history]

# ============================================================
# IMAGE GENERATION - FREE
# ============================================================
@app.post("/api/image/generate")
async def generate_image(request: Request):
    user = get_current_user(request)
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    style = body.get("style", "realistic")
    width = body.get("width", 1024)
    height = body.get("height", 1024)
    
    if not prompt: raise HTTPException(400, "Prompt is required")
    
    try:
        image_bytes = await generate_image_pollinations(prompt, style, width, height)
    except Exception as e:
        raise HTTPException(500, f"Image generation failed: {str(e)}")
    
    filename = f"{uuid.uuid4().hex}.png"
    (IMAGE_DIR / filename).write_bytes(image_bytes)
    
    conn = get_db()
    conn.execute("INSERT INTO image_history (user_id, prompt, style, filename, url) VALUES (?,?,?,?,?)",
        (user["id"], prompt[:500], style, filename, f"/api/storage/images/{filename}"))
    conn.commit(); conn.close()
    
    return {"url": f"/api/storage/images/{filename}", "filename": filename,
            "prompt": prompt, "style": style}

@app.get("/api/image/history")
async def image_history(request: Request):
    user = get_current_user(request)
    conn = get_db()
    history = conn.execute("SELECT * FROM image_history WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (user["id"],)).fetchall()
    conn.close()
    return [dict(h) for h in history]

# ============================================================
# VIDEO GENERATION - FREE
# ============================================================
@app.post("/api/video/generate")
async def generate_video(request: Request):
    user = get_current_user(request)
    body = await request.json()
    script = body.get("script", "").strip()
    scenes_text = body.get("scenes", script)
    
    if not script: raise HTTPException(400, "Script is required")
    
    # Split script into scenes
    scenes = [{"text": s.strip()} for s in scenes_text.split("\n\n") if s.strip()]
    if not scenes:
        scenes = [{"text": script}]
    
    filename = f"{uuid.uuid4().hex}.mp4"
    output_path = str(VIDEO_DIR / filename)
    
    try:
        await create_video_from_scenes(scenes, output_path)
    except Exception as e:
        # Create a text-based placeholder
        filename = f"{uuid.uuid4().hex}.txt"
        (VIDEO_DIR / filename).write_text(f"Video Script:\n{script}\n\nScenes: {len(scenes)}")
        return {"url": f"/api/storage/videos/{filename}", "filename": filename,
                "script": script, "scenes": len(scenes), "note": "FFmpeg not available - script saved as text"}
    
    conn = get_db()
    conn.execute("INSERT INTO video_history (user_id, script, scenes, filename, url) VALUES (?,?,?,?,?)",
        (user["id"], script[:500], json.dumps(scenes), filename, f"/api/storage/videos/{filename}"))
    conn.commit(); conn.close()
    
    return {"url": f"/api/storage/videos/{filename}", "filename": filename,
            "script": script, "scenes": len(scenes)}

# ============================================================
# AVATAR STUDIO - FREE
# ============================================================
@app.post("/api/avatar/generate")
async def generate_avatar(request: Request):
    user = get_current_user(request)
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
    user = get_current_user(request)
    body = await request.json()
    name = body.get("name", "My Voice")
    base_voice = body.get("base_voice", "aria")
    settings = {
        "pitch": body.get("pitch", 1.0),
        "speed": body.get("speed", 1.0),
        "base_voice": base_voice,
        "name": name,
    }
    
    conn = get_db()
    cursor = conn.execute("INSERT INTO voice_profiles (user_id, name, voice_key, settings) VALUES (?,?,?,?)",
        (user["id"], name, base_voice, json.dumps(settings)))
    conn.commit()
    profile_id = cursor.lastrowid
    conn.close()
    
    return {"id": profile_id, "name": name, "base_voice": base_voice, "settings": settings}

@app.get("/api/voice-clone/list")
async def list_voice_clones(request: Request):
    user = get_current_user(request)
    conn = get_db()
    profiles = conn.execute("SELECT * FROM voice_profiles WHERE user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
    conn.close()
    return [dict(p) for p in profiles]

@app.post("/api/voice-clone/generate")
async def generate_with_clone(request: Request):
    user = get_current_user(request)
    body = await request.json()
    text = body.get("text", "").strip()
    profile_id = body.get("profile_id")
    
    if not text: raise HTTPException(400, "Text is required")
    
    # Get voice profile
    conn = get_db()
    profile = conn.execute("SELECT * FROM voice_profiles WHERE id=? AND user_id=?", (profile_id, user["id"])).fetchone()
    conn.close()
    
    if not profile: raise HTTPException(404, "Voice profile not found")
    
    settings = json.loads(profile["settings"])
    voice_key = settings.get("base_voice", "aria")
    
    # Generate TTS with base voice
    try:
        audio_bytes = await edge_tts_generate(text, voice_key)
    except Exception as e:
        raise HTTPException(500, f"Voice generation failed: {str(e)}")
    
    filename = f"{uuid.uuid4().hex}.mp3"
    (AUDIO_DIR / filename).write_bytes(audio_bytes)
    
    return {"url": f"/api/storage/audio/{filename}", "filename": filename,
            "profile_name": profile["name"], "base_voice": voice_key}

# ============================================================
# SCRIPT WRITER - Template-based (FREE)
# ============================================================
@app.post("/api/script/write")
async def write_script(request: Request):
    user = get_current_user(request)
    body = await request.json()
    topic = body.get("topic", "").strip()
    genre = body.get("genre", "general")
    mood = body.get("mood", "neutral")
    duration = body.get("duration", "medium")
    
    if not topic: raise HTTPException(400, "Topic is required")
    
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
    
    # Pad or trim to approximate length
    words = script.split()
    if len(words) < target_words:
        extra = f"\n\nTo elaborate further on {topic}, there are several additional aspects worth discussing. The implications are far-reaching and continue to evolve as we learn more."
        script += extra
    
    return {"script": script, "topic": topic, "genre": genre, "mood": mood,
            "word_count": len(script.split()), "scenes": script.split("\n\n")}

# ============================================================
# ADMIN
# ============================================================
@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    user = get_current_user(request)
    if user["role"] != "admin": raise HTTPException(403, "Admin only")
    conn = get_db()
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    audio_count = conn.execute("SELECT COUNT(*) FROM audio_history").fetchone()[0]
    image_count = conn.execute("SELECT COUNT(*) FROM image_history").fetchone()[0]
    video_count = conn.execute("SELECT COUNT(*) FROM video_history").fetchone()[0]
    total_chars = conn.execute("SELECT SUM(total_used) FROM users").fetchone()[0] or 0
    conn.close()
    return {"total_users": users, "active_users": users, "total_voices": len(EDGE_VOICES),
            "total_audio": audio_count, "total_images": image_count, "total_videos": video_count,
            "total_credits_used": total_chars}

@app.get("/api/admin/users")
async def admin_users(request: Request):
    user = get_current_user(request)
    if user["role"] != "admin": raise HTTPException(403, "Admin only")
    conn = get_db()
    users = [dict(u) for u in conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()]
    conn.close()
    return users

@app.put("/api/admin/users/{user_id}")
async def admin_update_user(user_id: int, request: Request):
    admin = get_current_user(request)
    if admin["role"] != "admin": raise HTTPException(403, "Admin only")
    body = await request.json()
    conn = get_db()
    if "credits" in body: conn.execute("UPDATE users SET credits=? WHERE id=?", (body["credits"], user_id))
    if "is_active" in body: conn.execute("UPDATE users SET is_active=? WHERE id=?", (1 if body["is_active"] else 0, user_id))
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if not user: raise HTTPException(404, "User not found")
    return dict(user)

# ============================================================
# BILLING
# ============================================================
@app.get("/api/billing/plans")
async def plans():
    return {"plans": {"free": {"name": "FREE", "price": 0, "credits": "Unlimited"},
                      "pro": {"name": "PRO", "price": 9.99, "credits": "Unlimited + Priority"},
                      "enterprise": {"name": "ENTERPRISE", "price": 49.99, "credits": "Unlimited + API + Custom"}}}

@app.get("/api/billing/current")
async def current_sub(request: Request):
    user = get_current_user(request)
    return {"tier": "free", "credits": user["credits"], "status": "active"}

# ============================================================
# REFERRAL
# ============================================================
@app.get("/api/referral/code")
async def get_referral_code(request: Request):
    user = get_current_user(request)
    return {"referral_code": user["referral_code"], "referral_link": f"https://bglabs.app?ref={user['referral_code']}"}

# ============================================================
# ROOT
# ============================================================
@app.get("/")
async def root():
    return {"name": "BG LABS API", "version": "5.0.0", "status": "running",
            "features": ["TTS (Edge - FREE)", "Image Gen (Pollinations - FREE)", "Video Gen (FFmpeg)",
                         "Voice Cloning", "Avatar Studio", "Script Writer"],
            "voices": len(EDGE_VOICES)}

@app.get("/health")
async def health():
    return {"status": "healthy", "version": "5.0.0"}

# ============================================================
if __name__ == "__main__":
    print("BG LABS v5.0 - Starting...")
    uvicorn.run("main:app", host="0.0.0.0", port=7860, reload=True)
