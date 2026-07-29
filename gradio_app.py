"""
BG LABS - Gradio UI for Hugging Face Spaces Deployment
Complete AI Platform: TTS, Image Gen, Voice Cloning, Script Writer, Avatar, Video
Uses Edge TTS (free), Pollinations.ai (free), Neon PostgreSQL
"""
import os
import json
import uuid
import time
import asyncio
import hashlib
import logging
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import gradio as gr
import asyncpg
import jwt
import edge_tts
import httpx
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
    try:
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
    except Exception as e:
        logger.error(f"Database init failed: {e}")
        pool = None


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


async def get_user_by_token(token: str):
    if not token:
        return None
    user_id = decode_token(token)
    if not user_id or not pool:
        return None
    try:
        async with pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
        if user and user["is_active"]:
            return dict(user)
    except Exception:
        pass
    return None


# ============================================================
# EDGE TTS - FREE UNLIMITED (26+ voices)
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
    "polish_female": {"name": "Agnieszka", "voice": "pl-PL-AgnieszkaNeural", "gender": "Female", "lang": "pl", "accent": "Polish", "color": "#d946ef"},
    "dutch_female": {"name": "Colette", "voice": "nl-NL-ColetteNeural", "gender": "Female", "lang": "nl", "accent": "Dutch", "color": "#0891b2"},
}

VOICE_CHOICES = {f"{v['name']} ({v['accent']}, {v['gender']})": k for k, v in EDGE_VOICES.items()}


async def edge_tts_generate(text: str, voice_key: str = "aria") -> bytes:
    voice_info = EDGE_VOICES.get(voice_key, EDGE_VOICES["aria"])
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
STYLE_CHOICES = {
    "Realistic": "realistic",
    "Anime": "anime",
    "Oil Painting": "oil_painting",
    "Digital Art": "digital_art",
    "Watercolor": "watercolor",
    "3D Render": "3d_render",
    "Pixel Art": "pixel_art",
    "Cyberpunk": "cyberpunk",
}


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
# SCRIPT WRITER - Template-based (FREE)
# ============================================================
SCRIPT_GENRES = ["youtube", "podcast", "presentation", "general"]
SCRIPT_MOODS = ["neutral", "energetic", "calm", "humorous", "inspirational", "professional"]
SCRIPT_DURATIONS = ["short", "medium", "long"]


def write_script(topic: str, genre: str = "general", mood: str = "neutral", duration: str = "medium") -> dict:
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
    return {"script": script, "topic": topic, "genre": genre, "mood": mood, "word_count": len(script.split()), "scenes": script.split("\n\n")}


# ============================================================
# GRADIO FUNCTIONS (wrap async operations)
# ============================================================

# -- TTS --
def tts_generate(text: str, voice_choice: str):
    if not text or not text.strip():
        return None, "Please enter some text."
    voice_key = VOICE_CHOICES.get(voice_choice, "aria")
    voice_info = EDGE_VOICES[voice_key]
    try:
        loop = asyncio.new_event_loop()
        audio_bytes = loop.run_until_complete(edge_tts_generate(text.strip(), voice_key))
        loop.close()
    except Exception as e:
        return None, f"TTS Error: {str(e)}"
    filename = f"{uuid.uuid4().hex}.mp3"
    audio_path = str(AUDIO_DIR / filename)
    with open(audio_path, "wb") as f:
        f.write(audio_bytes)
    return audio_path, f"Generated: {voice_info['name']} ({voice_info['accent']} {voice_info['gender']}) | {len(text)} chars | {len(audio_bytes)//1024}KB"


# -- Image Gen --
def image_generate(prompt: str, style_choice: str):
    if not prompt or not prompt.strip():
        return None, "Please enter a prompt."
    style = STYLE_CHOICES.get(style_choice, "realistic")
    try:
        loop = asyncio.new_event_loop()
        image_bytes = loop.run_until_complete(generate_image_pollinations(prompt.strip(), style))
        loop.close()
    except Exception as e:
        return None, f"Image Gen Error: {str(e)}"
    filename = f"{uuid.uuid4().hex}.png"
    image_path = str(IMAGE_DIR / filename)
    with open(image_path, "wb") as f:
        f.write(image_bytes)
    return image_path, f"Generated: {style_choice} style | {len(image_bytes)//1024}KB"


# -- Voice Cloning (profile-based) --
def voice_clone_create(name: str, base_voice_choice: str):
    if not name or not name.strip():
        return "Please enter a name.", ""
    voice_key = VOICE_CHOICES.get(base_voice_choice, "aria")
    profile_id = int(time.time() * 1000) % 1000000
    info = f"Voice profile '{name}' created using {EDGE_VOICES.get(voice_key, EDGE_VOICES['aria'])['name']} as base."
    return info, f"Profile ID: {profile_id}"


