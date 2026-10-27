"""Run with VIMAX_TEST_PIPER_MODEL to verify real audio, video and approval."""
import os
from pathlib import Path
import subprocess
import wave

from fastapi.testclient import TestClient
import pytest
from PIL import Image

from vimax_skills.health import ffmpeg_executable
from vimax_skills.service import create_app
from test_service import HEADERS, TOKEN, wait_job


@pytest.mark.parametrize(('format','dimensions'), [('shorts','360x640'), ('landscape','640x360')])
def test_actual_local_video_pipeline_and_review(format, dimensions, tmp_path, monkeypatch):
    model = os.environ.get('VIMAX_TEST_PIPER_MODEL')
    if not model or not Path(model).is_file():
        pytest.skip('set VIMAX_TEST_PIPER_MODEL to a licensed Piper voice for real media verification')
    monkeypatch.setenv('VIMAX_PIPER_MODEL', model)
    monkeypatch.setenv('VIMAX_PIPER_LANGUAGE', 'en-US')
    monkeypatch.delenv('VIMAX_SKILLS_VOICES', raising=False)
    with TestClient(create_app(token=TOKEN, output_root=tmp_path)) as client:
        payload = {'topic':'Small garden guide', 'script':'Start with a sunny spot. Water the soil gently.', 'research_notes':'Author supplied notes.',
                   'format':format,'language':'en-US','voice_id':'default','duration_seconds':8,'visual_style':'midnight','quality':'draft'}
        response = client.post('/api/skills/jobs', headers=HEADERS, json=payload)
        assert response.status_code == 202, response.text
        job_id = response.json()['id']
        job = wait_job(client, job_id)
        assert job['status'] == 'awaiting_review', job.get('error')
        assert job['result']['scenes'] == 2 and job['estimated_api_cost_usd'] == 0
        assert client.post(f'/api/skills/jobs/{job_id}/upload', headers=HEADERS).status_code == 409
        video = tmp_path / job_id / 'video.mp4'
        metadata = subprocess.run([ffmpeg_executable(), '-hide_banner', '-i', str(video)], capture_output=True, text=True).stderr
        assert dimensions in metadata and 'Video: h264' in metadata and 'Audio: aac' in metadata and '00:00:08.00' in metadata
        decoded = subprocess.run([ffmpeg_executable(), '-v', 'error', '-i', str(video), '-f', 'null', '-'], capture_output=True, text=True)
        assert decoded.returncode == 0, decoded.stderr
        with wave.open(str(tmp_path / job_id / 'narration.wav')) as narration:
            assert narration.getnframes() == 8 * narration.getframerate()
        with Image.open(tmp_path / job_id / 'thumbnail.png') as thumbnail:
            assert thumbnail.size == (1280, 720)
        srt = (tmp_path / job_id / 'subtitles.srt').read_text()
        assert 'Start with a sunny spot.' in srt and 'Water the soil gently.' in srt
        assert client.get(f'/api/skills/jobs/{job_id}/files/video.mp4', headers=HEADERS).status_code == 200
        assert client.get(f'/api/skills/jobs/{job_id}/files/job.json', headers=HEADERS).status_code == 404
        assert client.post(f'/api/skills/jobs/{job_id}/approve', headers=HEADERS, json={'confirmed':False}).status_code == 422
        approved = client.post(f'/api/skills/jobs/{job_id}/approve', headers=HEADERS, json={'confirmed':True})
        assert approved.status_code == 200 and approved.json()['status'] == 'approved'
        upload = client.post(f'/api/skills/jobs/{job_id}/upload', headers=HEADERS)
        assert upload.status_code == 501 and 'not implemented' in upload.json()['detail']
