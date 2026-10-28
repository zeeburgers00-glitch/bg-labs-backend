'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state = {
    user:null, session:'loading', sessionSequence:0, version:0, controllers:new Set(), authBusy:false,
    deployment:{chat:'checking', youtube:'checking'},
    google:{status:'checking', checking:false, rechecking:false, error:''},
    chat:{providers:[], pexels:'unknown', allowed:false, paused:false, settingsReady:false, historyReady:false, busy:false, testing:false, tests:new Map(), usageLoading:false, turns:[], pending:null, note:'', error:''},
    channel:{ready:false, configured:false, allowed:false, analyticsConfigured:false, analyticsConnected:false, busy:false, connected:null, connectionId:null, saved:[], autoAttempted:false, sequence:0, notice:'', error:''},
    facebook:{ready:false, configured:false, allowed:false, busy:false, saved:[], verified:null, autoAttempted:false, sequence:0, notice:'', error:''},
    workforce:{loaded:false, loading:false, busy:false, agentsLoaded:false, agentsLoading:false, reviewBusy:false, researchLoaded:false, researchLoading:false, researchReady:false, researchBusy:false},
  };
  let offerChannelAfterLogin = false;
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
  // The server enforces the same rule; the UI mirrors it for clarity.
  const noAutomaticFallback = (provider, model) => provider === 'vercel'
    || (provider === 'openrouter' && (model === 'openrouter/free' || model.endsWith(':free')))
    || (provider === 'zai' && ['glm-4.7-flash','glm-4.5-flash'].includes(model));
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
    if (noAutomaticFallback($('provider').value, $('model').value)) $('fallback').value = '';
    updateChatControls();
  }
  function renderProviders() {
    const providers = availableProviders();
    setOptions($('provider'), providers.map(item => [item.id, item.label]), 'No provider configured');
    const fallback = $('fallback'), previous = fallback.value;
    fallback.replaceChildren(); makeOption(fallback, '', 'No fallback');
    for (const provider of providers) for (const model of provider.models) makeOption(fallback, `${provider.id}|${model}`, `${provider.label} · ${model}`);
    if (Array.from(fallback.options).some(option => option.value === previous)) fallback.value = previous;
    const status = $('provider-status-list'); status.replaceChildren();
    if (!state.user || !state.chat.settingsReady) status.append(element('li', state.user ? 'Checking configuration…' : 'Sign in to view configuration status.'));
    else {
      const names = {groq:'GROQ_API_KEY',gemini:'GEMINI_API_KEY',mistral:'MISTRAL_API_KEY',zai:'ZAI_API_KEY',openrouter:'OPENROUTER_API_KEY',huggingface:'HF_TOKEN',opencode:'OPENCODE_API_KEY',openai:'OPENAI_API_KEY',vercel:'VIMAX_GATEWAY_FREE_ENABLED'};
      const states = {not_configured:'Not configured',configured_unverified:'Configured, not verified',invalid_configuration:'Invalid configuration',model_required:'Model list required',unknown:'Unknown'};
      for (const provider of state.chat.providers) {
        if (!provider || typeof provider.label !== 'string' || typeof provider.id !== 'string') continue;
        const tested = Array.from(state.chat.tests.entries()).filter(([key]) => key.startsWith(`${provider.id}|`)).at(-1);
        const result = tested ? ` · ${tested[1].summary}` : '';
        status.append(element('li', `${provider.label}: ${states[provider.state] || 'Unknown'}${names[provider.id] ? ` · ${names[provider.id]}` : ''}${result}`));
      }
      status.append(element('li', `Pexels stock: ${states[state.chat.pexels] || 'Unknown'} · PEXELS_API_KEY`));
      status.append(element('li', 'Hacker AI: Not implemented'));
    }
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
    // General text chat does not require a YouTube grant. Analytics still
    // requires the selected authorized channel and never uses the text model.
    const readyForRequest = analytics ? state.channel.ready && state.channel.connected : $('provider').value && $('model').value;
    return Boolean(state.user && state.chat.settingsReady && state.chat.historyReady && state.chat.allowed
      && !state.chat.paused && !state.chat.busy && readyForRequest);
  }
  function updateChatControls() {
    const chat = state.chat;
    $('chat-send').disabled = !canChat() || !$('chat-prompt').value.trim();
    $('provider').disabled = chat.busy || !availableProviders().length;
    $('model').disabled = chat.busy || !availableProviders().length;
    const providerId = $('provider').value, model = $('model').value;
    const noFallback = noAutomaticFallback(providerId, model);
    if (noFallback) $('fallback').value = '';
    $('fallback').disabled = chat.busy || !availableProviders().length || noFallback;
    $('provider-test').disabled = !state.user || !chat.settingsReady || !chat.allowed || chat.paused || chat.busy || !providerId || !model;
    $('free-route-hint').hidden = !noFallback;
    $('openrouter-privacy').hidden = providerId !== 'openrouter' && !$('fallback').value.startsWith('openrouter|');
    const tested = chat.tests.get(`${providerId}|${model}`);
    $('provider-test-message').textContent = chat.testing ? 'Testing the selected provider…'
      : tested?.detail || (providerId && model ? 'Not tested in this browser session.' : 'Sign in and configure a provider to test it.');
    $('answer-length').disabled = chat.busy;
    $('clear-history').disabled = !state.user || !chat.historyReady || chat.busy;
    $('usage-refresh').disabled = !state.user || chat.usageLoading;
    $('toggle-pause').disabled = !state.user || !chat.settingsReady || chat.busy;
    $('toggle-pause').textContent = chat.paused ? 'Resume chat' : 'Pause chat';
    const selected = availableProviders().find(provider => provider.id === $('provider').value);
    const analytics = isAnalyticsRequest($('chat-prompt').value);
    $('gateway-privacy').hidden = selected?.id !== 'vercel' && !$('fallback').value.startsWith('vercel|');
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
    else if (chat.busy) status = chat.testing ? 'Testing the selected provider…' : 'Waiting for a reply…';
    else if (analytics && !state.channel.ready && state.channel.error) status = 'Channel status could not be checked. Open Account to try again.';
    else if (analytics && !state.channel.ready) status = 'Checking your channel connection…';
    else if (analytics && !state.channel.configured) status = 'YouTube channel setup is incomplete.';
    else if (analytics && !state.channel.allowed) status = 'YouTube channel access is not enabled for this account.';
    else if (analytics && state.channel.busy) status = 'Restoring your channel…';
    else if (analytics && !state.channel.connected) status = 'Connect a YouTube channel in Account to request analytics.';
    else if (!availableProviders().length && analytics && state.channel.analyticsConfigured)
      status = 'Analytics can be requested separately; an AI provider is still needed for general chat.';
    else if (!availableProviders().length && !analytics) status = 'No AI provider is configured. The deployment owner needs to finish setup.';
    else if (selected?.id === 'vercel') status = chat.note || 'Free AI configured but not yet verified. YouTube features need a separate channel connection.';
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
    // Keep email sign-in reachable even when Google is enabled or fails.
    $('account-button').hidden = false;
    $('account-google').hidden = !ready;
    $('account-google-signin').disabled = state.authBusy || !ready;
    $('google-setup-help').hidden = Boolean(state.user) || (state.session !== 'error' && state.google.status === 'enabled');
    $('google-recheck').disabled = state.authBusy || state.google.checking || state.google.rechecking || state.session === 'loading';
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
    $('workforce-open').hidden = !loggedIn;
    updateGoogleControls();
  }
  function closeDialog(id) { const dialog = $(id); if (dialog.open) dialog.close(); }
  function showDialog(id) { const dialog = $(id); if (!dialog.open) dialog.showModal(); }
  function resetForSession(user, sessionState) {
    state.version++;
    for (const controller of state.controllers) controller.abort();
    state.controllers.clear();
    stopAllSpeech();
    // A disclosure accepted by one signed-in user must not carry over to the
    // next person using the same browser tab.
    voiceDisclosureAccepted = false;
    state.user = user && typeof user.id === 'string' ? {id:user.id, email:typeof user.email === 'string' ? user.email : ''} : null;
    state.session = state.user ? 'signed-in' : sessionState;
    state.chat = {providers:[], pexels:'unknown', allowed:false, paused:false, settingsReady:false, historyReady:false, busy:false, testing:false, tests:new Map(), usageLoading:false, turns:[], pending:null, note:'', error:''};
    state.channel = {ready:false, configured:false, allowed:false, analyticsConfigured:false, analyticsConnected:false, busy:false, connected:null, connectionId:null, saved:[], autoAttempted:false, sequence:0, notice:'', error:''};
    state.facebook = {ready:false, configured:false, allowed:false, busy:false, saved:[], verified:null, autoAttempted:false, sequence:0, notice:'', error:''};
    state.workforce = {loaded:false, loading:false, busy:false, agentsLoaded:false, agentsLoading:false, reviewBusy:false, researchLoaded:false, researchLoading:false, researchReady:false, researchBusy:false};
    $('public-research-form').reset(); for (const field of $('public-research-form').elements) field.disabled = false;
    $('public-research-submit').disabled = true; $('public-research-setup').textContent = 'Checking setup…';
    $('public-research-status').textContent = ''; $('public-research-error').textContent = ''; $('public-research-notice').textContent = '';
    $('public-research-result').hidden = true; $('public-research-data').replaceChildren();
    $('creator-review-form').reset(); for (const field of $('creator-review-form').elements) field.disabled = false;
    $('creator-review-status').textContent = ''; $('creator-review-error').textContent = ''; $('creator-review-notice').textContent = '';
    $('creator-review-result').hidden = true; $('creator-review-steps').replaceChildren(); $('creator-metrics-options').open = false;
    $('agent-registry-status').textContent = ''; $('agent-departments').replaceChildren();
    $('preflight-form').reset(); for (const field of $('preflight-form').elements) field.disabled = false;
    $('preflight-status').textContent = ''; $('preflight-error').textContent = ''; $('preflight-notice').textContent = '';
    $('preflight-result').hidden = true; $('preflight-notes').replaceChildren(); $('preflight-preview').textContent = '';
    $('registry-status').textContent = ''; $('registry-list').replaceChildren(); $('role-plan-list').replaceChildren(); document.querySelector('.slot-plan').open = false;
    $('chat-prompt').value = ''; $('account-password').value = ''; $('speak-replies').checked = false;
    $('settings-message').textContent = ''; $('account-error').textContent = ''; $('account-message').textContent = '';
    $('usage-message').textContent = ''; $('usage-list').replaceChildren();
    closeDialog('channel-dialog'); closeDialog('facebook-dialog'); closeDialog('settings-dialog'); closeDialog('workforce-dialog');
    renderMessages(); renderProviders(); renderChannelList(); renderFacebookList(); updateAccount(); updateChannelControls(); updateFacebookControls(); updateChatControls();
    return state.version;
  }
  async function loadProviders(version) {
    try {
      const data = await sessionApi('/api/cloud/providers');
      if (!isCurrent(version)) return;
      state.chat.providers = Array.isArray(data.providers) ? data.providers : [];
      state.chat.pexels = typeof data.pexels === 'string' ? data.pexels : 'unknown';
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
      if (channel.connected) offerChannelAfterLogin = false;
      else if (channel.configured && channel.allowed && savedDefault?.status === 'active' && !channel.autoAttempted && !channel.busy) {
        offerChannelAfterLogin = false; channel.autoAttempted = true;
        await selectChannel(version, savedDefault.id, true);
      } else if (offerChannelAfterLogin) {
        // App login and channel authorization are separate. A fresh login may
        // offer the channel dialog, but must not navigate away to another OAuth
        // flow until the user explicitly chooses to connect a channel.
        offerChannelAfterLogin = false;
        channel.notice = channel.saved.length ? 'Signed in. Choose a saved channel or reconnect it with Google.'
          : channel.configured && channel.allowed ? 'Signed in. Choose Add channel with Google when you are ready to grant separate access.'
          : 'Signed in. Channel setup must be completed before you can connect.';
        updateChannelControls(); showDialog('channel-dialog');
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
    if (state.google.checking) return;
    const previous = state.google.status, controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15_000);
    state.google.checking = true; state.google.status = 'checking'; updateGoogleControls();
    try {
      const data = await api('/api/cloud/google/status', {signal:controller.signal});
      state.google.status = data?.enabled === true ? 'enabled' : 'disabled';
    } catch { state.google.status = 'unknown'; }
    finally { clearTimeout(timer); state.google.checking = false; updateGoogleControls(); }
    if (previous !== 'enabled' && state.google.status === 'enabled' && state.session === 'signed-out'
        && !state.authBusy && $('account-dialog').open) {
      $('account-message').textContent = 'Google setup is enabled. Choose Continue with Google to try signing in.';
    }
  }
  $('google-recheck').addEventListener('click', async () => {
    if (state.user || state.authBusy || state.google.checking || state.google.rechecking) return;
    state.google.rechecking = true; state.google.error = ''; $('account-error').textContent = '';
    $('account-message').textContent = 'Checking Google sign-in…'; updateGoogleControls();
    try {
      if (state.session === 'error') await checkSession();
      await checkGoogleSignIn();
      if (state.user) return;
      $('account-message').textContent = state.session === 'error' ? 'The account service is still unavailable. Try again later.'
        : state.google.status === 'enabled' ? 'Google setup is enabled. Choose Continue with Google to try signing in.'
        : state.google.status === 'unknown' ? 'Google sign-in could not be checked. Try again later.'
        : 'Google sign-in still needs setup by the app owner. Email sign-in remains available.';
    } finally { state.google.rechecking = false; updateGoogleControls(); }
  });
  async function beginGoogleSignIn() {
    if (state.user || state.authBusy) return;
    if (state.session === 'error' || (state.session === 'signed-out' && ['disabled','unknown'].includes(state.google.status))) {
      $('account-error').textContent = '';
      $('account-message').textContent = state.session === 'error'
        ? 'The account service could not be checked. Refresh and try again, or try email sign-in below.'
        : state.google.status === 'unknown'
          ? 'Google sign-in could not be checked. Refresh and try again, or use email sign-in below.'
          : 'Google sign-in is not set up yet. The app owner must finish the Google and Supabase setup. You can use email sign-in below or resend a confirmation if needed. No password is needed to resend confirmation.';
      showDialog('account-dialog');
      $('account-email').focus();
      return;
    }
    if (state.session !== 'signed-out' || state.google.status !== 'enabled') return;
    state.authBusy = true; state.google.error = ''; $('account-error').textContent = '';
    const sequence = ++state.sessionSequence; updateGoogleControls();
    try {
      const data = await api('/api/cloud/google/start', {method:'POST', body:'{}'});
      let url;
      try { url = new URL(data?.authorization_url); } catch { throw new Error('Invalid Google sign-in URL.'); }
      if (url.protocol !== 'https:' || !/^[a-z0-9-]+\.supabase\.co$/.test(url.hostname) || url.port || url.username || url.password || url.hash
          || url.pathname !== '/auth/v1/authorize' || url.searchParams.get('provider') !== 'google') throw new Error('Invalid Google sign-in URL.');
      if (sequence !== state.sessionSequence || state.user) return;
      // This nonsensitive, tab-scoped intent allows an optional channel dialog
      // after app sign-in. URL parameters alone cannot trigger that prompt.
      try { sessionStorage.setItem('vimax-google-channel-intent', String(Date.now())); } catch {}
      window.location.assign(url.href);
    } catch (error) {
      if (sequence === state.sessionSequence) {
        state.google.error = error.message;
        if ($('account-dialog').open) $('account-error').textContent = error.message;
      }
    } finally { state.authBusy = false; updateGoogleControls(); }
  }
  $('google-signin').addEventListener('click', beginGoogleSignIn);
  $('account-google-signin').addEventListener('click', beginGoogleSignIn);
  function renderWorkforceRegistry(data) {
    if (!Array.isArray(data?.skills) || data.skills.length > 100) throw new Error('The skill registry response is invalid.');
    const list = $('registry-list'); list.replaceChildren();
    const roles = $('role-plan-list'); roles.replaceChildren();
    if (Array.isArray(data.workforce_plan?.roles) && data.workforce_plan.roles.length <= 100) {
      for (const item of data.workforce_plan.roles) {
        if (typeof item?.role === 'string' && Number.isInteger(item.proposed_slots) && item.proposed_slots > 0) {
          roles.append(element('li', `${item.role}: ${item.proposed_slots} proposed slots`));
        }
      }
    }
    const labels = {integrated_hosted:'Hosted preview', integrated_local:'Local setup required', not_integrated:'Not installed'};
    for (const skill of data.skills) {
      if (!skill || typeof skill.name !== 'string' || typeof skill.setup_status !== 'string') continue;
      const details = element('details'), summary = element('summary', `${skill.name} · ${labels[skill.setup_status] || 'Unknown'}`);
      details.append(summary);
      const line = (label, value) => details.append(element('p', `${label}: ${value}`));
      const entries = value => Array.isArray(value) && value.length ? value.filter(x => typeof x === 'string').join(', ') : 'None';
      line('Proposed roles', entries(skill.agent_assignments));
      line('License', typeof skill.license === 'string' ? skill.license : 'Unknown');
      line('Credentials', entries(skill.required_credentials));
      line('Tool permissions', entries(skill.tool_permissions));
      line('Tests', `${skill.test_results?.status || 'unknown'} · ${skill.test_results?.scope || 'No test details'}`);
      if (typeof skill.notes === 'string') line('Notes', skill.notes);
      if (typeof skill.revision === 'string') line('Pinned revision', skill.revision);
      try {
        const url = new URL(skill.repository);
        if (url.origin === 'https://github.com' && !url.username && !url.password) {
          const source = element('a', 'View source'); source.href = url.href; source.target = '_blank'; source.rel = 'noopener noreferrer'; details.append(source);
        }
      } catch { /* Invalid source links are not clickable. */ }
      list.append(details);
    }
  }
  async function loadWorkforceRegistry(version) {
    if (!isCurrent(version) || state.workforce.loaded || state.workforce.loading) return;
    state.workforce.loading = true; $('registry-status').textContent = 'Loading registry…';
    try {
      const data = await sessionApi('/api/cloud/skills/registry');
      if (!isCurrent(version)) return;
      renderWorkforceRegistry(data); state.workforce.loaded = true;
      $('registry-status').textContent = `${data.skills.length} reviewed entries. Assignments do not start agents.`;
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') $('registry-status').textContent = `${error.message} Close and reopen to retry.`;
    } finally { if (isCurrent(version)) state.workforce.loading = false; }
  }
  function renderAgentRegistry(data) {
    if (!Array.isArray(data?.departments) || data.departments.length > 20 || !Array.isArray(data.roles) || data.roles.length > 200) throw new Error('The role registry response is invalid.');
    const container = $('agent-departments'); container.replaceChildren();
    const ready = data.roles.filter(role => role?.execution_status === 'implemented_read_only').length;
    const planned = data.roles.length - ready;
    $('agent-registry-status').textContent = `${data.roles.length} role specifications · ${ready} read-only roles tested locally · ${planned} awaiting integration. No role is a running worker.`;
    for (const name of data.departments) {
      if (typeof name !== 'string') continue;
      const members = data.roles.filter(role => role?.department === name && typeof role.name === 'string');
      const group = element('details', null, 'agent-department');
      group.append(element('summary', `${name} · ${members.length} roles`));
      for (const role of members) {
        const item = element('details', null, 'agent-role');
        const available = role.execution_status === 'implemented_read_only';
        item.append(element('summary', `${role.name} · ${available ? 'Read-only check available' : 'Awaiting integration'}`));
        const line = (label, value) => item.append(element('p', `${label}: ${value}`));
        const entries = values => Array.isArray(values) && values.length ? values.filter(x => typeof x === 'string').join(', ') : 'None';
        line('Responsibility', typeof role.responsibility === 'string' ? role.responsibility : 'Not specified');
        line('Assigned tool', entries(role.assigned_tools)); line('Required capability', entries(role.required_capabilities));
        line('Dependencies', entries(role.dependencies)); line('Tests', typeof role.test_status === 'string' ? role.test_status : 'unknown');
        line('Error handling', typeof role.error_handling === 'string' ? role.error_handling : 'Not specified');
        line('Success criteria', typeof role.success_criteria === 'string' ? role.success_criteria : 'Not specified');
        const schema = element('details', null, 'role-schema'); schema.append(element('summary', 'Input and output schemas'));
        schema.append(element('pre', JSON.stringify({input:role.input_schema, output:role.output_schema}, null, 2))); item.append(schema);
        group.append(item);
      }
      container.append(group);
    }
  }
  async function loadAgentRegistry(version) {
    if (!isCurrent(version) || state.workforce.agentsLoaded || state.workforce.agentsLoading) return;
    state.workforce.agentsLoading = true; $('agent-registry-status').textContent = 'Loading role specifications…';
    try {
      const data = await sessionApi('/api/cloud/agents');
      if (!isCurrent(version)) return;
      renderAgentRegistry(data); state.workforce.agentsLoaded = true;
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') $('agent-registry-status').textContent = `${error.message} Close and reopen to retry.`;
    } finally { if (isCurrent(version)) state.workforce.agentsLoading = false; }
  }
  async function loadPublicResearchStatus(version) {
    if (!isCurrent(version) || state.workforce.researchLoaded || state.workforce.researchLoading) return;
    state.workforce.researchLoading = true; $('public-research-setup').textContent = 'Checking setup…';
    try {
      const data = await sessionApi('/api/cloud/youtube-public/status');
      if (!isCurrent(version)) return;
      state.workforce.researchReady = data?.allowed === true && data?.state === 'configured_unverified';
      state.workforce.researchLoaded = true;
      $('public-research-submit').disabled = !state.workforce.researchReady;
      $('public-research-setup').textContent = state.workforce.researchReady ? 'Configured, not yet verified. A lookup will use Google quota.'
        : data?.allowed !== true ? 'This account is not enabled for public lookups.'
        : 'Public research is not enabled and configured on this deployment.';
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') $('public-research-setup').textContent = `${error.message} Close and reopen to retry.`;
    } finally { if (isCurrent(version)) state.workforce.researchLoading = false; }
  }
  const integrationCatalog = [
    {name:'Pexels Video API',category:'Video production',status:'Credential required',detail:'Search licensed stock footage and use moving clips, not still-image-only results.',url:'https://www.pexels.com/api/'},
    {name:'FFmpeg',category:'Video production',status:'Local pipeline',detail:'Encode, combine clips, add transitions, captions, audio and final renders on a worker/desktop.',url:'https://ffmpeg.org/'},
    {name:'Whisper speech recognition',category:'Voice & speech',status:'Setup required',detail:'Speech-to-text for voice commands and transcription; local or hosted deployment choices.',url:'https://github.com/openai/whisper'},
    {name:'Piper TTS',category:'Voice & speech',status:'Setup required',detail:'Local text-to-speech option for spoken assistant replies.',url:'https://github.com/rhasspy/piper'},
    {name:'Kokoro TTS',category:'Voice & speech',status:'Setup required',detail:'Alternative lightweight voice synthesis; select a supported voice and verify its license.',url:'https://github.com/hexgrad/kokoro'},
    {name:'Ollama + Qwen / Gemma',category:'AI models',status:'Local PC setup',detail:'Local-model runtime and smaller models suited to constrained hardware; model performance depends on RAM.',url:'https://ollama.com/'},
    {name:'OpenAI API',category:'AI models',status:'Credential required',detail:'Hosted generation for scripts, planning, coding and chat; usage can incur charges.',url:'https://platform.openai.com/docs'},
    {name:'Groq API',category:'AI models',status:'Credential required',detail:'Fast hosted inference and the requested Groq bot integration.',url:'https://console.groq.com/docs'},
    {name:'Google Gemini API',category:'AI models',status:'Credential required',detail:'Optional model provider; configure server-side credentials and allowed models.',url:'https://ai.google.dev/'},
    {name:'Anthropic Claude API',category:'AI models',status:'Optional provider',detail:'Optional model provider; credentials and billing are separate.',url:'https://docs.anthropic.com/'},
    {name:'xAI / Grok API',category:'AI models',status:'Optional provider',detail:'Optional model provider, subject to account access and API credentials.',url:'https://docs.x.ai/'},
    {name:'OpenRouter',category:'AI models',status:'Optional provider',detail:'Multi-provider model routing; review the selected upstream provider’s data and billing terms.',url:'https://openrouter.ai/docs'},
    {name:'OpenClaw agent runtime',category:'Agents & automation',status:'Desktop integration required',detail:'Agent actions, scheduled work and messaging integrations need a trusted local runtime and scoped permissions.',url:'https://github.com/openclaw/openclaw'},
    {name:'OpenDots',category:'Agents & automation',status:'Integration required',detail:'Requested agent/task orchestration reference; adapt to ViMax architecture and review repository requirements.',url:'https://github.com/CopilotKit/OpenDots'},
    {name:'Rakazo',category:'Agents & automation',status:'Integration required',detail:'Requested Groq bot-related project; review compatibility before connecting it.',url:'https://github.com/elie222/rakazo'},
    {name:'Composio / MCP tools',category:'Agents & automation',status:'Connectors required',detail:'Tool and app integrations through scoped OAuth/MCP actions; authorize each service separately.',url:'https://github.com/ComposioHQ/composio'},
    {name:'Aider coding assistant',category:'Coding workspace',status:'Local setup required',detail:'Open-source AI coding workflow that can complement a Cursor-inspired code workspace.',url:'https://github.com/Aider-AI/aider'},
    {name:'GitHub API',category:'Coding workspace',status:'Connected; scopes vary',detail:'Repository, branch, issue and pull-request actions depend on granted write permissions.',url:'https://docs.github.com/en/rest'},
    {name:'Playwright browser automation',category:'PC & browser control',status:'Runtime required',detail:'Browser automation for approved workflows; isolate sessions and require confirmation for consequential actions.',url:'https://playwright.dev/'},
    {name:'Windows desktop control',category:'PC & browser control',status:'Desktop app required',detail:'Window/app control, typing, clicking, files and shell commands belong in a permissioned Windows desktop agent—not this hosted website.',url:'https://learn.microsoft.com/en-us/windows/'},
    {name:'Screen vision / OCR',category:'PC & browser control',status:'Implementation required',detail:'Screen understanding needs a local capture/OCR pipeline and explicit privacy controls.',url:'https://github.com/JaidedAI/EasyOCR'},
    {name:'Google Sign-In / OAuth',category:'Accounts & integrations',status:'Deployment configuration',detail:'Account identity and app authorization are distinct. Configure allowed redirect URLs and secrets privately.',url:'https://developers.google.com/identity'},
    {name:'YouTube Data API',category:'Creator & social',status:'OAuth / quota required',detail:'Channel metadata and authorized uploads depend on enabled API scopes, consent and quota.',url:'https://developers.google.com/youtube/v3'},
    {name:'YouTube Analytics API',category:'Creator & social',status:'Read-only OAuth required',detail:'Analytics reports need separate authorized scopes; this is not a publishing permission.',url:'https://developers.google.com/youtube/analytics'},
    {name:'Gmail API',category:'Accounts & integrations',status:'OAuth required',detail:'Email reading/sending is not enabled by merely linking Google sign-in; request minimal scopes.',url:'https://developers.google.com/gmail/api'},
    {name:'Facebook Pages API',category:'Creator & social',status:'App review required',detail:'Page listing and publishing require Facebook app setup, Page permissions and approval.',url:'https://developers.facebook.com/docs/pages-api/'},
    {name:'WhatsApp / Telegram / Discord / Slack',category:'Messaging & automation',status:'Per-service setup',detail:'Each bot/app needs its own credentials, permissions and delivery tests.',url:'https://core.telegram.org/bots/api'},
    {name:'GitHub + Gmail workflows',category:'Accounts & integrations',status:'Scoped integration',detail:'Cross-app automations must use explicit authorization, audit logs and least-privilege access.',url:'https://github.com/'},
    {name:'Skills catalog (162+ entries)',category:'Skills & agents',status:'Catalog exists',detail:'Browse existing skill metadata. A listed skill is not installed or executable until reviewed and wired.',url:'https://github.com/'},
    {name:'Multi-agent departments (120-slot plan)',category:'Skills & agents',status:'Partially wired',detail:'Role definitions and registry are not the same as 120 running agents; only enabled roles can execute.',url:'https://github.com/'},
    {name:'Wake word “Hey Jarvis”',category:'Voice & speech',status:'Not yet wired here',detail:'Requires a local wake-word engine, microphone permissions and background service.',url:'https://github.com/dscripka/openWakeWord'},
    {name:'Memory & scheduled tasks',category:'Agents & automation',status:'Backend work required',detail:'Persistent memory and reliable schedules need storage, retention controls and a worker.',url:'https://github.com/'},
    {name:'World Monitor / system status',category:'PC & browser control',status:'Integration required',detail:'Dashboard for task status, machine health, logs, pause/stop controls and live progress.',url:'https://github.com/'}
  ];
  function renderIntegrationCatalog() {
    const query = $('integration-search').value.trim().toLowerCase(), category = $('integration-category').value;
    const visible = integrationCatalog.filter(item => (category === 'all' || item.category === category)
      && (!query || [item.name,item.category,item.status,item.detail].join(' ').toLowerCase().includes(query)));
    const container = $('integration-catalog'); container.replaceChildren();
    $('integration-count').textContent = visible.length + ' of ' + integrationCatalog.length + ' tool entries · catalog links are not proof of connection.';
    if (!visible.length) { const empty = element('p','No tools match this search.','integration-empty'); container.append(empty); return; }
    for (const item of visible) {
      const card = element('article',null,'integration-card');
      card.append(element('div',item.category,'integration-category'), element('h4',item.name), element('span',item.status,'integration-state'), element('p',item.detail));
      const link = element('a','Official docs / source ↗'); link.href = item.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; card.append(link);
      container.append(card);
    }
  }
  const integrationCategories = [...new Set(integrationCatalog.map(item => item.category))].sort();
  for (const category of integrationCategories) { const option = element('option',category); option.value = category; $('integration-category').append(option); }
  $('integration-search').addEventListener('input', renderIntegrationCatalog);
  $('integration-category').addEventListener('change', renderIntegrationCatalog);
  renderIntegrationCatalog();
\n  $('workforce-open').addEventListener('click', () => {
    if (!state.user) return;
    showDialog('workforce-dialog'); void loadWorkforceRegistry(state.version); void loadAgentRegistry(state.version); void loadPublicResearchStatus(state.version);
  });
  $('public-research-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (!state.user || !state.workforce.researchReady || state.workforce.researchBusy || !$('public-research-confirm').checked) return;
    const version = state.version, input = {reference:$('public-research-reference').value,confirm_quota:true};
    state.workforce.researchBusy = true; for (const field of $('public-research-form').elements) field.disabled = true;
    $('public-research-status').textContent = 'Requesting a public metadata sample…'; $('public-research-error').textContent = ''; $('public-research-result').hidden = true;
    try {
      const data = await post('/api/cloud/youtube-public/sample', input);
      if (!isCurrent(version)) return;
      const sample = data?.sample;
      if (!sample?.channel || typeof sample.channel.title !== 'string' || !Array.isArray(sample.videos) || sample.videos.length > 10) throw new Error('The public sample response is invalid.');
      const omitted = Number.isInteger(sample.missing_videos) && sample.missing_videos > 0 ? ` ${sample.missing_videos} unavailable video record(s) omitted.` : '';
      $('public-research-status').textContent = (data.audit_saved ? 'Public metadata sample ready.' : 'Sample ready, but the attempt audit could not be finalized.') + omitted;
      $('public-research-notice').textContent = typeof sample.notice === 'string' ? sample.notice : '';
      const target = $('public-research-data'); target.replaceChildren();
      target.append(element('h4', sample.channel.title), element('p', `Channel: ${sample.channel.id}`),
        element('p', `Subscribers: ${sample.channel.subscribers ?? 'unavailable'} · Total views: ${sample.channel.total_views ?? 'unavailable'} · Videos: ${sample.channel.video_count ?? 'unavailable'}`),
        element('p', sample.channel.description || 'No public description returned.'));
      if (!sample.videos.length) target.append(element('p', 'No public video details were returned.'));
      for (const video of sample.videos) {
        if (!video || typeof video.title !== 'string') continue;
        const item = element('details'); item.append(element('summary', video.title || 'Untitled video'));
        item.append(element('p', `Published: ${video.published_at || 'unavailable'} · Duration: ${video.duration_iso || 'unavailable'} · Views: ${video.views ?? 'unavailable'} · Likes: ${video.likes ?? 'unavailable'} · Comments: ${video.comments ?? 'unavailable'}`));
        item.append(element('p', typeof video.url === 'string' ? video.url : '')); target.append(item);
      }
      $('public-research-result').hidden = false;
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') { $('public-research-status').textContent = ''; $('public-research-error').textContent = error.message; }
    } finally {
      if (isCurrent(version)) { state.workforce.researchBusy = false; for (const field of $('public-research-form').elements) field.disabled = false; $('public-research-submit').disabled = !state.workforce.researchReady; }
    }
  });
  $('creator-review-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (!state.user || state.workforce.reviewBusy) return;
    const version = state.version, input = {metadata:{title:$('creator-title').value}};
    for (const [key, field] of [['reference','creator-reference'],['idea','creator-idea'],['hook','creator-hook'],['thumbnail','creator-thumbnail']]) {
      const value = $(field).value.trim(); if (value) input[key] = value;
    }
    const metrics = {};
    for (const [key, field] of [['impressions','creator-impressions'],['views','creator-views'],['ctr','creator-ctr'],['avd_seconds','creator-avd'],['length_seconds','creator-length']]) {
      if ($(field).value !== '') metrics[key] = Number($(field).value);
    }
    if (Object.keys(metrics).length) input.funnel = {format:$('creator-format').value, metrics};
    state.workforce.reviewBusy = true; for (const field of $('creator-review-form').elements) field.disabled = true;
    $('creator-review-status').textContent = 'Reviewing supplied draft…'; $('creator-review-error').textContent = ''; $('creator-review-result').hidden = true;
    try {
      const data = await post('/api/cloud/agents/run', {agent:'studio_manager', input});
      if (!isCurrent(version)) return;
      const result = data?.result;
      if (!result || !Array.isArray(result.steps) || result.steps.length < 2 || result.steps.length > 6) throw new Error('The review response is invalid.');
      $('creator-review-status').textContent = result.status === 'review_ready' ? 'Read-only review ready. Review every result before use.' : 'The metadata draft needs changes.';
      $('creator-review-notice').textContent = typeof result.notice === 'string' ? result.notice : '';
      const steps = $('creator-review-steps'); steps.replaceChildren();
      const labels = {metadata_preflight:'Metadata preview',title_lint:'Title and thumbnail text',youtube_url_parser:'YouTube reference',idea_heuristic:'Idea wording',hook_heuristic:'Hook wording',funnel_heuristic:'Supplied metrics'};
      for (const step of result.steps) {
        if (!step || typeof step.skill !== 'string' || !step.result || typeof step.result !== 'object') continue;
        const item = element('details'); item.open = step.skill === 'metadata_preflight'; item.append(element('summary', labels[step.skill] || 'Read-only check'));
        item.append(element('pre', JSON.stringify(step.result, null, 2))); steps.append(item);
      }
      $('creator-review-result').hidden = false;
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') { $('creator-review-status').textContent = ''; $('creator-review-error').textContent = error.message; }
    } finally {
      if (isCurrent(version)) { state.workforce.reviewBusy = false; for (const field of $('creator-review-form').elements) field.disabled = false; }
    }
  });
  $('preflight-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (!state.user || state.workforce.busy) return;
    const version = state.version;
    const input = {title:$('preflight-title-input').value, description:$('preflight-description').value,
      tags:$('preflight-tags').value, categoryId:$('preflight-category').value, defaultLanguage:$('preflight-language').value};
    state.workforce.busy = true; for (const field of $('preflight-form').elements) field.disabled = true;
    $('preflight-status').textContent = 'Checking draft…'; $('preflight-error').textContent = ''; $('preflight-result').hidden = true;
    try {
      const data = await post('/api/cloud/skills/run', {skill:'metadata_preflight', input});
      if (!isCurrent(version)) return;
      const result = data?.result;
      if (!result || typeof result.valid !== 'boolean' || !result.preview || typeof result.preview !== 'object') throw new Error('The preview response is invalid.');
      $('preflight-status').textContent = result.valid ? 'Preview ready. Review warnings and normalized values.' : 'Draft needs changes before use.';
      $('preflight-notice').textContent = typeof result.notice === 'string' ? result.notice : '';
      const notes = $('preflight-notes'); notes.replaceChildren();
      for (const [prefix, values] of [['Error',result.errors],['Warning',result.warnings],['Change',result.changes]]) {
        if (Array.isArray(values)) for (const value of values) if (typeof value === 'string') notes.append(element('li', `${prefix}: ${value}`));
      }
      $('preflight-preview').textContent = JSON.stringify(result.preview, null, 2);
      $('preflight-result').hidden = false;
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') { $('preflight-status').textContent = ''; $('preflight-error').textContent = error.message; }
    } finally {
      if (isCurrent(version)) { state.workforce.busy = false; for (const field of $('preflight-form').elements) field.disabled = false; }
    }
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
    state.authBusy = true; state.sessionSequence++; offerChannelAfterLogin = false;
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
  $('fallback').addEventListener('change', updateChatControls);
  $('provider-test').addEventListener('click', async () => {
    if ($('provider-test').disabled) return;
    const provider = $('provider').value, model = $('model').value, version = state.version;
    const label = availableProviders().find(item => item.id === provider)?.label || provider;
    if (!confirm(`Send a live test to ${label} / ${model}? The provider receives the nonsensitive text “Reply with the word OK.” This uses one attempt and up to 1,024 output tokens plus input, and may incur charges. No fallback is used. Continue only if you accept its pricing and data practices.`)) return;
    state.chat.busy = true; state.chat.testing = true; state.chat.error = ''; updateChatControls();
    const key = `${provider}|${model}`;
    try {
      const data = await post('/api/cloud/providers/test', {provider, model});
      if (!isCurrent(version)) return;
      if (data?.ok !== true || data.provider !== provider || data.model !== model) throw new Error('The provider test returned an invalid result.');
      const remaining = Number.isSafeInteger(data.remaining_user) && data.remaining_user >= 0 ? ` ${data.remaining_user} attempt(s) remain today.` : '';
      const warning = data.audit_saved === true ? '' : ' Warning: the usage result could not be saved.';
      state.chat.tests.set(key, {summary:`${model} responded once`, detail:`${model} responded successfully in this browser session.${remaining}${warning} Future availability is not guaranteed.`});
    } catch (error) {
      if (isCurrent(version)) state.chat.tests.set(key, {summary:`Last test failed for ${model}`, detail:`Test failed: ${error.message}`});
    } finally {
      if (isCurrent(version)) { state.chat.busy = false; state.chat.testing = false; renderProviders(); updateChatControls(); }
    }
  });
  document.querySelectorAll('.quick-prompt').forEach(button => button.addEventListener('click', () => {
    if (state.chat.busy) return;
    const prompt = button.dataset.prompt || '';
    $('chat-prompt').value = prompt;
    $('chat-prompt').focus();
    updateChatControls();
  }));
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
    stopRecognition();
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
        const responding = availableProviders().find(item => item.id === data.provider && item.models.includes(data.model));
        if (responding) {
          state.chat.tests.set(`${data.provider}|${data.model}`, {summary:`${data.model} responded once`, detail:`${data.model} responded to chat in this browser session. Future availability is not guaranteed.`});
          renderProviders();
        }
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
  $('usage-refresh').addEventListener('click', async () => {
    if (!state.user || state.chat.usageLoading) return;
    const version = state.version;
    state.chat.usageLoading = true; $('usage-message').textContent = 'Loading recorded usage…'; updateChatControls();
    try {
      const data = await sessionApi('/api/cloud/usage');
      if (!isCurrent(version)) return;
      if (!Array.isArray(data?.calls) || data.calls.length > 20) throw new Error('Usage data was invalid. Try again.');
      const list = $('usage-list'); list.replaceChildren();
      const clean = (value, max, fallback) => typeof value === 'string'
        ? Array.from(value.replace(/[\u0000-\u001f\u007f]/g, ' ')).slice(0,max).join('') || fallback : fallback;
      const count = value => Number.isSafeInteger(value) && value >= 0 && value <= 10_000_000 ? String(value) : 'unknown';
      for (const call of data.calls) {
        if (!call || typeof call !== 'object') continue;
        const provider = clean(call.provider,24,'Unknown provider'), model = clean(call.model,128,'No model');
        const feature = clean(call.feature,32,'request');
        const statuses = {succeeded:'completed',failed:'failed; charges may apply',reserved:'in progress or unconfirmed'};
        const status = typeof call.status === 'string' && Object.hasOwn(statuses,call.status) ? statuses[call.status] : 'unknown status';
        const time = typeof call.created_at === 'string' && call.created_at.length <= 40 ? Date.parse(call.created_at) : NaN;
        const when = Number.isFinite(time) ? new Date(time).toISOString().replace('T',' ').replace('.000Z',' UTC') : 'Time unavailable';
        const row = element('li');
        row.append(element('strong', `${provider} · ${model}`),
          element('span', `${feature} · ${status} · ${when}`),
          element('span', `Input tokens: ${count(call.input_tokens)} · Output tokens: ${count(call.output_tokens)}`));
        list.append(row);
      }
      $('usage-message').textContent = list.childElementCount ? `Showing ${list.childElementCount} recent recorded attempt(s).` : 'No recorded usage yet.';
    } catch (error) {
      if (isCurrent(version) && error.name !== 'AbortError') { $('usage-list').replaceChildren(); $('usage-message').textContent = error.message; }
    } finally { if (isCurrent(version)) { state.chat.usageLoading = false; updateChatControls(); } }
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
  let recognition = null, currentUtterance = null, voices = [], voiceDisclosureAccepted = false;
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
  function microphoneStatus(message = '') {
    $('microphone-status').textContent = message;
    $('microphone-status').hidden = !message;
  }
  function dictateLabel(listening) {
    const label = listening ? 'Stop voice input' : 'Start voice input';
    $('dictate').setAttribute('aria-label', label); $('dictate').title = label;
  }
  function cancelPlayback() {
    // Invalidate callbacks before cancel: browsers may deliver old end events
    // after a newer utterance has started or an account has changed.
    currentUtterance = null;
    try { synthesis?.cancel(); } catch {}
    $('stop-speech').hidden = true;
  }
  function stopRecognition() {
    const active = recognition; recognition = null;
    if (active) { try { active.abort(); } catch {} }
    dictateLabel(false); microphoneStatus();
  }
  function stopAllSpeech() {
    stopRecognition(); cancelPlayback();
    $('dictate').disabled = !Recognition;
  }
  function speak(text) {
    // Do not let the microphone transcribe the assistant's own reply, even if
    // playback turns out to be unavailable or the language setting is invalid.
    stopRecognition(); cancelPlayback();
    if (!synthesis || typeof window.SpeechSynthesisUtterance !== 'function') {
      const message = 'Spoken playback is unavailable; the text reply is still visible.';
      $('voice-status').textContent = message; microphoneStatus(message); return;
    }
    const language = speechLanguage();
    if (!language) { microphoneStatus('Invalid speech language. The text reply is still visible.'); return; }
    const utterance = new window.SpeechSynthesisUtterance(text); currentUtterance = utterance; utterance.lang = language;
    if ($('speech-voice').value !== '') utterance.voice = voices[Number($('speech-voice').value)] || null;
    utterance.onstart = () => { if (currentUtterance === utterance) $('stop-speech').hidden = false; };
    utterance.onend = () => { if (currentUtterance === utterance) { currentUtterance = null; $('stop-speech').hidden = true; } };
    const playbackError = () => {
      if (currentUtterance !== utterance) return;
      currentUtterance = null; $('stop-speech').hidden = true;
      const message = 'Spoken playback is unavailable; the text reply is still visible.';
      $('voice-status').textContent = message; microphoneStatus(message);
    };
    utterance.onerror = playbackError;
    try { synthesis.speak(utterance); } catch { playbackError(); }
  }
  $('stop-speech').addEventListener('click', cancelPlayback);
  $('dictate').addEventListener('click', () => {
    if (!Recognition) return;
    if (recognition) {
      microphoneStatus('Stopping microphone…');
      try { recognition.stop(); } catch { stopRecognition(); }
      return;
    }
    if (!voiceDisclosureAccepted && !confirm('Voice input may send audio to your browser’s speech service. Continue?')) return;
    voiceDisclosureAccepted = true; const language = speechLanguage();
    if (!language) { microphoneStatus('Invalid speech language. You can type instead.'); return; }
    // Starting dictation interrupts playback; recognition is always one-shot
    // and fills the composer for review rather than sending automatically.
    cancelPlayback();
    const existing = $('chat-prompt').value.trim();
    try {
      const instance = new Recognition(); recognition = instance; let failed = false;
      instance.lang = language; instance.interimResults = true; instance.continuous = false;
      microphoneStatus('Requesting microphone access…');
      instance.onstart = () => { if (recognition === instance) { dictateLabel(true); microphoneStatus('Microphone is listening. Tap the microphone to stop.'); } };
      instance.onresult = event => {
        if (recognition !== instance) return;
        const transcript = Array.from(event.results, result => result[0]?.transcript || '').join(' ');
        $('chat-prompt').value = `${existing}${existing && transcript ? ' ' : ''}${transcript}`.slice(0, 1600); updateChatControls();
      };
      instance.onerror = () => {
        if (recognition !== instance) return;
        failed = true; const message = 'Voice input is unavailable. You can type instead.';
        $('voice-status').textContent = message; microphoneStatus(message);
      };
      instance.onend = () => {
        if (recognition !== instance) return;
        recognition = null; dictateLabel(false); if (!failed) microphoneStatus();
      };
      instance.start();
    } catch { recognition = null; dictateLabel(false); const message = 'Could not start voice input. You can type instead.'; $('voice-status').textContent = message; microphoneStatus(message); }
  });
  $('dictate').disabled = !Recognition;
  if (synthesis) { refreshVoices(); synthesis.addEventListener?.('voiceschanged', refreshVoices); }
  // Stop microphone and playback when the tab is backgrounded or leaves; they
  // never restart automatically on return. When the owner returns from setup,
  // recheck availability without starting an OAuth request or signing anyone in.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopAllSpeech();
    else if (!state.user && !state.authBusy && ['disabled','unknown'].includes(state.google.status)) void checkGoogleSignIn();
  });
  window.addEventListener('pagehide', stopAllSpeech);

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
      offerChannelAfterLogin = googleResult === 'success' && Boolean(intent) && age >= 0 && age < 600_000;
      sessionStorage.removeItem('vimax-google-channel-intent');
    }
  } catch {}
  if (googleResult === 'failed') state.google.error = 'Google sign-in did not complete. Try again.';
  renderMessages(); renderProviders(); renderChannelList(); renderFacebookList(); updateAccount(); updateChannelControls(); updateFacebookControls(); updateChatControls();
  void checkDeployment(); void checkGoogleSignIn();
  void checkSession().then(() => {
    if (googleResult === 'success' && !state.user) { offerChannelAfterLogin = false; state.google.error = 'Google sign-in could not be confirmed. Try again.'; updateGoogleControls(); }
    if (confirmation && !state.user) {
      $('account-message').textContent = confirmation === 'yes' ? 'Email confirmed. Please sign in.' : 'Email confirmation failed or expired; please try again.';
      showDialog('account-dialog');
    }
  });
})();
