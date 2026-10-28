'use strict';
// Cloud planning is separate from the local, single-user companion. This file
// never receives API keys; provider requests are made by the server.
(() => {
  const $ = id => document.getElementById(id);
  const state = {loggedIn:false, version:0, providers:[], pexels:'not_configured', pexelsVerified:false, allowed:false, paused:false, settingsReady:false, pauseBusy:false, turns:[], busy:false, tests:new Map()};
  const node = (tag, text, cls = '') => { const item = document.createElement(tag); if (text != null) item.textContent = text; if (cls) item.className = cls; return item; };
  async function api(path, options = {}) {
    let response;
    try { response = await fetch(path, {cache:'no-store', ...options, headers:{'Content-Type':'application/json', ...(options.headers || {})}}); }
    catch { throw new Error('The service could not be reached. Check your connection.'); }
    if (!(response.headers.get('content-type') || '').includes('json')) throw new Error(`The service returned a non-JSON response (HTTP ${response.status}).`);
    let data; try { data = await response.json(); } catch { throw new Error('The service returned invalid JSON.'); }
    if (!response.ok) throw new Error(typeof data?.error === 'string' ? data.error : `Request failed (HTTP ${response.status}).`);
    return data;
  }
  const active = version => state.loggedIn && state.version === version;
  function option(select, value, label) { const el = node('option', label); el.value = value; select.append(el); }
  function configured() { return state.providers.filter(p => p.state === 'configured_unverified' && Array.isArray(p.models) && p.models.length); }
  function selected() { return {provider:$('ai-provider').value, model:$('ai-model').value}; }
  function updateControls() {
    const canRequest = state.loggedIn && state.settingsReady && state.allowed && !state.paused && !state.busy && !state.pauseBusy;
    const canChat = canRequest && Boolean($('ai-provider').value && $('ai-model').value);
    $('chat-send').disabled = !canChat; $('ai-test').disabled = !canChat;
    $('stock-search').disabled = !canRequest || state.pexels !== 'configured_unverified';
    $('github-lookup').disabled = !canRequest;
    $('clear-chat').disabled = !state.loggedIn || state.busy;
    $('ai-pause').disabled = !state.loggedIn || !state.settingsReady || state.pauseBusy;
    $('ai-pause').textContent = state.paused ? 'Resume my provider calls' : 'Pause my provider calls';
    $('ai-provider').disabled = state.busy || !configured().length;
    $('ai-model').disabled = state.busy || !configured().length;
    $('ai-fallback').disabled = state.busy || !configured().length || $('ai-provider').value === 'vercel';
  }
  function chooseModels() {
    const select = $('ai-model'), old = select.value;
    select.replaceChildren();
    const provider = configured().find(p => p.id === $('ai-provider').value);
    if (!provider) option(select, '', 'No model configured');
    else for (const model of provider.models) option(select, model, model);
    if (Array.from(select.options).some(o => o.value === old)) select.value = old;
    if (provider?.id === 'vercel') $('ai-fallback').value = '';
    updateControls();
  }
  function renderAccess() {
    if (!state.settingsReady) $('ai-access').textContent = 'Account access could not be verified.';
    else if (!state.allowed) $('ai-access').textContent = 'This account is not on the deployment owner’s AI access list. Your Account ID is shown above.';
    else $('ai-access').textContent = state.paused ? 'Provider calls are paused for this account. In-flight requests may still finish.' : 'Provider calls are enabled for this account. Pause stops new requests, not ones already in flight.';
    updateControls();
  }
  function renderProviders() {
    const list = $('provider-list'); list.replaceChildren();
    const descriptions = {not_configured:'Not configured', configured_unverified:'Key present · unverified', model_required:'Model selection required in Vercel', invalid_configuration:'Invalid server configuration'};
    for (const provider of state.providers) {
      const row = node('li'); row.append(node('strong', provider.label), document.createTextNode(` — ${descriptions[provider.state] || 'Unavailable'}`));
      const verified = Array.from(state.tests.entries()).filter(([key]) => key.startsWith(`${provider.id}|`));
      if (verified.length) row.append(node('span', ` · ${verified.at(-1)[1]}`));
      list.append(row);
    }
    list.append(node('li', `Pexels — ${state.pexelsVerified ? 'Responded during this session' : descriptions[state.pexels] || 'Unavailable'}`));
    const primary = $('ai-provider'), previous = primary.value; primary.replaceChildren();
    const available = configured();
    if (!available.length) option(primary, '', 'No provider configured');
    else for (const provider of available) option(primary, provider.id, provider.label);
    if (Array.from(primary.options).some(o => o.value === previous)) primary.value = previous;
    const fallback = $('ai-fallback'), oldFallback = fallback.value; fallback.replaceChildren(); option(fallback, '', 'No fallback');
    for (const provider of available) for (const model of provider.models) option(fallback, `${provider.id}|${model}`, `${provider.label} · ${model}`);
    if (Array.from(fallback.options).some(o => o.value === oldFallback)) fallback.value = oldFallback;
    chooseModels();
  }
  function renderTurns() {
    const history = $('chat-history'); history.replaceChildren();
    if (!state.turns.length) { history.append(node('p', 'No conversation yet.', 'form-note')); return; }
    for (const turn of state.turns.slice(-30)) {
      const user = node('div', null, 'chat-turn user'); user.append(node('strong', 'YOU'), node('p', turn.prompt));
      const ai = node('div', null, 'chat-turn'); ai.append(node('strong', `ASSISTANT · ${turn.provider} / ${turn.model}`), node('p', turn.reply));
      history.append(user, ai);
    }
    history.scrollTop = history.scrollHeight;
  }
  async function loadHistory(version) {
    const data = await api('/api/cloud/chat/history');
    if (!active(version)) return;
    state.turns = Array.isArray(data.turns) ? data.turns.slice(0, 30).reverse() : [];
    renderTurns();
  }
  async function loadUsage(version) {
    const data = await api('/api/cloud/usage');
    if (!active(version)) return;
    const list = $('usage-list'); list.replaceChildren();
    if (!data.calls.length) { list.append(node('li', 'No provider attempts recorded yet.')); return; }
    for (const call of data.calls) {
      const date = new Date(call.created_at);
      const when = Number.isNaN(date.getTime()) ? '' : date.toLocaleString();
      const tokens = call.input_tokens == null && call.output_tokens == null ? '' : ` · tokens ${call.input_tokens ?? '?'} in / ${call.output_tokens ?? '?'} out`;
      list.append(node('li', `${when} · ${call.feature} · ${call.provider}${call.model ? ` / ${call.model}` : ''} · ${call.status}${tokens}`));
    }
  }
  async function loadCloud(version) {
    try {
      const data = await api('/api/cloud/providers');
      if (!active(version)) return;
      state.providers = data.providers; state.pexels = data.pexels; state.allowed = data.allowed === true; state.paused = data.paused === true; state.settingsReady = true;
      renderProviders(); renderAccess();
      $('chat-status').textContent = !state.allowed ? 'AI provider access is not enabled for this account.' : state.paused ? 'Provider calls are paused.' : configured().length ? 'Select a provider and test it, or send a message. Configured keys have not yet been verified.' : 'No AI provider is configured. The deployment owner can add a rotated key in Vercel.';
      $('stock-status').textContent = state.pexels === 'configured_unverified' ? 'Pexels key present; its connection has not been verified.' : 'Pexels is not configured.';
    } catch (error) { if (active(version)) { $('chat-error').textContent = error.message; renderAccess(); } }
    await Promise.all([
      loadHistory(version).catch(error => { if (active(version)) $('chat-error').textContent = error.message; }),
      loadUsage(version).catch(error => { if (active(version)) $('usage-list').replaceChildren(node('li', error.message)); }),
    ]);
  }
  async function onSession(loggedIn) {
    const version = ++state.version; state.loggedIn = loggedIn; state.busy = false; state.allowed = false; state.paused = false; state.settingsReady = false; state.pauseBusy = false;
    // Never retain the previous account's private history or in-progress form
    // while the next session is loading (including direct account switches).
    stopAllSpeech(); state.providers = []; state.pexels = 'not_configured'; state.pexelsVerified = false; state.turns = []; state.tests.clear();
    $('chat-prompt').value = ''; $('chat-error').textContent = ''; $('stock-query').value = ''; $('github-repository').value='';
    $('chat-status').textContent = ''; $('stock-status').textContent = ''; $('github-status').textContent=''; $('usage-list').replaceChildren(); $('stock-results').replaceChildren(); $('github-result').replaceChildren();
    $('cloud-ai').hidden = !loggedIn; $('cloud-ai-link').setAttribute('href', loggedIn ? '#cloud-ai' : '#account');
    renderTurns();renderProviders();
    if (!loggedIn) return;
    $('chat-status').textContent = 'Loading provider settings…';
    await loadCloud(version);
  }
  window.vimaxCloud = {onSession};
  $('ai-provider').addEventListener('change', chooseModels);
  $('ai-model').addEventListener('change', updateControls);
  $('ai-pause').addEventListener('click', async () => {
    const version = state.version, paused = !state.paused; state.pauseBusy = true; updateControls(); $('chat-error').textContent = '';
    try {
      const result = await api('/api/cloud/ai/pause', {method:'POST', body:JSON.stringify({paused})});
      if (!active(version)) return;
      state.paused = result.paused; $('chat-status').textContent = state.paused ? 'Provider calls are paused; in-flight requests may still finish.' : 'Provider calls have resumed.';
    } catch (error) { if (active(version)) $('chat-error').textContent = error.message; }
    finally { if (active(version)) { state.pauseBusy = false; renderAccess(); } }
  });
  $('ai-test').addEventListener('click', async () => {
    const version = state.version, choice = selected(); state.busy = true; updateControls();
    $('chat-error').textContent = ''; $('chat-status').textContent = 'Testing provider with a real request…';
    try {
      const data = await api('/api/cloud/providers/test', {method:'POST', body:JSON.stringify(choice)});
      if (!active(version)) return;
      state.tests.set(`${choice.provider}|${choice.model}`, `Test succeeded for ${choice.model}`); renderProviders();
      $('chat-status').textContent = `Provider responded successfully. ${data.remaining_user} request attempt(s) remain today.${data.audit_saved ? '' : ' Warning: usage result could not be saved.'}`;
    } catch (error) { if (active(version)) { state.tests.set(`${choice.provider}|${choice.model}`, 'Last test failed'); renderProviders(); $('chat-error').textContent = error.message; $('chat-status').textContent = 'Provider test failed.'; } }
    finally { if (active(version)) { state.busy = false; updateControls(); loadUsage(version).catch(() => {}); } }
  });
  $('chat-form').addEventListener('submit', async event => {
    event.preventDefault(); if (state.busy) return;
    const version = state.version, choice = selected(), prompt = $('chat-prompt').value.trim();
    const value = $('ai-fallback').value, split = value.indexOf('|');
    const fallback = value && split > 0 ? {provider:value.slice(0, split), model:value.slice(split + 1)} : null;
    state.busy = true; updateControls(); $('chat-error').textContent = ''; $('chat-status').textContent = 'Sending to the selected provider…';
    try {
      const data = await api('/api/cloud/chat', {method:'POST', body:JSON.stringify({...choice, mode:$('ai-mode').value, length:$('ai-length').value, prompt, fallback})});
      if (!active(version)) return;
      state.turns.push({prompt, reply:data.reply, provider:data.provider, model:data.model}); renderTurns(); $('chat-prompt').value = '';
      state.tests.set(`${data.provider}|${data.model}`, `Responded this session for ${data.model}`); renderProviders();
      $('chat-status').textContent = `${data.used_fallback ? 'Fallback provider responded. ' : 'Reply received. '}${data.remaining_user} request attempt(s) remain today.${data.truncated ? ' The reply was truncated; ask for a shorter or continued answer.' : ''}${data.history_saved ? '' : ' Warning: this turn could not be saved.'}${data.audit_saved ? '' : ' Warning: usage result could not be saved.'}`;
      if ($('speak-replies').checked) speak(data.reply);
    } catch (error) { if (active(version)) { $('chat-error').textContent = error.message; $('chat-status').textContent = 'No reply received.'; } }
    finally { if (active(version)) { state.busy = false; updateControls(); loadUsage(version).catch(() => {}); } }
  });
  $('clear-chat').addEventListener('click', async () => {
    if (!confirm('Delete all saved planning chat history for this account? This does not delete provider usage records.')) return;
    const version = state.version;
    try { await api('/api/cloud/chat/history', {method:'DELETE'}); if (active(version)) { state.turns = []; renderTurns(); $('chat-status').textContent = 'Saved chat history deleted.'; } }
    catch (error) { if (active(version)) $('chat-error').textContent = error.message; }
  });
  $('refresh-usage').addEventListener('click', () => { const version = state.version; loadUsage(version).catch(error => { if (active(version)) $('usage-list').replaceChildren(node('li', error.message)); }); });
  $('stock-form').addEventListener('submit', async event => {
    event.preventDefault(); if (state.busy) return;
    const version = state.version; state.busy = true; updateControls(); $('stock-status').textContent = 'Searching Pexels…'; $('stock-results').replaceChildren();
    try {
      const data = await api('/api/cloud/stock-search', {method:'POST', body:JSON.stringify({query:$('stock-query').value, orientation:$('stock-orientation').value})});
      if (!active(version)) return;
      state.pexelsVerified = true; renderProviders();
      for (const video of data.videos) {
        const li = node('li'), link = node('a', `View video by ${video.creator} ↗`); link.href = video.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        li.append(link, node('p', `${video.duration ?? '?'} sec · ${video.width ?? '?'} × ${video.height ?? '?'}`)); $('stock-results').append(li);
      }
      $('stock-status').textContent = `${data.videos.length} result(s). ${data.remaining_user} request attempt(s) remain today.${data.audit_saved ? '' : ' Warning: usage result could not be saved.'}`;
    } catch (error) { if (active(version)) $('stock-status').textContent = error.message; }
    finally { if (active(version)) { state.busy = false; updateControls(); loadUsage(version).catch(() => {}); } }
  });

  $('github-form').addEventListener('submit', async event => {
    event.preventDefault(); if (state.busy) return;
    const version=state.version;state.busy=true;updateControls();$('github-status').textContent='Checking GitHub’s public API…';$('github-result').replaceChildren();
    try {
      const data=await api('/api/cloud/github/repository',{method:'POST',body:JSON.stringify({repository:$('github-repository').value})});
      if(!active(version))return;
      const repo=data.repository,link=node('a',`${repo.name} ↗`);link.href=repo.url;link.target='_blank';link.rel='noopener noreferrer';
      $('github-result').append(link,node('p',repo.description||'No description provided.'),node('p',`Stars: ${repo.stars ?? '?'} · Forks: ${repo.forks ?? '?'} · License: ${repo.license}${repo.archived?' · Archived':''}`));
      $('github-status').textContent=`Public metadata received. ${data.remaining_user} request attempt(s) remain today.${data.audit_saved?'':' Warning: usage result could not be saved.'}`;
    } catch(error){if(active(version))$('github-status').textContent=error.message;}
    finally{if(active(version)){state.busy=false;updateControls();loadUsage(version).catch(()=>{});}}
  });

  // Browser speech APIs vary widely. Dictation is always reviewed before send,
  // and voice gender is never inferred from an unreliable voice name.
  const synth = 'speechSynthesis' in window ? window.speechSynthesis : null;
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null, voices = [];
  function refreshVoices() {
    const select = $('speech-voice'), old = select.value; select.replaceChildren(); option(select, '', 'Browser default');
    voices = synth ? synth.getVoices() : [];
    voices.forEach((voice, index) => option(select, String(index), `${voice.name} · ${voice.lang}${voice.localService ? ' · device' : ' · browser service'}`));
    if (Array.from(select.options).some(o => o.value === old)) select.value = old;
  }
  function speechLanguage() {
    const lang = $('speech-language').value.trim() || 'en-US';
    try { return new Intl.Locale(lang).toString(); } catch { $('voice-status').textContent = 'Enter a valid language tag, such as en-US or ur-PK.'; return null; }
  }
  function speak(text) {
    if (!synth || typeof window.SpeechSynthesisUtterance !== 'function') { $('voice-status').textContent = 'Spoken playback is unavailable in this browser; the text reply is above.'; return; }
    const lang = speechLanguage(); if (!lang) return;
    synth.cancel(); const utterance = new SpeechSynthesisUtterance(text); utterance.lang = lang;
    if ($('speech-voice').value !== '') utterance.voice = voices[Number($('speech-voice').value)] || null;
    utterance.onstart = () => { $('stop-speech').disabled = false; $('voice-status').textContent = 'Speaking…'; };
    utterance.onend = () => { $('stop-speech').disabled = true; $('voice-status').textContent = 'Playback finished.'; };
    utterance.onerror = () => { $('stop-speech').disabled = true; $('voice-status').textContent = 'Playback stopped or was unavailable; the text reply is above.'; };
    try { synth.speak(utterance); } catch { $('voice-status').textContent = 'Spoken playback is unavailable; the text reply is above.'; }
  }
  function stopAllSpeech() {
    if (recognition) { try { recognition.abort(); } catch {} recognition = null; }
    if (synth) synth.cancel(); $('stop-speech').disabled = true; $('stop-dictation').disabled = true;
  }
  $('stop-speech').addEventListener('click', () => { if (synth) synth.cancel(); $('stop-speech').disabled = true; $('voice-status').textContent = 'Playback interrupted.'; });
  $('dictate').disabled = !Recognition;
  $('dictate').addEventListener('click', () => {
    const lang = speechLanguage(); if (!Recognition || !lang || recognition) return;
    const existing = $('chat-prompt').value.trim();
    try {
      const instance = new Recognition(); recognition = instance; instance.lang = lang; instance.interimResults = true; instance.continuous = false;
      instance.onstart = () => { $('dictate').disabled = true; $('stop-dictation').disabled = false; $('voice-status').textContent = 'Listening…'; };
      instance.onresult = event => {
        if (recognition !== instance) return;
        const transcript = Array.from(event.results, result => result[0]?.transcript || '').join(' ');
        $('chat-prompt').value = `${existing}${existing && transcript ? ' ' : ''}${transcript}`.slice(0, 1600);
      };
      instance.onerror = () => { $('voice-status').textContent = 'Microphone or dictation service unavailable. You can type instead.'; };
      instance.onend = () => { if (recognition === instance) recognition = null; $('dictate').disabled = !Recognition; $('stop-dictation').disabled = true; };
      instance.start();
    } catch { recognition = null; $('voice-status').textContent = 'Could not start dictation. You can type instead.'; }
  });
  $('stop-dictation').addEventListener('click', () => { if (recognition) recognition.stop(); $('voice-status').textContent = 'Stopping dictation…'; });
  if (synth) { refreshVoices(); synth.addEventListener?.('voiceschanged', refreshVoices); }
  $('voice-status').textContent = `${Recognition ? 'Dictation available when microphone permission is granted.' : 'Dictation is not supported here; type instead.'} ${synth ? 'Playback depends on installed browser voices.' : 'Spoken playback is not supported here.'}`;
  renderTurns(); renderProviders();
})();
