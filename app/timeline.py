"""
app/timeline.py - turn generated material into a render-ready timeline.

Vercel has no ffmpeg binary and no GPU, so final stitching cannot happen inside
the function. What *can* happen - and what every editing tool in scope actually
needs - is a precise, machine-readable timeline. This module builds one in the
``bglabs.timeline.v1`` format and emits ready-to-run instructions for:

* FFmpeg        (https://github.com/FFmpeg/FFmpeg)        - a concat/filter_complex command
* moviepy       (https://github.com/Zulko/moviepy)        - a Python snippet (ViMax uses moviepy)
* Remotion      (https://github.com/remotion-dev/remotion)- composition props (React render)
* OpenMontage   (https://github.com/calesthio/OpenMontage)- the same shot list
* a render farm  (RENDER_SERVICE_URL)                      - POST the JSON, get an mp4 back

It also parses the EDL that ``/yt-edit`` produces (DEAD / FILLER / REPEAT cuts
with timecodes) into a cut list, so a transcript edit becomes an actual edit.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

FORMAT = "bglabs.timeline.v1"

TIMECODE = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?(?:[.,](\d{1,3}))?")
EDL_LINE = re.compile(r"^\s*(DEAD|FILLER|REPEAT|KEEP|CUT|CLIP)\b\s*[:\-]?\s*(.*)$", re.I)


def tc_to_seconds(value: Any) -> Optional[float]:
    """Parse ``mm:ss``, ``hh:mm:ss``, ``90``, ``1:30.5`` into seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    match = TIMECODE.search(text)
    if not match:
        digits = re.search(r"\d+(?:\.\d+)?", text)
        return float(digits.group(0)) if digits else None
    hours, minutes, seconds, millis = match.groups()
    if seconds is None:  # mm:ss form where the first group is minutes
        total = int(hours) * 60 + int(minutes)
    else:
        total = int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    if millis:
        total += float(f"0.{millis}")
    return round(total, 3)


def seconds_to_tc(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
    return f"{minutes:02d}:{secs:06.3f}"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def parse_edl(text: str) -> List[Dict[str, Any]]:
    """Parse a /yt-edit EDL into cut records.

    Accepts lines like ``DEAD 00:12 - 00:19  long pause``, ``FILLER 1:04: um``,
    ``KEEP 00:00-00:12`` and numbered markdown lists.
    """
    cuts: List[Dict[str, Any]] = []
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-*0123456789.) \t")
        if not line:
            continue
        match = EDL_LINE.match(line)
        kind = (match.group(1).upper() if match else "").strip()
        body = (match.group(2) if match else line)
        times = [tc_to_seconds(m.group(0)) for m in TIMECODE.finditer(body)]
        times = [t for t in times if t is not None]
        if not kind and len(times) >= 2:
            kind = "CUT"
        if not kind and not times:
            continue
        start = times[0] if times else None
        end = times[1] if len(times) > 1 else None
        label = re.sub(TIMECODE, "", body)
        label = re.sub(r"\s*[-\u2013\u2192]\s*$|\s{2,}", " ", label).strip(" -:")
        cuts.append({"kind": kind or "CUT", "start": start, "end": end,
                     "duration": round(end - start, 3) if (start is not None and end is not None) else None,
                     "reason": label or None, "line": raw.strip()})
    return cuts


