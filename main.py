import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import get_settings
from app.database import engine, Base
from app.routes import auth, voices, studio, admin, referral, youtube, scriptwriter, image_generator, avatar_studio, script_writer, billing
from app.middleware import setup_logging, RateLimitMiddleware, RequestLoggingMiddleware, SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    os.makedirs("storage/audio", exist_ok=True)
    os.makedirs("voices", exist_ok=True)
    yield
    await engine.dispose()


settings = get_settings()

app = FastAPI(
    title="BG Labs API - Free TTS Platform",
    description="Free AI Voice Generation Platform with 20+ built-in voices and 17+ language support",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=120, requests_per_hour=2000)

app.include_router(auth.router)
app.include_router(voices.router)
app.include_router(studio.router)
app.include_router(admin.router)
app.include_router(referral.router)
app.include_router(youtube.router)
app.include_router(scriptwriter.router)
app.include_router(image_generator.router)
app.include_router(avatar_studio.router)
app.include_router(script_writer.router)
app.include_router(billing.router)

os.makedirs("storage/audio", exist_ok=True)
app.mount("/api/storage", StaticFiles(directory="storage"), name="storage")


@app.get("/")
async def root():
    return {
        "message": "BG Labs API - Free TTS Platform",
        "version": "2.0.0",
        "features": {
            "voices": "20+ built-in voices",
            "languages": "17+ languages supported",
            "tts_engine": "Coqui XTTS v2 (Open Source)",
            "pricing": "Unlimited & Free",
        }
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "tts_engine": "xtts_v2"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
