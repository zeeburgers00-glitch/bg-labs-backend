'use strict';
const $ = (id) => document.getElementById(id);
const state = {catalog: [], system: null, job: null, timer: null, sceneOperation: false};

async function json(url, options = {}) {
  let response;
  try { response = await fetch(url, {cache: 'no-store', ...options, headers: {'Content-Type': 'application/json', ...(options.headers || {})}}); }
  catch { throw new Error('The ViMax service cannot be reached. Check your connection and try again.'); }
  const type = response.headers.get('content-type') || '';
  if (!type.includes('application/json') && !type.includes('+json')) throw new Error(`The backend returned a non-JSON response (HTTP ${response.status}). Check that the ViMax backend is connected.`);
  let payload;
  try { payload = await response.json(); } catch { throw new Error('The backend returned invalid JSON. Check its logs and connection.'); }
  if (!response.ok) {
    let error = payload?.error || payload?.detail || `Request failed (HTTP ${response.status}).`;
    if (Array.isArray(error)) error = error.map(x => x.msg || 'Invalid input').join('; ');
    throw new Error(String(error));
  }
  return payload;
}

function element(tag, text, className = '') {
  const item = document.createElement(tag);
  if (text != null) item.textContent = text;
  if (className) item.className = className;
  return item;
}
function statusFor(entry) {
  if (entry.status === 'unavailable') return 'Unavailable — not installed';
  if (entry.status === 'reference') return 'Reference only — not connected';
  if (entry.status === 'reviewed') return entry.review_level === 'surface' ? 'Surface triage only — not installed' : 'Assessed only — not installed';
  if (!state.system) return 'Selected adapter included · local service offline';
  if (!state.system.local_only) return 'Adapter included · local setup required';
  if (entry.name === 'rhasspy/piper') return state.system.piper_installed && state.system.voices.some(v => v.available) ? 'Piper adapter ready locally' : 'Piper adapter included · voice or runtime missing';
  if (entry.name === 'FFmpeg/FFmpeg') return state.system.ffmpeg_installed ? 'FFmpeg adapter ready locally' : 'FFmpeg adapter included · binary missing';
  if (entry.name === 'Breakthrough/PySceneDetect' || entry.name === 'opencv/opencv') return state.system.scene_detection_installed ? 'Scene-cut adapter ready locally' : 'Scene-cut adapter included · dependencies missing';
  return 'Selected tools ready locally';
}
function renderCatalog() {
  const text = $('catalog-search').value.trim().toLowerCase();
  const filter = $('catalog-filter').value;
  const shown = state.catalog.filter(item => (filter === 'all' || item.status === filter) && JSON.stringify(item).toLowerCase().includes(text));
  $('catalog-count').textContent = `${shown.length} / ${state.catalog.length} SOURCES`;
  const container = $('catalog-list'); container.replaceChildren();
  if (!shown.length) { container.append(element('p', 'No sources match your search.', 'catalog-empty')); return; }
  for (const item of shown) {
    const card = element('article', null, 'catalog-card');
    card.append(element('span', statusFor(item), `status ${item.status}`), element('h3', item.name), element('p', item.description));
    const dl = element('dl');
    for (const [label, value] of [['License', item.license], ['Requirements', item.requirements], ['Features', item.features.join(', ')], ['Platform', item.platform], ['Security / limits', item.security]]) {
      dl.append(element('dt', label), element('dd', value));
    }
    const pinned = item.status !== 'reference' && item.revision && item.readme;
    const link = element('a', item.status === 'reference' ? 'Open reference ↗' : pinned ? 'View assessed README ↗' : 'View source on GitHub ↗');
    const url = new URL(pinned ? `${item.source}/blob/${item.revision}/${item.readme}` : item.source);
    const allowedHosts = ['github.com', 'developers.google.com', 'developers.tiktok.com', 'developers.facebook.com'];
    if (url.protocol === 'https:' && allowedHosts.includes(url.hostname)) { link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; }
    card.append(dl, link); container.append(card);
  }
}
async function loadCatalog() {
  try {
    const data = await json('/skills/catalog.json'); state.catalog = data.entries; renderCatalog();
  } catch (error) { $('catalog-list').replaceChildren(element('p', error.message, 'catalog-empty')); }
}
function setupVoices(system) {
  const select = $('voice-select'); select.replaceChildren();
  const usable = system.voices.filter(voice => voice.available);
  if (!usable.length) select.append(element('option', 'No local voice detected'));
  else for (const voice of usable) { const option = element('option', `${voice.label} · ${voice.language}`); option.value = voice.id; select.append(option); }
  select.disabled = !usable.length;
  function language() { $('language').value = usable.find(v => v.id === select.value)?.language || ''; }
  select.addEventListener('change', language); language();
}
async function loadSystem() {
  try {
    const system = await json('/api/skills/system'); state.system = system;
    $('connection').classList.add('ready');
    if (!system.local_only) {
      $('connection').textContent = 'Database connected · video worker offline';
      $('notice').textContent = `Supabase accounts and private ideas are connected. Cloud text planning is ${system.text_chat === 'configured_unverified' ? 'configured but not yet verified' : 'not configured'}. Online video generation, web research and automatic YouTube upload are not connected. The renderer below runs only on a locally configured computer.`;
      $('account').hidden = false;
      $('hardware').textContent = system.warnings.join(' ');
      setupVoices(system); renderCatalog();
      await loadAccount();
      return;
    }
    $('connection').textContent = 'Local companion connected';
    $('cloud-ai-link').hidden = true; $('mission-link').hidden = true;
    $('notice').classList.add('ready');
    $('notice').textContent = 'Single-user local mode. Your script and notes remain on this computer. This path uses text cards, not AI-generated visuals; no online research, translation, or YouTube upload is included.';
    setupVoices(system); $('create-button').disabled = !system.ready_for_video; $('analysis-button').disabled = false;
    $('hardware').textContent = `${system.hardware.logical_cpus || '?'} logical CPUs · ${system.hardware.memory_gib ?? '?'} GiB RAM · ${system.hardware.home_disk_free_gib ?? '?'} GiB free on home drive · ${system.hardware.nvidia_gpu || 'No NVIDIA GPU detected'} · FFmpeg ${system.ffmpeg_installed ? 'available' : 'missing'} · Piper ${system.piper_installed ? 'available' : 'missing'} · Scene detection ${system.scene_detection_installed ? 'available' : 'missing'}. ${system.warnings.join(' ')}`;
    renderCatalog();
    const prior = await json('/api/skills/jobs');
    if (prior.jobs.length) showJob(prior.jobs[0]);
  } catch (error) {
    $('connection').textContent = 'Service health unavailable';
    $('notice').textContent = 'The service health check could not be completed. Cloud and local capabilities cannot be verified right now.';
    $('hardware').textContent = error.message;
  }
}
function fileLink(job, filename, label) {
  const a = element('a', label); a.href = `/api/skills/jobs/${encodeURIComponent(job.id)}/files/${encodeURIComponent(filename)}`; a.target = '_blank'; a.rel = 'noopener'; return a;
}
function showJob(job) {
  if (state.job?.id !== job.id) {
    $('scene-result').textContent = 'Analyzes this generated video on your computer; no media is uploaded.';
    $('clip-result').textContent = 'Exports up to 30 seconds. A new clip replaces the previous one.';
  }
  state.job = job; $('job-empty').hidden = true; $('job-result').hidden = false;
  $('job-badge').textContent = job.status.replaceAll('_', ' '); $('job-attempts').textContent = `Attempt ${job.attempts} / ${job.max_attempts}`;
  $('job-cost').textContent = `Estimated API cost: $${Number(job.estimated_api_cost_usd).toFixed(2)} · Local compute/electricity not included`;
  $('output-path').textContent = `Local output: ${job.output_directory}`;
  $('job-error').textContent = job.error || '';
  $('retry-button').hidden = job.status !== 'failed' || job.attempts >= job.max_attempts;
  $('approve-button').hidden = job.status !== 'awaiting_review';
  const logs = $('job-events'); logs.replaceChildren();
  for (const ev of job.events) logs.append(element('li', `${ev.stage}: ${ev.message}`));
  const completed = (job.status === 'awaiting_review' || job.status === 'approved') && job.result;
  $('scene-tools').hidden = !completed;
  $('clip-tools').hidden = !completed || !job.result.files?.scene_detection;
  $('scene-button').disabled = state.sceneOperation || !state.system?.scene_detection_installed;
  $('clip-button').disabled = state.sceneOperation || !state.system?.ffmpeg_installed;
  $('video-preview').hidden = !completed; $('thumbnail-preview').hidden = !completed; $('output-links').replaceChildren();
  if (completed) {
    const prefix = `/api/skills/jobs/${encodeURIComponent(job.id)}/files/`;
    const video = $('video-preview'); const source = `${prefix}video.mp4`;
    if (!video.getAttribute('src')?.endsWith(source)) { video.src = source; $('caption-track').src = `${prefix}subtitles.vtt`; }
    $('caption-track').srclang = job.input.language;
    $('thumbnail-preview').src = `${prefix}thumbnail.png`;
    for (const [filename, label] of [['video.mp4','Video'], ['thumbnail.png','Thumbnail'], ['subtitles.srt','SRT'], ['storyboard.json','Storyboard'], ['narration.wav','Narration'], ['script.txt','Script'], ['research.txt','Notes']]) $('output-links').append(fileLink(job, filename, label));
    if (job.result.files?.scene_detection) $('output-links').append(fileLink(job, 'scene-detection.json', 'Visual cuts (JSON)'));
    if (job.result.files?.scene_clip) $('output-links').append(fileLink(job, 'scene-clip.mp4', 'Scene clip'));
  } else { $('video-preview').removeAttribute('src'); $('thumbnail-preview').removeAttribute('src'); }
  clearTimeout(state.timer);
  if (job.status === 'queued' || job.status === 'running') state.timer = setTimeout(() => refreshJob(job.id), 1500);
}
async function refreshJob(id) { try { showJob(await json(`/api/skills/jobs/${encodeURIComponent(id)}`)); } catch (error) { $('job-error').textContent = error.message; } }
$('job-form').addEventListener('submit', async event => {
  event.preventDefault(); $('job-error').textContent = ''; $('create-button').disabled = true;
  const data = Object.fromEntries(new FormData(event.currentTarget)); data.duration_seconds = Number(data.duration_seconds);
  try { showJob(await json('/api/skills/jobs', {method:'POST', body:JSON.stringify(data)})); }
  catch (error) { $('job-error').textContent = error.message; }
  finally { $('create-button').disabled = !state.system?.ready_for_video; }
});
$('retry-button').addEventListener('click', async () => { try { showJob(await json(`/api/skills/jobs/${encodeURIComponent(state.job.id)}/retry`, {method:'POST',body:'{}'})); } catch (error) { $('job-error').textContent = error.message; } });
$('approve-button').addEventListener('click', async () => {
  if (!confirm('Have you reviewed this video and its rights? This records approval locally and does not upload it.')) return;
  try { showJob(await json(`/api/skills/jobs/${encodeURIComponent(state.job.id)}/approve`, {method:'POST',body:JSON.stringify({confirmed:true})})); }
  catch (error) { $('job-error').textContent = error.message; }
});
$('scene-button').addEventListener('click', async () => {
  const jobId = state.job?.id;
  const threshold = Number($('scene-threshold').value);
  if (!jobId || !$('scene-threshold').value || !Number.isFinite(threshold) || threshold < 0.1 || threshold > 100) {
    $('scene-result').textContent = 'Choose a threshold from 0.1 to 100.'; return;
  }
  state.sceneOperation = true; $('scene-button').disabled = true; $('clip-button').disabled = true;
  $('scene-result').textContent = 'Analyzing video frames locally…';
  try {
    const result = await json(`/api/skills/jobs/${encodeURIComponent(jobId)}/scene-detection`, {method:'POST',body:JSON.stringify({threshold})});
    if (state.job?.id !== jobId) return;
    const updated = await json(`/api/skills/jobs/${encodeURIComponent(jobId)}`);
    showJob(updated);
    const lines = result.scenes.slice(0, 10).map(scene => `Scene ${scene.number}: ${scene.start_seconds.toFixed(2)}s – ${scene.end_seconds.toFixed(2)}s`);
    if (result.scene_count > lines.length) lines.push('More scenes are in the downloadable JSON.');
    $('scene-result').textContent = `${result.scene_count} detected scene(s). ${result.notice}\n${lines.join('\n')}`;
  } catch (error) {
    if (state.job?.id === jobId) $('scene-result').textContent = error.message;
  } finally {
    state.sceneOperation = false;
    $('scene-button').disabled = !state.system?.scene_detection_installed;
    $('clip-button').disabled = !state.system?.ffmpeg_installed;
  }
});
$('clip-button').addEventListener('click', async () => {
  const jobId = state.job?.id;
  const number = Number($('clip-scene').value);
  if (!jobId || !Number.isInteger(number) || number < 1 || number > 1000) {
    $('clip-result').textContent = 'Enter a valid detected scene number.'; return;
  }
  state.sceneOperation = true; $('scene-button').disabled = true; $('clip-button').disabled = true;
  $('clip-result').textContent = 'Exporting clip locally…';
  try {
    const clip = await json(`/api/skills/jobs/${encodeURIComponent(jobId)}/scene-clip`, {method:'POST',body:JSON.stringify({scene_number:number})});
    if (state.job?.id !== jobId) return;
    const updated = await json(`/api/skills/jobs/${encodeURIComponent(jobId)}`);
    showJob(updated);
    $('clip-result').textContent = `Scene ${clip.scene_number}: ${clip.duration_seconds.toFixed(2)}s exported. ${clip.limited_to_30_seconds ? 'Trimmed to 30 seconds. ' : ''}Use the Scene clip link above. A new export replaces this clip.`;
  } catch (error) {
    if (state.job?.id === jobId) $('clip-result').textContent = error.message;
  } finally {
    state.sceneOperation = false;
    $('scene-button').disabled = !state.system?.scene_detection_installed;
    $('clip-button').disabled = !state.system?.ffmpeg_installed;
  }
});
$('analysis-form').addEventListener('submit', async event => {
  event.preventDefault(); $('analysis-error').textContent = '';
  try { const data = Object.fromEntries(new FormData(event.currentTarget)); $('analysis-result').textContent = JSON.stringify(await json('/api/skills/analyze', {method:'POST',body:JSON.stringify(data)}), null, 2); }
  catch (error) { $('analysis-error').textContent = error.message; }
});
$('catalog-search').addEventListener('input', renderCatalog); $('catalog-filter').addEventListener('change', renderCatalog);

