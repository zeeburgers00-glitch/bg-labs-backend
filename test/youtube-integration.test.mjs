import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash, randomUUID} from 'node:crypto';
import {PGlite} from '@electric-sql/pglite';
import {createBridge} from '../api/bridge.mjs';

const owner='11111111-1111-4111-8111-111111111111', other='22222222-2222-4222-8222-222222222222';
const channel='UC1234567890123456789012', video='abcdefghijk';
const keys={SUPABASE_URL:'https://example.supabase.co',SUPABASE_PUBLISHABLE_KEY:'sb_publishable_test',
  VIMAX_YOUTUBE_CLIENT_ID:'1234567890-test.apps.googleusercontent.com',VIMAX_YOUTUBE_CLIENT_SECRET:'fake-secret-for-testing',
  VIMAX_YOUTUBE_TOKEN_KEY:'12'.repeat(32),VIMAX_YOUTUBE_REDIRECT_URI:'https://vimax.example/api/cloud/youtube/callback',
  VIMAX_YOUTUBE_ALLOWED_USER_IDS:owner};
const routes={
  vimax_youtube_account_allowed:[],
  vimax_youtube_prepare:['p_client_key','p_channel_id','p_title','p_size_bytes','p_file_sha256','p_request_sha256'],
  vimax_youtube_finish_start:['p_id','p_token','p_status','p_session_cipher'],
  vimax_youtube_claim:['p_id'],vimax_youtube_finish_chunk:['p_id','p_token','p_status','p_offset_bytes','p_video_id'],
  vimax_youtube_cancel:['p_id'],vimax_youtube_lease_active:['p_id','p_token'],vimax_youtube_forget:['p_id'],
};
function request(path,{method='GET',cookie=`__Host-vimax_access=owner-token`,json,bytes,headers={}}={}) {
  return new Request(`https://vimax.example${path}`,{method,headers:{origin:'https://vimax.example',cookie,
    ...(json!==undefined?{'content-type':'application/json'}:{}),...headers},
    ...(json!==undefined?{body:JSON.stringify(json)}:bytes!==undefined?{body:bytes}:{})});
}
function cookieFrom(response,name) {
  const c=response.headers.getSetCookie().find(v=>v.startsWith(`${name}=`));
  return c?.split(';')[0] || '';
}
async function fixture() {
  const db=new PGlite();
  await db.exec(`create schema auth; create role anon; create role authenticated; create table auth.users(id uuid primary key);
    create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
    grant usage on schema auth to anon,authenticated;`);
  for (const id of [owner,other]) await db.query('insert into auth.users(id) values($1)',[id]);
  await db.exec(await readFile(new URL('../supabase/migrations/202610270005_vimax_youtube_uploads.sql',import.meta.url),'utf8'));
  await db.query('insert into public.vimax_youtube_allowed_users(owner_id) values ($1)',[owner]);
  let lock=Promise.resolve(), remoteOffset=0, uploaded=false, sessions=0, chunks=0, statusChecks=0, privateFlag=false, failChunk=false, failVerify=false;
  let oauthChallenge='', oauthState='', startGate=null, chunkGate=null;
  function gate() {let entered,release;const reached=new Promise(resolve=>{entered=resolve;}), wait=new Promise(resolve=>{release=resolve;});return {reached,entered,wait,release};}
  async function as(id,action) {
    const previous=lock; let release; lock=new Promise(resolve=>{release=resolve;}); await previous;
    try {await db.exec('reset role; set role authenticated;'); await db.query("select set_config('request.jwt.claim.sub',$1,false)",[id]); return await action();}
    finally {await db.exec('reset role;');release();}
  }
  async function fake(raw,init={}) {
    const url=new URL(raw), method=(init.method||'GET').toUpperCase(), h=new Headers(init.headers);
    if (url.hostname==='example.supabase.co') {
      const token=h.get('authorization')?.replace('Bearer ','');
      const id=token==='owner-token'?owner:token==='other-token'?other:null;
      if(url.pathname==='/auth/v1/user') return id?Response.json({id,email:'person@example.test'}):Response.json({}, {status:401});
      if(!id) return Response.json({}, {status:401});
      const name=url.pathname.replace('/rest/v1/rpc/','');
      if(routes[name]) return as(id,async()=>{
        try {
          const p=JSON.parse(init.body||'{}'), values=routes[name].map(x=>p[x]??null);
          const result=(await db.query(`select public.${name}(${values.map((_,i)=>`$${i+1}`).join(',')}) as result`,values)).rows[0].result;
          return Response.json(result);
        } catch(e) {return Response.json({error:e.message},{status:400});}
      });
      if(url.pathname==='/rest/v1/vimax_youtube_uploads') return as(id,async()=>Response.json((await db.query('select id,client_key,channel_id,title,size_bytes,file_sha256,status,offset_bytes,video_id,cancel_requested,created_at,updated_at from public.vimax_youtube_uploads order by created_at desc limit 50')).rows));
      return Response.json({error:'not mocked'}, {status:404});
    }
    if(url.hostname==='oauth2.googleapis.com'&&url.pathname==='/token') {
      const form=new URLSearchParams(init.body);
      assert.equal(form.get('code'),'4/test-code-123');
      assert.equal(createHash('sha256').update(form.get('code_verifier')).digest('base64url'),oauthChallenge);
      return Response.json({access_token:'ya29.fakeGoogleAccessToken',token_type:'Bearer',expires_in:3600,
        scope:'https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload'});
    }
    if(url.hostname==='oauth2.googleapis.com'&&url.pathname==='/revoke') return new Response(null,{status:200});
    assert.equal(url.hostname,'www.googleapis.com');
    assert.equal(h.get('authorization'),'Bearer ya29.fakeGoogleAccessToken');
    if(url.pathname==='/youtube/v3/channels') return Response.json({items:[{id:channel,snippet:{title:'Real authorized channel'}}]});
    if(url.pathname==='/youtube/v3/videos') {
      if(failVerify) return Response.json({error:'unavailable'},{status:503});
      return Response.json({items:[{id:video,snippet:{channelId:channel},status:{privacyStatus:'private'}}]});
    }
    if(url.pathname==='/upload/youtube/v3/videos'&&method==='POST') {
      sessions++; const metadata=JSON.parse(init.body); privateFlag=metadata.status.privacyStatus==='private';
      if(startGate){const g=startGate;startGate=null;g.entered();await g.wait;}
      return new Response(null,{status:200,headers:{location:'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=sensitive_session_123&part=snippet,status'}});
    }
    if(url.pathname==='/upload/youtube/v3/videos'&&method==='PUT') {
      const range=h.get('content-range');
      if(range.startsWith('bytes */')) {
        statusChecks++;
        if(uploaded) return Response.json({id:video},{status:200});
        return new Response(null,{status:308,headers:remoteOffset?{range:`bytes=0-${remoteOffset-1}`}: {}});
      }
      if(chunkGate){const g=chunkGate;chunkGate=null;g.entered();await g.wait;}
      if(failChunk) {failChunk=false;throw new Error('ambiguous transport failure');}
      const m=/^bytes (\d+)-(\d+)\/(\d+)$/.exec(range); assert.ok(m); assert.equal(Number(m[1]),remoteOffset);
      const b=Buffer.from(init.body); assert.equal(b.length,Number(m[2])-Number(m[1])+1); chunks++;remoteOffset+=b.length;
      if(remoteOffset===Number(m[3])) {uploaded=true;return Response.json({id:video},{status:201});}
      return new Response(null,{status:308,headers:{range:`bytes=0-${remoteOffset-1}`}});
    }
    throw new Error('unexpected URL');
  }
  return {db,as,fetch:fake,get stats(){return {remoteOffset,sessions,chunks,statusChecks,privateFlag}},
    setOAuth(url){oauthChallenge=url.searchParams.get('code_challenge');oauthState=url.searchParams.get('state');},get oauthState(){return oauthState},
    failNextChunk(){failChunk=true},failVerification(v){failVerify=v},
    holdStart(){return startGate=gate()},holdChunk(){return chunkGate=gate()}};
}
async function connect(fx,bridge,who='owner-token') {
  const r=await bridge.fetch(request('/api/cloud/youtube/oauth/start',{method:'POST',cookie:`__Host-vimax_access=${who}`,json:{}}));
  assert.equal(r.status,200); const url=new URL((await r.json()).authorization_url); fx.setOAuth(url);
  assert.equal(url.origin,'https://accounts.google.com'); assert.equal(url.searchParams.get('access_type'),'online');
  const pending=cookieFrom(r,'__Host-vimax_yt_pending'); assert.ok(pending.includes('HttpOnly')===false);
  const callback=await bridge.fetch(request(`/api/cloud/youtube/callback?state=${encodeURIComponent(fx.oauthState)}&code=4%2Ftest-code-123`,
    {cookie:`__Host-vimax_access=${who}; ${pending}`}));
  assert.equal(callback.status,303); const auth=cookieFrom(callback,'__Host-vimax_yt_access'); assert.ok(auth);
  assert.equal(auth.includes('ya29.fakeGoogleAccessToken'),false);
  return `__Host-vimax_access=${who}; ${auth}`;
}
const payload=(file,key=randomUUID())=>({client_key:key,title:'A private video',description:'Original material',size_bytes:file.length,
  file_sha256:createHash('sha256').update(file).digest('hex'),made_for_kids:false,confirm_private:true});

