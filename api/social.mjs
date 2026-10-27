// Optional, consent-based TikTok profile and Facebook Page connections.
// This module does not publish or provide unattended media processing.
import {createCipheriv,createDecipheriv,randomBytes,timingSafeEqual} from 'node:crypto';

export class SocialError extends Error {constructor(status,message){super(message);this.status=status;}}
const U=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const TOKEN=/^[\x21-\x7e]{10,4096}$/;
const GRAPH='https://graph.facebook.com/v26.0';
const pendingName=p=>`__Host-vimax_${p}_pending`;
const cookie=(name,value,age)=>{
  if(!/^[A-Za-z0-9_.~-]*$/.test(value)||value.length>3800)throw new SocialError(503,'Authorization data is too large.');
  return `${name}=${value}; Path=/; Max-Age=${age}; Secure; HttpOnly; SameSite=Lax`;
};
export const clearSocialCookies=()=>['tiktok','facebook'].map(p=>cookie(pendingName(p),'',0));
function readCookie(request,name){
  let result=null;
  for(const part of (request.headers.get('cookie')||'').split(';')){
    const i=part.indexOf('=');if(i<0||part.slice(0,i).trim()!==name)continue;
    const value=part.slice(i+1).trim();if(result!==null||!/^[A-Za-z0-9_.~-]{1,3800}$/.test(value))return null;result=value;
  }return result;
}
function seal(key,purpose,value){
  const iv=randomBytes(12),c=createCipheriv('aes-256-gcm',key,iv);c.setAAD(Buffer.from(purpose));
  const encrypted=Buffer.concat([c.update(JSON.stringify(value)),c.final()]);
  return 'v1.'+Buffer.concat([iv,c.getAuthTag(),encrypted]).toString('base64url');
}
function unseal(key,purpose,value){
  if(typeof value!=='string'||!/^v1\.[A-Za-z0-9_-]{40,11997}$/.test(value))return null;
  try{const encoded=value.slice(3),bytes=Buffer.from(encoded,'base64url');
    if(bytes.length<29||bytes.length>9000||bytes.toString('base64url')!==encoded)return null;
    const d=createDecipheriv('aes-256-gcm',key,bytes.subarray(0,12));d.setAAD(Buffer.from(purpose));d.setAuthTag(bytes.subarray(12,28));
    return JSON.parse(Buffer.concat([d.update(bytes.subarray(28)),d.final()]).toString('utf8'));
  }catch{return null;}
}
function configuration(env,request,provider){
  const prefix=provider==='tiktok'?'VIMAX_TIKTOK_':'VIMAX_FACEBOOK_';
  const client=env[prefix+(provider==='tiktok'?'CLIENT_KEY':'APP_ID')]||'',secret=env[prefix+(provider==='tiktok'?'CLIENT_SECRET':'APP_SECRET')]||'';
  const raw=env.VIMAX_SOCIAL_TOKEN_KEY||'';let redirect;
  try{redirect=new URL(env[prefix+'REDIRECT_URI']||'');}catch{return null;}
  if((provider==='tiktok'?!/^[A-Za-z0-9_-]{8,128}$/.test(client):!/^[0-9]{5,32}$/.test(client))
    ||secret.length<8||secret.length>512||/[\s\u0000-\u001f]/.test(secret)||!/^[a-f0-9]{64}$/i.test(raw)
    ||redirect.protocol!=='https:'||redirect.username||redirect.password||redirect.port||redirect.search||redirect.hash
    ||redirect.pathname!==`/api/cloud/social/${provider}/callback`||redirect.origin!==new URL(request.url).origin)return null;
  return {client,secret,key:Buffer.from(raw,'hex'),redirect:redirect.href};
}
function allowed(env,owner){
  const raw=env.VIMAX_SOCIAL_ALLOWED_USER_IDS||'';if(!raw||raw.length>4000)return false;
  const ids=raw.split(',').map(x=>x.trim());return ids.length<=100&&ids.every(x=>U.test(x))&&ids.some(x=>x.toLowerCase()===owner.toLowerCase());
}
function required(env,request,session,provider){
  const cfg=configuration(env,request,provider);if(!cfg)throw new SocialError(503,`${provider==='tiktok'?'TikTok':'Facebook'} is not configured on this deployment.`);
  if(!allowed(env,session.user.id))throw new SocialError(403,'Social connections are not enabled for this account.');return cfg;
}
const validId=(provider,id)=>provider==='tiktok'?/^[A-Za-z0-9_-]{1,160}$/.test(id||''):/^[0-9]{1,32}$/.test(id||'');
function cleanName(name){
  if(typeof name!=='string')return '';
  return Array.from(name.replace(/[\u0000-\u001f\u007f]/g,' ').trim()).slice(0,150).join('');
}
async function bounded(response){
  const declared=response.headers.get('content-length');if(declared&&(!/^\d+$/.test(declared)||Number(declared)>65536))throw new SocialError(502,'The provider returned an invalid response.');
  const reader=response.body?.getReader();if(!reader)throw new SocialError(502,'The provider returned an empty response.');
  const chunks=[];let size=0;while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;
    if(size>65536){await reader.cancel();throw new SocialError(502,'The provider returned an oversized response.');}chunks.push(Buffer.from(value));}
  try{return JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{throw new SocialError(502,'The provider returned invalid JSON.');}
}
function credentialPurpose(owner,provider,id){return `social-credential:${owner}:${provider}:${id}`;}

