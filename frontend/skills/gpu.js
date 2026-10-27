'use strict';
(() => {
  const $=id=>document.getElementById(id);
  const state={loggedIn:false,owner:null,version:0,refreshVersion:0,allowed:false,busy:false,historyReady:false};
  const active=v=>state.loggedIn&&state.version===v;
  const el=(tag,text,cls='')=>{const x=document.createElement(tag);if(text!=null)x.textContent=text;if(cls)x.className=cls;return x;};
  async function api(path,options={}) {
    let response;try{response=await fetch(path,{cache:'no-store',...options});}
    catch{throw new Error('The request was interrupted. Check the existing job and Runpod before another submission; charges may apply.');}
    const type=response.headers.get('content-type')||'';
    if(!type.includes('application/json')&&!type.includes('+json'))throw new Error(`The service returned a non-JSON response (HTTP ${response.status}).`);
    let value;try{value=await response.json();}catch{throw new Error('The service returned invalid JSON.');}
    if(!response.ok)throw new Error(typeof value?.error==='string'?value.error:`Request failed (HTTP ${response.status}).`);
    return value;
  }
  const post=(path,data={})=>api(path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(data)});
  const path=(id,op)=>`/api/cloud/gpu/jobs/${encodeURIComponent(id)}/${op}`;
  const pendingName=()=>`vimax-gpu-pending:${state.owner}`;
  function pending(){try{return state.owner?JSON.parse(sessionStorage.getItem(pendingName())||'null'):null;}catch{return null;}}
  function updateControls(){
    $('gpu-submit').disabled=state.busy||!state.allowed;
    $('gpu-clear-pending').hidden=!pending();$('gpu-clear-pending').disabled=state.busy||!state.historyReady;
    document.querySelectorAll('#gpu-history button[data-busy="yes"]').forEach(b=>{b.disabled=state.busy;});
  }
  const button=(text,fn,allowBusy=false)=>{const b=el('button',text,'small-button');b.type='button';b.dataset.busy=allowBusy?'no':'yes';b.disabled=state.busy&&!allowBusy;b.addEventListener('click',fn);return b;};
  async function refresh(){
    if(!state.loggedIn)return;const v=state.version,seq=++state.refreshVersion;
    const [config,history]=await Promise.allSettled([api('/api/cloud/gpu/config'),api('/api/cloud/gpu/jobs')]);
    if(!active(v)||seq!==state.refreshVersion)return;
    const errors=[];
    if(config.status==='fulfilled'){
      state.allowed=config.value.allowed===true;
      $('gpu-connection').textContent=!config.value.configured?'Not configured. The deployment owner must enable the provider and safety settings privately.'
        :!state.allowed?'GPU service is not enabled for this account.':'Configured but not verified. A real generation may be charged.';
    }else{state.allowed=false;$('gpu-connection').textContent='Could not check GPU configuration.';errors.push(config.reason.message);}
    if(history.status==='fulfilled'){state.historyReady=true;renderHistory(history.value.jobs||[]);}else{state.historyReady=false;errors.push(history.reason.message);}
    if(errors.length)$('gpu-error').textContent=errors.join(' ');
    updateControls();
  }
  function renderHistory(jobs){
    const list=$('gpu-history');list.replaceChildren();
    if(!jobs.length){list.append(el('p','No GPU jobs recorded.','form-note'));return;}
    for(const job of jobs){
      const row=el('div',null,'mission-row'),controls=el('div',null,'mission-controls');
      const created=new Date(job.created_at),when=Number.isNaN(created.getTime())?'':created.toLocaleString();
      row.append(el('strong',job.prompt),el('p',`${job.status}${job.cancel_requested&&!['cancelled','completed','failed','expired'].includes(job.status)?' · stop requested':''} · ${job.aspect} · ${when}${job.reported_cost==null?'':` · provider-reported $${Number(job.reported_cost).toFixed(3)}`}`));
      if(['starting','queued','running'].includes(job.status)){
        controls.append(button('Check status',async()=>{
          const v=state.version;if(state.busy)return;
          try{state.busy=true;updateControls();const result=await post(path(job.id,'check'));if(active(v))$('gpu-notice').textContent=result.message||`Status: ${result.status}.`;}
          catch(error){if(active(v))$('gpu-error').textContent=error.message;}
          finally{if(active(v)){state.busy=false;updateControls();await refresh();}}
        }));
        controls.append(button('Stop job',async()=>{
          if(!confirm('Request cancellation? A job already in flight may still complete or incur charges.'))return;
          const v=state.version;
          try{const result=await post(path(job.id,'cancel'));if(active(v)){$('gpu-notice').textContent=result.message||'Stop requested; check again for confirmation.';await refresh();}}
          catch(error){if(active(v))$('gpu-error').textContent=error.message;}
        },true));
      }
      if(job.status==='completed')controls.append(button('Get temporary video link',async()=>{
        const v=state.version;if(state.busy)return;
        try{
          state.busy=true;updateControls();const result=await post(path(job.id,'output'));if(!active(v))return;
          const url=new URL(result.url);if(url.protocol!=='https:'||url.hostname!=='video.runpod.ai'||url.port||url.username||url.password)throw new Error('The provider returned an unrecognized video link.');
          row.querySelector('a')?.remove();const link=el('a','Open video at Runpod ↗');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';row.append(link);
          $('gpu-notice').textContent=result.message;
        }catch(error){if(active(v))$('gpu-error').textContent=error.message;}
        finally{if(active(v)){state.busy=false;updateControls();}}
      }));
      if(['completed','failed','cancelled','uncertain','expired'].includes(job.status))controls.append(button('Forget record',async()=>{
        const uncertain=['uncertain','expired'].includes(job.status);
        if(!confirm(uncertain?'The outcome may be unknown and the provider may still charge. Check Runpod first. Forget this local record anyway?':'Forget this local record? This does not delete the provider video or restore the daily limit.'))return;
        const v=state.version;try{const result=await post(path(job.id,'forget'),{confirm_uncertain:uncertain});if(active(v)){$('gpu-notice').textContent=result.message;await refresh();}}catch(error){if(active(v))$('gpu-error').textContent=error.message;}
      }));
      row.append(controls);list.append(row);
    }
  }
  $('gpu-refresh').addEventListener('click',()=>refresh().catch(()=>{}));
  $('gpu-clear-pending').addEventListener('click',()=>{
    if(!state.historyReady||!pending())return;
    if(!confirm('A previous request might have reached Runpod. Check your job history and provider console first; a new submission could cause another charge. Clear the pending key anyway?'))return;
    try{sessionStorage.removeItem(pendingName());$('gpu-notice').textContent='Pending key cleared. This did not cancel a provider job or restore the attempt limit.';updateControls();}catch{$('gpu-error').textContent='Could not clear the pending key in this browser.';}
  });
  $('gpu-form').addEventListener('submit',async event=>{
    event.preventDefault();if(state.busy||!state.allowed)return;
    const v=state.version,prompt=$('gpu-prompt').value.trim(),aspect=$('gpu-aspect').value;
    if(!$('gpu-confirm').checked){$('gpu-error').textContent='Confirm the potential provider cost first.';return;}
    try{
      if(!crypto?.randomUUID)throw new Error('A modern browser over HTTPS is required for safe submission.');
      let value=pending();
      if(value && (value.prompt!==prompt||value.aspect!==aspect))throw new Error('A submission is pending. Restore the same prompt and format, or check Runpod before clearing the pending key.');
      if(!value){value={key:crypto.randomUUID(),prompt,aspect};sessionStorage.setItem(pendingName(),JSON.stringify(value));}
      state.busy=true;updateControls();$('gpu-error').textContent='';$('gpu-notice').textContent='Submitting once; do not start another job if the connection is interrupted…';
      const result=await post('/api/cloud/gpu/jobs',{client_key:value.key,prompt,aspect,confirm_cost:true});
      if(!active(v))return;
      sessionStorage.removeItem(pendingName());$('gpu-notice').textContent=result.message||`Status: ${result.status}.`;await refresh();
    }catch(error){if(active(v))$('gpu-error').textContent=error.message;}
    finally{if(active(v)){state.busy=false;updateControls();}}
  });
  window.vimaxGpu={onSession:async user=>{
    const v=++state.version;state.loggedIn=Boolean(user);state.owner=user?.id||null;state.allowed=false;state.busy=false;state.historyReady=false;
    $('gpu').hidden=!user;$('gpu-link').setAttribute('href',user?'#gpu':'#account');$('gpu-prompt').value='';$('gpu-confirm').checked=false;
    $('gpu-error').textContent='';$('gpu-notice').textContent='';$('gpu-history').replaceChildren();
    const saved=pending();
    if(saved && typeof saved.prompt==='string' && saved.prompt.length<=1200 && ['landscape','shorts'].includes(saved.aspect)) {
      $('gpu-prompt').value=saved.prompt;$('gpu-aspect').value=saved.aspect;
      $('gpu-notice').textContent='A previous submission is pending. Check existing job history and Runpod; resubmitting these same details reuses its key.';
    }
    updateControls();if(active(v))await refresh();
  }};
})();
