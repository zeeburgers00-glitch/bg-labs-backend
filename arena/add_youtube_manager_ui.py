from pathlib import Path
p=Path('index.html'); s=p.read_text()
marker='''                <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
                    <div class="lg:col-span-2 space-y-6">
                        <div id="ytFullPanel"'''
panel='''                <!-- AI Channel Manager -->
                <div id="ytAiManagerPanel" class="hidden glass-panel p-6 rounded-xl mb-8 border border-purple-500/30">
                    <div class="flex flex-wrap items-start justify-between gap-4">
                        <div class="flex items-center gap-3"><span class="w-9 h-9 rounded-xl bg-purple-500/15 text-purple-300 flex items-center justify-center"><i class="fa-solid fa-robot"></i></span><div><h3 class="text-lg font-semibold text-white">AI Channel Manager</h3><p id="ytManagerChannel" class="text-xs text-gray-400">Select a connected channel</p></div></div>
                        <div class="flex items-center gap-2"><span class="text-[11px] px-2 py-1 rounded-full bg-amber-500/15 text-amber-200">APPROVAL REQUIRED</span><button onclick="document.getElementById('ytAiManagerPanel').classList.add('hidden')" class="text-gray-400 px-2">✕</button></div>
                    </div>
                    <div class="grid md:grid-cols-2 xl:grid-cols-4 gap-3 mt-5">
                        <label class="p-3 rounded-xl bg-gray-900/50 border border-gray-700 flex items-center gap-3"><input id="ytManagerEnabled" type="checkbox" class="w-4 h-4"><span class="text-sm">Enable manager</span></label>
                        <select id="ytManagerTone" class="bg-gray-900/60 border border-gray-700 rounded-xl p-3 text-sm"><option value="friendly">Friendly voice</option><option value="professional">Professional voice</option><option value="playful">Playful voice</option></select>
                        <input id="ytManagerFrequency" class="bg-gray-900/60 border border-gray-700 rounded-xl p-3 text-sm" placeholder="2 videos per week">
                        <input id="ytManagerLanguage" class="bg-gray-900/60 border border-gray-700 rounded-xl p-3 text-sm" placeholder="English / Urdu">
                    </div>
                    <div class="grid md:grid-cols-2 gap-3 mt-3"><input id="ytManagerGoal" class="bg-gray-900/60 border border-gray-700 rounded-xl p-3 text-sm" placeholder="Channel goal"><input id="ytManagerAudience" class="bg-gray-900/60 border border-gray-700 rounded-xl p-3 text-sm" placeholder="Target audience"></div>
                    <div class="flex flex-wrap items-center gap-4 mt-4 text-xs text-gray-300">
                        <label><input id="ytMgrAnalytics" type="checkbox" checked class="mr-1"> Analytics audit</label><label><input id="ytMgrPlan" type="checkbox" checked class="mr-1"> Content plan</label><label><input id="ytMgrComments" type="checkbox" checked class="mr-1"> Comment drafts</label><label><input id="ytMgrMetadata" type="checkbox" checked class="mr-1"> Metadata drafts</label><label class="text-purple-300"><input id="ytMgrPackage" type="checkbox" class="mr-1"> Build full next-video package</label>
                    </div>
                    <div class="flex flex-wrap gap-3 mt-5"><button onclick="saveYtManager()" id="ytManagerSaveBtn" class="px-5 py-2.5 rounded-xl bg-gray-700 hover:bg-gray-600 font-medium text-sm"><i class="fa-solid fa-floppy-disk mr-2"></i>Save settings</button><button onclick="runYtManager()" id="ytManagerRunBtn" class="px-5 py-2.5 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 font-semibold text-sm"><i class="fa-solid fa-wand-magic-sparkles mr-2"></i>Run AI Manager now</button></div>
                    <p class="text-xs text-gray-500 mt-3"><i class="fa-solid fa-shield-halved mr-1 text-emerald-400"></i>Agent analytics, ideas aur reply drafts banata hai. Koi public reply/upload aapki approval ke baghair post nahi hota.</p>
                    <div id="ytManagerResult" class="mt-5"></div>
                </div>

'''
assert marker in s
s=s.replace(marker,panel+marker,1)
# Add channel-card control.
old='''                    <button onclick="showChannelAnalytics('${agentEsc(ch.channel_id)}')" class="text-[11px] bg-gray-700 hover:bg-gray-600 px-2.5 py-1.5 rounded-lg text-white"><i class="fa-solid fa-chart-line mr-1"></i>AI analytics</button>'''
new=old+'''\n                    <button onclick="openYtManager('${agentEsc(ch.channel_id)}')" class="text-[11px] bg-purple-500/15 hover:bg-purple-500/25 px-2.5 py-1.5 rounded-lg text-purple-200"><i class="fa-solid fa-robot mr-1"></i>AI Manager</button>'''
assert old in s
s=s.replace(old,new,1)
# Add state after YouTube globals.
old_state="""    let ytCanReply = false;"""
new_state="""    let ytCanReply = false;
    let ytManagerChannelId = '';"""
