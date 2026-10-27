"""Optional, local-only visual cut detection for completed ViMax videos.

Only videos produced under the configured jobs root can be selected by the
caller. PySceneDetect uses OpenCV to decode frames; no media is uploaded.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
from typing import Any


NOTICE = (
    "Visual cut estimates only, not semantic scene understanding. "
    "Cuts can be missed or falsely detected, especially in slideshows or fades."
)


def generated_video(root: Path, job_id: str) -> Path:
    """Resolve a completed job's video without accepting arbitrary paths/symlinks."""
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError("Invalid job id.")
    root = Path(root).resolve()
    directory = root / job_id
    video = directory / "video.mp4"
    if directory.is_symlink() or video.is_symlink() or not video.is_file():
        raise ValueError("No generated video is available for this job.")
    if video.resolve().parent != directory.resolve() or directory.resolve().parent != root:
        raise ValueError("No generated video is available for this job.")
    return video


def detect_scenes(video: Path, *, threshold: float = 0.1) -> dict[str, Any]:
    """Analyze generated video frames with PySceneDetect's content detector.

    Scene timestamps are estimates at source frame boundaries. The low default
    is intended for small text-card changes and may over-detect. Set
    start_in_scene so a video with no detected cuts still reports one scene.
    """
    if not math.isfinite(threshold) or not 0.1 <= threshold <= 100.0:
        raise ValueError("Scene threshold must be between 0.1 and 100.")
    try:
        from scenedetect import ContentDetector, detect, __version__
    except Exception as exc:
        raise RuntimeError("Scene detection is unavailable in this Python environment. Check PySceneDetect and OpenCV installation.") from exc
    try:
        ranges = detect(str(video), ContentDetector(threshold=threshold), start_in_scene=True, show_progress=False)
    except Exception as exc:
        # Do not return decoder details or filesystem paths to API callers.
        raise RuntimeError("Scene detection could not decode this video.") from exc
    if not ranges:
        raise RuntimeError("Scene detection found no decodable video frames.")
    def seconds(timecode):
        # ViMax pins PySceneDetect 0.6, while the companion pins 0.7.
        return timecode.seconds if hasattr(timecode, "seconds") else timecode.get_seconds()

    scenes = [
        {"number": index, "start_seconds": round(seconds(start), 3), "end_seconds": round(seconds(end), 3),
         "start_frame": start.frame_num, "end_frame": end.frame_num}
        for index, (start, end) in enumerate(ranges, 1)
    ]
    return {"engine": "PySceneDetect", "engine_version": __version__, "detector": "ContentDetector",
            "threshold": threshold, "scene_count": len(scenes), "scenes": scenes, "notice": NOTICE}
