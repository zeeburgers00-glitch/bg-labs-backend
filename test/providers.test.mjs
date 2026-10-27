import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createBridge} from '../api/bridge.mjs';
import {chatCompletion, providerStatus, searchPexels, validateSelection} from '../api/providers.mjs';

const baseEnv = {SUPABASE_URL:'https://example.supabase.co', SUPABASE_PUBLISHABLE_KEY:'sb_publishable_test'};
const testEnv = {...baseEnv, GROQ_API_KEY:'test-only-groq', MISTRAL_API_KEY:'test-only-mistral', PEXELS_API_KEY:'test-only-pexels', VIMAX_AI_ALLOW_ALL_AUTHENTICATED:'true'};
const users = {alice:'aaaaaaaa-0000-4000-8000-000000000001', bob:'bbbbbbbb-0000-4000-8000-000000000002'};
const id = n => `12345678-0000-4000-8000-${String(n).padStart(12, '0')}`;
const cookie = name => `__Host-vimax_access=${name}-token`;
function req(path, {method='GET', user='alice', origin='https://app.example', body} = {}) {
  return new Request(`https://app.example${path}`, {method, headers:{...(user ? {cookie:cookie(user)} : {}), ...(origin ? {origin} : {}), ...(body === undefined ? {} : {'content-type':'application/json'})},
    ...(body === undefined ? {} : {body:JSON.stringify(body)})});
}
function mockBackend({provider, denyReservation=false, finishAvailable=true} = {}) {
  const calls = [], external = [], turns = [], usage = [], paused = new Map(); let next = 1;
  const fetchImpl = async (url, init) => {
    const target = new URL(url), payload = init.body ? JSON.parse(init.body) : null;
    if (target.hostname !== 'example.supabase.co') {
      external.push({url:target.href, init, payload});
      if (provider) return provider(target, init, payload);
      return Response.json({choices:[{message:{content:'A useful draft.'}}], usage:{prompt_tokens:33, completion_tokens:12}});
    }
    const who = init.headers.authorization?.replace('Bearer ', '').replace('-token', '');
    calls.push({path:target.pathname, method:init.method, who, payload});
    if (target.pathname === '/auth/v1/user') return users[who] ? Response.json({id:users[who], email:`${who}@example.test`}) : Response.json({}, {status:401});
    if (target.pathname === '/auth/v1/health') return Response.json({status:'ok'});
    if (target.pathname === '/rest/v1/rpc/vimax_cloud_health') return Response.json(true);
    if (target.pathname === '/rest/v1/vimax_ai_preferences' && users[who]) return Response.json(paused.has(who) ? [{paused:paused.get(who)}] : []);
    if (target.pathname === '/rest/v1/rpc/vimax_set_ai_paused' && users[who]) { paused.set(who, payload.p_paused); return Response.json(payload.p_paused); }
    if (target.pathname === '/rest/v1/rpc/vimax_reserve_ai_call' && users[who]) {
      if (paused.get(who)) return Response.json({allowed:false, reason:'paused'});
      if (denyReservation) return Response.json({allowed:false, reason:'user_daily_limit'});
      const entry = {id:id(next++), secret:id(next++), owner:who, feature:payload.p_feature, provider:payload.p_provider, model:payload.p_model, status:'reserved'};
      usage.push(entry); return Response.json({allowed:true, id:entry.id, finish_secret:entry.secret, remaining_user:9 - usage.filter(x => x.owner === who).length + 1});
    }
    if (target.pathname === '/rest/v1/rpc/vimax_finish_ai_call' && users[who]) {
      if (!finishAvailable) return Response.json({}, {status:503});
      const entry = usage.find(x => x.id === payload.p_id && x.secret === payload.p_secret && x.owner === who && x.status === 'reserved');
      if (!entry) return Response.json(false);
      Object.assign(entry, {status:payload.p_status, input_tokens:payload.p_input_tokens, output_tokens:payload.p_output_tokens});
      return Response.json(true);
    }
    if (target.pathname === '/rest/v1/vimax_chat_turns' && users[who]) {
      if (init.method === 'GET') return Response.json(turns.filter(x => x.owner === who).slice().reverse().slice(0, Number(target.searchParams.get('limit')) || 30));
      if (init.method === 'POST') { turns.push({...payload, id:id(next++), owner:who}); return new Response(null, {status:201}); }
      if (init.method === 'DELETE') { for (let n=turns.length-1; n>=0; n--) if (turns[n].owner === who) turns.splice(n,1); return new Response(null, {status:204}); }
    }
    if (target.pathname === '/rest/v1/vimax_ai_calls' && users[who]) return Response.json(usage.filter(x => x.owner === who).map(({secret, owner, ...visible}) => visible));
    return Response.json({error:'unexpected request'}, {status:404});
  };
  return {fetchImpl, calls, external, turns, usage};
}
const input = {provider:'groq', model:'llama-3.1-8b-instant', prompt:'Plan a short original video.', mode:'ideas'};

