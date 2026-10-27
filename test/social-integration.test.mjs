import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {PGlite} from '@electric-sql/pglite';
import {createBridge} from '../api/bridge.mjs';

const owner='11111111-1111-4111-8111-111111111111',other='22222222-2222-4222-8222-222222222222';
const keys={SUPABASE_URL:'https://example.supabase.co',SUPABASE_PUBLISHABLE_KEY:'sb_publishable_test',
  VIMAX_SOCIAL_ALLOWED_USER_IDS:`${owner},${other}`,VIMAX_SOCIAL_TOKEN_KEY:'34'.repeat(32),
  VIMAX_TIKTOK_CLIENT_KEY:'testtiktokkey123',VIMAX_TIKTOK_CLIENT_SECRET:'fake-tiktok-secret',
  VIMAX_TIKTOK_REDIRECT_URI:'https://vimax.example/api/cloud/social/tiktok/callback',
  VIMAX_FACEBOOK_APP_ID:'123456789012345',VIMAX_FACEBOOK_APP_SECRET:'fake-facebook-secret',
  VIMAX_FACEBOOK_REDIRECT_URI:'https://vimax.example/api/cloud/social/facebook/callback'};
const routes={vimax_social_account_allowed:['p_provider'],vimax_social_connection_save:['p_provider','p_items'],
  vimax_social_connection_claim:['p_provider','p_id'],vimax_social_connection_finish:['p_provider','p_id','p_lease','p_status','p_cipher','p_verified'],
  vimax_social_connection_remove:['p_provider','p_id']};
const request=(path,{method='GET',cookie='__Host-vimax_access=owner-token',json}={})=>new Request(`https://vimax.example${path}`,{method,
  headers:{origin:'https://vimax.example',cookie,...(json!==undefined?{'content-type':'application/json'}:{})},...(json!==undefined?{body:JSON.stringify(json)}:{})});
