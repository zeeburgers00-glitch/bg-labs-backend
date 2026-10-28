import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createBridge} from '../api/bridge.mjs';
import {chatCompletion, providerStatus, providerTestTokens, searchPexels, validateSelection} from '../api/providers.mjs';

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
const input = {provider:'groq', model:'qwen/qwen3.8-27b', prompt:'Plan a short original video.', mode:'ideas'};

test('fixed-host chat adapters use server-only credentials and enforce model allowlists', async () => {
  const cases = [
    ['openai','OPENAI_API_KEY','gpt-5.4-mini','https://api.openai.com/v1/chat/completions'],
    ['groq','GROQ_API_KEY','qwen/qwen3.8-27b','https://api.groq.com/openai/v1/chat/completions'],
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
    assert.equal(captured.init.redirect,'error'); assert.equal(JSON.parse(captured.init.body)[provider === 'openai' ? 'max_completion_tokens' : 'max_tokens'],600);
    assert.deepEqual(result,{text:'Hello', truncated:false, inputTokens:1, outputTokens:2});
    assert.equal(JSON.stringify(providerStatus(env)).includes('test-only-key'),false);
    assert.throws(() => validateSelection(env,provider,'arbitrary-expensive-model'), /allowed/);
  }
  assert.equal(providerStatus({OPENCODE_API_KEY:'test-only-key'}).find(p => p.id === 'opencode').state,'model_required');
  assert.equal(providerStatus({OPENCODE_API_KEY:'test-only-key',OPENCODE_MODELS:'gpt-5'}).find(p => p.id === 'opencode').state,'invalid_configuration');
  assert.throws(() => validateSelection({GROQ_API_KEY:'key with spaces'},'groq','qwen/qwen3.8-27b'), /not configured/);
});

test('current defaults avoid retired Groq models and keep explicit owner overrides', () => {
  const initial = providerStatus({GROQ_API_KEY:'test-only-key'}).find(provider => provider.id === 'groq');
  assert.deepEqual(initial.models, ['openai/gpt-oss-120b','openai/gpt-oss-20b','qwen/qwen3.8-27b']);
  const override = providerStatus({GROQ_API_KEY:'test-only-key', GROQ_MODELS:'openai/gpt-oss-20b'}).find(provider => provider.id === 'groq');
  assert.deepEqual(override.models, ['openai/gpt-oss-20b']);
  const zai = providerStatus({ZAI_API_KEY:'test-only-key'}).find(provider => provider.id === 'zai');
  assert.deepEqual(zai.models, ['glm-4.7-flash','glm-4.5-flash']);
});

test('Gemini prefers current Flash while preserving owner-selected model overrides', () => {
  const initial = providerStatus({GEMINI_API_KEY:'test-only-key'}).find(provider => provider.id === 'gemini');
  assert.equal(initial.state, 'configured_unverified');
  assert.deepEqual(initial.models, ['gemini-3.8-flash','gemini-2.5-flash','gemini-4-argon']);
  const override = providerStatus({GEMINI_API_KEY:'test-only-key', GEMINI_MODELS:'gemini-2.5-flash'}).find(provider => provider.id === 'gemini');
  assert.deepEqual(override.models, ['gemini-2.5-flash']);
  assert.equal(JSON.stringify(initial).includes('test-only-key'), false);
});