test('fixed-host chat adapters use server-only credentials and enforce model allowlists', async () => {
  const cases = [
    ['groq','GROQ_API_KEY','llama-3.1-8b-instant','https://api.groq.com/openai/v1/chat/completions'],
    ['gemini','GEMINI_API_KEY','gemini-2.5-flash','https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'],
    ['mistral','MISTRAL_API_KEY','mistral-small-latest','https://api.mistral.ai/v1/chat/completions'],
    ['zai','ZAI_API_KEY','glm-4.5-flash','https://api.z.ai/api/paas/v4/chat/completions'],
    ['openrouter','OPENROUTER_API_KEY','openrouter/free','https://openrouter.ai/api/v1/chat/completions'],
    ['huggingface','HF_TOKEN','openai/gpt-oss-120b:groq','https://router.huggingface.co/v1/chat/completions'],
    ['opencode','OPENCODE_API_KEY','glm-5.3-flash','https://opencode.ai/inference/openai/v1/chat/completions'],
  ];
  for (const [provider, keyName, model, url] of cases) {
    const env = {[keyName]:'test-only-key', ...(provider === 'opencode' ? {OPENCODE_MODELS:model} : {})};
    let captured;
    const result = await chatCompletion({env, id:provider, model, messages:[{role:'user', content:'Hi'}], fetchImpl:async (target, init) => {
      captured = {target, init}; return Response.json({choices:[{message:{content:'Hello'}}], usage:{prompt_tokens:1, completion_tokens:2}});
    }});
    assert.equal(captured.target,url); assert.equal(captured.init.headers.authorization,'Bearer test-only-key');
    assert.equal(captured.init.redirect,'error'); assert.equal(JSON.parse(captured.init.body).max_tokens,600);
    assert.deepEqual(result,{text:'Hello', inputTokens:1, outputTokens:2});
    assert.equal(JSON.stringify(providerStatus(env)).includes('test-only-key'),false);
    assert.throws(() => validateSelection(env,provider,'arbitrary-expensive-model'), /allowed/);
  }
  assert.equal(providerStatus({OPENCODE_API_KEY:'test-only-key'}).find(p => p.id === 'opencode').state,'model_required');
  assert.equal(providerStatus({OPENCODE_API_KEY:'test-only-key',OPENCODE_MODELS:'gpt-5'}).find(p => p.id === 'opencode').state,'invalid_configuration');
  assert.throws(() => validateSelection({GROQ_API_KEY:'key with spaces'},'groq','llama-3.1-8b-instant'), /not configured/);
});

test('provider failures are sanitized, response size is bounded and timeouts do not request a retry', async () => {
  const options = {env:testEnv, id:'groq', model:'llama-3.1-8b-instant', messages:[]};
  await assert.rejects(chatCompletion({...options, fetchImpl:async () => Response.json({error:'test-only-groq'}, {status:401})}), error => error.status === 502 && error.retryable && !error.message.includes('test-only-groq'));
  await assert.rejects(chatCompletion({...options, fetchImpl:async () => {throw new Error('test-only-groq');}}), error => error.status === 504 && !error.retryable && !error.message.includes('test-only-groq'));
  await assert.rejects(chatCompletion({...options, fetchImpl:async () => new Response('x'.repeat(270_000))}), /too large/);
  await assert.rejects(chatCompletion({...options, fetchImpl:async () => new Response('not json')}), /invalid JSON/);
});