test('OAuth PKCE, owner isolation, idempotent resumable private upload and verified result',async()=>{
  const fx=await fixture(); try {
    const bridge=createBridge({env:keys,fetchImpl:fx.fetch}), cookie=await connect(fx,bridge);
    const status=await (await bridge.fetch(request('/api/cloud/youtube/status',{cookie}))).json();
    assert.equal(status.connected,true);assert.equal(status.channel.id,channel);
    const file=Buffer.alloc(1024*1024+137,7), data=payload(file);
    let r=await bridge.fetch(request('/api/cloud/youtube/uploads/start',{method:'POST',cookie,json:data}));
    assert.equal(r.status,201); const id=(await r.json()).id; assert.ok(id); assert.equal(fx.stats.sessions,1);assert.equal(fx.stats.privateFlag,true);
    r=await bridge.fetch(request('/api/cloud/youtube/uploads/start',{method:'POST',cookie,json:data}));
    assert.equal(r.status,200);assert.equal((await r.json()).id,id);assert.equal(fx.stats.sessions,1);
    const encrypted=(await fx.db.query('select session_cipher from public.vimax_youtube_uploads where id=$1',[id])).rows[0].session_cipher;
    assert.ok(encrypted.startsWith('v1.')); assert.equal(encrypted.includes('sensitive_session'),false);
    await assert.rejects(fx.as(owner,()=>fx.db.query('select session_cipher from public.vimax_youtube_uploads')),/permission denied/);
    let mine=await (await bridge.fetch(request('/api/cloud/youtube/uploads',{cookie}))).json(); assert.equal(mine.uploads.length,1);
    const theirs=await (await bridge.fetch(request('/api/cloud/youtube/uploads',{cookie:'__Host-vimax_access=other-token'}))).json();assert.equal(theirs.uploads.length,0);
    const wrong=await bridge.fetch(request(`/api/cloud/youtube/uploads/${id}/cancel`,{method:'POST',cookie:'__Host-vimax_access=other-token',json:{}}));assert.equal(wrong.status,409);
    const h={'content-type':'application/octet-stream','x-vimax-offset':'0','x-vimax-file-sha256':data.file_sha256};
    r=await bridge.fetch(request(`/api/cloud/youtube/uploads/${id}/chunk`,{method:'POST',cookie,headers:h,bytes:file.subarray(0,1024*1024)}));
    assert.equal(r.status,200);assert.equal((await r.json()).offset_bytes,1024*1024);
    h['x-vimax-offset']=String(1024*1024);
    r=await bridge.fetch(request(`/api/cloud/youtube/uploads/${id}/chunk`,{method:'POST',cookie,headers:h,bytes:file.subarray(1024*1024)}));
    assert.equal(r.status,200); const done=await r.json(); assert.equal(done.status,'completed');assert.equal(done.verified,true);assert.equal(done.video_id,video);
    assert.equal(fx.stats.chunks,2);assert.ok(fx.stats.statusChecks>=2);
    mine=await (await bridge.fetch(request('/api/cloud/youtube/uploads',{cookie}))).json(); assert.equal(mine.uploads[0].status,'completed');
  } finally {await fx.db.close();}
});

