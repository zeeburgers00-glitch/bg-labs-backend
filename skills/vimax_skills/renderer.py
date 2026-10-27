"""CPU-only, user-script-to-slideshow adapter using Piper and FFmpeg.

No shell, downloads, providers, stock assets, hidden publishing or fabricated
research. Timing is measured from the actual generated WAV, not guessed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import wave
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from .health import Voice


STYLES = {
    "midnight": ((15, 25, 48), (50, 68, 115), (239, 244, 255), (134, 190, 255)),
    "sunrise": ((57, 24, 41), (162, 74, 66), (255, 247, 235), (255, 205, 158)),
    "paper": ((235, 231, 215), (198, 216, 214), (23, 40, 48), (18, 103, 104)),
}


def scenes_from_script(script: str, limit: int = 12, chars: int = 150) -> list[str]:
    """Split without inventing content. Long tokens are split rather than dropped."""
    chunks: list[str] = []
    units = re.split(r"(?<=[.!?。！？])\s+|\n+", script.strip())
    for unit in units:
        words = re.findall(r"\S+", unit)
        line = ""
        for word in words:
            while len(word) > chars:
                if line:
                    chunks.append(line)
                    line = ""
                chunks.append(word[:chars])
                word = word[chars:]
            if not word:
                continue
            if line and len(line) + 1 + len(word) > chars:
                chunks.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            chunks.append(line)
    if not chunks:
        raise ValueError("Please provide a non-empty narration script.")
    if len(chunks) > limit:
        raise ValueError(f"The script needs {len(chunks)} scenes; shorten it to at most {limit} scenes.")
    return chunks


def _font(size: int, *, bold: bool = False):
    custom = os.environ.get("VIMAX_SKILLS_FONT", "").strip()
    candidates = ([custom] if custom else []) + [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    raise RuntimeError("No usable font found. Set VIMAX_SKILLS_FONT to a Unicode TTF font on this computer.")


def _wrapped(draw, text: str, font, width: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        test = (current + " " + word).strip()
        if draw.textlength(test, font=font) <= width:
            current = test
        else:
            if current:
                lines.append(current)
                current = ""
            # Break a long unspaced token on character boundaries.
            for char in word:
                candidate = current + char
                if current and draw.textlength(candidate, font=font) > width:
                    lines.append(current)
                    current = char
                else:
                    current = candidate
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _card(path: Path, width: int, height: int, topic: str, text: str, style: str, index: int, total: int, thumbnail: bool = False) -> None:
    top, bottom, ink, accent = STYLES[style]
    image = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        f = y / max(1, height - 1)
        color = tuple(round(a * (1 - f) + b * f) for a, b in zip(top, bottom))
        draw.line((0, y, width, y), fill=color)
    margin = max(24, int(width * .075))
    draw.rounded_rectangle((margin, margin, width - margin, height - margin), radius=max(12, width // 35), outline=accent, width=max(2, width // 320))
    small = _font(max(13, int(width * .025)))
    heading = _font(max(28, int(width * (.060 if thumbnail else .050))), bold=True)
    caption = _font(max(20, int(width * (.035 if thumbnail else .039))))
    x = margin + max(14, width // 35)
    max_width = width - 2 * x
    y = margin + max(20, height // 25)
    draw.text((x, y), "VIMAX  /  LOCAL CREATOR", font=small, fill=accent)
    y += int(height * .12)
    for line in _wrapped(draw, topic, heading, max_width, 4 if thumbnail else 3):
        draw.text((x, y), line, font=heading, fill=ink)
        y += int(heading.size * 1.26)
    if not thumbnail:
        # Captions are rendered into the visual as well as exported as SRT/VTT.
        caption_lines = _wrapped(draw, text, caption, max_width, 7)
        line_height = int(caption.size * 1.35)
        y = max(y + int(height * .06), height - margin - line_height * len(caption_lines) - int(height * .08))
        for line in caption_lines:
            draw.text((x, y), line, font=caption, fill=ink)
            y += line_height
        draw.text((x, height - margin - int(height * .05)), f"{index:02} / {total:02}", font=small, fill=accent)
    else:
        draw.text((x, height - margin - int(height * .09)), "A LOCAL VIDEO STORY", font=small, fill=accent)
    image.save(path, "PNG", optimize=True)


def _timestamp(seconds: float, sep: str = ",") -> str:
    ms = max(0, round(seconds * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    seconds_int, ms = divmod(ms, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds_int:02}{sep}{ms:03}"


def _run(command: list[str], *, cwd: Path, input_text: str | None = None, timeout: int = 180) -> None:
    # No inherited provider credentials are needed for local media generation.
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "HOME", "LANG", "LC_ALL", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(command, input=input_text, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                cwd=cwd, env=env, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("A local media step timed out. Try a shorter script or lower quality.") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not start a required local media tool: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or "").strip().splitlines()
        raise RuntimeError(f"A local media tool failed (exit {result.returncode}): " + (detail[-1][:400] if detail else "no details"))


def render_job(spec: dict, directory: Path, voice: Voice, ffmpeg: str, progress: Callable[[str, str], None]) -> dict:
    topic, script, notes = spec["topic"], spec["script"], spec.get("research_notes", "")
    duration = int(spec["duration_seconds"])
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    progress("research", "Saved your notes; no automated research or fact-checking is performed.")
    (directory / "research.txt").write_text(notes or "No research notes were supplied.\n", encoding="utf-8")
    progress("script", "Using your supplied script verbatim; no AI writing or translation was performed.")
    (directory / "script.txt").write_text(script + "\n", encoding="utf-8")
    scenes = scenes_from_script(script)
    progress("storyboard", f"Prepared {len(scenes)} text-card scene(s).")
    progress("voice", f"Synthesizing {len(scenes)} scene(s) with the selected local Piper voice.")

    wavs: list[Path] = []
    for i, text in enumerate(scenes, 1):
        wav = directory / f"voice-{i:03}.wav"
        command = [sys.executable, "-m", "piper", "--model", str(voice.model), "--output_file", str(wav)]
        if voice.speaker is not None:
            command.extend(["--speaker", str(voice.speaker)])
        _run(command, cwd=directory, input_text=text + "\n", timeout=120)
        if not wav.is_file():
            raise RuntimeError("Piper did not produce an audio file; check the installed voice model.")
        wavs.append(wav)

    # Concatenate actual PCM output and a short pause, then pad to the requested
    # duration. Never speed up or truncate speech without the user's consent.
    audio_path = directory / "narration.wav"
    formats = []
    for wav in wavs:
        with wave.open(str(wav), "rb") as source:
            formats.append((source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype(), source.getnframes()))
    channels, sample_width, rate, compression, _ = formats[0]
    if compression != "NONE" or sample_width != 2 or channels not in (1, 2) or any(x[:4] != formats[0][:4] for x in formats):
        raise RuntimeError("The selected Piper voice returned incompatible PCM audio.")
    pause_frames = int(rate * .25)
    actual_frames = sum(x[4] for x in formats) + pause_frames * (len(wavs) - 1)
    target_frames = duration * rate
    if actual_frames > target_frames:
        required = actual_frames / rate
        raise ValueError(f"Narration needs about {required:.1f} seconds. Increase duration or shorten the script; speech is not truncated.")
    times: list[tuple[float, float]] = []
    frame = 0
    with wave.open(str(audio_path), "wb") as combined:
        combined.setnchannels(channels); combined.setsampwidth(sample_width); combined.setframerate(rate)
        for i, wav in enumerate(wavs):
            with wave.open(str(wav), "rb") as source:
                start = frame / rate
                while True:
                    block = source.readframes(4096)
                    if not block: break
                    combined.writeframesraw(block)
                frame += formats[i][4]
                times.append((start, frame / rate))
            if i < len(wavs) - 1:
                combined.writeframesraw(b"\0" * (pause_frames * channels * sample_width))
                frame += pause_frames
        # Stream padding in chunks to avoid allocating a duration-sized buffer.
        while frame < target_frames:
            count = min(rate * 5, target_frames - frame)
            combined.writeframesraw(b"\0" * (count * channels * sample_width))
            frame += count

    progress("subtitles", "Timed captions from the generated audio; captions are also saved as SRT and VTT.")
    srt, vtt = [], ["WEBVTT\n"]
    storyboard = []
    for i, (text, (start, end)) in enumerate(zip(scenes, times), 1):
        srt.append(f"{i}\n{_timestamp(start)} --> {_timestamp(end)}\n{text}\n")
        vtt.append(f"{_timestamp(start, '.')} --> {_timestamp(end, '.')}\n{text}\n")
        storyboard.append({"scene": i, "text": text, "start_seconds": round(start, 3), "end_seconds": round(end, 3), "visual": f"scene-{i:03}.png"})
    (directory / "subtitles.srt").write_text("\n".join(srt), encoding="utf-8")
    (directory / "subtitles.vtt").write_text("\n".join(vtt), encoding="utf-8")
    (directory / "storyboard.json").write_text(json.dumps(storyboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    progress("visuals", "Rendering original graphic text cards (not AI-generated imagery or stock footage).")
    if spec["format"] == "shorts":
        width, height = (360, 640) if spec["quality"] == "draft" else (720, 1280)
    else:
        width, height = (640, 360) if spec["quality"] == "draft" else (1280, 720)
    for i, text in enumerate(scenes, 1):
        _card(directory / f"scene-{i:03}.png", width, height, topic, text, spec["visual_style"], i, len(scenes))
    progress("thumbnail", "Created a 1280 × 720 graphic thumbnail.")
    _card(directory / "thumbnail.png", 1280, 720, topic, "", spec["visual_style"], 1, len(scenes), thumbnail=True)

    # Last scene holds through the remaining silence. Input file names are
    # generated constants; user content is never interpolated into FFmpeg args.
    manifest = ["ffconcat version 1.0"]
    for i, (start, _) in enumerate(times, 1):
        end = times[i][0] if i < len(times) else duration
        manifest.extend([f"file 'scene-{i:03}.png'", f"duration {max(.04, end - start):.6f}"])
    manifest.append(f"file 'scene-{len(scenes):03}.png'")
    (directory / "scenes.ffconcat").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    progress("assembly", f"Assembling {width} × {height} MP4 with FFmpeg; target duration {duration}s.")
    temporary = directory / "video.partial.mp4"
    output = directory / "video.mp4"
    if temporary.exists(): temporary.unlink()
    # Expand still-image timestamps into real constant-rate frames *before*
    # applying the output duration. Output `-r` alone can leave the video
    # stream ending early while the audio/container still reports full length.
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "1", "-i", "scenes.ffconcat",
               "-i", "narration.wav", "-vf", "fps=24", "-t", str(duration), "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "28" if spec["quality"] == "draft" else "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
               "-movflags", "+faststart", str(temporary)]
    _run(command, cwd=directory, timeout=max(180, duration * 8))
    if not temporary.is_file() or temporary.stat().st_size < 1000:
        raise RuntimeError("FFmpeg did not produce a playable-looking output file.")
    os.replace(temporary, output)
    progress("preview", "Output is ready for human review. Nothing has been uploaded.")
    return {"files": {"video": "video.mp4", "thumbnail": "thumbnail.png", "subtitles": "subtitles.srt", "webvtt": "subtitles.vtt",
                      "storyboard": "storyboard.json", "script": "script.txt", "research": "research.txt", "narration": "narration.wav"},
            "width": width, "height": height, "duration_seconds": duration,
            "spoken_seconds": round(actual_frames / rate, 3), "scenes": len(scenes)}
