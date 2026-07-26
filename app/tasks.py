from celery import shared_task
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
import asyncio
import uuid

from app.config import get_settings
from app.models import User, Voice, AudioFile, Project
from app.services.tts_engine import tts_service
from app.services.storage import storage_service

settings = get_settings()

engine = create_async_engine(settings.DATABASE_URL)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def get_db_session():
    return async_session()


@shared_task(bind=True, max_retries=3)
def generate_audio_task(self, user_id: int, voice_id: int, text: str, project_id: int = None,
                       language: str = "en", voice_settings: dict = None):
    async def _generate():
        async with get_db_session() as db:
            result = await db.execute(select(Voice).where(Voice.id == voice_id))
            voice = result.scalar_one_or_none()

            if not voice:
                return {"error": "Voice not found"}

            try:
                voice_key = voice.voice_key or "aria"
                audio_bytes = await tts_service.generate_audio(
                    text=text,
                    voice_id=voice_key,
                    language=language,
                    temperature=voice_settings.get("temperature", 0.7) if voice_settings else 0.7,
                    speed=voice_settings.get("speed", 1.0) if voice_settings else 1.0,
                )
            except Exception as e:
                return {"error": f"Audio generation failed: {str(e)}"}

            filename = f"user_{user_id}/{uuid.uuid4().hex}.mp3"
            audio_url = await storage_service.upload_audio(audio_bytes, filename)

            audio_file = AudioFile(
                filename=filename,
                url=audio_url,
                duration=len(text) // 15,
                text_content=text,
                voice_id=voice_id,
                project_id=project_id,
                owner_id=user_id,
                language=language,
                settings=voice_settings or {}
            )
            db.add(audio_file)

            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if user:
                user.total_credits_used += 1

            await db.commit()
            await db.refresh(audio_file)

            return {
                "audio_file_id": audio_file.id,
                "audio_url": audio_url,
                "duration": audio_file.duration
            }

    return asyncio.run(_generate())


@shared_task(bind=True, max_retries=3)
def clone_voice_task(self, user_id: int, name: str, audio_files_base64: list, description: str = ""):
    async def _clone():
        async with get_db_session() as db:
            import base64
            audio_files = [base64.b64decode(f) for f in audio_files_base64]

            try:
                result = await tts_service.clone_voice(
                    name=name,
                    audio_bytes=audio_files[0],
                    description=description
                )
                voice_key = result.get("voice_id")
            except Exception as e:
                return {"error": f"Voice cloning failed: {str(e)}"}

            voice = Voice(
                name=name,
                description=description,
                voice_type="cloned",
                voice_key=voice_key,
                owner_id=user_id,
                settings={"temperature": 0.7, "speed": 1.0}
            )
            db.add(voice)

            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if user:
                user.total_credits_used += 1

            await db.commit()
            await db.refresh(voice)

            return {
                "voice_id": voice.id,
                "voice_key": voice_key
            }

    return asyncio.run(_clone())


@shared_task
def process_youtube_automation_task(user_id: int, project_id: int, config: dict):
    async def _process():
        async with get_db_session() as db:
            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()

            if not project:
                return {"error": "Project not found"}

            return {"status": "processing", "message": "YouTube automation started"}

    return asyncio.run(_process())


@shared_task
def generate_script_task(user_id: int, topic: str, style: str = "educational", length: str = "medium"):
    async def _generate():
        script = f"Script for {topic} in {style} style ({length} length)..."

        async with get_db_session() as db:
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if user:
                user.total_credits_used += 1
                await db.commit()

        return {"script": script, "topic": topic, "style": style}

    return asyncio.run(_generate())


@shared_task
def generate_image_task(user_id: int, prompt: str, model: str = "dall-e-3", size: str = "1024x1024"):
    async def _generate():
        async with get_db_session() as db:
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if user:
                user.total_credits_used += 1
                await db.commit()

        return {"image_url": "https://example.com/generated-image.jpg", "prompt": prompt}

    return asyncio.run(_generate())


@shared_task
def cleanup_old_files_task():
    async def _cleanup():
        async with get_db_session() as db:
            pass

    return asyncio.run(_cleanup())
