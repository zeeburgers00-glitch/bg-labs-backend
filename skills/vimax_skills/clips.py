"""Bounded local scene-clip extraction from an already-generated video."""
from __future__ import annotations

import json
import math
from pathlib import Path
from uuid import uuid4

from .renderer import _run

MAX_CLIP_SECONDS = 30.0


def extract_clip(video: Path, scene_number: int, ffmpeg: str) -> tuple[Path, dict]:
    """Export at most 30 seconds from a detected scene, using no shell.

    Caller has already resolved a generated video and will atomically publish
    the returned temporary file. A new clip replaces the previous one.
    """
    directory = video.parent
    report = directory / "scene-detection.json"
    if report.is_symlink() or not report.is_file() or report.stat().st_size > 512_000:
        raise ValueError("Run local scene detection before exporting a clip.")
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
        scenes = data["scenes"]
        if not isinstance(scenes, list) or not 1 <= scene_number <= len(scenes) <= 1000:
            raise ValueError
        scene = scenes[scene_number - 1]
        start, end = float(scene["start_seconds"]), float(scene["end_seconds"])
        if (not math.isfinite(start) or not math.isfinite(end) or start < 0
                or end <= start or end > 181):
            raise ValueError
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("The scene number or stored scene report is invalid. Run detection again.") from exc
    duration = min(end - start, MAX_CLIP_SECONDS)
    temporary = directory / f".scene-clip-{uuid4().hex}.mp4"
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-i", video.name,
               "-t", f"{duration:.3f}", "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264",
               "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-threads", "2",
               "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", temporary.name]
    try:
        _run(command, cwd=directory, timeout=120)
        if not temporary.is_file() or not temporary.stat().st_size:
            raise RuntimeError("The local clip export produced no output.")
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return temporary, {"scene_number": scene_number, "start_seconds": round(start, 3),
                       "duration_seconds": round(duration, 3), "limited_to_30_seconds": end - start > MAX_CLIP_SECONDS}