const cookieFrom=(r,name)=>r.headers.getSetCookie().find(c=>c.startsWith(`${name}=`))?.split(';')[0]||'';
async function fixture(){
  const db=new PGlite();await db.exec(`create schema auth;create role anon;create role authenticated;create table auth.users(id uuid primary key);
    create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
    grant usage on schema auth to anon,authenticated;`);
  for(const id of [owner,other])await db.query('insert into auth.users(id) values($1)',[id]);
  await db.exec(await readFile(new URL('../supabase/migrations/202610270009_vimax_social_connections.sql',import.meta.url),'utf8'));
  await db.query("insert into public.vimax_social_allowed_users(owner_id,provider) values($1,'tiktok'),($1,'facebook'),($2,'tiktok'),($2,'facebook')",[owner,other]);
  let lock=Promise.resolve(),serial=0,refreshes=0,revokes=0,tikMode='ok',fbMode='ok',refreshGate=null,tooMany=false;
  const tikAccess=new Map(),tikRefresh=new Map(),pages=[{id:'123456789',name:'Page One',access_token:'facebookPageTokenOne12345'},
    {id:'987654321',name:'Page Two',access_token:'facebookPageTokenTwo12345'}];
  function gate(){let enter,release;const reached=new Promise(r=>enter=r),wait=new Promise(r=>release=r);return {reached,wait,enter,release};}
  async function as(id,action){const previous=lock;let release;lock=new Promise(r=>release=r);await previous;
    try{await db.exec('reset role;set role authenticated');await db.query("select set_config('request.jwt.claim.sub',$1,false)",[id]);return await action();}
    finally{await db.exec('reset role');release();}}
  async function fetchImpl(raw,init={}){
    const url=new URL(raw),h=new Headers(init.headers),method=(init.method||'GET').toUpperCase();
    if(url.hostname==='example.supabase.co'){
      const token=h.get('authorization')?.replace('Bearer ','');const id=token==='owner-token'?owner:token==='other-token'?other:null;
      if(url.pathname==='/auth/v1/user')return id?Response.json({id,email:'person@example.test'}):Response.json({}, {status:401});
      if(!id)return Response.json({}, {status:401});
      const name=url.pathname.replace('/rest/v1/rpc/','');
      if(routes[name])return as(id,async()=>{try{const p=JSON.parse(init.body||'{}'),args=routes[name].map(x=>p[x]??null);
        const sql=`select public.${name}(${args.map((_,i)=>`$${i+1}`).join(',')}) as result`;
        const result=(await db.query(sql,args.map(x=>Array.isArray(x)?JSON.stringify(x):x))).rows[0].result;return Response.json(result);
      }catch(e){return Response.json({error:e.message},{status:400});}});
      if(url.pathname==='/rest/v1/vimax_social_connections')return as(id,async()=>Response.json((await db.query('select id,provider,external_id,display_name,status,is_default,verified_at,updated_at from public.vimax_social_connections order by updated_at desc limit 20')).rows));
      return Response.json({error:'unmocked'}, {status:404});
    }
    if(url.hostname==='open.tiktokapis.com'){
      if(url.pathname==='/v2/oauth/token/'){
        const form=new URLSearchParams(init.body);assert.equal(method,'POST');assert.equal(form.get('client_key'),keys.VIMAX_TIKTOK_CLIENT_KEY);
        if(form.get('grant_type')==='refresh_token'){
          refreshes++;if(refreshGate){const g=refreshGate;refreshGate=null;g.enter();await g.wait;}
          if(tikMode==='network')throw new Error('ambiguous provider timeout');
          if(tikMode==='invalid')return Response.json({error:'invalid_grant'},{status:400});
          const open=tikRefresh.get(form.get('refresh_token'));if(!open)return Response.json({error:'invalid_grant'},{status:400});
          const access=`act.fake_access_${++serial}`,refresh=`rft.fake_refresh_${serial}`;tikRefresh.delete(form.get('refresh_token'));tikRefresh.set(refresh,open);tikAccess.set(access,open);
          return Response.json({access_token:access,refresh_token:refresh,open_id:open,expires_in:86400,refresh_expires_in:31536000,token_type:'Bearer'});
        }
        assert.equal(form.get('code'),'tiktok-code-123');const open='tiktok_user_123',access=`act.fake_access_${++serial}`,refresh=`rft.fake_refresh_${serial}`;
        tikAccess.set(access,open);tikRefresh.set(refresh,open);
        return Response.json({access_token:access,refresh_token:refresh,open_id:open,expires_in:60,refresh_expires_in:31536000,token_type:'Bearer',scope:'user.info.basic'});
      }
      if(url.pathname==='/v2/user/info/'){
        const open=tikAccess.get((h.get('authorization')||'').replace('Bearer ',''));assert.ok(open);
        return Response.json({data:{user:{open_id:open,display_name:'TikTok profile'}},error:{code:'ok'}});
      }
      if(url.pathname==='/v2/oauth/revoke/'){revokes++;return new Response(null,{status:200});}
    }
    if(url.hostname==='graph.facebook.com'){
      if(url.pathname==='/v26.0/oauth/access_token'){
        assert.equal(url.searchParams.get('client_id'),keys.VIMAX_FACEBOOK_APP_ID);
        if(url.searchParams.get('grant_type')==='fb_exchange_token')return Response.json({access_token:'facebookLongUserToken_123456',expires_in:5184000,token_type:'bearer'});
        assert.equal(url.searchParams.get('code'),'facebook-code-123');return Response.json({access_token:'facebookShortUserToken_12345',expires_in:3600});
      }
      if(url.pathname==='/v26.0/me/accounts'){
        assert.equal(h.get('authorization'),'Bearer facebookLongUserToken_123456');
        if(fbMode==='invalid')return Response.json({error:{code:190}},{status:400});
        return Response.json({data:pages,...(tooMany?{paging:{next:'https://graph.facebook.com/next'}}:{})});
      }
    }
    throw new Error('unexpected provider request');
  }
  return {db,as,fetchImpl,get stats(){return {refreshes,revokes}},setTik(v){tikMode=v},setFb(v){fbMode=v},many(v){tooMany=v},holdRefresh(){return refreshGate=gate()}};
}
async function connect(fx,bridge,provider,who='owner-token'){
  const cookie=`__Host-vimax_access=${who}`;
  let r=await bridge.fetch(request(`/api/cloud/social/${provider}/start`,{method:'POST',cookie,json:{}}));assert.equal(r.status,200,await r.clone().text());
  const url=new URL((await r.json()).authorization_url),pending=cookieFrom(r,`__Host-vimax_${provider}_pending`);
  assert.equal(url.origin,provider==='tiktok'?'https://www.tiktok.com':'https://www.facebook.com');
  assert.equal(url.searchParams.get('scope'),provider==='tiktok'?'user.info.basic':'pages_show_list');
  r=await bridge.fetch(request(`/api/cloud/social/${provider}/callback?state=${encodeURIComponent(url.searchParams.get('state'))}&code=${provider}-code-123`,{cookie:`${cookie}; ${pending}`}));
  return r;
}