test('uncertain chunk is not replayed without first reconciling; verification is not faked',async()=>{
  const fx=await fixture(); try {
    const bridge=createBridge({env:keys,fetchImpl:fx.fetch}),cookie=await connect(fx,bridge),file=Buffer.alloc(1040,2),data=payload(file);
    const id=(await (await bridge.fetch(request('/api/cloud/youtube/uploads/start',{method:'POST',cookie,json:data}))).json()).id;
    const h={'content-type':'application/octet-stream','x-vimax-offset':'0','x-vimax-file-sha256':data.file_sha256};
    fx.failNextChunk(); let r=await bridge.fetch(request(`/api/cloud/youtube/uploads/${id}/chunk`,{method:'POST',cookie,headers:h,bytes:file}));assert.equal(r.status,503);
    let row=(await fx.db.query('select status from public.vimax_youtube_uploads where id=$1',[id])).rows[0];assert.equal(row.status,'uncertain');
    const before=fx.stats.statusChecks; fx.failVerification(true);
    r=await bridge.fetch(request(`/api/cloud/youtube/uploads/${id}/chunk`,{method:'POST',cookie,headers:h,bytes:file}));assert.equal(r.status,200);
    let result=await r.json();assert.equal(result.status,'verifying');assert.equal(result.verified,false);assert.ok(fx.stats.statusChecks>before);
    fx.failVerification(false);
    r=await bridge.fetch(request(`/api/cloud/youtube/uploads/${id}/check`,{method:'POST',cookie,json:{}}));assert.equal(r.status,200);
    result=await r.json();assert.equal(result.status,'completed');assert.equal(result.verified,true);assert.equal(fx.stats.chunks,1);
  } finally {await fx.db.close();}
});

