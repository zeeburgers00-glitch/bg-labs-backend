// Public, stateless Supabase account/project API. It never exposes ViMax's
// unauthenticated single-workspace local server to the Internet.
const ACCESS_COOKIE = '__Host-vimax_access';
const REFRESH_COOKIE = '__Host-vimax_refresh';
const MAX_BODY = 8192;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const AGENT_UNAVAILABLE = 'Supabase is connected, but the online ViMax video agent and automatic YouTube upload are not connected yet. Open Skills & Agents to save private ideas.';

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
        ...(data === undefined ? {} : {body:JSON.stringify(data)}), signal:AbortSignal.timeout(12_000), cache:'no-store'});
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
  async function databaseReady() {
    const {response} = await supa('/auth/v1/health');
    if (!response.ok) throw new HttpError(503, 'Supabase is temporarily unavailable.');
  }
  async function handler(request) {
    try {
      const path = pathFor(request), method = request.method.toUpperCase();
      if (!['GET', 'HEAD', 'POST', 'DELETE'].includes(method)) throw new HttpError(405, 'Method not allowed.');
      if (!['GET', 'HEAD'].includes(method) && !sameOrigin(request)) throw new HttpError(403, 'A same-origin request is required.');

      if (method === 'GET' && path === '/api/health') {
        await databaseReady();
        return json({ok:true, database:'connected', video_agent:'unavailable', youtube_upload:'unavailable'});
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
        return json({local_only:false, database_connected:true, ready_for_video:false, piper_installed:false, ffmpeg_installed:false, scene_detection_installed:false,
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
      if (path === '/api/cloud/projects' && ['GET','POST'].includes(method)) {
        const session = await requireUser(request);
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
        const session = await requireUser(request);
        const {response} = await supa(`/rest/v1/vimax_projects?id=eq.${id}`, {method:'DELETE',token:session.access});
        if (!response.ok) throw new HttpError(503, 'Could not delete this idea.');
        return json({ok:true}, 200, session.updates);
      }
      if (path.startsWith('/api/')) throw new HttpError(503, AGENT_UNAVAILABLE);
      throw new HttpError(404, 'Not found.');
    } catch (error) {
      const status = error instanceof HttpError ? error.status : 500;
      return json({error:status === 500 ? 'The request could not be completed.' : error.message}, status);
    }
  }
  return {fetch:handler};
}

export default createBridge();
