"""Offline tests for conversational YouTube agent routing."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import main


def run():
    checks = 0
    with TestClient(main.app) as client:
        reg = client.post('/api/auth/register', data={
            'email': 'yt-chat@test.local', 'username': 'yt-chat-user',
            'full_name': 'YT Chat', 'password': 'secret12'
        })
        assert reg.status_code == 200
        headers = {'Authorization': 'Bearer ' + reg.json()['access_token']}
        checks += 1

        status = client.get('/api/youtube/agent/status', headers=headers)
        assert status.status_code == 200
        assert status.json()['ready'] is True and status.json()['connected'] is False
        assert len(status.json()['agents']) == 8
        checks += 3

        cases = [
            ('Give me a 30 day content strategy', 'strategist'),
            ('Write a strong hook and script about AI', 'scriptwriter'),
            ('Analyze my CTR and retention performance', 'analytics'),
            ('Create clickable thumbnail concepts', 'thumbnail'),
        ]
        for message, expected in cases:
            result = client.post('/api/youtube/agent/chat', headers=headers, json={'message': message})
            assert result.status_code == 200, result.text
            data = result.json()
            assert data['agent'] == expected
            assert data['connected'] is False
            assert data['approval_required'] is True and data['public_actions_taken'] == 0
            assert data['reply'] and data['run_id']
            checks += 5

        empty = client.post('/api/youtube/agent/chat', headers=headers, json={'message': ''})
        assert empty.status_code == 400
        checks += 1

    print(f'YOUTUBE AGENT CHAT: {checks} checks / 0 failures')


if __name__ == '__main__':
    run()