test('stronger documented models use bounded, provider-specific reasoning parameters', async () => {
  for (const [id,keyName,model,expected] of [
    ['groq','GROQ_API_KEY','openai/gpt-oss-120b',{reasoning_effort:'low',include_reasoning:false}],
    ['groq','GROQ_API_KEY','openai/gpt-oss-20b',{reasoning_effort:'low',include_reasoning:false}],
    ['groq','GROQ_API_KEY','qwen/qwen3.8-27b',{reasoning_effort:'none'}],
    ['gemini','GEMINI_API_KEY','gemini-3.8-flash',{reasoning_effort:'low'}],
    ['gemini','GEMINI_API_KEY','gemini-4-argon',{reasoning_effort:'low'}],
  ]) {
    let request;
    await chatCompletion({env:{[keyName]:'test-only-key'},id,model,messages:[],fetchImpl:async (_,init)=>{
      request=JSON.parse(init.body); return Response.json({choices:[{message:{content:'OK'}}]});
    }});
    for (const [name,value] of Object.entries(expected)) assert.equal(request[name],value);
    assert.equal(request.max_tokens,600);
  }
  const fake=mockBackend({provider:async (_target,_init,payload) => {
    // Mimic Groq's documented GPT-OSS parameter contract rather than accepting every payload.
    if ('reasoning_format' in payload || payload.include_reasoning !== false) return Response.json({}, {status:400});
    return Response.json({choices:[{message:{content:'OK'}}]});
  }}), bridge=createBridge({env:testEnv,fetchImpl:fake.fetchImpl});
  const response=await bridge.fetch(req('/api/cloud/providers/test',{method:'POST',body:{provider:'groq',model:'openai/gpt-oss-120b'}}));
  assert.equal(response.status,200); assert.equal(fake.external[0].payload.max_tokens,1024);
  assert.equal(fake.external[0].payload.include_reasoning,false);
  assert.equal('reasoning_format' in fake.external[0].payload,false, 'Groq GPT-OSS rejects reasoning_format');
  await assert.rejects(chatCompletion({env:testEnv,id:'groq',model:'qwen/qwen3.8-27b',messages:[],maxTokens:1601,fetchImpl:fake.fetchImpl}),/response-length/);
});

test('reasoning settings and free-route price filters are confined to documented models', async () => {
  assert.equal(providerTestTokens('groq','openai/gpt-oss-120b'),1024);
  assert.equal(providerTestTokens('opencode','minimax-m2.7'),1024);
  assert.equal(providerTestTokens('openrouter','openrouter/free'),1024);
  assert.equal(providerTestTokens('huggingface','openai/gpt-oss-120b:groq'),1024);
  assert.equal(providerTestTokens('zai','glm-4.7-flash'),16);
  for (const [id,keyName,model,expected] of [
    ['zai','ZAI_API_KEY','glm-4.7-flash',{thinking:{type:'disabled'}}],
    ['zai','ZAI_API_KEY','glm-4.5-flash',{thinking:{type:'disabled'}}],
    ['openrouter','OPENROUTER_API_KEY','openrouter/free',{provider:{max_price:{prompt:0,completion:0,request:0}}}],
    ['openrouter','OPENROUTER_API_KEY','nvidia/nemotron-3.5-lightning:free',{provider:{max_price:{prompt:0,completion:0,request:0}},reasoning:{enabled:false}}],
    ['zai','ZAI_API_KEY','glm-5.3',{}],
    ['openrouter','OPENROUTER_API_KEY','openai/gpt-5.4',{}],
  ]) {
    let payload;
    const env = {[keyName]:'test-only-key', ...(id === 'zai' ? {ZAI_MODELS:model} : {OPENROUTER_MODELS:model})};
    await chatCompletion({env,id,model,messages:[{role:'user',content:'Hi'}],fetchImpl:async (_,init)=>{
      payload = JSON.parse(init.body);
      return Response.json({choices:[{message:{content:'OK'}}]});
    }});
    assert.deepEqual(payload, {model,messages:[{role:'user',content:'Hi'}],max_tokens:600,...expected});
    assert.equal('models' in payload,false, 'never send a model fallback list');
  }
  for (const [provider,model,keyName,modelsName] of [
    ['openrouter','openrouter/free','OPENROUTER_API_KEY','OPENROUTER_MODELS'],
    ['openrouter','nvidia/nemotron-3.5-lightning:free','OPENROUTER_API_KEY','OPENROUTER_MODELS'],
    ['zai','glm-4.7-flash','ZAI_API_KEY','ZAI_MODELS'],
    ['zai','glm-4.5-flash','ZAI_API_KEY','ZAI_MODELS'],
  ]) {
    const fake = mockBackend({provider:async()=>Response.json({}, {status:429})});
    const bridge = createBridge({env:{...testEnv,[keyName]:'test-only-key',[modelsName]:model},fetchImpl:fake.fetchImpl});
    const res = await bridge.fetch(req('/api/cloud/chat',{method:'POST',body:{...input,provider,model,fallback:{provider:'mistral',model:'mistral-small-latest'}}}));
    assert.equal(res.status,422); assert.match((await res.json()).error,/does not allow a fallback/);
    assert.equal(fake.external.length,0); assert.equal(fake.usage.length,0);
    const noFallback = await bridge.fetch(req('/api/cloud/chat',{method:'POST',body:{...input,provider,model}}));
    assert.equal(noFallback.status,429); assert.equal(fake.external.length,1); assert.equal(fake.usage.length,1);
  }
});

