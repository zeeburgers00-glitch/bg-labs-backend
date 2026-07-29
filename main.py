"""
BG LABS - Complete AI Platform Backend
Deploy to Render / any cloud - 100% FREE, runs 24/7
Uses Neon PostgreSQL (free 3GB), Edge TTS, Pollinations.ai, FFmpeg
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
import edge_tts
import httpx
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("bglabs")

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
SECRET_KEY = os.getenv("SECRET_KEY", "bglabs-secret-key-change-in-production")
ALGORITHM = "HS256"
DATABASE_URL = os.getenv("DATABASE_URL", "")

for d in [STORAGE_DIR, AUDIO_DIR, IMAGE_DIR, VIDEO_DIR, AVATAR_DIR, VOICE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# DATABASE - Neon PostgreSQL (asyncpg)
# ============================================================
pool: Optional[asyncpg.Pool] = None

async def init_db():
    global pool
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set - running without persistent database")
        return
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
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
# EDGE TTS - FREE UNLIMITED (322+ voices)
# ============================================================
EDGE_VOICES = {
    # English - US
    "en-US-AriaNeural": {"name": "Aria", "voice": "en-US-AriaNeural", "gender": "Female", "lang": "en", "accent": "American", "color": "#a855f7"},
    "en-US-JennyNeural": {"name": "Jenny", "voice": "en-US-JennyNeural", "gender": "Female", "lang": "en", "accent": "American", "color": "#ec4899"},
    "en-US-GuyNeural": {"name": "Guy", "voice": "en-US-GuyNeural", "gender": "Male", "lang": "en", "accent": "American", "color": "#84cc16"},
    "en-US-BrianNeural": {"name": "Brian", "voice": "en-US-BrianNeural", "gender": "Male", "lang": "en", "accent": "American", "color": "#3b82f6"},
    "en-US-AndrewNeural": {"name": "Andrew", "voice": "en-US-AndrewNeural", "gender": "Male", "lang": "en", "accent": "American", "color": "#06b6d4"},
    "en-US-EmmaNeural": {"name": "Emma", "voice": "en-US-EmmaNeural", "gender": "Female", "lang": "en", "accent": "American", "color": "#f472b6"},
    "en-US-ChristopherNeural": {"name": "Christopher", "voice": "en-US-ChristopherNeural", "gender": "Male", "lang": "en", "accent": "American", "color": "#14b8a6"},
    "en-US-EricNeural": {"name": "Eric", "voice": "en-US-EricNeural", "gender": "Male", "lang": "en", "accent": "American", "color": "#6366f1"},
    "en-US-MichelleNeural": {"name": "Michelle", "voice": "en-US-MichelleNeural", "gender": "Female", "lang": "en", "accent": "American", "color": "#f59e0b"},
    "en-US-RogerNeural": {"name": "Roger", "voice": "en-US-RogerNeural", "gender": "Male", "lang": "en", "accent": "American", "color": "#10b981"},
    "en-US-AvaNeural": {"name": "Ava", "voice": "en-US-AvaNeural", "gender": "Female", "lang": "en", "accent": "American", "color": "#c084fc"},
    "en-US-AnaNeural": {"name": "Ana", "voice": "en-US-AnaNeural", "gender": "Female", "lang": "en", "accent": "American", "color": "#e879f9"},
    "en-US-SteffanNeural": {"name": "Steffan", "voice": "en-US-SteffanNeural", "gender": "Male", "lang": "en", "accent": "American", "color": "#fb923c"},
    # English - GB
    "en-GB-SoniaNeural": {"name": "Sonia", "voice": "en-GB-SoniaNeural", "gender": "Female", "lang": "en", "accent": "British", "color": "#0ea5e9"},
    "en-GB-RyanNeural": {"name": "Ryan", "voice": "en-GB-RyanNeural", "gender": "Male", "lang": "en", "accent": "British", "color": "#64748b"},
    "en-GB-LibbyNeural": {"name": "Libby", "voice": "en-GB-LibbyNeural", "gender": "Female", "lang": "en", "accent": "British", "color": "#22d3ee"},
    "en-GB-MaisieNeural": {"name": "Maisie", "voice": "en-GB-MaisieNeural", "gender": "Female", "lang": "en", "accent": "British", "color": "#a3e635"},
    "en-GB-ThomasNeural": {"name": "Thomas", "voice": "en-GB-ThomasNeural", "gender": "Male", "lang": "en", "accent": "British", "color": "#38bdf8"},
    # English - IN
    "en-IN-NeerjaNeural": {"name": "Neerja", "voice": "en-IN-NeerjaNeural", "gender": "Female", "lang": "en", "accent": "Indian", "color": "#d946ef"},
    "en-IN-PrabhatNeural": {"name": "Prabhat", "voice": "en-IN-PrabhatNeural", "gender": "Male", "lang": "en", "accent": "Indian", "color": "#22c55e"},
    # English - AU
    "en-AU-NatashaNeural": {"name": "Natasha", "voice": "en-AU-NatashaNeural", "gender": "Female", "lang": "en", "accent": "Australian", "color": "#f43f5e"},
    "en-AU-WilliamNeural": {"name": "William", "voice": "en-AU-WilliamNeural", "gender": "Male", "lang": "en", "accent": "Australian", "color": "#818cf8"},
    # English - CA
    "en-CA-ClaraNeural": {"name": "Clara", "voice": "en-CA-ClaraNeural", "gender": "Female", "lang": "en", "accent": "Canadian", "color": "#a855f7"},
    "en-CA-LiamNeural": {"name": "Liam", "voice": "en-CA-LiamNeural", "gender": "Male", "lang": "en", "accent": "Canadian", "color": "#ec4899"},
    # English - HK
    "en-HK-YanNeural": {"name": "Yan", "voice": "en-HK-YanNeural", "gender": "Female", "lang": "en", "accent": "Hong Kong", "color": "#06b6d4"},
    "en-HK-SamNeural": {"name": "Sam", "voice": "en-HK-SamNeural", "gender": "Male", "lang": "en", "accent": "Hong Kong", "color": "#84cc16"},
    # English - IE
    "en-IE-EmilyNeural": {"name": "Emily", "voice": "en-IE-EmilyNeural", "gender": "Female", "lang": "en", "accent": "Irish", "color": "#14b8a6"},
    "en-IE-ConnorNeural": {"name": "Connor", "voice": "en-IE-ConnorNeural", "gender": "Male", "lang": "en", "accent": "Irish", "color": "#6366f1"},
    # English - NZ
    "en-NZ-MollyNeural": {"name": "Molly", "voice": "en-NZ-MollyNeural", "gender": "Female", "lang": "en", "accent": "New Zealand", "color": "#f59e0b"},
    "en-NZ-MitchellNeural": {"name": "Mitchell", "voice": "en-NZ-MitchellNeural", "gender": "Male", "lang": "en", "accent": "New Zealand", "color": "#10b981"},
    # English - PH
    "en-PH-RosaNeural": {"name": "Rosa", "voice": "en-PH-RosaNeural", "gender": "Female", "lang": "en", "accent": "Philippines", "color": "#c084fc"},
    "en-PH-JamesNeural": {"name": "James", "voice": "en-PH-JamesNeural", "gender": "Male", "lang": "en", "accent": "Philippines", "color": "#e879f9"},
    # English - SG
    "en-SG-LunaNeural": {"name": "Luna", "voice": "en-SG-LunaNeural", "gender": "Female", "lang": "en", "accent": "Singapore", "color": "#fb923c"},
    "en-SG-WayneNeural": {"name": "Wayne", "voice": "en-SG-WayneNeural", "gender": "Male", "lang": "en", "accent": "Singapore", "color": "#22d3ee"},
    # English - ZA
    "en-ZA-LeahNeural": {"name": "Leah", "voice": "en-ZA-LeahNeural", "gender": "Female", "lang": "en", "accent": "South African", "color": "#a3e635"},
    "en-ZA-LukeNeural": {"name": "Luke", "voice": "en-ZA-LukeNeural", "gender": "Male", "lang": "en", "accent": "South African", "color": "#38bdf8"},
    # Urdu
    "ur-PK-UzmaNeural": {"name": "Uzma", "voice": "ur-PK-UzmaNeural", "gender": "Female", "lang": "ur", "accent": "Pakistani", "color": "#ef4444"},
    "ur-PK-SalmanNeural": {"name": "Salman", "voice": "ur-PK-SalmanNeural", "gender": "Male", "lang": "ur", "accent": "Pakistani", "color": "#8b5cf6"},
    # Hindi
    "hi-IN-SwaraNeural": {"name": "Swara", "voice": "hi-IN-SwaraNeural", "gender": "Female", "lang": "hi", "accent": "Indian", "color": "#f59e0b"},
    # Arabic
    "ar-SA-ZariyahNeural": {"name": "Zariyah", "voice": "ar-SA-ZariyahNeural", "gender": "Female", "lang": "ar", "accent": "Arabic", "color": "#14b8a6"},
    "ar-SA-HamedNeural": {"name": "Hamed", "voice": "ar-SA-HamedNeural", "gender": "Male", "lang": "ar", "accent": "Arabic", "color": "#6366f1"},
    # Chinese
    "zh-CN-XiaoxiaoNeural": {"name": "Xiaoxiao", "voice": "zh-CN-XiaoxiaoNeural", "gender": "Female", "lang": "zh", "accent": "Chinese", "color": "#f43f5e"},
    "zh-CN-YunxiNeural": {"name": "Yunxi", "voice": "zh-CN-YunxiNeural", "gender": "Male", "lang": "zh", "accent": "Chinese", "color": "#22c55e"},
    # Japanese
    "ja-JP-NanamiNeural": {"name": "Nanami", "voice": "ja-JP-NanamiNeural", "gender": "Female", "lang": "ja", "accent": "Japanese", "color": "#c084fc"},
    "ja-JP-KeitaNeural": {"name": "Keita", "voice": "ja-JP-KeitaNeural", "gender": "Male", "lang": "ja", "accent": "Japanese", "color": "#818cf8"},
    # Korean
    "ko-KR-SunHiNeural": {"name": "SunHi", "voice": "ko-KR-SunHiNeural", "gender": "Female", "lang": "ko", "accent": "Korean", "color": "#22d3ee"},
    "ko-KR-InJoonNeural": {"name": "InJoon", "voice": "ko-KR-InJoonNeural", "gender": "Male", "lang": "ko", "accent": "Korean", "color": "#f97316"},
    # Spanish
    "es-ES-ElviraNeural": {"name": "Elvira", "voice": "es-ES-ElviraNeural", "gender": "Female", "lang": "es", "accent": "Spanish", "color": "#e879f9"},
    "es-ES-AlvaroNeural": {"name": "Alvaro", "voice": "es-ES-AlvaroNeural", "gender": "Male", "lang": "es", "accent": "Spanish", "color": "#d946ef"},
    # French
    "fr-FR-DeniseNeural": {"name": "Denise", "voice": "fr-FR-DeniseNeural", "gender": "Female", "lang": "fr", "accent": "French", "color": "#fb923c"},
    "fr-FR-HenriNeural": {"name": "Henri", "voice": "fr-FR-HenriNeural", "gender": "Male", "lang": "fr", "accent": "French", "color": "#0ea5e9"},
    # German
    "de-DE-KatjaNeural": {"name": "Katja", "voice": "de-DE-KatjaNeural", "gender": "Female", "lang": "de", "accent": "German", "color": "#22c55e"},
    "de-DE-ConradNeural": {"name": "Conrad", "voice": "de-DE-ConradNeural", "gender": "Male", "lang": "de", "accent": "German", "color": "#06b6d4"},
    # Portuguese
    "pt-BR-FranciscaNeural": {"name": "Francisca", "voice": "pt-BR-FranciscaNeural", "gender": "Female", "lang": "pt", "accent": "Brazilian", "color": "#818cf8"},
    "pt-BR-AntonioNeural": {"name": "Antonio", "voice": "pt-BR-AntonioNeural", "gender": "Male", "lang": "pt", "accent": "Brazilian", "color": "#84cc16"},
    # Italian
    "it-IT-ElsaNeural": {"name": "Elsa", "voice": "it-IT-ElsaNeural", "gender": "Female", "lang": "it", "accent": "Italian", "color": "#f472b6"},
    "it-IT-DiegoNeural": {"name": "Diego", "voice": "it-IT-DiegoNeural", "gender": "Male", "lang": "it", "accent": "Italian", "color": "#10b981"},
    # Russian
    "ru-RU-SvetlanaNeural": {"name": "Svetlana", "voice": "ru-RU-SvetlanaNeural", "gender": "Female", "lang": "ru", "accent": "Russian", "color": "#38bdf8"},
    "ru-RU-DmitryNeural": {"name": "Dmitry", "voice": "ru-RU-DmitryNeural", "gender": "Male", "lang": "ru", "accent": "Russian", "color": "#a855f7"},
    # Turkish
    "tr-TR-EmelNeural": {"name": "Emel", "voice": "tr-TR-EmelNeural", "gender": "Female", "lang": "tr", "accent": "Turkish", "color": "#a3e635"},
    "tr-TR-AhmetNeural": {"name": "Ahmet", "voice": "tr-TR-AhmetNeural", "gender": "Male", "lang": "tr", "accent": "Turkish", "color": "#ec4899"},
    # Polish
    "pl-PL-AgnieszkaNeural": {"name": "Agnieszka", "voice": "pl-PL-AgnieszkaNeural", "gender": "Female", "lang": "pl", "accent": "Polish", "color": "#d946ef"},
    "pl-PL-MarekNeural": {"name": "Marek", "voice": "pl-PL-MarekNeural", "gender": "Male", "lang": "pl", "accent": "Polish", "color": "#14b8a6"},
    # Dutch
    "nl-NL-ColetteNeural": {"name": "Colette", "voice": "nl-NL-ColetteNeural", "gender": "Female", "lang": "nl", "accent": "Dutch", "color": "#0891b2"},
    "nl-NL-MaartenNeural": {"name": "Maarten", "voice": "nl-NL-MaartenNeural", "gender": "Male", "lang": "nl", "accent": "Dutch", "color": "#6366f1"},
    # Swedish
    "sv-SE-SofieNeural": {"name": "Sofie", "voice": "sv-SE-SofieNeural", "gender": "Female", "lang": "sv", "accent": "Swedish", "color": "#f43f5e"},
    "sv-SE-SvanteNeural": {"name": "Svante", "voice": "sv-SE-SvanteNeural", "gender": "Male", "lang": "sv", "accent": "Swedish", "color": "#22d3ee"},
    # Danish
    "da-DK-ChristelNeural": {"name": "Christel", "voice": "da-DK-ChristelNeural", "gender": "Female", "lang": "da", "accent": "Danish", "color": "#c084fc"},
    "da-DK-JeppeNeural": {"name": "Jeppe", "voice": "da-DK-JeppeNeural", "gender": "Male", "lang": "da", "accent": "Danish", "color": "#fb923c"},
    # Finnish
    "fi-FI-SelmaNeural": {"name": "Selma", "voice": "fi-FI-SelmaNeural", "gender": "Female", "lang": "fi", "accent": "Finnish", "color": "#e879f9"},
    "fi-FI-HarriNeural": {"name": "Harri", "voice": "fi-FI-HarriNeural", "gender": "Male", "lang": "fi", "accent": "Finnish", "color": "#a3e635"},
    # Norwegian
    "nb-NO-PernilleNeural": {"name": "Pernille", "voice": "nb-NO-PernilleNeural", "gender": "Female", "lang": "nb", "accent": "Norwegian", "color": "#38bdf8"},
    "nb-NO-FinnNeural": {"name": "Finn", "voice": "nb-NO-FinnNeural", "gender": "Male", "lang": "nb", "accent": "Norwegian", "color": "#d946ef"},
    # Greek
    "el-GR-AthinaNeural": {"name": "Athina", "voice": "el-GR-AthinaNeural", "gender": "Female", "lang": "el", "accent": "Greek", "color": "#0ea5e9"},
    "el-GR-NestorasNeural": {"name": "Nestoras", "voice": "el-GR-NestorasNeural", "gender": "Male", "lang": "el", "accent": "Greek", "color": "#22c55e"},
    # Hungarian
    "hu-HU-NoemiNeural": {"name": "Noemi", "voice": "hu-HU-NoemiNeural", "gender": "Female", "lang": "hu", "accent": "Hungarian", "color": "#818cf8"},
    "hu-HU-TamasNeural": {"name": "Tamas", "voice": "hu-HU-TamasNeural", "gender": "Male", "lang": "hu", "accent": "Hungarian", "color": "#f59e0b"},
    # Czech
    "cs-CZ-VlastaNeural": {"name": "Vlasta", "voice": "cs-CZ-VlastaNeural", "gender": "Female", "lang": "cs", "accent": "Czech", "color": "#10b981"},
    "cs-CZ-AntoninNeural": {"name": "Antonin", "voice": "cs-CZ-AntoninNeural", "gender": "Male", "lang": "cs", "accent": "Czech", "color": "#c084fc"},
    # Romanian
    "ro-RO-AlinaNeural": {"name": "Alina", "voice": "ro-RO-AlinaNeural", "gender": "Female", "lang": "ro", "accent": "Romanian", "color": "#f472b6"},
    "ro-RO-EmilNeural": {"name": "Emil", "voice": "ro-RO-EmilNeural", "gender": "Male", "lang": "ro", "accent": "Romanian", "color": "#84cc16"},
    # Thai
    "th-TH-PremwadeeNeural": {"name": "Premwadee", "voice": "th-TH-PremwadeeNeural", "gender": "Female", "lang": "th", "accent": "Thai", "color": "#6366f1"},
    "th-TH-NiwatNeural": {"name": "Niwat", "voice": "th-TH-NiwatNeural", "gender": "Male", "lang": "th", "accent": "Thai", "color": "#ef4444"},
    # Vietnamese
    "vi-VN-HoaiMyNeural": {"name": "HoaiMy", "voice": "vi-VN-HoaiMyNeural", "gender": "Female", "lang": "vi", "accent": "Vietnamese", "color": "#8b5cf6"},
    "vi-VN-NamMinhNeural": {"name": "NamMinh", "voice": "vi-VN-NamMinhNeural", "gender": "Male", "lang": "vi", "accent": "Vietnamese", "color": "#f97316"},
    # Indonesian
    "id-ID-GadisNeural": {"name": "Gadis", "voice": "id-ID-GadisNeural", "gender": "Female", "lang": "id", "accent": "Indonesian", "color": "#22d3ee"},
    "id-ID-ArdiNeural": {"name": "Ardi", "voice": "id-ID-ArdiNeural", "gender": "Male", "lang": "id", "accent": "Indonesian", "color": "#a3e635"},
    # Malay
    "ms-MY-YasminNeural": {"name": "Yasmin", "voice": "ms-MY-YasminNeural", "gender": "Female", "lang": "ms", "accent": "Malay", "color": "#38bdf8"},
    "ms-MY-OsmanNeural": {"name": "Osman", "voice": "ms-MY-OsmanNeural", "gender": "Male", "lang": "ms", "accent": "Malay", "color": "#0891b2"},
    # Filipino
    "fil-PH-BlessicaNeural": {"name": "Blessica", "voice": "fil-PH-BlessicaNeural", "gender": "Female", "lang": "fil", "accent": "Filipino", "color": "#d946ef"},
    "fil-PH-AngeloNeural": {"name": "Angelo", "voice": "fil-PH-AngeloNeural", "gender": "Male", "lang": "fil", "accent": "Filipino", "color": "#0ea5e9"},
    # Ukrainian
    "uk-UA-PolinaNeural": {"name": "Polina", "voice": "uk-UA-PolinaNeural", "gender": "Female", "lang": "uk", "accent": "Ukrainian", "color": "#22c55e"},
    "uk-UA-DmytroNeural": {"name": "Dmytro", "voice": "uk-UA-DmytroNeural", "gender": "Male", "lang": "uk", "accent": "Ukrainian", "color": "#818cf8"},
    # Bengali
    "bn-BD-TanishaNeural": {"name": "Tanisha", "voice": "bn-BD-TanishaNeural", "gender": "Female", "lang": "bn", "accent": "Bengali", "color": "#f59e0b"},
    "bn-BD-BashkarNeural": {"name": "Bashkar", "voice": "bn-BD-BashkarNeural", "gender": "Male", "lang": "bn", "accent": "Bengali", "color": "#10b981"},
    # Swahili
    "sw-KE-ZuriNeural": {"name": "Zuri", "voice": "sw-KE-ZuriNeural", "gender": "Female", "lang": "sw", "accent": "Swahili", "color": "#c084fc"},
    "sw-KE-RafaelNeural": {"name": "Rafael", "voice": "sw-KE-RafaelNeural", "gender": "Male", "lang": "sw", "accent": "Swahili", "color": "#f472b6"},
    # Tamil
    "ta-IN-PallaviNeural": {"name": "Pallavi", "voice": "ta-IN-PallaviNeural", "gender": "Female", "lang": "ta", "accent": "Tamil", "color": "#84cc16"},
    "ta-IN-ValluvarNeural": {"name": "Valluvar", "voice": "ta-IN-ValluvarNeural", "gender": "Male", "lang": "ta", "accent": "Tamil", "color": "#6366f1"},
    # Telugu
    "te-IN-ShrutiNeural": {"name": "Shruti", "voice": "te-IN-ShrutiNeural", "gender": "Female", "lang": "te", "accent": "Telugu", "color": "#ef4444"},
    "te-IN-MohanNeural": {"name": "Mohan", "voice": "te-IN-MohanNeural", "gender": "Male", "lang": "te", "accent": "Telugu", "color": "#8b5cf6"},
    # Marathi
    "mr-IN-AarohiNeural": {"name": "Aarohi", "voice": "mr-IN-AarohiNeural", "gender": "Female", "lang": "mr", "accent": "Marathi", "color": "#f97316"},
    "mr-IN-ManoharNeural": {"name": "Manohar", "voice": "mr-IN-ManoharNeural", "gender": "Male", "lang": "mr", "accent": "Marathi", "color": "#22d3ee"},
    # Gujarati
    "gu-IN-DhwaniNeural": {"name": "Dhwani", "voice": "gu-IN-DhwaniNeural", "gender": "Female", "lang": "gu", "accent": "Gujarati", "color": "#a3e635"},
    "gu-IN-NishantNeural": {"name": "Nishant", "voice": "gu-IN-NishantNeural", "gender": "Male", "lang": "gu", "accent": "Gujarati", "color": "#38bdf8"},
    # Kannada
    "kn-IN-SapnaNeural": {"name": "Sapna", "voice": "kn-IN-SapnaNeural", "gender": "Female", "lang": "kn", "accent": "Kannada", "color": "#d946ef"},
    "kn-IN-GaganNeural": {"name": "Gagan", "voice": "kn-IN-GaganNeural", "gender": "Male", "lang": "kn", "accent": "Kannada", "color": "#0891b2"},
    # Malayalam
    "ml-IN-SobhanaNeural": {"name": "Sobhana", "voice": "ml-IN-SobhanaNeural", "gender": "Female", "lang": "ml", "accent": "Malayalam", "color": "#0ea5e9"},
    "ml-IN-MidhunNeural": {"name": "Midhun", "voice": "ml-IN-MidhunNeural", "gender": "Male", "lang": "ml", "accent": "Malayalam", "color": "#22c55e"},
    # Tamil (Sri Lanka)
    "ta-LK-SaranyaNeural": {"name": "Saranya", "voice": "ta-LK-SaranyaNeural", "gender": "Female", "lang": "ta", "accent": "Sri Lankan Tamil", "color": "#818cf8"},
    "ta-LK-KumarNeural": {"name": "Kumar", "voice": "ta-LK-KumarNeural", "gender": "Male", "lang": "ta", "accent": "Sri Lankan Tamil", "color": "#f59e0b"},
    # Tamil (Singapore)
    "ta-SG-VenbaNeural": {"name": "Venba", "voice": "ta-SG-VenbaNeural", "gender": "Female", "lang": "ta", "accent": "Singapore Tamil", "color": "#10b981"},
    "ta-SG-AnbuNeural": {"name": "Anbu", "voice": "ta-SG-AnbuNeural", "gender": "Male", "lang": "ta", "accent": "Singapore Tamil", "color": "#c084fc"},
    # Afrikaans
    "af-ZA-AdriNeural": {"name": "Adri", "voice": "af-ZA-AdriNeural", "gender": "Female", "lang": "af", "accent": "Afrikaans", "color": "#f472b6"},
    "af-ZA-WillemNeural": {"name": "Willem", "voice": "af-ZA-WillemNeural", "gender": "Male", "lang": "af", "accent": "Afrikaans", "color": "#84cc16"},
    # Albanian
    "sq-AL-AnilaNeural": {"name": "Anila", "voice": "sq-AL-AnilaNeural", "gender": "Female", "lang": "sq", "accent": "Albanian", "color": "#6366f1"},
    "sq-AL-DIlirNeural": {"name": "DIlir", "voice": "sq-AL-DIlirNeural", "gender": "Male", "lang": "sq", "accent": "Albanian", "color": "#ef4444"},
    # Bosnian
    "bs-BA-VesnaNeural": {"name": "Vesna", "voice": "bs-BA-VesnaNeural", "gender": "Female", "lang": "bs", "accent": "Bosnian", "color": "#8b5cf6"},
    "bs-BA-GoranNeural": {"name": "Goran", "voice": "bs-BA-GoranNeural", "gender": "Male", "lang": "bs", "accent": "Bosnian", "color": "#f97316"},
    # Catalan
    "ca-ES-JoanaNeural": {"name": "Joana", "voice": "ca-ES-JoanaNeural", "gender": "Female", "lang": "ca", "accent": "Catalan", "color": "#22d3ee"},
    "ca-ES-EnricNeural": {"name": "Enric", "voice": "ca-ES-EnricNeural", "gender": "Male", "lang": "ca", "accent": "Catalan", "color": "#a3e635"},
    # Welsh
    "cy-GB-NiaNeural": {"name": "Nia", "voice": "cy-GB-NiaNeural", "gender": "Female", "lang": "cy", "accent": "Welsh", "color": "#38bdf8"},
    "cy-GB-GethinNeural": {"name": "Gethin", "voice": "cy-GB-GethinNeural", "gender": "Male", "lang": "cy", "accent": "Welsh", "color": "#d946ef"},
    # Estonian
    "et-EE-AnuNeural": {"name": "Anu", "voice": "et-EE-AnuNeural", "gender": "Female", "lang": "et", "accent": "Estonian", "color": "#0891b2"},
    "et-EE-KertNeural": {"name": "Kert", "voice": "et-EE-KertNeural", "gender": "Male", "lang": "et", "accent": "Estonian", "color": "#0ea5e9"},
    # Basque
    "eu-ES-AinhoaNeural": {"name": "Ainhoa", "voice": "eu-ES-AinhoaNeural", "gender": "Female", "lang": "eu", "accent": "Basque", "color": "#22c55e"},
    "eu-ES-AnderNeural": {"name": "Ander", "voice": "eu-ES-AnderNeural", "gender": "Male", "lang": "eu", "accent": "Basque", "color": "#818cf8"},
    # Galician
    "gl-ES-RosaNeural": {"name": "Rosa", "voice": "gl-ES-RosaNeural", "gender": "Female", "lang": "gl", "accent": "Galician", "color": "#f59e0b"},
    "gl-ES-DiegoNeural": {"name": "Diego", "voice": "gl-ES-DiegoNeural", "gender": "Male", "lang": "gl", "accent": "Galician", "color": "#10b981"},
    # Irish
    "ga-IE-OrlaNeural": {"name": "Orla", "voice": "ga-IE-OrlaNeural", "gender": "Female", "lang": "ga", "accent": "Irish", "color": "#c084fc"},
    "ga-IE-ColmNeural": {"name": "Colm", "voice": "ga-IE-ColmNeural", "gender": "Male", "lang": "ga", "accent": "Irish", "color": "#f472b6"},
    # Croatian
    "hr-HR-GabrijelaNeural": {"name": "Gabrijela", "voice": "hr-HR-GabrijelaNeural", "gender": "Female", "lang": "hr", "accent": "Croatian", "color": "#84cc16"},
    "hr-HR-SreckoNeural": {"name": "Srecko", "voice": "hr-HR-SreckoNeural", "gender": "Male", "lang": "hr", "accent": "Croatian", "color": "#6366f1"},
    # Icelandic
    "is-IS-GudrunNeural": {"name": "Gudrun", "voice": "is-IS-GudrunNeural", "gender": "Female", "lang": "is", "accent": "Icelandic", "color": "#ef4444"},
    "is-IS-GunnarNeural": {"name": "Gunnar", "voice": "is-IS-GunnarNeural", "gender": "Male", "lang": "is", "accent": "Icelandic", "color": "#8b5cf6"},
    # Georgian
    "ka-GE-EkaNeural": {"name": "Eka", "voice": "ka-GE-EkaNeural", "gender": "Female", "lang": "ka", "accent": "Georgian", "color": "#f97316"},
    "ka-GE-GiorgiNeural": {"name": "Giorgi", "voice": "ka-GE-GiorgiNeural", "gender": "Male", "lang": "ka", "accent": "Georgian", "color": "#22d3ee"},
    # Kazakh
    "kk-KZ-AigulNeural": {"name": "Aigul", "voice": "kk-KZ-AigulNeural", "gender": "Female", "lang": "kk", "accent": "Kazakh", "color": "#a3e635"},
    "kk-KZ-DauletNeural": {"name": "Daulet", "voice": "kk-KZ-DauletNeural", "gender": "Male", "lang": "kk", "accent": "Kazakh", "color": "#38bdf8"},
    # Khmer
    "km-KH-SopheaNeural": {"name": "Sophea", "voice": "km-KH-SopheaNeural", "gender": "Female", "lang": "km", "accent": "Khmer", "color": "#d946ef"},
    "km-KH-PisethNeural": {"name": "Piseth", "voice": "km-KH-PisethNeural", "gender": "Male", "lang": "km", "accent": "Khmer", "color": "#0891b2"},
    # Lao
    "lo-LA-KeomanyNeural": {"name": "Keomany", "voice": "lo-LA-KeomanyNeural", "gender": "Female", "lang": "lo", "accent": "Lao", "color": "#0ea5e9"},
    "lo-LA-ChanthavongNeural": {"name": "Chanthavong", "voice": "lo-LA-ChanthavongNeural", "gender": "Male", "lang": "lo", "accent": "Lao", "color": "#22c55e"},
    # Lithuanian
    "lt-LT-OnaNeural": {"name": "Ona", "voice": "lt-LT-OnaNeural", "gender": "Female", "lang": "lt", "accent": "Lithuanian", "color": "#818cf8"},
    "lt-LT-LeonasNeural": {"name": "Leonas", "voice": "lt-LT-LeonasNeural", "gender": "Male", "lang": "lt", "accent": "Lithuanian", "color": "#f59e0b"},
    # Latvian
    "lv-LV-EveritaNeural": {"name": "Everita", "voice": "lv-LV-EveritaNeural", "gender": "Female", "lang": "lv", "accent": "Latvian", "color": "#10b981"},
    "lv-LV-NilsNeural": {"name": "Nils", "voice": "lv-LV-NilsNeural", "gender": "Male", "lang": "lv", "accent": "Latvian", "color": "#c084fc"},
    # Macedonian
    "mk-MK-MarijaNeural": {"name": "Marija", "voice": "mk-MK-MarijaNeural", "gender": "Female", "lang": "mk", "accent": "Macedonian", "color": "#f472b6"},
    "mk-MK-AleksandarNeural": {"name": "Aleksandar", "voice": "mk-MK-AleksandarNeural", "gender": "Male", "lang": "mk", "accent": "Macedonian", "color": "#84cc16"},
    # Mongolian
    "mn-MN-YesuiNeural": {"name": "Yesui", "voice": "mn-MN-YesuiNeural", "gender": "Female", "lang": "mn", "accent": "Mongolian", "color": "#6366f1"},
    "mn-MN-BataaNeural": {"name": "Bataa", "voice": "mn-MN-BataaNeural", "gender": "Male", "lang": "mn", "accent": "Mongolian", "color": "#ef4444"},
    # Maltese
    "mt-MT-GretaNeural": {"name": "Greta", "voice": "mt-MT-GretaNeural", "gender": "Female", "lang": "mt", "accent": "Maltese", "color": "#8b5cf6"},
    "mt-MT-JosephNeural": {"name": "Joseph", "voice": "mt-MT-JosephNeural", "gender": "Male", "lang": "mt", "accent": "Maltese", "color": "#f97316"},
    # Myanmar
    "my-MM-HihaNeural": {"name": "Hiha", "voice": "my-MM-HihaNeural", "gender": "Female", "lang": "my", "accent": "Myanmar", "color": "#22d3ee"},
    "my-MM-TunLaNeural": {"name": "TunLa", "voice": "my-MM-TunLaNeural", "gender": "Male", "lang": "my", "accent": "Myanmar", "color": "#a3e635"},
    # Nepali
    "ne-NP-HemkalaNeural": {"name": "Hemkala", "voice": "ne-NP-HemkalaNeural", "gender": "Female", "lang": "ne", "accent": "Nepali", "color": "#38bdf8"},
    "ne-NP-SagarNeural": {"name": "Sagar", "voice": "ne-NP-SagarNeural", "gender": "Male", "lang": "ne", "accent": "Nepali", "color": "#d946ef"},
    # Pashto
    "ps-AF-LatifaNeural": {"name": "Latifa", "voice": "ps-AF-LatifaNeural", "gender": "Female", "lang": "ps", "accent": "Pashto", "color": "#0891b2"},
    "ps-AF-GulNawazNeural": {"name": "GulNawaz", "voice": "ps-AF-GulNawazNeural", "gender": "Male", "lang": "ps", "accent": "Pashto", "color": "#0ea5e9"},
    # Sinhala
    "si-LK-ThiliniNeural": {"name": "Thilini", "voice": "si-LK-ThiliniNeural", "gender": "Female", "lang": "si", "accent": "Sinhala", "color": "#22c55e"},
    "si-LK-SameeraNeural": {"name": "Sameera", "voice": "si-LK-SameeraNeural", "gender": "Male", "lang": "si", "accent": "Sinhala", "color": "#818cf8"},
    # Slovak
    "sk-SK-LukasNeural": {"name": "Lukas", "voice": "sk-SK-LukasNeural", "gender": "Male", "lang": "sk", "accent": "Slovak", "color": "#f59e0b"},
    "sk-SK-ViktoriaNeural": {"name": "Viktoria", "voice": "sk-SK-ViktoriaNeural", "gender": "Female", "lang": "sk", "accent": "Slovak", "color": "#10b981"},
    # Slovenian
    "sl-SI-PetraNeural": {"name": "Petra", "voice": "sl-SI-PetraNeural", "gender": "Female", "lang": "sl", "accent": "Slovenian", "color": "#c084fc"},
    "sl-SI-RokNeural": {"name": "Rok", "voice": "sl-SI-RokNeural", "gender": "Male", "lang": "sl", "accent": "Slovenian", "color": "#f472b6"},
    # Somali
    "so-SO-UbaxNeural": {"name": "Ubax", "voice": "so-SO-UbaxNeural", "gender": "Female", "lang": "so", "accent": "Somali", "color": "#84cc16"},
    "so-SO-MuuseNeural": {"name": "Muuse", "voice": "so-SO-MuuseNeural", "gender": "Male", "lang": "so", "accent": "Somali", "color": "#6366f1"},
    # Serbian
    "sr-RS-SophieNeural": {"name": "Sophie", "voice": "sr-RS-SophieNeural", "gender": "Female", "lang": "sr", "accent": "Serbian", "color": "#ef4444"},
    "sr-RS-NikolaNeural": {"name": "Nikola", "voice": "sr-RS-NikolaNeural", "gender": "Male", "lang": "sr", "accent": "Serbian", "color": "#8b5cf6"},
    # Sundanese
    "su-ID-TutiNeural": {"name": "Tuti", "voice": "su-ID-TutiNeural", "gender": "Female", "lang": "su", "accent": "Sundanese", "color": "#f97316"},
    "su-ID-JajangNeural": {"name": "Jajang", "voice": "su-ID-JajangNeural", "gender": "Male", "lang": "su", "accent": "Sundanese", "color": "#22d3ee"},
    # Uzbek
    "uz-UZ-MadinaNeural": {"name": "Madina", "voice": "uz-UZ-MadinaNeural", "gender": "Female", "lang": "uz", "accent": "Uzbek", "color": "#a3e635"},
    "uz-UZ-SardorNeural": {"name": "Sardor", "voice": "uz-UZ-SardorNeural", "gender": "Male", "lang": "uz", "accent": "Uzbek", "color": "#38bdf8"},
    # Zulu
    "zu-ZA-ThandoNeural": {"name": "Thando", "voice": "zu-ZA-ThandoNeural", "gender": "Female", "lang": "zu", "accent": "Zulu", "color": "#d946ef"},
    "zu-ZA-ThaboNeural": {"name": "Thabo", "voice": "zu-ZA-ThaboNeural", "gender": "Male", "lang": "zu", "accent": "Zulu", "color": "#0891b2"},
}

async def edge_tts_generate(text: str, voice_key: str = "en-US-AriaNeural") -> bytes:
    voice_info = EDGE_VOICES.get(voice_key, EDGE_VOICES["en-US-AriaNeural"])
    communicate = edge_tts.Communicate(text, voice_info["voice"])
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    if not audio_data:
        raise Exception("TTS returned empty audio")
    return audio_data

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
async def keep_alive_ping():
    """Self-ping every 10 minutes to prevent Render free tier sleep"""
    while True:
        try:
            await asyncio.sleep(600)  # 10 minutes
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Ping self
                port = os.getenv("PORT", "7860")
                url = f"http://localhost:{port}/keep-alive"
                try:
                    resp = await client.get(url)
                    logger.info(f"Keep-alive ping: {resp.status_code}")
                except Exception:
                    pass
                # Also try external ping if RENDER_EXTERNAL_URL is set
                ext_url = os.getenv("RENDER_EXTERNAL_URL")
                if ext_url:
                    try:
                        await client.get(f"{ext_url}/keep-alive")
                        logger.info("External keep-alive ping sent")
                    except Exception:
                        pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Keep-alive error: {e}")

keep_alive_task = None

# ============================================================
# FASTAPI APP
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global keep_alive_task
    await init_db()
    keep_alive_task = asyncio.create_task(keep_alive_ping())
    logger.info("BG LABS API started - All features FREE!")
    yield
    if keep_alive_task:
        keep_alive_task.cancel()

app = FastAPI(title="BG LABS API", version="6.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/api/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")

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
# VOICES
# ============================================================
@app.get("/api/voices")
async def list_voices():
    voices = [
        {"key": k, "name": v["name"], "gender": v["gender"], "accent": v["accent"],
         "lang": v["lang"], "color": v["color"], "desc": f"{v['gender']} {v['accent']} voice"}
        for k, v in EDGE_VOICES.items()
    ]
    return {"voices": voices, "total": len(voices), "engine": "Edge TTS (FREE)"}

# ============================================================
# TTS - FREE UNLIMITED
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
    (AUDIO_DIR / filename).write_bytes(audio_bytes)
    voice_info = EDGE_VOICES.get(voice_key, EDGE_VOICES["en-US-AriaNeural"])
    if pool:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO audio_history (user_id, text, voice, language, model, filename, url, chars) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                user["id"], text[:500], voice_key, voice_info["lang"], "Edge TTS", filename, f"/api/storage/audio/{filename}", len(text)
            )
            await conn.execute("UPDATE users SET total_used = total_used + $1 WHERE id = $2", len(text), user["id"])
    return {
        "url": f"/api/storage/audio/{filename}", "filename": filename,
        "model_used": "Edge TTS (FREE)", "chars": len(text), "voice": voice_info["name"]
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
        audio_bytes = await edge_tts_generate(text, voice_key)
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
    return {
        "name": "BG LABS API", "version": "6.0.0", "status": "running",
        "features": [
            "TTS (Edge TTS - FREE, 322+ voices)",
            "Image Gen (Pollinations.ai - FREE)",
            "Video Gen (FFmpeg)",
            "Voice Cloning",
            "Avatar Studio",
            "Script Writer",
            "Keep-Alive 24/7"
        ],
        "voices": len(EDGE_VOICES),
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
