'use strict';
(() => {
  const $=id=>document.getElementById(id),providers=['tiktok','facebook'];
  const state={loggedIn:false,version:0,sequence:0,connections:[],config:{},busy:{},attempted:{},verified:{},controllers:new Set()};
  const node=(tag,text)=>{const element=document.createElement(tag);element.textContent=text;return element;};
  const id=(p,s)=>`social-${p}-${s}`;
  const active=v=>state.loggedIn&&state.version===v;
  async function api(path,options={}){
    let response;try{response=await fetch(path,{cache:'no-store',...options});}
    catch(error){if(error?.name==='AbortError')throw error;throw new Error('The connection request was interrupted.');}
    const type=response.headers.get('content-type')||'';
    if(!type.includes('application/json')&&!type.includes('+json'))throw new Error(`The service returned a non-JSON response (HTTP ${response.status}).`);
    let data;try{data=await response.json();}catch{throw new Error('The service returned invalid JSON.');}
    if(!response.ok)throw new Error(typeof data?.error==='string'?data.error:`Request failed (HTTP ${response.status}).`);
    return data;
  }
  const post=(path,data={},signal)=>api(path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(data),signal});
  const options=p=>state.connections.filter(x=>x.provider===p);
  function controls(p){
    const entries=options(p),selected=entries.find(x=>x.id===$(id(p,'list')).value),busy=Boolean(state.busy[p]);
    $(id(p,'connect')).disabled=busy||!state.config[p]?.allowed;
    $(id(p,'list')).disabled=busy||!entries.length;
    $(id(p,'select')).disabled=busy||!state.config[p]?.allowed||!selected||selected.status!=='active';
    $(id(p,'remove')).hidden=!entries.length;$(id(p,'remove')).disabled=busy||!selected;
  }
  function draw(p){
    const entries=options(p),select=$(id(p,'list')),previous=select.value,config=state.config[p]||{};
    select.replaceChildren();
    if(!entries.length){const option=node('option',p==='tiktok'?'No saved profiles':'No saved Pages');option.value='';select.append(option);}
    for(const entry of entries){
      const suffix=entry.status==='active'?'':' — reconnect required';
      const option=node('option',`${entry.display_name} (${entry.external_id})${suffix}`);option.value=entry.id;select.append(option);
    }
    const chosen=entries.find(x=>x.id===previous)||entries.find(x=>x.id===state.verified[p])||entries.find(x=>x.is_default)||entries[0];
    if(chosen)select.value=chosen.id;
    const verified=entries.find(x=>x.id===state.verified[p]&&x.status==='active');
    const selectedDefault=entries.find(x=>x.is_default);
    $(id(p,'status')).textContent=!config.configured?`${p==='tiktok'?'TikTok':'Facebook'} developer app is not configured on this deployment.`
      :!config.allowed?'This provider is not enabled for your account.'
      :verified?`Verified this session: ${verified.display_name} (${verified.external_id}).`
      :selectedDefault&&selectedDefault.status!=='active'?'Saved authorization needs consent again.'
      :entries.length?'Saved connection available; restore it to verify access.':'Ready for provider consent.';
    controls(p);
  }
  async function restore(p,connectionId,v){
    const controller=new AbortController();state.controllers.add(controller);state.busy[p]=true;state.attempted[p]=true;controls(p);
    $(id(p,'status')).textContent='Restoring the saved connection…';
    try{await post(`/api/cloud/social/${p}/select`,{id:connectionId},controller.signal);
      if(active(v)){state.verified[p]=connectionId;$(id(p,'error')).textContent='';}}
    catch(error){if(active(v)&&error.name!=='AbortError'){$(id(p,'error')).textContent=error.message;state.verified[p]=null;}}
    finally{state.controllers.delete(controller);if(active(v)){state.busy[p]=false;controls(p);}}
  }
  async function refresh(tryAutomatic=true){
    if(!state.loggedIn)return;const v=state.version,seq=++state.sequence;let result;
    try{result=await api('/api/cloud/social/status');}
    catch(error){if(active(v)&&seq===state.sequence)for(const p of providers){state.config[p]={};state.verified[p]=null;
      $(id(p,'status')).textContent='Could not check connection status.';$(id(p,'error')).textContent=error.message;controls(p);}return;}
    if(!active(v)||seq!==state.sequence)return;
    state.connections=Array.isArray(result.connections)?result.connections:[];state.config=result.providers||{};
    for(const p of providers)draw(p);
    if(tryAutomatic){
      const tasks=[];
      for(const p of providers){const item=options(p).find(x=>x.is_default&&x.status==='active');
        if(item&&state.config[p]?.allowed&&!state.attempted[p]&&!state.busy[p])tasks.push(restore(p,item.id,v));}
      if(tasks.length){await Promise.all(tasks);if(active(v))await refresh(false);}
    }
  }
  for(const p of providers){
    $(id(p,'list')).addEventListener('change',()=>controls(p));
    $(id(p,'connect')).addEventListener('click',async()=>{
      if(state.busy[p])return;const v=state.version,controller=new AbortController();state.controllers.add(controller);state.busy[p]=true;controls(p);
      $(id(p,'error')).textContent='';
      try{const result=await post(`/api/cloud/social/${p}/start`,{},controller.signal),url=new URL(result.authorization_url);
        const expected=p==='tiktok'?'https://www.tiktok.com':'https://www.facebook.com';
        if(url.origin!==expected)throw new Error('Invalid provider authorization URL.');
        if(active(v))window.location.assign(url.href);
      }catch(error){if(active(v)&&error.name!=='AbortError')$(id(p,'error')).textContent=error.message;}
      finally{state.controllers.delete(controller);if(active(v)){state.busy[p]=false;controls(p);}}
    });
    $(id(p,'select')).addEventListener('click',async()=>{
      const v=state.version,selected=$(id(p,'list')).value;if(state.busy[p]||!selected)return;
      await restore(p,selected,v);if(active(v))await refresh(false);
    });
    $(id(p,'remove')).addEventListener('click',async()=>{
      const v=state.version,selected=$(id(p,'list')).value;if(state.busy[p]||!selected)return;
      const warning=p==='facebook'?'Remove this Page from ViMax? This does not revoke the Facebook app grant. Manage app access in Facebook settings.'
        :'Remove this TikTok connection and ask TikTok to revoke access?';
      if(!confirm(warning))return;state.attempted[p]=true;state.busy[p]=true;controls(p);$(id(p,'error')).textContent='';
      const controller=new AbortController();state.controllers.add(controller);
      try{const result=await post(`/api/cloud/social/${p}/disconnect`,{id:selected},controller.signal);
        if(active(v)){if(state.verified[p]===selected)state.verified[p]=null;
          $(id(p,'notice')).textContent=result.revoked?'Removed and the provider acknowledged revocation.'
            :'Removed from ViMax. Provider revocation was not confirmed; review app access in provider settings.';}}
      catch(error){if(active(v)&&error.name!=='AbortError')$(id(p,'error')).textContent=error.message;}
      finally{state.controllers.delete(controller);if(active(v)){state.busy[p]=false;await refresh(false);}}
    });
  }
  $('social-refresh').addEventListener('click',()=>refresh(false));
  window.vimaxSocial={onSession:async user=>{
    state.version++;state.sequence++;for(const controller of state.controllers)controller.abort();state.controllers.clear();
    state.loggedIn=Boolean(user&&typeof user.id==='string');state.connections=[];state.config={};state.busy={};state.attempted={};state.verified={};
    $('social-connections').hidden=!state.loggedIn;$('social-link').href=state.loggedIn?'#social-connections':'#account';
    for(const p of providers){$(id(p,'list')).replaceChildren();$(id(p,'error')).textContent='';$(id(p,'notice')).textContent='';controls(p);}
    if(state.loggedIn)await refresh();
  }};
})();