test('detailed chat has a bounded token budget and reports truncated output', async () => {
  const fake=mockBackend({provider:async()=>Response.json({choices:[{message:{content:'x'.repeat(6001)},finish_reason:'length'}]})});
  const bridge=createBridge({env:testEnv,fetchImpl:fake.fetchImpl});
  const response=await bridge.fetch(req('/api/cloud/chat',{method:'POST',body:{...input,length:'detailed'}}));
  assert.equal(response.status,200); const data=await response.json();
  assert.equal(data.truncated,true); assert.equal(data.reply.length,6000);
  assert.match(data.reply,/\[Reply truncated; ask for a continuation\.\]$/);
  assert.equal(fake.external[0].payload.max_tokens,1600);
  assert.equal(fake.turns[0].reply,data.reply);
  const denied=await bridge.fetch(req('/api/cloud/chat',{method:'POST',body:{...input,length:'1000000'}}));
  assert.equal(denied.status,422); assert.equal(fake.external.length,1);
});

test('provider failures are sanitized, response size is bounded and timeouts do not request a retry', async () => {
  const options = {env:testEnv, id:'groq', model:'qwen/qwen3.8-27b', messages:[]};
  await assert.rejects(chatCompletion({...options, fetchImpl:async () => Response.json({error:'test-only-groq'}, {status:401})}), error => error.status === 502 && error.retryable && !error.message.includes('test-only-groq'));
  await assert.rejects(chatCompletion({...options, fetchImpl:async () => {throw new Error('test-only-groq');}}), error => error.status === 504 && !error.retryable && !error.message.includes('test-only-groq'));
  await assert.rejects(chatCompletion({...options, fetchImpl:async () => new Response('x'.repeat(270_000))}), /too large/);
  await assert.rejects(chatCompletion({...options, fetchImpl:async () => new Response('not json')}), /invalid JSON/);
});

