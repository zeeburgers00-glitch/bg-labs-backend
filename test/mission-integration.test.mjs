import {test} from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {PGlite} from '@electric-sql/pglite';
import {createBridge} from '../api/bridge.mjs';
import {createPlanningWorker} from '../scripts/planning-worker.mjs';

const owner='1a2b3c4d-0000-4000-8000-000000000001', other='1a2b3c4d-0000-4000-8000-000000000002';
const env={SUPABASE_URL:'https://example.supabase.co',SUPABASE_PUBLISHABLE_KEY:'sb_publishable_for_test_only'};
const paths={
  vimax_mission_submit:['p_channel_id','p_client_key','p_topic','p_provider','p_model','p_not_before'],
  vimax_mission_pause:['p_paused'], vimax_mission_action:['p_job_id','p_action','p_confirm_duplicate_charge'],
  vimax_mission_heartbeat:['p_worker_id'], vimax_mission_claim:['p_worker_id'], vimax_mission_lease:['p_job_id','p_lease'],
  vimax_mission_release:['p_job_id','p_lease'], vimax_mission_reject:['p_job_id','p_lease'],
  vimax_mission_begin:['p_job_id','p_lease','p_stage'],
  vimax_mission_finish:['p_job_id','p_lease','p_stage','p_call_id','p_secret','p_output','p_input_tokens','p_output_tokens'],
  vimax_mission_fail:['p_job_id','p_lease','p_stage','p_call_id','p_secret','p_code'],
};
const jobColumns='id,channel_id,topic,provider,model,status,review_reason,not_before,attempts,cancel_requested,last_error,created_at,updated_at';
const profileColumns='id,name,niche,audience,language,timezone,brand_voice,format,created_at,updated_at';
async function fixture() {
  const db=new PGlite();
  await db.exec(`create schema auth; create role anon; create role authenticated; create table auth.users(id uuid primary key);
    create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
    grant usage on schema auth to anon,authenticated;`);
  for(const id of [owner,other]) await db.query('insert into auth.users(id) values ($1)',[id]);
  for(const file of ['202610270001_vimax_projects.sql','202610270002_vimax_cloud_ai.sql','202610270003_vimax_ai_finish_token.sql','202610270004_vimax_mission_queue.sql','202610270006_vimax_mission_openai.sql']) await db.exec(await readFile(new URL(`../supabase/migrations/${file}`,import.meta.url),'utf8'));
  let lock=Promise.resolve(), providerMode='success'; const providerCalls=[], network=[];
  async function as(id,operation) {
    const previous=lock; let release; lock=new Promise(resolve=>{release=resolve;}); await previous;
    try { await db.exec('reset role; set role authenticated;'); await db.query("select set_config('request.jwt.claim.sub',$1,false)",[id]); return await operation(); }
    finally { await db.exec('reset role;'); release(); }
  }
  async function fakeFetch(raw,init={}) {
    const url=new URL(raw); const payload=init.body ? JSON.parse(init.body) : {};
    network.push({host:url.hostname,path:url.pathname,method:init.method});
    if(url.hostname==='api.groq.com' || url.hostname==='api.openai.com') {
      providerCalls.push(payload);
      if(providerMode==='timeout') throw new TypeError('network failure');
      if(providerMode==='rate') return Response.json({secret:'must not be shown'},{status:429});
      return Response.json({choices:[{message:{content:`Real adapter result ${providerCalls.length}`},...(providerMode==='truncated'?{finish_reason:'length'}:{})}],usage:{prompt_tokens:12,completion_tokens:8}});
    }
    if(url.hostname!=='example.supabase.co') throw new Error('Unexpected external host');
    const token=init.headers?.authorization?.replace('Bearer ','');
    const id=token==='owner-token' ? owner : token==='other-token' ? other : null;
    if(url.pathname==='/auth/v1/token') {
      const login=payload.email==='owner@example.test' && payload.password==='worker-test-password';
      const refresh=payload.refresh_token==='owner-refresh';
      if(!login&&!refresh) return Response.json({error:'rejected'}, {status:400});
      return Response.json({access_token:'owner-token',refresh_token:'owner-refresh',expires_in:3600,user:{id:owner}});
    }
    if(url.pathname==='/auth/v1/user') return id ? Response.json({id,email:id===owner?'owner@example.test':'other@example.test'}) : Response.json({}, {status:401});
    if(!id) return Response.json({}, {status:401});
    const name=url.pathname.replace('/rest/v1/rpc/','');
    if(paths[name]) return as(id,async()=>{
      try {
        const args=paths[name].map(key=>payload[key] ?? null);
        const result=(await db.query(`select public.${name}(${args.map((_,i)=>`$${i+1}`).join(',')}) as result`,args)).rows[0].result;
        if(name==='vimax_mission_claim' && result===null) return new Response(null,{status:204});
        return Response.json(result);
      } catch(error) {return Response.json({code:error.code,message:error.message},{status:400});}
    });
    if(url.pathname==='/rest/v1/vimax_channels') return as(id,async()=>{
      try {
        if(init.method==='POST') {
          const keys=['name','niche','audience','language','timezone','brand_voice','format'];
          const row=(await db.query(`insert into public.vimax_channels(${keys.join(',')}) values(${keys.map((_,i)=>`$${i+1}`).join(',')}) returning ${profileColumns}`,keys.map(k=>payload[k]))).rows;
          return Response.json(row,{status:201});
        }
        return Response.json((await db.query(`select ${profileColumns} from public.vimax_channels order by created_at desc limit 25`)).rows);
      } catch(error) {return Response.json({code:error.code,message:error.message},{status:400});}
    });
    if(url.pathname==='/rest/v1/vimax_competitors') return as(id,async()=>Response.json((await db.query('select id,channel_id,url,created_at from public.vimax_competitors order by created_at desc limit 625')).rows));
    if(url.pathname==='/rest/v1/vimax_mission_jobs') return as(id,async()=>{
      const filter=url.searchParams.get('id')?.replace('eq.','');
      const rows=filter ? (await db.query(`select ${jobColumns} from public.vimax_mission_jobs where id=$1`,[filter])).rows : (await db.query(`select ${jobColumns} from public.vimax_mission_jobs order by created_at desc limit 50`)).rows;
      return Response.json(rows);
    });
    if(url.pathname==='/rest/v1/vimax_mission_steps') return as(id,async()=>Response.json((await db.query('select stage,status,output,started_at,finished_at from public.vimax_mission_steps where job_id=$1 order by started_at asc',[url.searchParams.get('job_id')?.replace('eq.','')])).rows));
    if(url.pathname==='/rest/v1/vimax_mission_events') return as(id,async()=>Response.json((await db.query('select id,event,stage,created_at from public.vimax_mission_events where job_id=$1 order by id desc limit 100',[url.searchParams.get('job_id')?.replace('eq.','')])).rows));
    if(url.pathname==='/rest/v1/vimax_mission_workers') return as(id,async()=>Response.json((await db.query('select worker_id,last_seen_at from public.vimax_mission_workers order by last_seen_at desc limit 10')).rows));
    if(url.pathname==='/rest/v1/vimax_mission_settings') return as(id,async()=>Response.json((await db.query('select paused from public.vimax_mission_settings limit 1')).rows));
    return Response.json({message:'not mocked'},{status:404});
  }
  return {db,as,fetch:fakeFetch,network,providerCalls,setMode:mode=>{providerMode=mode;}};
}
const req=(path,{method='GET',who='owner',payload,origin='https://vimax.example'}={})=>new Request(`https://vimax.example${path}`,{method,headers:{origin,cookie:`__Host-vimax_access=${who}-token`,...(payload===undefined?{}:{'content-type':'application/json'})},...(payload===undefined?{}:{body:JSON.stringify(payload)})});
const channel={name:'Learning lab',niche:'Astronomy',audience:'Adults',language:'en',timezone:'UTC',brand_voice:'Curious',format:'shorts'};
const workerEnv={...env,VIMAX_WORKER_EMAIL:'owner@example.test',VIMAX_WORKER_PASSWORD:'worker-test-password',VIMAX_WORKER_OWNER_ID:owner,GROQ_API_KEY:'test-only-key'};
const quiet={warn(){},log(){}};