export function createSocial({env,fetchImpl,supa,body,json}){
  async function providerFetch(url,init={}){
    try{return await fetchImpl(url,{...init,signal:AbortSignal.timeout(25_000),redirect:'manual',cache:'no-store'});}
    catch{throw new SocialError(503,'The provider could not be reached.');}
  }
  async function rpc(session,name,data){
    const {response,value}=await supa(`/rest/v1/rpc/${name}`,{method:'POST',token:session.access,data});
    if(!response.ok)throw new SocialError(503,'The social connection database is unavailable.');return value;
  }
  async function checkAllowed(session,provider){
    if(await rpc(session,'vimax_social_account_allowed',{p_provider:provider})!==true)throw new SocialError(403,'This provider is not enabled for this account.');
  }
  async function list(session){
    const path='/rest/v1/vimax_social_connections?select=id,provider,external_id,display_name,status,is_default,verified_at,updated_at&order=updated_at.desc&limit=20';
    const {response,value}=await supa(path,{token:session.access});
    if(!response.ok||!Array.isArray(value))throw new SocialError(503,'Saved social connections are unavailable.');
    return value.filter(x=>['tiktok','facebook'].includes(x.provider)&&U.test(x.id||'')&&validId(x.provider,x.external_id)
      &&typeof x.display_name==='string'&&['active','needs_reauth','uncertain'].includes(x.status)).map(x=>({id:x.id,provider:x.provider,
      external_id:x.external_id,display_name:x.display_name,status:x.status,is_default:x.is_default===true,verified_at:x.verified_at}));
  }
  async function tiktokToken(cfg,fields){
    return providerFetch('https://open.tiktokapis.com/v2/oauth/token/',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded','cache-control':'no-cache'},
      body:new URLSearchParams({client_key:cfg.client,client_secret:cfg.secret,...fields}).toString()});
  }
  function validateTikTokens(value,requireScope=true){
    if(!TOKEN.test(value.access_token||'')||!TOKEN.test(value.refresh_token||'')||!validId('tiktok',value.open_id)
      ||String(value.token_type).toLowerCase()!=='bearer'||!Number.isFinite(value.expires_in)||value.expires_in<60
      ||!Number.isFinite(value.refresh_expires_in)||value.refresh_expires_in<60
      ||(requireScope&&(typeof value.scope!=='string'||!value.scope.split(',').includes('user.info.basic'))))
      throw new SocialError(502,'TikTok returned an incomplete authorization.');
  }
  async function tiktokProfile(token){
    const r=await providerFetch('https://open.tiktokapis.com/v2/user/info/?fields=open_id%2Cdisplay_name',{headers:{authorization:`Bearer ${token}`}});
    const value=await bounded(r);if(!r.ok||value.error?.code&&value.error.code!=='ok'){
      if(r.status===401||r.status===403||value.error?.code==='access_token_invalid')throw new SocialError(401,'TikTok authorization is no longer valid.');
      throw new SocialError(503,'TikTok could not verify the profile.');
    }
    const u=value.data?.user,name=cleanName(u?.display_name);
    if(!validId('tiktok',u?.open_id)||!name)throw new SocialError(502,'TikTok did not return a valid profile.');
    return {id:u.open_id,name};
  }
  async function graphToken(fields){
    // Meta documents GET for token exchanges; only this fixed server-side URL
    // is used, with no request logging and redirects disabled.
    const url=new URL(`${GRAPH}/oauth/access_token`);for(const [k,v] of Object.entries(fields))url.searchParams.set(k,v);
    const r=await providerFetch(url.href),value=await bounded(r);
    if(!r.ok||value.error||!TOKEN.test(value.access_token||''))throw new SocialError(502,'Facebook did not accept the authorization.');return value;
  }
  async function facebookPages(userToken){
    const url=new URL(`${GRAPH}/me/accounts`);url.searchParams.set('fields','id,name,access_token');url.searchParams.set('limit','11');
    const r=await providerFetch(url.href,{headers:{authorization:`Bearer ${userToken}`}}), value=await bounded(r);
    if(!r.ok||value.error){
      if(value.error?.code===190||r.status===401)throw new SocialError(401,'Facebook authorization expired or was revoked.');
      throw new SocialError(503,'Facebook could not list the authorized Pages.');
    }
    if(!Array.isArray(value.data)||value.data.length===0)throw new SocialError(409,'Facebook returned no authorized Pages. Choose a Page in Facebook and check the app permissions.');
    if(value.data.length>10||value.paging?.next)throw new SocialError(409,'More than ten Pages were returned. Choose no more than ten Pages in Facebook and try again.');
    const pages=value.data.map(page=>({id:page.id,name:cleanName(page.name),token:page.access_token}));
    if(pages.some(p=>!validId('facebook',p.id)||!p.name||!TOKEN.test(p.token||''))||new Set(pages.map(p=>p.id)).size!==pages.length)
      throw new SocialError(502,'Facebook returned incomplete Page information.');
    return pages;
  }
  async function save(session,cfg,provider,items){
    const encrypted=items.map(item=>({external_id:item.id,display_name:item.name,
      credential_cipher:seal(cfg.key,credentialPurpose(session.user.id,provider,item.id),{owner:session.user.id,provider,externalId:item.id,...item.credential})}));
    const result=await rpc(session,'vimax_social_connection_save',{p_provider:provider,p_items:encrypted});
    if(!result?.allowed){const msg=result?.reason==='limit'?'You have reached the limit of ten saved connections for this provider.':result?.reason==='busy'?'A connection is currently being restored. Try again shortly.':'The connections could not be saved.';throw new SocialError(409,msg);}
    return result.connections;
  }
  async function callback(session,cfg,provider,code){
    if(provider==='tiktok'){
      const r=await tiktokToken(cfg,{grant_type:'authorization_code',code,redirect_uri:cfg.redirect});
      if(!r.ok)throw new SocialError(502,'TikTok did not accept the authorization. Check the app and callback configuration.');
      const value=await bounded(r);validateTikTokens(value);
      const profile=await tiktokProfile(value.access_token);if(profile.id!==value.open_id)throw new SocialError(409,'TikTok returned a different profile.');
      return save(session,cfg,provider,[{id:profile.id,name:profile.name,credential:{accessToken:value.access_token,refreshToken:value.refresh_token,
        accessExpires:Date.now()+value.expires_in*1000,refreshExpires:Date.now()+value.refresh_expires_in*1000}}]);
    }
    const first=await graphToken({client_id:cfg.client,client_secret:cfg.secret,redirect_uri:cfg.redirect,code});
    const long=await graphToken({grant_type:'fb_exchange_token',client_id:cfg.client,client_secret:cfg.secret,fb_exchange_token:first.access_token});
    if(!Number.isFinite(long.expires_in)||long.expires_in<60)throw new SocialError(502,'Facebook did not return a long-lived user authorization.');
    const pages=await facebookPages(long.access_token);
    return save(session,cfg,provider,pages.map(p=>({id:p.id,name:p.name,credential:{userToken:long.access_token,pageToken:p.token,
      userExpires:Date.now()+long.expires_in*1000}})));
  }
  async function restore(session,cfg,provider,id){
    if(!U.test(id||''))throw new SocialError(422,'Choose a saved connection.');
    const claim=await rpc(session,'vimax_social_connection_claim',{p_provider:provider,p_id:id});
    if(!claim?.allowed){
      if(claim?.reason==='busy')throw new SocialError(409,'This connection is already being restored. Try again shortly.');
      if(['uncertain','needs_reauth'].includes(claim?.reason))throw new SocialError(409,'This connection needs authorization again.');
      throw new SocialError(404,'Saved connection not found or unavailable.');
    }
    let cipher=claim.credential_cipher,resolutionAttempted=false,refreshMayHaveRotated=false;
    async function resolve(status,verified){
      resolutionAttempted=true;
      if(await rpc(session,'vimax_social_connection_finish',{p_provider:provider,p_id:id,p_lease:claim.lease,p_status:status,p_cipher:cipher,p_verified:verified})!==true)
        throw new SocialError(503,'The connection changed while it was being restored.');
    }
    try{
      const purpose=credentialPurpose(session.user.id,provider,claim.external_id),stored=unseal(cfg.key,purpose,cipher);
      if(!stored||stored.owner!==session.user.id||stored.provider!==provider||stored.externalId!==claim.external_id){
        await resolve('needs_reauth',false);throw new SocialError(409,'The saved authorization could not be opened. Connect again.');
      }
      let name;
      if(provider==='tiktok'){
        if(!TOKEN.test(stored.accessToken||'')||!TOKEN.test(stored.refreshToken||'')||!Number.isFinite(stored.accessExpires)||!Number.isFinite(stored.refreshExpires)){
          await resolve('needs_reauth',false);throw new SocialError(409,'The saved TikTok authorization is invalid. Connect again.');
        }
        if(stored.accessExpires<=Date.now()+60_000){
          if(stored.refreshExpires<=Date.now()+60_000){await resolve('needs_reauth',false);throw new SocialError(409,'TikTok authorization expired. Connect again.');}
          refreshMayHaveRotated=true;
          const r=await tiktokToken(cfg,{grant_type:'refresh_token',refresh_token:stored.refreshToken});
          if(!r.ok){let value=null;try{value=await bounded(r);}catch{}
            const invalid=r.status===400&&value?.error==='invalid_grant';await resolve(invalid?'needs_reauth':'uncertain',false);
            throw new SocialError(invalid?409:503,invalid?'TikTok authorization expired or was revoked. Connect again.':'TikTok refresh could not be confirmed. Connect again.');}
          const value=await bounded(r);validateTikTokens(value,false);
          if(value.open_id!==claim.external_id){await resolve('needs_reauth',false);throw new SocialError(409,'TikTok returned a different profile.');}
          Object.assign(stored,{accessToken:value.access_token,refreshToken:value.refresh_token,accessExpires:Date.now()+value.expires_in*1000,
            refreshExpires:Date.now()+value.refresh_expires_in*1000});
          cipher=seal(cfg.key,purpose,stored);
        }
        const profile=await tiktokProfile(stored.accessToken);
        if(profile.id!==claim.external_id){await resolve('needs_reauth',false);throw new SocialError(409,'TikTok returned a different profile.');}
        name=profile.name;
      }else{
        if(!TOKEN.test(stored.userToken||'')||!TOKEN.test(stored.pageToken||'')||!Number.isFinite(stored.userExpires)||stored.userExpires<=Date.now()+60_000){
          await resolve('needs_reauth',false);throw new SocialError(409,'Facebook authorization expired. Connect again.');}
        const pages=await facebookPages(stored.userToken),page=pages.find(p=>p.id===claim.external_id);
        if(!page){await resolve('needs_reauth',false);throw new SocialError(409,'That Page is no longer authorized. Connect again.');}
        stored.pageToken=page.token;cipher=seal(cfg.key,purpose,stored);name=page.name;
      }
      await resolve('active',true);return {id,provider,external_id:claim.external_id,display_name:name};
    }catch(error){
      if(!resolutionAttempted){
        const invalid=error instanceof SocialError&&error.status===401;
        try{await resolve(invalid?'needs_reauth':refreshMayHaveRotated?'uncertain':'active',false);}catch{}
        if(invalid)throw new SocialError(409,'The provider authorization expired or was revoked. Connect again.');
        if(refreshMayHaveRotated)throw new SocialError(503,'The refresh outcome could not be confirmed. Connect again.');
      }throw error;
    }
  }
  async function handle({request,path,method,session}){
    const owner=session.user.id;
    if(path==='/api/cloud/social/status'&&method==='GET'){
      const connections=await list(session),providers={};
      for(const provider of ['tiktok','facebook']){
        const cfg=configuration(env,request,provider),envAllowed=Boolean(cfg&&allowed(env,owner));
        providers[provider]={configured:Boolean(cfg),allowed:envAllowed&&await rpc(session,'vimax_social_account_allowed',{p_provider:provider})===true};
      }
      return json({providers,connections},200,session.updates);
    }
    const match=/^\/api\/cloud\/social\/(tiktok|facebook)\/(start|callback|select|disconnect)$/.exec(path);
    if(!match)throw new SocialError(404,'Social connection route not found.');
    const [,provider,action]=match;
    if(action==='start'&&method==='POST'){
      const cfg=required(env,request,session,provider);await body(request);await checkAllowed(session,provider);
      const state=randomBytes(24).toString('base64url'),pending=seal(cfg.key,`social-pending:${provider}:${owner}`,{owner,state,expires:Date.now()+600_000});
      const url=new URL(provider==='tiktok'?'https://www.tiktok.com/v2/auth/authorize/':'https://www.facebook.com/v26.0/dialog/oauth');
      const params=provider==='tiktok'?{client_key:cfg.client,scope:'user.info.basic',response_type:'code',redirect_uri:cfg.redirect,state}:
        {client_id:cfg.client,scope:'pages_show_list',response_type:'code',redirect_uri:cfg.redirect,state};
      for(const [k,v] of Object.entries(params))url.searchParams.set(k,v);
      return json({authorization_url:url.href},200,[...session.updates,cookie(pendingName(provider),pending,600)]);
    }
    if(action==='callback'&&method==='GET'){
      const cfg=required(env,request,session,provider);await checkAllowed(session,provider);
      const params=new URL(request.url).searchParams,pending=unseal(cfg.key,`social-pending:${provider}:${owner}`,readCookie(request,pendingName(provider)));
      const state=params.get('state')||'',code=params.get('code')||'',a=Buffer.from(state),b=Buffer.from(typeof pending?.state==='string'?pending.state:'');
      if(params.getAll('state').length!==1||params.getAll('code').length!==1||!pending||pending.owner!==owner||pending.expires<=Date.now()
        ||!a.length||a.length!==b.length||!timingSafeEqual(a,b)||!/^[A-Za-z0-9._~+/-]{8,2048}={0,2}$/.test(code))
        throw new SocialError(400,'The authorization expired or was rejected. Start again.');
      await callback(session,cfg,provider,code);
      const headers=new Headers({location:'/skills/?social=connected#social-connections','cache-control':'no-store','referrer-policy':'no-referrer','x-content-type-options':'nosniff'});
      for(const c of [...session.updates,cookie(pendingName(provider),'',0)])headers.append('set-cookie',c);
      return new Response(null,{status:303,headers});
    }
    if(action==='select'&&method==='POST'){
      const cfg=required(env,request,session,provider);await checkAllowed(session,provider);const input=await body(request);
      return json({connection:await restore(session,cfg,provider,input.id)},200,session.updates);
    }
    if(action==='disconnect'&&method==='POST'){
      const input=await body(request);if(!U.test(input.id||''))throw new SocialError(422,'Choose a saved connection.');
      const removed=await rpc(session,'vimax_social_connection_remove',{p_provider:provider,p_id:input.id});
      if(!removed?.removed)throw new SocialError(removed?.reason==='busy'?409:404,removed?.reason==='busy'?'This connection is being restored. Try again shortly.':'Saved connection not found.');
      let revoked=false;const cfg=configuration(env,request,provider);
      if(provider==='tiktok'&&cfg&&!removed.ambiguous){
        const stored=unseal(cfg.key,credentialPurpose(owner,provider,removed.external_id),removed.credential_cipher);
        if(stored?.owner===owner&&stored.provider===provider&&stored.externalId===removed.external_id&&TOKEN.test(stored.accessToken||'')){
          try{const r=await providerFetch('https://open.tiktokapis.com/v2/oauth/revoke/',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},
            body:new URLSearchParams({client_key:cfg.client,client_secret:cfg.secret,token:stored.accessToken}).toString()});
            if(r.ok){
              const length=r.headers.get('content-length');
              if(!length||(/^\d+$/.test(length)&&Number(length)<=4096)){
                const reader=r.body?.getReader();let text='',size=0,tooLarge=false;
                if(reader)while(true){const part=await reader.read();if(part.done)break;size+=part.value.byteLength;
                  if(size>4096){tooLarge=true;await reader.cancel();break;}text+=Buffer.from(part.value).toString('utf8');}
                revoked=!tooLarge&&(!text||text.trim()==='{}');
              }
            }}catch{}
        }
      }
      // Facebook app-level revocation affects every Page in a grant; do not
      // silently revoke other Pages. The user can remove the app in Facebook.
      return json({disconnected:true,revoked},200,session.updates);
    }
    throw new SocialError(404,'Social connection route not found.');
  }
  return {handle};
}
