import {test} from 'node:test';
import assert from 'node:assert/strict';
import {youtubeReference, funnelReview, ideaReview, hookReview, titleReview} from '../api/creator-skills.mjs';
import {creatorReview, runHostedSkill} from '../api/workforce-skills.mjs';
import {createBridge} from '../api/bridge.mjs';

const id = 'dQw4w9WgXcQ';
const invalid = fn => assert.throws(fn, error => error.status === 422);

test('strict hosted YouTube reference parser canonicalizes without fetching or claiming verification', () => {
  const valid = [
    [id,'video',`https://www.youtube.com/watch?v=${id}`],
    [`https://youtu.be/${id}?t=3`,'video',`https://www.youtube.com/watch?v=${id}`],
    [`https://youtube.com/watch?list=x&v=${id}`,'video',`https://www.youtube.com/watch?v=${id}`],
    [`https://m.youtube.com/shorts/${id}`,'shorts',`https://www.youtube.com/watch?v=${id}`],
    [`https://youtube.com/embed/${id}`,'video',`https://www.youtube.com/watch?v=${id}`],
    ['https://youtube.com/@some.handle','handle','https://www.youtube.com/@some.handle'],
    ['https://youtube.com/channel/UCabcdefghijklmnopqrstuv','channel','https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv'],
    ['https://youtube.com/user/SomeUser','user','https://www.youtube.com/user/SomeUser'],
    ['https://youtube.com/c/SomeCreator','c','https://www.youtube.com/c/SomeCreator'],
  ];
  for (const [reference, kind, canonical] of valid) {
    const result = youtubeReference({reference});
    assert.equal(result.reference_kind,kind); assert.equal(result.canonical_url,canonical);
    assert.equal(result.is_short,kind === 'shorts'); assert.match(result.notice,/does not fetch/);
  }
  for (const reference of ['', ' ', `${id}junk`, `https://youtube.com.evil.example/watch?v=${id}`,
    `https://evil.example/youtube.com/watch?v=${id}`, `https://youtube.com@evil.example/watch?v=${id}`,
    `https://evil.example@youtube.com/watch?v=${id}`, `https://youtube.com:443/watch?v=${id}`,
    `http://youtube.com/watch?v=${id}`, `https://youtube.com/watch?v=${id}extra`,
    `https://youtube.com/watch?v=${id}&v=${id}`, `https://youtu.be/${id}/other`,
    `https://youtube.com/%73horts/${id}`, `https://youtube.com//watch?v=${id}`,
    `https://youtube.com/foo/../watch?v=${id}`, `https://youtube.com/watch?v=${id}\n`,
    'https://youtube.com/@bad%2Fhandle','https://youtube.com/channel/UCbad','https://youtube.com/user/Some.User',3,null]) {
    invalid(() => youtubeReference({reference}));
  }
  invalid(() => youtubeReference({reference:id, extra:true}));
});

test('hosted funnel keeps supplied figures, estimates and Shorts context separate', () => {
  const result = funnelReview({format:'long',metrics:{impressions:4000,ctr:2,avd_seconds:40,length_seconds:100,views:90}});
  assert.equal(result.status,'review'); assert.equal(result.binding_constraint,'CTR');
  assert.equal(result.views,90); assert.equal(result.estimated_views_from_impressions,80);
  assert.ok(result.warnings.some(w => /not total video views/.test(w))); assert.match(result.notice,/no YouTube data was fetched/);
  assert.equal(funnelReview({metrics:{views:0}}).status,'insufficient_data');
  const shorts = funnelReview({format:'shorts',metrics:{impressions:10000,ctr:10,views:25,avd_seconds:34,length_seconds:30}});
  assert.equal(shorts.status,'shorts_requires_context'); assert.equal(shorts.binding_constraint,null);
  assert.equal(shorts.estimated_views_from_impressions,null); assert.equal(shorts.views_est,25);
  assert.ok(shorts.avg_pct_viewed > 100); assert.ok(shorts.warnings.some(w => /ignored for Shorts/.test(w)));
  assert.ok(shorts.context_required.includes('engaged_views'));
  for (const payload of [{}, {metrics:{}}, {format:'other',metrics:{views:1}}, {metrics:{views:true}},
    {metrics:{views:1.5}}, {metrics:{views:-1}}, {metrics:{views:NaN}}, {metrics:{views:Infinity}},
    {metrics:{ctr:101}}, {metrics:{length_seconds:0}}, {metrics:{avd_seconds:86401}},
    {metrics:{unknown:1}}, {metrics:{views:1},ignored:true}]) invalid(() => funnelReview(payload));
});

