import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {patchApi, patchApp, patchSessionWarning} from '../scripts/apply-overlay.mjs';
import {secureUpstream} from '../scripts/secure-upstream.mjs';
import bridge from '../api/bridge.mjs';

const apiFixture = `export async function one(response) { return await response.json(); }
export async function two(response) { return await response.json(); }
export async function three(response) { return await response.json(); }`;

test('non-JSON and invalid JSON become actionable errors, not SyntaxError', async () => {
  const typescript = patchApi(apiFixture);
  const javascript = typescript.replace(': Response', '').replace(': Promise<any>', '');
  const mod = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString('base64')}`);
  assert.deepEqual(await mod.one(new Response('{"value":3}', {headers:{'Content-Type':'application/json'}})), {value:3});
  assert.deepEqual(await mod.two(new Response('{"error":"not ready"}', {status:503,headers:{'Content-Type':'application/json'}})), {error:'not ready'});
  await assert.rejects(mod.one(new Response('The page could not be found', {status:404,headers:{'Content-Type':'text/html'}})), /non-JSON response \(HTTP 404\).*backend is connected/);
  await assert.rejects(mod.one(new Response('{bad', {headers:{'Content-Type':'application/json'}})), /invalid JSON/);
  await assert.rejects(mod.one(new Response('<html>', {status:200,headers:{'Content-Type':'text/html'}})), /non-JSON response \(HTTP 200\)/);
});

test('overlay refuses unexpected upstream changes', () => {
  assert.throws(() => patchApi('await response.json()'), /expected 3/);
  assert.throws(() => patchApp('unrelated'), /did not match/);
});

test('skills navigation is additive', () => {
  const source = `import {\n  Film,\n} from 'lucide-react';\n  onDelete: (session: SessionSummary) => void;\n}) {\n  return (\n          <button className={activeView === 'settings' ? 'is-active' : ''} onClick={onSettings}><Settings size={17} /><span>Settings</span></button>`;
  const patched = patchApp(source);
  assert.match(patched, /Skills &amp; Agents/);
  assert.match(patched, /Connect YouTube/);
  assert.match(patched, /\/skills\/#youtube/);
  assert.match(patched, /<Youtube size=\{17\}/);
  assert.match(patched, /isCloudMode && <button/);
  assert.match(patched, /system\?\.local_only === false/);
  assert.match(patched, /onClick=\{onSettings\}/);
  assert.throws(() => patchApp(source.replace('onDelete:', 'deleteSession:')), /did not match/);
});

test('temporary upstream wrapper requires the local random token', () => {
  const fixture = `import {createServer} from 'node:http';\nimport x from './config-store.mjs';\nimport y from './server-lib.mjs';\nconst repoRoot = path.resolve(webRoot, '..');\nconst server = createServer(async (request, response) => {});`;
  const patched = secureUpstream(fixture, '/tmp/vimax/web');
  assert.match(patched, /timingSafeEqual/);
  assert.match(patched, /x-vimax-local-token/);
  assert.match(patched, /VIMAX_SOURCE_ROOT/);
  assert.throws(() => secureUpstream('unexpected', '/tmp/web'), /Unexpected ViMax/);
});

test('unavailable public agent returns JSON instead of exposing local server', async () => {
  const response = await bridge.fetch(new Request('https://example.test/api/config'));
  assert.equal(response.status, 503);
  assert.match(response.headers.get('content-type'), /application\/json/);
  assert.match((await response.json()).error, /not connected/);
});

test('the optional cloud warning is surfaced without changing local sessions', () => {
  const type = 'activeSessionId: string; sessions: SessionSummary[]';
  const result = patchSessionWarning(`${type}\n${type}`, '    const state = await getSessions();\n    setSessions(state.sessions);');
  assert.match(result.api, /warning\?: string/);
  assert.match(result.app, /if \(state.warning\) setLoadError\(state.warning\)/);
  assert.throws(() => patchSessionWarning('bad', 'bad'), /did not match/);
});

test('Vercel web entry injects request-scoped OIDC into the canonical bridge', async () => {
  const source = await readFile(new URL('../web/api/bridge.mjs', import.meta.url), 'utf8');
  assert.match(source, /import \{getVercelOidcTokenSync\} from '@vercel\/oidc'/);
  assert.match(source, /import \{createBridge\} from '\.\.\/\.\.\/api\/bridge\.mjs'/);
  assert.match(source, /createBridge\(\{getGatewayToken:getVercelOidcTokenSync\}\)/);
});