test('TikTok consent saves encrypted credentials, restores with rotation and isolates owners',async()=>{
  const fx=await fixture();try{
    const bridge=createBridge({env:keys,fetchImpl:fx.fetchImpl});assert.equal((await connect(fx,bridge,'tiktok')).status,303);
    let status=await (await bridge.fetch(request('/api/cloud/social/status'))).json();assert.equal(status.connections.length,1);
    const id=status.connections[0].id;assert.equal(status.connections[0].external_id,'tiktok_user_123');
    const cipher=(await fx.db.query('select credential_cipher from public.vimax_social_connections where id=$1',[id])).rows[0].credential_cipher;
    assert.match(cipher,/^v1\./);assert.doesNotMatch(cipher,/fake_refresh|fake_access/);assert.doesNotMatch(JSON.stringify(status),/fake_refresh|fake_access/);
    await assert.rejects(fx.as(owner,()=>fx.db.query('select credential_cipher from public.vimax_social_connections')),/permission denied/);
    let r=await bridge.fetch(request('/api/cloud/social/tiktok/select',{method:'POST',cookie:'__Host-vimax_access=other-token',json:{id}}));assert.equal(r.status,404);
    const copied=await fx.as(other,async()=>(await fx.db.query('select public.vimax_social_connection_save($1,$2::jsonb) result',
      ['tiktok',JSON.stringify([{external_id:'tiktok_user_123',display_name:'Copied',credential_cipher:cipher}])])).rows[0].result);
    const before=fx.stats.refreshes;
    r=await bridge.fetch(request('/api/cloud/social/tiktok/select',{method:'POST',cookie:'__Host-vimax_access=other-token',json:{id:copied.connections[0].id}}));
    assert.equal(r.status,409);assert.equal(fx.stats.refreshes,before,'another owner cannot decrypt a copied ciphertext');
    r=await bridge.fetch(request('/api/cloud/social/tiktok/select',{method:'POST',json:{id}}));assert.equal(r.status,200);assert.equal(fx.stats.refreshes,1);
    const after=(await fx.db.query('select credential_cipher from public.vimax_social_connections where id=$1',[id])).rows[0].credential_cipher;
    assert.notEqual(after,cipher);
    r=await bridge.fetch(request('/api/cloud/social/tiktok/select',{method:'POST',json:{id}}));assert.equal(r.status,200);assert.equal(fx.stats.refreshes,1);
    r=await bridge.fetch(request('/api/cloud/social/tiktok/disconnect',{method:'POST',json:{id}}));assert.equal(r.status,200);assert.equal((await r.json()).revoked,true);assert.equal(fx.stats.revokes,1);
    status=await (await bridge.fetch(request('/api/cloud/social/status'))).json();assert.equal(status.connections.length,0);
  }finally{await fx.db.close();}
});

test('TikTok refresh is exclusive and uncertain outcomes require new consent',async()=>{
  const fx=await fixture();try{
    const bridge=createBridge({env:keys,fetchImpl:fx.fetchImpl});await connect(fx,bridge,'tiktok');
    let status=await (await bridge.fetch(request('/api/cloud/social/status'))).json(),id=status.connections[0].id;
    const gate=fx.holdRefresh(),first=bridge.fetch(request('/api/cloud/social/tiktok/select',{method:'POST',json:{id}}));await gate.reached;
    let r=await bridge.fetch(request('/api/cloud/social/tiktok/select',{method:'POST',json:{id}}));assert.equal(r.status,409);
    r=await bridge.fetch(request('/api/cloud/social/tiktok/disconnect',{method:'POST',json:{id}}));assert.equal(r.status,409);
    gate.release();assert.equal((await first).status,200);assert.equal(fx.stats.refreshes,1);
    await connect(fx,bridge,'tiktok');fx.setTik('network');
    r=await bridge.fetch(request('/api/cloud/social/tiktok/select',{method:'POST',json:{id}}));assert.equal(r.status,503);
    status=await (await bridge.fetch(request('/api/cloud/social/status'))).json();assert.equal(status.connections[0].status,'uncertain');
    const before=fx.stats.refreshes;r=await bridge.fetch(request('/api/cloud/social/tiktok/select',{method:'POST',json:{id}}));assert.equal(r.status,409);assert.equal(fx.stats.refreshes,before);
    r=await bridge.fetch(request('/api/cloud/social/tiktok/disconnect',{method:'POST',json:{id}}));assert.equal(r.status,200);assert.equal((await r.json()).revoked,false);
  }finally{await fx.db.close();}
});

