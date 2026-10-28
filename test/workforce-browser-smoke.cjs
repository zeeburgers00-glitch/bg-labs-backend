// Browser-to-real-adapter smoke. Supabase session/account and unrelated APIs
// are fake; no provider, YouTube or paid service is contacted. Build web/dist
// first and set VIMAX_BROWSER_PATH and VIMAX_PLAYWRIGHT_PATH.
const http = require('node:http'), fs = require('node:fs/promises'), path = require('node:path'), assert = require('node:assert/strict');
const {chromium} = require(process.env.VIMAX_PLAYWRIGHT_PATH || 'playwright-core');
(async () => {
  const {createBridge} = await import('../api/bridge.mjs');
  const sourceRoot = path.resolve('web/dist');
  const server = http.createServer(async (req, res) => {
    try {
      let pathname = decodeURIComponent(new URL(req.url, 'http://local').pathname);
      if (pathname.endsWith('/')) pathname += 'index.html';
      const file = path.resolve(sourceRoot, '.' + pathname);
      if (!file.startsWith(sourceRoot + path.sep)) return res.writeHead(403).end();
      const types = {'.html':'text/html','.js':'application/javascript','.css':'text/css','.json':'application/json'};
      res.writeHead(200, {'content-type':types[path.extname(file)] || 'application/octet-stream'}).end(await fs.readFile(file));
    } catch { res.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    const authCalls = [];
    const bridge = createBridge({env:{SUPABASE_URL:'https://example.supabase.co',SUPABASE_PUBLISHABLE_KEY:'sb_publishable_browser_test'},
      fetchImpl:async (url, init) => {
        authCalls.push(new URL(url).pathname);
        assert.equal(new URL(url).pathname, '/auth/v1/user', 'No provider or YouTube network calls');
        return Response.json({id:'aaaaaaaa-0000-4000-8000-000000000001',email:'alice@example.test'});
      }});
    browser = await chromium.launch({executablePath:process.env.VIMAX_BROWSER_PATH,args:['--no-sandbox','--disable-dev-shm-usage'],headless:true});
    const page = await browser.newPage({viewport:{width:320,height:720}}), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    let signedIn = true, skillPosts = 0;
    await page.route('**/api/**', async route => {
      const request = route.request(), url = new URL(request.url()), pathname = url.pathname;
      if (pathname === '/api/cloud/skills/registry' || pathname === '/api/cloud/skills/run') {
        if (pathname.endsWith('/run')) skillPosts++;
        const headers = {cookie:'__Host-vimax_access=browser-token',origin:'https://vimax.example'};
        const init = {method:request.method(),headers};
        if (request.method() !== 'GET') { headers['content-type'] = 'application/json'; init.body = request.postData(); }
        const response = await bridge.fetch(new Request(`https://vimax.example${pathname}`, init));
        return route.fulfill({status:response.status,contentType:'application/json',body:await response.text()});
      }
      let value = {};
      if (pathname === '/api/health') value = {ok:true,text_chat:'unconfigured',youtube_upload:'unavailable'};
      else if (pathname === '/api/cloud/google/status') value = {enabled:false};
      else if (pathname === '/api/cloud/session') value = {user:signedIn ? {id:'aaaaaaaa-0000-4000-8000-000000000001',email:'alice@example.test'} : null};
      else if (pathname === '/api/cloud/logout') { signedIn = false; value = {ok:true}; }
      else if (pathname === '/api/cloud/providers') value = {providers:[],allowed:true,paused:false};
      else if (pathname === '/api/cloud/chat/history') value = {turns:[]};
      else if (pathname === '/api/cloud/youtube/status') value = {configured:false,allowed:false,saved_channels:[]};
      else if (pathname === '/api/cloud/social/status') value = {providers:{facebook:{configured:false,allowed:false}},connections:[]};
      return route.fulfill({status:200,json:value});
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/`, {waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => !document.getElementById('workforce-open').hidden);
    await page.locator('#workforce-open').click();
    await page.waitForFunction(() => document.querySelectorAll('#registry-list details').length >= 19);
    assert.match(await page.locator('#registry-status').textContent(), /Assignments do not start agents/);
    assert.match(await page.locator('#workforce-dialog').innerText(), /not 120 running agents/);
    await page.locator('.role-plan summary').click();
    assert.equal(await page.locator('#role-plan-list li').count(), 17);
    assert.match(await page.locator('#role-plan-list').innerText(), /proposed slots/);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'no mobile page overflow');
    assert.ok(await page.locator('#workforce-dialog').evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'no mobile dialog overflow');
    await page.locator('#preflight-title-input').fill('My useful title');
    await page.locator('#preflight-description').fill('First line\nSecond line');
    await page.locator('#preflight-tags').fill('one, ONE, two');
    await page.locator('#preflight-submit').click();
    await page.waitForFunction(() => !document.getElementById('preflight-result').hidden);
    assert.match(await page.locator('#preflight-status').textContent(), /Preview ready/);
    assert.match(await page.locator('#preflight-preview').textContent(), /First lineSecond line/);
    assert.match(await page.locator('#preflight-notes').textContent(), /line breaks/);
    assert.match(await page.locator('#preflight-notice').textContent(), /Nothing was saved, sent to YouTube or published/);
    assert.equal(await page.locator('#preflight-result img').count(), 0);
    assert.equal(skillPosts, 1);
    assert.ok(authCalls.every(call => call === '/auth/v1/user'));
    await page.locator('[data-close=workforce-dialog]').click();
    await page.locator('#account-button').click();
    await page.locator('#logout').click();
    await page.waitForFunction(() => document.getElementById('workforce-open').hidden);
    assert.equal(await page.locator('#preflight-title-input').inputValue(), '');
    assert.equal(await page.locator('#preflight-preview').textContent(), '');
    assert.equal(await page.locator('#registry-list details').count(), 0);
    assert.deepEqual(errors, []);
    console.log('Creator tools browser smoke passed: real local adapters, mocked auth, mobile, preview and sign-out cleanup.');
  } finally { if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
