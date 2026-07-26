import os
import io
import torch
import numpy as np
from typing import Dict, List, Optional
from pathlib import Path

# Global TTS model
_tts_model = None
_device = "cuda" if torch.cuda.is_available() else "cpu"


def get_tts_model():
    global _tts_model
    if _tts_model is None:
        from TTS.api import TTS
        print(f"Loading XTTS v2 model on {_device}...")
        _tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(_device)
        print("XTTS v2 model loaded!")
    return _tts_model


# ============================================================
# BUILT-IN VOICES - Reference audio files for voice cloning
# ============================================================
# These are pre-defined voice profiles. You can add your own
# .wav files in the voices/ directory.

BUILTIN_VOICES = {
    "aria": {
        "name": "Aria",
        "description": "Female, American English - Clear and professional",
        "language": "en",
        "gender": "female",
        "accent": "american",
    },
    "james": {
        "name": "James",
        "description": "Male, British English - Warm and authoritative",
        "language": "en",
        "gender": "male",
        "accent": "british",
    },
    "priya": {
        "name": "Priya",
        "description": "Female, Hindi - Soft and melodic",
        "language": "hi",
        "gender": "female",
        "accent": "indian",
    },
    "ahmed": {
        "name": "Ahmed",
        "description": "Male, Arabic - Deep and resonant",
        "language": "ar",
        "gender": "male",
        "accent": "arabic",
    },
    "mei": {
        "name": "Mei",
        "description": "Female, Mandarin Chinese - Gentle and clear",
        "language": "zh-cn",
        "gender": "female",
        "accent": "chinese",
    },
    "takeshi": {
        "name": "Takeshi",
        "description": "Male, Japanese - Calm and measured",
        "language": "ja",
        "gender": "male",
        "accent": "japanese",
    },
    "sofia": {
        "name": "Sofia",
        "description": "Female, Spanish - Warm and expressive",
        "language": "es",
        "gender": "female",
        "accent": "spanish",
    },
    "pierre": {
        "name": "Pierre",
        "description": "Male, French - Elegant and smooth",
        "language": "fr",
        "gender": "male",
        "accent": "french",
    },
    "hans": {
        "name": "Hans",
        "description": "Male, German - Precise and confident",
        "language": "de",
        "gender": "male",
        "accent": "german",
    },
    "yuki": {
        "name": "Yuki",
        "description": "Female, Japanese - Soft and pleasant",
        "language": "ja",
        "gender": "female",
        "accent": "japanese",
    },
    "liam": {
        "name": "Liam",
        "description": "Male, American English - Friendly and casual",
        "language": "en",
        "gender": "male",
        "accent": "american",
    },
    "emma": {
        "name": "Emma",
        "description": "Female, British English - Elegant and polished",
        "language": "en",
        "gender": "female",
        "accent": "british",
    },
    "carlos": {
        "name": "Carlos",
        "description": "Male, Spanish - Energetic and warm",
        "language": "es",
        "gender": "male",
        "accent": "spanish",
    },
    "fatima": {
        "name": "Fatima",
        "description": "Female, Arabic - Gentle and expressive",
        "language": "ar",
        "gender": "female",
        "accent": "arabic",
    },
    "vikram": {
        "name": "Vikram",
        "description": "Male, Hindi - Strong and clear",
        "language": "hi",
        "gender": "male",
        "accent": "indian",
    },
    "lena": {
        "name": "Lena",
        "description": "Female, German - Natural and warm",
        "language": "de",
        "gender": "female",
        "accent": "german",
    },
    "marie": {
        "name": "Marie",
        "description": "Female, French - Sweet and melodic",
        "language": "fr",
        "gender": "female",
        "accent": "french",
    },
    "wei": {
        "name": "Wei",
        "description": "Male, Mandarin Chinese - Steady and clear",
        "language": "zh-cn",
        "gender": "male",
        "accent": "chinese",
    },
    "kai": {
        "name": "Kai",
        "description": "Male, Korean - Smooth and modern",
        "language": "ko",
        "gender": "male",
        "accent": "korean",
    },
    "jiwon": {
        "name": "Jiwon",
        "description": "Female, Korean - Bright and friendly",
        "language": "ko",
        "gender": "female",
        "accent": "korean",
    },
}