test('bridge + simulated PostgREST + real SQL queue + worker + mocked provider',async()=>{
  const fx=await fixture();
  try {
    const bridge=createBridge({env,fetchImpl:fx.fetch});
    let res=await bridge.fetch(req('/api/cloud/mission/channels',{method:'POST',payload:{...channel,owner_id:other}}));
    assert.equal(res.status,201); const profile=(await res.json()).channel;
    const key=randomUUID(), payload={channel_id:profile.id,client_key:key,topic:'Original space story',provider:'groq',model:'llama-3.1-8b-instant'};
    res=await bridge.fetch(req('/api/cloud/mission/jobs',{method:'POST',payload})); assert.equal(res.status,201); const job=(await res.json()).job;
    res=await bridge.fetch(req('/api/cloud/mission/jobs',{method:'POST',payload})); assert.equal(res.status,200); assert.equal((await res.json()).job.id,job.id);
    let overview=await (await bridge.fetch(req('/api/cloud/mission'))).json();
    assert.equal(overview.channels.length,1); assert.equal(overview.jobs[0].status,'queued'); assert.equal(overview.workers.length,0);
    const worker=createPlanningWorker({env:workerEnv,fetchImpl:fx.fetch,logger:quiet}); await worker.tick();
    assert.equal(fx.providerCalls.length,3);
    for(const call of fx.providerCalls) {
      assert.match(call.messages[0].content,/NO web access/);
      assert.match(call.messages[1].content,/not fetched or analyzed/);
      assert.equal(JSON.stringify(call).includes('test-only-key'),false);
    }
    res=await bridge.fetch(req(`/api/cloud/mission/jobs/${job.id}`)); assert.equal(res.status,200); let detail=await res.json();
    assert.equal(detail.job.status,'needs_review'); assert.equal(detail.job.review_reason,'plan_ready');
    assert.deepEqual(detail.steps.map(s=>s.stage),['ideas','script','review']);
    assert.ok(detail.steps.every(s=>s.status==='completed' && s.output.startsWith('Real adapter result')));
    assert.ok(detail.events.some(e=>e.event==='stage_completed'));
    res=await bridge.fetch(req(`/api/cloud/mission/jobs/${job.id}`,{who:'other'})); assert.equal(res.status,404);
    res=await bridge.fetch(req(`/api/cloud/mission/jobs/${job.id}/action`,{method:'POST',payload:{action:'approve'}})); assert.equal(res.status,200);
    detail=await (await bridge.fetch(req(`/api/cloud/mission/jobs/${job.id}`))).json(); assert.equal(detail.job.status,'completed');
    const calls=await fx.as(owner,()=>fx.db.query("select status,feature,input_tokens,output_tokens from public.vimax_ai_calls where feature='job_stage' order by created_at"));
    assert.equal(calls.rows.length,3); assert.ok(calls.rows.every(row=>row.status==='succeeded'&&row.input_tokens===12&&row.output_tokens===8));
    assert.ok(fx.network.every(call=>['example.supabase.co','api.groq.com'].includes(call.host)));
  } finally {await fx.db.close();}
});

