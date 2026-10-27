"""Local capability and hardware checks. Never downloads a model or sends data."""
from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


@dataclass(frozen=True)
class Voice:
    id: str
    label: str
    language: str
    model: Path
    speaker: int | None = None

    @property
    def available(self) -> bool:
        return self.model.is_file() and Path(str(self.model) + ".json").is_file()

    def public(self) -> dict:
        return {"id": self.id, "label": self.label, "language": self.language,
                "available": self.available,
                "reason": "" if self.available else "Voice model or its .onnx.json configuration is missing."}


def load_voices() -> tuple[list[Voice], list[str]]:
    warnings: list[str] = []
    entries: list[dict] = []
    config_path = os.environ.get("VIMAX_SKILLS_VOICES", "").strip()
    base = Path.cwd()
    if config_path:
        path = Path(config_path).expanduser().resolve()
        base = path.parent
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("voices"), list):
                raise ValueError("Expected an object with a voices array")
            entries = data["voices"][:32]
        except (OSError, ValueError) as exc:
            warnings.append(f"Voice configuration could not be read: {exc}")
    else:
        model = os.environ.get("VIMAX_PIPER_MODEL", "").strip()
        if model:
            entries = [{"id": "default", "label": os.environ.get("VIMAX_PIPER_LABEL", "Local voice"),
                        "language": os.environ.get("VIMAX_PIPER_LANGUAGE", "en-US"), "model": model}]

    voices: list[Voice] = []
    seen: set[str] = set()
    for entry in entries:
        try:
            if not isinstance(entry, dict):
                raise ValueError("entry must be an object")
            voice_id, label, language, model = (entry.get(k) for k in ("id", "label", "language", "model"))
            if not isinstance(voice_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", voice_id) or voice_id in seen:
                raise ValueError("voice id must be unique and contain only letters, digits, _ or -")
            if not isinstance(label, str) or not label.strip() or len(label) > 80:
                raise ValueError("voice label must be 1–80 characters")
            if not isinstance(language, str) or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language):
                raise ValueError("voice language must be a language tag, such as en-US")
            if not isinstance(model, str) or not model.strip() or "\x00" in model:
                raise ValueError("voice model path is missing")
            speaker = entry.get("speaker")
            if speaker is not None and (not isinstance(speaker, int) or isinstance(speaker, bool) or not 0 <= speaker <= 999):
                raise ValueError("voice speaker must be a non-negative integer")
            resolved = Path(model).expanduser()
            if not resolved.is_absolute():
                resolved = base / resolved
            voices.append(Voice(voice_id, label.strip(), language, resolved.resolve(), speaker))
            seen.add(voice_id)
        except (ValueError, OSError) as exc:
            warnings.append(f"Invalid voice configuration: {exc}")
    if not voices:
        warnings.append("No Piper voice configured. Set VIMAX_PIPER_MODEL or VIMAX_SKILLS_VOICES; see the setup guide.")
    return voices, warnings


def ffmpeg_executable() -> str | None:
    configured = os.environ.get("VIMAX_FFMPEG", "").strip()
    if configured:
        return shutil.which(configured) or (configured if Path(configured).is_file() else None)
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def hardware_report() -> dict:
    gpu = None
    nvidia = shutil.which("nvidia-smi")
    if nvidia:
        try:
            result = subprocess.run([nvidia, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                    capture_output=True, text=True, timeout=3, check=True)
            gpu = result.stdout.strip()[:300] or None
        except (OSError, subprocess.SubprocessError):
            pass
    memory = None
    try:
        if os.name == "nt":
            import ctypes
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            *[(name, ctypes.c_ulonglong) for name in
                              ("total_phys", "avail_phys", "total_page", "avail_page", "total_virtual", "avail_virtual", "avail_extended")]]
            info = MemoryStatus(); info.length = ctypes.sizeof(info)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)):
                memory = info.total_phys
        else:
            memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        pass
    try:
        disk = shutil.disk_usage(Path.home()).free
    except OSError:
        disk = None
    gib = 1024 ** 3
    return {"logical_cpus": os.cpu_count(), "memory_gib": round(memory / gib, 1) if memory else None,
            "home_disk_free_gib": round(disk / gib, 1) if disk is not None else None, "nvidia_gpu": gpu,
            "note": "The local slideshow uses CPU. GPU model adapters are not installed or verified."}


def scene_detection_available() -> bool:
    """Check native imports, not just whether package metadata is present."""
    try:
        importlib.import_module("cv2")
        importlib.import_module("scenedetect")
        return True
    except Exception:
        return False


def capabilities() -> dict:
    ffmpeg = ffmpeg_executable()
    ffmpeg_version = None
    codecs_available = False
    if ffmpeg:
        try:
            result = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=5, check=True)
            ffmpeg_version = result.stdout.splitlines()[0][:200]
            encoders = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10, check=True).stdout
            codecs_available = bool(re.search(r"\blibx264\b", encoders) and re.search(r"\baac\b", encoders))
        except (OSError, subprocess.SubprocessError, IndexError):
            ffmpeg = None
    piper = importlib.util.find_spec("piper") is not None
    scene_detection = scene_detection_available()
    voices, warnings = load_voices()
    if not piper:
        warnings.append("Piper is not installed in the skills Python environment.")
    if not ffmpeg:
        warnings.append("FFmpeg is not available. Install imageio-ffmpeg or set VIMAX_FFMPEG.")
    elif not codecs_available:
        warnings.append("The FFmpeg build needs both libx264 and AAC encoders for this workflow.")
    return {"local_only": True, "piper_installed": piper, "scene_detection_installed": scene_detection, "ffmpeg_installed": bool(ffmpeg),
            "ffmpeg_version": ffmpeg_version, "ffmpeg_required_codecs": codecs_available, "voices": [v.public() for v in voices],
            "hardware": hardware_report(), "warnings": warnings,
            "ready_for_video": bool(piper and ffmpeg and codecs_available and any(v.available for v in voices)),
            "estimated_api_cost_usd": 0,
            "cost_note": "This local path calls no paid APIs; electricity, device, hosting and any other providers are not included."}
