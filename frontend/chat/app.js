'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = {
    user:null, session:'loading', sessionSequence:0, version:0, controllers:new Set(), authBusy:false,
    deployment:{chat:'checking', youtube:'checking'},
    google:{status:'checking', busy:false, error:''},
    chat:{providers:[], allowed:false, paused:false, settingsReady:false, historyReady:false, busy:false, turns:[], pending:null, note:'', error:''},
    channel:{ready:false, configured:false, allowed:false, analyticsConfigured:false, analyticsConnected:false, busy:false, connected:null, connectionId:null, saved:[], autoAttempted:false, sequence:0, notice:'', error:''},
    facebook:{ready:false, configured:false, allowed:false, busy:false, saved:[], verified:null, autoAttempted:false, sequence:0, notice:'', error:''},
  };
  let autoConnectAfterLogin = false;
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
  function isAnalyticsRequest(text) {
    const value = String(text || '').trim();
    if (!/\banalytics\b/i.test(value) && !/تجزیات/.test(value)) return false;
    if (/\b(show|send|image|picture|screenshot|chart|report|dikha\w*|dekha\w*|bhej\w*|bata\w*|bta\w*)\b/i.test(value)
        || /دکھا|بھیج|تصویر|رپورٹ/.test(value)) return true;
    if (/\b(explain|what|how|why|meaning|kya|kaise|kyun)\b/i.test(value)) return false;
    return value.split(/\s+/).length <= 4;
  }
  function canChat() {
    const analytics = isAnalyticsRequest($('chat-prompt').value);
    return Boolean(state.user && state.channel.ready && state.channel.connected && state.chat.settingsReady && state.chat.historyReady
      && state.chat.allowed && !state.chat.paused && !state.chat.busy && (analytics || ($('provider').value && $('model').value)));
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
    else if (!state.channel.ready && state.channel.error) status = 'Channel status could not be checked. Open Account to try again.';
    else if (!state.channel.ready) status = 'Checking your channel connection…';
    else if (!state.channel.configured) status = 'YouTube channel setup is incomplete. An AI provider may also need setup.';
    else if (!state.channel.allowed) status = 'YouTube channel access is not enabled for this account.';
    else if (state.channel.busy) status = 'Restoring your channel…';
    else if (!state.channel.connected) status = 'Connect a YouTube channel in Account before chatting.';
    else if (chat.busy) status = 'Waiting for a reply…';
    else if (!availableProviders().length && isAnalyticsRequest($('chat-prompt').value) && state.channel.analyticsConfigured)
      status = 'Analytics can be requested separately; an AI provider is still needed for general chat.';
    else if (!availableProviders().length) status = 'No AI provider is configured. The deployment owner needs to finish setup.';
    else status = chat.note || 'Provider configured; it has not necessarily been verified. Calls may incur charges.';
    $('chat-status').textContent = status;
    $('chat-error').textContent = chat.error;
  }
  function analyticsFigure(report) {
    const figure = element('figure', null, 'analytics-figure');
    const canvas = element('canvas', null, 'analytics-canvas'); canvas.width = 1000; canvas.height = 590;
    canvas.setAttribute('role', 'img'); canvas.setAttribute('aria-label', `ViMax visualization of YouTube Analytics for ${report.channel.title}`);
    const ctx = canvas.getContext('2d'), rows = report.rows, version = state.version;
    const number = n => new Intl.NumberFormat('en', {maximumFractionDigits:1, notation:n>=1e7?'compact':'standard'}).format(n);
    const views = rows.reduce((sum,row) => sum + row.views, 0);
    const minutes = rows.reduce((sum,row) => sum + row.estimated_minutes_watched, 0);
    const subscribers = rows.reduce((sum,row) => sum + row.subscribers_gained, 0);
    ctx.fillStyle = '#151622'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#c1b2ff'; ctx.font = '700 19px sans-serif'; ctx.fillText('VIMAX  /  YOUTUBE ANALYTICS', 48, 52);
    ctx.fillStyle = '#f5f2ff'; ctx.font = '700 32px sans-serif'; ctx.fillText(report.channel.title, 48, 101, 900);
    ctx.fillStyle = '#b7b2ca'; ctx.font = '18px sans-serif';
    ctx.fillText(`Requested ${report.requested_start} to ${report.requested_end}  •  latest reported ${report.latest_data}`, 48, 134, 900);
    const cards = [['VIEWS',number(views)], ['WATCH TIME (MIN)',number(minutes)], ['SUBSCRIBERS GAINED',number(subscribers)]];
    cards.forEach(([label,value],i)=>{
      const x=48+i*305; ctx.fillStyle='#232435'; ctx.fillRect(x,164,280,90);
      ctx.fillStyle='#aba5bf'; ctx.font='700 14px sans-serif'; ctx.fillText(label,x+16,193,248);
      ctx.fillStyle='#f6f3ff'; ctx.font='700 28px sans-serif'; ctx.fillText(value,x+16,229,248);
    });
    ctx.fillStyle='#d9d3ea'; ctx.font='700 17px sans-serif'; ctx.fillText('Views by reported day',48,297);
    const max=Math.max(1,...rows.map(row=>row.views)), left=48, top=321, width=900, height=168, step=width/rows.length;
    ctx.fillStyle='#aaa4ba'; ctx.font='14px sans-serif'; ctx.fillText(number(max),left,top-7);
    ctx.strokeStyle='#464257'; ctx.beginPath(); ctx.moveTo(left,top+height); ctx.lineTo(left+width,top+height); ctx.stroke();
    rows.forEach((row,i)=>{
      const barHeight=row.views/max*height, barWidth=Math.max(4,Math.min(24,step*.65));
      ctx.fillStyle='#b3a0ff'; ctx.fillRect(left+i*step+(step-barWidth)/2,top+height-barHeight,barWidth,barHeight);
    });
    ctx.fillStyle='#aaa4ba'; ctx.font='14px sans-serif'; ctx.fillText(rows[0].day,left,514); ctx.textAlign='right';
    ctx.fillText(rows.at(-1).day,left+width,514); ctx.textAlign='left';
    ctx.fillStyle='#9e98ad'; ctx.font='14px sans-serif';
    ctx.fillText('ViMax visualization, not a YouTube Studio screenshot. Data may be delayed.',48,559,900);
    const summary = element('p', `${number(views)} views · ${number(minutes)} watch minutes · ${number(subscribers)} subscribers gained`, 'analytics-summary');
    const caption = element('figcaption', 'ViMax visualization from YouTube Analytics. Missing days are not estimated; data may be delayed. The chart is not saved in chat history; save a copy if needed.', 'hint');
    const save = element('button', 'Save image', 'secondary-button analytics-save'); save.type = 'button';
    save.addEventListener('click', () => canvas.toBlob(blob => {
      if (!blob || !isCurrent(version)) return;
      const url = URL.createObjectURL(blob), link = element('a'); link.href = url; link.download = 'vimax-youtube-analytics.png'; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, 'image/png'));
    figure.append(canvas, summary, caption, save); return figure;
  }
  function renderMessages() {
    const container = $('messages'); container.replaceChildren();
    const turns = state.chat.turns.slice(-30);
    const add = (role, text, pending = false) => {
      const row = element('article', null, `message ${role}${pending ? ' pending' : ''}`);
      const avatar = element('div', role === 'user' ? 'Y' : '✦', 'message-avatar'); avatar.setAttribute('aria-hidden', 'true');
      const body = element('div', null, 'message-body');
      body.append(element('p', role === 'user' ? 'You' : 'ViMax', 'message-role'), element('p', text, 'message-text'));
      row.append(avatar, body); container.append(row); return body;
    };
    for (const turn of turns) {
      if (typeof turn.prompt === 'string') add('user', turn.prompt);
      if (typeof turn.reply === 'string') {
        const body = add('assistant', turn.reply);
        if (turn.analytics && Array.isArray(turn.analytics.rows) && turn.analytics.rows.length) body.append(analyticsFigure(turn.analytics));
      }
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
    $('channel-manage').disabled = !state.user;
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
    updateChatControls();
  }
  function selectedFacebook() { return state.facebook.saved.find(page => page.id === $('facebook-select').value); }
  function renderFacebookList() {
    const select = $('facebook-select'), previous = select.value, pages = state.facebook.saved;
    select.replaceChildren();
    if (!pages.length) makeOption(select, '', 'No saved Pages');
    for (const page of pages) makeOption(select, page.id, `${page.display_name} (${page.external_id})${page.status === 'active' ? '' : ' — reconnect required'}`);
    const chosen = pages.find(page => page.id === previous) || pages.find(page => page.id === state.facebook.verified)
      || pages.find(page => page.is_default) || pages[0];
    if (chosen) select.value = chosen.id;
  }
  function updateFacebookControls() {
    const fb = state.facebook, page = selectedFacebook(), available = Boolean(state.user && fb.ready && fb.configured && fb.allowed && !fb.busy);
    $('facebook-manage').disabled = !state.user;
    $('facebook-connect').disabled = !available;
    $('facebook-select').disabled = !state.user || fb.busy || !fb.saved.length;
    $('facebook-select-button').disabled = !available || !page || page.status !== 'active';
    $('facebook-disconnect').disabled = !state.user || fb.busy || !page;
    const verified = fb.saved.find(item => item.id === fb.verified && item.status === 'active');
    $('facebook-status').textContent = !state.user ? 'Sign in to manage Facebook Pages.'
      : fb.error && !fb.ready ? 'Could not check Facebook setup.' : !fb.ready ? 'Checking Facebook setup…'
      : !fb.configured ? 'Facebook developer app setup is incomplete.'
      : !fb.allowed ? 'Facebook access is not enabled for this account.' : fb.busy ? 'Checking Facebook connection…'
      : verified ? `Verified this session: ${verified.display_name}` : fb.saved.length ? 'Choose a saved Page or reconnect.' : 'Connect a Facebook account to list Pages.';
    $('facebook-message').textContent = fb.notice; $('facebook-error').textContent = fb.error;
  }
  function updateGoogleControls() {
    $('signin-area').hidden = Boolean(state.user);
    // Offer honest help instead of an inert Google button when setup is missing.
    // Email fallback remains available if either check failed.
    const help = state.session === 'error' || (state.session === 'signed-out' && ['disabled','unknown'].includes(state.google.status));
    const ready = state.session === 'signed-out' && state.google.status === 'enabled';
    $('account-button').hidden = !state.user && state.session !== 'error' && state.google.status === 'enabled' && !state.google.error;
    $('google-signin-label').textContent = help ? 'Google sign-in help' : 'Continue with Google';
    $('google-signin').disabled = state.authBusy || !(help || ready);
    $('google-signin-status').textContent = state.session === 'error' ? 'Account service unavailable. Tap for help.'
      : state.google.error || (state.google.status === 'checking' ? 'Checking Google sign-in…'
        : state.google.status === 'unknown' ? 'Google sign-in could not be checked. Tap for help.'
        : state.google.status === 'disabled' ? 'Google sign-in setup needed. Tap for help.' : 'Sign in, then allow channel access');
  }
  function updateAccount() {
    const loggedIn = Boolean(state.user);
    $('account-button').textContent = loggedIn ? 'Account' : 'Email sign in';
    $('account-form').hidden = loggedIn;
    $('account-signed-in').hidden = !loggedIn;
    $('account-title').textContent = loggedIn ? 'Your ViMax account' : 'Sign in to ViMax';
    $('account-identity').textContent = loggedIn ? state.user.email : '';
    $('account-id').textContent = loggedIn ? `Account ID: ${state.user.id}` : '';
    updateGoogleControls();
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
    state.channel = {ready:false, configured:false, allowed:false, analyticsConfigured:false, analyticsConnected:false, busy:false, connected:null, connectionId:null, saved:[], autoAttempted:false, sequence:0, notice:'', error:''};
    state.facebook = {ready:false, configured:false, allowed:false, busy:false, saved:[], verified:null, autoAttempted:false, sequence:0, notice:'', error:''};
    $('chat-prompt').value = ''; $('account-password').value = ''; $('speak-replies').checked = false;
    $('settings-message').textContent = ''; $('account-error').textContent = ''; $('account-message').textContent = '';
    closeDialog('channel-dialog'); closeDialog('facebook-dialog'); closeDialog('settings-dialog');
    renderMessages(); renderProviders(); renderChannelList(); renderFacebookList(); updateAccount(); updateChannelControls(); updateFacebookControls(); updateChatControls();
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
      channel.analyticsConfigured = data.analytics_configured === true; channel.analyticsConnected = data.analytics_connected === true;
      channel.saved = Array.isArray(data.saved_channels) ? data.saved_channels.filter(item => item && typeof item.id === 'string'
        && typeof item.channel_id === 'string' && typeof item.channel_title === 'string' && ['active','needs_reauth','uncertain'].includes(item.status)) : [];
      channel.connected = data.connected === true && typeof data.channel?.title === 'string' && typeof data.channel?.id === 'string'
        ? {id:data.channel.id, title:data.channel.title} : null;
      channel.connectionId = typeof data.connection_id === 'string' ? data.connection_id : null;
      channel.error = '';
      state.deployment.youtube = channel.configured ? 'configured_unverified' : 'unavailable';
      renderChannelList(); updateChannelControls();
      const savedDefault = channel.saved.find(item => item.is_default);
      if (channel.connected) autoConnectAfterLogin = false;
      else if (channel.configured && channel.allowed && savedDefault?.status === 'active' && !channel.autoAttempted && !channel.busy) {
        autoConnectAfterLogin = false; channel.autoAttempted = true;
        await selectChannel(version, savedDefault.id, true);
      } else if (autoConnectAfterLogin) {
        // Only a fresh Google sign-in started in this tab can launch the first
        // channel consent automatically. A crafted callback URL alone cannot.
        autoConnectAfterLogin = false;
        if (channel.configured && channel.allowed && !channel.saved.length && !channel.busy) await startChannel(version);
        else {
          channel.notice = channel.saved.length ? 'Choose a saved channel or reconnect it with Google.' : 'Channel setup must be completed before you can connect.';
          updateChannelControls(); showDialog('channel-dialog');
        }
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
  async function loadFacebook(version) {
    if (!isCurrent(version)) return;
    const sequence = ++state.facebook.sequence;
    try {
      const data = await sessionApi('/api/cloud/social/status');
      if (!isCurrent(version) || sequence !== state.facebook.sequence) return;
      const fb = state.facebook, config = data?.providers?.facebook || {};
      fb.ready = true; fb.configured = config.configured === true; fb.allowed = config.allowed === true;
      fb.saved = Array.isArray(data.connections) ? data.connections.filter(page => page && page.provider === 'facebook' && typeof page.id === 'string'
        && typeof page.external_id === 'string' && typeof page.display_name === 'string' && ['active','needs_reauth','uncertain'].includes(page.status)) : [];
      if (!fb.saved.some(page => page.id === fb.verified && page.status === 'active')) fb.verified = null;
      fb.error = ''; renderFacebookList(); updateFacebookControls();
      const savedDefault = fb.saved.find(page => page.is_default && page.status === 'active');
      if (fb.configured && fb.allowed && savedDefault && !fb.verified && !fb.autoAttempted && !fb.busy) {
        fb.autoAttempted = true; await selectFacebook(version, savedDefault.id, true);
      }
    } catch (error) {
      if (isCurrent(version) && sequence === state.facebook.sequence && error.name !== 'AbortError') {
        state.facebook.ready = false; state.facebook.error = error.message; updateFacebookControls();
      }
    }
  }
  async function selectFacebook(version, id, automatic = false) {
    const fb = state.facebook;
    if (!isCurrent(version) || !fb.ready || !fb.configured || !fb.allowed || fb.busy || !id) return;
    fb.busy = true; fb.error = ''; fb.notice = automatic ? '' : 'Checking this Page…'; updateFacebookControls();
    try {
      const data = await post('/api/cloud/social/facebook/select', {id});
      if (!isCurrent(version)) return;
      if (data?.connection?.id !== id || data.connection.provider !== 'facebook') throw new Error('Facebook did not confirm this Page.');
      fb.verified = id; fb.busy = false; fb.notice = automatic ? '' : 'Facebook confirmed the selected Page for this session.';
      await loadFacebook(version);
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') { fb.verified = null; fb.error = error.message; fb.notice = 'The Page was not restored. Reconnect if needed.'; }
    } finally { if (isCurrent(version)) { fb.busy = false; updateFacebookControls(); } }
  }
  function applySession(user, sessionState = 'signed-out') {
    const version = resetForSession(user, sessionState);
    if (!state.user) return;
    // Account sign-in and sign-out must not wait on provider or channel calls.
    // Each loader is owner-versioned and is cancelled on an account change.
    void Promise.all([loadProviders(version), loadHistory(version), loadChannel(version), loadFacebook(version)]).catch(() => {
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

  async function checkGoogleSignIn() {
    try {
      const data = await api('/api/cloud/google/status');
      state.google.status = data?.enabled === true ? 'enabled' : 'disabled';
    } catch { state.google.status = 'unknown'; }
    updateGoogleControls();
  }
  $('google-signin').addEventListener('click', async () => {
    if (state.user || state.authBusy) return;
    if (state.session === 'error' || (state.session === 'signed-out' && ['disabled','unknown'].includes(state.google.status))) {
      $('account-error').textContent = '';
      $('account-message').textContent = state.session === 'error'
        ? 'The account service could not be checked. Refresh and try again, or try email sign-in below.'
        : state.google.status === 'unknown'
          ? 'Google sign-in could not be checked. Refresh and try again, or use email sign-in below.'
          : 'Google sign-in is not set up yet. To confirm your existing account, enter your email and choose Resend confirmation email. No password is needed for that step. The app owner must still complete Google setup.';
      showDialog('account-dialog');
      $('account-email').focus();
      return;
    }
    if (state.session !== 'signed-out' || state.google.status !== 'enabled') return;
    state.authBusy = true; state.google.error = '';
    const sequence = ++state.sessionSequence; updateGoogleControls();
    try {
      const data = await api('/api/cloud/google/start', {method:'POST', body:'{}'});
      let url;
      try { url = new URL(data?.authorization_url); } catch { throw new Error('Invalid Google sign-in URL.'); }
      if (url.protocol !== 'https:' || !/^[a-z0-9-]+\.supabase\.co$/.test(url.hostname) || url.port || url.username || url.password || url.hash
          || url.pathname !== '/auth/v1/authorize' || url.searchParams.get('provider') !== 'google') throw new Error('Invalid Google sign-in URL.');
      if (sequence !== state.sessionSequence || state.user) return;
      // This nonsensitive, tab-scoped intent allows the first YouTube consent
      // after app sign-in. URL parameters alone cannot trigger that redirect.
      try { sessionStorage.setItem('vimax-google-channel-intent', String(Date.now())); } catch {}
      window.location.assign(url.href);
    } catch (error) {
      if (sequence === state.sessionSequence) state.google.error = error.message;
    } finally { state.authBusy = false; updateGoogleControls(); }
  });
  $('account-button').addEventListener('click', () => showDialog('account-dialog'));
  $('chat-settings').addEventListener('click', () => showDialog('settings-dialog'));
  $('channel-manage').addEventListener('click', () => { if (state.user) { closeDialog('account-dialog'); showDialog('channel-dialog'); } });
  $('facebook-manage').addEventListener('click', () => { if (state.user) { closeDialog('account-dialog'); showDialog('facebook-dialog'); } });
  document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => closeDialog(button.dataset.close)));
  $('account-dialog').addEventListener('close', () => { $('account-password').value = ''; });
  $('account-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (state.authBusy) return;
    const form = event.currentTarget, action = event.submitter?.value === 'signup' ? 'signup' : 'login';
    const input = {email:$('account-email').value.trim(), password:$('account-password').value};
    state.authBusy = true; state.sessionSequence++; updateGoogleControls();
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
    finally { state.authBusy = false; form.querySelectorAll('button').forEach(button => { button.disabled = false; }); updateGoogleControls(); }
  });
  $('resend-confirmation').addEventListener('click', async () => {
    if (state.authBusy || !$('account-email').reportValidity()) return;
    state.authBusy = true; updateGoogleControls(); $('account-error').textContent = ''; $('account-message').textContent = '';
    $('resend-confirmation').disabled = true;
    try {
      const data = await api('/api/cloud/resend-confirmation', {method:'POST', body:JSON.stringify({email:$('account-email').value.trim()})});
      $('account-message').textContent = data.message;
    } catch (error) { $('account-error').textContent = error.message; }
    finally { state.authBusy = false; $('resend-confirmation').disabled = false; updateGoogleControls(); }
  });
  $('logout').addEventListener('click', async () => {
    if (state.authBusy || !state.user) return;
    state.authBusy = true; state.sessionSequence++; autoConnectAfterLogin = false;
    try { sessionStorage.removeItem('vimax-google-channel-intent'); } catch {}
    // Immediately discard owner data and ignore late requests. A provider call
    // already received by the server can still finish or incur charges.
    await applySession(null, 'signed-out');
    try { await api('/api/cloud/logout', {method:'POST', body:'{}'}); closeDialog('account-dialog'); }
    catch { state.session = 'error'; $('account-error').textContent = 'Sign-out could not be confirmed. Refresh and try again.'; updateChatControls(); updateChannelControls(); }
    finally { state.authBusy = false; updateGoogleControls(); }
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
    const analytics = isAnalyticsRequest(prompt), connectionId = state.channel.connectionId, channelId = state.channel.connected?.id;
    const provider = $('provider').value, model = $('model').value, fallbackValue = $('fallback').value, divider = fallbackValue.indexOf('|');
    const fallback = fallbackValue && divider > 0 ? {provider:fallbackValue.slice(0, divider), model:fallbackValue.slice(divider + 1)} : null;
    if (!analytics && fallback && fallback.provider === provider && fallback.model === model) { state.chat.error = 'Choose a different fallback or turn it off.'; updateChatControls(); return; }
    state.chat.busy = true; state.chat.pending = prompt; state.chat.error = ''; state.chat.note = '';
    renderMessages(); updateChatControls();
    try {
      if (analytics) {
        if (!state.channel.analyticsConfigured) throw new Error('YouTube Analytics has not been enabled by the deployment owner.');
        if (!state.channel.analyticsConnected) throw new Error('Open Account → YouTube channels → Add channel with Google, and allow Analytics access for this channel.');
        const data = await post('/api/cloud/youtube/analytics');
        if (!isCurrent(version)) return;
        if (connectionId !== state.channel.connectionId || data?.channel?.id !== channelId) throw new Error('The selected channel changed. Select the intended channel and ask again.');
        if (!Array.isArray(data.rows) || data.rows.length > 30 || typeof data.channel.title !== 'string'
            || typeof data.requested_start !== 'string' || typeof data.requested_end !== 'string'
            || (data.rows.length && data.latest_data !== data.rows.at(-1)?.day)
            || data.rows.some(row => !row || typeof row.day !== 'string' || !Number.isSafeInteger(row.views) || row.views < 0
              || !Number.isFinite(row.estimated_minutes_watched) || row.estimated_minutes_watched < 0
              || !Number.isSafeInteger(row.subscribers_gained) || row.subscribers_gained < 0)) throw new Error('YouTube returned an invalid report.');
        const reply = data.rows.length
          ? `Here is a ViMax chart for ${data.channel.title}, using the available YouTube Analytics data from ${data.requested_start} to ${data.requested_end}. The latest reported day is ${data.latest_data}; data can be delayed. This is not a YouTube Studio screenshot.`
          : `YouTube returned no daily analytics rows for ${data.channel.title} from ${data.requested_start} to ${data.requested_end}. No image was created; the data may not be available yet.`;
        state.chat.turns.push({prompt, reply, analytics:data.rows.length ? data : null}); state.chat.pending = null;
        if ($('chat-prompt').value.trim() === prompt) $('chat-prompt').value = '';
        state.chat.note = 'Analytics report is only kept in this browser tab; request it again after refreshing.';
        renderMessages(); if ($('speak-replies').checked) speak(reply);
      } else {
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
      }
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') {
        state.chat.pending = null;
        if (analytics) {
          state.chat.turns.push({prompt,reply:`I could not create an analytics image. ${error.message}`});
          if ($('chat-prompt').value.trim() === prompt) $('chat-prompt').value = '';
          state.chat.note = 'No analytics image was created.';
        } else { state.chat.error = error.message; state.chat.note = 'No reply received.'; }
        renderMessages();
      }
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

  async function startChannel(version) {
    if (!isCurrent(version) || !canConnect()) return;
    state.channel.busy = true; state.channel.error = ''; state.channel.notice = ''; updateChannelControls();
    try {
      const data = await post('/api/cloud/youtube/oauth/start', state.channel.analyticsConfigured ? {analytics:true} : {});
      let url;
      try { url = new URL(data?.authorization_url); } catch { throw new Error('Invalid Google authorization URL.'); }
      if (url.origin !== 'https://accounts.google.com' || url.pathname !== '/o/oauth2/v2/auth' || url.username || url.password) throw new Error('Invalid Google authorization URL.');
      if (isCurrent(version)) window.location.assign(url.href);
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') { state.channel.error = error.message; state.channel.notice = ''; showDialog('channel-dialog'); }
    } finally { if (isCurrent(version)) { state.channel.busy = false; updateChannelControls(); } }
  }
  $('google-connect').addEventListener('click', () => { void startChannel(state.version); });
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

  $('facebook-connect').addEventListener('click', async () => {
    const fb = state.facebook, version = state.version;
    if (!isCurrent(version) || !fb.ready || !fb.configured || !fb.allowed || fb.busy) return;
    fb.busy = true; fb.error = ''; fb.notice = ''; updateFacebookControls();
    try {
      const data = await post('/api/cloud/social/facebook/start');
      let url;
      try { url = new URL(data?.authorization_url); } catch { throw new Error('Invalid Facebook authorization URL.'); }
      if (url.origin !== 'https://www.facebook.com' || url.pathname !== '/v26.0/dialog/oauth' || url.username || url.password || url.hash) throw new Error('Invalid Facebook authorization URL.');
      if (isCurrent(version)) window.location.assign(url.href);
    } catch (error) { if (isCurrent(version) && error.name !== 'AbortError') fb.error = error.message; }
    finally { if (isCurrent(version)) { fb.busy = false; updateFacebookControls(); } }
  });
  $('facebook-select').addEventListener('change', updateFacebookControls);
  $('facebook-select-button').addEventListener('click', () => {
    const page = selectedFacebook(); if (!page || page.status !== 'active') return;
    state.facebook.autoAttempted = true; void selectFacebook(state.version, page.id);
  });
  $('facebook-disconnect').addEventListener('click', async () => {
    const page = selectedFacebook(), fb = state.facebook;
    if (!state.user || fb.busy || !page || !confirm('Remove this Page from ViMax? This does not revoke the Facebook app grant; review access in Facebook settings.')) return;
    const version = state.version; fb.busy = true; fb.autoAttempted = true; fb.error = ''; fb.notice = ''; updateFacebookControls();
    try {
      await post('/api/cloud/social/facebook/disconnect', {id:page.id});
      if (!isCurrent(version)) return;
      if (fb.verified === page.id) fb.verified = null;
      fb.busy = false; fb.notice = 'Page removed from ViMax. Facebook app access was not revoked.';
      await loadFacebook(version);
    } catch (error) { if (isCurrent(version) && error.name !== 'AbortError') fb.error = error.message; }
    finally { if (isCurrent(version)) { fb.busy = false; updateFacebookControls(); } }
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
  const currentUrl = new URL(window.location.href), googleResult = currentUrl.searchParams.get('google_signin');
  let cleaned = false;
  for (const key of ['youtube','social','google_signin']) if (currentUrl.searchParams.has(key)) { currentUrl.searchParams.delete(key); cleaned = true; }
  if (['#youtube','#social-connections'].includes(currentUrl.hash) && cleaned) currentUrl.hash = '';
  if (cleaned) history.replaceState(null, '', currentUrl.pathname + currentUrl.search + currentUrl.hash);
  let confirmation = null;
  try {
    confirmation = sessionStorage.getItem('vimax-email-confirmed'); sessionStorage.removeItem('vimax-email-confirmed');
    if (googleResult) {
      const intent = sessionStorage.getItem('vimax-google-channel-intent'), age = Date.now() - Number(intent);
      autoConnectAfterLogin = googleResult === 'success' && Boolean(intent) && age >= 0 && age < 600_000;
      sessionStorage.removeItem('vimax-google-channel-intent');
    }
  } catch {}
  if (googleResult === 'failed') state.google.error = 'Google sign-in did not complete. Try again.';
  renderMessages(); renderProviders(); renderChannelList(); renderFacebookList(); updateAccount(); updateChannelControls(); updateFacebookControls(); updateChatControls();
  void checkDeployment(); void checkGoogleSignIn();
  void checkSession().then(() => {
    if (googleResult === 'success' && !state.user) { autoConnectAfterLogin = false; state.google.error = 'Google sign-in could not be confirmed. Try again.'; updateGoogleControls(); }
    if (confirmation && !state.user) {
      $('account-message').textContent = confirmation === 'yes' ? 'Email confirmed. Please sign in.' : 'Email confirmation failed or expired; please try again.';
      showDialog('account-dialog');
    }
  });
})();
