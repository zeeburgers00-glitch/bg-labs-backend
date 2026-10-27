"""Private loopback-only companion API. The local proxy supplies a random token.

Not a multi-user service: do not expose this API or the upstream ViMax server to
the Internet. The public Vercel deployment deliberately does not start it.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import hmac
import importlib.util
import json
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from .analyzers import lint_title, score_hook, score_idea
from .health import capabilities, ffmpeg_executable, load_voices
from .jobs import JobManager

CATALOG = Path(__file__).resolve().parents[2] / "catalog" / "catalog.json"
FILE_TYPES = {"video.mp4": "video/mp4", "thumbnail.png": "image/png", "subtitles.srt": "application/x-subrip",
              "subtitles.vtt": "text/vtt", "storyboard.json": "application/json", "script.txt": "text/plain; charset=utf-8",
              "research.txt": "text/plain; charset=utf-8", "narration.wav": "audio/wav"}


class AnalysisInput(BaseModel):
    idea: str = Field(default="", max_length=400)
    hook: str = Field(default="", max_length=400)
    title: str = Field(default="", max_length=400)
    thumbnail: str = Field(default="", max_length=400)


class JobInput(BaseModel):
    topic: str = Field(min_length=1, max_length=160)
    script: str = Field(min_length=1, max_length=1800)
    research_notes: str = Field(default="", max_length=4000)
    format: Literal["shorts", "landscape"] = "shorts"
    language: str = Field(min_length=2, max_length=35)
    voice_id: str = Field(min_length=1, max_length=48)
    duration_seconds: int = Field(ge=5, le=180)
    visual_style: Literal["midnight", "sunrise", "paper"] = "midnight"
    quality: Literal["draft", "standard"] = "draft"

    @field_validator("topic", "script", "research_notes", "language", "voice_id")
    @classmethod
    def clean(cls, value: str) -> str:
        value = value.strip()
        if "\x00" in value or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
            raise ValueError("Control characters are not allowed")
        return value

    @field_validator("topic", "script", "language", "voice_id")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value:
            raise ValueError("This field cannot be blank")
        return value


class ApprovalInput(BaseModel):
    confirmed: bool = False


def create_app(*, token: str | None = None, output_root: Path | None = None) -> FastAPI:
    token = token or os.environ.get("VIMAX_SKILLS_INTERNAL_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("A random VIMAX_SKILLS_INTERNAL_TOKEN of at least 32 characters is required.")
    root = output_root or Path(os.environ.get("VIMAX_SKILLS_OUTPUT", str(Path.home() / ".vimax-skills" / "jobs")))
    manager = JobManager(root)

    @asynccontextmanager
    async def lifespan(app):
        yield
        manager.shutdown()

    app = FastAPI(title="ViMax local skills", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.manager = manager

    @app.middleware("http")
    async def require_local_token(request: Request, call_next):
        candidate = request.headers.get("x-vimax-local-token", "")
        if not hmac.compare_digest(candidate.encode("utf-8"), token.encode("utf-8")):
            return JSONResponse({"error": "Local companion access denied."}, status_code=403)
        try:
            declared = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"error": "Invalid content length."}, status_code=400)
        if declared > 32_768:
            return JSONResponse({"error": "Request is too large."}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/skills/catalog")
    def catalog():
        return json.loads(CATALOG.read_text(encoding="utf-8"))

    @app.get("/api/skills/system")
    def system():
        return capabilities()

    @app.post("/api/skills/analyze")
    def analyze(payload: AnalysisInput):
        if not any((payload.idea.strip(), payload.hook.strip(), payload.title.strip())):
            raise HTTPException(422, "Provide an idea, hook or title to analyze.")
        try:
            result = {}
            if payload.idea.strip(): result["idea"] = score_idea(payload.idea)
            if payload.hook.strip(): result["hook"] = score_hook(payload.hook)
            if payload.title.strip(): result["title"] = lint_title(payload.title, payload.thumbnail)
            return result
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/skills/jobs")
    def jobs():
        return {"jobs": manager.list()}

    @app.post("/api/skills/jobs", status_code=202)
    def start_job(payload: JobInput):
        voices, _ = load_voices()
        voice = next((v for v in voices if v.id == payload.voice_id), None)
        if not voice or not voice.available:
            raise HTTPException(422, "Select an installed and configured Piper voice.")
        if voice.language.lower() != payload.language.lower():
            raise HTTPException(422, "The selected language must match the installed voice; this workflow does not translate.")
        if importlib.util.find_spec("piper") is None or not ffmpeg_executable():
            raise HTTPException(503, "Piper or FFmpeg is not installed in the local companion.")
        try:
            return manager.create(payload.model_dump())
        except RuntimeError as exc:
            raise HTTPException(429, str(exc)) from exc

    @app.get("/api/skills/jobs/{job_id}")
    def get_job(job_id: str):
        job = manager.get(job_id)
        if not job: raise HTTPException(404, "Job not found.")
        return job

    @app.post("/api/skills/jobs/{job_id}/retry")
    def retry(job_id: str):
        try:
            return manager.retry(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Job not found.") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(429, str(exc)) from exc

    @app.post("/api/skills/jobs/{job_id}/approve")
    def approve(job_id: str, payload: ApprovalInput):
        if not payload.confirmed: raise HTTPException(422, "Explicit confirmation is required.")
        try:
            return manager.approve(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Job not found.") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/skills/jobs/{job_id}/upload")
    def upload(job_id: str):
        job = manager.get(job_id)
        if not job: raise HTTPException(404, "Job not found.")
        if job["status"] != "approved":
            raise HTTPException(409, "Review and approve the finished video before any upload.")
        raise HTTPException(501, "YouTube upload and Google OAuth are not implemented. No upload occurred.")

    @app.get("/api/skills/jobs/{job_id}/files/{filename}")
    def file(job_id: str, filename: str):
        job = manager.get(job_id)
        if not job or filename not in FILE_TYPES or job["status"] not in {"awaiting_review", "approved"}:
            raise HTTPException(404, "Output not found.")
        path = manager.root / job_id / filename
        if not path.is_file() or path.is_symlink():
            raise HTTPException(404, "Output not found.")
        return FileResponse(path, media_type=FILE_TYPES[filename], headers={"Cache-Control": "no-store"})

    return app
