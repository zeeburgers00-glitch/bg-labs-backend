// Chromium smoke for the hosted chat shell. Every API and Google page below is
// mocked: this does not verify a live provider, paid call or Google consent.
// Build web/dist first; set VIMAX_BROWSER_PATH and VIMAX_PLAYWRIGHT_PATH.
const http=require('node:http'),fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.VIMAX_PLAYWRIGHT_PATH||'playwright-core');
(async()=>{
 const root=path.resolve(process.env.VIMAX_TEST_DIST||'web/dist');
 const server=http.createServer(async(req,res)=>{try{
  let p=decodeURIComponent(new URL(req.url,'http://local').pathname);if(p.endsWith('/'))p+='index.html';
  const full=path.resolve(root,'.'+p);if(!full.startsWith(root+path.sep))return res.writeHead(403).end();
  const types={'.html':'text/html','.js':'application/javascript','.css':'text/css','.svg':'image/svg+xml','.json':'application/json'};
  res.writeHead(200,{'content-type':types[path.extname(full)]||'application/octet-stream'});res.end(await fs.readFile(full));
 }catch{res.writeHead(404).end()}});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;
 try {
  if(!process.env.VIMAX_BROWSER_PATH)throw new Error('Set VIMAX_BROWSER_PATH to a Chromium executable.');
  browser=await chromium.launch({executablePath:process.env.VIMAX_BROWSER_PATH,args:['--no-sandbox','--disable-dev-shm-usage'],headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];page.on('pageerror',error=>errors.push(error.message));
  // Deterministic browser-speech fakes: no microphone or external speech service.
  await page.addInitScript(()=>{
   if(new URL(location.href).searchParams.has('no-voice')){
    Object.defineProperty(window,'speechSynthesis',{configurable:true,value:null});
    Object.defineProperty(window,'SpeechRecognition',{configurable:true,value:undefined});
    Object.defineProperty(window,'webkitSpeechRecognition',{configurable:true,value:undefined});return;
   }
   const voice={instances:[],utterances:[],cancelled:0};window.__voice=voice;
   class FakeRecognition {
    constructor(){voice.instances.push(this);}
    start(){this.started=true;this.onstart?.();}
    stop(){this.stopped=true;this.onend?.();}
    abort(){this.aborted=true;}
   }
   class FakeUtterance {constructor(text){this.text=text;}}
   const synthesis={getVoices:()=>[{name:'Test male voice',lang:'en-US',localService:true}],addEventListener(){},
    cancel(){voice.cancelled++;},speak(utterance){voice.utterances.push(utterance);utterance.onstart?.();}};
   Object.defineProperty(window,'speechSynthesis',{configurable:true,value:synthesis});
   window.SpeechRecognition=FakeRecognition;window.SpeechSynthesisUtterance=FakeUtterance;
  });
  let confirm=true,voiceConfirmCount=0;page.on('dialog',dialog=>{
   if(dialog.message().includes('Voice input may send audio'))voiceConfirmCount++;
   return confirm?dialog.accept():dialog.dismiss();
  });
  const alice='aaaaaaaa-0000-4000-8000-000000000001',bob='bbbbbbbb-0000-4000-8000-000000000002';
  const channelA='12345678-0000-4000-8000-000000000010',channelB='12345678-0000-4000-8000-000000000011';
  let signedIn=false,current=alice,configured=false,gatewayConfigured=false,allowed=true,paused=false,googleConfigured=false,googleAllowed=true,appLoginEnabled=false,fbConfigured=false;
  let googleStatusFailure=false,sessionFailure=false,usageMode='ok';
  let analyticsEnabled=false,analyticsGranted=false,analyticsMode='ok';
  let authorizationUrl='https://accounts.google.com/o/oauth2/v2/auth?state=mock',appAuthorizationUrl='https://fake.supabase.co/auth/v1/authorize?provider=google',holdChat=false,holdOAuth=false,holdProviders=false,holdUsage=false,releaseChat,releaseOAuth,releaseProviders,releaseUsage,notifyChat,notifyOAuth,notifyProviders,notifyUsage;
  const selected={[alice]:null,[bob]:null}, histories={
   [alice]:[{prompt:'Alice private question',reply:'<img src=x onerror=alert(1)> safe answer',provider:'groq',model:'openai/gpt-oss-120b'}],
   [bob]:[{prompt:'Bob private question',reply:'Bob reply',provider:'groq',model:'openai/gpt-oss-120b'}],
  };
  const channels={
   [alice]:[{id:channelA,channel_id:'UC1234567890123456789012',channel_title:'<img src=x onerror=alert(1)>',status:'active',is_default:true},
    {id:channelB,channel_id:'UCabcdefghijklmnopqrstuv',channel_title:'Second channel',status:'active',is_default:false}],
   [bob]:[],
  };
  const facebookPage='22345678-0000-4000-8000-000000000010';
  const pages={[alice]:[{id:facebookPage,provider:'facebook',external_id:'12345',display_name:'Alice Page',status:'active',is_default:true}],[bob]:[]};
  const requests=[],posts=[],chatBodies=[],loginBodies=[],resendBodies=[],selections=[],disconnects=[],facebookSelections=[],oauthBodies=[];
  await page.route('**/api/**',async route=>{
   const rq=route.request(),p=new URL(rq.url()).pathname,m=rq.method();let data={},body={};try{body=rq.postDataJSON()||{}}catch{}
   requests.push(p);if(m!=='GET')posts.push(p);
   if(p==='/api/health')data={ok:true,text_chat:configured?'configured_unverified':'unconfigured',youtube_upload:googleConfigured?'configured_unverified':'unavailable'};
   else if(p==='/api/cloud/google/status'){
    if(googleStatusFailure)return route.fulfill({status:503,json:{error:'unavailable'}});
    data={enabled:appLoginEnabled};
   }
   else if(p==='/api/cloud/google/start')data={authorization_url:appAuthorizationUrl};
   else if(p==='/api/cloud/social/status')data={providers:{facebook:{configured:fbConfigured,allowed:fbConfigured},tiktok:{configured:false,allowed:false}},connections:pages[current]};
   else if(p==='/api/cloud/social/facebook/select'){facebookSelections.push({owner:current,id:body.id});data={connection:{id:body.id,provider:'facebook'}};}
   else if(p==='/api/cloud/social/facebook/disconnect'){pages[current]=pages[current].filter(item=>item.id!==body.id);data={disconnected:true,revoked:false};}
   else if(p==='/api/cloud/social/facebook/start')data={authorization_url:'https://www.facebook.com/v26.0/dialog/oauth?state=mock'};
   else if(p==='/api/cloud/session'){
    if(sessionFailure)return route.fulfill({status:503,json:{error:'unavailable'}});
    data={user:signedIn?{id:current,email:current===alice?'alice@example.test':'bob@example.test'}:null};
   }
   else if(p==='/api/cloud/login'){loginBodies.push(body);current=body.email.startsWith('bob')?bob:alice;signedIn=true;data={ok:true};}
   else if(p==='/api/cloud/signup')data={message:'Check your email, then sign in.'};
   else if(p==='/api/cloud/resend-confirmation'){resendBodies.push(body);data={message:'If this account needs confirmation, check your inbox.'};}
   else if(p==='/api/cloud/logout'){signedIn=false;data={ok:true};}
   else if(p==='/api/cloud/providers'){
    if(holdProviders)await new Promise(resolve=>{releaseProviders=resolve;notifyProviders();});
    data={providers:configured?[...(gatewayConfigured?[{id:'vercel',label:'Vercel · Reflection Free',state:'configured_unverified',models:['reflection/beam-free']}]:[]),{id:'groq',label:'Groq',state:'configured_unverified',models:['openai/gpt-oss-120b','llama-3.1-8b-instant']},{id:'openai',label:'OpenAI',state:'configured_unverified',models:['gpt-5.4-mini']}]:[],allowed,paused};
   }
   else if(p==='/api/cloud/chat/history' && m==='GET')data={turns:[...histories[current]].reverse()};
   else if(p==='/api/cloud/chat/history' && m==='DELETE'){histories[current]=[];data={ok:true};}
   else if(p==='/api/cloud/usage' && m==='GET'){
    const owner=current;if(holdUsage)await new Promise(resolve=>{releaseUsage=resolve;notifyUsage();});
    if(usageMode==='error')return route.fulfill({status:503,json:{error:'Usage unavailable. Try again.'}});
    if(usageMode==='invalid')return route.fulfill({status:200,json:{calls:'invalid'}});
    data={calls:owner===alice?[{provider:'groq',model:'<img src=x onerror=alert(1)>',feature:'chat',status:'succeeded',input_tokens:33,output_tokens:12,created_at:'2026-10-28T06:00:00Z'},
     {provider:'groq',model:'llama-test',feature:'chat',status:'failed',input_tokens:null,output_tokens:null,created_at:'2026-10-28T06:01:00Z'}]:[]};
   }
   else if(p==='/api/cloud/ai/pause'){paused=body.paused;data={paused};}
   else if(p==='/api/cloud/chat' && m==='POST'){
    chatBodies.push(body);const owner=current;
    if(holdChat)await new Promise(resolve=>{releaseChat=resolve;notifyChat();});
    const reply='<img src=x onerror=alert(1)> mocked reply';histories[owner].push({prompt:body.prompt,reply});
    data={reply,provider:body.provider,model:body.model,remaining_user:8,history_saved:true,audit_saved:true,truncated:false,used_fallback:false};
   }
   else if(p==='/api/cloud/youtube/status'){
    const saved=channels[current],active=saved.find(item=>item.id===selected[current]);
    data={configured:googleConfigured,allowed:googleConfigured&&googleAllowed,connected:Boolean(active),channel:active?{id:active.channel_id,title:active.channel_title}:null,
      connection_id:active?.id||null,saved_channels:saved,analytics_configured:analyticsEnabled,analytics_connected:analyticsGranted};
   }
   else if(p==='/api/cloud/youtube/select'){
    selections.push({owner:current,id:body.id});const item=channels[current].find(value=>value.id===body.id);
    if(!item)return route.fulfill({status:404,json:{error:'not found'}});
    selected[current]=body.id;for(const value of channels[current])value.is_default=value.id===body.id;data={connected:true};
   }
   else if(p==='/api/cloud/youtube/disconnect'){
    disconnects.push({owner:current,id:body.id});const index=channels[current].findIndex(value=>value.id===body.id);
    if(index<0)return route.fulfill({status:404,json:{error:'not found'}});
    channels[current].splice(index,1);if(selected[current]===body.id)selected[current]=null;data={disconnected:true,revoked:false};
   }
   else if(p==='/api/cloud/youtube/analytics'){
    const active=channels[current].find(item=>item.id===selected[current]);
    if(!active)return route.fulfill({status:401,json:{error:'not connected'}});
    data={channel:{id:active.channel_id,title:active.channel_title},requested_start:'2026-09-01',requested_end:'2026-09-30',
      latest_data:analyticsMode==='empty'?null:'2026-09-29',rows:analyticsMode==='empty'?[]:[
       {day:'2026-09-01',views:100,estimated_minutes_watched:45,subscribers_gained:2},
       {day:'2026-09-29',views:220,estimated_minutes_watched:110,subscribers_gained:3}],remaining_user:4};
   }
   else if(p==='/api/cloud/youtube/oauth/start'){
    oauthBodies.push(body);
    if(holdOAuth)await new Promise(resolve=>{releaseOAuth=resolve;notifyOAuth();});
    data={authorization_url:authorizationUrl};
   }
   else return route.fulfill({status:404,json:{error:'unexpected mock path'}});
   try{return await route.fulfill({status:200,json:data});}catch(error){if(!holdChat&&!holdOAuth)throw error;}
  });
  const base=`http://127.0.0.1:${server.address().port}`;
  await page.goto(`${base}/`,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('chat-status').textContent.includes('AI provider'));
  assert.equal(await page.getByRole('heading',{name:'What’s on your mind?'}).isVisible(),true);
  await page.waitForFunction(()=>document.getElementById('google-signin-label').textContent==='Google sign-in help' && !document.getElementById('google-signin').disabled);
  assert.equal(await page.getByRole('button',{name:'Google sign-in help'}).isVisible(),true);
  assert.equal(await page.locator('#chat-send').isDisabled(),true);
  assert.match(await page.locator('#google-signin-status').textContent(),/setup needed.*help/i);
  assert.equal(await page.locator('video, iframe, a[href="/workspace.html"], a[href="/skills/full.html"]').count(),0);
  assert.doesNotMatch(await page.locator('body').innerText(),/video tools|gpu|mission control|upload|catalog/i);
  await page.setViewportSize({width:320,height:700});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'sign-in help mobile overflow');
  await page.locator('#google-signin').click();
  assert.equal(await page.locator('#account-dialog').isVisible(),true);
  assert.match(await page.locator('#account-message').textContent(),/not set up yet.*No password is needed/i);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'account dialog mobile overflow');
  await page.locator('#google-recheck').click();
  await page.waitForFunction(()=>document.getElementById('account-message').textContent.includes('still needs setup'));
  assert.equal(await page.locator('#account-google-signin').isHidden(),true);
  // Returning from setup rechecks status without starting OAuth automatically.
  appLoginEnabled=true;await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  await page.waitForFunction(()=>document.getElementById('account-message').textContent.includes('Google setup is enabled'));
  assert.equal(await page.locator('#account-google-signin').isVisible(),true);
  assert.equal(posts.includes('/api/cloud/google/start'),false);
  await page.locator('[data-close=account-dialog]').click();
  assert.equal(await page.locator('#account-button').isVisible(),true);
  assert.equal(await page.locator('#google-signin-label').textContent(),'Continue with Google');
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Google and email buttons mobile overflow');
  appLoginEnabled=false;await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('google-signin-label').textContent==='Google sign-in help' && !document.getElementById('google-signin').disabled);
  await page.locator('#google-signin').click();
  await page.setViewportSize({width:1280,height:900});
  assert.equal(posts.includes('/api/cloud/google/start'),false);
  assert.equal(posts.includes('/api/cloud/youtube/oauth/start'),false);
  assert.equal(requests.includes('/api/cloud/youtube/status'),false);
  // Resend works without a password and never sends one even when present.
  await page.locator('#account-email').fill('alice@example.test');
  assert.equal(await page.locator('#account-password').inputValue(),'');
  await page.locator('#resend-confirmation').click();
  await page.waitForFunction(()=>document.getElementById('account-message').textContent.includes('check your inbox'));
  assert.deepEqual(resendBodies,[{email:'alice@example.test'}]);
  await page.locator('#account-password').fill('never-send-on-resend');await page.locator('#resend-confirmation').click();
  await page.waitForFunction(()=>!document.getElementById('resend-confirmation').disabled);
  assert.deepEqual(resendBodies,[{email:'alice@example.test'},{email:'alice@example.test'}]);
  // A slow provider/settings check cannot keep the sign-in dialog or logout locked.
  holdProviders=true;const providersReached=new Promise(resolve=>{notifyProviders=resolve;});
  await page.locator('#account-form button[value=login]').click();await providersReached;
  await page.waitForFunction(()=>document.getElementById('account-button').textContent==='Account' && !document.getElementById('account-dialog').open);
  releaseProviders();holdProviders=false;
  await page.waitForFunction(()=>document.getElementById('chat-status').textContent.includes('No AI provider is configured'));
  assert.equal(loginBodies.length,1);assert.equal(await page.locator('#google-connect').isDisabled(),true);
  await page.locator('#chat-prompt').fill('Hello');await page.locator('#chat-form').dispatchEvent('submit');
  assert.equal(chatBodies.length,0,'unconfigured chat must not call the provider');
  // Restore a saved channel and chat history for the authenticated owner.
  configured=true;googleConfigured=true;fbConfigured=true;await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('channel-status').textContent.startsWith('Selected:'));
  assert.deepEqual(selections,[{owner:alice,id:channelA}]);
  assert.equal(await page.locator('#messages img').count(),0);assert.match(await page.locator('#messages').textContent(),/<img src=x/);
  assert.equal(await page.locator('#channel-status img').count(),0);
  await page.waitForFunction(()=>document.getElementById('facebook-status').textContent.includes('Verified this session'));
  assert.deepEqual(facebookSelections,[{owner:alice,id:facebookPage}]);
  await page.locator('#chat-settings').click();
  await page.locator('#usage-refresh').click();await page.waitForFunction(()=>document.getElementById('usage-list').childElementCount===2);
  assert.match(await page.locator('#usage-list').textContent(),/Input tokens: 33 · Output tokens: 12/);
  assert.match(await page.locator('#usage-list').textContent(),/failed; charges may apply/);
  assert.match(await page.locator('#usage-list').textContent(),/Input tokens: unknown/);
  assert.equal(await page.locator('#usage-list img').count(),0);
  assert.match(await page.locator('#usage-list').textContent(),/<img src=x/);
  usageMode='error';await page.locator('#usage-refresh').click();
  await page.waitForFunction(()=>document.getElementById('usage-message').textContent.includes('Usage unavailable'));
  assert.equal(await page.locator('#usage-list').textContent(),'');
  usageMode='invalid';await page.locator('#usage-refresh').click();
  await page.waitForFunction(()=>document.getElementById('usage-message').textContent.includes('Usage data was invalid'));
  usageMode='ok';await page.locator('#provider').selectOption('groq');
  await page.locator('#model').selectOption('openai/gpt-oss-120b');await page.locator('#answer-length').selectOption('detailed');
  await page.locator('#fallback').selectOption('openai|gpt-5.4-mini');await page.locator('[data-close=settings-dialog]').click();
  await page.locator('#chat-prompt').fill('A useful question');await page.locator('#chat-send').click();
  await page.waitForFunction(()=>document.getElementById('messages').textContent.includes('mocked reply'));
  assert.deepEqual(chatBodies[0],{provider:'groq',model:'openai/gpt-oss-120b',mode:'chat',length:'detailed',prompt:'A useful question',fallback:{provider:'openai',model:'gpt-5.4-mini'}});
  assert.equal(await page.locator('#messages img').count(),0);assert.match(await page.locator('#chat-status').textContent(),/8 request attempt/);
  // Voice is opt-in, one-shot, user-reviewed and interrupted by later input.
  const chatBeforeVoice=chatBodies.length;
  assert.equal(await page.evaluate(()=>window.__voice.instances.length),0);
  confirm=false;await page.locator('#dictate').click();confirm=true;
  assert.equal(await page.evaluate(()=>window.__voice.instances.length),0,'denied disclosure must not start the microphone');
  await page.locator('#dictate').click();
  assert.equal(voiceConfirmCount,2);
  assert.match(await page.locator('#microphone-status').textContent(),/Microphone is listening/);
  assert.equal(await page.locator('#dictate').getAttribute('aria-label'),'Stop voice input');
  await page.evaluate(()=>window.__voice.instances.at(-1).onresult({results:[[{transcript:'Assalam alaikum'}]]}));
  assert.equal(await page.locator('#chat-prompt').inputValue(),'Assalam alaikum');
  assert.equal(chatBodies.length,chatBeforeVoice,'dictation must not auto-send');
  await page.locator('#dictate').click();assert.equal(await page.locator('#microphone-status').isHidden(),true);
  await page.locator('#chat-settings').click();await page.locator('#speak-replies').check();
  await page.locator('#speech-voice').selectOption('0');await page.locator('#speech-language').fill('ur-PK');
  await page.locator('[data-close=settings-dialog]').click();await page.locator('#dictate').click();
  await page.locator('#chat-send').click();
  assert.equal(await page.evaluate(()=>window.__voice.instances.at(-1).aborted),true,'sending stops the microphone');
  await page.waitForFunction(()=>window.__voice.utterances.length===1);
  assert.deepEqual(await page.evaluate(()=>({lang:window.__voice.utterances[0].lang,voice:window.__voice.utterances[0].voice.name})),{lang:'ur-PK',voice:'Test male voice'});
  assert.equal(await page.locator('#stop-speech').isVisible(),true);
  await page.locator('#chat-prompt').fill('Another voice reply');await page.locator('#chat-send').click();
  await page.waitForFunction(()=>window.__voice.utterances.length===2);
  await page.evaluate(()=>window.__voice.utterances[0].onend());
  assert.equal(await page.locator('#stop-speech').isVisible(),true,'a stale speech callback must not hide a newer stop control');
  const cancelBefore=await page.evaluate(()=>window.__voice.cancelled);await page.locator('#dictate').click();
  assert.ok((await page.evaluate(()=>window.__voice.cancelled))>cancelBefore,'dictation interrupts playback');
  assert.equal(await page.locator('#stop-speech').isHidden(),true);await page.locator('#dictate').click();
  await page.locator('#dictate').click();
  await page.evaluate(()=>{const instance=window.__voice.instances.at(-1);instance.onerror();instance.onend();});
  assert.match(await page.locator('#microphone-status').textContent(),/Voice input is unavailable/);
  assert.equal(await page.locator('#dictate').getAttribute('aria-label'),'Start voice input');
  await page.locator('#chat-prompt').fill('Voice playback error');await page.locator('#chat-send').click();
  await page.waitForFunction(()=>window.__voice.utterances.length===3);
  await page.evaluate(()=>window.__voice.utterances[2].onerror());
  assert.match(await page.locator('#microphone-status').textContent(),/Spoken playback is unavailable/);
  assert.match(await page.locator('#messages').textContent(),/mocked reply/);
  // Pause/resume stays part of chat and does not bypass backend safety settings.
  await page.locator('#chat-settings').click();await page.locator('#toggle-pause').click();
  await page.waitForFunction(()=>document.getElementById('toggle-pause').textContent==='Resume chat');assert.equal(await page.locator('#chat-send').isDisabled(),true);
  await page.locator('#toggle-pause').click();await page.waitForFunction(()=>document.getElementById('toggle-pause').textContent==='Pause chat');
  await page.locator('[data-close=settings-dialog]').click();
  await page.locator('#account-button').click();await page.locator('#channel-manage').click();await page.locator('#channel-select').selectOption(channelB);await page.locator('#channel-select-button').click();
  await page.waitForFunction(()=>document.getElementById('channel-status').textContent.includes('Second channel'));
  assert.equal(selections.at(-1).id,channelB);await page.locator('#channel-disconnect').click();
  await page.waitForFunction(()=>document.getElementById('channel-message').textContent.includes('revocation was not confirmed'));
  assert.deepEqual(disconnects,[{owner:alice,id:channelB}]);
  await page.locator('#channel-select').selectOption(channelA);await page.locator('#channel-select-button').click();
  await page.waitForFunction(()=>document.getElementById('channel-status').textContent.startsWith('Selected:'));
  await page.locator('[data-close=channel-dialog]').click();
  await page.locator('#account-button').click();await page.locator('#facebook-manage').click();
  assert.match(await page.locator('#facebook-status').textContent(),/Alice Page/);
  await page.locator('#facebook-disconnect').click();
  await page.waitForFunction(()=>document.getElementById('facebook-message').textContent.includes('not revoked'));
  await page.locator('[data-close=facebook-dialog]').click();
  // Late usage and provider responses after logout must not reveal the old owner's data.
  holdUsage=true;const usageReached=new Promise(resolve=>{notifyUsage=resolve;});
  await page.locator('#chat-settings').click();await page.locator('#usage-refresh').click();await usageReached;
  await page.locator('[data-close=settings-dialog]').click();
  holdChat=true;const chatReached=new Promise(resolve=>{notifyChat=resolve;});
  await page.locator('#chat-prompt').fill('Private pending question');await page.locator('#chat-send').click();await chatReached;
  await page.locator('#dictate').click();assert.equal(await page.locator('#microphone-status').isVisible(),true);
  await page.locator('#account-button').click();await page.locator('#logout').click();
  await page.waitForFunction(()=>document.getElementById('account-button').textContent==='Email sign in');
  assert.equal(await page.evaluate(()=>window.__voice.instances.at(-1).aborted),true);
  // Browser callbacks arriving after logout must not repopulate the next session.
  await page.evaluate(()=>{const old=window.__voice.instances.at(-1);old.onresult({results:[[{transcript:'private late speech'}]]});old.onend();});
  releaseChat();releaseUsage();await page.waitForTimeout(100);holdChat=false;holdUsage=false;
  assert.equal(await page.locator('#microphone-status').isHidden(),true);
  assert.equal(await page.locator('#usage-list').textContent(),'');
  assert.equal(await page.locator('#messages').textContent(),'');assert.equal(await page.locator('#chat-prompt').inputValue(),'');
  assert.equal(await page.locator('#channel-manage').isHidden(),true);assert.doesNotMatch(await page.locator('#channel-status').textContent(),/Selected|img src/);
  // A different account never sees Alice's history or saved-channel names.
  await page.locator('#account-button').click();await page.locator('#account-email').fill('bob@example.test');
  await page.locator('#account-password').fill('sample-password');await page.locator('#account-form button[value=login]').click();
  await page.waitForFunction(()=>document.getElementById('messages').textContent.includes('Bob private question'));
  assert.doesNotMatch(await page.locator('#messages').textContent(),/Alice private|Private pending/);
  await page.locator('#chat-settings').click();await page.locator('#usage-refresh').click();
  await page.waitForFunction(()=>document.getElementById('usage-message').textContent.includes('No recorded usage'));
  assert.equal(await page.locator('#usage-list').textContent(),'');await page.locator('[data-close=settings-dialog]').click();
  const voicePromptsBeforeBob=voiceConfirmCount;await page.locator('#dictate').click();
  assert.equal(voiceConfirmCount,voicePromptsBeforeBob+1,'voice disclosure must not carry between accounts');
  await page.evaluate(()=>window.dispatchEvent(new Event('pagehide')));
  assert.equal(await page.evaluate(()=>window.__voice.instances.at(-1).aborted),true);
  assert.equal(await page.locator('#microphone-status').isHidden(),true);
  assert.equal(await page.locator('#channel-manage').isHidden(),true);
  // General chat works without a YouTube grant; analytics still requires one.
  gatewayConfigured=true;await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('provider').value==='vercel');
  assert.equal(await page.locator('#gateway-privacy').isVisible(),true);
  assert.match(await page.locator('#gateway-privacy').textContent(),/Vercel and Reflection.*retain or use/i);
  await page.locator('#chat-prompt').fill('Hello without a channel');
  await page.waitForFunction(()=>!document.getElementById('chat-send').disabled);
  await page.locator('#chat-send').click();
  await page.waitForFunction(()=>document.getElementById('chat-status').textContent.includes('request attempt'));
  assert.equal(chatBodies.at(-1).provider,'vercel');assert.equal(chatBodies.at(-1).fallback,null);
  await page.locator('#chat-settings').click();assert.equal(await page.locator('#fallback').isDisabled(),true);
  await page.locator('#provider').selectOption('groq');await page.locator('#fallback').selectOption('vercel|reflection/beam-free');
  assert.equal(await page.locator('#gateway-privacy').evaluate(el=>el.hidden),false);
  await page.locator('#provider').selectOption('vercel');assert.equal(await page.locator('#fallback').inputValue(),'');
  assert.equal(await page.locator('#fallback').isDisabled(),true);await page.locator('[data-close=settings-dialog]').click();
  await page.locator('#chat-prompt').fill('show my channel analytics');
  assert.match(await page.locator('#chat-status').textContent(),/Connect a YouTube channel/);
  assert.equal(await page.locator('#chat-send').isDisabled(),true);
  await page.locator('#chat-prompt').fill('');gatewayConfigured=false;
  // Validate redirect origin and prevent a late OAuth start from navigating after logout.
  authorizationUrl='https://example.invalid/steal';await page.locator('#account-button').click();await page.locator('#channel-manage').click();await page.locator('#google-connect').click();
  await page.waitForFunction(()=>document.getElementById('channel-error').textContent.includes('Invalid Google authorization URL'));
  assert.ok(page.url().startsWith(base));await page.locator('[data-close=channel-dialog]').click();
  authorizationUrl='https://accounts.google.com/o/oauth2/v2/auth?state=mock';holdOAuth=true;
  const oauthReached=new Promise(resolve=>{notifyOAuth=resolve;});await page.locator('#account-button').click();await page.locator('#channel-manage').click();await page.locator('#google-connect').click();await oauthReached;
  await page.locator('[data-close=channel-dialog]').click();await page.locator('#account-button').click();await page.locator('#logout').click();
  await page.waitForFunction(()=>document.getElementById('account-button').textContent==='Email sign in');
  releaseOAuth();await page.waitForTimeout(100);holdOAuth=false;assert.ok(page.url().startsWith(base));
  await page.locator('#account-button').click();await page.locator('#account-email').fill('bob@example.test');
  await page.locator('#account-password').fill('sample-password');await page.locator('#account-form button[value=login]').click();
  await page.waitForFunction(()=>!document.getElementById('google-connect').disabled);
  let googleNavigation='';await page.route('https://accounts.google.com/**',route=>{googleNavigation=route.request().url();return route.fulfill({status:200,body:'Mock consent page'});});
  await page.locator('#account-button').click();await page.locator('#channel-manage').click();
  await page.locator('#google-connect').click();await page.waitForURL('https://accounts.google.com/**');
  assert.equal(new URL(googleNavigation).pathname,'/o/oauth2/v2/auth');
  assert.equal(posts.filter(value=>value==='/api/cloud/youtube/oauth/start').length,3);
  // Existing callback paths still show the focused interface and remove query/fragment.
  await page.goto(`${base}/skills/?youtube=connected#youtube`,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>!location.search && !location.hash);assert.equal(await page.locator('#chat-form').isVisible(),true);
  signedIn=false;await page.goto(`${base}/skills/?confirm_test=1#access_token=test-token&refresh_token=test-refresh`,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>!location.hash && document.getElementById('account-message').textContent.includes('Email confirmed'));
  assert.equal(await page.locator('#account-dialog').isVisible(),true);assert.ok(!page.url().includes('test-token'));
  await page.locator('[data-close=account-dialog]').click();await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile overflow');
  assert.equal(await page.locator('#google-signin').isVisible(),true);assert.equal(await page.locator('#chat-form').isVisible(),true);
  // A forged success query without this tab's login intent cannot start channel consent.
  appLoginEnabled=true;signedIn=true;current=bob;const beforeAuto=posts.filter(value=>value==='/api/cloud/youtube/oauth/start').length;
  await page.goto(`${base}/skills/?google_signin=success`,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('channel-status').textContent.includes('Connect your YouTube channel'));
  assert.equal(posts.filter(value=>value==='/api/cloud/youtube/oauth/start').length,beforeAuto);
  await page.locator('#chat-prompt').fill('show my channel analytics');
  assert.equal(await page.locator('#chat-send').isDisabled(),true);
  // Google app sign-in is first; reject untrusted redirect, then mock the
  // Supabase callback and the first separately-consented channel authorization.
  signedIn=false;await page.goto(`${base}/`,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>!document.getElementById('google-signin').disabled);
  assert.equal(await page.getByRole('button',{name:'Continue with Google'}).isVisible(),true);
  assert.equal(await page.locator('#account-button').isVisible(),true);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Google and email choices mobile overflow');
  await page.locator('#account-button').click();assert.equal(await page.locator('#account-google-signin').isVisible(),true);
  appAuthorizationUrl='https://evil.example/steal';await page.locator('#account-google-signin').click();
  await page.waitForFunction(()=>document.getElementById('account-error').textContent.includes('Invalid Google sign-in URL'));
  await page.locator('[data-close=account-dialog]').click();
  await page.waitForFunction(()=>document.getElementById('google-signin-status').textContent.includes('Invalid Google sign-in URL'));
  assert.ok(page.url().startsWith(base));assert.equal(await page.locator('#account-button').isVisible(),true);
  appAuthorizationUrl='https://fake.supabase.co/auth/v1/authorize?provider=google';let appNavigation='';
  await page.route('https://fake.supabase.co/**',route=>{appNavigation=route.request().url();return route.fulfill({status:200,body:'Mock app sign-in'});});
  await page.locator('#google-signin').click();await page.waitForURL('https://fake.supabase.co/**');
  assert.equal(new URL(appNavigation).pathname,'/auth/v1/authorize');
  signedIn=true;await page.goto(`${base}/skills/?google_signin=success`,{waitUntil:'domcontentloaded'});
  await page.waitForURL('https://accounts.google.com/**');
  assert.equal(posts.filter(value=>value==='/api/cloud/youtube/oauth/start').length,beforeAuto+1);
  // A saved channel restores without a second consent; it enables channel analytics.
  channels[bob]=[{id:channelB,channel_id:'UCabcdefghijklmnopqrstuv',channel_title:'Bob channel',status:'active',is_default:true}];selected[bob]=null;
  await page.goto(`${base}/skills/?youtube=connected#youtube`,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('channel-status').textContent.includes('Bob channel'));
  await page.locator('#chat-prompt').fill('Hi');assert.equal(await page.locator('#chat-send').isEnabled(),true);
  // Analytics is never fabricated: disabled and unconsented cases do not call Google or draw an image.
  await page.locator('#chat-prompt').fill('analytics ka screenshot bhej do');await page.locator('#chat-send').click();
  await page.waitForFunction(()=>document.getElementById('messages').textContent.includes('has not been enabled'));
  assert.equal(posts.filter(value=>value==='/api/cloud/youtube/analytics').length,0);assert.equal(await page.locator('.analytics-canvas').count(),0);
  analyticsEnabled=true;await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('channel-status').textContent.includes('Bob channel'));
  await page.locator('#chat-prompt').fill('show my channel analytics');await page.locator('#chat-send').click();
  await page.waitForFunction(()=>document.getElementById('messages').textContent.includes('allow Analytics access'));
  assert.equal(posts.filter(value=>value==='/api/cloud/youtube/analytics').length,0);
  // A report can be requested even without a configured text model. The chart
  // is explicitly a ViMax visualization, downloadable and scoped to Bob.
  analyticsGranted=true;configured=false;await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('channel-status').textContent.includes('Bob channel'));
  const beforeChat=chatBodies.length;await page.locator('#chat-prompt').fill('analytics ka screenshot bhej do');
  await page.waitForFunction(()=>!document.getElementById('chat-send').disabled);await page.locator('#chat-send').click();
  await page.waitForSelector('.analytics-canvas');assert.equal(chatBodies.length,beforeChat);
  assert.match(await page.locator('#messages').textContent(),/Bob channel/);assert.match(await page.locator('#messages').textContent(),/not a YouTube Studio screenshot/i);
  assert.match(await page.locator('.analytics-canvas').getAttribute('aria-label'),/Bob channel/);
  assert.match(await page.locator('.analytics-summary').textContent(),/320 views · 155 watch minutes · 5 subscribers gained/);
  assert.ok((await page.locator('.analytics-canvas').evaluate(canvas=>canvas.toDataURL('image/png'))).startsWith('data:image/png;base64,'));
  if(process.env.VIMAX_CHAT_SCREENSHOT)await page.screenshot({path:process.env.VIMAX_CHAT_SCREENSHOT});
  const [download]=await Promise.all([page.waitForEvent('download'),page.locator('.analytics-save').click()]);
  assert.equal(download.suggestedFilename(),'vimax-youtube-analytics.png');
  analyticsMode='empty';await page.locator('#chat-prompt').fill('send analytics report');await page.locator('#chat-send').click();
  await page.waitForFunction(()=>document.getElementById('messages').textContent.includes('no daily analytics rows'));
  assert.equal(await page.locator('.message.assistant').last().locator('.analytics-canvas').count(),0);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'analytics mobile overflow');
  holdOAuth=true;const analyticsOAuthReached=new Promise(resolve=>{notifyOAuth=resolve;});
  await page.locator('#account-button').click();await page.locator('#channel-manage').click();await page.locator('#google-connect').click();await analyticsOAuthReached;
  assert.deepEqual(oauthBodies.at(-1),{analytics:true});
  await page.locator('[data-close=channel-dialog]').click();await page.locator('#account-button').click();await page.locator('#logout').click();
  await page.waitForFunction(()=>document.getElementById('google-signin').offsetParent!==null);
  releaseOAuth();await page.waitForTimeout(100);holdOAuth=false;assert.ok(page.url().startsWith(base));
  assert.equal(await page.locator('.analytics-canvas').count(),0);assert.equal(await page.locator('#messages').textContent(),'');
  // Failed configuration/account checks offer honest help, not a Google redirect.
  const starts=posts.filter(value=>value==='/api/cloud/google/start').length;
  signedIn=false;appLoginEnabled=false;googleStatusFailure=true;
  await page.goto(`${base}/`,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('google-signin-status').textContent.includes('could not be checked') && !document.getElementById('google-signin').disabled);
  assert.equal(await page.getByRole('button',{name:'Google sign-in help'}).isVisible(),true);
  await page.locator('#google-signin').click();
  assert.match(await page.locator('#account-message').textContent(),/could not be checked/i);
  await page.locator('#google-recheck').click();
  await page.waitForFunction(()=>document.getElementById('account-message').textContent.includes('could not be checked'));
  googleStatusFailure=false;appLoginEnabled=true;
  await page.locator('#google-recheck').click();
  await page.waitForFunction(()=>document.getElementById('account-message').textContent.includes('Google setup is enabled'));
  assert.equal(await page.locator('#account-google-signin').isVisible(),true);
  assert.equal(posts.filter(value=>value==='/api/cloud/google/start').length,starts);
  googleStatusFailure=false;sessionFailure=true;appLoginEnabled=true;
  await page.goto(`${base}/`,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('google-signin-status').textContent.includes('Account service unavailable') && !document.getElementById('google-signin').disabled);
  assert.equal(await page.locator('#account-button').isVisible(),true);
  await page.locator('#google-signin').click();
  assert.match(await page.locator('#account-message').textContent(),/account service could not be checked/i);
  await page.locator('#google-recheck').click();
  await page.waitForFunction(()=>document.getElementById('account-message').textContent.includes('still unavailable'));
  sessionFailure=false;await page.locator('#google-recheck').click();
  await page.waitForFunction(()=>document.getElementById('account-message').textContent.includes('Google setup is enabled'));
  assert.equal(await page.locator('#account-google-signin').isVisible(),true);
  assert.equal(posts.filter(value=>value==='/api/cloud/google/start').length,starts);
  // Devices without browser speech still have a working text path and a clear error.
  sessionFailure=false;appLoginEnabled=false;signedIn=true;current=bob;configured=true;
  await page.goto(`${base}/?no-voice=1`,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('account-button').textContent==='Account' && document.getElementById('provider').value==='groq');
  assert.equal(await page.locator('#dictate').isDisabled(),true);
  await page.locator('#chat-settings').click();await page.locator('#speak-replies').check();await page.locator('[data-close=settings-dialog]').click();
  await page.locator('#chat-prompt').fill('Text still works');await page.locator('#chat-send').click();
  await page.waitForFunction(()=>document.getElementById('microphone-status').textContent.includes('Spoken playback is unavailable'));
  assert.match(await page.locator('#messages').textContent(),/mocked reply/);
  assert.deepEqual(errors,[]);
  console.log('Mocked hosted chat smoke passed: auth, channel consent/restore, analytics, usage, speech safety and mobile.');
 } finally {await browser?.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1});