async function loadProjects() {
  const data = await json('/api/cloud/projects');
  const list = $('cloud-project-list'); list.replaceChildren();
  if (!data.projects.length) { list.append(element('li', 'No ideas saved yet.', 'form-note')); return; }
  for (const project of data.projects) {
    const item = element('li', null, 'cloud-project');
    const details = element('div');
    details.append(element('strong', project.title), element('p', project.notes || 'No notes.', 'form-note'));
    const remove = element('button', 'Delete', 'small-button'); remove.type = 'button';
    remove.addEventListener('click', async () => {
      if (!confirm(`Delete the saved idea “${project.title}”?`)) return;
      try { await json(`/api/cloud/projects/${encodeURIComponent(project.id)}`, {method:'DELETE'}); await loadProjects(); }
      catch (error) { $('cloud-project-error').textContent = error.message; }
    });
    item.append(details, remove); list.append(item);
  }
}
async function loadAccount() {
  const data = await json('/api/cloud/session');
  const loggedIn = Boolean(data.user);
  $('account-form').hidden = loggedIn; $('cloud-projects').hidden = !loggedIn; $('cloud-info').hidden = loggedIn;
  const cloud = window.vimaxCloud.onSession(loggedIn);
  const mission = window.vimaxMission.onSession(loggedIn);
  if (loggedIn) { $('account-identity').textContent = `${data.user.email} · Account ID: ${data.user.id}`; await loadProjects(); }
  await Promise.all([cloud, mission]);
  try {
    const confirmed = sessionStorage.getItem('vimax-email-confirmed');
    if (confirmed) { $('account-message').textContent = confirmed === 'yes' ? 'Email confirmed. Please sign in.' : 'Email confirmation failed or expired; please try again.'; sessionStorage.removeItem('vimax-email-confirmed'); }
  } catch {}
}
$('account-form').addEventListener('submit', async event => {
  event.preventDefault(); $('account-error').textContent = ''; $('account-message').textContent = '';
  const action = event.submitter?.value === 'signup' ? 'signup' : 'login';
  const data = Object.fromEntries(new FormData(event.currentTarget));
  const buttons = event.currentTarget.querySelectorAll('button'); buttons.forEach(button => { button.disabled = true; });
  try {
    const result = await json(`/api/cloud/${action}`, {method:'POST', body:JSON.stringify(data)});
    event.currentTarget.elements.password.value = '';
    if (action === 'signup') $('account-message').textContent = result.message;
    else await loadAccount();
  } catch (error) { $('account-error').textContent = error.message; }
  finally { buttons.forEach(button => { button.disabled = false; }); }
});
$('logout-button').addEventListener('click', async () => {
  try { await json('/api/cloud/logout', {method:'POST',body:'{}'}); await loadAccount(); }
  catch (error) { $('cloud-project-error').textContent = error.message; }
});
$('cloud-project-form').addEventListener('submit', async event => {
  event.preventDefault(); $('cloud-project-error').textContent = '';
  try { await json('/api/cloud/projects', {method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.currentTarget)))}); event.currentTarget.reset(); await loadProjects(); }
  catch (error) { $('cloud-project-error').textContent = error.message; }
});
loadCatalog(); loadSystem();
