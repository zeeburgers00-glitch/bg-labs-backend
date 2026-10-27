"""Integration test of the real single-user local proxy and upstream web server."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest

PROJECT = Path(__file__).resolve().parents[2]


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def wait_for_port(port, process, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f'Local proxy exited early: {process.stdout.read()}')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.2):
                return
        except OSError:
            time.sleep(.1)
    raise AssertionError('Local proxy did not start')


def test_local_proxy_routes_real_vimax_and_private_skills(tmp_path):
    source = os.environ.get('VIMAX_TEST_SOURCE')
    model = os.environ.get('VIMAX_TEST_PIPER_MODEL')
    if not source or not model or not (PROJECT / 'dist' / 'index.html').exists():
        pytest.skip('build the frontend and set VIMAX_TEST_SOURCE and VIMAX_TEST_PIPER_MODEL')
    ports = []
    while len(ports) < 3:
        value = free_port()
        if value not in ports: ports.append(value)
    public, upstream, skills = ports
    environment = {**os.environ, 'VIMAX_SOURCE_DIR':source, 'VIMAX_SKILLS_PYTHON':sys.executable,
                   'VIMAX_AGENT_PYTHON':sys.executable, 'VIMAX_LOCAL_PORT':str(public), 'VIMAX_UPSTREAM_PORT':str(upstream),
                   'VIMAX_SKILLS_PORT':str(skills), 'VIMAX_PIPER_MODEL':model, 'VIMAX_PIPER_LANGUAGE':'en-US',
                   'VIMAX_SKILLS_OUTPUT':str(tmp_path / 'jobs')}
    environment.pop('VIMAX_SKILLS_VOICES', None)
    process = subprocess.Popen(['node', 'scripts/local.mjs'], cwd=PROJECT, env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        wait_for_port(public, process)
        base = f'http://127.0.0.1:{public}'
        with httpx.Client(base_url=base, timeout=15, trust_env=False) as client:
            assert client.get('/skills/').status_code == 200
            assert len(client.get('/skills/catalog.json').json()['entries']) == 28
            assert client.get('/api/sessions').status_code == 200
            assert client.get('/api/skills/system').json()['ready_for_video'] is True
            assert client.get('/api/sessions', headers={'Host':f'evil.example:{public}'}).status_code == 403
            assert client.get('/api/sessions', headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403
            assert client.post('/api/skills/analyze', headers={'Origin':'https://evil.example'}, json={'idea':'test'}).status_code == 403
            assert client.post('/api/skills/analyze', json={'idea':'test'}).status_code == 403
            analyzed = client.post('/api/skills/analyze', headers={'Origin':base}, json={'idea':'How to grow 5 herbs at home'})
            assert analyzed.status_code == 200 and analyzed.json()['idea']['score'] == 51
            assert httpx.get(f'http://127.0.0.1:{skills}/api/skills/catalog', trust_env=False).status_code == 403
            assert httpx.get(f'http://127.0.0.1:{upstream}/api/sessions', trust_env=False).status_code == 403
            payload = {'topic':'Local end-to-end test', 'script':'This video is generated locally.', 'language':'en-US',
                       'voice_id':'default','duration_seconds':5,'format':'shorts','visual_style':'paper','quality':'draft'}
            response = client.post('/api/skills/jobs', headers={'Origin':base}, json=payload)
            assert response.status_code == 202, response.text
            job_id = response.json()['id']
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                job = client.get(f'/api/skills/jobs/{job_id}').json()
                if job['status'] not in ('queued','running'): break
                time.sleep(.1)
            assert job['status'] == 'awaiting_review', job.get('error')
            video = client.get(f'/api/skills/jobs/{job_id}/files/video.mp4')
            assert video.status_code == 200 and b'ftyp' in video.content[:32]
            approve = client.post(f'/api/skills/jobs/{job_id}/approve', headers={'Origin':base}, json={'confirmed':True})
            assert approve.status_code == 200 and approve.json()['status'] == 'approved'
    finally:
        process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
