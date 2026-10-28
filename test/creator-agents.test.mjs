import {test} from 'node:test';
import assert from 'node:assert/strict';
import {creatorAgentRegistry, runCreatorAgent} from '../api/creator-agents.mjs';
import {createBridge} from '../api/bridge.mjs';

test('108 distinct role specifications cover 12 departments without presenting pending roles as running', () => {
  const registry=creatorAgentRegistry(), ids=new Set(registry.roles.map(role=>role.id));
  assert.equal(registry.departments.length,12); assert.equal(registry.roles.length,108); assert.equal(ids.size,108);
  assert.equal(registry.implemented_count,7); assert.equal(registry.planned_count,101);
  assert.match(registry.notice,/not running agents/);
  for (const department of registry.departments) assert.equal(registry.roles.filter(x=>x.department===department).length,9);
  for (const role of registry.roles) {
    assert.ok(role.responsibility && role.success_criteria && role.error_handling);
    assert.equal(role.input_schema.type,'object'); assert.equal(role.output_schema.type,'object');
    assert.ok(Array.isArray(role.input_schema.required) && role.input_schema.required.length);
    assert.ok(Array.isArray(role.output_schema.required) && role.output_schema.required.length);
    assert.ok(role.required_capabilities.length && role.dependencies.length);
    if (role.execution_status==='implemented_read_only') {
      assert.equal(role.assigned_tools.length,1); assert.equal(role.test_status,'automated_local_tests');
    } else {
      assert.equal(role.execution_status,'awaiting_integration'); assert.deepEqual(role.assigned_tools,[]);
      assert.equal(role.test_status,'not_run'); assert.match(role.error_handling,/Fail closed/);
    }
  }
  registry.roles[0].name='mutated'; assert.notEqual(creatorAgentRegistry().roles[0].name,'mutated');
});

test('seven fixed roles execute only the installed tools; planned or arbitrary roles fail closed', () => {
  assert.equal(runCreatorAgent('studio_manager',{metadata:{title:'My original video'}}).status,'review_ready');
  assert.equal(runCreatorAgent('channel_reference',{reference:'dQw4w9WgXcQ'}).video_id,'dQw4w9WgXcQ');
  assert.equal(runCreatorAgent('idea_phrasing',{idea:'How to grow 5 herbs at home'}).score,51);
  assert.equal(runCreatorAgent('hook_phrasing',{hook:'Why do your seedlings die after only seven days?'}).score,52);
  assert.equal(runCreatorAgent('title_thumbnail',{title:'5 ways to start a garden',thumbnail:'FIRST SEEDS'}).score,100);
  assert.equal(runCreatorAgent('metadata_reviewer',{title:'Original video'}).valid,true);
  assert.equal(runCreatorAgent('supplied_funnel',{metrics:{views:0}}).status,'insufficient_data');
  assert.throws(()=>runCreatorAgent('upload_initiator',{}),error=>error.status===409);
  assert.throws(()=>runCreatorAgent('../../shell',{}),error=>error.status===404);
  assert.throws(()=>runCreatorAgent('channel_reference',{reference:'https://youtube.com.evil.example'}),error=>error.status===422);
});

test('each implemented role output satisfies its published required-key schema', () => {
  const examples={studio_manager:{metadata:{title:'Original'}},channel_reference:{reference:'dQw4w9WgXcQ'},
    idea_phrasing:{idea:'How to grow herbs'},hook_phrasing:{hook:'Why grow herbs?'},title_thumbnail:{title:'A title'},
    metadata_reviewer:{title:'Original'},supplied_funnel:{format:'shorts',metrics:{views:1}}};
  const check=(schema,value,path)=>{
    if (schema.type==='object') {
      assert.ok(value && typeof value==='object' && !Array.isArray(value),path);
      for (const key of schema.required || []) assert.ok(Object.hasOwn(value,key),`${path}.${key}`);
      for (const [key,child] of Object.entries(schema.properties || {})) if (Object.hasOwn(value,key)) check(child,value[key],`${path}.${key}`);
    } else if (schema.type==='array') {
      assert.ok(Array.isArray(value),path); if (schema.items) value.forEach((item,i)=>check(schema.items,item,`${path}[${i}]`));
    } else if (schema.type==='integer') assert.ok(Number.isInteger(value),path);
    else if (schema.type) assert.equal(typeof value,schema.type,path);
    if (schema.enum) assert.ok(schema.enum.includes(value),path);
    if (schema.minimum!==undefined) assert.ok(value>=schema.minimum,path);
    if (schema.maximum!==undefined) assert.ok(value<=schema.maximum,path);
  };
  const registry=creatorAgentRegistry();
  for (const [id,input] of Object.entries(examples)) check(registry.roles.find(role=>role.id===id).output_schema,runCreatorAgent(id,input),id);
  const funnelSchema=registry.roles.find(role=>role.id==='supplied_funnel').output_schema;
  for (const metrics of [{views:1},{impressions:1000},{ctr:2},{impressions:1000,ctr:5,avd_seconds:60,length_seconds:100}]) {
    check(funnelSchema,runCreatorAgent('supplied_funnel',{metrics}),'supplied_funnel');
  }
});

test('agent endpoints require authentication and same-origin writes and cannot dispatch pending roles', async () => {
  const calls=[];
  const bridge=createBridge({env:{SUPABASE_URL:'https://example.supabase.co',SUPABASE_PUBLISHABLE_KEY:'sb_publishable_test_key'},
    fetchImpl:async url=>{calls.push(String(url));return Response.json({id:'aaaaaaaa-0000-4000-8000-000000000001',email:'alice@example.test'});}});
  const request=(path,{method='GET',cookie='',origin='https://vimax.example',payload}={})=>new Request(`https://vimax.example${path}`,{
    method,headers:{origin,...(cookie?{cookie}:{}),...(payload===undefined?{}:{'content-type':'application/json'})},
    ...(payload===undefined?{}:{body:JSON.stringify(payload)})});
  assert.equal((await bridge.fetch(request('/api/cloud/agents'))).status,401);
  const cookie='__Host-vimax_access=alice-token';
  let response=await bridge.fetch(request('/api/cloud/agents',{cookie})); assert.equal(response.status,200);
  assert.equal(response.headers.get('cache-control'),'no-store'); assert.equal((await response.json()).roles.length,108);
  const payload={agent:'channel_reference',input:{reference:'dQw4w9WgXcQ'}};
  assert.equal((await bridge.fetch(request('/api/cloud/agents/run',{cookie,method:'POST',origin:'https://evil.example',payload}))).status,403);
  response=await bridge.fetch(request('/api/cloud/agents/run',{cookie,method:'POST',payload}));
  assert.equal(response.status,200); assert.equal((await response.json()).result.video_id,'dQw4w9WgXcQ');
  response=await bridge.fetch(request('/api/cloud/agents/run',{cookie,method:'POST',payload:{agent:'upload_initiator',input:{}}}));
  assert.equal(response.status,409);
  response=await bridge.fetch(request('/api/cloud/agents/run',{cookie,method:'POST',payload:{...payload,extra:1}}));
  assert.equal(response.status,422);
  assert.ok(calls.length && calls.every(url=>new URL(url).host==='example.supabase.co' && new URL(url).pathname==='/auth/v1/user'));
});