test('cloud text planning requires auth and budget; chat and usage remain user scoped', async () => {
  const fake = mockBackend(), bridge = createBridge({env:testEnv, fetchImpl:fake.fetchImpl});
  assert.equal((await bridge.fetch(req('/api/cloud/providers',{user:null}))).status,401);
  assert.equal((await bridge.fetch(req('/api/cloud/chat',{method:'POST',origin:'https://evil.example',body:input}))).status,403);
  const status = await (await bridge.fetch(req('/api/cloud/providers'))).json();
  assert.equal(status.providers.find(p => p.id === 'groq').state,'configured_unverified');
  assert.equal(JSON.stringify(status).includes('test-only-groq'),false);
  const first = await bridge.fetch(req('/api/cloud/chat',{method:'POST',body:{...input,owner_id:users.bob}}));
  assert.equal(first.status,200); const result = await first.json();
  assert.equal(result.reply,'A useful draft.'); assert.equal(result.history_saved,true); assert.equal(result.audit_saved,true);
  assert.deepEqual(result.usage,{input_tokens:33,output_tokens:12});
  assert.equal(JSON.stringify(result).includes('test-only-groq'),false);
  assert.equal(JSON.stringify(result).includes(fake.usage[0].secret),false);
  const ownUsage = await (await bridge.fetch(req('/api/cloud/usage'))).json();
  assert.equal(JSON.stringify(ownUsage).includes(fake.usage[0].secret),false);
  assert.equal(fake.external.length,1); assert.match(fake.external[0].payload.messages[0].content,/cannot browse/);
  const second = await bridge.fetch(req('/api/cloud/chat',{method:'POST',body:{...input,prompt:'Follow up'}})); assert.equal(second.status,200);
  assert.equal(fake.external[1].payload.messages.at(-2).content,'A useful draft.');
  assert.equal((await (await bridge.fetch(req('/api/cloud/chat/history',{user:'bob'}))).json()).turns.length,0);
  assert.equal((await (await bridge.fetch(req('/api/cloud/usage',{user:'bob'}))).json()).calls.length,0);
  await bridge.fetch(req('/api/cloud/chat/history',{method:'DELETE',user:'bob'}));
  assert.equal((await (await bridge.fetch(req('/api/cloud/chat/history'))).json()).turns.length,2);
  await bridge.fetch(req('/api/cloud/chat/history',{method:'DELETE'}));
  assert.equal((await (await bridge.fetch(req('/api/cloud/chat/history'))).json()).turns.length,0);
  const blocked = await bridge.fetch(req('/api/cloud/chat',{method:'POST',body:{...input,model:'expensive-model'}}));
  assert.equal(blocked.status,422); assert.equal(fake.external.length,2);
  const quota = mockBackend({denyReservation:true}), limited = createBridge({env:testEnv,fetchImpl:quota.fetchImpl});
  const response = await limited.fetch(req('/api/cloud/chat',{method:'POST',body:input}));
  assert.equal(response.status,429); assert.equal(quota.external.length,0);
});

test('shared-project users are denied by default; owner allowlist and per-user pause gate calls', async () => {
  const fake = mockBackend();
  const deniedEnv = {...testEnv, VIMAX_AI_ALLOW_ALL_AUTHENTICATED:'false'};
  const denied = createBridge({env:deniedEnv,fetchImpl:fake.fetchImpl});
  assert.equal((await (await denied.fetch(req('/api/cloud/providers'))).json()).allowed,false);
  assert.equal((await denied.fetch(req('/api/cloud/chat',{method:'POST',body:input}))).status,403);
  assert.equal(fake.external.length,0);
  const bridge = createBridge({env:{...deniedEnv,VIMAX_AI_ALLOWED_USER_IDS:users.alice},fetchImpl:fake.fetchImpl});
  assert.equal((await (await bridge.fetch(req('/api/cloud/providers'))).json()).allowed,true);
  assert.equal((await bridge.fetch(req('/api/cloud/chat',{method:'POST',user:'bob',body:input}))).status,403);
  const pause = await bridge.fetch(req('/api/cloud/ai/pause',{method:'POST',body:{paused:true}})); assert.equal(pause.status,200);
  assert.equal((await (await bridge.fetch(req('/api/cloud/providers'))).json()).paused,true);
  assert.equal((await bridge.fetch(req('/api/cloud/chat',{method:'POST',body:input}))).status,409);
  assert.equal(fake.external.length,0);
  assert.equal((await bridge.fetch(req('/api/cloud/ai/pause',{method:'POST',body:{paused:false}}))).status,200);
  assert.equal((await bridge.fetch(req('/api/cloud/chat',{method:'POST',body:input}))).status,200);
  assert.equal(fake.external.length,1);
});

