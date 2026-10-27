// User-initiated YouTube channel authorization and private uploads. Offline
// refresh tokens and resumable URLs are encrypted before database storage;
// access tokens stay in short-lived encrypted, owner-bound HttpOnly cookies.
// No automatic publishing or unattended upload is implemented.
import {createCipheriv, createDecipheriv, createHash, randomBytes, timingSafeEqual} from 'node:crypto';

export class YouTubeError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const U = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CHANNEL = /^UC[A-Za-z0-9_-]{22}$/;
const VIDEO = /^[A-Za-z0-9_-]{11}$/;
const SHA = /^[a-f0-9]{64}$/;
const GOOGLE_TOKEN = /^[A-Za-z0-9._~+/-]{10,2048}={0,2}$/;
const PENDING = '__Host-vimax_yt_pending';
const ACCESS = '__Host-vimax_yt_access';
const SCOPES = ['https://www.googleapis.com/auth/youtube.readonly','https://www.googleapis.com/auth/youtube.upload'];
const ANALYTICS_SCOPE = 'https://www.googleapis.com/auth/yt-analytics.readonly';
const MAX_FILE = 100 * 1024 * 1024;
const CHUNK = 1024 * 1024;
const QUANTUM = 256 * 1024;

function ytCookie(name, value, seconds) {
  if (!/^[A-Za-z0-9_.~-]*$/.test(value) || value.length > 3800) throw new YouTubeError(503,'YouTube authorization data is too large.');
  return `${name}=${value}; Path=/; Max-Age=${seconds}; Secure; HttpOnly; SameSite=Lax`;
}
export function clearYouTubeCookies() { return [ytCookie(PENDING,'',0),ytCookie(ACCESS,'',0)]; }
function cookieValue(request, name) {
  let value = null;
  for (const part of (request.headers.get('cookie') || '').split(';')) {
    const i = part.indexOf('='); if (i < 0 || part.slice(0,i).trim() !== name) continue;
    const candidate = part.slice(i+1).trim();
    if (value !== null || !/^[A-Za-z0-9_.~-]{1,3800}$/.test(candidate)) return null;
    value = candidate;
  }
  return value;
}
function seal(key, purpose, data) {
  const iv=randomBytes(12), cipher=createCipheriv('aes-256-gcm',key,iv);
  cipher.setAAD(Buffer.from(purpose,'utf8'));
  const encrypted=Buffer.concat([cipher.update(JSON.stringify(data),'utf8'),cipher.final()]);
  return `v1.${Buffer.concat([iv,cipher.getAuthTag(),encrypted]).toString('base64url')}`;
}
function unseal(key, purpose, text) {
  if (typeof text !== 'string' || !/^v1\.[A-Za-z0-9_-]{40,4090}$/.test(text)) return null;
  try {
    const encoded=text.slice(3), bytes=Buffer.from(encoded,'base64url');
    if (bytes.length < 29 || bytes.length > 3072 || bytes.toString('base64url')!==encoded) return null;
    const decipher=createDecipheriv('aes-256-gcm',key,bytes.subarray(0,12));
    decipher.setAAD(Buffer.from(purpose,'utf8')); decipher.setAuthTag(bytes.subarray(12,28));
    return JSON.parse(Buffer.concat([decipher.update(bytes.subarray(28)),decipher.final()]).toString('utf8'));
  } catch { return null; }
}
function configuration(env, request) {
  const clientId=env.VIMAX_YOUTUBE_CLIENT_ID || '', secret=env.VIMAX_YOUTUBE_CLIENT_SECRET || '', rawKey=env.VIMAX_YOUTUBE_TOKEN_KEY || '';
  let redirect; try { redirect=new URL(env.VIMAX_YOUTUBE_REDIRECT_URI || ''); } catch { return null; }
  if (!/^[A-Za-z0-9._-]{10,240}\.apps\.googleusercontent\.com$/.test(clientId)
      || secret.length < 8 || secret.length > 512 || /[\s\u0000-\u001f]/.test(secret)
      || !/^[a-f0-9]{64}$/i.test(rawKey) || redirect.protocol !== 'https:' || redirect.username || redirect.password
      || redirect.port || redirect.search || redirect.hash || redirect.pathname !== '/api/cloud/youtube/callback'
      || redirect.origin !== new URL(request.url).origin) return null;
  return {clientId,secret,key:Buffer.from(rawKey,'hex'),redirect:redirect.href};
}
function allowed(env, owner) {
  const value=env.VIMAX_YOUTUBE_ALLOWED_USER_IDS || '';
  if (!value || value.length>4000) return false;
  const ids=value.split(',').map(x=>x.trim());
  return ids.length<=100 && ids.every(id=>U.test(id)) && ids.some(id=>id.toLowerCase()===owner.toLowerCase());
}
function configRequired(env,request,session) {
  const config=configuration(env,request);
  if (!config) throw new YouTubeError(503,'YouTube is not configured on this deployment.');
  if (!allowed(env,session.user.id)) throw new YouTubeError(403,'YouTube access is not enabled for this account.');
  return config;
}
function tokenSession(config,request,owner) {
  const value=unseal(config.key,`youtube-access:${owner}`,cookieValue(request,ACCESS));
  if (!value || value.owner!==owner || !U.test(value.connectionId||'') || !CHANNEL.test(value.channel?.id || '')
      || typeof value.channel?.title!=='string' || !GOOGLE_TOKEN.test(value.token||'')
      || !Number.isFinite(value.expires) || value.expires <= Date.now()+5000) return null;
  return value;
}
function requireToken(config,request,owner) {
  const value=tokenSession(config,request,owner);
  if (!value) throw new YouTubeError(401,'Connect your YouTube channel again. The short-lived authorization may have expired.');
  return value;
}
async function boundedJson(response) {
  const declared=response.headers.get('content-length');
  if (declared && (!/^\d+$/.test(declared) || Number(declared)>65536)) throw new YouTubeError(502,'Google returned an invalid response.');
  const reader=response.body?.getReader(); if (!reader) throw new YouTubeError(502,'Google returned an empty response.');
  const chunks=[]; let size=0;
  while (true) {
    const {done,value}=await reader.read(); if (done) break;
    size+=value.byteLength; if (size>65536) { await reader.cancel(); throw new YouTubeError(502,'Google returned an oversized response.'); }
    chunks.push(value);
  }
  try { return JSON.parse(Buffer.concat(chunks.map(x=>Buffer.from(x))).toString('utf8')); }
  catch { throw new YouTubeError(502,'Google returned an invalid response.'); }
}
async function readChunk(request) {
  if ((request.headers.get('content-type')||'').toLowerCase()!=='application/octet-stream') throw new YouTubeError(415,'Upload chunks must be binary.');
  const declared=request.headers.get('content-length');
  if (declared && (!/^\d+$/.test(declared) || Number(declared)>CHUNK || Number(declared)<1)) throw new YouTubeError(413,'A chunk must be at most 1 MiB.');
  const reader=request.body?.getReader(); if (!reader) throw new YouTubeError(400,'A video chunk is required.');
  const chunks=[]; let size=0;
  while (true) {
    const {done,value}=await reader.read(); if(done) break;
    size+=value.byteLength; if(size>CHUNK) {await reader.cancel(); throw new YouTubeError(413,'A chunk must be at most 1 MiB.');}
    chunks.push(value);
  }
  if (!size || (declared && size!==Number(declared))) throw new YouTubeError(400,'The video chunk was incomplete.');
  return Buffer.concat(chunks.map(x=>Buffer.from(x)));
}
function uploadLocation(value) {
  let u; try {u=new URL(value);} catch {return null;}
  // Restrict the sensitive resumable capability to Google's documented host
  // and endpoint. Never fetch a user-supplied arbitrary URL or follow redirects.
  if (u.protocol!=='https:' || u.hostname!=='www.googleapis.com' || u.port || u.username || u.password || u.hash
      || u.pathname!=='/upload/youtube/v3/videos' || u.href.length>2000
      || u.searchParams.get('uploadType')!=='resumable' || !/^[A-Za-z0-9_-]{1,500}$/.test(u.searchParams.get('upload_id')||'')
      || u.searchParams.getAll('upload_id').length!==1 || u.searchParams.getAll('uploadType').length!==1) return null;
  return u.href;
}
function uploadOffset(response,total) {
  const range=response.headers.get('range');
  if (!range) return 0;
  const m=/^bytes=0-(\d+)$/.exec(range);
  if (!m) throw new YouTubeError(502,'Google returned an invalid upload range.');
  const n=Number(m[1])+1;
  if (!Number.isSafeInteger(n) || n<1 || n>total) throw new YouTubeError(502,'Google returned an invalid upload range.');
  return n;
}
function analyticsRows(data, start, end) {
  const names=['day','views','estimatedMinutesWatched','subscribersGained'];
  if (!Array.isArray(data?.columnHeaders) || data.columnHeaders.length!==names.length
      || data.columnHeaders.some((column,index)=>column?.name!==names[index])) throw new YouTubeError(502,'YouTube returned an unexpected analytics report.');
  const rows=data.rows===undefined ? [] : data.rows;
  if (!Array.isArray(rows) || rows.length>30) throw new YouTubeError(502,'YouTube returned an unexpected analytics report.');
  let previous='';
  return rows.map(row=>{
    const [day,views,minutes,subscribers]=Array.isArray(row)?row:[];
    if (!Array.isArray(row) || row.length!==4 || typeof day!=='string' || !/^\d{4}-\d{2}-\d{2}$/.test(day)
        || !Number.isFinite(Date.parse(`${day}T00:00:00Z`)) || new Date(`${day}T00:00:00Z`).toISOString().slice(0,10)!==day
        || day<start || day>end || day<=previous || !Number.isSafeInteger(views) || views<0 || views>1e12
        || !Number.isFinite(minutes) || minutes<0 || minutes>1e12 || !Number.isSafeInteger(subscribers) || subscribers<0 || subscribers>1e12)
      throw new YouTubeError(502,'YouTube returned an unexpected analytics report.');
    previous=day;
    return {day,views,estimated_minutes_watched:minutes,subscribers_gained:subscribers};
  });
}
function validateStart(input, channel) {
  const title=typeof input.title==='string' ? input.title.trim() : '';
  const description=typeof input.description==='string' ? input.description.trim() : '';
  if (!U.test(input.client_key||'') || !title || Array.from(title).length>100 || Array.from(description).length>5000
      || Buffer.byteLength(description,'utf8')>5000 || /[<>\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(title+description)
      || !Number.isSafeInteger(input.size_bytes) || input.size_bytes<1 || input.size_bytes>MAX_FILE
      || !SHA.test(input.file_sha256||'') || typeof input.made_for_kids!=='boolean' || input.confirm_private!==true) {
    throw new YouTubeError(422,'Check the title, audience, file (maximum 100 MiB) and private-upload confirmation.');
  }
  const digest=createHash('sha256').update(JSON.stringify({channel,title,description,size:input.size_bytes,
    file_sha256:input.file_sha256,made_for_kids:input.made_for_kids,privacy:'private'})).digest('hex');
  return {title,description,size:input.size_bytes,digest,hash:input.file_sha256,key:input.client_key,madeForKids:input.made_for_kids};
}

export function createYouTube({env,fetchImpl,supa,body,json}) {
  async function google(url, init={}, failure='Google could not be reached. The upload outcome may be uncertain; check its status before retrying.') {
    try { return await fetchImpl(url,{...init,signal:AbortSignal.timeout(25_000),redirect:'manual',cache:'no-store'}); }
    catch { throw new YouTubeError(503,failure); }
  }
  async function rpc(session,name,data) {
    const {response,value}=await supa(`/rest/v1/rpc/${name}`,{method:'POST',token:session.access,data});
    if (!response.ok) throw new YouTubeError(503,'The YouTube safety database is unavailable.');
    return value;
  }
  async function databaseAllowed(session) {
    return (await rpc(session,'vimax_youtube_account_allowed',{}))===true;
  }
  async function requireDatabaseAccess(session) {
    if (!await databaseAllowed(session)) throw new YouTubeError(403,'YouTube access is not enabled for this account in the safety database.');
  }
  async function connections(session) {
    const path='/rest/v1/vimax_youtube_connections?select=id,channel_id,channel_title,status,is_default,updated_at&order=updated_at.desc&limit=10';
    const {response,value}=await supa(path,{token:session.access});
    if (!response.ok || !Array.isArray(value)) throw new YouTubeError(503,'Saved YouTube channels are unavailable.');
    return value.filter(x=>U.test(x.id||'') && CHANNEL.test(x.channel_id||'') && typeof x.channel_title==='string'
      && ['active','needs_reauth','uncertain'].includes(x.status)).map(x=>({id:x.id,channel_id:x.channel_id,
      channel_title:x.channel_title,status:x.status,is_default:x.is_default===true,updated_at:x.updated_at}));
  }
  async function requireActiveToken(config,request,session) {
    const auth=requireToken(config,request,session.user.id);
    if (await rpc(session,'vimax_youtube_connection_valid',{p_id:auth.connectionId,p_channel_id:auth.channel.id})!==true)
      throw new YouTubeError(401,'The saved channel was disconnected or needs Google authorization again.');
    return auth;
  }
  function accessCookie(config,owner,id,channel,token,expiresIn,analytics=false) {
    const seconds=Math.min(3600,Math.floor(Number(expiresIn)))-60;
    if (seconds<30 || !U.test(id||'') || !GOOGLE_TOKEN.test(token||'')) throw new YouTubeError(502,'Google returned an incomplete authorization.');
    return ytCookie(ACCESS,seal(config.key,`youtube-access:${owner}`,{owner,connectionId:id,channel,token,analytics:analytics===true,expires:Date.now()+seconds*1000}),seconds);
  }
  async function channelFor(token) {
    const r=await google('https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true&maxResults=2',
      {headers:{authorization:`Bearer ${token}`}});
    if (!r.ok) throw new YouTubeError(502,'Google could not verify the authorized YouTube channel.');
    const data=await boundedJson(r);
    if (!Array.isArray(data.items) || data.items.length!==1 || !CHANNEL.test(data.items[0]?.id||'')
        || typeof data.items[0]?.snippet?.title!=='string') throw new YouTubeError(409,'Select exactly one YouTube channel during Google authorization.');
    const title=Array.from(data.items[0].snippet.title.replace(/[\u0000-\u001f\u007f]/g,' ').trim()).slice(0,150).join('');
    if (!title) throw new YouTubeError(409,'Google did not return a channel name.');
    return {id:data.items[0].id,title};
  }
  async function resumeConnection(session,config,id) {
    if (!U.test(id||'')) throw new YouTubeError(422,'Choose a saved YouTube channel.');
    const claim=await rpc(session,'vimax_youtube_connection_claim',{p_id:id});
    if (!claim?.allowed) {
      if (claim?.reason==='busy') throw new YouTubeError(409,'This channel is already reconnecting. Please try again shortly.');
      if (['needs_reauth','uncertain'].includes(claim?.reason)) throw new YouTubeError(409,'This connection needs Google authorization again.');
      throw new YouTubeError(404,'Saved YouTube channel not found or unavailable.');
    }
    let cipher=claim.refresh_cipher, resolutionAttempted=false;
    async function resolve(status) {
      resolutionAttempted=true;
      if (await rpc(session,'vimax_youtube_connection_finish',{p_id:id,p_lease:claim.lease,p_status:status,p_refresh_cipher:cipher})!==true)
        throw new YouTubeError(503,'The saved connection changed while reconnecting. Check its status before trying again.');
    }
    try {
      const stored=unseal(config.key,`youtube-refresh:${session.user.id}:${claim.channel_id}`,cipher);
      if (!stored || stored.owner!==session.user.id || stored.channelId!==claim.channel_id || !GOOGLE_TOKEN.test(stored.token||'')) {
        await resolve('needs_reauth');
        throw new YouTubeError(409,'The saved authorization could not be opened. Connect this channel with Google again.');
      }
      const response=await google('https://oauth2.googleapis.com/token',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},
        body:new URLSearchParams({grant_type:'refresh_token',refresh_token:stored.token,client_id:config.clientId,client_secret:config.secret})});
      if (!response.ok) {
        let error=null;try {error=await boundedJson(response);}catch{}
        const invalid=response.status===400 && error?.error==='invalid_grant';
        await resolve(invalid?'needs_reauth':'uncertain');
        throw new YouTubeError(invalid?409:503,invalid?'Google authorization expired or was revoked. Connect this channel again.':
          'Google could not confirm this reconnect. Connect this channel again rather than retrying an uncertain refresh.');
      }
      const tokens=await boundedJson(response);
      if (tokens.refresh_token!==undefined && !GOOGLE_TOKEN.test(tokens.refresh_token||''))
        throw new YouTubeError(502,'Google returned an incomplete refresh response.');
      if (!GOOGLE_TOKEN.test(tokens.access_token||'') || !Number.isFinite(Number(tokens.expires_in)) || Number(tokens.expires_in)<90
          || (tokens.token_type!==undefined && String(tokens.token_type).toLowerCase()!=='bearer')
          || (tokens.scope!==undefined && (typeof tokens.scope!=='string' || !SCOPES.every(scope=>tokens.scope.split(/\s+/).includes(scope)))))
        throw new YouTubeError(502,'Google returned an incomplete refresh response.');
      // Old connections have no analytics marker and remain valid for uploads.
      // A scope returned on refresh is authoritative; if omitted, preserve
      // only a previously verified analytics grant in the encrypted record.
      const analytics=tokens.scope===undefined ? stored.analytics===true : tokens.scope.split(/\s+/).includes(ANALYTICS_SCOPE);
      if (tokens.refresh_token!==undefined || stored.analytics!==analytics) {
        cipher=seal(config.key,`youtube-refresh:${session.user.id}:${claim.channel_id}`,
          {owner:session.user.id,channelId:claim.channel_id,token:tokens.refresh_token||stored.token,analytics});
      }
      const channel=await channelFor(tokens.access_token);
      if (channel.id!==claim.channel_id) {
        await resolve('needs_reauth');
        throw new YouTubeError(409,'Google returned a different channel. Connect the intended channel again.');
      }
      const access=accessCookie(config,session.user.id,id,channel,tokens.access_token,tokens.expires_in,analytics);
      await resolve('active');
      return {channel,access};
    } catch (error) {
      // Never replay a refresh after an ambiguous network/parse/verification
      // outcome; a provider may already have rotated its refresh token.
      if (!resolutionAttempted) {
        try {await resolve('uncertain');} catch {}
        throw new YouTubeError(503,'The reconnect outcome could not be confirmed. Connect this channel with Google again.');
      }
      throw error;
    }
  }
  async function verifyVideo(token,id,channel) {
    if (!VIDEO.test(id||'')) return false;
    const url=`https://www.googleapis.com/youtube/v3/videos?part=snippet%2Cstatus&id=${encodeURIComponent(id)}`;
    try {
      const r=await google(url,{headers:{authorization:`Bearer ${token}`}});
      if (!r.ok) return false;
      const data=await boundedJson(r), video=data.items?.[0];
      return Array.isArray(data.items) && data.items.length===1 && video?.id===id
        && video?.snippet?.channelId===channel && video?.status?.privacyStatus==='private';
    } catch { return false; }
  }
  async function finish(session,id,token,status,offset,video=null) {
    const v=await rpc(session,'vimax_youtube_finish_chunk',{p_id:id,p_token:token,p_status:status,p_offset_bytes:offset,p_video_id:video});
    if (!['uploading','uncertain','verifying','completed','failed','cancelled'].includes(v)) throw new YouTubeError(503,'Upload status could not be saved. Check YouTube Studio before retrying.');
    return v;
  }
  async function completedResponse(session,auth,claim,id,videoId) {
    if (!VIDEO.test(videoId||'')) {
      await finish(session,id,claim.token,'uncertain',claim.offset_bytes);
      throw new YouTubeError(503,'YouTube returned an incomplete result. Check upload status before retrying.');
    }
    const verified=await verifyVideo(auth.token,videoId,auth.channel.id);
    const saved=await finish(session,id,claim.token,verified?'completed':'verifying',claim.size_bytes,videoId);
    const message=saved==='cancelled' ? 'Stopped while verifying. A video may exist; check YouTube Studio.' : verified
      ? 'Private upload verified on the selected channel.' : 'YouTube reported a video, but privacy/channel verification is pending. Check status before retrying.';
    return json({id,status:saved,offset_bytes:claim.size_bytes,video_id:videoId,verified:saved==='completed' && verified,message},200,session.updates);
  }
  async function process(request,session,config,id,action) {
    const auth=await requireActiveToken(config,request,session);
    let chunk=null, requestedOffset=null;
    if (action==='chunk') {
      const raw=request.headers.get('x-vimax-offset')||'', hash=request.headers.get('x-vimax-file-sha256')||'';
      if (!/^\d{1,9}$/.test(raw) || !SHA.test(hash)) throw new YouTubeError(422,'Choose the same video file and a valid upload offset.');
      requestedOffset=Number(raw); chunk=await readChunk(request);
      // The full-file digest prevents accidental resumption with a different file.
      if (!Number.isSafeInteger(requestedOffset)) throw new YouTubeError(422,'Invalid upload offset.');
    }
    const claim=await rpc(session,'vimax_youtube_claim',{p_id:id});
    if (!claim?.allowed) {
      const reasons={not_allowed:'YouTube access is no longer enabled in the safety database.',not_found:'Upload not found.',not_active:'This upload is no longer active.',busy:'Another upload request is still running.',session_unknown:'The upload session could not be saved. Check YouTube Studio before starting another.'};
      throw new YouTubeError(claim?.reason==='not_found'?404:409,reasons[claim?.reason]||'Upload cannot be resumed.');
    }
    if (!U.test(claim.token||'') || !Number.isSafeInteger(claim.size_bytes) || !Number.isSafeInteger(claim.offset_bytes)
        || claim.size_bytes<1 || claim.size_bytes>MAX_FILE || claim.offset_bytes<0 || claim.offset_bytes>claim.size_bytes
        || !SHA.test(claim.file_sha256||'') || !CHANNEL.test(claim.channel_id||'')) throw new YouTubeError(503,'Invalid upload safety record.');
    if (auth.channel.id!==claim.channel_id || (action==='chunk' && request.headers.get('x-vimax-file-sha256')!==claim.file_sha256)) {
      await finish(session,id,claim.token,'uncertain',claim.offset_bytes);
      throw new YouTubeError(409,'Reconnect the original channel and select the same video file.');
    }
    if (claim.status==='verifying') return completedResponse(session,auth,claim,id,claim.video_id);
    const stored=unseal(config.key,`youtube-upload:${session.user.id}:${id}`,claim.session_cipher);
    const location=uploadLocation(stored?.url);
    if (!location) {await finish(session,id,claim.token,'uncertain',claim.offset_bytes); throw new YouTubeError(503,'The stored upload session is invalid. Check YouTube Studio.');}
    let current=claim.offset_bytes;
    try {
      // Always reconcile before sending a chunk, including after a timeout.
      const check=await google(location,{method:'PUT',headers:{authorization:`Bearer ${auth.token}`,'content-length':'0','content-range':`bytes */${claim.size_bytes}`},body:new Uint8Array(0)});
      if ([200,201].includes(check.status)) {
        const video=await boundedJson(check);
        return await completedResponse(session,auth,claim,id,video?.id);
      }
      if (check.status!==308) {
        const terminal=check.status===404 || check.status===410;
        await finish(session,id,claim.token,terminal?'failed':'uncertain',current);
        throw new YouTubeError(terminal?409:503,terminal?'The Google upload session expired. Check YouTube Studio before starting again.':'Google could not confirm the upload status. Reconnect or retry the status check.');
      }
      current=uploadOffset(check,claim.size_bytes);
      if (current<claim.offset_bytes) throw new YouTubeError(503,'Google reported an earlier upload position. Check YouTube Studio.');
      if (action==='check' || requestedOffset!==current) {
        const saved=await finish(session,id,claim.token,'uploading',current);
        return json({id,status:saved,offset_bytes:current,size_bytes:claim.size_bytes},200,session.updates);
      }
      if (current>=claim.size_bytes || current+chunk.length>claim.size_bytes
          || (current+chunk.length<claim.size_bytes && chunk.length%QUANTUM!==0)) throw new YouTubeError(422,'Invalid chunk length or position.');
      const active=await rpc(session,'vimax_youtube_lease_active',{p_id:id,p_token:claim.token});
      if (active!==true) {await finish(session,id,claim.token,'uncertain',current); throw new YouTubeError(409,'Upload was stopped before the next chunk.');}
      const response=await google(location,{method:'PUT',headers:{authorization:`Bearer ${auth.token}`,'content-type':'video/mp4',
        'content-length':String(chunk.length),'content-range':`bytes ${current}-${current+chunk.length-1}/${claim.size_bytes}`},body:chunk});
      if ([200,201].includes(response.status)) {
        const video=await boundedJson(response);
        return await completedResponse(session,auth,claim,id,video?.id);
      }
      if (response.status===308) {
        const next=uploadOffset(response,claim.size_bytes);
        if (next<current || next>current+chunk.length) throw new YouTubeError(503,'Google returned an unexpected upload position.');
        const saved=await finish(session,id,claim.token,'uploading',next);
        return json({id,status:saved,offset_bytes:next,size_bytes:claim.size_bytes},200,session.updates);
      }
      const terminal=response.status===404 || response.status===410;
      await finish(session,id,claim.token,terminal?'failed':'uncertain',current);
      throw new YouTubeError(terminal?409:503,terminal?'The upload session expired. Check YouTube Studio before starting again.':'Upload interrupted. Check the existing upload status before retrying.');
    } catch (error) {
      // Finishing twice is harmless: the capability was already consumed. If a
      // request timed out, an uncertain state blocks blind replay; the next
      // explicit resume first asks Google for its committed offset.
      try {await finish(session,id,claim.token,'uncertain',Math.max(claim.offset_bytes,current));} catch {}
      throw error;
    }
  }

  async function handle({request,path,method,session}) {
    const owner=session.user.id;
    if (path==='/api/cloud/youtube/status' && method==='GET') {
      const cfg=configuration(env,request), envPermission=Boolean(cfg&&allowed(env,owner));
      const permission=envPermission && await databaseAllowed(session);
      const saved=await connections(session), candidate=permission ? tokenSession(cfg,request,owner) : null;
      const auth=candidate && saved.some(x=>x.id===candidate.connectionId && x.channel_id===candidate.channel.id && x.status==='active') ? candidate : null;
      return json({configured:Boolean(cfg),allowed:permission,connected:Boolean(auth),channel:auth?.channel||null,
        connection_id:auth?.connectionId||null,saved_channels:saved,
        analytics_configured:Boolean(cfg) && env.VIMAX_YOUTUBE_ANALYTICS_ENABLED==='true',analytics_connected:auth?.analytics===true,
        expires_at:auth?new Date(auth.expires).toISOString():null,privacy:'private',max_file_bytes:MAX_FILE},200,session.updates);
    }
    if (path==='/api/cloud/youtube/oauth/start' && method==='POST') {
      const cfg=configRequired(env,request,session), input=await body(request); await requireDatabaseAccess(session);
      if (input.analytics!==undefined && typeof input.analytics!=='boolean') throw new YouTubeError(422,'Invalid analytics consent request.');
      if (input.analytics===true && env.VIMAX_YOUTUBE_ANALYTICS_ENABLED!=='true') throw new YouTubeError(503,'YouTube Analytics is not enabled on this deployment.');
      const wantsAnalytics=input.analytics===true;
      const state=randomBytes(24).toString('base64url'), verifier=randomBytes(32).toString('base64url');
      const challenge=createHash('sha256').update(verifier).digest('base64url');
      const pending=seal(cfg.key,`youtube-pending:${owner}`,{owner,state,verifier,analytics:wantsAnalytics,expires:Date.now()+600_000});
      const url=new URL('https://accounts.google.com/o/oauth2/v2/auth');
      for (const [k,v] of Object.entries({client_id:cfg.clientId,redirect_uri:cfg.redirect,response_type:'code',scope:[...SCOPES,...(wantsAnalytics?[ANALYTICS_SCOPE]:[])].join(' '),
        access_type:'offline',prompt:'consent select_account',state,code_challenge:challenge,code_challenge_method:'S256'})) url.searchParams.set(k,v);
      return json({authorization_url:url.href},200,[...session.updates,ytCookie(PENDING,pending,600)]);
    }
    if (path==='/api/cloud/youtube/callback' && method==='GET') {
      const cfg=configRequired(env,request,session), params=new URL(request.url).searchParams;
      await requireDatabaseAccess(session);
      const pending=unseal(cfg.key,`youtube-pending:${owner}`,cookieValue(request,PENDING));
      const state=params.get('state')||'', code=params.get('code')||'';
      const a=Buffer.from(state),b=Buffer.from(typeof pending?.state==='string'?pending.state:'');
      if (params.getAll('state').length!==1 || params.getAll('code').length!==1 || !pending || pending.owner!==owner || pending.expires<=Date.now()
          || a.length!==b.length || !a.length || !timingSafeEqual(a,b) || !/^[A-Za-z0-9._~+/-]{8,2048}={0,2}$/.test(code)
          || !/^[A-Za-z0-9_-]{43,128}$/.test(pending.verifier||'')) throw new YouTubeError(400,'YouTube authorization expired or was rejected. Start again.');
      const form=new URLSearchParams({client_id:cfg.clientId,client_secret:cfg.secret,redirect_uri:cfg.redirect,
        grant_type:'authorization_code',code,code_verifier:pending.verifier});
      const r=await google('https://oauth2.googleapis.com/token',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:form.toString()});
      if (!r.ok) throw new YouTubeError(502,'Google did not accept the authorization. Check the OAuth client and redirect URI.');
      const value=await boundedJson(r);
      const scopes=typeof value.scope==='string'?value.scope.split(/\s+/):[];
      if (!GOOGLE_TOKEN.test(value.access_token||'') || String(value.token_type).toLowerCase()!=='bearer'
          || !Number.isFinite(value.expires_in) || value.expires_in<90 || !SCOPES.every(scope=>scopes.includes(scope)))
        throw new YouTubeError(403,'Google did not grant the required upload and channel-read permissions.');
      if (!GOOGLE_TOKEN.test(value.refresh_token||''))
        throw new YouTubeError(409,'Google did not return an offline authorization. Reconnect with consent; you may need to remove the old grant in your Google account first.');
      const channel=await channelFor(value.access_token);
      // Analytics is optional: declining it must not prevent a base channel
      // connection, but no report can be fetched without the separate grant.
      const analytics=pending.analytics===true && scopes.includes(ANALYTICS_SCOPE);
      const refreshCipher=seal(cfg.key,`youtube-refresh:${owner}:${channel.id}`,{owner,channelId:channel.id,token:value.refresh_token,analytics});
      const saved=await rpc(session,'vimax_youtube_connection_save',{p_channel_id:channel.id,p_channel_title:channel.title,p_refresh_cipher:refreshCipher});
      if (!saved?.allowed || !U.test(saved.id||'') || saved.channel_id!==channel.id) {
        const message=saved?.reason==='busy'?'This channel is reconnecting. Wait for it to finish before authorizing again.':
          saved?.reason==='limit'?'You have reached the limit of ten saved YouTube channels. Remove one before connecting another.':'The channel could not be saved.';
        throw new YouTubeError(409,message);
      }
      const access=accessCookie(cfg,owner,saved.id,channel,value.access_token,value.expires_in,analytics);
      const headers=new Headers({'location':'/skills/?youtube=connected#youtube','cache-control':'no-store','referrer-policy':'no-referrer','x-content-type-options':'nosniff'});
      for (const c of [...session.updates,ytCookie(PENDING,'',0),access]) headers.append('set-cookie',c);
      return new Response(null,{status:303,headers});
    }
    if (path==='/api/cloud/youtube/select' && method==='POST') {
      const cfg=configRequired(env,request,session); await requireDatabaseAccess(session);
      const input=await body(request), result=await resumeConnection(session,cfg,input.id);
      return json({connected:true,channel:result.channel,connection_id:input.id},200,[...session.updates,result.access]);
    }
    if (path==='/api/cloud/youtube/analytics' && method==='POST') {
      if (env.VIMAX_YOUTUBE_ANALYTICS_ENABLED!=='true') throw new YouTubeError(503,'YouTube Analytics is not enabled on this deployment.');
      const cfg=configRequired(env,request,session); await body(request); await requireDatabaseAccess(session);
      const auth=await requireActiveToken(cfg,request,session);
      if (auth.analytics!==true) throw new YouTubeError(428,'Reconnect this channel with Google and allow YouTube Analytics access.');
      const reservation=await rpc(session,'vimax_youtube_analytics_reserve',{});
      if (!reservation?.allowed) {
        const msg=reservation?.reason==='user_daily_limit'?'The daily analytics request limit for this account was reached.'
          : reservation?.reason==='global_daily_limit'?'The shared daily analytics request limit was reached.'
          : 'Analytics access is not enabled for this account.';
        throw new YouTubeError(reservation?.reason==='not_allowed'?403:429,msg);
      }
      // Fixed-host, fixed report, owner-bound channel. Missing days are not
      // invented; YouTube can return no rows or delayed data.
      const endTime=Date.now()-86_400_000, startTime=endTime-29*86_400_000;
      const end=new Date(endTime).toISOString().slice(0,10), start=new Date(startTime).toISOString().slice(0,10);
      const url=new URL('https://youtubeanalytics.googleapis.com/v2/reports');
      for (const [key,value] of Object.entries({ids:`channel==${auth.channel.id}`,startDate:start,endDate:end,
        metrics:'views,estimatedMinutesWatched,subscribersGained',dimensions:'day',sort:'day'})) url.searchParams.set(key,value);
      const response=await google(url.href,{headers:{authorization:`Bearer ${auth.token}`}},'YouTube Analytics could not be reached. No report was returned.');
      if (!response.ok) {
        try {await response.body?.cancel();} catch {}
        if (response.status===401 || response.status===403) throw new YouTubeError(403,'YouTube Analytics rejected access. Check Google permission, channel ownership and API setup.');
        if (response.status===429) throw new YouTubeError(429,'YouTube Analytics rate limit or quota was reached.');
        throw new YouTubeError(502,'YouTube Analytics could not return the report.');
      }
      const rows=analyticsRows(await boundedJson(response),start,end);
      return json({channel:auth.channel,requested_start:start,requested_end:end,latest_data:rows.at(-1)?.day||null,
        rows,remaining_user:reservation.remaining_user},200,session.updates);
    }
    if (path==='/api/cloud/youtube/disconnect' && method==='POST') {
      const cfg=configuration(env,request), input=await body(request), auth=cfg?tokenSession(cfg,request,owner):null;
      const id=input.id||auth?.connectionId;
      if (!U.test(id||'')) throw new YouTubeError(422,'Choose the saved channel to disconnect.');
      const removed=await rpc(session,'vimax_youtube_connection_remove',{p_id:id});
      if (!removed?.removed) throw new YouTubeError(removed?.reason==='busy'?409:404,
        removed?.reason==='busy'?'This channel is reconnecting. Wait for it to finish before disconnecting.':'Saved YouTube channel not found.');
      let revoked=false;
      // An expired/uncertain refresh may have rotated remotely. Forgetting is
      // effective locally, but only the user can ensure complete revocation.
      if (cfg && !removed.ambiguous) {
        const stored=unseal(cfg.key,`youtube-refresh:${owner}:${removed.channel_id}`,removed.refresh_cipher);
        if (stored?.owner===owner && stored.channelId===removed.channel_id && GOOGLE_TOKEN.test(stored.token||'')) {
          try {const r=await google('https://oauth2.googleapis.com/revoke',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},
            body:new URLSearchParams({token:stored.token}).toString()}); revoked=r.ok;} catch {}
        }
      }
      const updates=[...session.updates];
      if (!cfg || auth?.connectionId===id) updates.push(ytCookie(ACCESS,'',0));
      return json({disconnected:true,revoked,may_affect_other_channels:revoked},200,updates);
    }
    if (path==='/api/cloud/youtube/uploads' && method==='GET') {
      const {response,value}=await supa('/rest/v1/vimax_youtube_uploads?select=id,client_key,channel_id,title,size_bytes,file_sha256,status,offset_bytes,video_id,cancel_requested,created_at,updated_at&order=created_at.desc&limit=50',{token:session.access});
      if (!response.ok || !Array.isArray(value)) throw new YouTubeError(503,'Upload history is unavailable.');
      return json({uploads:value},200,session.updates);
    }
    if (path==='/api/cloud/youtube/uploads/start' && method==='POST') {
      const cfg=configRequired(env,request,session);
      await requireDatabaseAccess(session);
      const auth=await requireActiveToken(cfg,request,session);
      const input=validateStart(await body(request),auth.channel.id);
      const actual=await channelFor(auth.token);
      if (actual.id!==auth.channel.id) throw new YouTubeError(409,'The authorized channel changed. Connect it again.');
      const reservation=await rpc(session,'vimax_youtube_prepare',{p_client_key:input.key,p_channel_id:auth.channel.id,p_title:input.title,
        p_size_bytes:input.size,p_file_sha256:input.hash,p_request_sha256:input.digest});
      if (reservation?.created===false && U.test(reservation.id||'')) return json({id:reservation.id,status:reservation.status,existing:true},200,session.updates);
      if (!reservation?.allowed || !reservation.created) {
        const reasons={not_allowed:'YouTube access is not enabled for this account in the safety database.',history_limit:'Upload history is full.',active_upload:'Finish or cancel the active upload first.',user_daily_limit:'Your daily private-upload limit was reached.',global_daily_limit:'The shared daily upload limit was reached.'};
        throw new YouTubeError(['user_daily_limit','global_daily_limit'].includes(reservation?.reason)?429:409,reasons[reservation?.reason]||'Upload could not be reserved.');
      }
      if (!U.test(reservation.id||'') || !U.test(reservation.token||'')) throw new YouTubeError(503,'Invalid upload safety reservation.');
      let status='uncertain', encrypted=null;
      try {
        const r=await google('https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet%2Cstatus&notifySubscribers=false',
          {method:'POST',headers:{authorization:`Bearer ${auth.token}`,'content-type':'application/json; charset=UTF-8',
            'x-upload-content-length':String(input.size),'x-upload-content-type':'video/mp4'},
           body:JSON.stringify({snippet:{title:input.title,description:input.description,categoryId:'22'},status:{privacyStatus:'private',selfDeclaredMadeForKids:input.madeForKids}})});
        if (r.status===200) {
          const location=uploadLocation(r.headers.get('location'));
          if (location) {status='uploading'; encrypted=seal(cfg.key,`youtube-upload:${owner}:${reservation.id}`,{url:location});}
        } else if (r.status>=400 && r.status<500) status='failed';
      } catch { /* Outcome is uncertain; never start another automatically. */ }
      const saved=await rpc(session,'vimax_youtube_finish_start',{p_id:reservation.id,p_token:reservation.token,p_status:status,p_session_cipher:encrypted});
      if (!['uploading','uncertain','failed','cancelled'].includes(saved)) throw new YouTubeError(503,'The upload session could not be saved. Check YouTube Studio before retrying.');
      if (saved==='cancelled') return json({id:reservation.id,status:'cancelled',existing:false},200,session.updates);
      if (saved!=='uploading') throw new YouTubeError(saved==='failed'?502:503,'YouTube did not start the upload. Check its status and YouTube Studio before retrying.');
      return json({id:reservation.id,status:'uploading',existing:false},201,session.updates);
    }
    const match=/^\/api\/cloud\/youtube\/uploads\/([0-9a-f-]{36})\/(check|chunk|cancel|forget)$/i.exec(path);
    if (match && method==='POST' && U.test(match[1])) {
      if (match[2]==='cancel') {
        await body(request); const stopped=await rpc(session,'vimax_youtube_cancel',{p_id:match[1]});
        if (stopped!==true) throw new YouTubeError(409,'Upload cannot be stopped.');
        return json({stopped:true,message:'No new chunks will start. A chunk already in flight may still complete.'},200,session.updates);
      }
      if (match[2]==='forget') {
        await body(request); const deleted=await rpc(session,'vimax_youtube_forget',{p_id:match[1]});
        if (deleted!==true) throw new YouTubeError(409,'Only completed, failed or stopped records can be forgotten.');
        return json({forgotten:true,message:'The ViMax record was removed. No video was deleted from YouTube.'},200,session.updates);
      }
      const cfg=configRequired(env,request,session);
      if (match[2]==='check') await body(request);
      return process(request,session,cfg,match[1],match[2]);
    }
    throw new YouTubeError(404,'YouTube route not found.');
  }
  return {handle,configured:request=>Boolean(configuration(env,request))};
}
