"""
BG LABS - FREE Unlimited TTS Backend
Edge TTS (Microsoft - FREE, Unlimited)
SQLite + JWT Auth
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
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

# ============================================================
# CONFIG
# ============================================================
BASE_DIR = Path(__file__).parent
STORAGE_DIR = BASE_DIR / "storage"
AUDIO_DIR = STORAGE_DIR / "audio"
DB_PATH = BASE_DIR / "bg_labs.db"
SECRET_KEY = "bglabs-secret-key-2024-change-in-production"
ALGORITHM = "HS256"

STORAGE_DIR.mkdir(exist_ok=True)
AUDIO_DIR.mkdir(exist_ok=True)

# ============================================================
# DATABASE (SQLite)
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
            user_id INTEGER,
            text TEXT,
            voice TEXT,
            language TEXT,
            model TEXT,
            filename TEXT,
            url TEXT,
            chars INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def hash_pass(p):
    return hashlib.sha256(p.encode()).hexdigest()

def verify_pass(p, h):
    return hash_pass(p) == h

def create_token(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(days=30),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("user_id")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def get_current_user(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "No token provided")
    token = auth.replace("Bearer ", "")
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid or expired token")
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not user:
        raise HTTPException(401, "User not found")
    if not user["is_active"]:
        raise HTTPException(403, "Account blocked")
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
    voice_name = voice_info["voice"]
    communicate = edge_tts.Communicate(text, voice_name)
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    if not audio_data:
        raise Exception("TTS returned empty audio")
    return audio_data

# ============================================================
# FASTAPI APP
# ============================================================
app = FastAPI(title="BG LABS API", version="4.0.0")

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
    print("BG LABS API started - Edge TTS FREE Unlimited")

# ============================================================
# AUTH - FIXED
# ============================================================
@app.post("/api/auth/register")
async def register(email: str = Form(...), username: str = Form(...), full_name: str = Form(""), password: str = Form(...)):
    conn = get_db()
    try:
        existing = conn.execute("SELECT 1 FROM users WHERE email=? OR username=?", (email, username)).fetchone()
        if existing:
            conn.close()
            raise HTTPException(400, "Email or username already exists")
        
        code = uuid.uuid4().hex[:8]
        pw_hash = hash_pass(password)
        cursor = conn.execute(
            "INSERT INTO users (email, username, full_name, password_hash, referral_code) VALUES (?, ?, ?, ?, ?)",
            (email, username, full_name, pw_hash, code)
        )
        conn.commit()
        user_id = cursor.lastrowid
        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        conn.close()
        
        token = create_token(user_id)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user["id"],
                "email": user["email"],
                "username": user["username"],
                "full_name": user["full_name"],
                "role": user["role"],
                "credits": user["credits"],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.close()
        raise HTTPException(500, str(e))

@app.post("/api/auth/login")
async def login(username: str = Form(...), password: str = Form(...)):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username=? OR email=?", (username, username)).fetchone()
    conn.close()
    
    if not user:
        raise HTTPException(401, "User not found")
    if not verify_pass(password, user["password_hash"]):
        raise HTTPException(401, "Incorrect password")
    if not user["is_active"]:
        raise HTTPException(403, "Account blocked")
    
    token = create_token(user["id"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "credits": user["credits"],
        }
    }

@app.get("/api/auth/me")
async def get_me(request: Request):
    user = get_current_user(request)
    return {
        "id": user["id"],
        "email": user["email"],
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "is_active": bool(user["is_active"]),
        "credits": user["credits"],
        "total_credits_used": user["total_used"],
        "referral_code": user["referral_code"],
        "created_at": user["created_at"],
    }

@app.put("/api/auth/me")
async def update_me(request: Request):
    user = get_current_user(request)
    body = await request.json()
    conn = get_db()
    if "full_name" in body:
        conn.execute("UPDATE users SET full_name=? WHERE id=?", (body["full_name"], user["id"]))
        conn.commit()
    updated = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    conn.close()
    return {
        "id": updated["id"],
        "email": updated["email"],
        "username": updated["username"],
        "full_name": updated["full_name"],
        "role": updated["role"],
        "credits": updated["credits"],
    }

# ============================================================
# VOICES
# ============================================================
@app.get("/api/voices")
async def list_voices():
    voices = []
    for key, v in EDGE_VOICES.items():
        voices.append({
            "key": key,
            "name": v["name"],
            "gender": v["gender"],
            "accent": v["accent"],
            "lang": v["lang"],
            "color": v["color"],
            "desc": f"{v['gender']} {v['accent']} voice",
        })
    return {"voices": voices, "total": len(voices), "engine": "Edge TTS (FREE)"}

@app.get("/api/voices/builtin")
async def builtin_voices():
    return await list_voices()

# ============================================================
# TTS - FREE UNLIMITED
# ============================================================
@app.post("/api/studio/generate")
async def generate_audio(request: Request):
    user = get_current_user(request)
    body = await request.json()
    text = body.get("text", "").strip()
    voice_key = body.get("voice_key", "aria")
    
    if not text:
        raise HTTPException(400, "Text is required")
    if len(text) > 10000:
        raise HTTPException(400, "Text too long (max 10,000 chars)")
    
    try:
        audio_bytes = await edge_tts_generate(text, voice_key)
    except Exception as e:
        raise HTTPException(500, f"TTS failed: {str(e)}")
    
    filename = f"{uuid.uuid4().hex}.mp3"
    filepath = AUDIO_DIR / filename
    filepath.write_bytes(audio_bytes)
    
    voice_info = EDGE_VOICES.get(voice_key, EDGE_VOICES["aria"])
    conn = get_db()
    conn.execute(
        "INSERT INTO audio_history (user_id, text, voice, language, model, filename, url, chars) VALUES (?,?,?,?,?,?,?,?)",
        (user["id"], text[:500], voice_key, voice_info["lang"], "Edge TTS", filename, f"/api/storage/audio/{filename}", len(text))
    )
    conn.execute("UPDATE users SET total_used = total_used + ? WHERE id = ?", (len(text), user["id"]))
    conn.commit()
    conn.close()
    
    return {
        "url": f"/api/storage/audio/{filename}",
        "filename": filename,
        "model_used": "Edge TTS (FREE)",
        "chars": len(text),
        "voice": voice_info["name"],
    }

@app.get("/api/studio/audio")
async def list_audio(request: Request):
    user = get_current_user(request)
    conn = get_db()
    history = conn.execute(
        "SELECT * FROM audio_history WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
        (user["id"],)
    ).fetchall()
    conn.close()
    return [dict(h) for h in history]

@app.get("/api/studio/languages")
async def languages():
    langs = {}
    for v in EDGE_VOICES.values():
        if v["lang"] not in langs:
            langs[v["lang"]] = v["accent"]
    return {"languages": langs, "total": len(langs)}

# ============================================================
# ADMIN
# ============================================================
@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    user = get_current_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    conn = get_db()
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    audio_count = len(list(AUDIO_DIR.glob("*.mp3")))
    total_chars = conn.execute("SELECT SUM(total_used) FROM users").fetchone()[0] or 0
    conn.close()
    return {"total_users": users, "active_users": users, "total_voices": len(EDGE_VOICES),
            "total_projects": 0, "total_audio_generated": audio_count, "total_credits_used": total_chars}

@app.get("/api/admin/users")
async def admin_users(request: Request):
    user = get_current_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    conn = get_db()
    users = [dict(u) for u in conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()]
    conn.close()
    return users

@app.put("/api/admin/users/{user_id}")
async def admin_update_user(user_id: int, request: Request):
    admin = get_current_user(request)
    if admin["role"] != "admin":
        raise HTTPException(403, "Admin only")
    body = await request.json()
    conn = get_db()
    if "credits" in body:
        conn.execute("UPDATE users SET credits=? WHERE id=?", (body["credits"], user_id))
    if "is_active" in body:
        conn.execute("UPDATE users SET is_active=? WHERE id=?", (1 if body["is_active"] else 0, user_id))
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if not user:
        raise HTTPException(404, "User not found")
    return dict(user)

# ============================================================
# BILLING
# ============================================================
@app.get("/api/billing/plans")
async def plans():
    return {"plans": {"free": {"name": "FREE", "price": 0, "credits": "Unlimited"}}}

@app.get("/api/billing/current")
async def current_sub(request: Request):
    user = get_current_user(request)
    return {"tier": "free", "credits": user["credits"], "status": "active"}

# ============================================================
# ROOT
# ============================================================
@app.get("/")
async def root():
    return {"name": "BG LABS API", "version": "4.0.0", "engine": "Edge TTS (FREE)",
            "voices": len(EDGE_VOICES), "status": "running"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# ============================================================
if __name__ == "__main__":
    print("BG LABS - Starting...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