test('OAuth is disabled by default, state is bound to owner, cancel blocks chunks, and forgetting cannot reset budgets',async()=>{
  const fx=await fixture(); try {
    const disabled=createBridge({env:{...keys,VIMAX_YOUTUBE_ALLOWED_USER_IDS:''},fetchImpl:fx.fetch});
    let r=await disabled.fetch(request('/api/cloud/youtube/oauth/start',{method:'POST',json:{}})); assert.equal(r.status,403);
    const bridge=createBridge({env:keys,fetchImpl:fx.fetch});
    r=await bridge.fetch(request('/api/cloud/youtube/oauth/start',{method:'POST',json:{}})); const pending=cookieFrom(r,'__Host-vimax_yt_pending');
    r=await bridge.fetch(request('/api/cloud/youtube/callback?state=invalid&code=4%2Ftest-code-123',{cookie:`__Host-vimax_access=owner-token; ${pending}`}));assert.equal(r.status,400);
    const cookie=await connect(fx,bridge),file=Buffer.alloc(64,3),data=payload(file);
    const id=(await (await bridge.fetch(request('/api/cloud/youtube/uploads/start',{method:'POST',cookie,json:data}))).json()).id;
    r=await bridge.fetch(request(`/api/cloud/youtube/uploads/${id}/cancel`,{method:'POST',cookie,json:{}}));assert.equal(r.status,200);
    r=await bridge.fetch(request(`/api/cloud/youtube/uploads/${id}/chunk`,{method:'POST',cookie,headers:{'content-type':'application/octet-stream','x-vimax-offset':'0','x-vimax-file-sha256':data.file_sha256},bytes:file}));assert.equal(r.status,409);
    r=await bridge.fetch(request(`/api/cloud/youtube/uploads/${id}/forget`,{method:'POST',cookie,json:{}}));assert.equal(r.status,200);
    const budget=(await fx.db.query('select attempts from public.vimax_youtube_user_daily_budget where owner_id=$1',[owner])).rows[0];assert.equal(budget.attempts,1);
  } finally {await fx.db.close();}
});


