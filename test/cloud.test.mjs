import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createBridge} from '../api/bridge.mjs';

const env = {SUPABASE_URL:'https://example.supabase.co', SUPABASE_PUBLISHABLE_KEY:'sb_publishable_for_test_only'};
const userIds = {alice:'1a2b3c4d-0000-4000-8000-000000000001', bob:'1a2b3c4d-0000-4000-8000-000000000002'};
const idFor = n => `12345678-0000-4000-8000-${String(n).padStart(12,'0')}`;
function fakeSupabase() {
  const projects = []; let next = 1; const calls = [];
  const fetch = async (url, init) => {
    const u = new URL(url), payload = init.body ? JSON.parse(init.body) : null;
    calls.push({path:u.pathname, method:init.method, token:init.headers.authorization});
    const token = init.headers.authorization?.replace('Bearer ', '');
    const who = token === 'alice-token' ? 'alice' : token === 'bob-token' ? 'bob' : null;
    if (u.pathname === '/auth/v1/health') return Response.json({status:'ok'});
    if (u.pathname === '/rest/v1/rpc/vimax_cloud_health') return Response.json(true);
    if (u.pathname === '/auth/v1/signup') return Response.json({id:'fake'});
    if (u.pathname === '/auth/v1/token' && u.searchParams.get('grant_type') === 'password') {
      const name = payload.email.split('@')[0];
      if (!userIds[name] || payload.password !== 'example-password') return Response.json({error:'bad auth'}, {status:400});
      return Response.json({access_token:`${name}-token`,refresh_token:`${name}-refresh`,expires_in:3600});
    }
    if (u.pathname === '/auth/v1/token' && u.searchParams.get('grant_type') === 'refresh_token') {
      const name = payload.refresh_token?.replace('-refresh', '');
      return userIds[name] ? Response.json({access_token:`${name}-token`,refresh_token:`${name}-refresh`,expires_in:3600}) : Response.json({}, {status:401});
    }
    if (u.pathname === '/auth/v1/user') return who ? Response.json({id:userIds[who],email:`${who}@example.test`}) : Response.json({}, {status:401});
    if (u.pathname === '/auth/v1/logout') return new Response(null, {status:204});
    if (u.pathname === '/rest/v1/vimax_projects' && who) {
      if (init.method === 'POST') { const project = {id:idFor(next++), title:payload.title, notes:payload.notes, owner:who}; projects.push(project); return Response.json([project], {status:201}); }
      if (init.method === 'GET') return Response.json(projects.filter(p => p.owner === who));
      if (init.method === 'DELETE') { const id = u.searchParams.get('id')?.replace('eq.', ''); const pos = projects.findIndex(p => p.id === id && p.owner === who); if (pos >= 0) projects.splice(pos,1); return new Response(null, {status:204}); }
    }
    return Response.json({error:'unexpected'}, {status:404});
  };
  return {fetch,calls};
}
function request(path, {method='GET', cookie='', origin='https://vimax.example', payload, contentType='application/json', extra={}} = {}) {
  return new Request(`https://vimax.example${path}`, {method, headers:{...(cookie ? {cookie} : {}), ...(origin ? {origin} : {}),
    ...(payload === undefined ? {} : {'content-type':contentType}), ...extra}, ...(payload === undefined ? {} : {body:JSON.stringify(payload)})});
}
async function login(bridge, user) {
  const response = await bridge.fetch(request('/api/cloud/login', {method:'POST', payload:{email:`${user}@example.test`,password:'example-password'}}));
  assert.equal(response.status, 200);
  const values = response.headers.getSetCookie();
  assert.equal(values.length, 2);
  assert.ok(values.every(c => c.includes('HttpOnly') && c.includes('Secure') && c.includes('SameSite=Lax') && c.includes('Path=/')));
  return values.map(value => value.split(';')[0]).join('; ');
}

test('health truthfully distinguishes connected database from missing agent and upload', async () => {
  const fake = fakeSupabase(); const bridge = createBridge({env,fetchImpl:fake.fetch});
  const health = await bridge.fetch(request('/api/health'));
  assert.deepEqual(await health.json(), {ok:true,database:'connected',text_chat:'unconfigured',video_agent:'unavailable',youtube_upload:'unavailable'});
  const sessions = await (await bridge.fetch(request('/api/bridge?__vimax_path=sessions'))).json();
  assert.deepEqual(sessions.sessions, []); assert.match(sessions.warning, /not connected/);
  const system = await (await bridge.fetch(request('/api/skills/system'))).json();
  assert.equal(system.database_connected, true); assert.equal(system.ready_for_video, false); assert.equal(system.scene_detection_installed, false);
  assert.ok(fake.calls.every(call => !call.path.includes('service_role')));
});