test('Facebook saves only consented Pages, switches separately, and never claims local removal revoked Meta access',async()=>{
  const fx=await fixture();try{
    const bridge=createBridge({env:keys,fetchImpl:fx.fetchImpl});assert.equal((await connect(fx,bridge,'facebook')).status,303);
    let status=await (await bridge.fetch(request('/api/cloud/social/status'))).json();assert.equal(status.connections.length,2);
    const first=status.connections.find(x=>x.external_id==='123456789'),second=status.connections.find(x=>x.external_id==='987654321');
    assert.ok(first.is_default);assert.equal(second.is_default,false);assert.doesNotMatch(JSON.stringify(status),/facebookLongUserToken|facebookPageToken/);
    const rows=(await fx.db.query('select credential_cipher from public.vimax_social_connections')).rows;
    for(const row of rows)assert.doesNotMatch(row.credential_cipher,/facebookLongUserToken|facebookPageToken/);
    let r=await bridge.fetch(request('/api/cloud/social/facebook/select',{method:'POST',json:{id:second.id}}));assert.equal(r.status,200);
    status=await (await bridge.fetch(request('/api/cloud/social/status'))).json();assert.equal(status.connections.find(x=>x.id===second.id).is_default,true);
    fx.setFb('invalid');r=await bridge.fetch(request('/api/cloud/social/facebook/select',{method:'POST',json:{id:first.id}}));assert.equal(r.status,409);
    status=await (await bridge.fetch(request('/api/cloud/social/status'))).json();assert.equal(status.connections.find(x=>x.id===first.id).status,'needs_reauth');
    r=await bridge.fetch(request('/api/cloud/social/facebook/disconnect',{method:'POST',json:{id:second.id}}));assert.equal(r.status,200);assert.equal((await r.json()).revoked,false);
  }finally{await fx.db.close();}
});

test('denied consent, excess Pages and missing provider configuration do not fake a connection',async()=>{
  const fx=await fixture();try{
    const bridge=createBridge({env:keys,fetchImpl:fx.fetchImpl}),start=await bridge.fetch(request('/api/cloud/social/facebook/start',{method:'POST',json:{}}));
    const pending=cookieFrom(start,'__Host-vimax_facebook_pending');
    let r=await bridge.fetch(request('/api/cloud/social/facebook/callback?state=bad&code=facebook-code-123',{cookie:`__Host-vimax_access=owner-token; ${pending}`}));assert.equal(r.status,400);
    fx.many(true);r=await connect(fx,bridge,'facebook');assert.equal(r.status,409);
    assert.equal((await fx.db.query('select count(*)::int n from public.vimax_social_connections')).rows[0].n,0);
    const disabled=createBridge({env:{...keys,VIMAX_TIKTOK_CLIENT_SECRET:'',VIMAX_FACEBOOK_APP_SECRET:''},fetchImpl:fx.fetchImpl});
    const status=await (await disabled.fetch(request('/api/cloud/social/status'))).json();assert.equal(status.providers.tiktok.configured,false);assert.equal(status.providers.facebook.configured,false);
    r=await disabled.fetch(request('/api/cloud/social/tiktok/start',{method:'POST',json:{}}));assert.equal(r.status,503);
    await assert.rejects(fx.as(owner,()=>fx.db.query("select public.vimax_social_connection_save('facebook',$1::jsonb)",[JSON.stringify([{external_id:'123',display_name:'bad',credential_cipher:'plaintext-secret'}])])),/Invalid social connection/);
  }finally{await fx.db.close();}
});
