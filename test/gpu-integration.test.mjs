import {test} from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {PGlite} from '@electric-sql/pglite';
import {createBridge} from '../api/bridge.mjs';
import {sealGpu,unsealGpu,gpuOutputUrl} from '../api/gpu.mjs';

const owner='1a2b3c4d-0000-4000-8000-000000000001',other='1a2b3c4d-0000-4000-8000-000000000002';
const key='11'.repeat(32);
const env={SUPABASE_URL:'https://example.supabase.co',SUPABASE_PUBLISHABLE_KEY:'sb_publishable_for_test_only',
  VIMAX_GPU_ENABLED:'true',VIMAX_GPU_ALLOWED_USER_IDS:`${owner},${other}`,RUNPOD_API_KEY:'test-only-runpod-key',VIMAX_GPU_TOKEN_KEY:key};
const argNames={vimax_gpu_account_allowed:[],vimax_gpu_prepare:['p_client_key','p_prompt','p_aspect','p_request_hash'],
  vimax_gpu_start_active:['p_id','p_token'],vimax_gpu_finish_start:['p_id','p_token','p_status','p_provider_cipher'],
  vimax_gpu_claim:['p_id'],vimax_gpu_finish:['p_id','p_token','p_status','p_output_cipher','p_cost'],
  vimax_gpu_request_cancel:['p_id'],vimax_gpu_forget:['p_id','p_confirm_uncertain']};
const columns='id,client_key,prompt,aspect,status,reported_cost,cancel_requested,created_at,updated_at';
async function fixture({allowed=[owner],mode='queued'}={}) {
  const db=new PGlite();
  await db.exec(`create schema auth; create role anon; create role authenticated; create table auth.users(id uuid primary key);
    create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
    grant usage on schema auth to anon,authenticated;`);
  for(const id of [owner,other])await db.query('insert into auth.users(id) values ($1)',[id]);
  await db.exec(await readFile(new URL('../supabase/migrations/202610270007_vimax_gpu_previews.sql',import.meta.url),'utf8'));
  for(const id of allowed)await db.query('insert into public.vimax_gpu_allowed_users(owner_id) values ($1)',[id]);
  let lock=Promise.resolve(),providerMode=mode,releaseRun; const providerCalls=[],network=[];
  const gate=new Promise(resolve=>{releaseRun=resolve;});
  async function as(id,op){const previous=lock;let release;lock=new Promise(r=>{release=r;});await previous;
    try{await db.exec('reset role;set role authenticated;');await db.query("select set_config('request.jwt.claim.sub',$1,false)",[id]);return await op();}
    finally{await db.exec('reset role;');release();}}
  async function fakeFetch(raw,init={}) {
    const url=new URL(raw),payload=init.body?JSON.parse(init.body):{};
    network.push({host:url.hostname,path:url.pathname,method:init.method});
    if(url.hostname==='api.runpod.ai') {
      providerCalls.push({path:url.pathname,method:init.method,payload,authorization:init.headers.authorization,redirect:init.redirect});
      if(url.pathname.endsWith('/run')) {
        if(providerMode==='timeout')throw new Error('simulated connection interruption');
        if(providerMode==='reject')return Response.json({error:'private provider details'},{status:429});
        if(providerMode==='hold')await gate;
        if(providerMode==='bad-id')return Response.json({id:'../../other'});
        return Response.json({id:'runpod-job-1',status:'IN_QUEUE'});
      }
      if(url.pathname.includes('/cancel/'))return Response.json({id:'runpod-job-1',status:providerMode==='cancel-race'?'COMPLETED':'CANCELLED'});
      if(url.pathname.includes('/status/')) {
        if(providerMode==='gone')return Response.json({},{status:404});
        if(providerMode==='running')return Response.json({id:'runpod-job-1',status:'IN_PROGRESS'});
        if(providerMode==='evil')return Response.json({id:'runpod-job-1',status:'COMPLETED',output:{result:'https://evil.example/steal',cost:0.10}});
        if(providerMode==='large')return new Response('x'.repeat(70_000),{headers:{'content-type':'application/json'}});
        return Response.json({id:'runpod-job-1',status:'COMPLETED',output:{result:'https://video.runpod.ai/abc123/output.mp4?temporary=secret',cost:0.10}});
      }
      throw new Error('unexpected provider route');
    }
    if(url.hostname!=='example.supabase.co')throw new Error(`Unexpected host ${url.hostname}`);
    const token=init.headers.authorization?.replace('Bearer ','');
    const id=token==='owner-token'?owner:token==='other-token'?other:null;
    if(url.pathname==='/auth/v1/user')return id?Response.json({id,email:'test@example.test'}):Response.json({},{status:401});
    if(!id)return Response.json({},{status:401});
    const name=url.pathname.replace('/rest/v1/rpc/','');
    if(Object.hasOwn(argNames,name))return as(id,async()=>{
      try{const args=argNames[name].map(k=>payload[k]??null);const result=(await db.query(`select public.${name}(${args.map((_,i)=>`$${i+1}`).join(',')}) as result`,args)).rows[0].result;return Response.json(result);}
      catch(error){return Response.json({message:error.message},{status:400});}
    });
    if(url.pathname==='/rest/v1/vimax_gpu_jobs')return as(id,async()=>Response.json((await db.query(`select ${columns} from public.vimax_gpu_jobs order by created_at desc limit 30`)).rows));
    return Response.json({},{status:404});
  }
  return {db,as,fetch:fakeFetch,network,providerCalls,releaseRun,setMode:x=>{providerMode=x;}};
}
const req=(path,{method='GET',who='owner',payload,origin='https://vimax.example'}={})=>new Request(`https://vimax.example${path}`,{method,headers:{origin,cookie:`__Host-vimax_access=${who}-token`,...(payload===undefined?{}:{'content-type':'application/json'})},...(payload===undefined?{}:{body:JSON.stringify(payload)})});
const start=(bridge,payload,who='owner')=>bridge.fetch(req('/api/cloud/gpu/jobs',{method:'POST',payload,who}));
const action=(bridge,id,op,who='owner',payload={})=>bridge.fetch(req(`/api/cloud/gpu/jobs/${id}/${op}`,{method:'POST',payload,who}));
const input=()=>({client_key:randomUUID(),prompt:'A peaceful night sky',aspect:'shorts',confirm_cost:true});

