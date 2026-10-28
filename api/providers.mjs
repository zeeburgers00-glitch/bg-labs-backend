// Server-only, fixed-host provider adapters. Browser input can choose only a
// configured provider/model; it never supplies a URL, key, or arbitrary model.
const SPECS = Object.freeze([
  // The bridge injects a fresh Vercel request-context token, never browser input
  // or a durable user-supplied key. The model and provider cannot be overridden.
  {id:'vercel', label:'Vercel · Reflection Free', key:'VIMAX_GATEWAY_REQUEST_TOKEN', enabled:'VIMAX_GATEWAY_FREE_ENABLED', defaults:['reflection/beam-free'], allowedModels:['reflection/beam-free'], url:'https://ai-gateway.vercel.sh/v1/chat/completions'},
  {id:'openai', label:'OpenAI', key:'OPENAI_API_KEY', models:'OPENAI_MODELS', defaults:['gpt-5.4-mini','gpt-5.4'], url:'https://api.openai.com/v1/chat/completions', maxTokenField:'max_completion_tokens'},
  {id:'groq', label:'Groq', key:'GROQ_API_KEY', models:'GROQ_MODELS', defaults:['openai/gpt-oss-120b','llama-3.1-8b-instant'], url:'https://api.groq.com/openai/v1/chat/completions'},
  // Google limits 2.5 Flash for new projects; prefer its current Flash model.
  // Actual model availability and pricing still depend on the owner's account.
  {id:'gemini', label:'Gemini', key:'GEMINI_API_KEY', models:'GEMINI_MODELS', defaults:['gemini-3.8-flash','gemini-2.5-flash','gemini-4-argon'], url:'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'},
  {id:'mistral', label:'Mistral', key:'MISTRAL_API_KEY', models:'MISTRAL_MODELS', defaults:['mistral-small-latest'], url:'https://api.mistral.ai/v1/chat/completions'},
  {id:'zai', label:'Z.ai (general API)', key:'ZAI_API_KEY', models:'ZAI_MODELS', defaults:['glm-4.5-flash'], url:'https://api.z.ai/api/paas/v4/chat/completions'},
  {id:'openrouter', label:'OpenRouter', key:'OPENROUTER_API_KEY', models:'OPENROUTER_MODELS', defaults:['openrouter/free'], url:'https://openrouter.ai/api/v1/chat/completions'},
  {id:'huggingface', label:'Hugging Face Inference', key:'HF_TOKEN', models:'HF_MODELS', defaults:['openai/gpt-oss-120b:groq'], url:'https://router.huggingface.co/v1/chat/completions'},
  // OpenCode's different model families use different protocols. Restrict this
  // adapter to documented paid chat-completions models, not /responses or
  // /messages models. Free chat models require the OpenCode client itself.
  {id:'opencode', label:'OpenCode Console / Zen', key:'OPENCODE_API_KEY', models:'OPENCODE_MODELS', defaults:[], url:'https://opencode.ai/inference/openai/v1/chat/completions', allowedModels:['qwen3.8-max','deepseek-v4.1-flash','deepseek-v4-pro','minimax-m3','minimax-m2.7','minimax-m2.5','glm-5.3-flash','glm-5.3','glm-5.2','glm-5.1','glm-5','kimi-k2.5','kimi-k2.6','kimi-k2.7-code','kimi-k3','mistral-large-4']},
]);
const MODEL = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/;
const MAX_RESPONSE_BYTES = 256 * 1024;

