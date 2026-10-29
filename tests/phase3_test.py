"""Offline integration checks for skills, provider hub, vault, ViMax and timeline."""
from __future__ import annotations
import asyncio, os, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
for name in ("SUPABASE_URL","SUPABASE_SERVICE_KEY","DATABASE_URL","OPENAI_API_KEY","GEMINI_API_KEY",
             "GROQ_API_KEY","OPENROUTER_API_KEY","FAL_KEY","REPLICATE_API_TOKEN"):
    os.environ.pop(name,None)

from fastapi.testclient import TestClient
import main
from app import store as stores


def run():
    asyncio.run(stores.reset_store())
    client=TestClient(main.app)
    reg=client.post('/api/auth/register',data={'email':'phase3@example.com','username':'phase3tester',
                                               'full_name':'Phase Three','password':'StrongPass123!'})
    assert reg.status_code==200,reg.text
    headers={'Authorization':'Bearer '+reg.json()['access_token']}
    checks=0
    def call(method,path,code=200,**kwargs):
        nonlocal checks
        response=getattr(client,method)(path,headers=headers,**kwargs)
        assert response.status_code==code,(path,response.status_code,response.text)
        checks+=1
        return response.json() if response.text else {}

    models=call('get','/api/models')
    assert len(models['models'])>=70 and len(models['status']['repos'])>=40
    assert {'chat','tts','image','video','avatar','render'} <= set(models['capabilities'])
    checks+=2

    call('put','/api/providers/keys/GROQ_API_KEY',json={'value':'gsk_test_secret_1234'})
    status=call('get','/api/providers/keys')
    assert 'gsk_test_secret_1234' not in str(status)
    groq=next(row for row in status['keys'] if row['name']=='GROQ_API_KEY')
    assert groq['stored_by_you'] and groq['masked'].endswith('1234')
    checks+=2
    call('delete','/api/providers/keys/GROQ_API_KEY')

    rendered=call('post','/api/generate/render',json={'model':'timeline-local','title':'Test',
        'shots':[{'prompt':'open','duration':4,'image_url':'https://example.com/a.jpg'},
                 {'prompt':'payoff','duration':5,'video_url':'https://example.com/b.mp4'}]})
    tl=rendered['json']
    assert tl['format']=='bglabs.timeline.v1' and tl['meta']['shots']==2 and tl['meta']['duration']==9
    assert 'ffmpeg_filter_complex' in tl['render'] and 'moviepy_python' in tl['render']
    checks+=2

    project=call('post','/api/vimax/idea2video/run',json={
        'idea':'The last bookbinder in Lahore saves one final manuscript',
        'duration_seconds':45,'shots':6,'generate_images':False,'render_video':False})
    assert len(project['shots'])==6 and project['project_id']
    checks+=1
    pid=project['project_id']
    call('get',f'/api/vimax/projects/{pid}')
    project_tl=call('get',f'/api/vimax/projects/{pid}/timeline')
    assert project_tl['format']=='bglabs.timeline.v1'
    checks+=1
    listed=call('get','/api/vimax/projects/list')
    assert listed['count']==1
    checks+=1

    edl=call('post','/api/vimax/timeline/edl',json={'edl':'DEAD 00:05 - 00:08 pause\nFILLER 00:12 - 00:13 um',
                                                     'total_duration':20,'source':'x.mp4'})
    assert len(edl['edits'])==2 and edl['timeline']['meta']['removed_seconds']==4
    checks+=1

    skill=call('post','/api/skills/command',json={'command':'/yt-script Why most channels die --length short'})
    assert skill['gate']=='ship it, or change it?' and len(skill['best_two'])==2
    checks+=1
    call('post','/api/generate/video',code=503,json={'prompt':'cat','model':'veo-3'})
    call('post','/api/vimax/bad/run',code=404,json={})
    print(f"PHASE 3: {checks} checks / 0 failures")

if __name__=='__main__': run()
