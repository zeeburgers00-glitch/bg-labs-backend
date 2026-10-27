import json
import os
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from vimax_skills.renderer import scenes_from_script, _timestamp
from vimax_skills.service import create_app

TOKEN = "b" * 64
HEADERS = {"x-vimax-local-token": TOKEN}


def wait_job(client, job_id, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/skills/jobs/{job_id}", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        if data["status"] not in ("queued", "running"):
            return data
        time.sleep(.1)
    raise AssertionError(f"Job did not finish in {timeout} seconds")


def test_service_token_validation_and_catalog(tmp_path):
    with pytest.raises(RuntimeError): create_app(token="short", output_root=tmp_path)
    with TestClient(create_app(token=TOKEN, output_root=tmp_path)) as client:
        assert client.get("/api/skills/catalog").status_code == 403
        assert client.get("/api/skills/catalog", headers={"x-vimax-local-token":"wrong"}).status_code == 403
        entries = client.get("/api/skills/catalog", headers=HEADERS).json()["entries"]
        assert len(entries) >= 149
        assert {x["name"] for x in entries if x["status"] == "unavailable"} >= {
            "Sarim78/Claude-YouTube-Agent-Skill", "shotcut/shotcut", "electron-vite/electron-vite"}
        assert any(x["name"] == "Breakthrough/PySceneDetect" and x["status"] == "partial" for x in entries)
        assert any(x["status"] == "reference" for x in entries)
        assert client.get("/openapi.json", headers=HEADERS).status_code == 404
        response = client.post("/api/skills/analyze", headers=HEADERS, json={"idea":"How to grow 5 herbs at home", "hook":""})
        assert response.status_code == 200 and response.json()["idea"]["score"] == 51
        assert client.post("/api/skills/analyze", headers=HEADERS, json={}).status_code == 422
        assert client.get("/api/skills/jobs/../../anything", headers=HEADERS).status_code == 404


def test_storyboard_bounded_and_subtitle_timestamps():
    assert scenes_from_script("First sentence. Second sentence!") == ["First sentence.", "Second sentence!"]
    assert _timestamp(3723.123) == "01:02:03,123"
    with pytest.raises(ValueError): scenes_from_script("\n".join(f"Sentence {i}." for i in range(13)))
    assert "".join(scenes_from_script("x" * 180)) == "x" * 180


def test_failed_jobs_can_be_retried_but_never_approved(tmp_path, monkeypatch):
    # The fake is used only to exercise failure/retry states; no integration is
    # claimed from it. The media test separately runs real Piper and FFmpeg.
    model = tmp_path / "voice.onnx"; model.write_bytes(b"test")
    Path(str(model) + ".json").write_text("{}")
    monkeypatch.setenv("VIMAX_PIPER_MODEL", str(model))
    monkeypatch.setenv("VIMAX_PIPER_LANGUAGE", "en-US")
    import vimax_skills.jobs as jobs
    monkeypatch.setattr(jobs, "render_job", lambda *args: (_ for _ in ()).throw(RuntimeError("planned failure")))
    with TestClient(create_app(token=TOKEN, output_root=tmp_path / "jobs")) as client:
        payload = {"topic":"Test", "script":"A sentence.", "format":"shorts", "language":"en-US", "voice_id":"default", "duration_seconds":5, "visual_style":"paper", "quality":"draft"}
        res = client.post('/api/skills/jobs', headers=HEADERS, json=payload)
        assert res.status_code == 202
        job = wait_job(client, res.json()["id"])
        assert job["status"] == "failed" and "planned failure" in job["error"]
        assert client.post(f"/api/skills/jobs/{job['id']}/approve", headers=HEADERS, json={"confirmed":True}).status_code == 409
        assert client.post(f"/api/skills/jobs/{job['id']}/upload", headers=HEADERS).status_code == 409
        retry = client.post(f"/api/skills/jobs/{job['id']}/retry", headers=HEADERS).json()
        assert retry["attempts"] == 2
        assert wait_job(client, job["id"])["status"] == "failed"


def test_api_rejects_language_mismatch(tmp_path, monkeypatch):
    model = tmp_path / 'voice.onnx'; model.write_bytes(b'test'); Path(str(model)+'.json').write_text('{}')
    monkeypatch.setenv('VIMAX_PIPER_MODEL', str(model)); monkeypatch.setenv('VIMAX_PIPER_LANGUAGE', 'en-US')
    with TestClient(create_app(token=TOKEN, output_root=tmp_path / 'jobs')) as client:
        payload = {"topic":"Test", "script":"A sentence.", "language":"ur-PK", "voice_id":"default", "duration_seconds":8}
        res = client.post('/api/skills/jobs', headers=HEADERS, json=payload)
        assert res.status_code == 422 and 'does not translate' in res.json()['detail']