export class ProviderError extends Error {
  constructor(status, message, retryable = false, uncertain = false) {
    super(message); this.status = status; this.retryable = retryable; this.uncertain = uncertain;
  }
}
function validKey(value) {
  return typeof value === 'string' && /^[\x21-\x7e]{1,2048}$/.test(value);
}
function configuration(env, spec) {
  if (spec.enabled && env[spec.enabled] !== 'true') return {state:'not_configured', models:[]};
  const key = env[spec.key] || '';
  const raw = spec.models ? env[spec.models] : undefined;
  const models = raw === undefined || raw === '' ? spec.defaults : String(raw).split(',').map(s => s.trim());
  if (!key) return {state:'not_configured', models:[]};
  // OIDC JWTs can be longer than ordinary provider API keys.
  const valid = spec.id === 'vercel' ? typeof key === 'string' && /^[A-Za-z0-9._-]{1,8192}$/.test(key) : validKey(key);
  if (!valid) return {state:'invalid_configuration', models:[]};
  if (!models.length) return {state:'model_required', models:[]};
  if (models.length > 10 || new Set(models).size !== models.length || models.some(m => !MODEL.test(m) || (spec.allowedModels && !spec.allowedModels.includes(m)))) {
    return {state:'invalid_configuration', models:[]};
  }
  return {state:'configured_unverified', models, key};
}
export function providerStatus(env) {
  return SPECS.map(spec => {
    const config = configuration(env, spec);
    return {id:spec.id, label:spec.label, state:config.state, models:config.models};
  });
}
export function pexelsStatus(env) {
  const value = env.PEXELS_API_KEY || '';
  return !value ? 'not_configured' : validKey(value) ? 'configured_unverified' : 'invalid_configuration';
}
function selected(env, id, model) {
  const spec = SPECS.find(p => p.id === id);
  if (!spec) throw new ProviderError(422, 'Choose an available AI provider.');
  const config = configuration(env, spec);
  if (config.state !== 'configured_unverified') throw new ProviderError(503, `${spec.label} is not configured for chat on this deployment.`);
  if (typeof model !== 'string' || !config.models.includes(model)) throw new ProviderError(422, 'Choose a model allowed by the deployment owner.');
  return {spec, key:config.key};
}
export function validateSelection(env, id, model) {
  selected(env, id, model);
}
function responseFailure(status, inference = false) {
  if (status === 401 || status === 403) return new ProviderError(502, 'The provider rejected its credentials or permissions.', true);
  if (status === 429) return new ProviderError(429, 'The provider rate limit or quota was reached.', true);
  // An intermediary or provider may fail after the model has already run.
  // An unexpected HTTP error is not proof that it was free or unprocessed.
  if (inference) return new ProviderError(502,
    'The provider returned an unexpected error. The request may have been processed or incurred charges; no further automatic retry or fallback will be sent.', false, true);
  if ([500, 502, 503, 504].includes(status)) return new ProviderError(502, 'The provider is temporarily unavailable.', true);
  return new ProviderError(502, 'The provider rejected the configured model or request.');
}
async function readResponse(response, {inference = false} = {}) {
  const invalidResponse = message => new ProviderError(502,
    inference ? `${message} The request may have incurred charges.` : message, false, inference);
  if (!response.ok) {
    try { await response.body?.cancel(); } catch { /* Never disclose provider error bodies. */ }
    throw responseFailure(response.status, inference);
  }
  const declared = response.headers.get('content-length');
  if (declared && Number(declared) > MAX_RESPONSE_BYTES) throw invalidResponse('The provider response was too large.');
  const reader = response.body?.getReader();
  if (!reader) throw invalidResponse('The provider returned an empty response.');
  const chunks = []; let size = 0;
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_RESPONSE_BYTES) {
      await reader.cancel();
      throw invalidResponse('The provider response was too large.');
    }
    chunks.push(value);
  }
  const joined = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { joined.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder().decode(joined)); }
  catch { throw invalidResponse('The provider returned invalid JSON.'); }
}
function safeCount(value) {
  return Number.isSafeInteger(value) && value >= 0 && value <= 10_000_000 ? value : null;
}

