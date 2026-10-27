// Public, stateless Supabase API. It never exposes ViMax's unauthenticated
// single-workspace local server or server-side provider keys to the Internet.
import {ProviderError, providerStatus, pexelsStatus, validateSelection, chatCompletion, searchPexels} from './providers.mjs';

const ACCESS_COOKIE = '__Host-vimax_access';
const REFRESH_COOKIE = '__Host-vimax_refresh';
const MAX_BODY = 8192;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const AGENT_UNAVAILABLE = 'The online ViMax video agent and YouTube upload are not connected yet. Open Skills & Agents for saved ideas and cloud text planning when configured.';
const SYSTEM_PROMPT = 'You are ViMax’s text-planning assistant for original, legitimate video projects. You cannot browse, verify facts, render videos, access YouTube, publish or run background jobs. Never claim you performed those actions. Distinguish suggestions from verified facts, say when sources need checking, respect copyright, and do not suggest fake engagement or spam.';
const MODES = Object.freeze({chat:'Help the user plan their video project.', ideas:'Brainstorm distinct, original video ideas with audiences and hooks.', script:'Draft a clear narration script with a hook and structure; flag claims needing verification.', review:'Review the provided material for unsupported claims, originality risks and unclear wording; do not claim independent verification.'});

class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

function json(body, status = 200, cookies = []) {
  const headers = new Headers({'cache-control':'no-store', 'x-content-type-options':'nosniff', 'referrer-policy':'no-referrer', 'vary':'Cookie, Origin'});
  for (const cookie of cookies) headers.append('set-cookie', cookie);
  return Response.json(body, {status, headers});
}
function cookie(name, value, maxAge) {
  // Values are opaque GoTrue tokens; reject anything that could corrupt headers.
  if (!/^[A-Za-z0-9_.~-]*$/.test(value) || value.length > 4096) throw new Error('Invalid session token.');
  return `${name}=${value}; Path=/; Max-Age=${maxAge}; Secure; HttpOnly; SameSite=Lax`;
}
function sessionCookies(session) {
  if (!session || typeof session.access_token !== 'string' || typeof session.refresh_token !== 'string') throw new Error('Invalid authentication response.');
  const age = Math.max(1, Math.min(Number(session.expires_in) || 3600, 3600));
  return [cookie(ACCESS_COOKIE, session.access_token, age), cookie(REFRESH_COOKIE, session.refresh_token, 30 * 24 * 3600)];
}
function clearCookies() { return [cookie(ACCESS_COOKIE, '', 0), cookie(REFRESH_COOKIE, '', 0)]; }
function readCookies(request) {
  const result = Object.create(null);
  for (const part of (request.headers.get('cookie') || '').split(';')) {
    const idx = part.indexOf('=');
    if (idx < 0) continue;
    const name = part.slice(0, idx).trim(), value = part.slice(idx + 1).trim();
    if ([ACCESS_COOKIE, REFRESH_COOKIE].includes(name) && /^[A-Za-z0-9_.~-]{1,4096}$/.test(value)) {
      // Duplicate names can cause cookie-tossing ambiguity. Treat them as invalid.
      if (name in result) return Object.create(null);
      result[name] = value;
    }
  }
  return result;
}
function pathFor(request) {
  const url = new URL(request.url);
  const rewrite = url.searchParams.get('__vimax_path');
  if (rewrite !== null) {
    if (!/^[A-Za-z0-9_/-]*$/.test(rewrite) || rewrite.includes('..')) throw new HttpError(400, 'Invalid API path.');
    return `/api/${rewrite.replace(/^\/+/, '')}`;
  }
  return url.pathname;
}
function sameOrigin(request) {
  const origin = request.headers.get('origin');
  return Boolean(origin && origin === new URL(request.url).origin && request.headers.get('sec-fetch-site') !== 'cross-site');
}
async function body(request) {
  if (!(request.headers.get('content-type') || '').toLowerCase().startsWith('application/json')) throw new HttpError(415, 'Use application/json.');
  const declared = request.headers.get('content-length');
  if (declared && (!/^\d+$/.test(declared) || Number(declared) > MAX_BODY)) throw new HttpError(413, 'Request is too large.');
  const reader = request.body?.getReader();
  if (!reader) throw new HttpError(400, 'A JSON request body is required.');
  const chunks = []; let size = 0;
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BODY) { await reader.cancel(); throw new HttpError(413, 'Request is too large.'); }
    chunks.push(value);
  }
  const joined = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { joined.set(chunk, offset); offset += chunk.length; }
  try {
    const value = JSON.parse(new TextDecoder().decode(joined));
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('not an object');
    return value;
  } catch { throw new HttpError(400, 'Invalid JSON object.'); }
}
function authInput(input) {
  const email = typeof input.email === 'string' ? input.email.trim() : '';
  const password = typeof input.password === 'string' ? input.password : '';
  if (email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || password.length < 6 || password.length > 128) {
    throw new HttpError(422, 'Enter a valid email and a password of 6–128 characters.');
  }
  return {email, password};
}
function projectInput(input) {
  const title = typeof input.title === 'string' ? input.title.trim() : '';
  const notes = typeof input.notes === 'string' ? input.notes.trim() : '';
  if (!title || title.length > 160 || notes.length > 4000 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(title + notes)) {
    throw new HttpError(422, 'Enter a title (up to 160 characters) and notes (up to 4000 characters).');
  }
  return {title, notes};
}
function chatInput(input) {
  const prompt = typeof input.prompt === 'string' ? input.prompt.trim() : '';
  const mode = input.mode === undefined ? 'chat' : input.mode;
  if (!prompt || Array.from(prompt).length > 1600 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(prompt) || !Object.hasOwn(MODES, mode)) {
    throw new HttpError(422, 'Enter up to 1600 characters and select a supported planning mode.');
  }
  const primary = {provider:input.provider, model:input.model};
  let fallback = null;
  if (input.fallback !== undefined && input.fallback !== null) {
    if (typeof input.fallback !== 'object' || Array.isArray(input.fallback)) throw new HttpError(422, 'Invalid fallback provider.');
    fallback = {provider:input.fallback.provider, model:input.fallback.model};
    if (fallback.provider === primary.provider && fallback.model === primary.model) throw new HttpError(422, 'Choose a different fallback provider or model.');
  }
  return {prompt, mode, primary, fallback};
}
function stockInput(input) {
  const query = typeof input.query === 'string' ? input.query.trim() : '';
  const orientation = input.orientation || '';
  if (!query || Array.from(query).length > 120 || /[\u0000-\u001f\u007f]/.test(query) || !['', 'landscape', 'portrait', 'square'].includes(orientation)) {
    throw new HttpError(422, 'Enter a stock search of up to 120 characters and a valid orientation.');
  }
  return {query, orientation};
}