test('fallback is explicit, separately budgeted and never attempted after ambiguous timeout or missing audit', async () => {
  const fallback = {provider:'mistral',model:'mistral-small-latest'};
  const responder = async target => target.hostname === 'api.groq.com' ? Response.json({error:'private'}, {status:429}) : Response.json({choices:[{message:{content:'Fallback draft.'}}]});
  const fake = mockBackend({provider:responder}), bridge = createBridge({env:testEnv,fetchImpl:fake.fetchImpl});
  const response = await bridge.fetch(req('/api/cloud/chat',{method:'POST',body:{...input,fallback}}));
  const result = await response.json(); assert.equal(response.status,200); assert.equal(result.used_fallback,true); assert.equal(result.provider,'mistral');
  assert.equal(fake.external.length,2); assert.deepEqual(fake.usage.map(x => x.status),['failed','succeeded']);
  const timed = mockBackend({provider:async () => {throw new Error('sensitive network detail');}});
  const timeout = await createBridge({env:testEnv,fetchImpl:timed.fetchImpl}).fetch(req('/api/cloud/chat',{method:'POST',body:{...input,fallback}}));
  assert.equal(timeout.status,504); assert.equal(timed.external.length,1); assert.equal((await timeout.json()).error.includes('sensitive'),false);
  const noAudit = mockBackend({provider:responder,finishAvailable:false});
  const stopped = await createBridge({env:testEnv,fetchImpl:noAudit.fetchImpl}).fetch(req('/api/cloud/chat',{method:'POST',body:{...input,fallback}}));
  assert.equal(stopped.status,429); assert.equal(noAudit.external.length,1);
});

test('provider health test is a real metered call; Pexels uses fixed host and filters unsafe links', async () => {
  const fake = mockBackend({provider:async target => target.hostname === 'api.pexels.com'
    ? Response.json({videos:[{id:12,url:'https://www.pexels.com/video/example-12/',duration:8,width:1920,height:1080,user:{name:'Creator'}},{id:13,url:'https://evil.example/tracker',user:{name:'Bad'}}]})
    : Response.json({choices:[{message:{content:'OK'}}]})});
  const bridge = createBridge({env:testEnv,fetchImpl:fake.fetchImpl});
  const health = await bridge.fetch(req('/api/cloud/providers/test',{method:'POST',body:{provider:'groq',model:input.model}}));
  assert.equal(health.status,200); assert.equal(fake.external[0].payload.max_tokens,16); assert.equal(fake.usage[0].feature,'provider_test');
  const search = await bridge.fetch(req('/api/cloud/stock-search',{method:'POST',body:{query:'beach & waves',orientation:'landscape'}}));
  const result = await search.json(); assert.equal(search.status,200); assert.equal(result.videos.length,1); assert.equal(result.videos[0].creator,'Creator');
  const url = new URL(fake.external[1].url); assert.equal(url.hostname,'api.pexels.com'); assert.equal(url.pathname,'/v1/videos/search');
  assert.equal(url.searchParams.get('query'),'beach & waves'); assert.equal(fake.external[1].init.headers.authorization,'test-only-pexels');
  assert.equal(JSON.stringify(result).includes('test-only-pexels'),false); assert.equal(fake.usage[1].feature,'stock_search');
  await assert.rejects(searchPexels({env:{},fetchImpl:fake.fetchImpl,query:'x'}), /not configured/);
});
