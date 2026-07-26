import os
import uuid
import aiofiles
from pathlib import Path
from app.config import get_settings

settings = get_settings()


class StorageService:
    def __init__(self):
        self.storage_dir = Path(settings.STORAGE_DIR)
        self.audio_dir = self.storage_dir / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    async def upload_audio(self, audio_bytes: bytes, filename: str) -> str:
        filepath = self.audio_dir / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(filepath, "wb") as f:
            await f.write(audio_bytes)

        return f"/api/storage/audio/{filename}"

    async def delete_audio(self, filename: str) -> bool:
        filepath = self.audio_dir / filename
        if filepath.exists():
            filepath.unlink()
            return True
        return False

    def get_audio_path(self, filename: str) -> str:
        return str(self.audio_dir / filename)


storage_service = StorageService()