test('OpenAI can be queued and processed through the planning worker with a mocked provider',async()=>{
  const fx=await fixture();
  try {
    const bridge=createBridge({env,fetchImpl:fx.fetch});
    const profile=(await (await bridge.fetch(req('/api/cloud/mission/channels',{method:'POST',payload:channel}))).json()).channel;
    const payload={channel_id:profile.id,client_key:randomUUID(),topic:'OpenAI planning test',provider:'openai',model:'gpt-5.4-mini'};
    let response=await bridge.fetch(req('/api/cloud/mission/jobs',{method:'POST',payload}));
    assert.equal(response.status,201); const job=(await response.json()).job;
    response=await bridge.fetch(req('/api/cloud/mission/jobs',{method:'POST',payload}));
    assert.equal(response.status,200); assert.equal((await response.json()).job.id,job.id);
    fx.setMode('truncated');
    const worker=createPlanningWorker({env:{...workerEnv,OPENAI_API_KEY:'test-only-openai-key'},fetchImpl:fx.fetch,logger:quiet});
    await worker.tick();
    assert.equal(fx.providerCalls.length,3);
    for(const call of fx.providerCalls) {
      assert.equal(call.model,'gpt-5.4-mini'); assert.equal(call.max_completion_tokens,900);
      assert.equal(Object.hasOwn(call,'max_tokens'),false);
    }
    const detail=await (await bridge.fetch(req(`/api/cloud/mission/jobs/${job.id}`))).json();
    assert.equal(detail.job.status,'needs_review'); assert.equal(detail.steps.length,3);
    assert.ok(detail.steps.every(step=>step.output.includes('[Provider output was truncated; review before use.]')));
    assert.equal(fx.network.filter(call=>call.host==='api.openai.com' && call.path==='/v1/chat/completions').length,3);
    assert.equal(fx.network.some(call=>call.host==='api.groq.com'),false);
  } finally {await fx.db.close();}
});