def voice_clone_generate(text: str, voice_choice: str):
    if not text or not text.strip():
        return None, "Please enter text to synthesize."
    voice_key = VOICE_CHOICES.get(voice_choice, "aria")
    voice_info = EDGE_VOICES[voice_key]
    try:
        loop = asyncio.new_event_loop()
        audio_bytes = loop.run_until_complete(edge_tts_generate(text.strip(), voice_key))
        loop.close()
    except Exception as e:
        return None, f"Voice Clone Error: {str(e)}"
    filename = f"{uuid.uuid4().hex}.mp3"
    audio_path = str(AUDIO_DIR / filename)
    with open(audio_path, "wb") as f:
        f.write(audio_bytes)
    return audio_path, f"Cloned voice generated: {voice_info['name']} | {len(text)} chars"


# -- Script Writer --
def script_write(topic: str, genre: str, mood: str, duration: str):
    if not topic or not topic.strip():
        return "Please enter a topic.", "", ""
    result = write_script(topic.strip(), genre, mood, duration)
    scenes_text = "\n\n---\n\n".join(result["scenes"])
    stats = f"Genre: {genre} | Mood: {mood} | Duration: {duration} | Words: {result['word_count']}"
    return stats, result["script"], scenes_text


# -- Avatar Studio --
def avatar_generate(hair_color: str, eye_color: str, skin_tone: str, clothing_color: str):
    svg = generate_avatar_svg(hair_color, eye_color, skin_tone, clothing_color)
    filename = f"{uuid.uuid4().hex}.svg"
    svg_path = str(AVATAR_DIR / filename)
    with open(svg_path, "w") as f:
        f.write(svg)
    return svg, svg_path


# -- Video Generator --
def video_generate(script: str):
    if not script or not script.strip():
        return None, "Please enter a script."
    scenes = [{"text": s.strip()} for s in script.strip().split("\n\n") if s.strip()]
    if not scenes:
        scenes = [{"text": script.strip()}]
    filename = f"{uuid.uuid4().hex}.mp4"
    output_path = str(VIDEO_DIR / filename)
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(create_video_from_scenes(scenes, output_path))
        loop.close()
        return output_path, f"Video generated: {len(scenes)} scenes | {filename}"
    except Exception as e:
        txt_filename = f"{uuid.uuid4().hex}.txt"
        txt_path = str(VIDEO_DIR / txt_filename)
        with open(txt_path, "w") as f:
            f.write(f"Video Script:\n{script}\n\nScenes: {len(scenes)}")
        return None, f"FFmpeg unavailable. Script saved as text ({txt_filename}). Error: {str(e)}"


# -- Admin Dashboard --
def admin_get_stats():
    if not pool:
        return "Database not connected", "No users", "No audio", "No images"
    try:
        loop = asyncio.new_event_loop()

        async def fetch_stats():
            async with pool.acquire() as conn:
                users = await conn.fetchval("SELECT COUNT(*) FROM users")
                audio_count = await conn.fetchval("SELECT COUNT(*) FROM audio_history")
                image_count = await conn.fetchval("SELECT COUNT(*) FROM image_history")
                video_count = await conn.fetchval("SELECT COUNT(*) FROM video_history")
                total_chars = await conn.fetchval("SELECT COALESCE(SUM(total_used), 0) FROM users")
            return users, audio_count, image_count, video_count, total_chars

        users, audio_count, image_count, video_count, total_chars = loop.run_until_complete(fetch_stats())
        loop.close()
        stats = f"Users: {users} | Audio: {audio_count} | Images: {image_count} | Videos: {video_count} | Total Chars Used: {total_chars}"
        return stats
    except Exception as e:
        return f"Error: {str(e)}"


