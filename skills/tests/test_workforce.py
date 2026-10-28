"""Real upstream pure functions, strict wrappers, companion API and ViMax tools."""
import asyncio
import json
import os
from pathlib import Path
import socket
import sys

from fastapi.testclient import TestClient
import pytest

from vimax_skills.service import create_app
from vimax_skills.workforce import analyze_funnel, parse_youtube_reference

TOKEN = 'x' * 64
HEADERS = {'x-vimax-local-token': TOKEN}
VIDEO = 'dQw4w9WgXcQ'


@pytest.mark.parametrize('reference,kind,canonical', [
    (VIDEO, 'video', f'https://www.youtube.com/watch?v={VIDEO}'),
    (f'https://youtu.be/{VIDEO}?t=3', 'video', f'https://www.youtube.com/watch?v={VIDEO}'),
    (f'https://www.youtube.com/watch?list=abcd&v={VIDEO}', 'video', f'https://www.youtube.com/watch?v={VIDEO}'),
    (f'https://m.youtube.com/shorts/{VIDEO}', 'shorts', f'https://www.youtube.com/watch?v={VIDEO}'),
    (f'https://youtube.com/embed/{VIDEO}', 'video', f'https://www.youtube.com/watch?v={VIDEO}'),
    (f'https://youtube.com/live/{VIDEO}', 'video', f'https://www.youtube.com/watch?v={VIDEO}'),
    ('https://youtube.com/@some.handle', 'handle', 'https://www.youtube.com/@some.handle'),
    ('https://youtube.com/channel/UCabcdefghijklmnopqrstuv', 'channel', 'https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv'),
    ('https://youtube.com/user/SomeUser', 'user', 'https://www.youtube.com/user/SomeUser'),
    ('https://youtube.com/c/SomeCreator', 'c', 'https://www.youtube.com/c/SomeCreator'),
])
def test_reference_parser_canonicalizes_valid_references_without_fetch(monkeypatch, reference, kind, canonical):
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('Network call is not allowed'))
    result = parse_youtube_reference(reference)
    assert result['canonical_url'] == canonical
    assert result['reference_kind'] == kind
    assert result['is_short'] is (kind == 'shorts')
    assert 'does not fetch' in result['notice']


@pytest.mark.parametrize('reference', [
    '', ' ', 'not-a-real-video-id', f'{VIDEO}junk',
    f'https://youtube.com.evil.example/watch?v={VIDEO}',
    f'https://evil.example/youtube.com/watch?v={VIDEO}',
    f'https://youtube.com@evil.example/watch?v={VIDEO}',
    f'https://evil.example@youtube.com/watch?v={VIDEO}',
    f'https://youtube.com:443/watch?v={VIDEO}',
    f'http://youtube.com/watch?v={VIDEO}',
    f'https://youtube.com/watch?v={VIDEO}extra',
    f'https://youtube.com/watch?v={VIDEO}&v={VIDEO}',
    f'https://youtu.be/{VIDEO}/other',
    f'https://youtube.com/shorts/{VIDEO}garbage',
    f'https://youtube.com/%73horts/{VIDEO}',
    f'https://youtube.com//watch?v={VIDEO}',
    f'https://youtube.com/watch?v={VIDEO}\n',
    'https://youtube.com/@bad%2Fhandle',
    'https://youtube.com/channel/UCbad',
    'https://youtube.com/user/Some.User',
    'https://youtube.com/' + 'x' * 2100,
    3, None,
])
def test_reference_parser_rejects_spoofed_or_ambiguous_inputs(reference):
    with pytest.raises(ValueError):
        parse_youtube_reference(reference)


def test_funnel_uses_supplied_values_only_and_qualifies_estimates():
    result = analyze_funnel({'format':'long','metrics':{'impressions':4000,'ctr':2,'avd_seconds':40,'length_seconds':100,'views':90}})
    assert result['status'] == 'review'
    assert result['binding_constraint'] == 'CTR'
    assert result['views'] == 90 and result['estimated_views_from_impressions'] == 80
    assert any('not total video views' in warning for warning in result['warnings'])
    assert 'no YouTube data was fetched' in result['notice']
    assert analyze_funnel({'metrics':{'views':0}})['status'] == 'insufficient_data'