test('CSRF, oversized bodies, malformed input and missing sessions fail closed', async () => {
  const fake = fakeSupabase(); const bridge = createBridge({env,fetchImpl:fake.fetch});
  assert.equal((await bridge.fetch(request('/api/cloud/login', {method:'POST',origin:'https://evil.example',payload:{}}))).status,403);
  assert.equal((await bridge.fetch(request('/api/cloud/login', {method:'POST',origin:'',payload:{}}))).status,403);
  assert.equal((await bridge.fetch(request('/api/cloud/login', {method:'POST',payload:{email:'x'.repeat(9000),password:'123456'}}))).status,413);
  assert.equal((await bridge.fetch(request('/api/cloud/login', {method:'POST',payload:{email:'bad',password:'123456'}}))).status,422);
  assert.equal((await bridge.fetch(request('/api/cloud/projects'))).status,401);
  assert.equal((await bridge.fetch(request('/api/bridge?__vimax_path=../secret'))).status,400);
  assert.equal(fake.calls.length,0);
});

test('login cookies are HTTP-only, CRUD is scoped by user JWT, logout clears tokens', async () => {
  const fake = fakeSupabase(); const bridge = createBridge({env,fetchImpl:fake.fetch});
  const alice = await login(bridge,'alice'), bob = await login(bridge,'bob');
  const session = await (await bridge.fetch(request('/api/cloud/session',{cookie:alice}))).json();
  assert.equal(session.user.email,'alice@example.test');
  assert.equal(JSON.stringify(session).includes('alice-token'),false);
  let response = await bridge.fetch(request('/api/cloud/projects',{method:'POST',cookie:alice,payload:{title:'My private idea',notes:'private notes',owner_id:userIds.bob}}));
  assert.equal(response.status,201); const created = (await response.json()).project;
  response = await bridge.fetch(request('/api/cloud/projects',{cookie:bob}));
  assert.deepEqual((await response.json()).projects,[]);
  // Even when Bob knows the UUID, RLS at the provider removes only his rows.
  await bridge.fetch(request(`/api/cloud/projects/${created.id}`,{method:'DELETE',cookie:bob}));
  assert.equal((await (await bridge.fetch(request('/api/cloud/projects',{cookie:alice}))).json()).projects.length,1);
  await bridge.fetch(request(`/api/cloud/projects/${created.id}`,{method:'DELETE',cookie:alice}));
  assert.equal((await (await bridge.fetch(request('/api/cloud/projects',{cookie:alice}))).json()).projects.length,0);
  const logout = await bridge.fetch(request('/api/cloud/logout',{method:'POST',cookie:alice,payload:{}}));
  assert.ok(logout.headers.getSetCookie().every(value => value.includes('Max-Age=0')));
});

test('refresh uses the HTTP-only cookie and rejects forged or duplicate cookies', async () => {
  const fake = fakeSupabase(); const bridge = createBridge({env,fetchImpl:fake.fetch});
  const expired = '__Host-vimax_access=expired; __Host-vimax_refresh=alice-refresh';
  const response = await bridge.fetch(request('/api/cloud/session',{cookie:expired}));
  assert.equal((await response.json()).user.email,'alice@example.test');
  assert.equal(response.headers.getSetCookie().length,2);
  const duplicate = `${expired}; __Host-vimax_refresh=bob-refresh`;
  assert.equal((await (await bridge.fetch(request('/api/cloud/session',{cookie:duplicate}))).json()).user,null);
});

test('misconfigured upstream or unavailable Supabase does not claim a backend is ready', async () => {
  const invalid = createBridge({env:{...env, SUPABASE_URL:'https://evil.example'},fetchImpl:async () => { throw new Error('should not reach'); }});
  assert.equal((await invalid.fetch(request('/api/health'))).status,503);
  const down = createBridge({env,fetchImpl:async () => { throw new Error('network'); }});
  const res = await down.fetch(request('/api/health')); assert.equal(res.status,503);
  assert.match((await res.json()).error,/unreachable/);
});