test('GPU encryption binds owner, job and purpose; output hosts are fixed',()=>{
  const aes=Buffer.from(key,'hex'),id=randomUUID(),value='remote-job-1',sealed=sealGpu(aes,owner,id,'job',value);
  assert.equal(unsealGpu(aes,owner,id,'job',sealed),value);
  assert.equal(unsealGpu(aes,other,id,'job',sealed),null);
  assert.equal(unsealGpu(aes,owner,randomUUID(),'job',sealed),null);
  assert.equal(unsealGpu(aes,owner,id,'output',sealed),null);
  assert.equal(unsealGpu(aes,owner,id,'job',sealed+'x'),null);
  assert.equal(gpuOutputUrl('https://video.runpod.ai/a/output.mp4?token=x'),'https://video.runpod.ai/a/output.mp4?token=x');
  for(const url of ['http://video.runpod.ai/a','https://video.runpod.ai.evil.example/a','https://user@video.runpod.ai/a','https://video.runpod.ai:444/a','https://127.0.0.1/a','https://video.runpod.ai/'])assert.equal(gpuOutputUrl(url),null);
});

test('GPU is default-off, account-gated, CSRF-protected and never calls provider without explicit cost consent',async()=>{
  const fx=await fixture({allowed:[]});try{
    const disabled=createBridge({env:{...env,VIMAX_GPU_ENABLED:'false'},fetchImpl:fx.fetch});
    assert.deepEqual(await (await disabled.fetch(req('/api/cloud/gpu/config'))).json(),{configured:false,allowed:false,provider:'Runpod P-Video',verified:false});
    assert.equal((await start(disabled,input())).status,503);
    const bridge=createBridge({env,fetchImpl:fx.fetch});
    assert.equal((await (await bridge.fetch(req('/api/cloud/gpu/config'))).json()).allowed,false);
    assert.equal((await start(bridge,input())).status,403);
    assert.equal((await bridge.fetch(req('/api/cloud/gpu/jobs',{method:'POST',payload:input(),origin:'https://evil.example'}))).status,403);
    assert.equal((await start(bridge,{...input(),confirm_cost:false})).status,422);
    assert.equal(fx.providerCalls.length,0);
  }finally{await fx.db.close();}
});

