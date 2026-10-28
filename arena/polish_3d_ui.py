from pathlib import Path
p=Path('index.html')
s=p.read_text(encoding='utf-8')
css=r'''
        /* ================================================================
           BG LABS NEURAL 3D DESIGN SYSTEM
           GPU-friendly transforms, canvas depth and reduced-motion support.
           ================================================================ */
        :root {
            --mx: 50vw; --my: 30vh;
            --neon-a: #818cf8; --neon-b: #c084fc; --neon-c: #22d3ee;
            --panel: rgba(8, 12, 28, .64); --line: rgba(148, 163, 255, .16);
        }
        html { background: #030712; }
        body { background: radial-gradient(circle at 50% -20%, #172554 0, #070b18 42%, #02040b 100%) !important; overflow: hidden; }
        body::before {
            content: ''; position: fixed; inset: 0; z-index: -3; pointer-events: none;
            background-image: linear-gradient(rgba(99,102,241,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(99,102,241,.045) 1px, transparent 1px);
            background-size: 54px 54px; mask-image: linear-gradient(to bottom, black, transparent 82%);
            transform: perspective(700px) rotateX(61deg) scale(1.65) translateY(28%); transform-origin: bottom;
            animation: neuralGrid 18s linear infinite;
        }
        @keyframes neuralGrid { to { background-position: 0 54px, 54px 0; } }
        #bg3dCanvas { position: fixed; inset: 0; width: 100%; height: 100%; z-index: -4; pointer-events: none; opacity: .82; }
        .neural-aurora { position: fixed; inset: 0; z-index: -2; overflow: hidden; pointer-events: none; filter: blur(4px); }
        .neural-orb { position: absolute; border-radius: 999px; opacity: .22; filter: blur(70px); will-change: transform; mix-blend-mode: screen; }
        .neural-orb:nth-child(1) { width: 42vw; height: 42vw; left: -12vw; top: -20vw; background: #4f46e5; animation: orbA 16s ease-in-out infinite alternate; }
        .neural-orb:nth-child(2) { width: 34vw; height: 34vw; right: -8vw; top: 12vh; background: #9333ea; animation: orbB 19s ease-in-out infinite alternate; }
        .neural-orb:nth-child(3) { width: 30vw; height: 30vw; left: 34vw; bottom: -20vw; background: #0891b2; animation: orbC 14s ease-in-out infinite alternate; }
        @keyframes orbA { to { transform: translate3d(25vw, 18vh, 0) scale(1.18); } }
        @keyframes orbB { to { transform: translate3d(-24vw, 24vh, 0) scale(.8); } }
        @keyframes orbC { to { transform: translate3d(12vw, -30vh, 0) scale(1.25); } }
        .mouse-glow { position: fixed; inset: 0; z-index: -1; pointer-events: none; background: radial-gradient(500px circle at var(--mx) var(--my), rgba(99,102,241,.11), transparent 64%); }

        .glass { background: rgba(5, 9, 23, .73) !important; border-color: rgba(129,140,248,.13) !important; backdrop-filter: blur(22px) saturate(145%) !important; box-shadow: 0 24px 80px rgba(0,0,0,.23); }
        .glass-panel {
            position: relative; background: linear-gradient(145deg, rgba(18,25,52,.74), rgba(5,8,20,.7)) !important;
            border: 1px solid var(--line) !important; backdrop-filter: blur(20px) saturate(145%) !important;
            box-shadow: 0 22px 70px rgba(0,0,0,.32), inset 0 1px 0 rgba(255,255,255,.055);
            transform-style: preserve-3d; isolation: isolate;
        }
        .glass-panel::before { content: ''; position: absolute; inset: 0; border-radius: inherit; pointer-events: none; z-index: -1; background: radial-gradient(420px circle at var(--card-x,50%) var(--card-y,0%), rgba(129,140,248,.14), transparent 55%); opacity: 0; transition: opacity .25s; }
        .glass-panel:hover::before { opacity: 1; }
        .tilt-ready { transition: transform .2s ease, border-color .25s, box-shadow .25s !important; will-change: transform; }
        .tilt-ready:hover { border-color: rgba(129,140,248,.42) !important; box-shadow: 0 30px 90px rgba(0,0,0,.42), 0 0 34px rgba(99,102,241,.09), inset 0 1px 0 rgba(255,255,255,.08); }
        .tilt-ready > * { transform: translateZ(10px); }

        aside { box-shadow: 24px 0 70px rgba(0,0,0,.28); }
        aside > div:first-child > div > div:first-child { box-shadow: 0 0 28px rgba(129,140,248,.45); animation: logoFloat 4s ease-in-out infinite; transform-style: preserve-3d; }
        @keyframes logoFloat { 0%,100% { transform: translateY(0) rotateY(-8deg); } 50% { transform: translateY(-4px) rotateY(10deg); } }
        .sidebar-item { position: relative; overflow: hidden; border: 1px solid transparent; transition: transform .24s ease, color .24s, background .24s, border-color .24s !important; }
        .sidebar-item::before { content:''; position:absolute; inset:0; background: linear-gradient(90deg, transparent, rgba(129,140,248,.1), transparent); transform: translateX(-110%); transition: transform .5s; }
        .sidebar-item:hover::before { transform: translateX(110%); }
        .sidebar-item:hover { transform: translateX(5px) translateZ(12px); border-color: rgba(129,140,248,.18); }
        .sidebar-item i { transition: transform .3s, filter .3s; }
        .sidebar-item:hover i { transform: translateZ(15px) rotate(-6deg) scale(1.13); filter: drop-shadow(0 0 8px rgba(129,140,248,.6)); }
        .sidebar-item.active { background: linear-gradient(90deg, rgba(79,70,229,.25), rgba(168,85,247,.08)) !important; box-shadow: inset -3px 0 var(--neon-a), 0 8px 24px rgba(49,46,129,.15); border-right: 0 !important; }

        header { background: linear-gradient(90deg, rgba(5,9,23,.76), rgba(14,10,35,.64)) !important; backdrop-filter: blur(24px) saturate(145%) !important; }
        #pageTitle { background: linear-gradient(90deg,#fff,#c7d2fe 45%,#67e8f9); -webkit-background-clip:text; background-clip:text; color:transparent; filter: drop-shadow(0 0 18px rgba(129,140,248,.18)); }
        #contentArea { perspective: 1400px; transform-style: preserve-3d; }
        #contentArea > * { transform-origin: 50% 20%; }
        .page-enter { animation: pagePortal .52s cubic-bezier(.2,.75,.25,1) both; }
        @keyframes pagePortal { from { opacity:0; transform: translate3d(0,18px,-45px) rotateX(2deg) scale(.985); filter:blur(7px); } to { opacity:1; transform:none; filter:none; } }

        button:not(:disabled), a.rounded-lg, a.rounded-xl { position: relative; overflow: hidden; transform-style: preserve-3d; transition: transform .22s ease, box-shadow .22s ease, filter .22s ease !important; }
        button:not(:disabled)::after { content:''; position:absolute; top:-120%; left:-40%; width:35%; height:340%; background:linear-gradient(90deg,transparent,rgba(255,255,255,.25),transparent); transform:rotate(28deg) translateX(-250%); transition: transform .65s ease; pointer-events:none; }
        button:not(:disabled):hover::after { transform:rotate(28deg) translateX(600%); }
        button:not(:disabled):hover { transform: translateY(-2px) translateZ(8px); box-shadow: 0 12px 35px rgba(79,70,229,.23); filter: brightness(1.09); }
        button:not(:disabled):active { transform: translateY(1px) scale(.98); }
        input, textarea, select { background-color: rgba(2,6,23,.62) !important; transition: border-color .2s, box-shadow .2s, transform .2s !important; }
        input:focus, textarea:focus, select:focus { outline: none !important; border-color: rgba(129,140,248,.72) !important; box-shadow: 0 0 0 3px rgba(99,102,241,.12), 0 8px 30px rgba(49,46,129,.14); transform: translateY(-1px); }
        .loader { border-color: rgba(255,255,255,.12) !important; border-top-color: #818cf8 !important; box-shadow: 0 0 20px rgba(129,140,248,.4); }
        .pulse-dot { box-shadow: 0 0 0 0 rgba(34,197,94,.7); animation: onlinePulse 2s infinite !important; }
        @keyframes onlinePulse { 0% { box-shadow:0 0 0 0 rgba(34,197,94,.55); } 70% { box-shadow:0 0 0 8px rgba(34,197,94,0); } 100% { box-shadow:0 0 0 0 rgba(34,197,94,0); } }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: linear-gradient(#6366f1,#a855f7) !important; }
        ::selection { background: rgba(99,102,241,.65); color:#fff; }

        @media (max-width: 768px) {
            .neural-orb { filter: blur(48px); opacity:.16; }
            body::before { background-size: 38px 38px; }
            .tilt-ready, .tilt-ready:hover { transform: none !important; }
        }
        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; }
            #bg3dCanvas, .neural-aurora { display:none; }
            .tilt-ready, .tilt-ready:hover { transform:none !important; }
        }
'''
assert '</style>' in s
s=s.replace('    </style>',css+'    </style>',1)
body='''<body class="bg-gray-900 text-white min-h-screen selection:bg-indigo-500">'''
scene='''<body class="bg-gray-900 text-white min-h-screen selection:bg-indigo-500">
    <canvas id="bg3dCanvas" aria-hidden="true"></canvas>
    <div class="neural-aurora" aria-hidden="true"><span class="neural-orb"></span><span class="neural-orb"></span><span class="neural-orb"></span></div>
    <div class="mouse-glow" aria-hidden="true"></div>'''
