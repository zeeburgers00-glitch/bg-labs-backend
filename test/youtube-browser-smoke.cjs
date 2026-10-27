// Optional Chromium smoke: APIs below are mocked; this never contacts Google.
// Build web/dist first. Set VIMAX_BROWSER_PATH and, if needed,
// VIMAX_PLAYWRIGHT_PATH to an installed playwright-core module.
const http=require('node:http'),fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.VIMAX_PLAYWRIGHT_PATH||'playwright-core');
(async()=>{
 const root=path.resolve(process.env.VIMAX_TEST_DIST||'web/dist');
 const server=http.createServer(async(req,res)=>{try{
  let p=decodeURIComponent(new URL(req.url,'http://local').pathname);if(p.endsWith('/'))p+='index.html';
  const full=path.resolve(root,'.'+p);if(!full.startsWith(root+path.sep))return res.writeHead(403).end();
  const types={'.html':'text/html','.js':'application/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml'};
  res.writeHead(200,{'content-type':types[path.extname(full)]||'application/octet-stream'});res.end(await fs.readFile(full));
 }catch{res.writeHead(404).end()}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
 try{
  if(!process.env.VIMAX_BROWSER_PATH)throw new Error('Set VIMAX_BROWSER_PATH to a Chromium executable.');
  browser=await chromium.launch({executablePath:process.env.VIMAX_BROWSER_PATH,args:['--no-sandbox','--disable-dev-shm-usage'],headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  let acceptDialog=false;page.on('dialog',dialog=>acceptDialog?dialog.accept():dialog.dismiss());
  const alice='aaaaaaaa-0000-4000-8000-000000000001',bob='bbbbbbbb-0000-4000-8000-000000000002';
  const uploadId='12345678-0000-4000-8000-000000000002',secondId='12345678-0000-4000-8000-000000000003',channel='UC1234567890123456789012';
  let current=alice,signedIn=false,firstStart=true,failStatus=false,releaseChunk,releaseSecond,connectionMode=false,selectedConnection=null;
  let youtubeConfigured=false,youtubeAllowed=true,localOnly=false,authorizationUrl='https://accounts.google.com/o/oauth2/v2/auth?state=mock';
  let holdOAuth=false,notifyOAuth,releaseOAuth;
  const connectionA='12345678-0000-4000-8000-000000000010',connectionB='12345678-0000-4000-8000-000000000011';
  const saved=[{id:connectionA,channel_id:channel,channel_title:'<img src=x onerror=alert(1)>',status:'active',is_default:true},
    {id:connectionB,channel_id:'UCabcdefghijklmnopqrstuv',channel_title:'Another channel',status:'active',is_default:false}];
  const selections=[],disconnects=[];
  let socialMode=false;
  const socialTik='12345678-0000-4000-8000-000000000021',socialFb='12345678-0000-4000-8000-000000000022';
  const socialConnections=[{id:socialTik,provider:'tiktok',external_id:'tik_user',display_name:'<img src=x onerror=alert(1)>',status:'active',is_default:true},
    {id:socialFb,provider:'facebook',external_id:'123456789',display_name:'Example Page',status:'active',is_default:true}];
  const socialSelections=[],socialRemovals=[];
  let reachedChunk,reachedSecond;const chunkReached=new Promise(r=>{reachedChunk=r;}),secondReached=new Promise(r=>{reachedSecond=r;});
  const jobs=[],keys=[],posts=[],requests=[],chatBodies=[],resendBodies=[];
  await page.route('**/api/**',async route=>{
   const rq=route.request(),u=new URL(rq.url()),p=u.pathname,m=rq.method();let data={},body={};try{body=rq.postDataJSON()||{}}catch{}
   requests.push(p);if(m!=='GET')posts.push(p);
   if(p==='/api/skills/system')data={local_only:localOnly,database_connected:true,text_chat:'unconfigured',youtube_upload:youtubeConfigured?'configured_unverified':'unavailable',ready_for_video:false,piper_installed:false,ffmpeg_installed:false,scene_detection_installed:false,voices:[],hardware:{},warnings:[]};
   else if(p==='/api/skills/jobs')data={jobs:[]};
   else if(p==='/api/cloud/session')data={user:signedIn?{id:current,email:'person@example.test'}:null};
   else if(p==='/api/cloud/resend-confirmation'){resendBodies.push(body);data={message:'If this account needs confirmation, check your inbox.'};}
   else if(p==='/api/cloud/projects')data={projects:[]};
   else if(p==='/api/cloud/providers')data={providers:[{id:'groq',label:'Groq',state:'configured_unverified',models:['openai/gpt-oss-120b']}],pexels:'not_configured',allowed:true,paused:false};
   else if(p==='/api/cloud/chat/history')data={turns:[]};
   else if(p==='/api/cloud/chat'){chatBodies.push(body);data={reply:'A partial response',provider:body.provider,model:body.model,truncated:true,used_fallback:false,remaining_user:8,history_saved:true,audit_saved:true};}
   else if(p==='/api/cloud/usage')data={calls:[]};
   else if(p==='/api/cloud/github/repository')data={repository:{name:'octocat/Hello-World',url:'https://github.com/octocat/Hello-World',description:'<img src=x onerror=alert(1)>',stars:12,forks:3,license:'MIT',archived:false},remaining_user:9,audit_saved:true};
   else if(p==='/api/cloud/mission')data={channels:[],competitors:[],jobs:[],workers:[],paused:false};
   else if(p==='/api/cloud/social/status')data={providers:{tiktok:{configured:socialMode,allowed:socialMode},facebook:{configured:socialMode,allowed:socialMode}},
    connections:socialMode&&current===alice?socialConnections:[]};
   else if(p==='/api/cloud/social/tiktok/select'||p==='/api/cloud/social/facebook/select'){
    socialSelections.push({owner:current,id:body.id});data={connection:socialConnections.find(x=>x.id===body.id)};}
   else if(p==='/api/cloud/social/facebook/disconnect'){
    socialRemovals.push({owner:current,id:body.id});const index=socialConnections.findIndex(x=>x.id===body.id);
    if(index>=0)socialConnections.splice(index,1);data={disconnected:true,revoked:false};}
   else if(p==='/api/cloud/youtube/status'){
    if(failStatus){failStatus=false;return route.fulfill({status:503,json:{error:'simulated status outage'}});}
    if(!youtubeConfigured||!youtubeAllowed)data={configured:youtubeConfigured,allowed:false,connected:false,channel:null,saved_channels:[]};
    else if(connectionMode){const channels=current===alice?saved:[],active=channels.find(x=>x.id===selectedConnection);
      data={configured:true,allowed:true,connected:Boolean(active),channel:active?{id:active.channel_id,title:active.channel_title}:null,
        connection_id:active?.id||null,saved_channels:channels,expires_at:new Date(Date.now()+3600000).toISOString()};}
    else data={configured:true,allowed:true,connected:true,channel:{id:channel,title:'Test channel'},expires_at:new Date(Date.now()+3600000).toISOString()};
   }
   else if(p==='/api/cloud/youtube/oauth/start' && m==='POST'){
    if(holdOAuth)await new Promise(resolve=>{releaseOAuth=resolve;notifyOAuth();});
    data={authorization_url:authorizationUrl};
   }
   else if(p==='/api/cloud/youtube/select' && connectionMode){selections.push({owner:current,id:body.id});
    if(current!==alice||!saved.some(x=>x.id===body.id))return route.fulfill({status:404,json:{error:'not found'}});
    selectedConnection=body.id;for(const x of saved)x.is_default=x.id===body.id;data={connected:true};}
   else if(p==='/api/cloud/youtube/disconnect' && connectionMode){disconnects.push({owner:current,id:body.id});
    const index=saved.findIndex(x=>x.id===body.id);if(current!==alice||index<0)return route.fulfill({status:404,json:{error:'not found'}});
    saved.splice(index,1);if(selectedConnection===body.id)selectedConnection=null;data={disconnected:true,revoked:false};}
   else if(p==='/api/cloud/youtube/uploads')data={uploads:jobs.filter(j=>j.owner===current)};
   else if(p==='/api/cloud/youtube/uploads/start'){
    keys.push(body.client_key);
    if(firstStart){firstStart=false;jobs.push({id:uploadId,owner:current,channel_id:channel,title:body.title,size_bytes:body.size_bytes,file_sha256:body.file_sha256,status:'uploading',offset_bytes:0,cancel_requested:false});return route.abort('failed');}
    if(keys.length===2)data={id:uploadId,status:'uploading',existing:true};
    else{jobs.push({id:secondId,owner:current,channel_id:channel,title:body.title,size_bytes:body.size_bytes,file_sha256:body.file_sha256,status:'uploading',offset_bytes:0,cancel_requested:false});data={id:secondId,status:'uploading',existing:false};}
   }
   else if(p===`/api/cloud/youtube/uploads/${uploadId}/chunk` || p===`/api/cloud/youtube/uploads/${secondId}/chunk`){
    const job=jobs.find(j=>p.includes(j.id)),offset=Number(rq.headers()['x-vimax-offset']),length=rq.postDataBuffer().length;
    if(job.id===uploadId && offset===0){reachedChunk();await new Promise(r=>{releaseChunk=r;});}
    if(job.id===secondId && offset===0){reachedSecond();await new Promise(r=>{releaseSecond=r;});}
    job.offset_bytes=offset+length;
    if(job.offset_bytes===job.size_bytes){job.status='completed';job.video_id='abcdefghijk';data={status:'completed',offset_bytes:job.offset_bytes,message:'Private upload verified on the selected channel.'};}
    else data={status:'uploading',offset_bytes:job.offset_bytes};
   }
   else if(p==='/api/cloud/logout'){signedIn=false;data={ok:true};}
   else return route.fulfill({status:404,json:{error:'unexpected mock path'}});
   return route.fulfill({status:200,json:data});
  });
  const skills=`http://127.0.0.1:${server.address().port}/skills/`;
  // The deep link must reveal the option while signed out without exposing owner data.
  await page.goto(`${skills}#youtube`,{waitUntil:'domcontentloaded'});
  await page.waitForSelector('#youtube:not([hidden])');
  await page.waitForFunction(()=>document.getElementById('yt-connection').textContent.includes('needs server setup'));
  await page.waitForFunction(()=>Math.abs(document.getElementById('youtube').getBoundingClientRect().top)<20);
  assert.equal(await page.locator('#yt-connect').isVisible(),true);
  assert.equal(await page.locator('#yt-connect').isDisabled(),true);
  assert.equal(await page.locator('#yt-login-prompt a').getAttribute('href'),'#account');
  assert.equal(await page.locator('#yt-saved-tools').isHidden(),true);
  assert.equal(await page.locator('#yt-upload-panel').isHidden(),true);
  await page.locator('#yt-connect').dispatchEvent('click');
  assert.equal(posts.includes('/api/cloud/youtube/oauth/start'),false);
  assert.equal(requests.some(p=>p==='/api/cloud/youtube/status'||p==='/api/cloud/youtube/uploads'),false);
  // A signed-in owner cannot start OAuth while setup is missing or access is denied.
  signedIn=true;await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('yt-connection').textContent.includes('not configured'));
  assert.equal(await page.locator('#yt-connect').isDisabled(),true);
  assert.equal(await page.locator('#yt-login-prompt').isHidden(),true);
  youtubeConfigured=true;youtubeAllowed=false;await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('yt-connection').textContent.includes('not enabled'));
  assert.equal(await page.locator('#yt-connect').isDisabled(),true);
  await page.locator('#yt-connect').dispatchEvent('click');assert.equal(posts.includes('/api/cloud/youtube/oauth/start'),false);
  youtubeAllowed=true;await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForSelector('#youtube:not([hidden])');await page.waitForFunction(()=>!document.getElementById('yt-upload').disabled);
  await page.waitForSelector('#mission:not([hidden])');
  await page.locator('#mission-provider').selectOption('openai');
  assert.equal(await page.locator('#mission-model').inputValue(),'gpt-5.4-mini');
  await page.locator('#mission-provider').selectOption('groq');
  await page.waitForFunction(()=>!document.getElementById('chat-send').disabled);
  await page.locator('#ai-length').selectOption('detailed');
  await page.locator('#chat-prompt').fill('Write a detailed response.');
  await page.locator('#chat-send').click();
  await page.waitForFunction(()=>document.getElementById('chat-status').textContent.includes('truncated'));
  assert.equal(chatBodies[0].length,'detailed');
  await page.waitForFunction(()=>!document.getElementById('github-lookup').disabled);
  await page.locator('#github-repository').fill('octocat/Hello-World');await page.locator('#github-lookup').click();
  await page.waitForSelector('#github-result a');assert.equal(await page.locator('#github-result img').count(),0);
  assert.equal(await page.locator('#github-result a').getAttribute('href'),'https://github.com/octocat/Hello-World');
  await page.evaluate(()=>window.vimaxCloud.onSession(true));assert.equal(await page.locator('#github-result a').count(),0);
  const fill=async()=>{
   await page.locator('#yt-file').setInputFiles({name:'sample.mp4',mimeType:'video/mp4',buffer:Buffer.alloc(1024*1024+17,7)});
   await page.locator('#yt-form [name=title]').fill('<img src=x onerror=alert(1)>');
   await page.locator('#yt-form [name=description]').fill('An original private sample.');
   await page.locator('#yt-form [name=audience]').selectOption('no');
   await page.locator('#yt-form [name=confirm_private]').check();
  };
  await fill();await page.locator('#yt-upload').click();
  await page.waitForFunction(()=>document.getElementById('yt-error').textContent.includes('interrupted'));
  await page.waitForSelector('#yt-clear-pending:not([hidden])');
  assert.equal(keys.length,1);assert.equal(await page.locator('#yt-history img').count(),0);
  assert.match(await page.locator('#yt-history').innerText(),/<img src=x/);
  current=bob;await page.evaluate(id=>window.vimaxYouTube.onSession({id}),bob);
  assert.equal(await page.locator('#yt-clear-pending').isHidden(),true);
  assert.equal(await page.locator('#yt-file').inputValue(),'');assert.equal(await page.locator('#yt-history .mission-row').count(),0);
  current=alice;await page.evaluate(id=>window.vimaxYouTube.onSession({id}),alice);
  assert.equal(await page.locator('#yt-clear-pending').isVisible(),true);
  await fill();await page.locator('#yt-upload').click();await chunkReached;
  assert.deepEqual(keys,[keys[0],keys[0]],'an interrupted start must reuse its key');
  failStatus=true;await page.locator('#yt-refresh').click();await page.waitForFunction(()=>document.getElementById('yt-error').textContent.includes('simulated status outage'));
  assert.equal(await page.locator('#yt-upload').isDisabled(),true,'failed refresh must not clear an active upload busy state');
  assert.equal(await page.locator('#yt-connect').isDisabled(),true);
  releaseChunk();await page.waitForFunction(()=>document.getElementById('yt-progress').textContent.includes('verified'));
  await page.waitForFunction(()=>!document.getElementById('yt-upload').disabled);
  assert.match(await page.locator('#yt-history').innerText(),/completed/);
  await page.evaluate(id=>sessionStorage.setItem(`vimax-yt-pending:${id}`,'test-pending'),alice);
  await page.locator('#yt-refresh').click();await page.waitForSelector('#yt-clear-pending:not([hidden])');
  await page.locator('#yt-clear-pending').click();assert.equal(await page.evaluate(id=>sessionStorage.getItem(`vimax-yt-pending:${id}`),alice),'test-pending');
  acceptDialog=true;await page.locator('#yt-clear-pending').click();assert.equal(await page.evaluate(id=>sessionStorage.getItem(`vimax-yt-pending:${id}`),alice),null);
  await fill();await page.locator('#yt-upload').click();await secondReached;
  current=bob;await page.evaluate(id=>window.vimaxYouTube.onSession({id}),bob);
  releaseSecond();await page.waitForTimeout(150);
  assert.equal(await page.locator('#yt-file').inputValue(),'');assert.equal(await page.locator('#yt-history .mission-row').count(),0);
  assert.match(await page.locator('#yt-progress').innerText(),/No upload in progress/);
  // Simulate a returning owner with no access cookie: the saved default is
  // restored once, channel names are rendered as text, and switching/removing
  // sends the selected record ID rather than a provider token.
  connectionMode=true;current=alice;selectedConnection=null;
  await page.evaluate(id=>window.vimaxYouTube.onSession({id}),alice);
  await page.waitForFunction(()=>document.getElementById('yt-connection').textContent.startsWith('Selected:'));
  assert.deepEqual(selections,[{owner:alice,id:connectionA}]);
  assert.equal(await page.locator('#youtube img').count(),0);assert.match(await page.locator('#yt-saved-channels').innerText(),/<img src=x/);
  await page.locator('#yt-saved-channels').selectOption(connectionB);await page.locator('#yt-select-channel').click();
  await page.waitForFunction(()=>document.getElementById('yt-connection').textContent.includes('Another channel'));
  assert.equal(selections.at(-1).id,connectionB);
  await page.locator('#yt-disconnect').click();await page.waitForFunction(()=>document.getElementById('yt-notice').textContent.includes('revocation was not confirmed'));
  assert.deepEqual(disconnects,[{owner:alice,id:connectionB}]);assert.equal(saved.length,1);
  socialMode=true;await page.evaluate(id=>window.vimaxSocial.onSession({id}),alice);
  await page.waitForFunction(()=>document.getElementById('social-tiktok-status').textContent.startsWith('Verified this session'));
  await page.waitForFunction(()=>document.getElementById('social-facebook-status').textContent.startsWith('Verified this session'));
  assert.equal(socialSelections.length,2);assert.equal(await page.locator('#social-connections img').count(),0);
  assert.match(await page.locator('#social-tiktok-list').innerText(),/<img src=x/);
  await page.locator('#social-facebook-remove').click();
  await page.waitForFunction(()=>document.getElementById('social-facebook-notice').textContent.includes('revocation was not confirmed'));
  assert.deepEqual(socialRemovals,[{owner:alice,id:socialFb}]);
  current=bob;selectedConnection=null;await page.evaluate(id=>window.vimaxSocial.onSession({id}),bob);
  assert.equal(await page.locator('#social-tiktok-list').inputValue(),'');
  await page.evaluate(id=>window.vimaxYouTube.onSession({id}),bob);
  assert.equal(await page.locator('#yt-saved-channels option').count(),1);
  assert.equal(await page.locator('#yt-saved-channels').inputValue(),'');
  // Logout leaves the connection option visible but removes all owner-specific
  // names, history, selections, notices and form contents from the page.
  current=alice;selectedConnection=connectionA;await page.evaluate(id=>window.vimaxYouTube.onSession({id}),alice);
  assert.match(await page.locator('#yt-saved-channels').textContent(),/<img src=x/);
  await page.locator('#yt-form [name=title]').fill('Private title');
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile overflow');
  await page.locator('#logout-button').click();await page.waitForSelector('#yt-login-prompt:not([hidden])');
  assert.equal(await page.locator('#youtube').isVisible(),true);
  assert.equal(await page.locator('#yt-connect').isDisabled(),true);
  assert.equal(await page.locator('#yt-connect').textContent(),'Continue with Google');
  assert.match(await page.locator('#yt-connection').textContent(),/not yet been verified/);
  assert.equal(await page.locator('#yt-saved-tools').isHidden(),true);
  assert.equal(await page.locator('#yt-upload-panel').isHidden(),true);
  assert.equal(await page.locator('#yt-saved-channels option').count(),0);
  assert.equal(await page.locator('#yt-history .mission-row').count(),0);
  assert.equal(await page.locator('#yt-form [name=title]').inputValue(),'');
  assert.equal(await page.locator('#yt-notice').textContent(),'');assert.equal(await page.locator('#yt-error').textContent(),'');
  await page.locator('#account-form [name=email]').fill('person@example.test');
  await page.locator('#account-form [name=password]').fill('never-send-on-resend');
  await page.locator('#resend-confirmation').click();
  await page.waitForFunction(()=>document.getElementById('account-message').textContent.includes('check your inbox'));
  assert.deepEqual(resendBodies,[{email:'person@example.test'}]);
  // Starting the real UI action must POST to the OAuth endpoint and only
  // navigate to the Google origin, never an arbitrary returned URL. A late
  // start response must not redirect after the owner logs out.
  signedIn=true;connectionMode=false;await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>!document.getElementById('yt-connect').disabled);
  authorizationUrl='https://example.invalid/steal';await page.locator('#yt-connect').click();
  await page.waitForFunction(()=>document.getElementById('yt-error').textContent.includes('Invalid Google authorization URL'));
  assert.ok(page.url().startsWith(skills));
  authorizationUrl='https://accounts.google.com/o/oauth2/v2/auth?state=mock';holdOAuth=true;
  const oauthReached=new Promise(resolve=>{notifyOAuth=resolve;});
  await page.locator('#yt-connect').click();await oauthReached;
  await page.evaluate(()=>window.vimaxYouTube.onSession(null));
  const lateResponse=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/cloud/youtube/oauth/start');
  releaseOAuth();await lateResponse;await page.waitForTimeout(100);
  assert.ok(page.url().startsWith(skills));assert.equal(await page.locator('#yt-connect').isDisabled(),true);
  holdOAuth=false;await page.evaluate(id=>window.vimaxYouTube.onSession({id}),alice);
  await page.waitForFunction(()=>!document.getElementById('yt-connect').disabled);
  let navigatedToGoogle='';
  await page.route('https://accounts.google.com/**',route=>{navigatedToGoogle=route.request().url();return route.fulfill({status:200,body:'Mock consent page'});});
  await page.locator('#yt-connect').click();await page.waitForURL('https://accounts.google.com/**');
  assert.equal(new URL(navigatedToGoogle).pathname,'/o/oauth2/v2/auth');
  assert.equal(posts.filter(x=>x==='/api/cloud/youtube/oauth/start').length,3);
  // Local-only mode should not advertise a cloud-only YouTube action.
  localOnly=true;await page.goto(`${skills}#youtube`,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.getElementById('connection').textContent==='Local companion connected');
  assert.equal(await page.locator('#youtube').isHidden(),true);assert.equal(await page.locator('#youtube-link').isHidden(),true);
  // The additive ViMax sidebar item reaches the same deep link even when the
  // original video agent is unavailable.
  localOnly=false;signedIn=false;youtubeConfigured=false;await page.setViewportSize({width:1280,height:1000});
  await page.goto(`http://127.0.0.1:${server.address().port}/`,{waitUntil:'domcontentloaded'});
  await page.getByRole('button',{name:'Connect YouTube'}).click();
  await page.waitForURL(`${skills}#youtube`);await page.waitForSelector('#youtube:not([hidden])');
  assert.equal(await page.locator('#yt-connect').isVisible(),true);
  await page.setViewportSize({width:390,height:844});
  await page.goto(`http://127.0.0.1:${server.address().port}/`,{waitUntil:'domcontentloaded'});
  await page.getByRole('button',{name:'Open navigation'}).click();
  await page.getByRole('button',{name:'Connect YouTube'}).click();
  await page.waitForURL(`${skills}#youtube`);await page.waitForSelector('#youtube:not([hidden])');
  assert.equal(await page.locator('#yt-connect').isVisible(),true);
  assert.deepEqual(errors,[]);
  console.log('Browser smoke passed with mocked APIs: channel discovery, OAuth navigation, logout privacy, YouTube uploads, social, public GitHub, chat and mobile layout.');
 }finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1});
