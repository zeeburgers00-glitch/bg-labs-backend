"""Offline integration test for Continue-with-Google channel AI Manager."""
from __future__ import annotations
import asyncio, os, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
for key in ("SUPABASE_URL","SUPABASE_SERVICE_KEY","DATABASE_URL"):
    os.environ.pop(key,None)

from fastapi.testclient import TestClient
import main
from app import agents, google
from app import store as stores

async def fake_uploads(access_token, uploads_playlist, max_results=10, api_key_override=""):
    return [{"video_id":"vid00000001","title":"How I started","url":"https://youtube.com/watch?v=vid00000001",
             "thumbnail":"","stats":{"views":1200,"likes":90,"comments":12}},
            {"video_id":"vid00000002","title":"My second tutorial","url":"https://youtube.com/watch?v=vid00000002",
             "thumbnail":"","stats":{"views":800,"likes":55,"comments":8}}]
async def fake_comments(access_token, video_id, max_results=25, api_key_override=""):
    return [{"comment_id":f"c-{video_id}","author":"Viewer","text":"Can you make a detailed tutorial?","likes":2}]
async def fake_agent(agent_id,payload,provider=None):
    result={
      "analytics":{"insights":["Tutorials perform best"],"actions":["Publish a follow-up"]},
      "strategist":{"ideas":[{"title":"The complete follow-up tutorial","hook":"Do this first"}]},
      "comment_responder":{"replies":[{"comment":"Can you make a detailed tutorial?","reply":"Yes — the detailed guide is next!"}]},
    }[agent_id]
    return {"agent":agent_id,"name":agent_id,"engine":"builtin","provider":"test","model":"test","result":result}
async def fake_autopilot(payload,provider=None,steps=None):
    return {"topic":payload["topic"],"package":{"title":payload["topic"],"script":"script","description":"description","tags":["test"]},"agents":[]}


def run():
    asyncio.run(stores.reset_store())
    client=TestClient(main.app)
    reg=client.post('/api/auth/register',data={'email':'manager@example.com','username':'manager',
                                               'full_name':'Manager','password':'StrongPass123!'})
    assert reg.status_code==200,reg.text
    token=reg.json()['access_token']; headers={'Authorization':'Bearer '+token}
    store=asyncio.run(stores.get_store())
    channel={"channel_id":"UC123","title":"Test Channel","thumbnail":"","custom_url":"",
             "description":"","country":"PK","uploads_playlist":"UU123",
             "stats":{"views":10000,"subscribers":500,"videos":20}}
    payload=google.connection_payload(1,channel,{"access_token":"access","refresh_token":"refresh",
        "expires_at_epoch":time.time()+3600,"expires_at":"2099-01-01T00:00:00+00:00","scope":"youtube"},
        google_user={"email":"creator@example.com"},primary=True)
    asyncio.run(store.add_project(user_id=1,name=payload['name'],project_type=payload['project_type'],settings=payload['settings']))
    old_uploads,old_comments=google.fetch_uploads,google.fetch_comments
    old_agent,old_auto=agents.run_agent,agents.run_autopilot
    google.fetch_uploads,google.fetch_comments=fake_uploads,fake_comments
    agents.run_agent,agents.run_autopilot=fake_agent,fake_autopilot
    try:
        status=client.get('/api/youtube/manager/status?channel_id=UC123',headers=headers)
        assert status.status_code==200,status.text
        assert status.json()['manager']['approval_required'] is True
        saved=client.post('/api/youtube/manager/config',headers=headers,json={"channel_id":"UC123","enabled":True,
            "goal":"reach 1k subscribers","audience":"beginners","permissions":{"comment_drafts":True}})
        assert saved.status_code==200,saved.text
        result=client.post('/api/youtube/manager/run',headers=headers,json={"channel_id":"UC123","build_package":True})
        assert result.status_code==200,result.text
        body=result.json()
        assert body['review_queue']=={"comment_replies":1,"video_ideas":1,"video_package_ready":True,"public_actions_taken":0}
        assert body['approval_required'] is True and body['run_id']
        runs=client.get('/api/youtube/manager/runs?channel_id=UC123',headers=headers)
        assert runs.status_code==200 and runs.json()['count']==1
        print('YOUTUBE AI MANAGER: 10 checks / 0 failures')
    finally:
        google.fetch_uploads,google.fetch_comments=old_uploads,old_comments
        agents.run_agent,agents.run_autopilot=old_agent,old_auto

if __name__=='__main__': run()
