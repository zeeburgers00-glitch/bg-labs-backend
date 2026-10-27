'use strict';
(() => {
  const $=id=>document.getElementById(id);
  const state={loggedIn:false,version:0,fetchVersion:0,data:null,editId:null,detailId:null,pending:null,page:0,timer:null};
  const active=version=>state.loggedIn && state.version===version;
  const node=(tag,text,cls='')=>{ const el=document.createElement(tag); if(text != null) el.textContent=text; if(cls) el.className=cls; return el; };
  async function api(path, options={}) {
    let response;
    try { response=await fetch(path,{cache:'no-store',...options,headers:{'content-type':'application/json',...(options.headers||{})}}); }
    catch { throw new Error('Mission control cannot reach the service.'); }
    const type=response.headers.get('content-type')||'';
    if (!type.includes('application/json') && !type.includes('+json')) throw new Error(`Mission control returned a non-JSON response (HTTP ${response.status}).`);
    let value; try { value=await response.json(); } catch { throw new Error('Mission control returned invalid JSON.'); }
    if(!response.ok) throw new Error(typeof value?.error==='string' ? value.error : `Request failed (HTTP ${response.status}).`);
    return value;
  }
  function button(label,action) { const b=node('button',label,'small-button'); b.type='button'; b.addEventListener('click',action); return b; }
  const time=value=>{ const d=new Date(value); return Number.isFinite(d.getTime()) ? d.toLocaleString() : 'Unknown time'; };
  function setChannels(select,channels) {
    const previous=select.value; select.replaceChildren();
    if (!channels.length) { const option=node('option','Add a profile first'); option.value=''; select.append(option); return; }
    for (const channel of channels) { const option=node('option',channel.name); option.value=channel.id; select.append(option); }
    if (channels.some(channel=>channel.id===previous)) select.value=previous;
  }
  function resetEdit() {
    state.editId=null; $('mission-channel-form').reset(); $('mission-channel-save').textContent='Add profile'; $('mission-channel-reset').hidden=true;
  }
  function render() {
    const {channels,competitors,jobs,workers,paused}=state.data;
    const recent=workers.some(worker=>{const age=Date.now()-Date.parse(worker.last_seen_at); return Number.isFinite(age) && age>=-300_000 && age<120_000;});
    $('mission-worker-state').textContent=recent ? 'Recent worker heartbeat · provider not verified' : 'No recent worker heartbeat';
    $('mission-queue-state').textContent=paused ? 'Queue paused · running calls may still finish' : 'Queue accepting planning jobs';
    $('mission-pause').disabled=false; $('mission-pause').textContent=paused ? 'Resume queue' : 'Pause queue';
    setChannels($('mission-job-channel'),channels); setChannels($('mission-competitor-channel'),channels);
    const list=$('mission-channel-list'); list.replaceChildren();
    if(!channels.length) list.append(node('p','No channel profiles saved yet.','form-note'));
    for (const channel of channels) {
      const row=node('div',null,'mission-row'), actions=node('div',null,'mission-controls');
      row.append(node('strong',channel.name),node('p',`${channel.niche} · ${channel.language} · ${channel.timezone} · ${channel.format}`));
      actions.append(button('Edit',()=>{
        state.editId=channel.id; const form=$('mission-channel-form');
        for(const key of ['name','niche','audience','language','timezone','brand_voice','format']) form.elements.namedItem(key).value=channel[key]||'';
        $('mission-channel-save').textContent='Save profile'; $('mission-channel-reset').hidden=false; form.elements.namedItem('name').focus();
      }),button('Delete',async()=>{
        if(!confirm('Delete this profile and its competitor references? Profiles with stored jobs cannot be deleted until those jobs are removed.')) return;
        const version=state.version;
        try { await api(`/api/cloud/mission/channels/${encodeURIComponent(channel.id)}`,{method:'DELETE'}); if(active(version)){if(state.editId===channel.id) resetEdit(); await refresh();} }
        catch(error){if(active(version)) $('mission-error').textContent=error.message;}
      })); row.append(actions); list.append(row);
    }
    const refs=$('mission-competitor-list'); refs.replaceChildren();
    if(!competitors.length) refs.append(node('p','No references saved.','form-note'));
    for(const ref of competitors) {
      const row=node('div',null,'mission-row'), label=channels.find(c=>c.id===ref.channel_id)?.name || 'Profile';
      const link=node('a',ref.url); try { const url=new URL(ref.url); if(url.protocol==='https:' && ['youtube.com','www.youtube.com'].includes(url.hostname)){link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';} } catch {}
      row.append(node('p',label),link,node('br'),button('Remove',async()=>{
        const version=state.version;
        try {await api(`/api/cloud/mission/competitors/${encodeURIComponent(ref.id)}`,{method:'DELETE'}); if(active(version)) await refresh();}
        catch(error){if(active(version)) $('mission-error').textContent=error.message;}
      })); refs.append(row);
    }
    $('mission-page').textContent=`Page ${state.page+1}`; $('mission-prev').disabled=state.page===0; $('mission-next').disabled=jobs.length<50 || state.page>=39;
    const jobList=$('mission-job-list'); jobList.replaceChildren();
    if(!jobs.length) jobList.append(node('p','No planning jobs yet.','form-note'));
    for(const job of jobs) {
      const row=node('div',null,'mission-row');
      const profile=channels.find(c=>c.id===job.channel_id)?.name || 'Profile';
      row.append(node('strong',job.topic),node('p',`${profile} · ${job.status.replaceAll('_',' ')}${job.last_error ? ` · ${job.last_error.replaceAll('_',' ')}` : ''} · ${time(job.created_at)}`),button('View details',()=>loadDetail(job.id)));
      jobList.append(row);
    }
  }
  async function refresh() {
    if(!state.loggedIn) return;
    const version=state.version, request=++state.fetchVersion;
    try {
      const data=await api('/api/cloud/mission');
      if(state.page>0){const page=await api(`/api/cloud/mission/jobs-page/${state.page*50}`);data.jobs=page.jobs;}
      if(!active(version)||request!==state.fetchVersion) return;
      if(!Array.isArray(data.channels)||!Array.isArray(data.competitors)||!Array.isArray(data.jobs)||!Array.isArray(data.workers)) throw new Error('Mission control returned incomplete data.');
      state.data=data; $('mission-error').textContent=''; render();
    } catch(error){if(active(version)&&request===state.fetchVersion) {$('mission-error').textContent=error.message; $('mission-worker-state').textContent='Worker status unavailable'; $('mission-queue-state').textContent='Queue status unavailable'; $('mission-pause').disabled=true;}}
  }
  async function loadDetail(id) {
    const version=state.version; state.detailId=id; $('mission-detail').hidden=false;
    $('mission-detail-title').textContent='Loading job…'; $('mission-steps').replaceChildren(); $('mission-events').replaceChildren(); $('mission-detail-actions').replaceChildren();
    try {
      const data=await api(`/api/cloud/mission/jobs/${encodeURIComponent(id)}`);
      if(!active(version)||state.detailId!==id) return;
      const {job,steps,events}=data; $('mission-detail-title').textContent=job.topic;
      const reason=job.review_reason === 'uncertain' ? ' · outcome uncertain; a retry may incur duplicate charges' : job.review_reason === 'plan_ready' ? ' · draft needs human review' : '';
      $('mission-detail-status').textContent=`${job.status.replaceAll('_',' ')}${reason} · ${job.provider} / ${job.model} · attempts ${job.attempts}${job.last_error ? ` · ${job.last_error.replaceAll('_',' ')}` : ''}`;
      const actions=$('mission-detail-actions');
      const action=(label,name,confirmation,extra={})=>button(label,async()=>{
        if(confirmation && !confirm(confirmation)) return;
        try { await api(`/api/cloud/mission/jobs/${encodeURIComponent(id)}/action`,{method:'POST',body:JSON.stringify({action:name,...extra})});
          if(active(version)){ $('mission-notice').textContent=name==='approve' ? 'Text plan approved. No video was rendered or published.' : `Job ${name} recorded.`; await refresh(); if(name==='purge'){state.detailId=null;$('mission-detail').hidden=true;} else await loadDetail(id); }
        } catch(error){if(active(version)) $('mission-error').textContent=error.message;}
      });
      if(['queued','running','needs_review'].includes(job.status)) actions.append(action('Cancel job','cancel','Cancel this job? An already-started provider call may still finish or be billed.'));
      if(job.status==='needs_review'&&job.review_reason==='plan_ready') actions.append(action('Approve text plan','approve','Mark this text plan as reviewed? This does not render or publish anything.'));
      if(job.status==='failed') actions.append(action('Retry','retry','Retry this failed job? Provider attempts may incur charges.'));
      if(job.status==='needs_review'&&job.review_reason==='uncertain') actions.append(action('Retry uncertain job','retry','The previous request may have completed or been billed. Retrying can duplicate charges. Continue?',{confirm_duplicate_charge:true}));
      if(['completed','failed','cancelled'].includes(job.status)) actions.append(action('Delete job','purge','Permanently delete this job, its drafts and event history?'));
      if(!steps.length) $('mission-steps').append(node('p','No stage outputs recorded.','form-note'));
      for(const step of steps) {const div=node('div',null,'mission-output'); div.append(node('strong',`${step.stage} · ${step.status}`)); if(step.output) div.append(node('pre',step.output)); $('mission-steps').append(div);}
      if(!events.length) $('mission-events').append(node('li','No events recorded.'));
      for(const event of events) $('mission-events').append(node('li',`${time(event.created_at)} · ${event.event.replaceAll('_',' ')}${event.stage ? ` · ${event.stage}` : ''}`));
    } catch(error){if(active(version)&&state.detailId===id) {$('mission-detail-title').textContent='Job details unavailable';$('mission-error').textContent=error.message;}}
  }
  async function onSession(loggedIn) {
    const version=++state.version; ++state.fetchVersion; state.loggedIn=loggedIn; state.data=null; state.detailId=null; state.pending=null; state.page=0;
    clearInterval(state.timer); state.timer=null; $('mission').hidden=!loggedIn; $('mission-link').setAttribute('href',loggedIn ? '#mission' : '#account');
    $('mission-detail').hidden=true; $('mission-detail-title').textContent='Job details'; $('mission-detail-status').textContent=''; $('mission-detail-actions').replaceChildren(); $('mission-steps').replaceChildren(); $('mission-events').replaceChildren();
    $('mission-job-channel').replaceChildren(); $('mission-competitor-channel').replaceChildren(); $('mission-channel-list').replaceChildren(); $('mission-competitor-list').replaceChildren(); $('mission-job-list').replaceChildren(); $('mission-error').textContent=''; $('mission-notice').textContent=''; $('mission-worker-state').textContent='Checking worker heartbeat…'; $('mission-queue-state').textContent='Loading queue…'; $('mission-pause').disabled=true;
    $('mission-channel-form').reset(); $('mission-job-form').reset(); $('mission-competitor-form').reset(); resetEdit();
    if(!loggedIn) return;
    await refresh();
    if(active(version)) state.timer=setInterval(()=>{if(!document.hidden) void refresh();},30_000);
  }
  window.vimaxMission={onSession};
  $('mission-refresh').addEventListener('click',()=>refresh());
  $('mission-prev').addEventListener('click',()=>{if(state.page>0){state.page--;void refresh();}});
  $('mission-next').addEventListener('click',()=>{if(state.data?.jobs.length===50 && state.page<39){state.page++;void refresh();}});
  $('mission-detail-close').addEventListener('click',()=>{state.detailId=null;$('mission-detail').hidden=true;});
  $('mission-channel-reset').addEventListener('click',resetEdit);
  $('mission-pause').addEventListener('click',async()=>{
    if(!state.data) return; const version=state.version,paused=!state.data.paused;
    if(paused && !confirm('Pause new jobs and request cancellation of running jobs? A provider call already started can still complete and incur charges.')) return;
    $('mission-pause').disabled=true;
    try { await api('/api/cloud/mission/pause',{method:'POST',body:JSON.stringify({paused})}); if(active(version)){ $('mission-notice').textContent=paused ? 'Queue paused; in-flight calls may still finish.' : 'Queue resumed.'; await refresh();} }
    catch(error){if(active(version)) {$('mission-error').textContent=error.message;$('mission-pause').disabled=false;}}
  });
  $('mission-channel-form').addEventListener('submit',async event=>{
    event.preventDefault(); const version=state.version, form=event.currentTarget, id=state.editId, data=Object.fromEntries(new FormData(form));
    const submit=$('mission-channel-save'); submit.disabled=true;
    try {await api(id ? `/api/cloud/mission/channels/${encodeURIComponent(id)}` : '/api/cloud/mission/channels',{method:id?'PATCH':'POST',body:JSON.stringify(data)});
      if(active(version)){resetEdit();$('mission-notice').textContent='Channel profile saved. This is not a connected YouTube channel.';await refresh();}}
    catch(error){if(active(version)) $('mission-error').textContent=error.message;}
    finally {submit.disabled=false;}
  });
  $('mission-competitor-form').addEventListener('submit',async event=>{
    event.preventDefault(); const version=state.version, form=event.currentTarget, data=Object.fromEntries(new FormData(form)), submit=form.querySelector('button[type=submit]'); submit.disabled=true;
    try {await api('/api/cloud/mission/competitors',{method:'POST',body:JSON.stringify(data)}); if(active(version)){form.elements.namedItem('url').value='';$('mission-notice').textContent='Reference saved; no analysis was performed.';await refresh();}}
    catch(error){if(active(version)) $('mission-error').textContent=error.message;}
    finally {submit.disabled=false;}
  });
  const defaults={groq:'llama-3.1-8b-instant',openai:'gpt-5.4-nano',gemini:'gemini-2.5-flash',mistral:'mistral-small-latest',zai:'glm-4.5-flash',openrouter:'openrouter/free',huggingface:'openai/gpt-oss-120b:groq',opencode:''};
  $('mission-provider').addEventListener('change',()=>{$('mission-model').value=defaults[$('mission-provider').value]||'';});
  $('mission-job-form').addEventListener('submit',async event=>{
    event.preventDefault(); const version=state.version, form=event.currentTarget, data=Object.fromEntries(new FormData(form)), submit=form.querySelector('button[type=submit]');
    try {
      if(data.not_before){const date=new Date(data.not_before);if(!Number.isFinite(date.getTime())) throw new Error('Choose a valid start time.');data.not_before=date.toISOString();}else data.not_before=null;
      const signature=JSON.stringify(data);
      if(!state.pending || state.pending.signature!==signature){if(!crypto.randomUUID) throw new Error('This browser cannot generate a secure job ID.');state.pending={signature,key:crypto.randomUUID()};}
      data.client_key=state.pending.key; submit.disabled=true;
      const result=await api('/api/cloud/mission/jobs',{method:'POST',body:JSON.stringify(data)});
      if(active(version)){state.pending=null; state.page=0; form.elements.namedItem('topic').value=''; form.elements.namedItem('not_before').value=''; $('mission-notice').textContent=result.job.existing ? 'Existing job recovered after retry.' : 'Text plan queued. It will not run without a separately hosted worker.'; await refresh();}
    } catch(error){if(active(version)) $('mission-error').textContent=`${error.message} If the response was lost, retry the unchanged form to avoid a duplicate.`;}
    finally {submit.disabled=false;}
  });
})();