def edl_to_timeline(edl: List[Dict[str, Any]], *, total_duration: Optional[float] = None,
                    source: str = "source.mp4", title: str = "") -> Dict[str, Any]:
    """Turn DEAD/FILLER/REPEAT cuts into the clips that should survive."""
    removals = sorted([c for c in edl if c["kind"] in ("DEAD", "FILLER", "REPEAT", "CUT")
                       and c["start"] is not None and c["end"] is not None],
                      key=lambda c: c["start"])
    merged: List[Dict[str, Any]] = []
    for cut in removals:
        if merged and cut["start"] <= merged[-1]["end"] + 0.05:
            merged[-1]["end"] = max(merged[-1]["end"], cut["end"])
            merged[-1]["reasons"].append(cut.get("reason") or cut["kind"])
        else:
            merged.append({"start": cut["start"], "end": cut["end"],
                           "reasons": [cut.get("reason") or cut["kind"]]})
    keeps: List[Dict[str, Any]] = []
    cursor = 0.0
    for gap in merged:
        if gap["start"] > cursor + 0.05:
            keeps.append({"in": round(cursor, 3), "out": round(gap["start"], 3)})
        cursor = max(cursor, gap["end"])
    if total_duration and total_duration > cursor + 0.05:
        keeps.append({"in": round(cursor, 3), "out": round(total_duration, 3)})
    if not keeps and total_duration:
        keeps.append({"in": 0.0, "out": round(total_duration, 3)})
    clips = [{"id": f"keep-{i + 1}", "kind": "video", "source": source, "in": keep["in"], "out": keep["out"],
              "duration": round(keep["out"] - keep["in"], 3), "start_at": None} for i, keep in enumerate(keeps)]
    running = 0.0
    for clip in clips:
        clip["start_at"] = round(running, 3)
        running += clip["duration"]
    return {
        "format": FORMAT, "meta": {"title": title or "Edited cut", "source": source,
                                   "aspect_ratio": "16:9", "duration": round(running, 3),
                                   "removed_seconds": round(sum(c["end"] - c["start"] for c in merged), 3),
                                   "removed": [{"start": seconds_to_tc(c["start"]), "end": seconds_to_tc(c["end"]),
                                                "reasons": [r for r in c["reasons"] if r]} for c in merged]},
        "tracks": [{"id": "video", "kind": "video", "clips": clips}],
    }