// Check the fixed public catalog before every free-route call. This is a
// fail-closed check of published Gateway prices, not a guarantee against team
// BYOK or add-on charges. It must never turn into a paid model fallback.
async function requireFreeGatewayEndpoint(fetchImpl) {
  try {
    const response = await fetchImpl('https://ai-gateway.vercel.sh/v1/models/reflection/beam-free/endpoints', {
      method:'GET', signal:AbortSignal.timeout(12_000), redirect:'error', cache:'no-store'
    });
    const catalog = await readResponse(response);
    const endpoints = catalog?.data?.endpoints;
    const endpoint = Array.isArray(endpoints) && endpoints.find(item => item?.provider_name === 'reflection');
    const prices = endpoint?.pricing;
    const zero = value => (typeof value === 'number' && Number.isFinite(value) && value === 0)
      || (typeof value === 'string' && value.length <= 32 && /^0+(?:\.0+)?$/.test(value));
    if (catalog?.data?.id !== 'reflection/beam-free' || endpoint?.status !== 0 || !Array.isArray(endpoint?.tags) || !endpoint.tags.includes('free')
        || !prices || typeof prices !== 'object' || Array.isArray(prices)
        || !['prompt','completion','request'].every(key => Object.hasOwn(prices, key) && zero(prices[key]))
        || !Object.values(prices).every(zero)) throw new Error('Free endpoint is not confirmed.');
  } catch {
    throw new ProviderError(503, 'Free AI pricing or availability could not be verified. No AI generation was sent.');
  }
}
// Explicitly bound reasoning for the documented models below. Other models
// keep their provider defaults rather than receiving an incompatible parameter.
function reasoningOptions(id, model) {
  if (id === 'vercel') return {reasoning:{effort:'low', exclude:true}, providerOptions:{gateway:{only:['reflection'], has:['free']}}};
  if (id === 'groq' && /^openai\/gpt-oss-(?:20b|120b)$/.test(model)) return {reasoning_effort:'low', reasoning_format:'hidden'};
  if (id === 'gemini' && ['gemini-3.8-flash','gemini-4-argon'].includes(model)) return {reasoning_effort:'low'};
  return {};
}
export function providerTestTokens(id, model) {
  // Thinking models may use the small probe budget before producing an answer.
  return id === 'vercel' || id === 'gemini' || (id === 'groq' && /^openai\/gpt-oss-(?:20b|120b)$/.test(model)) ? 1024 : 16;
}
export async function chatCompletion({env, fetchImpl, id, model, messages, maxTokens = 600}) {
  const {spec, key} = selected(env, id, model);
  if (!Number.isInteger(maxTokens) || maxTokens < 1 || maxTokens > 1600) throw new ProviderError(422, 'Invalid response-length limit.');
  if (id === 'vercel') await requireFreeGatewayEndpoint(fetchImpl);
  let value;
  try {
    const response = await fetchImpl(spec.url, {method:'POST', headers:{authorization:`Bearer ${key}`, 'content-type':'application/json'},
      body:JSON.stringify({model, messages, [spec.maxTokenField || 'max_tokens']:maxTokens, ...reasoningOptions(id, model)}), signal:AbortSignal.timeout(25_000), redirect:'error', cache:'no-store'});
    value = await readResponse(response, {inference:true});
  } catch (error) {
    if (error instanceof ProviderError) throw error;
    // A timed-out or interrupted request may already have been billed. Do not
    // automatically retry or switch providers in that ambiguous situation.
    throw new ProviderError(504, 'The provider request timed out or could not be completed; it may have incurred charges.', false, true);
  }
  const text = value?.choices?.[0]?.message?.content;
  if (typeof text !== 'string' || !text.trim()) throw new ProviderError(502,
    'The provider returned no text. The request may have incurred charges.', false, true);
  const chars = Array.from(text.trim());
  return {text:chars.slice(0, 6000).join(''), truncated:chars.length > 6000 || value?.choices?.[0]?.finish_reason === 'length',
    inputTokens:safeCount(value?.usage?.prompt_tokens), outputTokens:safeCount(value?.usage?.completion_tokens)};
}
function safePexelsUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'www.pexels.com' && !url.port && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
export async function searchPexels({env, fetchImpl, query, orientation}) {
  if (pexelsStatus(env) !== 'configured_unverified') throw new ProviderError(503, 'Pexels is not configured on this deployment.');
  const url = new URL('https://api.pexels.com/v1/videos/search');
  url.searchParams.set('query', query); url.searchParams.set('per_page', '8');
  if (orientation) url.searchParams.set('orientation', orientation);
  let value;
  try {
    const response = await fetchImpl(url.href, {method:'GET', headers:{authorization:env.PEXELS_API_KEY}, signal:AbortSignal.timeout(12_000), redirect:'error', cache:'no-store'});
    value = await readResponse(response);
  } catch (error) {
    if (error instanceof ProviderError) throw error;
    throw new ProviderError(504, 'Pexels could not be reached.');
  }
  if (!Array.isArray(value?.videos)) throw new ProviderError(502, 'Pexels returned an invalid result.');
  return value.videos.slice(0, 8).map(video => {
    const url = safePexelsUrl(video?.url);
    if (!url || !Number.isSafeInteger(video?.id) || video.id < 1) return null;
    return {id:video.id, url, creator:typeof video?.user?.name === 'string' ? video.user.name.replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 100) : 'Pexels contributor',
      duration:Number.isFinite(video.duration) && video.duration >= 0 ? Math.round(video.duration) : null,
      width:Number.isSafeInteger(video.width) && video.width > 0 ? video.width : null,
      height:Number.isSafeInteger(video.height) && video.height > 0 ? video.height : null};
  }).filter(Boolean);
}

