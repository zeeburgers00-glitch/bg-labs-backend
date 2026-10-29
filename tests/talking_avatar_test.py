"""Talking avatar upload and model workflow contract."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import main


def run():
    passed = 0
    with TestClient(main.app) as client:
        reg = client.post('/api/auth/register', data={
            'email': 'avatar@test.local', 'username': 'avatar-user',
            'full_name': 'Avatar User', 'password': 'secret12'
        })
        assert reg.status_code == 200
        token = reg.json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}
        passed += 1

        upload = client.post('/api/talking-avatar/assets', headers=headers, files={
            'portrait': ('me.jpg', b'\xff\xd8\xff\xe0portrait', 'image/jpeg'),
            'voice_sample': ('voice.wav', b'RIFFvoice-sample', 'audio/wav'),
        })
        assert upload.status_code == 200, upload.text
        body = upload.json()
        assert body['portrait_url'] and body['voice_sample_url']
        assert body['asset_id']
        passed += 3

        bad = client.post('/api/talking-avatar/assets', headers=headers, files={
            'portrait': ('not.txt', b'bad', 'text/plain'),
            'voice_sample': ('voice.wav', b'RIFFvoice', 'audio/wav'),
        })
        assert bad.status_code == 400
        passed += 1

        models = client.get('/api/models?capability=avatar', headers=headers)
        ids = {row['id'] for row in models.json()['models']}
        assert 'fal-echomimic' in ids and 'fal-sadtalker' in ids
        passed += 1

    print(f'TALKING AVATAR: {passed} checks / 0 failures')


if __name__ == '__main__':
    run()
