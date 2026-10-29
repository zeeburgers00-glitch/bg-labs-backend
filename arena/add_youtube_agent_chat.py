from pathlib import Path
p=Path('index.html');s=p.read_text()
css=r'''
.chat-mode{display:flex;gap:7px;align-items:center}.chat-mode .select{width:auto;min-width:155px}.yt-agent-badge{display:inline-flex;align-items:center;gap:6px;color:#ff8c8c}.yt-connect-mini{padding:7px 10px}.oauth-check{margin-top:14px}.oauth-check code{display:block;margin-top:7px;padding:8px;background:#060914;border-radius:8px;color:#8ee7ff;word-break:break-all}.oauth-ok{background:#123d2f80!important;color:#77e4b6!important;border-color:#2ebc8755!important}@media(max-width:760px){.chat-head{align-items:flex-start;gap:10px}.chat-head>.row{width:100%}.chat-mode{width:100%}.chat-mode .select{min-width:0;flex:1}.chat-head{flex-direction:column}.model-pill{max-width:none;flex:1}}
'''
s=s.replace('</style>',css+'</style>')
old='<div class="row"><select id="chatModel" class="select model-pill"><option value="">Best available model</option></select><button class="btn secondary" id="clearChat">Clear</button></div>'
new='<div class="row"><div class="chat-mode"><select id="chatMode" class="select"><option value="general">◈ General AI</option><option value="youtube">▶ YouTube Agent</option></select><select id="chatChannel" class="select hidden"><option value="">No channel connected</option></select></div><select id="chatModel" class="select model-pill"><option value="">Best available model</option></select><button class="btn secondary" id="clearChat">Clear</button></div>'
if old not in s: raise SystemExit('chat header missing')
s=s.replace(old,new)
old2='<div id="ytChannels" class="list"><div class="empty">Loading channels…</div></div></div><form class="card" id="ytManagerForm">'
new2='<div id="ytOAuthNotice" class="notice info oauth-check hidden"></div><div id="ytChannels" class="list"><div class="empty">Loading channels…</div></div></div><form class="card" id="ytManagerForm">'
if old2 not in s: raise SystemExit('youtube panel missing')
s=s.replace(old2,new2)
# load page youtube chat status too
s=s.replace("if(name==='chat')await loadChatModels();","if(name==='chat'){await loadChatModels();await loadYouTubeChatStatus();}")
# Add status function before loadYouTube
needle='async function loadYouTube()'
fn=r'''async function loadYouTubeChatStatus(){try{const d=await api('/api/youtube/agent/status');const channels=d.channels||[];$('#chatChannel').innerHTML=channels.length?channels.map(c=>`<option value="${esc(c.channel_id)}">${esc(c.title)}</option>`).join(''):'<option value="">No channel connected</option>';state.youtubeAgentStatus=d;updateChatMode()}catch(e){state.youtubeAgentStatus={connected:false};updateChatMode()}}
function updateChatMode(){const yt=$('#chatMode').value==='youtube';$('#chatChannel').classList.toggle('hidden',!yt);$('#chatModel').classList.toggle('hidden',yt);const status=$('.chat-status');if(yt){const connected=state.youtubeAgentStatus?.connected;status.innerHTML=`<span class="dot ${connected?'ok':''}"></span><span class="yt-agent-badge">YouTube Agent</span> · ${connected?'using connected channel':'general mode — connect a channel for live data'}`;$('#chatInput').placeholder='Ask your YouTube Agent about strategy, scripts, SEO, analytics or comments…'}else{status.innerHTML='<span class="dot ok"></span> Connected to your AI model router';$('#chatInput').placeholder='Message BG LABS AI…'}}
'''
s=s.replace(needle,fn+needle)
# Replace loadYouTube prefix to include oauth status
old3="async function loadYouTube(){const d=await api('/api/youtube/channels');state.channels=d.channels||[];"
new3="async function loadYouTube(){const auth=await api('/api/youtube/auth/status');state.youtubeAuth=auth;const notice=$('#ytOAuthNotice');if(auth.oauth_configured){notice.className='notice oauth-check oauth-ok';notice.innerHTML=`✓ Google OAuth is configured.<code>Callback: ${esc(auth.redirect_uri)}</code>`;$('#connectGoogle').disabled=false}else{notice.className='notice oauth-check';notice.innerHTML=`Google login needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in Vercel.<code>Authorized redirect URI: ${esc(auth.redirect_uri)}</code>`;$('#connectGoogle').disabled=true}notice.classList.remove('hidden');const d=await api('/api/youtube/channels');state.channels=d.channels||[];"
if old3 not in s: raise SystemExit('load youtube missing')
s=s.replace(old3,new3)
# Replace sendChat API selection
old4="const d=await api('/api/generate/chat',{method:'POST',body:JSON.stringify({model:$('#chatModel').value,messages:state.chat,prompt:text})});const answer=chatText(d);"
new4="const youtubeMode=$('#chatMode').value==='youtube';const endpoint=youtubeMode?'/api/youtube/agent/chat':'/api/generate/chat';const payload=youtubeMode?{message:text,messages:state.chat,channel_id:$('#chatChannel').value}:{model:$('#chatModel').value,messages:state.chat,prompt:text};const d=await api(endpoint,{method:'POST',body:JSON.stringify(payload)});const answer=youtubeMode?(d.reply||chatText(d)):chatText(d);"
if old4 not in s: raise SystemExit('sendChat target missing')
s=s.replace(old4,new4)
# safer connect button and mode event
old5="$('#connectGoogle').onclick=async()=>{try{const d=await api('/api/youtube/auth/url');location.href=d.url}catch(e){toast(e.message,true)}};$('#ytChannel').onchange=loadManagerSettings;"
new5="$('#connectGoogle').onclick=async()=>{try{if(state.youtubeAuth&&!state.youtubeAuth.oauth_configured)throw new Error('Google OAuth credentials are not configured yet. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in Vercel.');const d=await api('/api/youtube/auth/url');location.href=d.url}catch(e){toast(e.message,true)}};$('#ytChannel').onchange=loadManagerSettings;$('#chatMode').onchange=updateChatMode;"
if old5 not in s: raise SystemExit('connect target missing')
s=s.replace(old5,new5)
# callback toast in boot
old6="async function boot(){try{const h=await api('/health');"
new6="async function boot(){const qp=new URLSearchParams(location.search);if(qp.get('yt')==='error')setTimeout(()=>toast('Google connection failed: '+(qp.get('detail')||qp.get('reason')||'unknown error'),true),500);if(qp.get('yt')==='connected')setTimeout(()=>toast('YouTube channel connected successfully'),500);try{const h=await api('/health');"
if old6 not in s: raise SystemExit('boot target missing')
s=s.replace(old6,new6)
p.write_text(s)
print('youtube agent chat UI added')
