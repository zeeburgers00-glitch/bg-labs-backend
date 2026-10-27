"""Real cut detection and local-only output boundary tests."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from vimax_skills.health import ffmpeg_executable
from vimax_skills.scene_analysis import detect_scenes, generated_video
from vimax_skills.service import create_app
from test_service import HEADERS, TOKEN


@pytest.fixture
def cut_video(tmp_path):
    executable = ffmpeg_executable()
    if not executable:
        pytest.skip('FFmpeg is required to generate the synthetic test video')
    path = tmp_path / 'cuts.mp4'
    command = [executable, '-hide_banner', '-loglevel', 'error', '-y']
    for color in ('red', 'blue', 'green'):
        command += ['-f', 'lavfi', '-i', f'color=c={color}:s=160x90:r=24:d=1']
    command += ['-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0',
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)]
    subprocess.run(command, check=True, capture_output=True, timeout=30)
    return path


def test_real_cut_detection_on_synthetic_frames(cut_video):
    pytest.importorskip('scenedetect')
    result = detect_scenes(cut_video)
    assert result['engine'] == 'PySceneDetect'
    assert result['scene_count'] == 3
    assert [(x['start_frame'], x['end_frame']) for x in result['scenes']] == [(0, 24), (24, 48), (48, 72)]
    assert [x['end_seconds'] for x in result['scenes']] == [1.0, 2.0, 3.0]
    assert 'estimates' in result['notice']
    for invalid in (0, 0.09, 101, float('inf'), float('nan')):
        with pytest.raises(ValueError):
            detect_scenes(cut_video, threshold=invalid)


def test_local_scene_api_and_output_scope(cut_video, tmp_path):
    pytest.importorskip('scenedetect')
    root = tmp_path / 'jobs'
    app = create_app(token=TOKEN, output_root=root)
    job_id = 'a' * 32
    directory = root / job_id
    directory.mkdir()
    shutil.copyfile(cut_video, directory / 'video.mp4')
    # Seed a completed local job, then exercise the real detector/API/file output.
    app.state.manager.jobs[job_id] = {'id': job_id, 'status': 'awaiting_review', 'stage': 'review',
                                      'result': {'files': {}}, 'events': []}
    with TestClient(app) as client:
        url = f'/api/skills/jobs/{job_id}/scene-detection'
        assert client.post(url, json={}).status_code == 403
        assert client.post('/api/skills/jobs/bad/scene-detection', headers=HEADERS, json={}).status_code == 404
        assert client.post(url, headers=HEADERS, json={'threshold': 101}).status_code == 422
        clip_url = f'/api/skills/jobs/{job_id}/scene-clip'
        assert client.post(clip_url, headers=HEADERS, json={'scene_number': 1}).status_code == 422
        response = client.post(url, headers=HEADERS, json={'threshold': 27})
        assert response.status_code == 200, response.text
        assert response.json()['scene_count'] == 3
        output = client.get(f'/api/skills/jobs/{job_id}/files/scene-detection.json', headers=HEADERS)
        assert output.status_code == 200 and output.json() == response.json()
        job = client.get(f'/api/skills/jobs/{job_id}', headers=HEADERS).json()
        assert job['result']['files']['scene_detection'] == 'scene-detection.json'
        assert json.loads((directory / 'scene-detection.json').read_text())['scene_count'] == 3
        assert client.post(clip_url, headers=HEADERS, json={'scene_number': 4}).status_code == 422
        assert client.post(clip_url, headers=HEADERS, json={'scene_number': 0}).status_code == 422
        clip = client.post(clip_url, headers=HEADERS, json={'scene_number': 2})
        assert clip.status_code == 200, clip.text
        assert clip.json()['scene_number'] == 2 and clip.json()['duration_seconds'] == 1
        assert client.get(f'/api/skills/jobs/{job_id}/files/scene-clip.mp4', headers=HEADERS).status_code == 200
        # Blue is the second synthetic scene: verify decoded pixels and duration.
        import cv2
        capture = cv2.VideoCapture(str(directory / 'scene-clip.mp4'))
        assert capture.isOpened()
        assert abs(capture.get(cv2.CAP_PROP_FRAME_COUNT) / capture.get(cv2.CAP_PROP_FPS) - 1) < .05
        ok, frame = capture.read()
        assert ok and frame[45, 80, 0] > 180 and frame[45, 80, 2] < 50
        capture.release()
        assert client.get(f'/api/skills/jobs/{job_id}/files/job.json', headers=HEADERS).status_code == 404
        app.state.manager.jobs[job_id]['status'] = 'failed'
        assert client.post(url, headers=HEADERS, json={}).status_code == 409


def test_video_selector_rejects_paths_and_symlinks(cut_video, tmp_path):
    root = tmp_path / 'jobs'
    root.mkdir()
    job_id = 'b' * 32
    directory = root / job_id
    directory.mkdir()
    with pytest.raises(ValueError):
        generated_video(root, '../cuts')
    with pytest.raises(ValueError):
        generated_video(root, job_id)
    try:
        (directory / 'video.mp4').symlink_to(cut_video)
    except (OSError, NotImplementedError):
        pytest.skip('Creating symlinks is not permitted on this platform')
    with pytest.raises(ValueError):
        generated_video(root, job_id)


def test_real_vimax_registry_executes_scene_tool(cut_video, tmp_path, monkeypatch):
    source = os.environ.get('VIMAX_TEST_SOURCE')
    if not source:
        pytest.skip('set VIMAX_TEST_SOURCE to the pinned ViMax checkout')
    pytest.importorskip('scenedetect')
    sys.path.insert(0, source)
    from agent_runtime.tools import ToolRegistry
    from vimax_skills.agent_tools import build_skill_specs
    root = tmp_path / 'jobs'
    job_id = 'c' * 32
    (root / job_id).mkdir(parents=True)
    shutil.copyfile(cut_video, root / job_id / 'video.mp4')
    monkeypatch.setenv('VIMAX_SKILLS_OUTPUT', str(root))
    registry = ToolRegistry(build_skill_specs())
    result = asyncio.run(registry.execute('video_scene_cuts', {'job_id':job_id}))
    assert result.ok, result.content
    assert json.loads(result.content)['scene_count'] == 3
