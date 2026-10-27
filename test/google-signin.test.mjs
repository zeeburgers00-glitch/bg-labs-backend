import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {createBridge} from '../api/bridge.mjs';

// These tests simulate Supabase Auth. They do not complete real Google consent
// or prove provider configuration, account linking, or hosted login.
const env = {SUPABASE_URL:'https://fake.supabase.co', SUPABASE_PUBLISHABLE_KEY:'sb_publishable_test',
  VIMAX_GOOGLE_SIGNIN_ENABLED:'true', VIMAX_GOOGLE_SIGNIN_REDIRECT_URI:'https://vimax.example/api/cloud/google/callback'};
const code = 'aaaaaaaa-0000-4000-8000-000000000001';
const owner = 'bbbbbbbb-0000-4000-8000-000000000002';
const pkceName = '__Host-vimax_google_pkce';
function fakeAuth({provider=true} = {}) {
  const state={provider,expectedChallenge:'', calls:[], networkDown:false};
  async function fetch(url, init={}) {
    const parsed = new URL(url), payload = init.body ? JSON.parse(init.body) : null;
    state.calls.push({path:parsed.pathname, query:parsed.searchParams, payload, authorization:init.headers?.authorization});
    if (state.networkDown) throw new Error('network failed');
    if (parsed.pathname === '/auth/v1/settings') return Response.json({external:{google:state.provider}});
    if (parsed.pathname === '/auth/v1/user') {
      return init.headers?.authorization === 'Bearer alice-token'
        ? Response.json({id:owner,email:'alice@example.test'}) : Response.json({}, {status:401});
    }
    if (parsed.pathname === '/auth/v1/token' && parsed.searchParams.get('grant_type') === 'pkce') {
      const challenge = createHash('sha256').update(payload.code_verifier || '').digest('base64url');
      if (payload.auth_code !== code || challenge !== state.expectedChallenge) return Response.json({}, {status:400});
      return Response.json({access_token:'alice-token',refresh_token:'alice-refresh',expires_in:3600,
        provider_token:'google-provider-token-must-not-be-returned',provider_refresh_token:'google-refresh-token-must-not-be-returned'});
    }
    if (parsed.pathname === '/auth/v1/logout') return new Response(null,{status:204});
    throw new Error(`Unexpected mock route: ${parsed.pathname}`);
  }
  return {state,fetch};
}
function request(path,{method='GET',origin='https://vimax.example',cookie='',payload,extra={}}={}) {
  return new Request(`https://vimax.example${path}`,{method,headers:{...(origin?{origin}:{}),...(cookie?{cookie}:{}),
    ...(payload === undefined ? {} : {'content-type':'application/json'}),...extra},
    ...(payload === undefined ? {} : {body:JSON.stringify(payload)})});
}
function cookiePair(response,name) {
  const found=response.headers.getSetCookie().find(value=>value.startsWith(`${name}=`));
  return found?.split(';')[0] || '';
}
async function start(bridge, auth) {
  const response=await bridge.fetch(request('/api/cloud/google/start',{method:'POST',payload:{}}));
  assert.equal(response.status,200);
  const authUrl=new URL((await response.json()).authorization_url);
  auth.state.expectedChallenge=authUrl.searchParams.get('code_challenge');
  return {response, authUrl, verifierCookie:cookiePair(response,pkceName)};
}

test('Google app sign-in is opt-in, provider-gated and same-origin', async()=>{
  const auth=fakeAuth(), disabled=createBridge({env:{...env,VIMAX_GOOGLE_SIGNIN_ENABLED:'false'},fetchImpl:auth.fetch});
  assert.deepEqual(await (await disabled.fetch(request('/api/cloud/google/status'))).json(),{enabled:false});
  assert.equal((await disabled.fetch(request('/api/cloud/google/start',{method:'POST',payload:{}}))).status,503);
  assert.equal(auth.state.calls.length,0);
  const notEnabled=fakeAuth({provider:false}),bridge=createBridge({env,fetchImpl:notEnabled.fetch});
  assert.deepEqual(await (await bridge.fetch(request('/api/cloud/google/status'))).json(),{enabled:false});
  const denied=await bridge.fetch(request('/api/cloud/google/start',{method:'POST',payload:{}}));
  assert.equal(denied.status,503);assert.equal(denied.headers.getSetCookie().length,0);
  const before=notEnabled.state.calls.length;
  assert.equal((await bridge.fetch(request('/api/cloud/google/start',{method:'POST',origin:'https://evil.example',payload:{}}))).status,403);
  assert.equal((await bridge.fetch(request('/api/cloud/google/start',{method:'POST',origin:'',payload:{}}))).status,403);
  assert.equal(notEnabled.state.calls.length,before);
  const badRedirect=createBridge({env:{...env,VIMAX_GOOGLE_SIGNIN_REDIRECT_URI:'https://evil.example/api/cloud/google/callback'},fetchImpl:notEnabled.fetch});
  assert.deepEqual(await (await badRedirect.fetch(request('/api/cloud/google/status'))).json(),{enabled:false});
});