def build_timeline(req: Dict[str, Any]) -> Dict[str, Any]:
    """Build a timeline from ViMax shots, a shot list, or a /yt-edit EDL.

    Recognised inputs (all optional):
      ``shots``    list of {prompt, duration, image_url, video_url, caption, dialogue, camera, voice}
      ``edl``      text or list from /yt-edit
      ``voiceover``{url, duration, script} or a list of per-shot audio cues
      ``music``    {url, volume}
      ``captions`` list of {text, start, end} (or generated from shot captions)
      ``title``, ``aspect_ratio``, ``fps``, ``resolution``, ``source``, ``total_duration``
    """
    req = req or {}
    edl_raw = req.get("edl")
    if edl_raw:
        edl = edl_raw if isinstance(edl_raw, list) else parse_edl(str(edl_raw))
        timeline = edl_to_timeline(edl, total_duration=_number(req.get("total_duration"), 0) or None,
                                   source=_text(req.get("source")) or "source.mp4",
                                   title=_text(req.get("title")))
        timeline["meta"].update({"aspect_ratio": _text(req.get("aspect_ratio")) or timeline["meta"]["aspect_ratio"],
                                 "fps": _number(req.get("fps"), 30), "edl_cuts": len(edl)})
        timeline["render"] = render_instructions(timeline)
        return timeline

    shots = req.get("shots") or []
    if isinstance(shots, str):
        shots = [{"prompt": line} for line in shots.splitlines() if line.strip()]
    fps = _number(req.get("fps"), 30)
    default_clip = _number(req.get("clip_duration") or req.get("duration"), 6)
    aspect = _text(req.get("aspect_ratio")) or "16:9"

    video_clips: List[Dict[str, Any]] = []
    audio_clips: List[Dict[str, Any]] = []
    caption_cues: List[Dict[str, Any]] = []
    running = 0.0

    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            shot = {"prompt": _text(shot)}
        duration = _number(shot.get("duration") or shot.get("seconds"), default_clip)
        duration = max(0.5, min(duration, 60))
        caption = _text(shot.get("caption") or shot.get("dialogue") or shot.get("text"))
        prompt = _text(shot.get("prompt") or shot.get("description") or caption)
        clip = {
            "id": _text(shot.get("id")) or f"shot-{index + 1}",
            "kind": "video",
            "index": index + 1,
            "source": _text(shot.get("video_url")) or _text(shot.get("image_url")) or None,
            "source_kind": "video" if shot.get("video_url") else ("image" if shot.get("image_url") else "pending"),
            "prompt": prompt or None,
            "camera": _text(shot.get("camera")) or None,
            "in": 0.0,
            "out": round(duration, 3),
            "duration": round(duration, 3),
            "start_at": round(running, 3),
            "caption": caption or None,
            "transition": _text(shot.get("transition")) or ("cut" if index else "fade"),
            "audio_url": _text(shot.get("audio_url")) or None,
        }
        video_clips.append(clip)

        audio_source = _text(shot.get("audio_url"))
        if audio_source:
            audio_clips.append({"id": f"vo-{index + 1}", "kind": "audio", "source": audio_source,
                                "start_at": round(running, 3), "duration": round(duration, 3),
                                "volume": _number(shot.get("volume"), 1.0), "track": "voiceover"})
        if caption:
            caption_cues.append({"id": f"cap-{index + 1}", "start": round(running, 3),
                                 "end": round(running + duration, 3), "text": caption})
        running += duration

    voiceover = req.get("voiceover") or {}
    if isinstance(voiceover, dict) and _text(voiceover.get("url")):
        audio_clips.append({"id": "vo-master", "kind": "audio", "source": _text(voiceover["url"]),
                            "start_at": 0.0, "duration": _number(voiceover.get("duration"), running),
                            "volume": 1.0, "track": "voiceover"})
    music = req.get("music") or {}
    if isinstance(music, dict) and _text(music.get("url")):
        audio_clips.append({"id": "music", "kind": "audio", "source": _text(music["url"]), "start_at": 0.0,
                            "duration": round(running, 3), "volume": _number(music.get("volume"), 0.25),
                            "track": "music", "loop": True})
    elif isinstance(music, str) and music.strip():
        audio_clips.append({"id": "music", "kind": "audio", "source": music.strip(), "start_at": 0.0,
                            "duration": round(running, 3), "volume": 0.25, "track": "music", "loop": True})

    explicit_captions = req.get("captions")
    if isinstance(explicit_captions, list) and explicit_captions:
        caption_cues = []
        for i, cue in enumerate(explicit_captions):
            if isinstance(cue, dict):
                caption_cues.append({"id": f"cap-{i + 1}", "start": tc_to_seconds(cue.get("start")) or 0.0,
                                     "end": tc_to_seconds(cue.get("end")) or 0.0, "text": _text(cue.get("text"))})
            else:
                caption_cues.append({"id": f"cap-{i + 1}", "start": 0.0, "end": 0.0, "text": _text(cue)})

    tracks = [{"id": "video", "kind": "video", "clips": video_clips}]
    if audio_clips:
        tracks.append({"id": "audio", "kind": "audio", "clips": audio_clips})
    if caption_cues:
        tracks.append({"id": "captions", "kind": "text", "clips": caption_cues})

    pending = [c["id"] for c in video_clips if c["source_kind"] == "pending"]
    width, height = resolution_for(aspect, req.get("resolution"))
    timeline = {
        "format": FORMAT,
        "meta": {
            "title": _text(req.get("title")) or "Untitled",
            "aspect_ratio": aspect, "fps": fps, "width": width, "height": height,
            "duration": round(running, 3), "duration_tc": seconds_to_tc(running),
            "shots": len(video_clips), "source": _text(req.get("source")) or None,
            "pending_generation": pending,
            "style": _text(req.get("style")) or None,
            "characters": req.get("characters") or [],
        },
        "tracks": tracks,
        "srt": to_srt(caption_cues),
    }
    timeline["render"] = render_instructions(timeline)
    return timeline


def resolution_for(aspect: str, override: Any = None) -> Tuple[int, int]:
    if override and isinstance(override, str) and "x" in override:
        try:
            w, h = override.lower().split("x", 1)
            return int(w), int(h)
        except ValueError:
            pass
    table = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080),
             "4:5": (1080, 1350), "21:9": (2560, 1080), "4:3": (1440, 1080)}
    return table.get((aspect or "16:9").strip(), (1920, 1080))


def to_srt(cues: List[Dict[str, Any]]) -> str:
    """Standard SRT so any editor (and YouTube) can take the captions directly."""
    lines: List[str] = []
    for i, cue in enumerate(cues):
        if not cue.get("text"):
            continue
        lines.append(str(i + 1))
        lines.append(f"{_srt_tc(cue.get('start', 0))} --> {_srt_tc(cue.get('end', 0))}")
        lines.append(str(cue["text"]).strip())
        lines.append("")
    return "\n".join(lines).strip()