function channelInput(input) {
  const fields = {name:100, niche:500, audience:500, brand_voice:500};
  const result = {};
  for (const [key,max] of Object.entries(fields)) {
    const value = typeof input[key] === 'string' ? input[key].trim() : '';
    if (Array.from(value).length > max || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value)) throw new HttpError(422, 'A channel field is too long or contains invalid characters.');
    result[key] = value;
  }
  if (!result.name || !result.niche) throw new HttpError(422, 'Enter a channel name and niche.');
  result.language = typeof input.language === 'string' ? input.language.trim() : '';
  result.timezone = typeof input.timezone === 'string' ? input.timezone.trim() : '';
  result.format = input.format;
  if (!/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(result.language) || result.language.length > 35
      || !/^[A-Za-z0-9_+/-]{1,80}$/.test(result.timezone) || !['shorts','landscape'].includes(result.format)) throw new HttpError(422, 'Choose a valid language, timezone and format.');
  try { new Intl.DateTimeFormat('en', {timeZone:result.timezone}); } catch { throw new HttpError(422, 'Choose a valid IANA timezone, such as Asia/Karachi or UTC.'); }
  return result;
}
function competitorInput(input) {
  if (typeof input.channel_id !== 'string' || !UUID.test(input.channel_id)) throw new HttpError(422, 'Choose a channel profile.');
  const url = typeof input.url === 'string' ? input.url.trim() : '';
  if (url.length > 300 || !/^https:\/\/(?:www\.)?youtube\.com\/(?:@[A-Za-z0-9_.-]+|(?:channel|c|user)\/[A-Za-z0-9_.-]+)$/.test(url)) {
    throw new HttpError(422, 'Use a YouTube channel URL without query parameters.');
  }
  return {channel_id:input.channel_id,url};
}
function missionJobInput(input) {
  const topic = typeof input.topic === 'string' ? input.topic.trim() : '';
  if (typeof input.channel_id !== 'string' || !UUID.test(input.channel_id) || typeof input.client_key !== 'string' || !UUID.test(input.client_key)
      || !topic || Array.from(topic).length > 1600 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(topic)
      || !['groq','gemini','mistral','zai','openrouter','huggingface','opencode'].includes(input.provider)
      || typeof input.model !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/.test(input.model)) throw new HttpError(422, 'Choose a channel, topic, supported provider and model.');
  let when = null;
  if (input.not_before !== undefined && input.not_before !== null && input.not_before !== '') {
    if (typeof input.not_before !== 'string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d{1,3})?)?(?:Z|[+-]\d\d:\d\d)$/.test(input.not_before)) throw new HttpError(422, 'Use an ISO timestamp with a timezone.');
    const date = new Date(input.not_before);
    if (!Number.isFinite(date.getTime()) || date.getTime() < Date.now() - 30 * 86400_000 || date.getTime() > Date.now() + 30 * 86400_000) throw new HttpError(422, 'Choose a start time within the next 30 days.');
    when = date.toISOString();
  }
  return {p_channel_id:input.channel_id,p_client_key:input.client_key,p_topic:topic,p_provider:input.provider,p_model:input.model,p_not_before:when};
}

export function createBridge({env = process.env, fetchImpl = globalThis.fetch} = {}) {
  function config() {
    let url;
    try { url = new URL(env.SUPABASE_URL || ''); } catch { throw new HttpError(503, 'Supabase is not configured on this deployment.'); }
    if (url.protocol !== 'https:' || !/^[a-z0-9-]+\.supabase\.co$/.test(url.hostname) || url.pathname !== '/' || url.search || url.hash || url.username || url.password || url.port) {
      throw new HttpError(503, 'Supabase configuration is invalid.');
    }
    const key = env.SUPABASE_PUBLISHABLE_KEY || '';
    if (!/^sb_publishable_[A-Za-z0-9_-]+$/.test(key)) throw new HttpError(503, 'Supabase is not configured on this deployment.');
    return {base:url.origin, key};
  }
  async function supa(path, {method = 'GET', token, data, extraHeaders = {}} = {}) {
    const {base, key} = config();
    let response;
    try {
      response = await fetchImpl(`${base}${path}`, {method, headers:{apikey:key, ...(token ? {authorization:`Bearer ${token}`} : {}),
        ...(data === undefined ? {} : {'content-type':'application/json'}), ...extraHeaders},
        ...(data === undefined ? {} : {body:JSON.stringify(data)}), signal:AbortSignal.timeout(12_000), redirect:'error', cache:'no-store'});
    } catch { throw new HttpError(503, 'Supabase is temporarily unreachable.'); }
    let value = null;
    if (response.status !== 204) { try { value = await response.json(); } catch { /* fail closed below */ } }
    return {response, value};
  }
  async function currentUser(request) {
    const cookies = readCookies(request);
    let access = cookies[ACCESS_COOKIE], updates = [];
    async function validate(token) {
      if (!token) return null;
      const {response, value} = await supa('/auth/v1/user', {token});
      return response.ok && value && typeof value.id === 'string' && UUID.test(value.id) ? value : null;
    }
    let user = await validate(access);
    if (!user && cookies[REFRESH_COOKIE]) {
      const {response, value} = await supa('/auth/v1/token?grant_type=refresh_token', {method:'POST', data:{refresh_token:cookies[REFRESH_COOKIE]}});
      if (response.ok && typeof value?.access_token === 'string' && typeof value?.refresh_token === 'string') {
        access = value.access_token; updates = sessionCookies(value); user = await validate(access);
      }
    }
    if (!user) return {user:null, access:null, updates:[]};
    return {user:{id:user.id, email:typeof user.email === 'string' ? user.email : ''}, access, updates};
  }
  async function requireUser(request) {
    const session = await currentUser(request);
    if (!session.user) throw new HttpError(401, 'Please sign in to your ViMax account.');
    return session;
  }
  function aiAllowed(session) {
    // The Supabase project is shared with other apps. A key alone must not
    // grant every account access to billable provider requests by accident.
    if (env.VIMAX_AI_ALLOW_ALL_AUTHENTICATED === 'true') return true;
    const raw = env.VIMAX_AI_ALLOWED_USER_IDS || '';
    if (!raw || raw.length > 4000) return false;
    const ids = raw.split(',').map(id => id.trim());
    if (ids.length > 100 || ids.some(id => !UUID.test(id))) return false;
    return ids.some(id => id.toLowerCase() === session.user.id.toLowerCase());
  }
  function requireAiAccess(session) {
    if (!aiAllowed(session)) throw new HttpError(403, 'AI provider access is not enabled for this account. Ask the deployment owner.');
  }
  async function databaseReady() {
    const auth = await supa('/auth/v1/health');
    if (!auth.response.ok) throw new HttpError(503, 'Supabase Auth is temporarily unavailable.');
    const database = await supa('/rest/v1/rpc/vimax_cloud_health', {method:'POST', data:{}});
    if (!database.response.ok || database.value !== true) throw new HttpError(503, 'Supabase database health check failed.');
  }
  async function reserve(session, feature, provider, model) {
    const {response, value} = await supa('/rest/v1/rpc/vimax_reserve_ai_call', {method:'POST', token:session.access,
      data:{p_feature:feature, p_provider:provider, p_model:model}});
    if (!response.ok || !value || typeof value !== 'object') throw new HttpError(503, 'AI safety limits are unavailable. No provider request was sent.');
    if (value.allowed !== true) {
      const reasons = {paused:'AI calls are paused for your account. Resume them to make another request.', in_flight:'Another request is in progress; wait up to a minute and try again.', user_daily_limit:'Your daily provider-request limit was reached (UTC).', global_daily_limit:'The shared daily provider-request limit was reached (UTC).', history_limit:'Chat history is full. Delete it before generating more replies.'};
      const known = typeof value.reason === 'string' && Object.hasOwn(reasons, value.reason);
      const message = known ? reasons[value.reason] : 'AI safety limits are unavailable. No provider request was sent.';
      throw new HttpError(['history_limit', 'paused'].includes(value.reason) ? 409 : known ? 429 : 503, message);
    }
    if (typeof value.id !== 'string' || !UUID.test(value.id) || typeof value.finish_secret !== 'string' || !UUID.test(value.finish_secret) || !Number.isInteger(value.remaining_user) || value.remaining_user < 0 || value.remaining_user > 9) {
      throw new HttpError(503, 'AI safety limits returned an invalid response. No provider request was sent.');
    }
    // Never return this random capability to the browser or log it.
    return {id:value.id, secret:value.finish_secret, remaining:value.remaining_user};
  }
  async function finish(session, reservation, state, result) {
    try {
      const {response, value} = await supa('/rest/v1/rpc/vimax_finish_ai_call', {method:'POST', token:session.access,
        data:{p_id:reservation.id, p_secret:reservation.secret, p_status:state, p_input_tokens:result?.inputTokens ?? null, p_output_tokens:result?.outputTokens ?? null}});
      return response.ok && value === true;
    } catch { return false; }
  }
  async function attempt(session, feature, selection, operation) {
    const reservation = await reserve(session, feature, selection.provider, selection.model);
    try {
      const result = await operation();
      const auditSaved = await finish(session, reservation, 'succeeded', result);
      return {result, remaining:reservation.remaining, auditSaved};
    } catch (error) {
      const auditSaved = await finish(session, reservation, 'failed', null);
      if (error && typeof error === 'object') error.auditSaved = auditSaved;
      throw error;
    }
  }
  async function handler(request) {
    let sessionUpdates = [];
    try {
      // Retain refreshed cookies even when a later provider/database operation
      // fails; otherwise refresh-token rotation would silently sign users out.
      const authenticated = async () => {
        const session = await requireUser(request);
        sessionUpdates = session.updates;
        return session;
      };
      const path = pathFor(request), method = request.method.toUpperCase();
      if (!['GET', 'HEAD', 'POST', 'PATCH', 'DELETE'].includes(method)) throw new HttpError(405, 'Method not allowed.');
      if (!['GET', 'HEAD'].includes(method) && !sameOrigin(request)) throw new HttpError(403, 'A same-origin request is required.');

      if (method === 'GET' && path === '/api/health') {
        await databaseReady();
        return json({ok:true, database:'connected', text_chat:providerStatus(env).some(p => p.state === 'configured_unverified') ? 'configured_unverified' : 'unconfigured', video_agent:'unavailable', youtube_upload:'unavailable'});
      }
      if (method === 'GET' && path === '/api/sessions') {
        await databaseReady();
        return json({activeSessionId:'', sessions:[], warning:AGENT_UNAVAILABLE});
      }
      if (method === 'GET' && path === '/api/events') {
        return new Response(`retry: 60000\ndata: ${JSON.stringify({type:'bridge_status', status:'stopped', message:AGENT_UNAVAILABLE})}\n\n`,
          {headers:{'content-type':'text/event-stream; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'}});
      }
      if (method === 'GET' && path === '/api/skills/system') {
        await databaseReady();
        return json({local_only:false, database_connected:true, text_chat:providerStatus(env).some(p => p.state === 'configured_unverified') ? 'configured_unverified' : 'unconfigured', ready_for_video:false, piper_installed:false, ffmpeg_installed:false, scene_detection_installed:false,
          voices:[], hardware:{logical_cpus:null, memory_gib:null, home_disk_free_gib:null, nvidia_gpu:null}, warnings:[AGENT_UNAVAILABLE]});
      }
      if (method === 'GET' && path === '/api/cloud/session') {
        const session = await currentUser(request);
        return json({user:session.user}, 200, session.updates);
      }
      if (method === 'POST' && path === '/api/cloud/signup') {
        const input = authInput(await body(request));
        // Only the production origin is allow-listed in the shared Supabase project.
        const redirect = encodeURIComponent('https://vimax-vert.vercel.app/skills/');
        const {response} = await supa(`/auth/v1/signup?redirect_to=${redirect}`, {method:'POST',data:input});
        if (!response.ok) throw new HttpError(response.status === 429 ? 429 : 400, response.status === 429 ? 'Email signup limit reached; try again later.' : 'Account creation failed. Check your details and try again.');
        return json({message:'If the account can be created, check your email to confirm it, then sign in here.'}, 202);
      }
      if (method === 'POST' && path === '/api/cloud/login') {
        const input = authInput(await body(request));
        const {response, value} = await supa('/auth/v1/token?grant_type=password', {method:'POST',data:input});
        if (!response.ok) throw new HttpError(response.status === 429 ? 429 : 401, response.status === 429 ? 'Too many attempts; try again later.' : 'Sign-in failed. Check your email, password and email confirmation.');
        return json({ok:true}, 200, sessionCookies(value));
      }
      if (method === 'POST' && path === '/api/cloud/logout') {
        // A network outage must not prevent a user from clearing local cookies.
        let session;
        try { session = await currentUser(request); } catch { /* clear locally even if offline */ }
        if (session?.access) { try { await supa('/auth/v1/logout', {method:'POST', token:session.access}); } catch { /* session cookies are still cleared below */ } }
        return json({ok:true}, 200, clearCookies());
      }
      if (path === '/api/cloud/mission' && method === 'GET') {
        const session = await authenticated();
        const paths = [
          '/rest/v1/vimax_channels?select=id,name,niche,audience,language,timezone,brand_voice,format,created_at,updated_at&order=created_at.desc&limit=25',
          '/rest/v1/vimax_competitors?select=id,channel_id,url,created_at&order=created_at.desc&limit=625',
          '/rest/v1/vimax_mission_jobs?select=id,channel_id,topic,provider,model,status,review_reason,not_before,attempts,cancel_requested,last_error,created_at,updated_at&order=created_at.desc,id.desc&limit=50',
          '/rest/v1/vimax_mission_workers?select=worker_id,last_seen_at&order=last_seen_at.desc&limit=10',
          '/rest/v1/vimax_mission_settings?select=paused&limit=1',
        ];
        const items = await Promise.all(paths.map(item => supa(item,{token:session.access})));
        if (items.some(item => !item.response.ok || !Array.isArray(item.value))) throw new HttpError(503, 'Mission control is temporarily unavailable.');
        return json({channels:items[0].value,competitors:items[1].value,jobs:items[2].value,workers:items[3].value,paused:items[4].value[0]?.paused === true},200,session.updates);
      }
      const pageMatch = path.match(/^\/api\/cloud\/mission\/jobs-page\/(\d{1,4})$/);
      if (pageMatch && method === 'GET') {
        const offset=Number(pageMatch[1]);
        if (offset > 1950 || offset % 50 !== 0) throw new HttpError(400, 'Invalid job page.');
        const session=await authenticated();
        const {response,value}=await supa(`/rest/v1/vimax_mission_jobs?select=id,channel_id,topic,provider,model,status,review_reason,not_before,attempts,cancel_requested,last_error,created_at,updated_at&order=created_at.desc,id.desc&limit=50&offset=${offset}`,{token:session.access});
        if (!response.ok || !Array.isArray(value)) throw new HttpError(503, 'Job history is temporarily unavailable.');
        return json({jobs:value},200,session.updates);
      }
      if (path === '/api/cloud/mission/channels' && method === 'POST') {
        const session = await authenticated(); const input = channelInput(await body(request));
        const {response,value} = await supa('/rest/v1/vimax_channels?select=id,name,niche,audience,language,timezone,brand_voice,format,created_at,updated_at',
          {method:'POST',token:session.access,data:input,extraHeaders:{prefer:'return=representation'}});
        if (!response.ok || !Array.isArray(value) || !value[0]) throw new HttpError(response.status === 400 ? 409 : 503, 'Could not save the channel profile. Check the 25-profile limit.');
        return json({channel:value[0]},201,session.updates);
      }
      const channelMatch = path.match(/^\/api\/cloud\/mission\/channels\/([0-9a-f-]+)$/i);
      if (channelMatch && ['PATCH','DELETE'].includes(method)) {
        if (!UUID.test(channelMatch[1])) throw new HttpError(400, 'Invalid channel profile.');
        const session = await authenticated(); const data = method === 'PATCH' ? channelInput(await body(request)) : undefined;
        const {response,value} = await supa(`/rest/v1/vimax_channels?id=eq.${channelMatch[1]}&select=id,name,niche,audience,language,timezone,brand_voice,format,created_at,updated_at`,
          {method,token:session.access,data,extraHeaders:{prefer:'return=representation'}});
        if (!response.ok) throw new HttpError(response.status === 409 ? 409 : 503, 'Could not change this profile. Remove its completed jobs first.');
        if (!Array.isArray(value) || !value[0]) throw new HttpError(404, 'Channel profile not found.');
        return json({channel:value[0]},200,session.updates);
      }
      if (path === '/api/cloud/mission/competitors' && method === 'POST') {
        const session = await authenticated(); const input = competitorInput(await body(request));
        const {response,value} = await supa('/rest/v1/vimax_competitors?select=id,channel_id,url,created_at',
          {method:'POST',token:session.access,data:input,extraHeaders:{prefer:'return=representation'}});
        if (!response.ok || !Array.isArray(value) || !value[0]) throw new HttpError(response.status === 409 || response.status === 400 ? 409 : 503, 'Could not save this reference. Check the profile, duplicate URL and 25-reference limit.');
        return json({competitor:value[0]},201,session.updates);
      }
      const competitorMatch = path.match(/^\/api\/cloud\/mission\/competitors\/([0-9a-f-]+)$/i);
      if (competitorMatch && method === 'DELETE') {
        if (!UUID.test(competitorMatch[1])) throw new HttpError(400, 'Invalid reference.');
        const session = await authenticated();
        const {response,value} = await supa(`/rest/v1/vimax_competitors?id=eq.${competitorMatch[1]}&select=id`,{method:'DELETE',token:session.access,extraHeaders:{prefer:'return=representation'}});
        if (!response.ok) throw new HttpError(503, 'Could not remove this reference.');
        if (!Array.isArray(value) || !value[0]) throw new HttpError(404, 'Reference not found.');
        return json({ok:true},200,session.updates);
      }
      if (path === '/api/cloud/mission/jobs' && method === 'POST') {
        const session = await authenticated(); const input = missionJobInput(await body(request));
        const {response,value} = await supa('/rest/v1/rpc/vimax_mission_submit',{method:'POST',token:session.access,data:input});
        if (!response.ok || !value || typeof value.id !== 'string' || !UUID.test(value.id)) {
          if (typeof value?.message === 'string' && value.message.includes('Idempotency key')) throw new HttpError(409, 'This request key was already used for different job details.');
          throw new HttpError(response.status === 400 ? 409 : 503, 'Could not queue this job. Check the profile, start time and storage limits.');
        }
        return json({job:value},value.existing ? 200 : 201,session.updates);
      }
      const detailMatch = path.match(/^\/api\/cloud\/mission\/jobs\/([0-9a-f-]+)$/i);
      if (detailMatch && method === 'GET') {
        if (!UUID.test(detailMatch[1])) throw new HttpError(400, 'Invalid job.');
        const session = await authenticated(); const id = detailMatch[1];
        const paths = [
          `/rest/v1/vimax_mission_jobs?id=eq.${id}&select=id,channel_id,topic,provider,model,status,review_reason,not_before,attempts,cancel_requested,last_error,created_at,updated_at`,
          `/rest/v1/vimax_mission_steps?job_id=eq.${id}&select=stage,status,output,started_at,finished_at&order=started_at.asc`,
          `/rest/v1/vimax_mission_events?job_id=eq.${id}&select=id,event,stage,created_at&order=id.desc&limit=100`,
        ];
        const items=await Promise.all(paths.map(item=>supa(item,{token:session.access})));
        if (items.some(item=>!item.response.ok || !Array.isArray(item.value))) throw new HttpError(503,'Job details are temporarily unavailable.');
        if (!items[0].value[0]) throw new HttpError(404,'Job not found.');
        return json({job:items[0].value[0],steps:items[1].value,events:items[2].value},200,session.updates);
      }
      const actionMatch = path.match(/^\/api\/cloud\/mission\/jobs\/([0-9a-f-]+)\/action$/i);
      if (actionMatch && method === 'POST') {
        if (!UUID.test(actionMatch[1])) throw new HttpError(400, 'Invalid job.');
        const session = await authenticated(); const input = await body(request);
        if (!['cancel','retry','approve','purge'].includes(input.action) || (input.confirm_duplicate_charge !== undefined && typeof input.confirm_duplicate_charge !== 'boolean')) throw new HttpError(422,'Invalid job action.');
        const {response,value}=await supa('/rest/v1/rpc/vimax_mission_action',{method:'POST',token:session.access,
          data:{p_job_id:actionMatch[1],p_action:input.action,p_confirm_duplicate_charge:input.confirm_duplicate_charge === true}});
        if (!response.ok || value?.ok !== true) throw new HttpError(response.status === 400 ? 409 : 503,'Action unavailable. An uncertain retry requires confirmation of possible duplicate charges.');
        return json({result:value},200,session.updates);
      }
      if (path === '/api/cloud/mission/pause' && method === 'POST') {
        const session=await authenticated(); const input=await body(request);
        if (typeof input.paused !== 'boolean') throw new HttpError(422,'Specify whether to pause the queue.');
        const {response,value}=await supa('/rest/v1/rpc/vimax_mission_pause',{method:'POST',token:session.access,data:{p_paused:input.paused}});
        if (!response.ok || value !== input.paused) throw new HttpError(503,'Could not change the queue pause setting.');
        return json({paused:value},200,session.updates);
      }
      if (path === '/api/cloud/projects' && ['GET','POST'].includes(method)) {
        const session = await authenticated();
        if (method === 'GET') {
          const {response, value} = await supa('/rest/v1/vimax_projects?select=id,title,notes,created_at,updated_at&order=created_at.desc&limit=100', {token:session.access});
          if (!response.ok || !Array.isArray(value)) throw new HttpError(503, 'Saved ideas are temporarily unavailable.');
          return json({projects:value}, 200, session.updates);
        }
        const input = projectInput(await body(request));
        const {response, value} = await supa('/rest/v1/vimax_projects?select=id,title,notes,created_at,updated_at',
          {method:'POST',token:session.access,data:input,extraHeaders:{prefer:'return=representation'}});
        if (!response.ok || !Array.isArray(value) || !value[0]) throw new HttpError(400, 'Could not save this idea. Check the 100-project account limit.');
        return json({project:value[0]}, 201, session.updates);
      }
      if (method === 'DELETE' && path.startsWith('/api/cloud/projects/')) {
        const id = path.slice('/api/cloud/projects/'.length);
        if (!UUID.test(id)) throw new HttpError(400, 'Invalid project ID.');
        const session = await authenticated();
        const {response} = await supa(`/rest/v1/vimax_projects?id=eq.${id}`, {method:'DELETE',token:session.access});
        if (!response.ok) throw new HttpError(503, 'Could not delete this idea.');
        return json({ok:true}, 200, session.updates);
      }
      if (method === 'GET' && path === '/api/cloud/providers') {
        const session = await authenticated();
        const preferences = await supa('/rest/v1/vimax_ai_preferences?select=paused&limit=1', {token:session.access});
        if (!preferences.response.ok || !Array.isArray(preferences.value) || preferences.value.length > 1 || (preferences.value.length && typeof preferences.value[0].paused !== 'boolean')) {
          throw new HttpError(503, 'AI safety settings are temporarily unavailable.');
        }
        return json({providers:providerStatus(env), pexels:pexelsStatus(env), allowed:aiAllowed(session), paused:preferences.value[0]?.paused ?? false,
          hackerai:{state:'unsupported', reason:'Its private API endpoint has not been verified for this deployment.'},
          limits:{user_daily_attempts:10, global_daily_attempts:50, history_turns:200}}, 200, session.updates);
      }
      if (method === 'POST' && path === '/api/cloud/ai/pause') {
        const session = await authenticated();
        const input = await body(request);
        if (typeof input.paused !== 'boolean') throw new HttpError(422, 'Choose whether to pause AI calls.');
        const result = await supa('/rest/v1/rpc/vimax_set_ai_paused', {method:'POST', token:session.access, data:{p_paused:input.paused}});
        if (!result.response.ok || result.value !== input.paused) throw new HttpError(503, 'Could not update the AI pause setting.');
        return json({paused:input.paused}, 200, session.updates);
      }
      if (method === 'POST' && path === '/api/cloud/providers/test') {
        const session = await authenticated(); requireAiAccess(session);
        const input = await body(request);
        validateSelection(env, input.provider, input.model);
        const selection = {provider:input.provider, model:input.model};
        const tested = await attempt(session, 'provider_test', selection, () => chatCompletion({env, fetchImpl, id:selection.provider, model:selection.model,
          messages:[{role:'user', content:'Reply with the word OK.'}], maxTokens:16}));
        return json({ok:true, provider:selection.provider, model:selection.model, remaining_user:tested.remaining, audit_saved:tested.auditSaved}, 200, session.updates);
      }
      if (path === '/api/cloud/chat/history' && ['GET', 'DELETE'].includes(method)) {
        const session = await authenticated();
        if (method === 'DELETE') {
          const {response} = await supa('/rest/v1/vimax_chat_turns?id=not.is.null', {method:'DELETE', token:session.access});
          if (!response.ok) throw new HttpError(503, 'Could not delete chat history.');
          return json({ok:true}, 200, session.updates);
        }
        const {response, value} = await supa('/rest/v1/vimax_chat_turns?select=id,prompt,reply,provider,model,created_at&order=created_at.desc,id.desc&limit=30', {token:session.access});
        if (!response.ok || !Array.isArray(value)) throw new HttpError(503, 'Chat history is temporarily unavailable.');
        return json({turns:value}, 200, session.updates);
      }
      if (method === 'GET' && path === '/api/cloud/usage') {
        const session = await authenticated();
        const {response, value} = await supa('/rest/v1/vimax_ai_calls?select=id,feature,provider,model,status,input_tokens,output_tokens,created_at,completed_at&order=created_at.desc&limit=20', {token:session.access});
        if (!response.ok || !Array.isArray(value)) throw new HttpError(503, 'Provider usage history is temporarily unavailable.');
        return json({calls:value}, 200, session.updates);
      }
      if (method === 'POST' && path === '/api/cloud/chat') {
        const session = await authenticated(); requireAiAccess(session);
        const input = chatInput(await body(request));
        validateSelection(env, input.primary.provider, input.primary.model);
        if (input.fallback) validateSelection(env, input.fallback.provider, input.fallback.model);
        const history = await supa('/rest/v1/vimax_chat_turns?select=prompt,reply&order=created_at.desc,id.desc&limit=3', {token:session.access});
        if (!history.response.ok || !Array.isArray(history.value)) throw new HttpError(503, 'Chat history is unavailable. No provider request was sent.');
        const messages = [{role:'system', content:`${SYSTEM_PROMPT} ${MODES[input.mode]}`}];
        for (const turn of history.value.slice(0, 3).reverse()) {
          if (typeof turn?.prompt === 'string' && typeof turn?.reply === 'string') {
            messages.push({role:'user', content:Array.from(turn.prompt).slice(0, 1600).join('')});
            messages.push({role:'assistant', content:Array.from(turn.reply).slice(0, 6000).join('')});
          }
        }
        messages.push({role:'user', content:input.prompt});
        const run = selection => attempt(session, 'chat', selection, () => chatCompletion({env, fetchImpl, id:selection.provider, model:selection.model, messages}));
        let selection = input.primary, completed, usedFallback = false;
        try { completed = await run(selection); }
        catch (error) {
          // Fallback is opt-in, separately budgeted, and only for explicit
          // upstream failures. Ambiguous timeouts are never retried automatically.
          if (!(input.fallback && error instanceof ProviderError && error.retryable && error.auditSaved)) throw error;
          selection = input.fallback; usedFallback = true; completed = await run(selection);
        }
        let saved = false;
        try {
          const stored = await supa('/rest/v1/vimax_chat_turns', {method:'POST', token:session.access,
            data:{prompt:input.prompt, reply:completed.result.text, provider:selection.provider, model:selection.model}, extraHeaders:{prefer:'return=minimal'}});
          saved = stored.response.ok;
        } catch { /* Return the generated text, but disclose that it was not saved. */ }
        return json({reply:completed.result.text, provider:selection.provider, model:selection.model, used_fallback:usedFallback,
          history_saved:saved, audit_saved:completed.auditSaved, remaining_user:completed.remaining,
          usage:{input_tokens:completed.result.inputTokens, output_tokens:completed.result.outputTokens}}, 200, session.updates);
      }
      if (method === 'POST' && path === '/api/cloud/stock-search') {
        const session = await authenticated(); requireAiAccess(session);
        const input = stockInput(await body(request));
        if (pexelsStatus(env) !== 'configured_unverified') throw new HttpError(503, 'Pexels is not configured on this deployment.');
        const result = await attempt(session, 'stock_search', {provider:'pexels', model:''}, () => searchPexels({env, fetchImpl, ...input}));
        return json({videos:result.result, remaining_user:result.remaining, audit_saved:result.auditSaved}, 200, session.updates);
      }
      if (path.startsWith('/api/')) throw new HttpError(503, AGENT_UNAVAILABLE);
      throw new HttpError(404, 'Not found.');
    } catch (error) {
      const status = error instanceof HttpError || error instanceof ProviderError ? error.status : 500;
      return json({error:status === 500 ? 'The request could not be completed.' : error.message}, status, sessionUpdates);
    }
  }
  return {fetch:handler};
}

export default createBridge();