test('PKCE Google login uses server-only cookies and a one-use Supabase code', async()=>{
  const auth=fakeAuth(),bridge=createBridge({env,fetchImpl:auth.fetch});
  assert.deepEqual(await (await bridge.fetch(request('/api/cloud/google/status'))).json(),{enabled:true});
  const {response,authUrl,verifierCookie}=await start(bridge,auth);
  assert.equal(authUrl.origin,'https://fake.supabase.co');assert.equal(authUrl.pathname,'/auth/v1/authorize');
  assert.equal(authUrl.searchParams.get('provider'),'google');assert.equal(authUrl.searchParams.get('scopes'),'openid');
  assert.equal(authUrl.searchParams.get('redirect_to'),env.VIMAX_GOOGLE_SIGNIN_REDIRECT_URI);
  assert.equal(authUrl.searchParams.get('code_challenge_method'),'s256');
  const verifier=verifierCookie.split('=')[1];assert.match(verifier,/^[A-Za-z0-9_-]{43}$/);
  assert.equal(authUrl.searchParams.get('code_challenge'),createHash('sha256').update(verifier).digest('base64url'));
  assert.ok(response.headers.getSetCookie().every(item=>item.includes('HttpOnly')&&item.includes('Secure')&&item.includes('SameSite=Lax')&&item.includes('Max-Age=600')));
  assert.ok(!authUrl.href.includes(verifier));
  const callback=await bridge.fetch(request(`/api/cloud/google/callback?code=${code}`,{cookie:verifierCookie}));
  assert.equal(callback.status,303);assert.equal(callback.headers.get('location'),'/skills/?google_signin=success');
  assert.equal(callback.headers.get('referrer-policy'),'no-referrer');assert.equal(callback.headers.get('cache-control'),'no-store');
  const set=callback.headers.getSetCookie();
  assert.ok(set.some(value=>value.startsWith(`${pkceName}=`)&&value.includes('Max-Age=0')));
  assert.ok(set.some(value=>value.startsWith('__Host-vimax_access=alice-token;')&&value.includes('HttpOnly')));
  assert.ok(set.some(value=>value.startsWith('__Host-vimax_refresh=alice-refresh;')&&value.includes('HttpOnly')));
  assert.ok(set.some(value=>value.startsWith('__Host-vimax_yt_access=')&&value.includes('Max-Age=0')));
  assert.ok(!JSON.stringify(set).includes('google-provider-token'));
  assert.equal(await callback.text(),'');
  const exchange=auth.state.calls.find(call=>call.query.get('grant_type')==='pkce');
  assert.deepEqual(exchange.payload,{auth_code:code,code_verifier:verifier});
});

test('callback rejects missing or duplicate codes and verifiers, stale PKCE, and in-flight account switches',async()=>{
  const auth=fakeAuth(),bridge=createBridge({env,fetchImpl:auth.fetch});
  const {verifierCookie}=await start(bridge,auth);
  const exchangeCount=()=>auth.state.calls.filter(call=>call.query.get('grant_type')==='pkce').length;
  for (const [path,cookies] of [
    [`/api/cloud/google/callback?code=${code}`,''],
    [`/api/cloud/google/callback?code=${code}&code=${code}`,verifierCookie],
    ['/api/cloud/google/callback?error=access_denied',verifierCookie],
    [`/api/cloud/google/callback?code=${code}`,`${verifierCookie}; ${verifierCookie}`],
    [`/api/cloud/google/callback?code=${code}`,`${pkceName}=bad`],
  ]) {
    const response=await bridge.fetch(request(path,{cookie:cookies}));
    assert.equal(response.status,303);assert.equal(response.headers.get('location'),'/skills/?google_signin=failed');
    assert.ok(response.headers.getSetCookie().some(item=>item.startsWith(`${pkceName}=`)&&item.includes('Max-Age=0')));
  }
  assert.equal(exchangeCount(),0);
  const stale=await bridge.fetch(request(`/api/cloud/google/callback?code=${code}`,{cookie:`${pkceName}=${'A'.repeat(43)}`}));
  assert.equal(stale.headers.get('location'),'/skills/?google_signin=failed');
  assert.equal(exchangeCount(),1);
  const switched=await bridge.fetch(request(`/api/cloud/google/callback?code=${code}`,{cookie:`${verifierCookie}; __Host-vimax_access=alice-token`}));
  assert.equal(switched.headers.get('location'),'/skills/?google_signin=failed');
  assert.equal(exchangeCount(),1,'a different active session must not be overwritten');
  assert.ok(!switched.headers.getSetCookie().some(item=>item.startsWith('__Host-vimax_access=')));
  const beginWhileSignedIn=await bridge.fetch(request('/api/cloud/google/start',{method:'POST',cookie:'__Host-vimax_access=alice-token',payload:{}}));
  assert.equal(beginWhileSignedIn.status,409);
  const logout=await bridge.fetch(request('/api/cloud/logout',{method:'POST',cookie:'__Host-vimax_access=alice-token',payload:{}}));
  assert.ok(logout.headers.getSetCookie().some(item=>item.startsWith(`${pkceName}=`)&&item.includes('Max-Age=0')));
});

test('network or provider failures do not return raw tokens or callback JSON to the browser',async()=>{
  const auth=fakeAuth(),bridge=createBridge({env,fetchImpl:auth.fetch});
  const {verifierCookie}=await start(bridge,auth);auth.state.networkDown=true;
  const response=await bridge.fetch(request(`/api/cloud/google/callback?code=${code}`,{cookie:verifierCookie}));
  assert.equal(response.status,303);assert.equal(response.headers.get('location'),'/skills/?google_signin=failed');
  assert.equal(await response.text(),'');assert.ok(response.headers.getSetCookie().every(item=>!item.includes('alice-token')));
  assert.equal((await bridge.fetch(request('/api/cloud/google/status'))).status,503);
});