def _srt_tc(seconds: Any) -> str:
    total = max(0.0, _number(seconds, 0))
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = int(total % 60)
    millis = int(round((total - int(total)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def render_instructions(timeline: Dict[str, Any]) -> Dict[str, Any]:
    """Ready-to-run recipes for the renderers in scope."""
    meta = timeline.get("meta") or {}
    tracks = timeline.get("tracks") or []
    video = next((t for t in tracks if t["kind"] == "video"), {"clips": []})
    audio = next((t for t in tracks if t["kind"] == "audio"), {"clips": []})
    clips = [c for c in video.get("clips") or [] if c.get("source")]
    width, height = meta.get("width") or 1920, meta.get("height") or 1080
    fps = meta.get("fps") or 30

    # ---- FFmpeg concat (same-codec sources) -------------------------------
    concat_list = "\n".join(f"file '{c['source']}'" for c in clips)
    ffmpeg_concat = (f"# save as list.txt then run:\nffmpeg -f concat -safe 0 -i list.txt "
                     f"-c:v libx264 -crf 18 -preset medium -r {fps} -vf scale={width}:{height} "
                     f"-pix_fmt yuv420p -c:a aac -b:a 192k out.mp4") if clips else ""

    # ---- FFmpeg filter_complex (mixed sources, trims, audio mix) ----------
    inputs: List[str] = []
    filters: List[str] = []
    for i, clip in enumerate(clips):
        inputs.append(f"-i \"{clip['source']}\"")
        trim = ""
        if clip.get("in") or clip.get("out"):
            trim = f"trim=start={clip.get('in') or 0}:end={clip.get('out') or 0},setpts=PTS-STARTPTS"
        filters.append(f"[{i}:v]{('' if not trim else trim)}scale={width}:{height},fps={fps}[v{i}]")
    audio_inputs: List[str] = []
    for j, cue in enumerate(audio.get("clips") or []):
        if not cue.get("source"):
            continue
        index = len(clips) + j
        inputs.append(f"-i \"{cue['source']}\"")
        audio_inputs.append((index, cue))
        delay = int((cue.get("start_at") or 0) * 1000)
        vol = cue.get("volume", 1.0)
        filters.append(f"[{index}:a]adelay={delay}|{delay},volume={vol}[a{j}]")
    concat_v = "".join(f"[v{i}]" for i in range(len(clips)))
    filters.append(f"{concat_v}concat=n={len(clips)}:v=1:a=0[vout]") if clips else None
    mix_inputs = "".join(f"[a{j}]" for j in range(len(audio_inputs)))
    if audio_inputs:
        filters.append(f"{mix_inputs}amix=inputs={len(audio_inputs)}:duration=longest[aout]")
    ffmpeg_complex = ("ffmpeg " + " ".join(inputs) + " -filter_complex \"" + ";".join(f for f in filters if f)
                      + f"\" -map \"[vout]\"" + (" -map \"[aout]\"" if audio_inputs else "")
                      + f" -c:v libx264 -crf 18 -r {fps} -c:a aac -b:a 192k out.mp4") if clips else ""

    # ---- moviepy (ViMax's own renderer) ----------------------------------
    moviepy = _moviepy_snippet(timeline)

    # ---- Remotion --------------------------------------------------------
    # Copy only render inputs. Referencing ``timeline`` itself here would create
    # a circular object as soon as the caller assigns this render block back to
    # timeline["render"], which JSON encoders correctly reject.
    remotion_timeline = {k: timeline.get(k) for k in ("format", "meta", "tracks", "srt") if k in timeline}
    remotion = {
        "composition": "BGLabsTimeline",
        "props": {"timeline": remotion_timeline},
        "install": "npx create-video@latest --template blank && npm i",
        "render": "npx remotion render src/index.ts BGLabsTimeline out/video.mp4",
        "note": "Drop the props JSON into your Remotion composition; <OffthreadVideo> per clip, "
                "<Audio> per cue, <AbsoluteFill> captions from tracks[].kind == 'text'.",
    }

    # ---- render farm -----------------------------------------------------
    render_service = os_environ("RENDER_SERVICE_URL")
    return {
        "ffmpeg_concat_list": concat_list,
        "ffmpeg_concat": ffmpeg_concat,
        "ffmpeg_filter_complex": ffmpeg_complex,
        "moviepy_python": moviepy,
        "remotion": remotion,
        "open_montage_shots": [{"id": c["id"], "src": c["source"], "in": c.get("in"), "out": c.get("out"),
                                "caption": c.get("caption"), "transition": c.get("transition")} for c in clips],
        "render_service": {
            "url": render_service or None,
            "method": "POST",
            "body": "this timeline JSON",
            "configured": bool(render_service),
            "hint": None if render_service else
                    "Set RENDER_SERVICE_URL (Settings -> AI Keys) to your own FFmpeg/moviepy/Remotion service "
                    "and POST /api/vimax/projects/{id}/timeline to it - or use the recipes above locally.",
        },
        "captions_srt_available": bool(timeline.get("srt")),
    }


def _moviepy_snippet(timeline: Dict[str, Any]) -> str:
    meta = timeline.get("meta") or {}
    tracks = timeline.get("tracks") or []
    video = next((t for t in tracks if t["kind"] == "video"), {"clips": []})
    audio = next((t for t in tracks if t["kind"] == "audio"), {"clips": []})
    clips = [c for c in video.get("clips") or [] if c.get("source")]
    lines = [
        "# pip install moviepy  (this is what ViMax uses to stitch its shots)",
        "from moviepy.editor import VideoFileClip, ImageClip, AudioFileClip, CompositeAudioClip, concatenate_videoclips",
        "",
        f"W, H, FPS = {meta.get('width') or 1920}, {meta.get('height') or 1080}, {meta.get('fps') or 30}",
        "clips = []",
    ]
    for clip in clips:
        source = clip["source"].replace("'", "\\'")
        if clip.get("source_kind") == "image":
            lines.append(f"c = ImageClip('{source}').set_duration({clip.get('duration') or 6})")
        else:
            start = clip.get("in") or 0
            end = clip.get("out") or 0
            lines.append(f"c = VideoFileClip('{source}')" +
                         (f".subclip({start}, {end})" if end else ""))
        lines.append("clips.append(c.resize((W, H)).set_fps(FPS))")
    lines.append("video = concatenate_videoclips(clips, method='compose')")
    if audio.get("clips"):
        lines.append("audio_tracks = []")
        for cue in audio["clips"]:
            if not cue.get("source"):
                continue
            source = cue["source"].replace("'", "\\'")
            lines.append(f"a = AudioFileClip('{source}').set_start({cue.get('start_at') or 0})"
                         f".volumex({cue.get('volume', 1.0)})")
            lines.append("audio_tracks.append(a)")
        lines.append("video = video.set_audio(CompositeAudioClip(audio_tracks))")
    lines.append(f"video.write_videofile('out.mp4', fps=FPS, codec='libx264', audio_codec='aac')")
    return "\n".join(lines)


def os_environ(name: str, default: str = "") -> str:
    import os
    return (os.getenv(name) or default).strip()


def timeline_summary(timeline: Dict[str, Any]) -> Dict[str, Any]:
    meta = timeline.get("meta") or {}
    tracks = timeline.get("tracks") or []
    return {"title": meta.get("title"), "duration": meta.get("duration"),
            "duration_tc": meta.get("duration_tc") or seconds_to_tc(meta.get("duration") or 0),
            "shots": meta.get("shots") or len((tracks[0].get("clips") if tracks else []) or []),
            "aspect_ratio": meta.get("aspect_ratio"), "tracks": [t["kind"] for t in tracks],
            "pending_generation": meta.get("pending_generation") or [],
            "srt_chars": len(timeline.get("srt") or "")}


def estimate_render_cost(timeline: Dict[str, Any]) -> Dict[str, Any]:
    """Rough guidance so a user knows what a full render will cost before running it."""
    meta = timeline.get("meta") or {}
    duration = _number(meta.get("duration"), 0)
    shots = int(_number(meta.get("shots"), 0)) or max(1, math.ceil(duration / 6))
    return {
        "shots": shots,
        "duration_seconds": round(duration, 1),
        "image_generations": shots,
        "video_generations": shots,
        "guidance": f"{shots} keyframe images + {shots} video clips (~{int(duration)}s total). "
                    f"Draft with fal-ai/ltx-video first, then re-render the shots you keep with Veo 3.",
    }


__all__ = ["FORMAT", "build_timeline", "parse_edl", "edl_to_timeline", "to_srt", "seconds_to_tc",
           "tc_to_seconds", "render_instructions", "timeline_summary", "estimate_render_cost",
           "resolution_for"]
