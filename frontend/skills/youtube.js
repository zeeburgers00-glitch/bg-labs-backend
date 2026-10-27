'use strict';
(() => {
  const $=id=>document.getElementById(id), chunkSize=1024*1024;
  const state={loggedIn:false,owner:null,version:0,refreshVersion:0,connected:false,channel:null,busy:false,abort:null,
    resumeAbort:null,autoAttempted:false,savedChannels:[],historyReady:false};
  const active=version=>state.loggedIn && state.version===version;
  const el=(tag,text,cls='')=>{const x=document.createElement(tag);if(text!=null)x.textContent=text;if(cls)x.className=cls;return x;};
  async function api(path,options={}) {
    let response;
    try {response=await fetch(path,{cache:'no-store',...options,headers:{...(options.headers||{})}});}
    catch (error) {if(error?.name==='AbortError')throw error;throw new Error('The request was interrupted. Check the existing upload status and YouTube Studio before trying again.');}
    const type=response.headers.get('content-type')||'';
    if (!type.includes('application/json') && !type.includes('+json')) throw new Error(`The service returned a non-JSON response (HTTP ${response.status}).`);
    let value;try{value=await response.json();}catch{throw new Error('The service returned invalid JSON.');}
    if(!response.ok) throw new Error(typeof value?.error==='string'?value.error:`Request failed (HTTP ${response.status}).`);
    return value;
  }
  const post=(path,data={})=>api(path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(data)});
  const button=(label,fn,allowBusy=false)=>{const b=el('button',label,'small-button');b.type='button';b.dataset.pauseDuringBusy=allowBusy?'no':'yes';b.disabled=state.busy&&!allowBusy;b.addEventListener('click',fn);return b;};
  const pendingName=()=>`vimax-yt-pending:${state.owner}`;
  function hasPending(){try{return Boolean(state.owner&&sessionStorage.getItem(pendingName()));}catch{return false;}}
  const path=(id,operation)=>`/api/cloud/youtube/uploads/${encodeURIComponent(id)}/${operation}`;
  function busy(value) {
    state.busy=value;
    $('yt-upload').disabled=value||!state.connected;
    $('yt-connect').disabled=value||$('yt-connect').dataset.allowed!=='yes';
    const selected=state.savedChannels.find(x=>x.id===$('yt-saved-channels').value);
    $('yt-saved-channels').disabled=value||!state.savedChannels.length;
    $('yt-select-channel').disabled=value||$('yt-connect').dataset.allowed!=='yes'||!selected||selected.status!=='active';
    $('yt-disconnect').disabled=value||!selected;
    $('yt-clear-pending').hidden=!hasPending();
    $('yt-clear-pending').disabled=value||!state.historyReady;
    document.querySelectorAll('#yt-history button[data-pause-during-busy="yes"]').forEach(b=>{b.disabled=value;});
  }
  async function refresh() {
    if(!state.loggedIn)return; const v=state.version,seq=++state.refreshVersion;
    const [statusResult,historyResult]=await Promise.allSettled([api('/api/cloud/youtube/status'),api('/api/cloud/youtube/uploads')]);
    if(!active(v)||seq!==state.refreshVersion)return;
    const errors=[];let autoId=null;
    if(statusResult.status==='fulfilled') {
      const status=statusResult.value, select=$('yt-saved-channels'), previous=select.value;
      state.connected=status.connected===true;state.channel=status.channel;
      state.savedChannels=Array.isArray(status.saved_channels)?status.saved_channels:[];
      select.replaceChildren();
      if(!state.savedChannels.length){const opt=el('option','No saved channels');opt.value='';select.append(opt);}
      for(const saved of state.savedChannels){
        const suffix=saved.status==='active'?'':saved.status==='uncertain'?' — reconnect required':' — authorization expired';
        const opt=el('option',`${saved.channel_title} (${saved.channel_id})${suffix}`);opt.value=saved.id;select.append(opt);
      }
      const chosen=state.savedChannels.find(x=>x.id===previous)||state.savedChannels.find(x=>x.id===status.connection_id)
        ||state.savedChannels.find(x=>x.is_default)||state.savedChannels[0];
      if(chosen)select.value=chosen.id;
      $('yt-connect').dataset.allowed=status.allowed?'yes':'no';
      $('yt-connect').textContent=state.savedChannels.length?'Add / reconnect with Google':'Continue with Google';
      $('yt-disconnect').hidden=!state.savedChannels.length;
      const defaultChannel=state.savedChannels.find(x=>x.is_default);
      $('yt-connection').textContent=!status.configured ? 'Google OAuth is not configured in Vercel yet.' : !status.allowed ? 'YouTube access is not enabled for this account.' : state.connected
        ? `Selected: ${status.channel.title} (${status.channel.id}). The saved authorization was verified when connected or restored.`
        : defaultChannel && defaultChannel.status!=='active' ? 'The saved authorization needs Google consent again.'
        : state.savedChannels.length ? 'Choose a saved channel or reconnect with Google.' : 'Ready to connect: choose your channel on Google’s consent screen.';
      if(state.connected)state.autoAttempted=false;
      else if(status.allowed && defaultChannel?.status==='active' && !state.autoAttempted && !state.busy){state.autoAttempted=true;autoId=defaultChannel.id;}
    } else {
      state.connected=false;$('yt-connect').dataset.allowed='no';state.savedChannels=[];
      $('yt-saved-channels').replaceChildren();$('yt-disconnect').hidden=true;
      $('yt-connection').textContent='Could not check YouTube authorization.';errors.push(statusResult.reason.message);
    }
    if(historyResult.status==='fulfilled') {state.historyReady=true;renderHistory(historyResult.value.uploads||[]);}
    else {state.historyReady=false;errors.push(historyResult.reason.message);}
    if(errors.length)$('yt-error').textContent=errors.join(' ');
    busy(state.busy);
    if(autoId && active(v)) {
      const controller=new AbortController();state.resumeAbort=controller;busy(true);
      $('yt-connection').textContent='Restoring the saved channel…';
      try {
        await api('/api/cloud/youtube/select',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id:autoId}),signal:controller.signal});
        if(active(v)){busy(false);await refresh();}
      } catch(error) {
        if(active(v) && error.name!=='AbortError'){$('yt-error').textContent=error.message;busy(false);await refresh();}
      } finally {if(state.resumeAbort===controller)state.resumeAbort=null;if(active(v))busy(false);}
    }
  }
  async function digest(file) {
    if(!globalThis.crypto?.subtle || !crypto.randomUUID)throw new Error('This browser cannot securely fingerprint the video. Use a current browser over HTTPS.');
    if(!file || file.size<1 || file.size>100*1024*1024 || (!/\.mp4$/i.test(file.name) && file.type!=='video/mp4')) throw new Error('Choose an MP4 video no larger than 100 MiB.');
    $('yt-progress').textContent='Checking the selected file before upload…';
    return [...new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer()))].map(x=>x.toString(16).padStart(2,'0')).join('');
  }
  function renderHistory(jobs) {
    const list=$('yt-history');list.replaceChildren();
    if(!jobs.length){list.append(el('p','No uploads recorded.','form-note'));return;}
    for(const job of jobs){
      const row=el('div',null,'mission-row'),controls=el('div',null,'mission-controls');
      row.append(el('strong',job.title),el('p',`${job.status.replaceAll('_',' ')}${job.cancel_requested && !['cancelled','completed','failed'].includes(job.status)?' · stop requested':''} · ${Math.round(100*Number(job.offset_bytes)/Number(job.size_bytes))}% · ${job.channel_id}`));
      if(/^[A-Za-z0-9_-]{11}$/.test(job.video_id||'')) {
        const link=el('a',job.status==='completed'?'Open reported private video in YouTube ↗':'Open reported video in YouTube ↗');link.href=`https://www.youtube.com/watch?v=${encodeURIComponent(job.video_id)}`;link.target='_blank';link.rel='noopener noreferrer';row.append(link);
      }
      if(['uploading','uncertain','verifying'].includes(job.status) && !job.cancel_requested) {
        controls.append(button('Check status',async()=>{
          const v=state.version;if(state.busy)return;
          try{busy(true);const result=await post(path(job.id,'check'));if(active(v)){$('yt-notice').textContent=result.message||`Google confirmed ${result.offset_bytes} bytes.`;}}
          catch(error){if(active(v))$('yt-error').textContent=error.message;}
          finally{if(active(v)){busy(false);await refresh();}}
        }));
        if(job.status!=='verifying') controls.append(button('Resume selected file',async()=>{
          const v=state.version;if(state.busy)return;
          try{busy(true);const file=$('yt-file').files[0],hash=await digest(file);if(hash!==job.file_sha256)throw new Error('Choose the exact same video file to resume.');
            const check=await post(path(job.id,'check'));if(!active(v))return;
            if(['completed','verifying','cancelled','failed'].includes(check.status)){$('yt-notice').textContent=check.message||`Upload ${check.status}. Check YouTube Studio.`;return;}
            await upload(job.id,file,hash,Number(check.offset_bytes),v);
          }catch(error){if(active(v)&&error.name!=='AbortError')$('yt-error').textContent=error.message;}
          finally{if(active(v)){state.abort=null;busy(false);await refresh();}}
        }));
      }
      if(['starting','uploading','uncertain','verifying'].includes(job.status)) controls.append(button('Stop upload',async()=>{
        if(!confirm('Stop new chunks? A request already in flight may still finish, and the private video may exist in YouTube Studio.'))return;
        const v=state.version;
        try{const result=await post(path(job.id,'cancel'));if(active(v)){state.abort?.abort();$('yt-notice').textContent=result.message;await refresh();}}
        catch(error){if(active(v))$('yt-error').textContent=error.message;}
      },true));
      if(['completed','failed','cancelled'].includes(job.status)) controls.append(button('Forget record',async()=>{
        if(!confirm('Forget this ViMax record? This does not delete the video from YouTube or reset the daily limit.'))return;
        const v=state.version;try{const result=await post(path(job.id,'forget'));if(active(v)){$('yt-notice').textContent=result.message;await refresh();}}catch(error){if(active(v))$('yt-error').textContent=error.message;}
      }));
      row.append(controls);list.append(row);
    }
  }
  async function upload(id,file,hash,offset,v) {
    if(!active(v))return;
    state.abort=new AbortController();
    while(active(v) && offset<file.size) {
      $('yt-progress').textContent=`Uploading privately: ${Math.round(100*offset/file.size)}%. Keep this page open.`;
      const end=Math.min(file.size,offset+chunkSize), blob=file.slice(offset,end);
      const result=await api(path(id,'chunk'),{method:'POST',signal:state.abort.signal,
        headers:{'content-type':'application/octet-stream','x-vimax-offset':String(offset),'x-vimax-file-sha256':hash},body:blob});
      if(!active(v))return;
      if(['completed','verifying','cancelled','failed'].includes(result.status)){$('yt-progress').textContent=result.message||`Upload ${result.status}. Check YouTube Studio.`;return;}
      const next=Number(result.offset_bytes);
      if(!Number.isSafeInteger(next)||next<=offset||next>file.size)throw new Error('Upload position needs review. Use Check status before resuming.');
      offset=next;
    }
    if(active(v))$('yt-progress').textContent='Upload bytes sent; check status for YouTube verification.';
  }
  $('yt-connect').addEventListener('click',async()=>{
    const v=state.version;try{busy(true);const result=await post('/api/cloud/youtube/oauth/start');
      const url=new URL(result.authorization_url);if(url.origin!=='https://accounts.google.com')throw new Error('Invalid Google authorization URL.');
      if(active(v))window.location.assign(url.href);
    }catch(error){if(active(v)){$('yt-error').textContent=error.message;busy(false);}}
  });
  $('yt-saved-channels').addEventListener('change',()=>busy(state.busy));
  $('yt-select-channel').addEventListener('click',async()=>{
    const v=state.version,id=$('yt-saved-channels').value;if(state.busy||!id)return;
    state.autoAttempted=true;$('yt-error').textContent='';
    try{busy(true);await post('/api/cloud/youtube/select',{id});if(active(v))$('yt-notice').textContent='Selected channel restored.';}
    catch(error){if(active(v))$('yt-error').textContent=error.message;}
    finally{if(active(v)){busy(false);await refresh();}}
  });
  $('yt-disconnect').addEventListener('click',async()=>{
    const id=$('yt-saved-channels').value;if(state.busy||!id)return;
    if(!confirm('Remove this saved channel and ask Google to revoke its grant? Other channels using the same Google grant may also need to reconnect. Existing videos are not deleted.'))return;
    const v=state.version;state.autoAttempted=true;$('yt-error').textContent='';
    try{busy(true);const result=await post('/api/cloud/youtube/disconnect',{id});if(active(v))$('yt-notice').textContent=result.revoked
      ?'Saved channel removed and Google acknowledged revocation. Other channels using the same grant may need to reconnect.'
      :'Saved channel removed locally; Google revocation was not confirmed. Review access in your Google account.';}
    catch(error){if(active(v))$('yt-error').textContent=error.message;}
    finally{if(active(v)){busy(false);await refresh();}}
  });
  $('yt-refresh').addEventListener('click',refresh);$('yt-history-refresh').addEventListener('click',refresh);
  $('yt-clear-pending').addEventListener('click',()=>{
    if(state.busy||!state.historyReady||!hasPending())return;
    if(!confirm('Have you checked BOTH the upload history below and YouTube Studio? Clearing this saved attempt can allow a duplicate private upload.'))return;
    try{sessionStorage.removeItem(pendingName());$('yt-notice').textContent='Saved start attempt cleared. Existing uploads were not changed.';busy(state.busy);}
    catch{$('yt-error').textContent='Could not clear the saved attempt in this browser.';}
  });
  $('yt-form').addEventListener('submit',async event=>{
    event.preventDefault();if(state.busy||!state.connected)return;const v=state.version; $('yt-error').textContent='';$('yt-notice').textContent='';
    try {
      busy(true);const form=event.currentTarget,file=$('yt-file').files[0],hash=await digest(file);
      if(!active(v))return;
      let key;try {key=sessionStorage.getItem(pendingName());if(!key){key=crypto.randomUUID();sessionStorage.setItem(pendingName(),key);busy(state.busy);}}
      catch{throw new Error('This browser must allow session storage to protect against duplicate upload attempts.');}
      const data={client_key:key,title:form.elements.title.value,description:form.elements.description.value,
        size_bytes:file.size,file_sha256:hash,made_for_kids:form.elements.audience.value==='yes',confirm_private:form.elements.confirm_private.checked};
      const result=await post('/api/cloud/youtube/uploads/start',data);if(!active(v))return;
      try{sessionStorage.removeItem(pendingName());busy(state.busy);}catch{}
      if(result.status!=='uploading'){ $('yt-progress').textContent=`Existing upload is ${result.status}. Check history before starting another.`;return;}
      await refresh();if(active(v))await upload(result.id,file,hash,0,v);
    } catch(error){if(active(v)&&error.name!=='AbortError'){$('yt-error').textContent=error.message;$('yt-progress').textContent='Upload paused or uncertain. Use Check status; do not start a duplicate blindly.';}}
    finally{if(active(v)){state.abort=null;busy(false);await refresh();}}
  });
  window.vimaxYouTube={onSession:async user=>{
    const loggedIn=Boolean(user && typeof user.id==='string');
    state.version++;state.refreshVersion++;state.loggedIn=loggedIn;state.owner=loggedIn?user.id:null;state.connected=false;state.channel=null;state.historyReady=false;
    state.abort?.abort();state.abort=null;state.resumeAbort?.abort();state.resumeAbort=null;state.autoAttempted=false;state.savedChannels=[];state.busy=false;
    $('yt-form').reset();$('yt-saved-channels').replaceChildren();$('yt-connect').dataset.allowed='no';$('yt-disconnect').hidden=true;
    $('youtube').hidden=!loggedIn;$('youtube-link').setAttribute('href',loggedIn?'#youtube':'#account');$('yt-error').textContent='';$('yt-notice').textContent='';$('yt-history').replaceChildren();
    $('yt-progress').textContent='No upload in progress.';busy(false);
    if(loggedIn)await refresh();
  }};
})();
