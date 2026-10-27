'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = {
    user:null, session:'loading', sessionSequence:0, version:0, controllers:new Set(), authBusy:false,
    deployment:{chat:'checking', youtube:'checking'},
    chat:{providers:[], allowed:false, paused:false, settingsReady:false, historyReady:false, busy:false, turns:[], pending:null, note:'', error:''},
    channel:{ready:false, configured:false, allowed:false, busy:false, connected:null, connectionId:null, saved:[], autoAttempted:false, sequence:0, notice:'', error:''},
  };
  const isCurrent = version => Boolean(state.user && state.version === version);
  const element = (tag, text, className = '') => {
    const item = document.createElement(tag);
    if (text != null) item.textContent = text;
    if (className) item.className = className;
    return item;
  };
  async function api(path, options = {}) {
    let response;
    try {
      response = await fetch(path, {cache:'no-store', credentials:'same-origin', ...options,
        headers:{'content-type':'application/json', ...(options.headers || {})}});
    } catch (error) {
      if (error?.name === 'AbortError') throw error;
      throw new Error('The ViMax service could not be reached. Check your connection and try again.');
    }
    const type = response.headers.get('content-type') || '';
    if (!type.includes('application/json') && !type.includes('+json')) throw new Error(`The service returned a non-JSON response (HTTP ${response.status}).`);
    let value;
    try { value = await response.json(); } catch { throw new Error('The service returned invalid JSON.'); }
    if (!response.ok) throw new Error(typeof value?.error === 'string' ? value.error : `Request failed (HTTP ${response.status}).`);
    return value;
  }
  async function sessionApi(path, options = {}) {
    const controller = new AbortController();
    state.controllers.add(controller);
    try { return await api(path, {...options, signal:controller.signal}); }
    finally { state.controllers.delete(controller); }
  }
  const post = (path, data = {}) => sessionApi(path, {method:'POST', body:JSON.stringify(data)});
  const availableProviders = () => state.chat.providers.filter(p => p?.state === 'configured_unverified' && Array.isArray(p.models) && p.models.length > 0);
  const makeOption = (select, value, text) => { const option = element('option', text); option.value = value; select.append(option); };
  function setOptions(select, entries, empty) {
    const previous = select.value;
    select.replaceChildren();
    if (!entries.length) makeOption(select, '', empty);
    else for (const [value, label] of entries) makeOption(select, value, label);
    if (Array.from(select.options).some(option => option.value === previous)) select.value = previous;
  }
  function updateModels() {
    const provider = availableProviders().find(item => item.id === $('provider').value);
    setOptions($('model'), provider ? provider.models.map(model => [model, model]) : [], 'No model configured');
    updateChatControls();
  }
  function renderProviders() {
    const providers = availableProviders();
    setOptions($('provider'), providers.map(item => [item.id, item.label]), 'No provider configured');
    const fallback = $('fallback'), previous = fallback.value;
    fallback.replaceChildren(); makeOption(fallback, '', 'No fallback');
    for (const provider of providers) for (const model of provider.models) makeOption(fallback, `${provider.id}|${model}`, `${provider.label} · ${model}`);
    if (Array.from(fallback.options).some(option => option.value === previous)) fallback.value = previous;
    updateModels();
  }
  function canChat() {
    return Boolean(state.user && state.chat.settingsReady && state.chat.historyReady && state.chat.allowed && !state.chat.paused
      && !state.chat.busy && $('provider').value && $('model').value);
  }
  function updateChatControls() {
    const chat = state.chat;
    $('chat-send').disabled = !canChat() || !$('chat-prompt').value.trim();
    $('provider').disabled = chat.busy || !availableProviders().length;
    $('model').disabled = chat.busy || !availableProviders().length;
    $('fallback').disabled = chat.busy || !availableProviders().length;
    $('answer-length').disabled = chat.busy;
    $('clear-history').disabled = !state.user || !chat.historyReady || chat.busy;
    $('toggle-pause').disabled = !state.user || !chat.settingsReady || chat.busy;
    $('toggle-pause').textContent = chat.paused ? 'Resume chat' : 'Pause chat';
    const selected = availableProviders().find(provider => provider.id === $('provider').value);
    $('model-label').textContent = selected && $('model').value ? `${selected.label} · ${$('model').value}` : 'Chat settings';
    let status;
    if (state.session === 'loading') status = 'Checking your account…';
    else if (state.session === 'error') status = 'The account service is unavailable. Please refresh and try again.';
    else if (!state.user) status = state.deployment.chat === 'unconfigured' ? 'Sign in to chat. An AI provider still needs to be configured.'
      : state.deployment.chat === 'unknown' ? 'Sign in to chat. AI provider setup could not be checked.'
      : state.deployment.chat === 'checking' ? 'Checking AI provider setup…' : 'Sign in to start a conversation.';
    else if (chat.error && (!chat.settingsReady || !chat.historyReady)) status = 'Chat setup could not be checked. Refresh and try again.';
    else if (!chat.settingsReady || !chat.historyReady) status = 'Checking chat settings…';
    else if (!chat.allowed) status = 'Chat access is not enabled for this account.';
    else if (chat.paused) status = 'Chat is paused for this account. Resume it in chat settings.';
    else if (!availableProviders().length) status = 'No AI provider is configured. The deployment owner needs to finish setup.';
    else if (chat.busy) status = 'Waiting for a reply…';
    else status = chat.note || 'Provider configured; it has not necessarily been verified. Calls may incur charges.';
    $('chat-status').textContent = status;
    $('chat-error').textContent = chat.error;
  }
  function renderMessages() {
    const container = $('messages'); container.replaceChildren();
    const turns = state.chat.turns.slice(-30);
    const add = (role, text, pending = false) => {
      const row = element('article', null, `message ${role}${pending ? ' pending' : ''}`);
      const avatar = element('div', role === 'user' ? 'Y' : '✦', 'message-avatar'); avatar.setAttribute('aria-hidden', 'true');
      const body = element('div', null, 'message-body');
      body.append(element('p', role === 'user' ? 'You' : 'ViMax', 'message-role'), element('p', text, 'message-text'));
      row.append(avatar, body); container.append(row);
    };
    for (const turn of turns) {
      if (typeof turn.prompt === 'string') add('user', turn.prompt);
      if (typeof turn.reply === 'string') add('assistant', turn.reply);
    }
    if (state.chat.pending) { add('user', state.chat.pending); add('assistant', 'Thinking…', true); }
    $('welcome').hidden = Boolean(turns.length || state.chat.pending);
    requestAnimationFrame(() => { $('conversation').scrollTop = $('conversation').scrollHeight; });
  }
  function selectedChannel() { return state.channel.saved.find(channel => channel.id === $('channel-select').value); }
  function renderChannelList() {
    const previous = $('channel-select').value, select = $('channel-select'); select.replaceChildren();
    const channels = state.channel.saved;
    if (!channels.length) makeOption(select, '', 'No saved channels');
    for (const channel of channels) {
      const suffix = channel.status === 'active' ? '' : ' — reconnect required';
      makeOption(select, channel.id, `${channel.channel_title} (${channel.channel_id})${suffix}`);
    }
    const chosen = channels.find(channel => channel.id === previous) || channels.find(channel => channel.id === state.channel.connectionId)
      || channels.find(channel => channel.is_default) || channels[0];
    if (chosen) select.value = chosen.id;
  }
  function canConnect() {
    const channel = state.channel;
    return Boolean(state.user && channel.ready && channel.configured && channel.allowed && !channel.busy);
  }
  function updateChannelControls() {
    const channel = state.channel, selected = selectedChannel();
    $('google-connect').disabled = !canConnect();
    $('channel-manage').hidden = !state.user || !channel.saved.length;
    $('channel-select').disabled = !state.user || channel.busy || !channel.saved.length;
    $('channel-select-button').disabled = !canConnect() || !selected || selected.status !== 'active';
    $('channel-disconnect').disabled = !state.user || channel.busy || !selected;
    let status;
    if (state.session === 'loading') status = 'Checking channel setup…';
    else if (state.session === 'error') status = 'Channel service unavailable.';
    else if (!state.user) status = state.deployment.youtube === 'unavailable' ? 'Google setup needed · sign in first'
      : state.deployment.youtube === 'unknown' ? 'Channel setup could not be checked'
      : state.deployment.youtube === 'checking' ? 'Checking channel setup…' : 'Sign in to connect your channel';
    else if (channel.error && !channel.ready) status = 'Could not check channel setup.';
    else if (!channel.ready) status = 'Checking channel connection…';
    else if (!channel.configured) status = 'Google channel setup is incomplete.';
    else if (!channel.allowed) status = 'Channel access is not enabled for this account.';
    else if (channel.busy) status = 'Connecting channel…';
    else if (channel.connected) status = `Selected: ${channel.connected.title}`;
    else if (channel.saved.length) status = 'Choose a saved channel or reconnect.';
    else status = 'Connect your YouTube channel';
    $('channel-status').textContent = status;
    $('channel-message').textContent = channel.notice;
    $('channel-error').textContent = channel.error;
  }
  function updateAccount() {
    const loggedIn = Boolean(state.user);
    $('account-button').textContent = loggedIn ? 'Account' : 'Sign in';
    $('account-form').hidden = loggedIn;
    $('account-signed-in').hidden = !loggedIn;
    $('account-title').textContent = loggedIn ? 'Your ViMax account' : 'Sign in to ViMax';
    $('account-identity').textContent = loggedIn ? state.user.email : '';
    $('account-id').textContent = loggedIn ? `Account ID: ${state.user.id}` : '';
  }
  function closeDialog(id) { const dialog = $(id); if (dialog.open) dialog.close(); }
  function showDialog(id) { const dialog = $(id); if (!dialog.open) dialog.showModal(); }
  function resetForSession(user, sessionState) {
    state.version++;
    for (const controller of state.controllers) controller.abort();
    state.controllers.clear();
    stopAllSpeech();
    state.user = user && typeof user.id === 'string' ? {id:user.id, email:typeof user.email === 'string' ? user.email : ''} : null;
    state.session = state.user ? 'signed-in' : sessionState;
    state.chat = {providers:[], allowed:false, paused:false, settingsReady:false, historyReady:false, busy:false, turns:[], pending:null, note:'', error:''};
    state.channel = {ready:false, configured:false, allowed:false, busy:false, connected:null, connectionId:null, saved:[], autoAttempted:false, sequence:0, notice:'', error:''};
    $('chat-prompt').value = ''; $('account-password').value = ''; $('speak-replies').checked = false;
    $('settings-message').textContent = ''; $('account-error').textContent = ''; $('account-message').textContent = '';
    closeDialog('channel-dialog'); closeDialog('settings-dialog');
    renderMessages(); renderProviders(); renderChannelList(); updateAccount(); updateChannelControls(); updateChatControls();
    return state.version;
  }
  async function loadProviders(version) {
    try {
      const data = await sessionApi('/api/cloud/providers');
      if (!isCurrent(version)) return;
      state.chat.providers = Array.isArray(data.providers) ? data.providers : [];
      state.chat.allowed = data.allowed === true; state.chat.paused = data.paused === true; state.chat.settingsReady = true;
      renderProviders(); updateChatControls();
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') { state.chat.error = error.message; updateChatControls(); }
    }
  }
  async function loadHistory(version) {
    try {
      const data = await sessionApi('/api/cloud/chat/history');
      if (!isCurrent(version)) return;
      state.chat.turns = Array.isArray(data.turns) ? data.turns.slice(0, 30).reverse() : [];
      state.chat.historyReady = true; renderMessages(); updateChatControls();
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') { state.chat.error = error.message; updateChatControls(); }
    }
  }
  async function loadChannel(version) {
    if (!isCurrent(version)) return;
    const sequence = ++state.channel.sequence;
    try {
      const data = await sessionApi('/api/cloud/youtube/status');
      if (!isCurrent(version) || sequence !== state.channel.sequence) return;
      const channel = state.channel;
      channel.ready = true; channel.configured = data.configured === true; channel.allowed = data.allowed === true;
      channel.saved = Array.isArray(data.saved_channels) ? data.saved_channels.filter(item => item && typeof item.id === 'string'
        && typeof item.channel_id === 'string' && typeof item.channel_title === 'string' && ['active','needs_reauth','uncertain'].includes(item.status)) : [];
      channel.connected = data.connected === true && typeof data.channel?.title === 'string' ? {title:data.channel.title} : null;
      channel.connectionId = typeof data.connection_id === 'string' ? data.connection_id : null;
      channel.error = '';
      state.deployment.youtube = channel.configured ? 'configured_unverified' : 'unavailable';
      renderChannelList(); updateChannelControls();
      const savedDefault = channel.saved.find(item => item.is_default);
      if (!channel.connected && channel.configured && channel.allowed && savedDefault?.status === 'active' && !channel.autoAttempted && !channel.busy) {
        channel.autoAttempted = true;
        await selectChannel(version, savedDefault.id, true);
      }
    } catch (error) {
      if (isCurrent(version) && sequence === state.channel.sequence && error.name !== 'AbortError') {
        state.channel.ready = false; state.channel.error = error.message; updateChannelControls();
      }
    }
  }
  async function selectChannel(version, id, automatic = false) {
    if (!isCurrent(version) || !canConnect() || !id) return;
    state.channel.busy = true; state.channel.error = ''; state.channel.notice = automatic ? '' : 'Restoring channel…'; updateChannelControls();
    try {
      await post('/api/cloud/youtube/select', {id});
      if (!isCurrent(version)) return;
      state.channel.busy = false;
      state.channel.notice = automatic ? '' : 'Channel restored. Google authorization was checked during this operation.';
      await loadChannel(version);
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') { state.channel.error = error.message; state.channel.notice = 'The channel was not restored. Reconnect with Google if needed.'; }
    } finally { if (isCurrent(version)) { state.channel.busy = false; updateChannelControls(); } }
  }
  function applySession(user, sessionState = 'signed-out') {
    const version = resetForSession(user, sessionState);
    if (!state.user) return;
    // Account sign-in and sign-out must not wait on provider or channel calls.
    // Each loader is owner-versioned and is cancelled on an account change.
    void Promise.all([loadProviders(version), loadHistory(version), loadChannel(version)]).catch(() => {
      if (isCurrent(version)) { state.chat.error = 'Settings could not be loaded. Refresh and try again.'; updateChatControls(); }
    });
  }
  async function checkSession() {
    const sequence = ++state.sessionSequence;
    try {
      const data = await api('/api/cloud/session');
      if (sequence !== state.sessionSequence) return;
      await applySession(data.user);
    } catch (error) {
      if (sequence !== state.sessionSequence) return;
      await applySession(null, 'error');
      $('account-error').textContent = error.message;
    }
  }
  async function checkDeployment() {
    try {
      const data = await api('/api/health');
      state.deployment.chat = data.text_chat === 'configured_unverified' ? 'configured_unverified' : 'unconfigured';
      state.deployment.youtube = data.youtube_upload === 'configured_unverified' ? 'configured_unverified' : 'unavailable';
    } catch { state.deployment.chat = 'unknown'; state.deployment.youtube = 'unknown'; }
    updateChatControls(); updateChannelControls();
  }

  $('account-button').addEventListener('click', () => showDialog('account-dialog'));
  $('chat-settings').addEventListener('click', () => showDialog('settings-dialog'));
  $('channel-manage').addEventListener('click', () => { if (state.user && state.channel.saved.length) showDialog('channel-dialog'); });
  document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => closeDialog(button.dataset.close)));
  $('account-dialog').addEventListener('close', () => { $('account-password').value = ''; });
  $('account-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (state.authBusy) return;
    const form = event.currentTarget, action = event.submitter?.value === 'signup' ? 'signup' : 'login';
    const input = {email:$('account-email').value.trim(), password:$('account-password').value};
    state.authBusy = true; state.sessionSequence++;
    $('account-error').textContent = ''; $('account-message').textContent = '';
    form.querySelectorAll('button').forEach(button => { button.disabled = true; });
    try {
      const result = await api(`/api/cloud/${action}`, {method:'POST', body:JSON.stringify(input)});
      $('account-password').value = '';
      if (action === 'signup') $('account-message').textContent = result.message || 'Check your email, then sign in.';
      else {
        await checkSession();
        if (state.user) closeDialog('account-dialog');
        else $('account-error').textContent = 'Sign-in could not be confirmed. Please try again.';
      }
    } catch (error) { $('account-password').value = ''; $('account-error').textContent = error.message; }
    finally { state.authBusy = false; form.querySelectorAll('button').forEach(button => { button.disabled = false; }); }
  });
  $('resend-confirmation').addEventListener('click', async () => {
    if (state.authBusy || !$('account-email').reportValidity()) return;
    state.authBusy = true; $('account-error').textContent = ''; $('account-message').textContent = '';
    $('resend-confirmation').disabled = true;
    try {
      const data = await api('/api/cloud/resend-confirmation', {method:'POST', body:JSON.stringify({email:$('account-email').value.trim()})});
      $('account-message').textContent = data.message;
    } catch (error) { $('account-error').textContent = error.message; }
    finally { state.authBusy = false; $('resend-confirmation').disabled = false; }
  });
  $('logout').addEventListener('click', async () => {
    if (state.authBusy || !state.user) return;
    state.authBusy = true; state.sessionSequence++;
    // Immediately discard owner data and ignore late requests. A provider call
    // already received by the server can still finish or incur charges.
    await applySession(null, 'signed-out');
    try { await api('/api/cloud/logout', {method:'POST', body:'{}'}); closeDialog('account-dialog'); }
    catch { state.session = 'error'; $('account-error').textContent = 'Sign-out could not be confirmed. Refresh and try again.'; updateChatControls(); updateChannelControls(); }
    finally { state.authBusy = false; }
  });

  $('provider').addEventListener('change', updateModels);
  $('model').addEventListener('change', updateChatControls);
  $('chat-prompt').addEventListener('input', updateChatControls);
  $('chat-prompt').addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !event.repeat) {
      event.preventDefault(); if (!$('chat-send').disabled) $('chat-form').requestSubmit();
    }
  });
  $('chat-form').addEventListener('submit', async event => {
    event.preventDefault(); if (!canChat()) return;
    const prompt = $('chat-prompt').value.trim(), version = state.version;
    if (!prompt || Array.from(prompt).length > 1600) return;
    const provider = $('provider').value, model = $('model').value, fallbackValue = $('fallback').value, divider = fallbackValue.indexOf('|');
    const fallback = fallbackValue && divider > 0 ? {provider:fallbackValue.slice(0, divider), model:fallbackValue.slice(divider + 1)} : null;
    if (fallback && fallback.provider === provider && fallback.model === model) { state.chat.error = 'Choose a different fallback or turn it off.'; updateChatControls(); return; }
    state.chat.busy = true; state.chat.pending = prompt; state.chat.error = ''; state.chat.note = '';
    renderMessages(); updateChatControls();
    try {
      const data = await post('/api/cloud/chat', {provider, model, mode:'chat', length:$('answer-length').value, prompt, fallback});
      if (!isCurrent(version)) return;
      if (typeof data?.reply !== 'string' || !data.reply.trim()) throw new Error('The provider returned no text.');
      state.chat.turns.push({prompt, reply:data.reply}); state.chat.pending = null;
      if ($('chat-prompt').value.trim() === prompt) $('chat-prompt').value = '';
      const notices = [];
      if (data.used_fallback) notices.push('A fallback provider responded.');
      if (data.truncated) notices.push('The reply was truncated.');
      if (!data.history_saved) notices.push('This reply could not be saved.');
      if (!data.audit_saved) notices.push('The usage result could not be saved.');
      if (Number.isInteger(data.remaining_user)) notices.push(`${data.remaining_user} request attempt(s) remain today.`);
      state.chat.note = notices.join(' ') || 'Reply received.';
      renderMessages(); if ($('speak-replies').checked) speak(data.reply);
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') { state.chat.pending = null; state.chat.error = error.message; state.chat.note = 'No reply received.'; renderMessages(); }
    } finally { if (isCurrent(version)) { state.chat.busy = false; updateChatControls(); } }
  });
  $('toggle-pause').addEventListener('click', async () => {
    if (!state.user || !state.chat.settingsReady || state.chat.busy) return;
    const version = state.version, desired = !state.chat.paused;
    state.chat.busy = true; $('settings-message').textContent = ''; updateChatControls();
    try {
      const data = await post('/api/cloud/ai/pause', {paused:desired});
      if (isCurrent(version)) { state.chat.paused = data.paused === true; $('settings-message').textContent = state.chat.paused ? 'Chat is paused. In-flight calls may still finish.' : 'Chat resumed.'; }
    } catch (error) { if (isCurrent(version) && error.name !== 'AbortError') $('settings-message').textContent = error.message; }
    finally { if (isCurrent(version)) { state.chat.busy = false; updateChatControls(); } }
  });
  $('clear-history').addEventListener('click', async () => {
    if (!state.user || !state.chat.historyReady || state.chat.busy || !confirm('Delete all saved chat history for this account? Usage records are not deleted.')) return;
    const version = state.version; state.chat.busy = true; updateChatControls();
    try {
      await sessionApi('/api/cloud/chat/history', {method:'DELETE'});
      if (isCurrent(version)) { state.chat.turns = []; state.chat.note = 'Saved chat history deleted.'; renderMessages(); $('settings-message').textContent = 'Saved chat history deleted.'; }
    } catch (error) { if (isCurrent(version) && error.name !== 'AbortError') $('settings-message').textContent = error.message; }
    finally { if (isCurrent(version)) { state.chat.busy = false; updateChatControls(); } }
  });

  $('google-connect').addEventListener('click', async () => {
    if (!canConnect()) return;
    const version = state.version; state.channel.busy = true; state.channel.error = ''; state.channel.notice = ''; updateChannelControls();
    try {
      const data = await post('/api/cloud/youtube/oauth/start');
      let url;
      try { url = new URL(data?.authorization_url); } catch { throw new Error('Invalid Google authorization URL.'); }
      if (url.origin !== 'https://accounts.google.com' || url.pathname !== '/o/oauth2/v2/auth' || url.username || url.password) throw new Error('Invalid Google authorization URL.');
      if (isCurrent(version)) window.location.assign(url.href);
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') { state.channel.error = error.message; state.channel.notice = ''; showDialog('channel-dialog'); }
    } finally { if (isCurrent(version)) { state.channel.busy = false; updateChannelControls(); } }
  });
  $('channel-select').addEventListener('change', updateChannelControls);
  $('channel-select-button').addEventListener('click', () => {
    const item = selectedChannel(); if (!item || item.status !== 'active') return;
    state.channel.autoAttempted = true; void selectChannel(state.version, item.id);
  });
  $('channel-disconnect').addEventListener('click', async () => {
    const item = selectedChannel();
    if (!state.user || state.channel.busy || !item || !confirm('Remove this channel and ask Google to revoke its grant? Other channels using that grant may also need to reconnect.')) return;
    const version = state.version; state.channel.busy = true; state.channel.autoAttempted = true; state.channel.error = ''; state.channel.notice = ''; updateChannelControls();
    try {
      const data = await post('/api/cloud/youtube/disconnect', {id:item.id});
      if (!isCurrent(version)) return;
      state.channel.busy = false;
      state.channel.notice = data.revoked ? 'Channel removed and Google acknowledged revocation. Other channels may need to reconnect.'
        : 'Channel removed locally. Google revocation was not confirmed; review access in your Google account.';
      await loadChannel(version);
    } catch (error) { if (isCurrent(version) && error.name !== 'AbortError') state.channel.error = error.message; }
    finally { if (isCurrent(version)) { state.channel.busy = false; updateChannelControls(); } }
  });

  const synthesis = 'speechSynthesis' in window ? window.speechSynthesis : null;
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null, voices = [], voiceDisclosureAccepted = false;
  function refreshVoices() {
    const select = $('speech-voice'), previous = select.value;
    select.replaceChildren(); makeOption(select, '', 'Browser default');
    voices = synthesis ? synthesis.getVoices() : [];
    voices.forEach((voice, index) => makeOption(select, String(index), `${voice.name} · ${voice.lang}${voice.localService ? ' · device' : ' · browser service'}`));
    if (Array.from(select.options).some(option => option.value === previous)) select.value = previous;
  }
  function speechLanguage() {
    try { return new Intl.Locale($('speech-language').value.trim() || 'en-US').toString(); }
    catch { $('voice-status').textContent = 'Enter a valid language tag, such as en-US or ur-PK.'; return null; }
  }
  function stopAllSpeech() {
    if (recognition) { try { recognition.abort(); } catch {} recognition = null; }
    if (synthesis) synthesis.cancel();
    $('dictate').disabled = !Recognition; $('dictate').setAttribute('aria-label', 'Start voice input'); $('dictate').title = 'Start voice input'; $('stop-speech').hidden = true;
  }
  function speak(text) {
    if (!synthesis || typeof window.SpeechSynthesisUtterance !== 'function') { $('voice-status').textContent = 'Spoken playback is unavailable; the text reply is still visible.'; return; }
    const language = speechLanguage(); if (!language) return;
    synthesis.cancel(); const utterance = new SpeechSynthesisUtterance(text); utterance.lang = language;
    if ($('speech-voice').value !== '') utterance.voice = voices[Number($('speech-voice').value)] || null;
    utterance.onstart = () => { $('stop-speech').hidden = false; };
    utterance.onend = utterance.onerror = () => { $('stop-speech').hidden = true; };
    try { synthesis.speak(utterance); } catch { $('voice-status').textContent = 'Spoken playback is unavailable; the text reply is still visible.'; }
  }
  $('stop-speech').addEventListener('click', () => { synthesis?.cancel(); $('stop-speech').hidden = true; });
  $('dictate').addEventListener('click', () => {
    if (!Recognition) return;
    if (recognition) { try { recognition.stop(); } catch {} return; }
    if (!voiceDisclosureAccepted && !confirm('Voice input may send audio to your browser’s speech service. Continue?')) return;
    voiceDisclosureAccepted = true; const language = speechLanguage(); if (!language) return;
    const existing = $('chat-prompt').value.trim();
    try {
      const instance = new Recognition(); recognition = instance; instance.lang = language; instance.interimResults = true; instance.continuous = false;
      instance.onstart = () => { $('dictate').setAttribute('aria-label', 'Stop voice input'); $('dictate').title = 'Stop voice input'; };
      instance.onresult = event => {
        if (recognition !== instance) return;
        const transcript = Array.from(event.results, result => result[0]?.transcript || '').join(' ');
        $('chat-prompt').value = `${existing}${existing && transcript ? ' ' : ''}${transcript}`.slice(0, 1600); updateChatControls();
      };
      instance.onerror = () => { $('voice-status').textContent = 'Voice input is unavailable. You can type instead.'; };
      instance.onend = () => { if (recognition === instance) recognition = null; $('dictate').setAttribute('aria-label', 'Start voice input'); $('dictate').title = 'Start voice input'; };
      instance.start();
    } catch { recognition = null; $('voice-status').textContent = 'Could not start voice input. You can type instead.'; }
  });
  $('dictate').disabled = !Recognition;
  if (synthesis) { refreshVoices(); synthesis.addEventListener?.('voiceschanged', refreshVoices); }

  // The callback contains no tokens; only show success after the owner-scoped
  // status endpoint confirms the saved channel. Email fragments are scrubbed by
  // auth-clean.js before this file runs.
  const currentUrl = new URL(window.location.href);
  if (currentUrl.searchParams.has('youtube')) {
    currentUrl.searchParams.delete('youtube');
    if (currentUrl.hash === '#youtube') currentUrl.hash = '';
    history.replaceState(null, '', currentUrl.pathname + currentUrl.search + currentUrl.hash);
  }
  let confirmation = null;
  try { confirmation = sessionStorage.getItem('vimax-email-confirmed'); sessionStorage.removeItem('vimax-email-confirmed'); } catch {}
  renderMessages(); renderProviders(); renderChannelList(); updateAccount(); updateChannelControls(); updateChatControls();
  void checkDeployment();
  void checkSession().then(() => {
    if (confirmation && !state.user) {
      $('account-message').textContent = confirmation === 'yes' ? 'Email confirmed. Please sign in.' : 'Email confirmation failed or expired; please try again.';
      showDialog('account-dialog');
    }
  });
})();