assert old_state in s
s=s.replace(old_state,new_state,1)
# Add functions before connectGoogle.
func_marker='''    async function connectGoogle() {'''
functions=r'''    async function openYtManager(channelId) {
        ytManagerChannelId = channelId || ((ytChannels.find(c => c.is_primary) || ytChannels[0] || {}).channel_id || '');
        if (!ytManagerChannelId) return toast('Connect a channel first', 'error');
        const panel=document.getElementById('ytAiManagerPanel'), result=document.getElementById('ytManagerResult');
        panel?.classList.remove('hidden'); if(result) result.innerHTML='<div class="loader"></div>'; panel?.scrollIntoView({behavior:'smooth',block:'start'});
        try {
            const d=await agentFetch(`/api/youtube/manager/status?channel_id=${encodeURIComponent(ytManagerChannelId)}`), m=d.manager||{};
            document.getElementById('ytManagerChannel').textContent=`Managing: ${(d.channel||{}).title||ytManagerChannelId}`;
            document.getElementById('ytManagerEnabled').checked=!!m.enabled;
            document.getElementById('ytManagerTone').value=m.tone||'friendly';
            document.getElementById('ytManagerFrequency').value=m.content_frequency||'2 videos per week';
            document.getElementById('ytManagerLanguage').value=m.language||'English';
            document.getElementById('ytManagerGoal').value=m.goal||'grow watch time and subscribers';
            document.getElementById('ytManagerAudience').value=m.audience||'';
            const pm=m.permissions||{}; document.getElementById('ytMgrAnalytics').checked=pm.analytics!==false; document.getElementById('ytMgrPlan').checked=pm.content_plan!==false; document.getElementById('ytMgrComments').checked=pm.comment_drafts!==false; document.getElementById('ytMgrMetadata').checked=pm.metadata_drafts!==false;
            result.innerHTML=`<div class="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-sm text-emerald-200"><i class="fa-solid fa-shield-halved mr-2"></i>${agentEsc(d.safety||'Approval required')} ${m.last_run?`<span class="text-gray-400 ml-2">Last run: ${agentEsc(m.last_run)}</span>`:''}</div>`;
        } catch(e) { result.innerHTML=`<p class="text-red-400">${agentEsc(e.message)}</p>`; }
    }
    function ytManagerPayload() { return {channel_id:ytManagerChannelId,enabled:document.getElementById('ytManagerEnabled').checked,tone:document.getElementById('ytManagerTone').value,content_frequency:document.getElementById('ytManagerFrequency').value,language:document.getElementById('ytManagerLanguage').value,goal:document.getElementById('ytManagerGoal').value,audience:document.getElementById('ytManagerAudience').value,permissions:{analytics:document.getElementById('ytMgrAnalytics').checked,content_plan:document.getElementById('ytMgrPlan').checked,comment_drafts:document.getElementById('ytMgrComments').checked,metadata_drafts:document.getElementById('ytMgrMetadata').checked}}; }
    async function saveYtManager() { const b=document.getElementById('ytManagerSaveBtn'); b.disabled=true; try{const d=await agentFetch('/api/youtube/manager/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(ytManagerPayload())});toast('AI Manager settings saved','success');document.getElementById('ytManagerEnabled').checked=d.manager.enabled;}catch(e){toast(e.message,'error');}finally{b.disabled=false;} }
    async function runYtManager() {
        const b=document.getElementById('ytManagerRunBtn'), out=document.getElementById('ytManagerResult'); b.disabled=true;b.innerHTML='<i class="fa-solid fa-circle-notch fa-spin mr-2"></i>Agents analyzing channel…';out.innerHTML='<div class="loader"></div>';
        try { await agentFetch('/api/youtube/manager/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...ytManagerPayload(),enabled:true})}); const d=await agentFetch('/api/youtube/manager/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel_id:ytManagerChannelId,run_once:true,build_package:document.getElementById('ytMgrPackage').checked})}); const ideas=(((d.strategy||{}).result||{}).ideas||[]), replies=(((d.community||{}).result||{}).replies||[]), insight=((d.analytics||{}).result||{}); out.innerHTML=`<div class="grid md:grid-cols-3 gap-3"><div class="p-3 rounded-xl bg-indigo-500/10 border border-indigo-500/20"><div class="text-xs text-indigo-300">VIDEO IDEAS</div><div class="text-2xl font-bold mt-1">${ideas.length}</div></div><div class="p-3 rounded-xl bg-purple-500/10 border border-purple-500/20"><div class="text-xs text-purple-300">REPLY DRAFTS</div><div class="text-2xl font-bold mt-1">${replies.length}</div></div><div class="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20"><div class="text-xs text-emerald-300">PUBLIC ACTIONS</div><div class="text-2xl font-bold mt-1">0</div></div></div><details open class="mt-4"><summary class="cursor-pointer text-sm font-semibold text-white">AI management report</summary><pre class="mt-3 p-4 rounded-xl bg-black/30 border border-gray-700 text-xs text-emerald-200 overflow-auto max-h-[600px] whitespace-pre-wrap">${agentEsc(JSON.stringify(d,null,2))}</pre></details>`; toast('Channel AI report ready for approval','success');
        } catch(e) { out.innerHTML=`<p class="text-red-400">${agentEsc(e.message)}</p>`; } finally {b.disabled=false;b.innerHTML='<i class="fa-solid fa-wand-magic-sparkles mr-2"></i>Run AI Manager now';}
    }

'''
assert func_marker in s
s=s.replace(func_marker,functions+func_marker,1)
p.write_text(s)
print('YouTube manager UI patched',len(s))
