// Optional, billable managed GPU video previews. Provider calls stay on the
// server; database capabilities are authenticated-encrypted and bound to the
// owner and local job ID. There is deliberately no automatic submit retry.
import {createCipheriv, createDecipheriv, createHash, randomBytes} from 'node:crypto';

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PROVIDER_ID=/^[A-Za-z0-9_-]{1,128}$/;
const BASE='https://api.runpod.ai/v2/p-video';
const MAX_PROVIDER_JSON=64*1024;

export class GpuError extends Error {
  constructor(status,message) {super(message);this.status=status;}
}

function config(env) {
  const ids=typeof env.VIMAX_GPU_ALLOWED_USER_IDS==='string' ? env.VIMAX_GPU_ALLOWED_USER_IDS.split(',').map(x=>x.trim()) : [];
  const key=env.RUNPOD_API_KEY||'', tokenKey=env.VIMAX_GPU_TOKEN_KEY||'';
  if (env.VIMAX_GPU_ENABLED!=='true' || !/^[\x21-\x7e]{8,512}$/.test(key) || !/^[a-f0-9]{64}$/i.test(tokenKey)
      || !ids.length || ids.length>100 || ids.some(x=>!UUID.test(x))) return null;
  return {apiKey:key,key:Buffer.from(tokenKey,'hex'),ids:ids.map(x=>x.toLowerCase())};
}
export function gpuConfigured(env) {return Boolean(config(env));}
function aad(owner,id,kind) {return Buffer.from(`vimax-gpu-v1:${owner.toLowerCase()}:${id.toLowerCase()}:${kind}`);}
export function sealGpu(key,owner,id,kind,value) {
  const iv=randomBytes(12),cipher=createCipheriv('aes-256-gcm',key,iv);
  cipher.setAAD(aad(owner,id,kind));
  const encrypted=Buffer.concat([cipher.update(value,'utf8'),cipher.final()]);
  return ['v1',iv.toString('base64url'),cipher.getAuthTag().toString('base64url'),encrypted.toString('base64url')].join('.');
}
export function unsealGpu(key,owner,id,kind,encoded) {
  try {
    if (typeof encoded!=='string' || encoded.length>4096) return null;
    const parts=encoded.split('.');
    if (parts.length!==4 || parts[0]!=='v1' || parts.slice(1).some(x=>!x || !/^[A-Za-z0-9_-]+$/.test(x))) return null;
    const iv=Buffer.from(parts[1],'base64url'),tag=Buffer.from(parts[2],'base64url'),data=Buffer.from(parts[3],'base64url');
    if (iv.length!==12 || tag.length!==16 || data.length>3000
        || [iv,tag,data].some((part,index)=>part.toString('base64url')!==parts[index+1])) return null;
    const decipher=createDecipheriv('aes-256-gcm',key,iv);
    decipher.setAAD(aad(owner,id,kind));decipher.setAuthTag(tag);
    return Buffer.concat([decipher.update(data),decipher.final()]).toString('utf8');
  } catch {return null;}
}
export function gpuOutputUrl(input) {
  try {
    if (typeof input!=='string' || input.length>2000) return null;
    const u=new URL(input);
    if (u.protocol!=='https:' || u.hostname!=='video.runpod.ai' || u.port || u.username || u.password || u.hash || u.pathname==='/') return null;
    return u.href;
  } catch {return null;}
}
function inputFor(value) {
  const prompt=typeof value.prompt==='string'?value.prompt.trim():'';
  if (typeof value.client_key!=='string' || !UUID.test(value.client_key) || !prompt || Array.from(prompt).length>600
      || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(prompt)
      || !['landscape','shorts'].includes(value.aspect) || value.confirm_cost!==true) {
    throw new GpuError(422,'Enter a prompt (up to 600 characters), choose a format and confirm the estimated paid cost.');
  }
  return {key:value.client_key,prompt,aspect:value.aspect};
}
async function boundedJson(response) {
  const declared=response.headers.get('content-length');
  if (declared && (!/^\d+$/.test(declared) || Number(declared)>MAX_PROVIDER_JSON)) throw new Error('oversized');
  if (!response.body) throw new Error('missing body');
  const reader=response.body.getReader(),parts=[];let size=0;
  while (true) {
    const {done,value}=await reader.read(); if(done)break;
    size+=value.byteLength;
    if(size>MAX_PROVIDER_JSON){await reader.cancel();throw new Error('oversized');}
    parts.push(Buffer.from(value));
  }
  const parsed=JSON.parse(Buffer.concat(parts).toString('utf8'));
  if (!parsed || typeof parsed!=='object' || Array.isArray(parsed)) throw new Error('invalid');
  return parsed;
}

