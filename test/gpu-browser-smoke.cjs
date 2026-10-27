// Optional Chromium smoke. All APIs are mocked; no Runpod call is made.
// Build web/dist first; set VIMAX_BROWSER_PATH and VIMAX_PLAYWRIGHT_PATH.
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
  if(!process.env.VIMAX_BROWSER_PATH)throw new Error('Set VIMAX_BROWSER_PATH to Chromium.');
  browser=await chromium.launch({executablePath:process.env.VIMAX_BROWSER_PATH,args:['--no-sandbox','--disable-dev-shm-usage'],headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('dialog',dialog=>dialog.dismiss());
  const alice='aaaaaaaa-0000-4000-8000-000000000001',bob='bbbbbbbb-0000-4000-8000-000000000002',id='12345678-0000-4000-8000-000000000001';
  let current=alice,first=true;const jobs=[],keys=[];
  await page.route('**/api/**',async route=>{
   const rq=route.request(),p=new URL(rq.url()).pathname;let data={},body={};try{body=rq.postDataJSON()||{}}catch{}
   if(p==='/api/skills/system')data={local_only:false,database_connected:true,text_chat:'unconfigured',gpu_preview:'configured_unverified',ready_for_video:false,piper_installed:false,ffmpeg_installed:false,scene_detection_installed:false,voices:[],hardware:{},warnings:[]};
   else if(p==='/api/cloud/session')data={user:{id:current,email:'test@example.test'}};
   else if(p==='/api/cloud/projects')data={projects:[]};
   else if(p==='/api/cloud/providers')data={providers:[],pexels:'not_configured',allowed:false,paused:false};
   else if(p==='/api/cloud/chat/history')data={turns:[]};
   else if(p==='/api/cloud/usage')data={calls:[]};
   else if(p==='/api/cloud/mission')data={channels:[],competitors:[],jobs:[],workers:[],paused:false};
   else if(p==='/api/cloud/youtube/status')data={configured:false,allowed:false,connected:false};
   else if(p==='/api/cloud/youtube/uploads')data={uploads:[]};
   else if(p==='/api/cloud/gpu/config')data={configured:true,allowed:true,provider:'Runpod P-Video',verified:false};
   else if(p==='/api/cloud/gpu/jobs' && rq.method()==='GET')data={jobs:jobs.filter(j=>j.owner===current)};
   else if(p==='/api/cloud/gpu/jobs' && rq.method()==='POST'){
    keys.push(body.client_key);
    if(first){first=false;jobs.push({id,owner:current,prompt:body.prompt,aspect:body.aspect,status:'queued',created_at:new Date().toISOString()});return route.abort('failed');}
    data={id,status:'queued',message:'Existing request: no new GPU job was sent.'};
   }else if(p===`/api/cloud/gpu/jobs/${id}/check`){jobs[0].status='completed';data={id,status:'completed',message:'Completed.'};}
   else if(p===`/api/cloud/gpu/jobs/${id}/output`)data={id,status:'completed',url:'https://video.runpod.ai/test/output.mp4?token=capability',message:'Temporary link; save the video.'};
   else return route.fulfill({status:404,json:{error:'unexpected mock path'}});
   return route.fulfill({status:200,json:data});
  });
  await page.goto(`http://127.0.0.1:${server.address().port}/skills/`,{waitUntil:'domcontentloaded'});
  await page.waitForSelector('#gpu:not([hidden])');await page.waitForFunction(()=>!document.getElementById('gpu-submit').disabled);
  const prompt='<img src=x onerror=alert(1)> A starry sky';
  await page.locator('#gpu-prompt').fill(prompt);await page.locator('#gpu-aspect').selectOption('shorts');await page.locator('#gpu-confirm').check();await page.locator('#gpu-submit').click();
  await page.waitForFunction(()=>document.getElementById('gpu-error').textContent.includes('interrupted'));
  assert.equal(keys.length,1);await page.reload({waitUntil:'domcontentloaded'});await page.waitForFunction(()=>!document.getElementById('gpu-submit').disabled);
  assert.equal(await page.locator('#gpu-prompt').inputValue(),prompt);assert.equal(await page.locator('#gpu-aspect').inputValue(),'shorts');
  await page.locator('#gpu-confirm').check();await page.locator('#gpu-submit').click();
  await page.waitForFunction(()=>document.getElementById('gpu-notice').textContent.includes('Existing request'));
  assert.deepEqual(keys,[keys[0],keys[0]]);assert.equal(await page.locator('#gpu-history img').count(),0);
  await page.getByRole('button',{name:'Check status'}).click();await page.getByRole('button',{name:'Get temporary video link'}).click();
  await page.waitForSelector('#gpu-history a');assert.equal(await page.locator('#gpu-history a').getAttribute('href'),'https://video.runpod.ai/test/output.mp4?token=capability');
  current=bob;await page.evaluate(id=>window.vimaxGpu.onSession({id}),bob);
  assert.equal(await page.locator('#gpu-history a').count(),0);assert.equal(await page.locator('#gpu-prompt').inputValue(),'');
  await page.evaluate(()=>window.vimaxGpu.onSession(null));assert.equal(await page.locator('#gpu').isHidden(),true);
  assert.deepEqual(errors,[]);console.log('Mocked Chromium GPU smoke passed; no real provider request was sent.');
 }finally{await browser?.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1});
