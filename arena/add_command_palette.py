from pathlib import Path
p=Path('index.html'); s=p.read_text()
# Header controls
old='''                    <button class="text-gray-400 hover:text-white transition" onclick="showNotifications()">
                        <i class="fa-regular fa-bell text-xl"></i>
                    </button>'''
new='''                    <button onclick="openCommandPalette()" class="hidden sm:flex items-center gap-2 text-xs text-gray-300 hover:text-white px-3 py-2 rounded-xl bg-white/5 border border-white/10" title="Command palette (Ctrl/Command + K)">
                        <i class="fa-solid fa-wand-magic-sparkles text-indigo-300"></i><span>Command</span><kbd class="text-[10px] text-gray-500 border border-gray-700 rounded px-1.5 py-0.5">⌘K</kbd>
                    </button>
                    <button onclick="toggleMotionMode()" id="motionToggleBtn" class="text-gray-400 hover:text-white transition w-9 h-9 rounded-xl bg-white/5 border border-white/10" title="Toggle animation performance mode">
                        <i class="fa-solid fa-gauge-high"></i>
                    </button>
                    <button class="text-gray-400 hover:text-white transition" onclick="showNotifications()">
                        <i class="fa-regular fa-bell text-xl"></i>
                    </button>'''
assert old in s;s=s.replace(old,new,1)
# Palette modal after toast container
marker='''    <div id="toastContainer" class="fixed bottom-6 right-6 z-50 flex flex-col gap-2 pointer-events-none"></div>'''
modal=marker+'''

    <!-- Global AI Command Palette -->
    <div id="commandPalette" class="fixed inset-0 z-[100] hidden items-start justify-center px-4 pt-[10vh] md:pt-[14vh]" role="dialog" aria-modal="true" aria-label="BG Labs command palette">
        <button class="absolute inset-0 bg-slate-950/75 backdrop-blur-md cursor-default" onclick="closeCommandPalette()" aria-label="Close command palette"></button>
        <div id="commandShell" class="relative w-full max-w-2xl overflow-hidden rounded-2xl border border-indigo-400/20 bg-slate-950/90 shadow-[0_35px_120px_rgba(0,0,0,.65),0_0_80px_rgba(99,102,241,.12)] command-shell">
            <div class="flex items-center gap-3 px-5 py-4 border-b border-white/10">
                <span class="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20"><i class="fa-solid fa-wand-magic-sparkles"></i></span>
                <input id="commandInput" oninput="filterCommands(this.value)" onkeydown="commandKeydown(event)" class="flex-1 bg-transparent border-0 p-0 text-base text-white placeholder:text-gray-500 focus:shadow-none focus:transform-none" placeholder="Search workspace, or type /yt-script your topic…" autocomplete="off">
                <kbd class="text-[10px] text-gray-500 border border-gray-700 rounded px-2 py-1">ESC</kbd>
            </div>
            <div id="commandHint" class="px-5 py-2 text-[11px] text-gray-500 border-b border-white/5">Navigate instantly · run YouTube skills · manage connected channels</div>
            <div id="commandResults" class="max-h-[52vh] overflow-y-auto custom-scrollbar p-2"></div>
            <div id="commandOutput" class="hidden max-h-[42vh] overflow-auto custom-scrollbar p-4 border-t border-white/10 bg-black/20"></div>
            <div class="flex items-center justify-between px-5 py-3 border-t border-white/10 text-[10px] text-gray-500"><span><kbd>↑↓</kbd> select · <kbd>Enter</kbd> open · <kbd>/</kbd> run skill</span><span class="text-indigo-300">BG LABS Neural Command</span></div>
        </div>
    </div>'''
