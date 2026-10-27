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
  let confirm=true;page.on('dialog',dialog=>confirm?dialog.accept():dialog.dismiss());
  const alice='aaaaaaaa-0000-4000-8000-000000000001',bob='bbbbbbbb-0000-4000-8000-000000000002';
  const channelA='12345678-0000-4000-8000-000000000010',channelB='12345678-0000-4000-8000-000000000011';
  let signedIn=false,current=alice,configured=false,allowed=true,paused=false,googleConfigured=false,googleAllowed=true;
  let authorizationUrl='https://accounts.google.com/o/oauth2/v2/auth?state=mock',holdChat=false,holdOAuth=false,holdProviders=false,releaseChat,releaseOAuth,releaseProviders,notifyChat,notifyOAuth,notifyProviders;
  const selected={[alice]:null,[bob]:null}, histories={
   [alice]:[{prompt:'Alice private question',reply:'<img src=x onerror=alert(1)> safe answer',provider:'groq',model:'openai/gpt-oss-120b'}],
   [bob]:[{prompt:'Bob private question',reply:'Bob reply',provider:'groq',model:'openai/gpt-oss-120b'}],
  };
  const channels={
   [alice]:[{id:channelA,channel_id:'UC1234567890123456789012',channel_title:'<img src=x onerror=alert(1)>',status:'active',is_default:true},
    {id:channelB,channel_id:'UCabcdefghijklmnopqrstuv',channel_title:'Second channel',status:'active',is_default:false}],
   [bob]:[],
  };
  const requests=[],posts=[],chatBodies=[],loginBodies=[],resendBodies=[],selections=[],disconnects=[];
  await page.route('**/api/**',async route=>{
   const rq=route.request(),p=new URL(rq.url()).pathname,m=rq.method();let data={},body={};try{body=rq.postDataJSON()||{}}catch{}
   requests.push(p);if(m!=='GET')posts.push(p);
   if(p==='/api/health')data={ok:true,text_chat:configured?'configured_unverified':'unconfigured',youtube_upload:googleConfigured?'configured_unverified':'unavailable'};
   else if(p==='/api/cloud/session')data={user:signedIn?{id:current,email:current===alice?'alice@example.test':'bob@example.test'}:null};
   else if(p==='/api/cloud/login'){loginBodies.push(body);current=body.email.startsWith('bob')?bob:alice;signedIn=true;data={ok:true};}
   else if(p==='/api/cloud/signup')data={message:'Check your email, then sign in.'};
   else if(p==='/api/cloud/resend-confirmation'){resendBodies.push(body);data={message:'If this account needs confirmation, check your inbox.'};}
   else if(p==='/api/cloud/logout'){signedIn=false;data={ok:true};}
   else if(p==='/api/cloud/providers'){
    if(holdProviders)await new Promise(resolve=>{releaseProviders=resolve;notifyProviders();});
    data={providers:configured?[{id:'groq',label:'Groq',state:'configured_unverified',models:['openai/gpt-oss-120b','llama-3.1-8b-instant']},{id:'openai',label:'OpenAI',state:'configured_unverified',models:['gpt-5.4-mini']}]:[],allowed,paused};
   }
   else if(p==='/api/cloud/chat/history' && m==='GET')data={turns:[...histories[current]].reverse()};
   else if(p==='/api/cloud/chat/history' && m==='DELETE'){histories[current]=[];data={ok:true};}
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
      connection_id:active?.id||null,saved_channels:saved};
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
   else if(p==='/api/cloud/youtube/oauth/start'){
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
  assert.equal(await page.getByRole('button',{name:'Continue with Google'}).isVisible(),true);
  assert.equal(await page.locator('#google-connect').isDisabled(),true);assert.equal(await page.locator('#chat-send').isDisabled(),true);
  assert.match(await page.locator('#channel-status').textContent(),/Google setup needed/);
  assert.equal(await page.locator('video, iframe, a[href="/workspace.html"], a[href="/skills/full.html"]').count(),0);
  assert.doesNotMatch(await page.locator('body').innerText(),/video tools|gpu|mission control|upload|catalog/i);
  await page.locator('#google-connect').dispatchEvent('click');
  assert.equal(posts.includes('/api/cloud/youtube/oauth/start'),false);
  assert.equal(requests.includes('/api/cloud/youtube/status'),false);
  // Email confirmation resend only sends the email; the password stays in the form.
  await page.locator('#account-button').click();await page.locator('#account-email').fill('alice@example.test');
  await page.locator('#account-password').fill('never-send-on-resend');await page.locator('#resend-confirmation').click();
  await page.waitForFunction(()=>document.getElementById('account-message').textContent.includes('check your inbox'));
  assert.deepEqual(resendBodies,[{email:'alice@example.test'}]);
  // A slow provider/settings check cannot keep the sign-in dialog or logout locked.
  holdProviders=true;const providersReached=new Promise(resolve=>{notifyProviders=resolve;});
  await page.locator('#account-form button[value=login]').click();await providersReached;
  await page.waitForFunction(()=>document.getElementById('account-button').textContent==='Account' && !document.getElementById('account-dialog').open);
  releaseProviders();holdProviders=false;
  await page.waitForFunction(()=>document.getElementById('chat-status').textContent.includes('No AI provider'));
  assert.equal(loginBodies.length,1);assert.equal(await page.locator('#google-connect').isDisabled(),true);
  await page.locator('#chat-prompt').fill('Hello');await page.locator('#chat-form').dispatchEvent('submit');
  assert.equal(chatBodies.length,0,'unconfigured chat must not call the provider');
  // Restore a saved channel and chat history for the authenticated owner.
  configured=true;googleConfigured=true;await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('channel-status').textContent.startsWith('Selected:'));
  assert.deepEqual(selections,[{owner:alice,id:channelA}]);
  assert.equal(await page.locator('#messages img').count(),0);assert.match(await page.locator('#messages').textContent(),/<img src=x/);
  assert.equal(await page.locator('#channel-status img').count(),0);
  await page.locator('#chat-settings').click();await page.locator('#provider').selectOption('groq');
  await page.locator('#model').selectOption('openai/gpt-oss-120b');await page.locator('#answer-length').selectOption('detailed');
  await page.locator('#fallback').selectOption('openai|gpt-5.4-mini');await page.locator('[data-close=settings-dialog]').click();
  await page.locator('#chat-prompt').fill('A useful question');await page.locator('#chat-send').click();
  await page.waitForFunction(()=>document.getElementById('messages').textContent.includes('mocked reply'));
  assert.deepEqual(chatBodies[0],{provider:'groq',model:'openai/gpt-oss-120b',mode:'chat',length:'detailed',prompt:'A useful question',fallback:{provider:'openai',model:'gpt-5.4-mini'}});
  assert.equal(await page.locator('#messages img').count(),0);assert.match(await page.locator('#chat-status').textContent(),/8 request attempt/);
  // Pause/resume stays part of chat and does not bypass backend safety settings.
  await page.locator('#chat-settings').click();await page.locator('#toggle-pause').click();
  await page.waitForFunction(()=>document.getElementById('toggle-pause').textContent==='Resume chat');assert.equal(await page.locator('#chat-send').isDisabled(),true);
  await page.locator('#toggle-pause').click();await page.waitForFunction(()=>document.getElementById('toggle-pause').textContent==='Pause chat');
  await page.locator('[data-close=settings-dialog]').click();
  await page.locator('#channel-manage').click();await page.locator('#channel-select').selectOption(channelB);await page.locator('#channel-select-button').click();
  await page.waitForFunction(()=>document.getElementById('channel-status').textContent.includes('Second channel'));
  assert.equal(selections.at(-1).id,channelB);await page.locator('#channel-disconnect').click();
  await page.waitForFunction(()=>document.getElementById('channel-message').textContent.includes('revocation was not confirmed'));
  assert.deepEqual(disconnects,[{owner:alice,id:channelB}]);await page.locator('[data-close=channel-dialog]').click();
  // A late provider response after logout must not reveal the old owner's data.
  holdChat=true;const chatReached=new Promise(resolve=>{notifyChat=resolve;});
  await page.locator('#chat-prompt').fill('Private pending question');await page.locator('#chat-send').click();await chatReached;
  await page.locator('#account-button').click();await page.locator('#logout').click();
  await page.waitForFunction(()=>document.getElementById('account-button').textContent==='Sign in');
  releaseChat();await page.waitForTimeout(100);holdChat=false;
  assert.equal(await page.locator('#messages').textContent(),'');assert.equal(await page.locator('#chat-prompt').inputValue(),'');
  assert.equal(await page.locator('#channel-manage').isHidden(),true);assert.doesNotMatch(await page.locator('#channel-status').textContent(),/Selected|img src/);
  // A different account never sees Alice's history or saved-channel names.
  await page.locator('#account-button').click();await page.locator('#account-email').fill('bob@example.test');
  await page.locator('#account-password').fill('sample-password');await page.locator('#account-form button[value=login]').click();
  await page.waitForFunction(()=>document.getElementById('messages').textContent.includes('Bob private question'));
  assert.doesNotMatch(await page.locator('#messages').textContent(),/Alice private|Private pending/);
  assert.equal(await page.locator('#channel-manage').isHidden(),true);
  // Validate redirect origin and prevent a late OAuth start from navigating after logout.
  authorizationUrl='https://example.invalid/steal';await page.locator('#google-connect').click();
  await page.waitForFunction(()=>document.getElementById('channel-error').textContent.includes('Invalid Google authorization URL'));
  assert.ok(page.url().startsWith(base));await page.locator('[data-close=channel-dialog]').click();
  authorizationUrl='https://accounts.google.com/o/oauth2/v2/auth?state=mock';holdOAuth=true;
  const oauthReached=new Promise(resolve=>{notifyOAuth=resolve;});await page.locator('#google-connect').click();await oauthReached;
  await page.locator('#account-button').click();await page.locator('#logout').click();
  await page.waitForFunction(()=>document.getElementById('account-button').textContent==='Sign in');
  releaseOAuth();await page.waitForTimeout(100);holdOAuth=false;assert.ok(page.url().startsWith(base));
  await page.locator('#account-button').click();await page.locator('#account-email').fill('bob@example.test');
  await page.locator('#account-password').fill('sample-password');await page.locator('#account-form button[value=login]').click();
  await page.waitForFunction(()=>!document.getElementById('google-connect').disabled);
  let googleNavigation='';await page.route('https://accounts.google.com/**',route=>{googleNavigation=route.request().url();return route.fulfill({status:200,body:'Mock consent page'});});
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
  assert.equal(await page.locator('#google-connect').isVisible(),true);assert.equal(await page.locator('#chat-form').isVisible(),true);
  assert.deepEqual(errors,[]);
  console.log('Mocked hosted chat smoke passed: minimal layout, auth, chat, channel restore, OAuth, logout privacy and mobile.');
 } finally {await browser?.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1});
