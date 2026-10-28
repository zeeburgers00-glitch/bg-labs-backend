import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createBridge} from '../api/bridge.mjs';
import {metadataPreflight, runHostedSkill, workforceRegistry} from '../api/workforce-skills.mjs';

const requested = [
  'darkzogx/youtube-automation-agent','gyoridavid/short-video-maker','adityaarsharma/youtube-marketing-skills',
  'ahmedsakri/youtube-agent-pro','salimzaks/youtube-content-creation-agent','sergebulaev/youtube-skills',
  'realjaymes/marketingagentskills','calesthio/openmontage','krillinai/opencreator','vincentwei1021/video-shotcraft',
  'ffmpeg/ffmpeg','comfyanonymous/comfyui','hexgrad/kokoro','systran/faster-whisper','googleapis/google-api-nodejs-client',
];

test('registry covers each pinned requested source and is descriptive, not an execution grant', () => {
  const registry = workforceRegistry();
  for (const name of requested) {
    const source = registry.repositories.find(repo => repo.name.toLowerCase() === name);
    assert.ok(source, name); assert.match(source.revision, /^[0-9a-f]{40}$/);
    assert.ok(source.license && source.installation && source.decision && source.source_inspected.length);
    const skill = registry.skills.find(entry => entry.repository.toLowerCase() === source.url.toLowerCase());
    assert.ok(skill, name); assert.equal(skill.revision, source.revision); assert.equal(skill.license, source.license);
  }
  assert.match(registry.workforce_notice, /not running agents/);
  assert.equal(registry.workforce_plan.status, 'proposed_only');
  assert.equal(registry.workforce_plan.roles.reduce((sum, item) => sum + item.proposed_slots, 0), 120);
  const roles = new Set(registry.workforce_plan.roles.map(item => item.role));
  assert.equal(roles.size, registry.workforce_plan.roles.length);
  assert.ok(registry.skills.every(skill => skill.agent_assignments.every(role => roles.has(role))));
  assert.equal(registry.skills.filter(skill => skill.setup_status === 'integrated_hosted').length, 6);
  assert.ok(registry.skills.every(skill => skill.agent_assignments.length && Array.isArray(skill.required_credentials)
    && Array.isArray(skill.tool_permissions) && skill.test_results.scope));
  registry.skills.length = 0;
  assert.ok(workforceRegistry().skills.length > 0, 'caller cannot mutate module state');
});

test('metadata preflight discloses normalization; it does not publish or silently approve a draft', () => {
  const result = metadataPreflight({title:'  A title  ', description:'First line\nSecond line',
    tags:'herbs, HERBS, gardening', categoryId:'22', defaultLanguage:'ur-PK'});
  assert.equal(result.valid, true);
  assert.equal(result.preview.title, 'A title');
  assert.equal(result.preview.description, 'First lineSecond line');
  assert.deepEqual(result.preview.tags, ['herbs','gardening']);
  assert.equal(result.preview.defaultAudioLanguage, 'ur-PK');
  assert.equal(result.changes.length, 3);
  assert.match(result.notice, /Nothing was saved, sent to YouTube or published/);
  assert.ok(result.warnings.length);
});

test('strict wrapper rejects invalid fields before the upstream truncation logic', () => {
  const reject = input => assert.throws(() => metadataPreflight(input), error => error.status === 422);
  reject({title:'x'.repeat(101)});
  reject({title:'Good', description:'x'.repeat(5001)});
  reject({title:'Good', description:'💡'.repeat(1251)}); // utf8 byte limit, not only JS length
  reject({title:'  '});
  reject({title:'Good', tags:new Array(32).fill('x').join(',')});
  reject({title:'Good', tags:'x'.repeat(101)});
  reject({title:'<img>'});
  reject({title:'Good', description:'bad\u0000value'});
  reject({title:'Good', categoryId:'1e2'});
  reject({title:'Good', defaultLanguage:'../en'});
  reject({title:'Good', extra:true});
  reject(null);
  assert.equal(metadataPreflight({title:'x'.repeat(100), description:'x'.repeat(5000)}).preview.description.length, 5000);
  assert.throws(() => runHostedSkill('youtube_url_parser', {}), error => error.status === 422);
  assert.throws(() => runHostedSkill('../../anything', {}), error => error.status === 404);
});

test('hosted routes require an authenticated session, same-origin POST and only the fixed skill', async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push(new URL(url).pathname);
    assert.equal(new URL(url).host, 'example.supabase.co', 'no third-party inference or YouTube calls');
    if (new URL(url).pathname === '/auth/v1/user' && init.headers.authorization === 'Bearer alice-token') {
      return Response.json({id:'aaaaaaaa-0000-4000-8000-000000000001',email:'alice@example.test'});
    }
    return Response.json({}, {status:401});
  };
  const bridge = createBridge({env:{SUPABASE_URL:'https://example.supabase.co',SUPABASE_PUBLISHABLE_KEY:'sb_publishable_test_key'},fetchImpl});
  const req = (path, {method='GET',cookie='',origin='https://vimax.example',payload} = {}) => new Request(`https://vimax.example${path}`, {
    method, headers:{...(cookie ? {cookie} : {}), ...(origin ? {origin} : {}), ...(payload === undefined ? {} : {'content-type':'application/json'})},
    ...(payload === undefined ? {} : {body:JSON.stringify(payload)}),
  });
  assert.equal((await bridge.fetch(req('/api/cloud/skills/registry'))).status, 401);
  const cookie = '__Host-vimax_access=alice-token';
  const registry = await bridge.fetch(req('/api/cloud/skills/registry', {cookie}));
  assert.equal(registry.status, 200); assert.equal(registry.headers.get('cache-control'), 'no-store');
  assert.ok((await registry.json()).skills.find(skill => skill.id === 'metadata_preflight'));
  let response = await bridge.fetch(req('/api/cloud/skills/run', {cookie, method:'POST', origin:'https://evil.example',
    payload:{skill:'metadata_preflight',input:{title:'Valid'}}}));
  assert.equal(response.status,403);
  response = await bridge.fetch(req('/api/cloud/skills/run', {cookie, method:'POST',payload:{skill:'metadata_preflight',input:{title:'Valid'}}}));
  assert.equal(response.status,200); assert.equal((await response.json()).result.preview.title,'Valid');
  response = await bridge.fetch(req('/api/cloud/skills/run', {cookie, method:'POST',payload:{skill:'funnel_heuristic',input:{}}}));
  assert.equal(response.status,422);
  response = await bridge.fetch(req('/api/cloud/skills/run', {cookie, method:'POST',payload:{skill:'metadata_preflight',input:{title:'x'.repeat(101)}}}));
  assert.equal(response.status,422);
  response = await bridge.fetch(req('/api/cloud/skills/run', {cookie, method:'POST',payload:{skill:'metadata_preflight',input:{title:'ok'},extra:1}}));
  assert.equal(response.status,422);
  assert.ok(calls.every(path => path === '/auth/v1/user'));
});