# Supported languages (XTTS v2 supports these)
SUPPORTED_LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "pl": "Polish",
    "tr": "Turkish",
    "ru": "Russian",
    "nl": "Dutch",
    "cs": "Czech",
    "ar": "Arabic",
    "zh-cn": "Chinese (Mandarin)",
    "ja": "Japanese",
    "hu": "Hungarian",
    "ko": "Korean",
    "hi": "Hindi",
}


class TTSService:
    def __init__(self):
        self.voices_dir = Path("voices")
        self.voices_dir.mkdir(exist_ok=True)
        self.custom_voices: Dict[str, str] = {}
        self._load_custom_voices()

    def _load_custom_voices(self):
        """Load custom voice reference audio files from voices/ directory"""
        if self.voices_dir.exists():
            for f in self.voices_dir.glob("*.wav"):
                voice_id = f.stem
                self.custom_voices[voice_id] = str(f)
            for f in self.voices_dir.glob("*.mp3"):
                voice_id = f.stem
                self.custom_voices[voice_id] = str(f)

    def get_all_voices(self) -> List[Dict]:
        """Get all available voices (built-in + custom)"""
        voices = []
        for voice_id, info in BUILTIN_VOICES.items():
            voices.append({
                "voice_id": voice_id,
                "name": info["name"],
                "description": info["description"],
                "language": info["language"],
                "gender": info["gender"],
                "accent": info["accent"],
                "type": "built-in",
            })
        for voice_id, path in self.custom_voices.items():
            voices.append({
                "voice_id": voice_id,
                "name": voice_id,
                "description": "Custom voice",
                "language": "en",
                "gender": "unknown",
                "accent": "custom",
                "type": "custom",
            })
        return voices

    def get_voice_info(self, voice_id: str) -> Optional[Dict]:
        """Get info about a specific voice"""
        if voice_id in BUILTIN_VOICES:
            info = BUILTIN_VOICES[voice_id]
            return {
                "voice_id": voice_id,
                "name": info["name"],
                "description": info["description"],
                "language": info["language"],
                "gender": info["gender"],
                "accent": info["accent"],
                "type": "built-in",
            }
        if voice_id in self.custom_voices:
            return {
                "voice_id": voice_id,
                "name": voice_id,
                "description": "Custom voice",
                "language": "en",
                "gender": "unknown",
                "accent": "custom",
                "type": "custom",
            }
        return None

    async def generate_audio(
        self,
        text: str,
        voice_id: str = "aria",
        language: str = "en",
        temperature: float = 0.7,
        speed: float = 1.0,
    ) -> bytes:
        """Generate audio from text using XTTS v2"""
        model = get_tts_model()

        # Get reference audio for voice cloning
        reference_audio = None
        if voice_id in self.custom_voices:
            reference_audio = self.custom_voices[voice_id]

        # Generate audio
        wav_outputs = model.tts(
            text=text,
            language=language,
            speaker_wav=reference_audio,
            temperature=temperature,
            speed=speed,
        )

        # Convert to bytes
        import soundfile as sf
        import io

        wav_array = np.array(wav_outputs)
        buffer = io.BytesIO()
        sf.write(buffer, wav_array, 22050, format="WAV")
        buffer.seek(0)

        # Convert WAV to MP3 for smaller size
        from pydub import AudioSegment
        audio = AudioSegment.from_wav(buffer)
        mp3_buffer = io.BytesIO()
        audio.export(mp3_buffer, format="mp3", bitrate="192k")
        mp3_buffer.seek(0)

        return mp3_buffer.read()

    async def clone_voice(
        self,
        name: str,
        audio_bytes: bytes,
        description: str = "",
    ) -> Dict:
        """Clone a voice from uploaded audio"""
        import uuid
        voice_id = f"custom_{uuid.uuid4().hex[:8]}"

        # Save reference audio
        voice_path = self.voices_dir / f"{voice_id}.wav"
        voice_path.write_bytes(audio_bytes)

        self.custom_voices[voice_id] = str(voice_path)

        return {
            "voice_id": voice_id,
            "name": name,
            "description": description,
            "type": "custom",
        }

    def delete_voice(self, voice_id: str) -> bool:
        """Delete a custom voice"""
        if voice_id in self.custom_voices:
            voice_path = Path(self.custom_voices[voice_id])
            if voice_path.exists():
                voice_path.unlink()
            del self.custom_voices[voice_id]
            return True
        return False

    def get_supported_languages(self) -> Dict[str, str]:
        return SUPPORTED_LANGUAGES


tts_service = TTSService()