assert marker in s;s=s.replace(marker,modal,1)
# CSS before reduced motion media marker
css=r'''
        /* Neural command palette */
        .command-shell { transform-style: preserve-3d; animation: commandOpen .28s cubic-bezier(.2,.8,.2,1) both; }
        @keyframes commandOpen { from { opacity:0; transform:perspective(900px) translateY(-16px) rotateX(-5deg) scale(.97); filter:blur(6px); } to { opacity:1; transform:none; filter:none; } }
        .command-item { display:flex; align-items:center; gap:.85rem; width:100%; padding:.72rem .8rem; border:1px solid transparent; border-radius:.75rem; text-align:left; transition:.16s ease; }
        .command-item:hover,.command-item.selected { background:linear-gradient(90deg,rgba(79,70,229,.23),rgba(168,85,247,.08)); border-color:rgba(129,140,248,.2); transform:translateX(3px); }
        .command-icon { width:2rem;height:2rem;border-radius:.65rem;display:flex;align-items:center;justify-content:center;background:rgba(99,102,241,.12);color:#a5b4fc;box-shadow:inset 0 1px rgba(255,255,255,.06); }
        .motion-lite #bg3dCanvas,.motion-lite .neural-aurora { display:none !important; }
        .motion-lite *, .motion-lite *::before,.motion-lite *::after { animation-duration:.01ms !important; animation-iteration-count:1 !important; }
        .motion-lite .tilt-ready,.motion-lite .tilt-ready:hover { transform:none !important; }
'''
style_pos=s.rfind('</style>',0,s.find('<body'))
assert style_pos>0;s=s[:style_pos]+css+s[style_pos:]
# Runtime before Neural 3d section near end
js=r'''
    // ============================================================================
    // GLOBAL AI COMMAND PALETTE
    // ============================================================================
    const workspaceCommands = [
      {id:'dashboard',title:'Command Center',hint:'Workspace overview and recent activity',icon:'fa-layer-group',group:'Navigate',run:()=>navigate('dashboard')},
      {id:'agents',title:'AI Agent Command',hint:'Run specialist agents and Auto Pilot',icon:'fa-robot',group:'Navigate',run:()=>navigate('agents')},
      {id:'youtube',title:'YouTube Automation',hint:'Google channels, publishing and AI Manager',icon:'fa-brands fa-youtube',group:'Navigate',run:()=>navigate('youtube')},
      {id:'manager',title:'Open YouTube AI Manager',hint:'Manage your primary connected channel',icon:'fa-user-gear',group:'Quick action',run:()=>{navigate('youtube');setTimeout(()=>openYtManager(''),700)}},
      {id:'skills',title:'Skills & Research',hint:'11 YouTube skills and sourced web research',icon:'fa-terminal',group:'Navigate',run:()=>navigate('skills')},
      {id:'vimax',title:'ViMax 3D Video Studio',hint:'Idea or script to storyboard and video',icon:'fa-film',group:'Navigate',run:()=>navigate('vimax')},
      {id:'models',title:'Models & Providers',hint:'72 model routes, API keys and GPU servers',icon:'fa-cubes',group:'Navigate',run:()=>navigate('models')},
      {id:'studio',title:'AI Voice Studio',hint:'Neural text to speech and voice controls',icon:'fa-microphone',group:'Create',run:()=>navigate('studio')},
      {id:'image',title:'Visual Intelligence',hint:'Generate and manage AI images',icon:'fa-image',group:'Create',run:()=>navigate('image')},
      {id:'script',title:'AI Script Lab',hint:'Write structured scripts and exports',icon:'fa-file-lines',group:'Create',run:()=>navigate('script')},
      {id:'avatar',title:'Avatar Studio',hint:'Talking avatar and presentation workflows',icon:'fa-user-astronaut',group:'Create',run:()=>navigate('avatar')},
      {id:'voices',title:'Neural Voice Library',hint:'Browse built-in and cloned voices',icon:'fa-volume-high',group:'Create',run:()=>navigate('voices')},
      {id:'connect',title:'Continue with Google',hint:'Connect one or more YouTube channels',icon:'fa-brands fa-google',group:'Quick action',run:()=>{navigate('youtube');setTimeout(connectGoogle,650)}},
      {id:'yt-script',title:'Run /yt-script',hint:'Generate five scored hooks and a retention script',icon:'fa-bolt',group:'Skill',fill:'/yt-script '},
      {id:'yt-audit',title:'Run /yt-audit',hint:'Audit channel positioning and packaging',icon:'fa-magnifying-glass-chart',group:'Skill',fill:'/yt-audit '},
      {id:'yt-package',title:'Run /yt-package',hint:'Titles and thumbnail packaging as one unit',icon:'fa-box-open',group:'Skill',fill:'/yt-package '},
      {id:'motion',title:'Toggle Performance Mode',hint:'Pause or resume 3D motion effects',icon:'fa-gauge-high',group:'Settings',run:toggleMotionMode}
    ];
    let commandMatches=[], commandSelected=0;
    function openCommandPalette(initial='') { const p=document.getElementById('commandPalette'),input=document.getElementById('commandInput');p.classList.remove('hidden');p.classList.add('flex');document.body.dataset.palette='open';document.getElementById('commandOutput').classList.add('hidden');input.value=initial;filterCommands(initial);setTimeout(()=>input.focus(),40); }
    function closeCommandPalette(){const p=document.getElementById('commandPalette');p.classList.add('hidden');p.classList.remove('flex');delete document.body.dataset.palette;}
    function commandRecent(){try{return JSON.parse(localStorage.getItem('bglabs_recent_commands')||'[]')}catch(_){return[]}}
    function rememberCommand(id){const r=[id,...commandRecent().filter(x=>x!==id)].slice(0,5);localStorage.setItem('bglabs_recent_commands',JSON.stringify(r));}
    function filterCommands(query='') { const q=query.trim().toLowerCase(),box=document.getElementById('commandResults'),hint=document.getElementById('commandHint');commandSelected=0;if(q.startsWith('/')){commandMatches=[{id:'execute-skill',title:`Execute ${query}`,hint:'Run this slash command through the installed Skills engine',icon:'fa-terminal',group:'Skill',execute:query}];hint.textContent='Press Enter to execute the slash command';}else{const recent=commandRecent();commandMatches=workspaceCommands.filter(c=>!q||`${c.title} ${c.hint} ${c.group} ${c.id}`.toLowerCase().includes(q)).sort((a,b)=>(recent.indexOf(a.id)<0?99:recent.indexOf(a.id))-(recent.indexOf(b.id)<0?99:recent.indexOf(b.id)));hint.textContent=q?`${commandMatches.length} matching commands`:'Navigate instantly · run YouTube skills · manage connected channels';}box.innerHTML=commandMatches.length?commandMatches.map((c,i)=>`<button class="command-item ${i===0?'selected':''}" onmouseenter="selectCommand(${i})" onclick="runCommand(${i})"><span class="command-icon"><i class="fa-solid ${c.icon}"></i></span><span class="min-w-0 flex-1"><span class="block text-sm font-medium text-white truncate">${esc3(c.title)}</span><span class="block text-[11px] text-gray-500 truncate">${esc3(c.hint)}</span></span><span class="text-[10px] text-indigo-300/70">${esc3(c.group)}</span></button>`).join(''):'<div class="p-8 text-center text-sm text-gray-500">No matching command</div>'; }
    function selectCommand(i){commandSelected=i;document.querySelectorAll('.command-item').forEach((e,n)=>e.classList.toggle('selected',n===i));}
    function commandKeydown(e){if(e.key==='Escape'){closeCommandPalette();return}if(e.key==='ArrowDown'){e.preventDefault();selectCommand(Math.min(commandMatches.length-1,commandSelected+1));document.querySelectorAll('.command-item')[commandSelected]?.scrollIntoView({block:'nearest'});}else if(e.key==='ArrowUp'){e.preventDefault();selectCommand(Math.max(0,commandSelected-1));document.querySelectorAll('.command-item')[commandSelected]?.scrollIntoView({block:'nearest'});}else if(e.key==='Enter'){e.preventDefault();runCommand(commandSelected);}}
    async function runCommand(i){const c=commandMatches[i];if(!c)return;if(c.fill){document.getElementById('commandInput').value=c.fill;filterCommands(c.fill);return}if(c.execute){const out=document.getElementById('commandOutput');out.classList.remove('hidden');out.innerHTML='<div class="loader mx-auto"></div>';try{const d=await aiRequest('/api/skills/command','POST',{command:c.execute});out.innerHTML=`<div class="flex justify-between mb-2"><b class="text-sm text-white">Skill result</b><button onclick="document.getElementById('commandOutput').classList.add('hidden')" class="text-xs text-gray-500">Close</button></div><pre class="text-xs text-emerald-200 whitespace-pre-wrap">${esc3(JSON.stringify(d,null,2))}</pre>`;rememberCommand(c.id);}catch(e){out.innerHTML=`<p class="text-sm text-red-400">${esc3(e.message)}</p>`;}return}rememberCommand(c.id);closeCommandPalette();c.run?.();}
    function toggleMotionMode(){const lite=!document.documentElement.classList.contains('motion-lite');document.documentElement.classList.toggle('motion-lite',lite);localStorage.setItem('bglabs_motion_lite',lite?'1':'0');const icon=document.querySelector('#motionToggleBtn i');if(icon)icon.className=`fa-solid ${lite?'fa-play':'fa-gauge-high'}`;toast(lite?'Performance mode: motion paused':'Neural motion resumed','info');}
    document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();document.body.dataset.palette==='open'?closeCommandPalette():openCommandPalette();}else if(e.key==='Escape'&&document.body.dataset.palette==='open')closeCommandPalette();});
    document.addEventListener('DOMContentLoaded',()=>{if(localStorage.getItem('bglabs_motion_lite')==='1'){document.documentElement.classList.add('motion-lite');const icon=document.querySelector('#motionToggleBtn i');if(icon)icon.className='fa-solid fa-play';}});
'''
insert=s.rfind('    // ============================================================================\n    // NEURAL 3D UI RUNTIME')
assert insert>0;s=s[:insert]+js+'\n'+s[insert:]
p.write_text(s)
print('command palette added',len(s))