assert body in s
s=s.replace(body,scene,1)
js=r'''
    // ============================================================================
    // NEURAL 3D UI RUNTIME
    // ============================================================================
    function initNeural3D() {
        const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
        document.addEventListener('pointermove', e => {
            document.documentElement.style.setProperty('--mx', e.clientX + 'px');
            document.documentElement.style.setProperty('--my', e.clientY + 'px');
        }, {passive:true});

        const decorate = root => {
            if (!root?.querySelectorAll) return;
            root.querySelectorAll('.glass-panel').forEach(card => setupTilt(card, reduced));
            root.querySelectorAll('button').forEach(btn => btn.classList.add('premium-shine'));
            [...root.children].forEach(child => child.classList?.add('page-enter'));
        };
        const content = document.getElementById('contentArea');
        decorate(document);
        if (content) new MutationObserver(mutations => mutations.forEach(m => m.addedNodes.forEach(n => {
            if (n.nodeType === 1) { setupTilt(n.matches?.('.glass-panel') ? n : null, reduced); decorate(n); }
        }))).observe(content, {childList:true, subtree:true});
        if (!reduced) startNeuralCanvas();
    }

    function setupTilt(card, reduced=false) {
        if (!card || card.dataset.tiltReady || reduced) return;
        card.dataset.tiltReady = '1'; card.classList.add('tilt-ready');
        card.addEventListener('pointermove', e => {
            if (innerWidth < 769) return;
            const r=card.getBoundingClientRect(), x=(e.clientX-r.left)/r.width, y=(e.clientY-r.top)/r.height;
            const strength = r.width > 850 ? 1.5 : r.width > 520 ? 2.7 : 4.2;
            card.style.setProperty('--card-x',(x*100)+'%'); card.style.setProperty('--card-y',(y*100)+'%');
            card.style.transform=`perspective(1100px) rotateX(${(0.5-y)*strength}deg) rotateY(${(x-0.5)*strength}deg) translateY(-2px)`;
        }, {passive:true});
        card.addEventListener('pointerleave', () => { card.style.transform=''; });
    }

    function startNeuralCanvas() {
        const canvas=document.getElementById('bg3dCanvas'); if(!canvas) return;
        const ctx=canvas.getContext('2d',{alpha:true}); let w=0,h=0,dpr=1,raf=0;
        const pointer={x:0,y:0};
        const count=innerWidth<700?36:76;
        const stars=Array.from({length:count},(_,i)=>({
            x:(Math.random()-.5)*1800, y:(Math.random()-.5)*1100,
            z:Math.random()*1500+80, pz:0, size:Math.random()*1.5+.45,
            hue:i%3===0?188:i%3===1?235:275
        }));
        function resize(){ dpr=Math.min(devicePixelRatio||1,1.5); w=innerWidth;h=innerHeight;canvas.width=w*dpr;canvas.height=h*dpr;canvas.style.width=w+'px';canvas.style.height=h+'px';ctx.setTransform(dpr,0,0,dpr,0,0); }
        function reset(s){s.x=(Math.random()-.5)*1800;s.y=(Math.random()-.5)*1100;s.z=1500;s.pz=s.z;}
        function frame(t){
            ctx.clearRect(0,0,w,h); const cx=w/2+pointer.x*22,cy=h/2+pointer.y*16;
            const projected=[];
            for(const s of stars){
                s.pz=s.z;s.z-=1.15;if(s.z<35)reset(s);
                const scale=480/s.z, x=cx+s.x*scale,y=cy+s.y*scale;
                if(x<-80||x>w+80||y<-80||y>h+80){reset(s);continue;}
                const alpha=Math.min(.72,(1-s.z/1600)*.74+.06),radius=s.size*scale*1.6;
                projected.push({x,y,z:s.z,hue:s.hue});
                ctx.beginPath();ctx.arc(x,y,Math.max(.45,radius),0,Math.PI*2);
                ctx.fillStyle=`hsla(${s.hue},90%,72%,${alpha})`;ctx.shadowBlur=radius*8;ctx.shadowColor=`hsla(${s.hue},90%,65%,.45)`;ctx.fill();ctx.shadowBlur=0;
            }
            // nearby projected nodes form a subtle neural constellation
            for(let i=0;i<projected.length;i++) for(let j=i+1;j<Math.min(projected.length,i+8);j++){
                const a=projected[i],b=projected[j],dx=a.x-b.x,dy=a.y-b.y,d=Math.hypot(dx,dy);
                if(d<105 && Math.abs(a.z-b.z)<290){ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.strokeStyle=`rgba(129,140,248,${(1-d/105)*.11})`;ctx.lineWidth=.6;ctx.stroke();}
            }
            raf=requestAnimationFrame(frame);
        }
        addEventListener('resize',resize,{passive:true});
        addEventListener('pointermove',e=>{pointer.x=e.clientX/innerWidth-.5;pointer.y=e.clientY/innerHeight-.5;},{passive:true});
        document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelAnimationFrame(raf);}else{raf=requestAnimationFrame(frame);}});
        resize();raf=requestAnimationFrame(frame);
    }
    document.addEventListener('DOMContentLoaded', initNeural3D);
'''
pos=s.rfind('</script>')
assert pos>0
s=s[:pos]+js+'\n    '+s[pos:]
p.write_text(s,encoding='utf-8')
print('3D polish applied:',len(s),'bytes')