test('stop races preserve a cancelled start and honestly report a video that completed in flight',async()=>{
  const fx=await fixture(); try {
    const bridge=createBridge({env:keys,fetchImpl:fx.fetch}),cookie=await connect(fx,bridge),file=Buffer.alloc(64,5);
    const first=payload(file), gatedStart=fx.holdStart();
    const pendingStart=bridge.fetch(request('/api/cloud/youtube/uploads/start',{method:'POST',cookie,json:first}));
    await gatedStart.reached;
    const started=(await fx.db.query('select id from public.vimax_youtube_uploads where client_key=$1',[first.client_key])).rows[0];
    const stopped=await bridge.fetch(request(`/api/cloud/youtube/uploads/${started.id}/cancel`,{method:'POST',cookie,json:{}}));
    assert.equal(stopped.status,200);gatedStart.release();
    const startResult=await (await pendingStart).json();assert.equal(startResult.status,'cancelled');assert.equal(fx.stats.chunks,0);
    const second=payload(file), created=await bridge.fetch(request('/api/cloud/youtube/uploads/start',{method:'POST',cookie,json:second}));
    const id=(await created.json()).id, gatedChunk=fx.holdChunk();fx.failVerification(true);
    const pendingChunk=bridge.fetch(request(`/api/cloud/youtube/uploads/${id}/chunk`,{method:'POST',cookie,
      headers:{'content-type':'application/octet-stream','x-vimax-offset':'0','x-vimax-file-sha256':second.file_sha256},bytes:file}));
    await gatedChunk.reached;
    assert.equal((await bridge.fetch(request(`/api/cloud/youtube/uploads/${id}/cancel`,{method:'POST',cookie,json:{}}))).status,200);
    gatedChunk.release();const result=await (await pendingChunk).json();
    assert.equal(result.status,'cancelled');assert.equal(result.verified,false);assert.match(result.message,/video may exist/i);
    const row=(await fx.db.query('select status,video_id from public.vimax_youtube_uploads where id=$1',[id])).rows[0];
    assert.equal(row.status,'cancelled');assert.equal(row.video_id,video);assert.equal(fx.stats.chunks,1);
  } finally {await fx.db.close();}
});

test('unauthorized direct reservations do not spend the shared budget or create records',async()=>{
  const fx=await fixture();try {
    const denied=await fx.as(other,async()=>(await fx.db.query('select public.vimax_youtube_prepare($1,$2,$3,$4,$5,$6) as result',
      [randomUUID(),channel,'test',12,'a'.repeat(64),'b'.repeat(64)])).rows[0].result);
    assert.equal(denied.allowed,false);assert.equal(denied.reason,'not_allowed');
    assert.equal((await fx.db.query('select count(*)::int n from public.vimax_youtube_daily_budget')).rows[0].n,0);
    await assert.rejects(fx.as(owner,()=>fx.db.query('select * from public.vimax_youtube_allowed_users')),/permission denied/);
  } finally {await fx.db.close();}
});