def test_shorts_do_not_use_long_form_funnel_or_estimate_views():
    result = analyze_funnel({'format':'shorts','metrics':{'impressions':10000,'ctr':10,'views':25,'avd_seconds':34,'length_seconds':30}})
    assert result['status'] == 'shorts_requires_context'
    assert result['binding_constraint'] is None and result['links'] == []
    assert result['estimated_views_from_impressions'] is None and result['views_est'] == 25
    assert result['avg_pct_viewed'] > 100  # replays are possible
    assert any('ignored for Shorts' in warning for warning in result['warnings'])
    assert 'engaged_views' in result['context_required']


@pytest.mark.parametrize('payload', [
    {}, {'metrics':{}}, {'format':'other','metrics':{'views':1}}, {'format':[],'metrics':{'views':1}},
    {'metrics':{'views':True}}, {'metrics':{'views':1.5}}, {'metrics':{'views':-1}},
    {'metrics':{'views':float('nan')}}, {'metrics':{'views':float('inf')}}, {'metrics':{'views':10**400}},
    {'metrics':{'ctr':101}}, {'metrics':{'length_seconds':0}}, {'metrics':{'length_seconds':1e-320}},
    {'metrics':{'avd_seconds':86401}}, {'metrics':{'viewed_pct':50}}, {'metrics':{'views':1},'ignored':1},
])
def test_funnel_rejects_invalid_or_ignored_metrics(payload):
    with pytest.raises(ValueError):
        analyze_funnel(payload)


def test_local_companion_auth_allowlist_and_shared_registry(tmp_path):
    app = create_app(token=TOKEN, output_root=tmp_path)
    with TestClient(app) as client:
        assert client.get('/api/skills/workforce').status_code == 403
        registry = client.get('/api/skills/workforce', headers=HEADERS)
        assert registry.status_code == 200 and registry.headers['cache-control'] == 'no-store'
        disk = json.loads((Path(__file__).resolve().parents[2] / 'catalog' / 'workforce-skills.json').read_text())
        assert registry.json() == disk
        response = client.post('/api/skills/workforce/youtube_url_parser', headers=HEADERS, json={'input':{'reference':VIDEO}})
        assert response.status_code == 200 and response.json()['result']['video_id'] == VIDEO
        response = client.post('/api/skills/workforce/funnel_heuristic', headers=HEADERS,
                               json={'input':{'format':'shorts','metrics':{'views':42}}})
        assert response.status_code == 200 and response.json()['result']['status'] == 'shorts_requires_context'
        assert client.post('/api/skills/workforce/metadata_preflight', headers=HEADERS, json={'input':{}}).status_code == 404
        assert client.post('/api/skills/workforce/youtube_url_parser', headers=HEADERS, json={'input':{'reference': 'https://evil.example'}}).status_code == 422
        assert client.post('/api/skills/workforce/youtube_url_parser', headers=HEADERS, json={'input':{'reference': VIDEO},'extra':True}).status_code == 422
        assert client.post('/api/skills/workforce/youtube_url_parser', json={'input':{'reference': VIDEO}}).status_code == 403


def test_pinned_real_vimax_registry_registers_and_executes_tools():
    source = os.environ.get('VIMAX_TEST_SOURCE')
    if not source:
        pytest.skip('Set VIMAX_TEST_SOURCE to the pinned ViMax source checkout')
    sys.path.insert(0, source)
    from agent_runtime.tools import ToolRegistry
    from vimax_skills.agent_tools import build_skill_specs
    registry = ToolRegistry(build_skill_specs())
    for name in ('youtube_reference_parse', 'youtube_funnel_review'):
        spec = registry.get_spec(name)
        assert spec is not None and spec.permission_mode == 'read-only' and spec.concurrency_safe
    parsed = asyncio.run(registry.execute('youtube_reference_parse', {'reference':VIDEO}))
    assert parsed.ok and json.loads(parsed.content)['video_id'] == VIDEO
    reviewed = asyncio.run(registry.execute('youtube_funnel_review', {'input':{'format':'long','metrics':{'ctr':2}}}))
    assert reviewed.ok and json.loads(reviewed.content)['status'] == 'review'
    rejected = asyncio.run(registry.execute('youtube_reference_parse', {'reference':f'https://youtube.com.evil.example/watch?v={VIDEO}'}))
    assert not rejected.ok and rejected.metadata['error_type'] == 'invalid_input'