def admin_list_users():
    if not pool:
        return "Database not connected"
    try:
        loop = asyncio.new_event_loop()

        async def fetch_users():
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT id, email, username, role, credits, total_used, is_active, created_at FROM users ORDER BY created_at DESC")
            return [dict(r) for r in rows]

        users = loop.run_until_complete(fetch_users())
        loop.close()
        if not users:
            return "No users found."
        lines = []
        for u in users:
            status = "Active" if u["is_active"] else "Blocked"
            lines.append(f"#{u['id']} | {u['username']} ({u['email']}) | {u['role']} | Credits: {u['credits']} | Used: {u['total_used']} | {status} | Joined: {u['created_at']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================
# BUILD GRADIO APP
# ============================================================
def build_app() -> gr.Blocks:
    with gr.Blocks(
        title="BG LABS - AI Platform",
        theme=gr.themes.Soft(),
        css="""
        .main-header { text-align: center; padding: 20px; }
        .feature-card { border: 1px solid #e0e0e0; border-radius: 12px; padding: 16px; }
        footer { display: none !important; }
        """
    ) as demo:
        # -- Header --
        gr.Markdown("""
        <div class="main-header">
            <h1>BG LABS</h1>
            <p>Complete AI Platform - TTS, Image Gen, Voice Cloning, Script Writer, Avatar, Video</p>
            <p><em>Edge TTS (FREE) | Pollinations.ai (FREE) | Neon PostgreSQL</em></p>
        </div>
        """)

        with gr.Tabs():
            # ============================================
            # TAB 1: TTS Studio
            # ============================================
            with gr.Tab("TTS Studio"):
                gr.Markdown("### Text-to-Speech Studio (26+ voices, FREE unlimited)")
                with gr.Row():
                    with gr.Column(scale=2):
                        tts_text = gr.Textbox(
                            label="Text to speak",
                            placeholder="Enter text to convert to speech...",
                            lines=6
                        )
                        tts_voice = gr.Dropdown(
                            choices=list(VOICE_CHOICES.keys()),
                            value=list(VOICE_CHOICES.keys())[0],
                            label="Select Voice"
                        )
                        tts_btn = gr.Button("Generate Audio", variant="primary")
                    with gr.Column(scale=1):
                        tts_audio = gr.Audio(label="Generated Audio", type="filepath")
                        tts_status = gr.Textbox(label="Status", interactive=False)
                tts_btn.click(fn=tts_generate, inputs=[tts_text, tts_voice], outputs=[tts_audio, tts_status])

            # ============================================
            # TAB 2: Image Generator
            # ============================================
            with gr.Tab("Image Generator"):
                gr.Markdown("### AI Image Generator (Pollinations.ai, FREE)")
                with gr.Row():
                    with gr.Column(scale=2):
                        img_prompt = gr.Textbox(
                            label="Image prompt",
                            placeholder="Describe the image you want to generate...",
                            lines=4
                        )
                        img_style = gr.Dropdown(
                            choices=list(STYLE_CHOICES.keys()),
                            value="Realistic",
                            label="Style"
                        )
                        img_btn = gr.Button("Generate Image", variant="primary")
                    with gr.Column(scale=1):
                        img_output = gr.Image(label="Generated Image", type="filepath")
                        img_status = gr.Textbox(label="Status", interactive=False)
                img_btn.click(fn=image_generate, inputs=[img_prompt, img_style], outputs=[img_output, img_status])

            # ============================================
            # TAB 3: Voice Cloning
            # ============================================
            with gr.Tab("Voice Cloning"):
                gr.Markdown("### Voice Cloning Studio (Profile-based, FREE)")
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("#### Create Voice Profile")
                        vc_name = gr.Textbox(label="Profile Name", placeholder="My Custom Voice")
                        vc_base = gr.Dropdown(
                            choices=list(VOICE_CHOICES.keys()),
                            value=list(VOICE_CHOICES.keys())[0],
                            label="Base Voice"
                        )
                        vc_create_btn = gr.Button("Create Profile")
                        vc_create_status = gr.Textbox(label="Status", interactive=False)
                        vc_create_info = gr.Textbox(label="Profile Info", interactive=False)
                    with gr.Column():
                        gr.Markdown("#### Generate with Cloned Voice")
                        vc_text = gr.Textbox(
                            label="Text to speak",
                            placeholder="Enter text for your cloned voice...",
                            lines=4
                        )
                        vc_voice_gen = gr.Dropdown(
                            choices=list(VOICE_CHOICES.keys()),
                            value=list(VOICE_CHOICES.keys())[0],
                            label="Voice to Use"
                        )
                        vc_gen_btn = gr.Button("Generate Audio", variant="primary")
                        vc_audio = gr.Audio(label="Generated Audio", type="filepath")
                        vc_gen_status = gr.Textbox(label="Status", interactive=False)
                vc_create_btn.click(fn=voice_clone_create, inputs=[vc_name, vc_base], outputs=[vc_create_status, vc_create_info])
                vc_gen_btn.click(fn=voice_clone_generate, inputs=[vc_text, vc_voice_gen], outputs=[vc_audio, vc_gen_status])

            # ============================================
            # TAB 4: Script Writer
            # ============================================
            with gr.Tab("Script Writer"):
                gr.Markdown("### AI Script Writer (Template-based, FREE)")
                with gr.Row():
                    with gr.Column():
                        sw_topic = gr.Textbox(
                            label="Topic",
                            placeholder="Enter your script topic...",
                            lines=2
                        )
                        sw_genre = gr.Dropdown(
                            choices=SCRIPT_GENRES,
                            value="general",
                            label="Genre"
                        )
                        sw_mood = gr.Dropdown(
                            choices=SCRIPT_MOODS,
                            value="neutral",
                            label="Mood"
                        )
                        sw_duration = gr.Dropdown(
                            choices=SCRIPT_DURATIONS,
                            value="medium",
                            label="Duration"
                        )
                        sw_btn = gr.Button("Generate Script", variant="primary")
                    with gr.Column():
                        sw_stats = gr.Textbox(label="Script Stats", interactive=False)
                        sw_script = gr.Textbox(label="Generated Script", lines=12, interactive=False)
                        sw_scenes = gr.Textbox(label="Scenes (split by paragraph)", lines=8, interactive=False)
                sw_btn.click(fn=script_write, inputs=[sw_topic, sw_genre, sw_mood, sw_duration], outputs=[sw_stats, sw_script, sw_scenes])

            # ============================================
            # TAB 5: Avatar Studio
            # ============================================
            with gr.Tab("Avatar Studio"):
                gr.Markdown("### Avatar Studio (SVG Generator, FREE)")
                with gr.Row():
                    with gr.Column():
                        av_hair = gr.ColorPicker(label="Hair Color", value="#333333")
                        av_eye = gr.ColorPicker(label="Eye Color", value="#333333")
                        av_skin = gr.ColorPicker(label="Skin Tone", value="#fdbcb4")
                        av_clothing = gr.ColorPicker(label="Clothing Color", value="#3b82f6")
                        av_btn = gr.Button("Generate Avatar", variant="primary")
                    with gr.Column():
                        av_svg = gr.Textbox(label="SVG Code", lines=10, interactive=False)
                        av_download = gr.File(label="Download SVG")
                av_btn.click(fn=avatar_generate, inputs=[av_hair, av_eye, av_skin, av_clothing], outputs=[av_svg, av_download])

            # ============================================
            # TAB 6: Video Generator
            # ============================================
            with gr.Tab("Video Generator"):
                gr.Markdown("### Video Generator (FFmpeg, FREE)")
                with gr.Row():
                    with gr.Column(scale=2):
                        vid_script = gr.Textbox(
                            label="Video Script (separate scenes with double newlines)",
                            placeholder="Scene 1: Introduction\n\nScene 2: Main Content\n\nScene 3: Conclusion",
                            lines=8
                        )
                        vid_btn = gr.Button("Generate Video", variant="primary")
                    with gr.Column(scale=1):
                        vid_output = gr.Video(label="Generated Video")
                        vid_status = gr.Textbox(label="Status", interactive=False)
                vid_btn.click(fn=video_generate, inputs=[vid_script], outputs=[vid_output, vid_status])

            # ============================================
            # TAB 7: Admin Dashboard
            # ============================================
            with gr.Tab("Admin Dashboard"):
                gr.Markdown("### Admin Dashboard")
                admin_stats_btn = gr.Button("Refresh Stats", variant="secondary")
                admin_stats_output = gr.Textbox(label="Platform Stats", interactive=False)
                admin_users_btn = gr.Button("List All Users", variant="secondary")
                admin_users_output = gr.Textbox(label="Users", lines=10, interactive=False)
                admin_stats_btn.click(fn=admin_get_stats, inputs=[], outputs=[admin_stats_output])
                admin_users_btn.click(fn=admin_list_users, inputs=[], outputs=[admin_users_output])

            # ============================================
            # TAB 8: Settings / Info
            # ============================================
            with gr.Tab("Settings"):
                gr.Markdown("### Platform Settings & Info")
                gr.Markdown(f"""
                **Database:** {"Neon PostgreSQL Connected" if pool else "Not Connected (set DATABASE_URL in .env)"}
                **Voices Available:** {len(EDGE_VOICES)}
                **Image Styles:** {len(STYLE_CHOICES)}
                **Storage Directory:** `{STORAGE_DIR}`
                **Version:** 7.0.0 (Gradio)
                """)
                gr.Markdown("""
                #### Features
                - **TTS Studio** - 26+ Edge TTS voices, unlimited free generation
                - **Image Generator** - 8 styles via Pollinations.ai, free
                - **Voice Cloning** - Profile-based custom voices
                - **Script Writer** - YouTube, Podcast, Presentation templates
                - **Avatar Studio** - Customizable SVG avatars
                - **Video Generator** - FFmpeg-powered video creation
                - **Admin Dashboard** - User management and stats
                """)

    return demo


# ============================================================
# INIT & LAUNCH
# ============================================================
async def startup():
    await init_db()

try:
    loop = asyncio.get_event_loop()
    if loop.is_running():
        asyncio.ensure_future(startup())
    else:
        loop.run_until_complete(startup())
except RuntimeError:
    asyncio.run(startup())

app = build_app()

if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7860)