test('English-only idea, hook and title heuristics produce pinned local examples without performance claims', () => {
  const idea = ideaReview({idea:'How to grow 5 herbs at home'});
  const hook = hookReview({hook:'Why do your seedlings die after only seven days?'});
  const title = titleReview({title:'5 ways to start a garden',thumbnail:'FIRST SEEDS'});
  assert.equal(idea.score,51); assert.equal(idea.axes.SEARCH,46);
  assert.equal(hook.score,52); assert.equal(hook.formula,'The Question');
  assert.equal(title.score,100); assert.deepEqual(title.issues,[]);
  for (const result of [idea,hook,title]) assert.match(result.notice,/not research, analytics, or a prediction/);
  assert.ok(titleReview({title:'5 ways to start a garden',thumbnail:'GARDEN'}).issues.some(([code])=>code === 'duplicate'));
  invalid(() => ideaReview({idea:'   '})); invalid(() => hookReview({hook:'x'.repeat(401)}));
  invalid(() => titleReview({title:'x\u0000y'})); invalid(() => titleReview({title:'ok', thumbnail:4}));
  invalid(() => ideaReview({idea:'ok',unknown:true}));
});

test('creator review runs a fixed, no-network sequence on supplied input and never approves or uploads', () => {
  const data = {metadata:{title:'5 ways to start a garden'},thumbnail:'FIRST SEEDS',reference:`https://youtu.be/${id}`,
    idea:'How to grow 5 herbs at home',hook:'Why do your seedlings die after only seven days?',funnel:{metrics:{views:5}}};
  const result = creatorReview(data);
  assert.equal(result.status,'review_ready');
  assert.deepEqual(result.steps.map(s=>s.skill),['metadata_preflight','title_lint','youtube_url_parser','idea_heuristic','hook_heuristic','funnel_heuristic']);
  assert.match(result.notice,/No competitor or channel was fetched/); assert.match(result.notice,/nothing was saved or uploaded/);
  assert.deepEqual(runHostedSkill('creator_review',data),result);
  invalid(() => creatorReview({...data,unknown:1}));
  assert.throws(() => runHostedSkill('https://example.invalid',{}), error => error.status === 404);
});

test('creator review HTTP endpoint requires session and same origin and contacts only simulated Supabase auth', async () => {
  const calls=[];
  const bridge=createBridge({env:{SUPABASE_URL:'https://example.supabase.co',SUPABASE_PUBLISHABLE_KEY:'sb_publishable_test_key'},
    fetchImpl:async url=>{calls.push(String(url)); return Response.json({id:'aaaaaaaa-0000-4000-8000-000000000001',email:'alice@example.test'});}});
  const req=(cookie='',origin='https://vimax.example',input={metadata:{title:'Original draft'},reference:`https://youtu.be/${id}`})=>new Request('https://vimax.example/api/cloud/skills/run',{
    method:'POST',headers:{origin,'content-type':'application/json',...(cookie?{cookie}:{})},body:JSON.stringify({skill:'creator_review',input})});
  assert.equal((await bridge.fetch(req())).status,401);
  const cookie='__Host-vimax_access=alice-token';
  assert.equal((await bridge.fetch(req(cookie,'https://evil.example'))).status,403);
  const response=await bridge.fetch(req(cookie)); assert.equal(response.status,200); assert.equal(response.headers.get('cache-control'),'no-store');
  const value=await response.json(); assert.equal(value.result.steps[2].result.video_id,id);
  assert.ok(calls.length && calls.every(url=>new URL(url).host==='example.supabase.co' && new URL(url).pathname==='/auth/v1/user'));
});