test('worker avoids duplicate paid calls on ambiguous failures and honours backoff and missing configuration',async()=>{
  const fx=await fixture();
  try {
    const bridge=createBridge({env,fetchImpl:fx.fetch});
    const profile=(await (await bridge.fetch(req('/api/cloud/mission/channels',{method:'POST',payload:channel}))).json()).channel;
    const makeJob=async topic=>(await (await bridge.fetch(req('/api/cloud/mission/jobs',{method:'POST',payload:{channel_id:profile.id,client_key:randomUUID(),topic,provider:'groq',model:'llama-3.1-8b-instant'}}))).json()).job;
    const timeout=await makeJob('Timeout test'); fx.setMode('timeout');
    const worker=createPlanningWorker({env:workerEnv,fetchImpl:fx.fetch,logger:quiet}); await worker.tick();
    let detail=await (await bridge.fetch(req(`/api/cloud/mission/jobs/${timeout.id}`))).json();
    assert.equal(detail.job.review_reason,'uncertain'); assert.equal(detail.job.last_error,'ambiguous'); assert.equal(fx.providerCalls.length,1);
    await worker.tick(); assert.equal(fx.providerCalls.length,1);
    let response=await bridge.fetch(req(`/api/cloud/mission/jobs/${timeout.id}/action`,{method:'POST',payload:{action:'retry'}})); assert.equal(response.status,409);
    const rate=await makeJob('Rate test'); fx.setMode('rate'); await worker.tick();
    detail=await (await bridge.fetch(req(`/api/cloud/mission/jobs/${rate.id}`))).json(); assert.equal(detail.job.status,'queued'); assert.equal(detail.job.last_error,'rate_limit');
    await worker.tick(); assert.equal(fx.providerCalls.length,2,'backoff must prevent an immediate retry');
    const bad=await makeJob('Missing provider'); const unconfigured=createPlanningWorker({env:{...workerEnv,GROQ_API_KEY:''},fetchImpl:fx.fetch,logger:quiet});
    await unconfigured.tick(); detail=await (await bridge.fetch(req(`/api/cloud/mission/jobs/${bad.id}`))).json();
    assert.equal(detail.job.status,'failed'); assert.equal(detail.job.last_error,'worker_config'); assert.equal(fx.providerCalls.length,2);
    const audits=await fx.as(owner,()=>fx.db.query("select count(*)::int as n from public.vimax_ai_calls where feature='job_stage'")); assert.equal(audits.rows[0].n,2,'missing config must not consume a reservation');
    const wrong=createPlanningWorker({env:{...workerEnv,VIMAX_WORKER_OWNER_ID:other},fetchImpl:fx.fetch,logger:quiet});
    await assert.rejects(wrong.tick(),/did not match/); assert.equal(fx.providerCalls.length,2);
  } finally {await fx.db.close();}
});

test('mission bridge checks same-origin, validation and own session before database writes',async()=>{
  const fx=await fixture();
  try {
    const bridge=createBridge({env,fetchImpl:fx.fetch});
    assert.equal((await bridge.fetch(req('/api/cloud/mission/channels',{method:'POST',origin:'https://evil.example',payload:channel}))).status,403);
    assert.equal((await bridge.fetch(req('/api/cloud/mission/channels',{method:'POST',payload:{...channel,timezone:'Not/AZone'}}))).status,422);
    assert.equal((await bridge.fetch(req('/api/cloud/mission/competitors',{method:'POST',payload:{channel_id:randomUUID(),url:'https://youtube.com.evil.example/@x'}}))).status,422);
    assert.equal((await bridge.fetch(req('/api/cloud/mission/jobs',{method:'POST',payload:{channel_id:randomUUID(),client_key:randomUUID(),topic:'x',provider:'groq',model:'../invalid'}}))).status,422);
    const anonymous=new Request('https://vimax.example/api/cloud/mission'); assert.equal((await bridge.fetch(anonymous)).status,401);
    assert.equal(fx.providerCalls.length,0);
  } finally {await fx.db.close();}
});