// Public GitHub repository metadata only. No OAuth token, private repository,
// branch content, write action, or user-supplied outbound URL is supported.
export function githubRepositoryInput(value) {
  const text=typeof value==='string'?value.trim():'';
  const match=/^(?:https:\/\/github\.com\/)?([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))\/([A-Za-z0-9._-]{1,100})\/?$/i.exec(text);
  if (!match || match[1].endsWith('-') || ['.','..'].includes(match[2])) throw new ProviderError(422,'Enter a public GitHub repository as owner/name or a github.com repository URL.');
  return {owner:match[1],repo:match[2]};
}
const cleanGithubText=(value,max)=>typeof value==='string'?Array.from(value.replace(/[\u0000-\u001f\u007f]/g,' ')).slice(0,max).join(''):'';
export async function getGithubRepository({fetchImpl,owner,repo}) {
  // Revalidate even if called outside the bridge, and construct a fixed host.
  const input=githubRepositoryInput(`${owner}/${repo}`);
  const url=`https://api.github.com/repos/${encodeURIComponent(input.owner)}/${encodeURIComponent(input.repo)}`;
  let value;
  try {
    const response=await fetchImpl(url,{method:'GET',headers:{accept:'application/vnd.github+json','user-agent':'ViMax-public-repository-lookup','x-github-api-version':'2026-03-10'},
      signal:AbortSignal.timeout(12_000),redirect:'error',cache:'no-store'});
    if (response.status===404) throw new ProviderError(404,'That public repository was not found. Private repositories are not supported.');
    if ([403,429].includes(response.status)) throw new ProviderError(429,'GitHub public API quota was reached or access was denied. Try later.');
    value=await readResponse(response);
  } catch (error) {
    if(error instanceof ProviderError)throw error;
    throw new ProviderError(503,'GitHub could not be reached. No private repository access was attempted.');
  }
  const full=cleanGithubText(value?.full_name,140);
  if (value?.private!==false || full.toLowerCase()!==`${input.owner}/${input.repo}`.toLowerCase()) throw new ProviderError(502,'GitHub returned an unexpected repository.');
  const date=typeof value.updated_at==='string' && Number.isFinite(Date.parse(value.updated_at)) ? new Date(value.updated_at).toISOString() : null;
  return {name:full,url:`https://github.com/${encodeURIComponent(input.owner)}/${encodeURIComponent(input.repo)}`,
    description:cleanGithubText(value.description,500),stars:safeCount(value.stargazers_count),forks:safeCount(value.forks_count),
    license:cleanGithubText(value.license?.spdx_id,80)||'Not specified',updated_at:date,archived:value.archived===true};
}
