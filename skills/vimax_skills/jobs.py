"""Small, single-user job manager with bounded local concurrency and retries."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4

from .health import ffmpeg_executable, load_voices
from .renderer import render_job
from .scene_analysis import generated_video

JOB_ID = re.compile(r"^[a-f0-9]{32}$")
GENERATED = re.compile(r"^(?:scene-\d{3}\.png|voice-\d{3}\.wav|video(?:\.partial)?\.mp4|scene-clip\.mp4|thumbnail\.png|narration\.wav|subtitles\.(?:srt|vtt)|storyboard\.json|scene-detection\.json|script\.txt|research\.txt|scenes\.ffconcat)$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobManager:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vimax-local-render")
        self.jobs: dict[str, dict] = {}
        self._recover()

    def _recover(self) -> None:
        for directory in self.root.iterdir():
            if not directory.is_dir() or directory.is_symlink() or not JOB_ID.fullmatch(directory.name):
                continue
            try:
                job = json.loads((directory / "job.json").read_text(encoding="utf-8"))
                if job.get("id") != directory.name:
                    continue
                self.jobs[directory.name] = job
                if job.get("status") in {"queued", "running"}:
                    job["status"] = "failed"
                    job["error"] = "The local worker stopped before finishing. Retry the job."
                    self._log(job, "error", job["error"])
                    self._save(job)
            except (OSError, ValueError, TypeError):
                continue

    def _save(self, job: dict) -> None:
        directory = self.root / job["id"]
        directory.mkdir(exist_ok=True, mode=0o700)
        temp = directory / "job.json.tmp"
        temp.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        os.replace(temp, directory / "job.json")

    @staticmethod
    def _log(job: dict, stage: str, message: str) -> None:
        job["stage"] = stage
        job["updated_at"] = now()
        job.setdefault("events", []).append({"time": job["updated_at"], "stage": stage, "message": message})
        job["events"] = job["events"][-120:]

    def _active_count(self) -> int:
        return sum(j.get("status") in {"queued", "running"} for j in self.jobs.values())

    def create(self, spec: dict) -> dict:
        with self.lock:
            if self._active_count() >= 3:
                raise RuntimeError("The local queue is full. Wait for a job to finish.")
            job_id = uuid4().hex
            timestamp = now()
            job = {"id": job_id, "input": spec, "status": "queued", "stage": "queued", "created_at": timestamp,
                   "updated_at": timestamp, "attempts": 1, "max_attempts": 3, "error": None, "events": [],
                   "estimated_api_cost_usd": 0, "result": None, "approved_at": None,
                   "output_directory": str(self.root / job_id)}
            self._log(job, "queued", "Queued for the local CPU worker.")
            self.jobs[job_id] = job
            self._save(job)
            self.pool.submit(self._run, job_id)
            return self._copy(job)

    @staticmethod
    def _copy(job: dict) -> dict:
        return json.loads(json.dumps(job, ensure_ascii=False))

    def get(self, job_id: str) -> dict | None:
        if not JOB_ID.fullmatch(job_id):
            return None
        with self.lock:
            job = self.jobs.get(job_id)
            return self._copy(job) if job else None

    def list(self) -> list[dict]:
        with self.lock:
            return [self._copy(job) for job in sorted(self.jobs.values(), key=lambda j: j.get("created_at", ""), reverse=True)[:30]]

    def save_scene_analysis(self, job_id: str, analysis: dict) -> dict:
        """Persist an on-demand analysis for a completed local video."""
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise KeyError("Job not found.")
            if job["status"] not in {"awaiting_review", "approved"} or not job.get("result"):
                raise ValueError("Scene detection requires a completed video.")
            directory = generated_video(self.root, job_id).parent
            temp = directory / f".scene-detection-{uuid4().hex}.tmp"
            try:
                with temp.open("x", encoding="utf-8") as stream:
                    json.dump(analysis, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                try:
                    temp.chmod(0o600)
                except OSError:
                    pass
                os.replace(temp, directory / "scene-detection.json")
            finally:
                temp.unlink(missing_ok=True)
            job["result"]["files"]["scene_detection"] = "scene-detection.json"
            self._log(job, "scene_detection", f"Detected {analysis['scene_count']} visual scene(s) locally.")
            self._save(job)
            return self._copy(job)

    def save_scene_clip(self, job_id: str, temporary: Path, metadata: dict) -> dict:
        """Publish a locally rendered temporary clip, replacing the previous one."""
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise KeyError("Job not found.")
            if job["status"] not in {"awaiting_review", "approved"} or not job.get("result"):
                raise ValueError("Clip export requires a completed video.")
            directory = self.root / job_id
            if (directory.is_symlink() or temporary.parent.resolve() != directory.resolve() or temporary.is_symlink()
                    or not re.fullmatch(r"\.scene-clip-[0-9a-f]{32}\.mp4", temporary.name) or not temporary.is_file()):
                raise ValueError("Clip output is not in the local job directory.")
            os.replace(temporary, directory / "scene-clip.mp4")
            job["result"]["files"]["scene_clip"] = "scene-clip.mp4"
            job["result"]["scene_clip"] = metadata
            self._log(job, "clip_export", f"Exported scene {metadata['scene_number']} locally (up to 30 seconds).")
            self._save(job)
            return self._copy(job)

    def retry(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise KeyError("Job not found.")
            if job["status"] != "failed":
                raise ValueError("Only a failed job can be retried.")
            if job["attempts"] >= job["max_attempts"]:
                raise ValueError("Retry limit reached; create a new job after correcting the problem.")
            if self._active_count() >= 3:
                raise RuntimeError("The local queue is full. Wait for a job to finish.")
            job.update(status="queued", error=None, result=None, approved_at=None, attempts=job["attempts"] + 1)
            self._log(job, "queued", f"Retry {job['attempts']} of {job['max_attempts']} queued.")
            self._save(job)
            self.pool.submit(self._run, job_id)
            return self._copy(job)

    def approve(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise KeyError("Job not found.")
            if job["status"] == "approved":
                return self._copy(job)
            if job["status"] != "awaiting_review":
                raise ValueError("Only a completed preview can be approved.")
            job["status"] = "approved"
            job["approved_at"] = now()
            self._log(job, "approved", "Approved locally. No upload was performed.")
            self._save(job)
            return self._copy(job)

    def _run(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job["status"] = "running"
            self._log(job, "starting", f"Starting attempt {job['attempts']}.")
            self._save(job)
            spec = self._copy(job["input"])
        directory = self.root / job_id

        def progress(stage: str, message: str) -> None:
            with self.lock:
                self._log(job, stage, message)
                self._save(job)

        try:
            # Clear only known generated files; never delete arbitrary user files.
            for path in directory.iterdir():
                if GENERATED.fullmatch(path.name) and (path.is_file() or path.is_symlink()):
                    path.unlink(missing_ok=True)
            voices, _ = load_voices()
            voice = next((v for v in voices if v.id == spec["voice_id"] and v.available), None)
            ffmpeg = ffmpeg_executable()
            if not voice or not ffmpeg:
                raise RuntimeError("The configured voice or FFmpeg is no longer available. Check local setup and retry.")
            result = render_job(spec, directory, voice, ffmpeg, progress)
            with self.lock:
                job["status"] = "awaiting_review"
                job["result"] = result
                self._log(job, "review", "Preview the video and confirm approval. YouTube upload is not implemented.")
                self._save(job)
        except Exception as exc:
            with self.lock:
                job["status"] = "failed"
                job["error"] = str(exc)[:600] or "Local rendering failed."
                self._log(job, "error", job["error"])
                self._save(job)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=True)