test('mocked GPU submission is idempotent and isolated; output capability is encrypted and owner-bound',async()=>{
  const fx=await fixture();try{
    const bridge=createBridge({env,fetchImpl:fx.fetch}),payload=input();
    let response=await start(bridge,payload);assert.equal(response.status,202);const started=await response.json();assert.equal(started.status,'queued');
    assert.equal(fx.providerCalls.length,1);const sent=fx.providerCalls[0];
    assert.equal(sent.path,'/v2/p-video/run');assert.equal(sent.redirect,'error');assert.equal(sent.authorization,'Bearer test-only-runpod-key');
    assert.deepEqual(sent.payload.input,{prompt:payload.prompt,duration:5,resolution:'720p',aspect_ratio:'9:16',fps:24,draft:false,save_audio:false,prompt_upsampling:false});
    assert.deepEqual(sent.payload.policy,{executionTimeout:600000,ttl:1200000});
    response=await start(bridge,payload);assert.equal(response.status,200);assert.equal((await response.json()).id,started.id);assert.equal(fx.providerCalls.length,1);
    assert.equal((await start(bridge,{...payload,prompt:'different'})).status,503);
    const history=await (await bridge.fetch(req('/api/cloud/gpu/jobs'))).json();assert.equal(history.jobs.length,1);
    assert.equal(JSON.stringify(history).includes('runpod-job-1'),false);assert.equal(JSON.stringify(history).includes('test-only-runpod-key'),false);
    assert.deepEqual((await (await bridge.fetch(req('/api/cloud/gpu/jobs',{who:'other'}))).json()).jobs,[]);
    assert.equal((await action(bridge,started.id,'check','other')).status,409);
    await assert.rejects(fx.as(owner,()=>fx.db.query('select provider_cipher from public.vimax_gpu_jobs')),/permission denied/i);
    fx.setMode('running');response=await action(bridge,started.id,'check');assert.equal((await response.json()).status,'running');
    fx.setMode('completed');response=await action(bridge,started.id,'check');const completed=await response.json();assert.equal(completed.status,'completed');assert.equal(completed.reported_cost,0.1);assert.equal(JSON.stringify(completed).includes('temporary=secret'),false);
    const row=(await fx.db.query('select provider_cipher,output_cipher from public.vimax_gpu_jobs')).rows[0];assert.ok(!row.provider_cipher.includes('runpod-job-1'));assert.ok(!row.output_cipher.includes('video.runpod.ai'));
    response=await action(bridge,started.id,'output');const output=await response.json();assert.equal(output.url,'https://video.runpod.ai/abc123/output.mp4?temporary=secret');
    assert.equal((await action(bridge,started.id,'forget')).status,200);
    assert.equal((await start(bridge,input())).status,409);assert.equal(fx.providerCalls.filter(x=>x.path.endsWith('/run')).length,1);
  }finally{await fx.db.close();}
});

test('forged database capability cannot make the server cancel another account\'s provider job',async()=>{
  const fx=await fixture({allowed:[owner,other]});try{
    const bridge=createBridge({env,fetchImpl:fx.fetch}),first=await (await start(bridge,input())).json();
    const stolen=(await fx.db.query('select provider_cipher from public.vimax_gpu_jobs where id=$1',[first.id])).rows[0].provider_cipher;
    const clientKey=randomUUID(),hash='a'.repeat(64);
    const reserved=await fx.as(other,async()=> (await fx.db.query('select public.vimax_gpu_prepare($1,$2,$3,$4) r',[clientKey,'another scene','shorts',hash])).rows[0].r);
    const forged=await fx.as(other,async()=> (await fx.db.query('select public.vimax_gpu_finish_start($1,$2,$3,$4) r',[reserved.id,reserved.token,'queued',stolen])).rows[0].r);
    assert.equal(forged.status,'queued');const before=fx.providerCalls.length;
    const result=await action(bridge,reserved.id,'cancel','other');assert.equal(result.status,409);
    assert.equal(fx.providerCalls.length,before,'owner/job-bound AES-GCM must reject forged provider capabilities');
  }finally{await fx.db.close();}
});

test('ambiguous submission never automatically retries or resets daily attempts',async()=>{
  const fx=await fixture({mode:'timeout'});try{
    const bridge=createBridge({env,fetchImpl:fx.fetch}),payload=input();
    let response=await start(bridge,payload);const result=await response.json();assert.equal(result.status,'uncertain');assert.match(result.message,/charges/);
    response=await start(bridge,payload);assert.equal((await response.json()).status,'uncertain');assert.equal(fx.providerCalls.length,1);
    assert.equal((await action(bridge,result.id,'forget')).status,409);
    assert.equal((await action(bridge,result.id,'forget','owner',{confirm_uncertain:true})).status,200);
    assert.equal((await start(bridge,input())).status,409);assert.equal(fx.providerCalls.length,1);
  }finally{await fx.db.close();}
});

test('stop requested during submission is carried forward and confirmed by provider',async()=>{
  const fx=await fixture({mode:'hold'});try{
    const bridge=createBridge({env,fetchImpl:fx.fetch}),promise=start(bridge,input());
    // The mock resolves this signal as soon as the provider call begins.
    while(fx.providerCalls.length===0)await new Promise(resolve=>setImmediate(resolve));
    const id=(await (await bridge.fetch(req('/api/cloud/gpu/jobs'))).json()).jobs[0].id;
    const cancellation=await action(bridge,id,'cancel');assert.equal((await cancellation.json()).status,'starting');
    fx.releaseRun();const response=await promise,result=await response.json();assert.equal(result.status,'cancelled');
    assert.equal(fx.providerCalls.filter(x=>x.path.includes('/cancel/')).length,1);
  }finally{fx.releaseRun();await fx.db.close();}
});

test('untrusted output links and oversized status fail closed without requesting arbitrary URLs',async()=>{
  const fx=await fixture();try{
    const bridge=createBridge({env,fetchImpl:fx.fetch}),started=await (await start(bridge,input())).json();
    fx.setMode('large');assert.equal((await action(bridge,started.id,'check')).status,503);
    fx.setMode('evil');const result=await (await action(bridge,started.id,'check')).json();assert.equal(result.status,'uncertain');
    assert.ok(fx.network.every(x=>['api.runpod.ai','example.supabase.co'].includes(x.host)));
  }finally{await fx.db.close();}
});