test('inference errors that might have incurred a charge never trigger automatic fallback', async () => {
  const fallback = {provider:'mistral',model:'mistral-small-latest'};
  const failures = [
    ...[400,402,404,408,409,422,499,500,501,502,503,504,599].map(status => [`HTTP ${status}`, () => Response.json({secret:'upstream-only'}, {status})]),
    ['invalid JSON', () => new Response('not json')],
    ['empty output', () => Response.json({choices:[{message:{content:''}}]})],
    ['oversized output', () => new Response('x'.repeat(270_000))],
    ['network timeout', () => {throw new Error('private-network-detail');}],
  ];
  for (const [label,fail] of failures) {
    const fake = mockBackend({provider:async target => target.hostname === 'api.groq.com'
      ? fail() : Response.json({choices:[{message:{content:'must never be sent'}}]})});
    const response = await createBridge({env:testEnv,fetchImpl:fake.fetchImpl}).fetch(req('/api/cloud/chat',{method:'POST',body:{...input,fallback}}));
    const result = await response.json();
    assert.ok([502,504].includes(response.status),label);
    assert.match(result.error, /may have (?:been processed|incurred charges)/i,label);
    if (label === 'HTTP 400') assert.match(result.error,/HTTP 400.*configured model/i);
    if (label === 'HTTP 402') assert.match(result.error,/HTTP 402.*balance and billing/i);
    assert.doesNotMatch(JSON.stringify(result), /upstream-only|private-network-detail/,label);
    assert.equal(fake.external.length,1,`${label} sent a second external request`);
    assert.deepEqual(fake.usage.map(call=>call.status),['failed'],label);
  }
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

test('GitHub lookup is authenticated, budgeted, public-only, fixed-host and sanitized',async()=>{
  const fake=mockBackend({provider:async target=>{
    assert.equal(target.hostname,'api.github.com');assert.equal(target.pathname,'/repos/octocat/Hello-World');
    return Response.json({private:false,full_name:'octocat/Hello-World',description:'<img src=x>\u0000demo',html_url:'https://evil.example/',
      stargazers_count:12,forks_count:3,license:{spdx_id:'MIT'},archived:false,updated_at:'2026-01-01T00:00:00Z'});
  }});
  const bridge=createBridge({env:testEnv,fetchImpl:fake.fetchImpl});
  assert.equal((await bridge.fetch(req('/api/cloud/github/repository',{method:'POST',user:null,body:{repository:'octocat/Hello-World'}}))).status,401);
  assert.equal((await bridge.fetch(req('/api/cloud/github/repository',{method:'POST',origin:'https://evil.example',body:{repository:'octocat/Hello-World'}}))).status,403);
  for(const repository of ['https://evil.example/octocat/Hello-World','octocat/../x','github.com/octocat/Hello-World','octocat/..','octocat/x?x=1']) {
    assert.equal((await bridge.fetch(req('/api/cloud/github/repository',{method:'POST',body:{repository}}))).status,422);
  }
  assert.equal(fake.external.length,0);assert.equal(fake.usage.length,0);
  const r=await bridge.fetch(req('/api/cloud/github/repository',{method:'POST',body:{repository:'https://github.com/octocat/Hello-World'}}));
  assert.equal(r.status,200);const result=await r.json();
  assert.equal(result.repository.url,'https://github.com/octocat/Hello-World');assert.equal(result.repository.license,'MIT');
  assert.equal(result.repository.description,'<img src=x> demo');assert.equal(fake.usage[0].provider,'github');assert.equal(fake.usage[0].feature,'stock_search');
  assert.equal(fake.external[0].init.redirect,'error');assert.equal(fake.external[0].init.headers.authorization,undefined);
  const denied=createBridge({env:{...testEnv,VIMAX_AI_ALLOW_ALL_AUTHENTICATED:'false'},fetchImpl:fake.fetchImpl});
  assert.equal((await denied.fetch(req('/api/cloud/github/repository',{method:'POST',body:{repository:'octocat/Hello-World'}}))).status,403);
  const privateApi=mockBackend({provider:async()=>Response.json({private:true,full_name:'octocat/Hello-World'})});
  const failed=await createBridge({env:testEnv,fetchImpl:privateApi.fetchImpl}).fetch(req('/api/cloud/github/repository',{method:'POST',body:{repository:'octocat/Hello-World'}}));
  assert.equal(failed.status,502);assert.equal(privateApi.usage[0].status,'failed');
  const limited=mockBackend({provider:async()=>Response.json({message:'not for clients'},{status:403})});
  const quota=await createBridge({env:testEnv,fetchImpl:limited.fetchImpl}).fetch(req('/api/cloud/github/repository',{method:'POST',body:{repository:'octocat/Hello-World'}}));
  assert.equal(quota.status,429);assert.match((await quota.json()).error,/quota/);
});

// These tests are simulated. No Vercel or provider request is made.
const freeCatalog = (changes = {}) => ({data:{id:'reflection/beam-free', endpoints:[{
  provider_name:'reflection', status:0, tags:['free'], pricing:{prompt:'0',completion:'0',request:'0',internal_reasoning:'0',discount:0},
  ...changes,
}]}});
const gatewayInput = {provider:'vercel', model:'reflection/beam-free', prompt:'A nonsensitive question.', mode:'chat'};

test('Vercel free adapter uses a fixed model, free routing and a fresh request token', async () => {
  const fake = mockBackend({provider:async target => target.pathname.endsWith('/endpoints')
    ? Response.json(freeCatalog()) : Response.json({choices:[{message:{content:'Free-route reply.'}}],usage:{prompt_tokens:7,completion_tokens:3}})});
  let issued = 0;
  const env = {...testEnv, VIMAX_GATEWAY_FREE_ENABLED:'true', VIMAX_GATEWAY_REQUEST_TOKEN:'untrusted-static-token'};
  const bridge = createBridge({env, fetchImpl:fake.fetchImpl, getGatewayToken:() => `temporary.request.token${++issued}`});
  const status = await (await bridge.fetch(req('/api/cloud/providers'))).json();
  const gateway = status.providers.find(p => p.id === 'vercel');
  assert.equal(gateway.state, 'configured_unverified');
  assert.deepEqual(gateway.models, ['reflection/beam-free']);
  assert.doesNotMatch(JSON.stringify(status), /temporary|untrusted-static/);
  const health = await (await bridge.fetch(req('/api/health', {user:null}))).json();
  assert.equal(health.text_chat, 'configured_unverified');
  assert.doesNotMatch(JSON.stringify(health), /temporary|untrusted-static/);

  const response = await bridge.fetch(req('/api/cloud/chat', {method:'POST', body:gatewayInput}));
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.reply, 'Free-route reply.');
  assert.equal(result.used_fallback, false);
  assert.doesNotMatch(JSON.stringify(result), /temporary|untrusted-static/);
  assert.equal(fake.external.length, 2);
  const [catalog, generation] = fake.external;
  assert.equal(catalog.url, 'https://ai-gateway.vercel.sh/v1/models/reflection/beam-free/endpoints');
  assert.equal(catalog.init.method, 'GET');
  assert.equal(catalog.init.redirect, 'error');
  assert.equal(catalog.init.cache, 'no-store');
  assert.equal(catalog.init.headers, undefined);
  assert.equal(generation.url, 'https://ai-gateway.vercel.sh/v1/chat/completions');
  assert.equal(generation.init.headers.authorization, 'Bearer temporary.request.token3');
  assert.equal(generation.init.redirect, 'error');
  assert.equal(generation.payload.model, 'reflection/beam-free');
  assert.equal(generation.payload.max_tokens, 600);
  assert.deepEqual(generation.payload.providerOptions, {gateway:{only:['reflection'], has:['free']}});
  assert.deepEqual(generation.payload.reasoning, {effort:'low',exclude:true});
  assert.equal(Object.hasOwn(generation.payload, 'models'), false);
  assert.equal(Object.hasOwn(generation.payload, 'tools'), false);
  assert.equal(fake.usage[0].provider, 'vercel');
  assert.equal(fake.usage[0].status, 'succeeded');
  assert.equal(env.VIMAX_GATEWAY_REQUEST_TOKEN, 'untrusted-static-token', 'do not mutate source environment');

  const next = await bridge.fetch(req('/api/cloud/providers/test', {method:'POST', body:gatewayInput}));
  assert.equal(next.status, 200);
  assert.equal(fake.external[3].init.headers.authorization, 'Bearer temporary.request.token4');
  assert.equal(fake.external[3].payload.max_tokens, 1024);
  assert.equal(fake.usage[1].feature, 'provider_test');
});

test('free adapter fails closed on missing flag or trusted token, wrong model, owner denial, and any fallback', async () => {
  const fake = mockBackend(), base = {...testEnv,VIMAX_GATEWAY_REQUEST_TOKEN:'static-token'};
  let calls = 0;
  const disabled = createBridge({env:base,fetchImpl:fake.fetchImpl,getGatewayToken:() => {calls++;return 'valid.token';}});
  const status = await (await disabled.fetch(req('/api/cloud/providers'))).json();
  assert.equal(status.providers.find(p => p.id === 'vercel').state, 'not_configured');
  assert.equal(calls, 0, 'disabled feature must not resolve credentials');
  const enabled = {...base, VIMAX_GATEWAY_FREE_ENABLED:'true'};
  const missing = createBridge({env:enabled,fetchImpl:fake.fetchImpl,getGatewayToken:() => {throw new Error('secret diagnostic');}});
  const missingStatus = await (await missing.fetch(req('/api/cloud/providers'))).json();
  assert.equal(missingStatus.providers.find(p => p.id === 'vercel').state, 'not_configured');
  assert.doesNotMatch(JSON.stringify(missingStatus), /secret diagnostic|static-token/);
  assert.equal((await missing.fetch(req('/api/cloud/chat',{method:'POST',body:gatewayInput}))).status,503);
  const noResolver = createBridge({env:enabled,fetchImpl:fake.fetchImpl});
  assert.equal((await (await noResolver.fetch(req('/api/cloud/providers'))).json()).providers.find(p => p.id === 'vercel').state, 'not_configured');
  const valid = createBridge({env:enabled,fetchImpl:fake.fetchImpl,getGatewayToken:() => 'trusted.token'});
  const badModel = await valid.fetch(req('/api/cloud/chat',{method:'POST',body:{...gatewayInput,model:'openai/gpt-6'}}));
  assert.equal(badModel.status, 422);
  const fallback = await valid.fetch(req('/api/cloud/chat',{method:'POST',body:{...gatewayInput,fallback:{provider:'groq',model:'qwen/qwen3.8-27b'}}}));
  assert.equal(fallback.status, 422);
  assert.match((await fallback.json()).error, /does not allow a fallback/);
  const denied = createBridge({env:{...enabled,VIMAX_AI_ALLOW_ALL_AUTHENTICATED:'false'},fetchImpl:fake.fetchImpl,getGatewayToken:() => 'trusted.token'});
  assert.equal((await denied.fetch(req('/api/cloud/chat',{method:'POST',body:gatewayInput}))).status, 403);
  assert.equal(fake.external.length, 0);
  assert.equal(fake.usage.length, 0);
});

test('free catalog rejects paid, changed, missing or unverifiable endpoints without sending a generation', async () => {
  const price = {prompt:'0',completion:'0',request:'0'};
  const invalidCatalogs = [
    {data:{id:'different/model',endpoints:freeCatalog().data.endpoints}},
    freeCatalog({provider_name:'other'}), freeCatalog({status:1}), freeCatalog({tags:['reasoning']}),
    freeCatalog({tags:'free'}), freeCatalog({pricing:{...price,completion:'0.01'}}),
    freeCatalog({pricing:{...price,unexpected_price:'0.00001'}}), freeCatalog({pricing:{...price,prompt:''}}),
    freeCatalog({pricing:{prompt:'0',completion:'0'}}), freeCatalog({pricing:{...price,tiers:[{cost:'0'}]}}),
    {data:{id:'reflection/beam-free',endpoints:[]}}, null,
  ];
  const env = {VIMAX_GATEWAY_FREE_ENABLED:'true',VIMAX_GATEWAY_REQUEST_TOKEN:'trusted.token'};
  for (const catalog of invalidCatalogs) {
    const targets = [];
    await assert.rejects(chatCompletion({env,id:'vercel',model:'reflection/beam-free',messages:[],fetchImpl:async (url)=>{
      targets.push(url); return Response.json(catalog);
    }}), error => error.status === 503 && /No AI generation was sent/.test(error.message));
    assert.deepEqual(targets, ['https://ai-gateway.vercel.sh/v1/models/reflection/beam-free/endpoints']);
  }
  let calls = 0;
  await assert.rejects(chatCompletion({env,id:'vercel',model:'reflection/beam-free',messages:[],fetchImpl:async()=>{calls++;throw new Error('private network details');}}),
    error => error.status === 503 && !error.message.includes('private network details'));
  assert.equal(calls, 1);
});
