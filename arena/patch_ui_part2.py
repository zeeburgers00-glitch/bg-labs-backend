"""Patch 2: append the AI Agents + YouTube Connect JavaScript to index.html."""
from pathlib import Path

path = Path("index.html")
html = path.read_text(encoding="utf-8")

ANCHOR = "    // Initialize login form by default"
if ANCHOR not in html:
    raise SystemExit("anchor missing")

JS = r'''    // ============================================================================
    // SHARED HELPERS (agents + youtube)
    // ============================================================================
    async function agentFetch(path, options) {
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const res = await fetch(`${API_BASE}${path}`, Object.assign({ headers }, options || {}));
        if (res.status === 401) { logout(); throw new Error('Session expired - please sign in again'); }
        let data = null;
        try { data = await res.json(); } catch (e) { data = null; }
        if (!res.ok) {
            const detail = data && (data.detail || data.message);
            throw new Error(typeof detail === 'string' ? detail : `Request failed (${res.status})`);
        }
        return data;
    }

    function agentEsc(value) {
        return String(value === null || value === undefined ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function agentLabel(key) {
        return String(key || '').replace(/_/g, ' ').replace(/\bid\b/gi, 'ID')
            .replace(/\b(ab|seo|ai|kpi|cta|ctr)\b/gi, m => m.toUpperCase())
            .replace(/\b\w/g, c => c.toUpperCase());
    }

    function agentCopy(btn) {
        const text = decodeURIComponent(btn.getAttribute('data-copy') || '');
        navigator.clipboard.writeText(text)
            .then(() => toast('Copied to clipboard', 'success'))
            .catch(() => toast('Could not copy - select the text manually', 'error'));
    }

    function agentCopyText(text, label) {
        navigator.clipboard.writeText(String(text || ''))
            .then(() => toast(`${label || 'Text'} copied`, 'success'))
            .catch(() => toast('Could not copy', 'error'));
    }

    function agentDownload(name, text) {
        const blob = new Blob([String(text || '')], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = name; document.body.appendChild(a); a.click();
        a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1500);
    }

    function agentSendToStudio(text, voiceKey) {
        sessionStorage.setItem('bglabs_handoff_tts_text', String(text || '').slice(0, 8000));
        if (voiceKey) sessionStorage.setItem('bglabs_handoff_tts_voice', String(voiceKey));
        navigate('studio');
    }

    function agentSendToImage(prompt) {
        sessionStorage.setItem('bglabs_handoff_img_prompt', String(prompt || '').slice(0, 1200));
        navigate('image');
    }

    function agentSendToScript(topic, script) {
        sessionStorage.setItem('bglabs_handoff_script_topic', String(topic || '').slice(0, 200));
        if (script) sessionStorage.setItem('bglabs_handoff_script_text', String(script).slice(0, 20000));
        navigate('script');
    }

    function applyAgentHandoff(page) {
        try {
            if (page === 'studio') {
                const text = sessionStorage.getItem('bglabs_handoff_tts_text');
                const voice = sessionStorage.getItem('bglabs_handoff_tts_voice');
                if (text && document.getElementById('ttsText')) {
                    document.getElementById('ttsText').value = text;
                    const counter = document.getElementById('ttsCharCount');
                    if (counter) counter.textContent = `${text.length} characters`;
                }
                if (voice && document.getElementById('ttsVoice')) {
                    const sel = document.getElementById('ttsVoice');
                    const match = Array.from(sel.options).find(o => o.value.toLowerCase().indexOf(voice.toLowerCase().replace('neural', '')) !== -1);
                    if (match) sel.value = match.value;
                }
                if (text) toast('Script loaded from the AI agent - press Generate', 'success');
                sessionStorage.removeItem('bglabs_handoff_tts_text');
                sessionStorage.removeItem('bglabs_handoff_tts_voice');
            } else if (page === 'image') {
                const prompt = sessionStorage.getItem('bglabs_handoff_img_prompt');
                if (prompt && document.getElementById('imgPrompt')) {
                    document.getElementById('imgPrompt').value = prompt;
                    toast('Thumbnail prompt loaded from the AI agent', 'success');
                }
                sessionStorage.removeItem('bglabs_handoff_img_prompt');
            } else if (page === 'script') {
                const topic = sessionStorage.getItem('bglabs_handoff_script_topic');
                const body = sessionStorage.getItem('bglabs_handoff_script_text');
                if (topic && document.getElementById('scriptTopic')) document.getElementById('scriptTopic').value = topic;
                if (body && document.getElementById('scriptEdit')) {
                    document.getElementById('scriptEdit').value = body;
                    document.getElementById('scriptResultContainer')?.classList.remove('hidden');
                }
                if (topic) toast('Topic loaded from the AI agent', 'success');
                sessionStorage.removeItem('bglabs_handoff_script_topic');
                sessionStorage.removeItem('bglabs_handoff_script_text');
            }
        } catch (e) { console.warn('handoff failed', e); }
    }

    // ============================================================================
    // AI AGENTS
    // ============================================================================
    let agentRegistry = [];
    let agentProviderInfo = null;
    let activeAgentId = null;
    let agentRunsCache = [];

    async function renderAgents() {
        const content = document.getElementById('contentArea');
        content.innerHTML = '<div class="animate-pulse flex items-center justify-center h-64"><div class="loader"></div></div>';
        try {
            const data = await agentFetch('/api/agents');
            agentRegistry = data.agents || [];
            agentProviderInfo = data.provider || {};
        } catch (e) {
            content.innerHTML = `<div class="glass-panel p-8 rounded-xl text-center"><p class="text-red-400 mb-4">Could not load the agents: ${agentEsc(e.message)}</p></div>`;
            return;
        }

        const provider = agentProviderInfo;
        const providerBadge = provider.engine === 'llm'
            ? `<span class="text-xs px-3 py-1.5 rounded-full bg-green-500/15 text-green-300 border border-green-500/25"><i class="fa-solid fa-microchip mr-1"></i>${agentEsc(provider.active)} &middot; ${agentEsc(provider.model)}</span>`
            : `<span class="text-xs px-3 py-1.5 rounded-full bg-yellow-500/15 text-yellow-200 border border-yellow-500/25"><i class="fa-solid fa-gears mr-1"></i>Built-in engine (add an API key for real LLMs)</span>`;

        content.innerHTML = `
        <div class="fade-in">
            <div class="flex flex-wrap justify-between items-end gap-4 mb-8">
                <div>
                    <h2 class="text-3xl font-bold text-white mb-2">Skilled AI Agents</h2>
                    <p class="text-gray-400">A team of specialists: strategy, scripting, SEO, thumbnails, voice direction, community and analytics.</p>
                </div>
                <div class="flex items-center gap-3">
                    ${providerBadge}
                    <select id="agentProviderSelect" class="bg-gray-800/50 border border-gray-700 rounded-lg px-3 py-2 text-white text-xs focus:outline-none focus:border-indigo-500">
                        <option value="auto">Auto (server default)</option>
                        ${(provider.providers || []).map(p => `<option value="${agentEsc(p.id)}">${agentEsc(p.label)}${p.configured ? '' : ' (no key)'}${p.active ? ' - active' : ''}</option>`).join('')}
                    </select>
                </div>
            </div>

            ${provider.note ? `<div class="mb-6 p-4 rounded-lg bg-indigo-500/10 border border-indigo-500/25 text-sm text-indigo-200"><i class="fa-solid fa-circle-info mr-2"></i>${agentEsc(provider.note)}</div>` : ''}

            <!-- Auto Pilot -->
            <div class="glass-panel p-6 rounded-xl mb-8 border border-purple-500/25 bg-gradient-to-br from-purple-500/10 to-indigo-500/5">
                <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
                    <div>
                        <h3 class="text-lg font-semibold text-white flex items-center gap-2"><i class="fa-solid fa-robot text-purple-400"></i>Auto Pilot <span class="text-[10px] font-bold px-2 py-0.5 rounded bg-purple-500/25 text-purple-200">MULTI-AGENT</span></h3>
                        <p class="text-sm text-gray-400">One topic in &rarr; strategy, script, voice direction, thumbnail and SEO out. Agents: ${(agentRegistry.length ? 'strategist &rarr; scriptwriter &rarr; voice director &rarr; thumbnail &rarr; SEO' : '')}</p>
                    </div>
                </div>
                <div class="grid grid-cols-1 md:grid-cols-4 gap-3 mb-4">
                    <input type="text" id="apTopic" placeholder="Video topic (required)" class="md:col-span-2 bg-gray-800/50 border border-gray-700 rounded-lg p-3 text-white text-sm focus:outline-none focus:border-purple-500">
                    <input type="text" id="apAudience" placeholder="Audience" class="bg-gray-800/50 border border-gray-700 rounded-lg p-3 text-white text-sm focus:outline-none focus:border-purple-500">
                    <input type="text" id="apGoal" placeholder="Goal (e.g. 10k subs)" class="bg-gray-800/50 border border-gray-700 rounded-lg p-3 text-white text-sm focus:outline-none focus:border-purple-500">
                </div>
                <div class="flex flex-wrap items-center gap-4">
                    <label class="flex items-center gap-2 text-sm text-gray-300"><input type="checkbox" id="apVoice" class="rounded bg-gray-700 border-gray-600 text-purple-600"> Generate voiceover too</label>
                    <label class="flex items-center gap-2 text-sm text-gray-300"><input type="checkbox" id="apThumb" class="rounded bg-gray-700 border-gray-600 text-purple-600"> Render thumbnail too</label>
                    <button onclick="runAutopilot()" id="apRunBtn" class="ml-auto bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 px-6 py-3 rounded-lg text-white font-medium transition"><i class="fa-solid fa-wand-magic-sparkles mr-2"></i>Run Auto Pilot</button>
                </div>
                <div id="apResult" class="hidden mt-6"></div>
            </div>

            <!-- Agent grid -->
            <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-8">
                ${agentRegistry.map(a => `
                <div class="glass-panel p-5 rounded-xl card-hover cursor-pointer border border-gray-700/60 hover:border-indigo-500/60 transition" onclick="selectAgent('${agentEsc(a.id)}')">
                    <div class="text-3xl mb-3">${a.emoji}</div>
                    <h4 class="text-white font-semibold mb-1">${agentEsc(a.name)}</h4>
                    <p class="text-xs text-gray-400 mb-3 leading-relaxed">${agentEsc(a.tagline)}</p>
                    <div class="flex flex-wrap gap-1.5">
                        ${(a.skills || []).slice(0, 3).map(s => `<span class="text-[10px] px-2 py-0.5 rounded-full bg-gray-700/60 text-gray-300">${agentEsc(s)}</span>`).join('')}
                    </div>
                </div>`).join('')}
            </div>

            <!-- Workspace -->
            <div id="agentWorkspace" class="hidden glass-panel p-6 rounded-xl mb-8">
                <div class="flex flex-wrap items-start justify-between gap-3 mb-5">
                    <div>
                        <h3 class="text-lg font-semibold text-white" id="agentTitle">Agent</h3>
                        <p class="text-sm text-gray-400" id="agentTagline"></p>
                    </div>
                    <button onclick="document.getElementById('agentWorkspace').classList.add('hidden'); activeAgentId = null;" class="text-gray-500 hover:text-white text-sm"><i class="fa-solid fa-xmark"></i></button>
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4" id="agentFields"></div>
                <div class="mt-5 flex items-center gap-3">
                    <button onclick="runActiveAgent()" id="agentRunBtn" class="btn-primary px-6 py-3 rounded-lg text-white font-medium"><i class="fa-solid fa-bolt mr-2"></i>Run agent</button>
                    <span class="text-xs text-gray-500" id="agentHint"></span>
                </div>
                <div id="agentResult" class="hidden mt-6"></div>
            </div>

            <!-- History -->
            <div class="glass-panel p-6 rounded-xl">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-lg font-semibold text-white">Agent activity</h3>
                    <button onclick="loadAgentRuns()" class="text-xs text-indigo-400 hover:text-indigo-300"><i class="fa-solid fa-rotate mr-1"></i>Refresh</button>
                </div>
                <div id="agentRuns" class="space-y-2 text-sm text-gray-500">Loading...</div>
            </div>
        </div>`;
        loadAgentRuns();
    }

    function agentFieldHtml(field) {
        const id = `agentField_${field.key}`;
        const cls = 'w-full bg-gray-800/50 border border-gray-700 rounded-lg p-3 text-white text-sm focus:outline-none focus:border-indigo-500';
        const label = `<label class="block text-sm font-medium text-gray-300 mb-2">${agentEsc(field.label)}${field.required ? ' <span class="text-red-400">*</span>' : ''}</label>`;
        const value = field.default === null || field.default === undefined ? '' : field.default;
        if (field.type === 'select') {
            return `<div>${label}<select id="${id}" class="${cls}">${(field.options || []).map(o => `<option value="${agentEsc(o)}" ${String(o) === String(value) ? 'selected' : ''}>${agentEsc(o)}</option>`).join('')}</select></div>`;
        }
        if (field.type === 'textarea') {
            return `<div class="md:col-span-2">${label}<textarea id="${id}" rows="4" placeholder="${agentEsc(field.placeholder || '')}" class="${cls}">${agentEsc(value)}</textarea></div>`;
        }
        if (field.type === 'number') {
            return `<div>${label}<input type="number" id="${id}" value="${agentEsc(value)}" placeholder="${agentEsc(field.placeholder || '')}" class="${cls}"></div>`;
        }
        return `<div>${label}<input type="text" id="${id}" value="${agentEsc(value)}" placeholder="${agentEsc(field.placeholder || '')}" class="${cls}"></div>`;
    }

    function selectAgent(id) {
        const agent = agentRegistry.find(a => a.id === id);
        if (!agent) return;
        activeAgentId = id;
        document.getElementById('agentWorkspace').classList.remove('hidden');
        document.getElementById('agentTitle').innerHTML = `${agent.emoji} ${agentEsc(agent.name)}`;
        document.getElementById('agentTagline').textContent = agent.tagline;
        document.getElementById('agentFields').innerHTML = (agent.fields || []).map(agentFieldHtml).join('');
        const extras = [];
        if (agent.can_render) extras.push('Set "Also generate the image" to yes to render the thumbnail.');
        if (agent.can_speak) extras.push('Paste a script and set preview=yes to hear a voice sample.');
        document.getElementById('agentHint').textContent = extras.join(' ');
        document.getElementById('agentResult').classList.add('hidden');
        document.getElementById('agentWorkspace').scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    function agentPayload(agent) {
        const payload = {};
        (agent.fields || []).forEach(field => {
            const el = document.getElementById(`agentField_${field.key}`);
            if (!el) return;
            let value = el.value;
            if (field.type === 'number') value = value === '' ? undefined : Number(value);
            if (value !== '' && value !== undefined && value !== null) payload[field.key] = value;
        });
        return payload;
    }

    async function runActiveAgent() {
        const agent = agentRegistry.find(a => a.id === activeAgentId);
        if (!agent) return;
        const payload = agentPayload(agent);
        const missing = (agent.fields || []).filter(f => f.required && !String(payload[f.key] || '').trim());
        if (missing.length) { toast(`${missing.map(m => m.label).join(', ')} is required`, 'error'); return; }

        const btn = document.getElementById('agentRunBtn');
        const out = document.getElementById('agentResult');
        const sel = document.getElementById('agentProviderSelect');
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin mr-2"></i>Working...';
        out.classList.remove('hidden');
        out.innerHTML = `<div class="flex items-center gap-3 text-gray-400 text-sm"><div class="loader"></div>${agent.emoji} ${agentEsc(agent.name)} is thinking...</div>`;
        try {
            const env = await agentFetch(`/api/agents/${agent.id}/run`, {
                method: 'POST',
                body: JSON.stringify({ payload, provider: sel ? sel.value : 'auto' })
            });
            out.innerHTML = agentResultHtml(env);
            loadAgentRuns();
        } catch (e) {
            out.innerHTML = `<div class="p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm">${agentEsc(e.message)}</div>`;
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-bolt mr-2"></i>Run agent';
        }
    }

    async function runAutopilot() {
        const topic = document.getElementById('apTopic').value.trim();
        if (!topic) { toast('Enter a video topic for Auto Pilot', 'error'); return; }
        const btn = document.getElementById('apRunBtn');
        const out = document.getElementById('apResult');
        const sel = document.getElementById('agentProviderSelect');
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin mr-2"></i>Agents working...';
        out.classList.remove('hidden');
        out.innerHTML = '<div class="flex items-center gap-3 text-gray-300 text-sm"><div class="loader"></div>Strategist &rarr; Scriptwriter &rarr; Voice Director &rarr; Thumbnail &rarr; SEO...</div>';
        try {
            const data = await agentFetch('/api/agents/autopilot', {
                method: 'POST',
                body: JSON.stringify({
                    topic,
                    audience: document.getElementById('apAudience').value.trim(),
                    goal: document.getElementById('apGoal').value.trim(),
                    provider: sel ? sel.value : 'auto',
                    generate_voiceover: document.getElementById('apVoice').checked ? 'yes' : 'no',
                    generate_thumbnail: document.getElementById('apThumb').checked ? 'yes' : 'no'
                })
            });
            const pkg = data.package || {};
            const audio = pkg.audio && pkg.audio.url ? `<audio controls src="${agentEsc(mediaUrl(pkg.audio.url, pkg.audio.data_uri))}" class="w-full mt-2"></audio>` : '';
            const thumb = pkg.thumbnail && (pkg.thumbnail.url || pkg.thumbnail.data_uri)
                ? `<img src="${agentEsc(mediaUrl(pkg.thumbnail.url, pkg.thumbnail.data_uri))}" class="rounded-lg border border-gray-700 w-full mt-2" alt="thumbnail">` : '';
            out.innerHTML = `
                <div class="border-t border-gray-700/60 pt-5">
                    <div class="flex flex-wrap items-center gap-2 mb-4">
                        <span class="text-xs px-2.5 py-1 rounded-full bg-green-500/15 text-green-300 border border-green-500/25">${(data.steps || []).length} agents ran in ${agentEsc(data.seconds)}s</span>
                        <span class="text-xs px-2.5 py-1 rounded-full bg-gray-700/60 text-gray-300">engine: ${agentEsc((data.engine_mix || []).join('+'))}</span>
                        <span class="text-xs px-2.5 py-1 rounded-full bg-gray-700/60 text-gray-300">provider: ${agentEsc((data.providers || []).join('+'))}</span>
                    </div>
                    <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
                        <div>
                            <p class="text-xs uppercase tracking-wider text-gray-500 mb-2">Ready-to-publish package</p>
                            <div class="space-y-3">
                                <div><p class="text-xs text-gray-500 mb-1">Title</p><p class="text-white font-medium">${agentEsc(pkg.title || '')}</p></div>
                                <div><p class="text-xs text-gray-500 mb-1">Description</p><pre class="whitespace-pre-wrap text-sm text-gray-300 bg-gray-900/60 border border-gray-700/60 rounded-lg p-3 max-h-40 overflow-y-auto custom-scrollbar">${agentEsc(pkg.description || '')}</pre></div>
                                <div><p class="text-xs text-gray-500 mb-1">Tags (${(pkg.tags || []).length})</p><div class="flex flex-wrap gap-1.5">${(pkg.tags || []).map(t => `<span class="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/15 text-indigo-300">${agentEsc(t)}</span>`).join('')}</div></div>
                                <div class="flex flex-wrap gap-2">
                                    <button onclick="agentCopyText(${JSON.stringify('').replace(/"/g, '')} || document.getElementById('apPackageScript').innerText, 'Script')" class="text-xs bg-gray-700 hover:bg-gray-600 px-3 py-2 rounded-lg text-white"><i class="fa-regular fa-copy mr-1"></i>Copy script</button>
                                    <button onclick="agentSendToStudio(document.getElementById('apPackageScript').innerText, '${agentEsc((pkg.voice || {}).voice_key || '')}')" class="text-xs bg-indigo-600 hover:bg-indigo-500 px-3 py-2 rounded-lg text-white"><i class="fa-solid fa-microphone mr-1"></i>Open in AI Studio</button>
                                    <button onclick="agentSendToImage(document.getElementById('apThumbPrompt').innerText)" class="text-xs bg-purple-600 hover:bg-purple-500 px-3 py-2 rounded-lg text-white"><i class="fa-solid fa-image mr-1"></i>Render thumbnail</button>
                                    <button onclick="agentDownload('autopilot-package.txt', document.getElementById('apPackageScript').innerText)" class="text-xs bg-gray-700 hover:bg-gray-600 px-3 py-2 rounded-lg text-white"><i class="fa-solid fa-download mr-1"></i>Download</button>
                                </div>
                            </div>
                        </div>
                        <div>
                            <p class="text-xs uppercase tracking-wider text-gray-500 mb-2">Script (${agentEsc(pkg.word_count || 0)} words &middot; ${agentEsc(pkg.duration_seconds || 0)}s &middot; voice: ${agentEsc((pkg.voice || {}).name || 'n/a')})</p>
                            <pre id="apPackageScript" class="whitespace-pre-wrap text-sm text-gray-200 bg-gray-900/60 border border-gray-700/60 rounded-lg p-3 max-h-72 overflow-y-auto custom-scrollbar">${agentEsc(pkg.script || '')}</pre>
                            <pre id="apThumbPrompt" class="hidden">${agentEsc((pkg.thumbnail || {}).prompt || '')}</pre>
                            ${audio}${thumb}
                        </div>
                    </div>
                    <div class="mt-5">
                        <p class="text-xs uppercase tracking-wider text-gray-500 mb-2">Each agent's output</p>
                        <div class="space-y-3">${(data.agents || []).map(env => `
                            <details class="p-3 rounded-lg bg-gray-800/40 border border-gray-700/60">
                                <summary class="cursor-pointer text-sm text-white">${agentEsc(env.emoji || '')} ${agentEsc(env.name)} <span class="text-xs text-gray-500">&middot; ${agentEsc(env.engine)} ${agentEsc(env.provider || '')}</span></summary>
                                <div class="mt-3">${agentResultHtml(env, true)}</div>
                            </details>`).join('')}
                        </div>
                    </div>
                    <div class="mt-5 flex flex-wrap gap-2">
                        <button onclick="navigate('youtube')" class="text-xs bg-red-600 hover:bg-red-500 px-4 py-2 rounded-lg text-white"><i class="fa-brands fa-youtube mr-1"></i>Publish on YouTube</button>
                    </div>
                </div>`;
            toast('Auto Pilot finished', 'success');
            loadAgentRuns();
        } catch (e) {
            out.innerHTML = `<div class="p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm">${agentEsc(e.message)}</div>`;
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles mr-2"></i>Run Auto Pilot';
        }
    }

    function agentRenderMedia(key, value) {
        if (!value || typeof value !== 'object') return '';
        if (value.status === 'failed') {
            return `<div class="mb-3 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/25 text-xs text-yellow-200">${agentLabel(key)}: ${agentEsc(value.error || 'failed')}</div>`;
        }
        const src = mediaUrl(value.url, value.data_uri);
        if (!src) return agentRenderObject(value, 1);
        const isAudio = /audio|sample|voice/i.test(key) || /\.mp3|\.wav|\.ogg/i.test(String(value.filename || value.url || ''));
        const media = isAudio
            ? `<audio controls src="${agentEsc(src)}" class="w-full mt-2"></audio>`
            : `<img src="${agentEsc(src)}" alt="${agentEsc(key)}" class="rounded-lg border border-gray-700 max-h-64 mt-2">`;
        return `<div class="mb-4"><p class="text-xs uppercase tracking-wider text-gray-500">${agentLabel(key)}</p>${media}</div>`;
    }

    function agentRenderObject(obj, depth, index) {
        if (!obj || typeof obj !== 'object') return agentEsc(obj);
        const skip = ['created_at', 'data_uri'];
        const heading = obj.title || obj.name || obj.beat || obj.metric || obj.comment || obj.style || obj.day;
        let html = '';
        if (heading && depth > 0) {
            html += `<p class="text-sm font-medium text-white mb-2">${typeof index === 'number' ? `<span class="text-gray-500 mr-2">#${index + 1}</span>` : ''}${agentEsc(heading)}</p>`;
        }
        Object.keys(obj).forEach(key => {
            if (skip.indexOf(key) !== -1) return;
            if (heading && (key === 'title' || key === 'name' || key === 'metric')) return;
            html += agentRenderValue(key, obj[key], depth);
        });
        return html || '<span class="text-xs text-gray-600">empty</span>';
    }

    function agentRenderValue(key, value, depth) {
        depth = depth || 0;
        if (value === null || value === undefined || value === '') return '';
        const label = agentLabel(key);

        if (Array.isArray(value)) {
            if (!value.length) return '';
            const scalar = value.every(v => typeof v === 'string' || typeof v === 'number');
            if (scalar) {
                if (['tags', 'hashtags', 'thumbnail_text', 'secondary_keywords', 'skills'].indexOf(key) !== -1) {
                    return `<div class="mb-3"><p class="text-xs uppercase tracking-wider text-gray-500 mb-2">${label}</p><div class="flex flex-wrap gap-1.5">${value.map(v => `<span class="text-[11px] px-2.5 py-1 rounded-full bg-indigo-500/15 text-indigo-300 border border-indigo-500/25">${agentEsc(v)}</span>`).join('')}</div></div>`;
                }
                return `<div class="mb-3"><p class="text-xs uppercase tracking-wider text-gray-500 mb-2">${label}</p><ul class="space-y-1 list-disc list-inside text-sm text-gray-300">${value.map(v => `<li>${agentEsc(v)}</li>`).join('')}</ul></div>`;
            }
            if (depth > 3) return `<pre class="text-xs text-gray-400 bg-gray-900/60 rounded-lg p-2 overflow-x-auto">${agentEsc(JSON.stringify(value, null, 2))}</pre>`;
            return `<div class="mb-3"><p class="text-xs uppercase tracking-wider text-gray-500 mb-2">${label}</p><div class="space-y-2">${value.map((item, i) => `<div class="p-3 rounded-lg bg-gray-800/40 border border-gray-700/50">${agentRenderObject(item, depth + 1, i)}</div>`).join('')}</div></div>`;
        }

        if (typeof value === 'object') {
            if (['rendered', 'sample', 'audio', 'thumbnail', 'image'].indexOf(key) !== -1) return agentRenderMedia(key, value);
            if (depth > 3) return `<pre class="text-xs text-gray-400 bg-gray-900/60 rounded-lg p-2 overflow-x-auto">${agentEsc(JSON.stringify(value, null, 2))}</pre>`;
            return `<div class="mb-3"><p class="text-xs uppercase tracking-wider text-gray-500 mb-2">${label}</p><div class="p-3 rounded-lg bg-gray-800/40 border border-gray-700/50">${agentRenderObject(value, depth + 1)}</div></div>`;
        }

        if (typeof value === 'boolean') value = value ? 'yes' : 'no';

        if (['script', 'content', 'description', 'reply', 'image_prompt', 'prompt', 'direction', 'comment', 'positioning', 'text', 'first_line', 'hook', 'cta'].indexOf(key) !== -1) {
            return `<div class="mb-3"><div class="flex items-center justify-between mb-1"><p class="text-xs uppercase tracking-wider text-gray-500">${label}</p><button onclick="agentCopy(this)" data-copy="${encodeURIComponent(String(value))}" class="text-[11px] text-indigo-400 hover:text-indigo-300"><i class="fa-regular fa-copy mr-1"></i>copy</button></div><pre class="whitespace-pre-wrap text-sm text-gray-200 bg-gray-900/60 border border-gray-700/50 rounded-lg p-3 max-h-64 overflow-y-auto custom-scrollbar">${agentEsc(value)}</pre></div>`;
        }

        if (/url|thumbnail|picture/i.test(key) && typeof value === 'string' && /^(https?:|\/|data:)/.test(value)) {
            return `<div class="mb-2"><span class="text-gray-500 text-sm">${label}:</span> <a href="${agentEsc(value)}" target="_blank" rel="noopener" class="text-sm text-indigo-400 hover:underline break-all">${agentEsc(String(value).slice(0, 80))}</a></div>`;
        }

        if (['score', 'predicted_ctr', 'chars', 'words', 'word_count', 'estimated_seconds', 'total'].indexOf(key) !== -1) {
            return `<span class="inline-block mr-2 mb-2 text-[11px] px-2.5 py-1 rounded-full bg-gray-700/60 text-gray-200">${label}: ${agentEsc(value)}</span>`;
        }

        return `<div class="mb-1.5 text-sm"><span class="text-gray-500">${label}:</span> <span class="text-gray-200">${agentEsc(value)}</span></div>`;
    }

    function agentResultHtml(env, compact) {
        const result = env.result || {};
        const actions = [];
        const script = result.script || result.content;
        if (script) {
            actions.push(`<button onclick="agentSendToStudio(this.dataset.script, '${agentEsc((result.voice || {}).voice_key || env.voice_key || '')}')" data-script="${encodeURIComponent(String(script).slice(0, 6000))}" class="text-xs bg-indigo-600 hover:bg-indigo-500 px-3 py-2 rounded-lg text-white"><i class="fa-solid fa-microphone mr-1"></i>Voiceover this</button>`);
            actions.push(`<button onclick="agentSendToScript('${agentEsc(String(result.topic || env.topic || '').slice(0, 120))}', this.dataset.script)" data-script="${encodeURIComponent(String(script).slice(0, 15000))}" class="text-xs bg-gray-700 hover:bg-gray-600 px-3 py-2 rounded-lg text-white"><i class="fa-solid fa-pen mr-1"></i>Edit in Script Writer</button>`);
        }
        const imagePrompt = result.image_prompt || (result.best_concept || {}).prompt;
        if (imagePrompt) {
            actions.push(`<button onclick="agentSendToImage(this.dataset.prompt)" data-prompt="${encodeURIComponent(String(imagePrompt).slice(0, 1000))}" class="text-xs bg-purple-600 hover:bg-purple-500 px-3 py-2 rounded-lg text-white"><i class="fa-solid fa-image mr-1"></i>Render this</button>`);
        }
        if (result.best_title) {
            actions.push(`<button onclick="agentCopyText(this.dataset.title, 'Title')" data-title="${encodeURIComponent(String(result.best_title))}" class="text-xs bg-gray-700 hover:bg-gray-600 px-3 py-2 rounded-lg text-white"><i class="fa-regular fa-copy mr-1"></i>Copy title</button>`);
        }
        if (result.tags && result.tags.length) {
            actions.push(`<button onclick="agentCopyText(this.dataset.tags, 'Tags')" data-tags="${encodeURIComponent(String(result.tags.join(', ')))}" class="text-xs bg-gray-700 hover:bg-gray-600 px-3 py-2 rounded-lg text-white"><i class="fa-solid fa-tags mr-1"></i>Copy tags</button>`);
        }
        actions.push(`<button onclick="agentDownload('${agentEsc(env.agent || 'agent')}-result.json', this.dataset.json)" data-json="${encodeURIComponent(JSON.stringify(result, null, 2))}" class="text-xs bg-gray-700 hover:bg-gray-600 px-3 py-2 rounded-lg text-white"><i class="fa-solid fa-download mr-1"></i>JSON</button>`);

        const badge = env.engine === 'llm'
            ? `<span class="text-[11px] px-2.5 py-1 rounded-full bg-green-500/15 text-green-300 border border-green-500/25"><i class="fa-solid fa-microchip mr-1"></i>${agentEsc(env.provider)} &middot; ${agentEsc(env.model)}</span>`
            : `<span class="text-[11px] px-2.5 py-1 rounded-full bg-yellow-500/15 text-yellow-200 border border-yellow-500/25"><i class="fa-solid fa-gears mr-1"></i>built-in engine</span>`;

        return `
            <div class="${compact ? '' : 'border-t border-gray-700/60 pt-5'}">
                <div class="flex flex-wrap items-center gap-2 mb-4">
                    ${badge}
                    ${env.error ? `<span class="text-[11px] px-2.5 py-1 rounded-full bg-red-500/15 text-red-300 border border-red-500/25" title="${agentEsc(env.error)}"><i class="fa-solid fa-triangle-exclamation mr-1"></i>LLM unavailable, used built-in</span>` : ''}
                    <span class="text-[11px] text-gray-500 ml-auto">${agentEsc(env.created_at || '')}</span>
                </div>
                <div class="flex flex-wrap gap-2 mb-5">${actions.join('')}</div>
                <div>${agentRenderObject(result, 0)}</div>
            </div>`;
    }

    async function loadAgentRuns() {
        const box = document.getElementById('agentRuns');
        if (!box) return;
        try {
            agentRunsCache = await agentFetch('/api/agents/runs?limit=25');
            if (!agentRunsCache.length) {
                box.innerHTML = '<div class="text-sm text-gray-500">No agent runs yet - pick an agent above.</div>';
                return;
            }
            box.innerHTML = agentRunsCache.map(run => `
                <div class="flex items-center gap-3 p-3 rounded-lg bg-gray-800/30 border border-gray-700/50">
                    <span class="text-lg">${agentEsc(run.emoji || '')}</span>
                    <div class="flex-1 min-w-0">
                        <p class="text-sm text-white truncate">${agentEsc(run.title || run.agent_name || run.agent)}</p>
                        <p class="text-[11px] text-gray-500">${agentEsc(run.engine || '')} &middot; ${agentEsc(run.provider || '')} &middot; ${agentEsc(String(run.created_at || '').slice(0, 19).replace('T', ' '))}</p>
                    </div>
                    <button onclick="openAgentRun(${run.id})" class="text-xs text-indigo-400 hover:text-indigo-300 px-2 py-1">Open</button>
                    <button onclick="deleteAgentRun(${run.id})" class="text-xs text-gray-500 hover:text-red-400 px-2 py-1"><i class="fa-regular fa-trash-can"></i></button>
                </div>`).join('');
        } catch (e) {
            box.innerHTML = `<div class="text-sm text-red-400">${agentEsc(e.message)}</div>`;
        }
    }

    function openAgentRun(id) {
        const run = agentRunsCache.find(r => r.id === id);
        if (!run) return;
        const ws = document.getElementById('agentWorkspace');
        if (!ws) return;
        ws.classList.remove('hidden');
        document.getElementById('agentTitle').innerHTML = `${agentEsc(run.emoji || '')} ${agentEsc(run.agent_name || run.agent)} <span class="text-xs text-gray-500">(saved run)</span>`;
        document.getElementById('agentTagline').textContent = run.title || '';
        document.getElementById('agentFields').innerHTML = Object.keys(run.payload || {}).map(key =>
            `<div><label class="block text-sm font-medium text-gray-300 mb-2">${agentLabel(key)}</label><pre class="whitespace-pre-wrap text-sm text-gray-200 bg-gray-900/60 border border-gray-700/60 rounded-lg p-3">${agentEsc(run.payload[key])}</pre></div>`).join('');
        const out = document.getElementById('agentResult');
        out.classList.remove('hidden');
        out.innerHTML = agentResultHtml({
            agent: run.agent, engine: run.engine, provider: run.provider, model: run.model,
            result: run.result || {}, created_at: run.created_at
        });
        ws.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    async function deleteAgentRun(id) {
        try {
            await agentFetch(`/api/agents/runs/${id}`, { method: 'DELETE' });
            toast('Run deleted', 'success');
            loadAgentRuns();
        } catch (e) { toast(e.message, 'error'); }
    }

    // ============================================================================
    // YOUTUBE CHANNEL CONNECTION
    // ============================================================================
    let ytChannels = [];
    let ytAuthStatus = null;
    let ytVideos = [];
    let ytComments = [];
    let ytCommentVideoId = '';
    let ytCanReply = false;

    function ytNumber(value) {
        const n = Number(value || 0);
        if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
        if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
        return String(n);
    }

    async function loadYouTubeChannels() {
        const list = document.getElementById('ytChannelList');
        if (!list) return;
        try { ytAuthStatus = await agentFetch('/api/youtube/auth/status'); } catch (e) { ytAuthStatus = null; }
        try {
            const data = await agentFetch('/api/youtube/channels');
            ytChannels = data.channels || [];
        } catch (e) { ytChannels = []; }

        const notice = document.getElementById('ytSetupNotice');
        const label = document.getElementById('googleConnectLabel');
        if (notice && ytAuthStatus && !ytAuthStatus.oauth_configured) {
            notice.classList.remove('hidden');
            notice.innerHTML = `<p class="font-semibold mb-2"><i class="fa-solid fa-triangle-exclamation mr-2"></i>Google OAuth is not configured on the server yet</p>
                <ol class="list-decimal list-inside space-y-1 text-xs text-yellow-100/80">${(ytAuthStatus.setup.steps || []).map(s => `<li>${agentEsc(s)}</li>`).join('')}</ol>
                <p class="text-xs mt-2 text-yellow-100/70">Register this redirect URI: <code class="bg-black/30 px-1.5 py-0.5 rounded break-all">${agentEsc(ytAuthStatus.redirect_uri || '')}</code></p>`;
            if (label) label.textContent = 'Continue with Google';
        } else if (notice) {
            notice.classList.add('hidden');
        }

        if (!ytChannels.length) {
            list.innerHTML = `<div class="col-span-full text-sm text-gray-500 py-8 text-center border border-dashed border-gray-700 rounded-xl">
                <i class="fa-brands fa-youtube text-2xl mb-2 block text-red-500/60"></i>
                No channel connected yet.<br>Click <span class="text-white font-medium">Continue with Google</span> - every channel on that Google account will be listed, and you can connect more accounts later.
            </div>`;
            document.getElementById('ytChannelTools')?.classList.add('hidden');
            return;
        }

        list.innerHTML = ytChannels.map(ch => `
            <div class="p-4 rounded-xl bg-gray-800/40 border ${ch.is_primary ? 'border-indigo-500/60' : 'border-gray-700/60'}">
                <div class="flex items-start gap-3">
                    ${ch.thumbnail ? `<img src="${agentEsc(ch.thumbnail)}" alt="" class="w-12 h-12 rounded-full object-cover border border-gray-700">` : '<div class="w-12 h-12 rounded-full bg-gray-700 flex items-center justify-center"><i class="fa-brands fa-youtube text-red-500"></i></div>'}
                    <div class="flex-1 min-w-0">
                        <p class="text-white font-medium truncate">${agentEsc(ch.title)}</p>
                        <p class="text-[11px] text-gray-500 truncate">${agentEsc(ch.google_email || '')}</p>
                        <div class="flex flex-wrap gap-2 mt-2 text-[11px] text-gray-400">
                            <span><i class="fa-solid fa-user-group mr-1"></i>${ytNumber(ch.stats && ch.stats.subscribers)} subs</span>
                            <span><i class="fa-solid fa-eye mr-1"></i>${ytNumber(ch.stats && ch.stats.views)} views</span>
                            <span><i class="fa-solid fa-video mr-1"></i>${ytNumber(ch.stats && ch.stats.videos)} videos</span>
                        </div>
                        <div class="flex flex-wrap gap-1.5 mt-2">
                            ${ch.is_primary ? '<span class="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">PRIMARY</span>' : ''}
                            <span class="text-[10px] px-2 py-0.5 rounded-full ${ch.mode === 'oauth' ? 'bg-green-500/15 text-green-300' : 'bg-gray-700/60 text-gray-300'}">${ch.mode === 'oauth' ? 'full access' : 'read-only'}</span>
                            ${ch.token_expired ? '<span class="text-[10px] px-2 py-0.5 rounded-full bg-yellow-500/15 text-yellow-200">token expiring</span>' : ''}
                        </div>
                    </div>
                </div>
                <div class="flex flex-wrap gap-2 mt-3">
                    ${ch.is_primary ? '' : `<button onclick="setPrimaryChannel('${agentEsc(ch.channel_id)}')" class="text-[11px] bg-gray-700 hover:bg-gray-600 px-2.5 py-1.5 rounded-lg text-white">Set primary</button>`}
                    <button onclick="loadYtVideos('${agentEsc(ch.channel_id)}')" class="text-[11px] bg-gray-700 hover:bg-gray-600 px-2.5 py-1.5 rounded-lg text-white">Videos</button>
                    <button onclick="showChannelAnalytics('${agentEsc(ch.channel_id)}')" class="text-[11px] bg-gray-700 hover:bg-gray-600 px-2.5 py-1.5 rounded-lg text-white"><i class="fa-solid fa-chart-line mr-1"></i>AI analytics</button>
                    <button onclick="refreshChannel('${agentEsc(ch.channel_id)}')" class="text-[11px] bg-gray-700 hover:bg-gray-600 px-2.5 py-1.5 rounded-lg text-white">Sync</button>
                    <button onclick="disconnectChannel('${agentEsc(ch.channel_id)}')" class="text-[11px] bg-red-500/15 hover:bg-red-500/25 text-red-300 px-2.5 py-1.5 rounded-lg">Disconnect</button>
                </div>
            </div>`).join('');

        document.getElementById('ytChannelTools')?.classList.remove('hidden');
        const sel = document.getElementById('ytUploadChannel');
        if (sel) {
            const uploadable = ytChannels.filter(c => c.can_upload);
            sel.innerHTML = uploadable.length
                ? uploadable.map(c => `<option value="${agentEsc(c.channel_id)}">${agentEsc(c.title)}</option>`).join('')
                : '<option value="">No channel with upload access</option>';
        }
    }

    async function connectGoogle() {
        try {
            const data = await agentFetch('/api/youtube/auth/url');
            if (!data.url) throw new Error('The server did not return a Google sign-in URL');
            sessionStorage.setItem('bglabs_google_state', data.state || '');
            toast('Opening Google sign-in...', 'info');
            window.location.href = data.url;
        } catch (e) {
            toast(e.message, 'error');
            const notice = document.getElementById('ytSetupNotice');
            if (notice) {
                notice.classList.remove('hidden');
                notice.innerHTML = `<p class="font-semibold mb-1"><i class="fa-solid fa-triangle-exclamation mr-2"></i>${agentEsc(e.message)}</p>
                    <p class="text-xs text-yellow-100/80">Add <code>GOOGLE_CLIENT_ID</code> and <code>GOOGLE_CLIENT_SECRET</code> to the Vercel environment variables, then redeploy.</p>`;
            }
        }
    }

    function handleYouTubeReturn() {
        const params = new URLSearchParams(window.location.search);
        const status = params.get('yt');
        if (!status) return;
        if (status === 'connected') {
            const count = params.get('channels') || '1';
            const names = params.get('names') || '';
            toast(`YouTube connected: ${count} channel(s)${names ? ' - ' + names : ''}`, 'success');
        } else {
            const reason = params.get('reason') || 'unknown';
            const detail = params.get('detail') || '';
            toast(`Google connect failed (${reason})${detail ? ': ' + detail : ''}`, 'error');
        }
        history.replaceState({}, document.title, window.location.pathname + window.location.hash);
    }

    async function setPrimaryChannel(channelId) {
        try {
            await agentFetch(`/api/youtube/channels/${encodeURIComponent(channelId)}/primary`, { method: 'POST' });
            toast('Primary channel updated', 'success');
            loadYouTubeChannels();
        } catch (e) { toast(e.message, 'error'); }
    }

    async function disconnectChannel(channelId) {
        if (!confirm('Disconnect this channel? Stored tokens will be deleted.')) return;
        try {
            const res = await agentFetch(`/api/youtube/channels/${encodeURIComponent(channelId)}`, { method: 'DELETE' });
            toast(`Disconnected (${res.remaining} channel(s) left)`, 'success');
            loadYouTubeChannels();
        } catch (e) { toast(e.message, 'error'); }
    }

    async function refreshChannel(channelId) {
        try {
            await agentFetch(`/api/youtube/channels/${encodeURIComponent(channelId)}/refresh`, { method: 'POST' });
            toast('Channel synced with YouTube', 'success');
            loadYouTubeChannels();
        } catch (e) { toast(e.message, 'error'); }
    }

    async function loadYtVideos(channelId) {
        const box = document.getElementById('ytVideoList');
        if (!box) return;
        const ch = channelId || ((ytChannels.find(c => c.is_primary) || ytChannels[0] || {}).channel_id);
        if (!ch) { toast('Connect a channel first', 'error'); return; }
        box.innerHTML = '<div class="loader"></div>';
        try {
            const data = await agentFetch(`/api/youtube/videos?channel_id=${encodeURIComponent(ch)}&max=12`);
            ytVideos = data.videos || [];
            if (!ytVideos.length) { box.innerHTML = '<div class="text-sm text-gray-500">No uploads found on this channel.</div>'; return; }
            box.innerHTML = ytVideos.map(v => `
                <div class="flex items-center gap-3 p-2 rounded-lg bg-gray-800/40 border border-gray-700/50">
                    ${v.thumbnail ? `<img src="${agentEsc(v.thumbnail)}" class="w-20 h-12 rounded object-cover" alt="">` : ''}
                    <div class="flex-1 min-w-0">
                        <p class="text-white text-sm truncate">${agentEsc(v.title)}</p>
                        <p class="text-[11px] text-gray-500"><i class="fa-solid fa-eye mr-1"></i>${ytNumber(v.stats && v.stats.views)} <i class="fa-solid fa-thumbs-up ml-2 mr-1"></i>${ytNumber(v.stats && v.stats.likes)} <i class="fa-solid fa-comment ml-2 mr-1"></i>${ytNumber(v.stats && v.stats.comments)}</p>
                    </div>
                    <div class="flex flex-col gap-1">
                        <button onclick="openYtComments('${agentEsc(v.video_id)}', this.dataset.title)" data-title="${encodeURIComponent(v.title || '')}" class="text-[11px] bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded text-white">Comments</button>
                        <a href="${agentEsc(v.url)}" target="_blank" rel="noopener" class="text-[11px] text-indigo-400 hover:text-indigo-300 px-2 py-1">Open</a>
                    </div>
                </div>`).join('');
        } catch (e) {
            box.innerHTML = `<div class="text-sm text-red-400">${agentEsc(e.message)}</div>`;
        }
    }

    async function showChannelAnalytics(channelId) {
        const panel = document.getElementById('ytConnectPanel');
        if (!panel) return;
        let box = document.getElementById('ytAnalyticsBox');
        if (!box) {
            box = document.createElement('div');
            box.id = 'ytAnalyticsBox';
            box.className = 'mt-6 pt-6 border-t border-gray-700/60';
            panel.appendChild(box);
        }
        box.innerHTML = '<div class="flex items-center gap-3 text-gray-400 text-sm"><div class="loader"></div>Pulling channel numbers and running the analytics agent...</div>';
        box.scrollIntoView({ behavior: 'smooth', block: 'center' });
        try {
            const data = await agentFetch(`/api/youtube/analytics?channel_id=${encodeURIComponent(channelId || '')}`);
            const stats = (data.channel && data.channel.stats) || {};
            const insight = data.insight || {};
            box.innerHTML = `
                <div class="flex items-center justify-between mb-3">
                    <h4 class="text-sm font-semibold text-white uppercase tracking-wider"><i class="fa-solid fa-chart-line mr-2 text-indigo-400"></i>Analytics - ${agentEsc((data.channel || {}).title || '')}</h4>
                    <button onclick="document.getElementById('ytAnalyticsBox').innerHTML=''" class="text-xs text-gray-500 hover:text-white">Close</button>
                </div>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                    ${[['Subscribers', stats.subscribers], ['Total views', stats.views], ['Videos', stats.videos], ['Recent avg views', (data.recent_totals || {}).avg_views]].map(pair => `
                    <div class="p-3 rounded-lg bg-gray-800/40 border border-gray-700/50"><p class="text-[11px] text-gray-500">${pair[0]}</p><p class="text-white font-semibold">${ytNumber(pair[1])}</p></div>`).join('')}
                </div>
                ${insight.result ? agentResultHtml(insight, true) : ''}`;
        } catch (e) {
            box.innerHTML = `<div class="p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm">${agentEsc(e.message)}</div>`;
        }
    }

    async function openYtComments(videoId, encodedTitle) {
        ytCommentVideoId = videoId;
        const box = document.getElementById('ytCommentTools');
        const list = document.getElementById('ytCommentList');
        if (!box || !list) return;
        box.classList.remove('hidden');
        try { document.getElementById('ytCommentVideoTitle').textContent = decodeURIComponent(encodedTitle || '').slice(0, 70); } catch (e) { }
        list.innerHTML = '<div class="loader"></div>';
        box.scrollIntoView({ behavior: 'smooth', block: 'center' });
        try {
            const data = await agentFetch(`/api/youtube/comments?video_id=${encodeURIComponent(videoId)}&max=25`);
            ytComments = data.comments || [];
            ytCanReply = !!data.can_reply;
            if (!ytComments.length) { list.innerHTML = '<div class="text-sm text-gray-500">No comments on this video yet.</div>'; return; }
            list.innerHTML = ytComments.map((c, i) => `
                <div class="p-3 rounded-lg bg-gray-800/40 border border-gray-700/50">
                    <div class="flex items-start gap-3">
                        ${c.author_thumbnail ? `<img src="${agentEsc(c.author_thumbnail)}" class="w-8 h-8 rounded-full" alt="">` : ''}
                        <div class="flex-1 min-w-0">
                            <p class="text-xs text-gray-400">${agentEsc(c.author)} <span class="text-gray-600">&middot; <i class="fa-solid fa-thumbs-up"></i> ${ytNumber(c.likes)} &middot; ${agentEsc(String(c.published_at || '').slice(0, 10))}</span></p>
                            <p class="text-sm text-gray-200 mt-1">${agentEsc(c.text)}</p>
                            <textarea id="ytReply_${i}" rows="2" placeholder="${ytCanReply ? 'Write a reply or let the AI agent draft one' : 'Read-only connection - reconnect with Google to post replies'}" class="w-full mt-2 bg-gray-900/60 border border-gray-700 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-indigo-500" ${ytCanReply ? '' : 'disabled'}></textarea>
                            <div class="flex flex-wrap gap-2 mt-2">
                                ${ytCanReply ? `<button onclick="aiDraftReply(${i})" class="text-[11px] bg-purple-600 hover:bg-purple-500 px-2.5 py-1.5 rounded-lg text-white"><i class="fa-solid fa-robot mr-1"></i>AI draft</button>
                                <button onclick="postYtReply(${i})" class="text-[11px] bg-indigo-600 hover:bg-indigo-500 px-2.5 py-1.5 rounded-lg text-white"><i class="fa-solid fa-paper-plane mr-1"></i>Post reply</button>` : ''}
                                <button onclick="agentCopyText(document.getElementById('ytReply_${i}').value || ${JSON.stringify('')}, 'Reply')" class="text-[11px] bg-gray-700 hover:bg-gray-600 px-2.5 py-1.5 rounded-lg text-white">Copy</button>
                            </div>
                            <p id="ytReplyStatus_${i}" class="text-[11px] mt-1 hidden"></p>
                        </div>
                    </div>
                </div>`).join('');
        } catch (e) {
            list.innerHTML = `<div class="text-sm text-red-400">${agentEsc(e.message)}</div>`;
        }
    }

    async function aiDraftReply(index) {
        const comment = ytComments[index];
        if (!comment) return;
        const status = document.getElementById(`ytReplyStatus_${index}`);
        const box = document.getElementById(`ytReply_${index}`);
        status.classList.remove('hidden');
        status.className = 'text-[11px] mt-1 text-gray-400';
        status.textContent = 'Comment Responder agent is drafting...';
        try {
            const data = await agentFetch('/api/youtube/comments/reply', {
                method: 'POST',
                body: JSON.stringify({
                    video_id: ytCommentVideoId, comment_id: comment.comment_id, comment: comment.text,
                    video_topic: document.getElementById('ytUploadTitle')?.value || '', dry_run: 'yes'
                })
            });
            box.value = data.reply || '';
            status.textContent = `Drafted by ${data.generated_by || 'the agent'} - edit before posting.`;
        } catch (e) {
            status.className = 'text-[11px] mt-1 text-red-400';
            status.textContent = e.message;
        }
    }

    async function postYtReply(index) {
        const comment = ytComments[index];
        const box = document.getElementById(`ytReply_${index}`);
        const status = document.getElementById(`ytReplyStatus_${index}`);
        const text = (box.value || '').trim();
        if (!text) { toast('Write or draft a reply first', 'error'); return; }
        status.classList.remove('hidden');
        status.className = 'text-[11px] mt-1 text-gray-400';
        status.textContent = 'Posting to YouTube...';
        try {
            const data = await agentFetch('/api/youtube/comments/reply', {
                method: 'POST',
                body: JSON.stringify({ video_id: ytCommentVideoId, comment_id: comment.comment_id, text })
            });
            status.className = 'text-[11px] mt-1 text-green-400';
            status.textContent = 'Posted to YouTube.';
            box.disabled = true;
            toast('Reply posted', 'success');
        } catch (e) {
            status.className = 'text-[11px] mt-1 text-red-400';
            status.textContent = e.message;
        }
    }

    async function aiReplyAll() {
        if (!ytComments.length) { toast('Load comments first', 'error'); return; }
        const limit = Math.min(ytComments.length, 10);
        toast(`Drafting replies for ${limit} comments...`, 'info');
        for (let i = 0; i < limit; i++) {
            await aiDraftReply(i);
        }
        toast('AI drafts ready - review before posting', 'success');
    }

    async function aiFillMetadata() {
        const topic = (document.getElementById('ytTopic')?.value || '').trim()
            || (document.getElementById('ytUploadTitle')?.value || '').trim();
        if (!topic) { toast('Enter a topic in the automation panel (or a title) first', 'error'); return; }
        toast('SEO agent is writing your metadata...', 'info');
        try {
            const env = await agentFetch('/api/agents/seo/run', { method: 'POST', body: JSON.stringify({ payload: { topic } }) });
            const r = env.result || {};
            if (document.getElementById('ytUploadTitle')) document.getElementById('ytUploadTitle').value = r.best_title || topic;
            if (document.getElementById('ytUploadDesc')) document.getElementById('ytUploadDesc').value = r.description || '';
            if (document.getElementById('ytUploadTags')) document.getElementById('ytUploadTags').value = (r.tags || []).join(', ');
            toast(`Metadata written by the SEO agent (${env.engine})`, 'success');
        } catch (e) { toast(e.message, 'error'); }
    }

    function xhrRequest(method, url, headers, body, onProgress) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open(method, url, true);
            Object.keys(headers || {}).forEach(key => {
                try { xhr.setRequestHeader(key, headers[key]); } catch (e) { /* forbidden header */ }
            });
            if (onProgress && xhr.upload) {
                xhr.upload.onprogress = ev => { if (ev.lengthComputable) onProgress(Math.round((ev.loaded / ev.total) * 100)); };
            }
            xhr.onload = () => resolve({
                status: xhr.status,
                text: xhr.responseText,
                location: xhr.getResponseHeader('Location'),
                json: () => { try { return JSON.parse(xhr.responseText); } catch (e) { return null; } }
            });
            xhr.onerror = () => reject(new Error('Network error while talking to Google (CORS or offline)'));
            xhr.send(body);
        });
    }

    async function googleUploadVideo(plan, file, onProgress) {
        const start = await xhrRequest('POST', plan.url, plan.headers, JSON.stringify(plan.body));
        if (start.status < 200 || start.status >= 300) {
            throw new Error(`Google rejected the upload start (${start.status}): ${String(start.text || '').slice(0, 220)}`);
        }
        const sessionUrl = start.location;
        if (!sessionUrl) throw new Error('Google did not return an upload session URL');
        const putHeaders = {
            'Authorization': plan.headers['Authorization'],
            'Content-Type': file.type || 'video/mp4',
            'Content-Range': `bytes 0-${Math.max(0, file.size - 1)}/${file.size}`
        };
        const done = await xhrRequest('PUT', sessionUrl, putHeaders, file, onProgress);
        if (done.status < 200 || done.status >= 300) {
            throw new Error(`Upload failed (${done.status}): ${String(done.text || '').slice(0, 220)}`);
        }
        return done.json() || {};
    }

    async function publishToYouTube() {
        const fileEl = document.getElementById('ytUploadFile');
        const file = fileEl && fileEl.files && fileEl.files[0];
        const title = (document.getElementById('ytUploadTitle').value || '').trim();
        if (!title) { toast('Video title is required', 'error'); return; }
        if (!file) { toast('Choose a video file to upload', 'error'); return; }
        const channelSel = document.getElementById('ytUploadChannel');
        const channelId = channelSel ? channelSel.value : '';
        if (!channelId) { toast('No channel with upload access - connect with Google', 'error'); return; }
        const schedule = document.getElementById('ytUploadSchedule').value;

        const body = {
            title,
            channel_id: channelId,
            description: document.getElementById('ytUploadDesc').value,
            tags: document.getElementById('ytUploadTags').value,
            privacy: document.getElementById('ytUploadPrivacy').value,
            publish_at: schedule ? new Date(schedule).toISOString() : ''
        };

        const btn = document.getElementById('ytPublishBtn');
        const barWrap = document.getElementById('ytUploadBarWrap');
        const bar = document.getElementById('ytUploadBar');
        btn.disabled = true;
        barWrap.classList.remove('hidden');
        bar.style.width = '3%';
        try {
            const planRes = await agentFetch('/api/youtube/upload-plan', { method: 'POST', body: JSON.stringify(body) });
            bar.style.width = '8%';
            const result = await googleUploadVideo(planRes.plan, file, pct => { bar.style.width = (8 + pct * 0.9) + '%'; });
            const videoId = (result && result.id) || '';
            if (planRes.upload_id) {
                try {
                    await agentFetch(`/api/youtube/uploads/${planRes.upload_id}/status`, {
                        method: 'POST', body: JSON.stringify({ status: 'uploaded', video_id: videoId })
                    });
                } catch (e) { /* non fatal */ }
            }
            bar.style.width = '100%';
            toast(videoId ? `Uploaded! https://youtu.be/${videoId}` : 'Upload finished', 'success');
            loadYtVideos(channelId);
        } catch (e) {
            toast(e.message || 'Upload failed', 'error');
        } finally {
            btn.disabled = false;
            setTimeout(() => barWrap.classList.add('hidden'), 2000);
        }
    }

'''

html = html.replace(ANCHOR, JS + ANCHOR, 1)

# navigate(): apply agent handoff after a page renders
old_switch = """                case 'admin': renderAdmin(); break;
            }
        }, 300);"""
new_switch = """                case 'admin': renderAdmin(); break;
            }
            setTimeout(() => applyAgentHandoff(page), 500);
        }, 300);"""
if old_switch not in html:
    raise SystemExit("navigate anchor missing")
html = html.replace(old_switch, new_switch, 1)

path.write_text(html, encoding="utf-8")
print("ok    JS block appended")
print("ok    navigate handoff")
print("bytes:", len(html))