export function createGpu({env,fetchImpl,supa,body,json}) {
  async function rpc(session,name,data={}) {
    const {response,value}=await supa(`/rest/v1/rpc/${name}`,{method:'POST',token:session.access,data});
    if (!response.ok) throw new GpuError(503,'GPU safety database is unavailable. Check the existing job before trying again.');
    return value;
  }
  function requireConfig(session) {
    const cfg=config(env);
    if (!cfg) throw new GpuError(503,'GPU video is not configured. No GPU request was sent.');
    if (!cfg.ids.includes(session.user.id.toLowerCase())) throw new GpuError(403,'GPU video is not enabled for this account.');
    return cfg;
  }
  async function provider(cfg,path,{method='GET',data}={}) {
    return fetchImpl(`${BASE}${path}`,{method,redirect:'error',cache:'no-store',signal:AbortSignal.timeout(15_000),
      headers:{authorization:`Bearer ${cfg.apiKey}`,...(data?{'content-type':'application/json'}:{})},...(data?{body:JSON.stringify(data)}:{})});
  }
  async function finish(session,id,claim,status,output=null,cost=null) {
    const result=await rpc(session,'vimax_gpu_finish',{p_id:id,p_token:claim.token,p_status:status,p_output_cipher:output,p_cost:cost});
    if (!result || typeof result.status!=='string') throw new GpuError(503,'GPU status could not be saved. Check the existing job before trying again.');
    return result;
  }
  async function release(session,id,claim) {
    try {await finish(session,id,claim,claim.status,claim.output_cipher||null,null);} catch { /* lease expires; do not retry submission */ }
  }
  async function process(session,cfg,id,action) {
    const claim=await rpc(session,'vimax_gpu_claim',{p_id:id});
    if (!claim?.allowed) {
      if (claim?.reason==='not_active' && ['starting','uncertain','failed','cancelled','expired'].includes(claim.status)) {
        const message=claim.status==='starting'?'Submission is in progress. Stop is only a request until confirmed.'
          :claim.status==='uncertain'?'The outcome is unknown. Check Runpod before another attempt; it may have incurred charges.'
          :claim.status==='expired'?'Runpod no longer has this job result. It may have generated a video and incurred charges.'
          :'This job is no longer active.';
        return json({id,status:claim.status,cancel_requested:Boolean(claim.cancel_requested),message},200,session.updates);
      }
      throw new GpuError(claim?.reason==='not_found'?404:409,claim?.reason==='busy'?'Another status request is in progress. Check again shortly.':'GPU job is not available for this account.');
    }
    if (!UUID.test(claim.token||'') || !['queued','running','completed'].includes(claim.status)) throw new GpuError(503,'Invalid GPU safety record.');
    const remoteId=unsealGpu(cfg.key,session.user.id,id,'job',claim.provider_cipher);
    if (!PROVIDER_ID.test(remoteId||'')) {await release(session,id,claim);throw new GpuError(409,'The stored GPU job capability is invalid. Check Runpod; no provider request was sent.');}
    if (claim.status==='completed') {
      const url=gpuOutputUrl(unsealGpu(cfg.key,session.user.id,id,'output',claim.output_cipher));
      if (!url) {await release(session,id,claim);throw new GpuError(409,'The saved output link is invalid or unavailable. Check Runpod.');}
      await finish(session,id,claim,'completed',claim.output_cipher,null);
      return json({id,status:'completed',...(action==='output'?{url}:{}),message:'The provider link is temporary and anyone with it can view the video. Save it promptly.'},200,session.updates);
    }
    if (action==='output') {await release(session,id,claim);throw new GpuError(409,'Video is not ready. Check status first.');}
    const stopping=Boolean(claim.cancel_requested);
    let response,result;
    try {
      response=await provider(cfg,`${stopping?'/cancel/':'/status/'}${encodeURIComponent(remoteId)}`,{method:stopping?'POST':'GET'});
      if(response.status===404) {
        const saved=await finish(session,id,claim,stopping?'uncertain':'expired');
        return json({id,status:saved.status,message:'Runpod could not find the job. Its outcome or charges may be unknown; check the provider console.'},200,session.updates);
      }
      if (!response.ok) throw new Error('upstream failure');
      result=await boundedJson(response);
      // Cancellation may race with completion. Obtain the result instead of
      // incorrectly claiming cancellation succeeded.
      if (stopping && result.status==='COMPLETED' && !result.output) {
        response=await provider(cfg,`/status/${encodeURIComponent(remoteId)}`);
        if(!response.ok)throw new Error('status unavailable');
        result=await boundedJson(response);
      }
    } catch {await release(session,id,claim);throw new GpuError(503,'Could not confirm GPU job status. It may still run or incur charges; check again or use the Runpod console.');}
    if (result.status==='COMPLETED') {
      const url=gpuOutputUrl(result.output?.result);
      if(!url) {
        await finish(session,id,claim,'uncertain');
        return json({id,status:'uncertain',message:'Runpod reported completion but its output link was not accepted. Check Runpod before retrying; charges may apply.'},200,session.updates);
      }
      const cost=typeof result.output?.cost==='number' && Number.isFinite(result.output.cost) && result.output.cost>=0 && result.output.cost<=100 ? result.output.cost : null;
      const saved=await finish(session,id,claim,'completed',sealGpu(cfg.key,session.user.id,id,'output',url),cost);
      return json({id,status:saved.status,reported_cost:cost,message:'Completed. Open the temporary provider link and save the video promptly.'},200,session.updates);
    }
    const states={IN_QUEUE:'queued',IN_PROGRESS:'running',CANCELLED:'cancelled',FAILED:'failed',TIMED_OUT:'failed'};
    if (!Object.hasOwn(states,result.status)) {await release(session,id,claim);throw new GpuError(503,'Runpod returned an unrecognized state. Check the existing job before retrying.');}
    const saved=await finish(session,id,claim,states[result.status]);
    return json({id,status:saved.status,cancel_requested:saved.cancel_requested,
      message:saved.status==='cancelled'?'Runpod confirmed cancellation; check the provider for any charges.'
        :saved.cancel_requested?'Stop requested; cancellation is not yet confirmed. Check again.'
        :saved.status==='failed'?'Runpod reported failure. Check the provider for any charges.':undefined},200,session.updates);
  }
  async function start(request,session,cfg) {
    const input=inputFor(await body(request));
    const hash=createHash('sha256').update(JSON.stringify({prompt:input.prompt,aspect:input.aspect,model:'p-video',duration:5,resolution:'720p'})).digest('hex');
    const reserved=await rpc(session,'vimax_gpu_prepare',{p_client_key:input.key,p_prompt:input.prompt,p_aspect:input.aspect,p_request_hash:hash});
    if (reserved?.created===false && UUID.test(reserved.id||'')) return json({id:reserved.id,status:reserved.status,message:'Existing request: no new GPU job was sent.'},200,session.updates);
    if (!reserved?.allowed) {
      const messages={not_allowed:'GPU access is not enabled in the safety database.',active_job:'An existing GPU job is active or has an unknown outcome. Check it first.',user_daily_limit:'The one-attempt-per-account daily limit was reached (UTC).',global_daily_limit:'The three-attempt shared daily limit was reached (UTC).',history_limit:'GPU job history is full; remove an old record.'};
      throw new GpuError(reserved?.reason==='not_allowed'?403:409,messages[reserved?.reason]||'GPU safety limits are unavailable. No GPU request was sent.');
    }
    if (reserved.created!==true || !UUID.test(reserved.id||'') || !UUID.test(reserved.token||'')) throw new GpuError(503,'Invalid GPU safety reservation. No GPU request was sent.');
    const id=reserved.id,token=reserved.token;
    const completeStart=(status,cipher=null)=>rpc(session,'vimax_gpu_finish_start',{p_id:id,p_token:token,p_status:status,p_provider_cipher:cipher});
    if (await rpc(session,'vimax_gpu_start_active',{p_id:id,p_token:token})!==true) {
      await completeStart('cancelled');
      return json({id,status:'cancelled',message:'Stopped before submission; no GPU request was sent.'},200,session.updates);
    }
    let remoteId, outcome='uncertain';
    try {
      const response=await provider(cfg,'/run',{method:'POST',data:{input:{prompt:input.prompt,duration:5,resolution:'720p',
        aspect_ratio:input.aspect==='shorts'?'9:16':'16:9',fps:24,draft:false,save_audio:false,prompt_upsampling:false},
        policy:{executionTimeout:600000,ttl:1200000}}});
      if (!response.ok) {if(response.status>=400 && response.status<500)outcome='failed';throw new Error('submission failed');}
      const result=await boundedJson(response);
      if (!PROVIDER_ID.test(result.id||'')) throw new Error('invalid job id');
      remoteId=result.id;
    } catch {
      const saved=await completeStart(outcome);
      if (!saved) throw new GpuError(503,'GPU submission outcome could not be saved. Check Runpod before retrying; charges may apply.');
      return json({id,status:outcome,message:outcome==='failed'?'Runpod rejected the request. No automatic retry was sent.'
        :'The submission outcome is unknown. Do not retry; check Runpod because a job may have started and charges may apply.'},202,session.updates);
    }
    let saved;
    try {saved=await completeStart('queued',sealGpu(cfg.key,session.user.id,id,'job',remoteId));} catch { /* handled below */ }
    if(!saved) {
      // The ID cannot be durably associated with the owner. Best-effort cancel;
      // the outcome remains unknown even if this request times out.
      try {await provider(cfg,`/cancel/${encodeURIComponent(remoteId)}`,{method:'POST'});} catch { /* do not retry submit */ }
      throw new GpuError(503,'GPU job was submitted but could not be saved. Cancellation was attempted; check Runpod for the outcome and charges.');
    }
    if (saved.cancel_requested) {
      try {return await process(session,cfg,id,'check');} catch {return json({id,status:'queued',cancel_requested:true,message:'Stop requested; cancellation is not yet confirmed. Check the existing job.'},202,session.updates);}
    }
    return json({id,status:'queued',message:'Submitted to Runpod. Generation is billable and may take time.'},202,session.updates);
  }
  async function handle({request,path,method,session}) {
    if (method==='GET' && path==='/api/cloud/gpu/config') {
      const cfg=config(env),serverAllowed=Boolean(cfg?.ids.includes(session.user.id.toLowerCase()));
      let databaseAllowed=false;
      if(serverAllowed) databaseAllowed=(await rpc(session,'vimax_gpu_account_allowed'))===true;
      return json({configured:Boolean(cfg),allowed:serverAllowed && databaseAllowed,provider:'Runpod P-Video',verified:false},200,session.updates);
    }
    if (method==='GET' && path==='/api/cloud/gpu/jobs') {
      const {response,value}=await supa('/rest/v1/vimax_gpu_jobs?select=id,client_key,prompt,aspect,status,reported_cost,cancel_requested,created_at,updated_at&order=created_at.desc&limit=30',{token:session.access});
      if(!response.ok || !Array.isArray(value))throw new GpuError(503,'GPU job history is unavailable.');
      return json({jobs:value},200,session.updates);
    }
    if(method==='POST' && path==='/api/cloud/gpu/jobs')return start(request,session,requireConfig(session));
    const match=path.match(/^\/api\/cloud\/gpu\/jobs\/([0-9a-f-]+)\/(check|cancel|output|forget)$/i);
    if(method!=='POST' || !match || !UUID.test(match[1]))throw new GpuError(404,'GPU operation not found.');
    const [,id,action]=match;
    if(action==='forget') {
      const input=await body(request);
      const removed=await rpc(session,'vimax_gpu_forget',{p_id:id,p_confirm_uncertain:input.confirm_uncertain===true});
      if(removed!==true)throw new GpuError(409,'Only inactive jobs can be removed. Unknown outcomes require explicit confirmation.');
      return json({removed:true,message:'Local record removed. Remote work or links were not cancelled or deleted, and the daily attempt is not restored.'},200,session.updates);
    }
    const cfg=requireConfig(session);
    if(action==='cancel') await rpc(session,'vimax_gpu_request_cancel',{p_id:id});
    return process(session,cfg,id,action);
  }
  return {configured:()=>gpuConfigured(env),handle};
}
