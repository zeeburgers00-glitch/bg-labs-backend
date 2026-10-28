import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createBridge} from '../api/bridge.mjs';
import {samplePublicChannel,youtubePublicStatus,youtubeResearchInput} from '../api/youtube-public-research.mjs';

const channelId = 'UCabcdefghijklmnopqrstuv', playlistId = 'UUabcdefghijklmnopqrstuv';
const video1 = 'abcdefghijk', video2 = '12345678901';
const env = {VIMAX_YOUTUBE_PUBLIC_RESEARCH_ENABLED:'true',YOUTUBE_PUBLIC_DATA_API_KEY:'test-private-key'};
const input = {reference:'https://www.youtube.com/@Example',confirm_quota:true};
const ok = data => Response.json(data);
const channel = () => ({id:channelId,snippet:{title:'<img src=x onerror=alert(1)>',description:'Public description',publishedAt:'2024-01-01T00:00:00Z'},
  contentDetails:{relatedPlaylists:{uploads:playlistId}},statistics:{subscriberCount:'1230',viewCount:'42500',videoCount:'12'}});
const video = (id,title='Public video') => ({id,snippet:{title,channelId,publishedAt:'2024-02-01T00:00:00Z'},contentDetails:{duration:'PT6M30S'},
  statistics:{viewCount:'250',likeCount:'4',commentCount:'2'},status:{privacyStatus:'public'}});
function youtubeFetch(overrides = {}) {
  const calls = [];
  const fetchImpl = async (url,init) => {
    const u = new URL(url); calls.push({u,init});
    assert.equal(u.origin,'https://www.googleapis.com');
    assert.equal(init.headers['x-goog-api-key'],env.YOUTUBE_PUBLIC_DATA_API_KEY);
    assert.ok(!u.href.includes(env.YOUTUBE_PUBLIC_DATA_API_KEY));
    assert.equal(init.redirect,'error');
    const path = u.pathname.split('/').pop();
    if (overrides[path]) return overrides[path](u,init);
    if (path === 'channels') return ok({items:[channel()]});
    if (path === 'playlistItems') return ok({items:[{contentDetails:{videoId:video1}},{contentDetails:{videoId:video2}}]});
    if (path === 'videos') return ok({items:[video(video2,'Second'),video(video1,'First')]});
    throw new Error('unexpected path');
  };
  return {fetchImpl,calls};
}

test('public metadata setup and strict input fail closed before any lookup', () => {
  assert.equal(youtubePublicStatus({}),'disabled');
  assert.equal(youtubePublicStatus({VIMAX_YOUTUBE_PUBLIC_RESEARCH_ENABLED:'true'}),'not_configured');
  assert.equal(youtubePublicStatus({...env,YOUTUBE_PUBLIC_DATA_API_KEY:'bad\nkey'}),'invalid_configuration');
  assert.equal(youtubePublicStatus(env),'configured_unverified');
  assert.equal(youtubeResearchInput(input).reference_kind,'handle');
  assert.equal(youtubeResearchInput({reference:`https://www.youtube.com/channel/${channelId}`,confirm_quota:true}).channel_id,channelId);
  for (const bad of [
    {...input,confirm_quota:false}, {...input,extra:1}, {reference:'https://www.youtube.com/watch?v=abcdefghijk',confirm_quota:true},
    {reference:'https://youtube.com.evil.test/@Example',confirm_quota:true},
    {reference:'https://www.youtube.com/user/Example',confirm_quota:true}, null,
  ]) assert.throws(() => youtubeResearchInput(bad), e => e.status === 422);
});

test('official fixed-host sample returns bounded public metadata in playlist order, never the key', async () => {
  const {fetchImpl,calls} = youtubeFetch();
  const result = await samplePublicChannel({env,fetchImpl,input});
  assert.equal(calls.length,3);
  assert.equal(calls[0].u.searchParams.get('forHandle'),'@Example');
  assert.equal(calls[1].u.searchParams.get('playlistId'),playlistId);
  assert.equal(calls[1].u.searchParams.get('maxResults'),'10');
  assert.equal(calls[2].u.searchParams.get('id'),`${video1},${video2}`);
  assert.deepEqual(result.videos.map(v => v.title),['First','Second']);
  assert.equal(result.videos[0].duration_iso,'PT6M30S');
  assert.equal(result.videos[0].views,250);
  assert.equal(result.channel.subscribers,1230);
  assert.equal(result.channel.title,'<img src=x onerror=alert(1)>');
  assert.match(result.notice,/No media, script, audio, visual template/);
  assert.ok(!JSON.stringify(result).includes(env.YOUTUBE_PUBLIC_DATA_API_KEY));
});

test('empty, unavailable, hidden and mismatched data are not invented or attributed to another channel', async () => {
  const {fetchImpl,calls} = youtubeFetch({
    channels:() => ok({items:[{...channel(),statistics:{hiddenSubscriberCount:true,subscriberCount:'1234',viewCount:'nope'}}]}),
    videos:() => ok({items:[video(video1),{...video(video2),snippet:{...video(video2).snippet,channelId:'UCxxxxxxxxxxxxxxxxxxxxxx'}}]}),
  });
  const result = await samplePublicChannel({env,fetchImpl,input});
  assert.equal(result.channel.subscribers,null); assert.equal(result.channel.total_views,null);
  assert.deepEqual(result.videos.map(v=>v.id),[video1]); assert.equal(result.missing_videos,1);
  assert.equal(calls.length,3);
  const empty = youtubeFetch({playlistItems:() => ok({items:[]})});
  const withoutVideos = await samplePublicChannel({env,fetchImpl:empty.fetchImpl,input});
  assert.equal(withoutVideos.videos.length,0); assert.equal(empty.calls.length,2);
  const malformed = youtubeFetch({playlistItems:() => ok({items:[{contentDetails:{videoId:'bad'}}]})});
  const withoutValidId = await samplePublicChannel({env,fetchImpl:malformed.fetchImpl,input});
  assert.equal(withoutValidId.missing_videos,1); assert.equal(malformed.calls.length,2);
  const mismatch = youtubeFetch();
  await assert.rejects(samplePublicChannel({env,fetchImpl:mismatch.fetchImpl,input:{reference:'https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx',confirm_quota:true}}),e => e.status===502);
  assert.equal(mismatch.calls.length,1);
});

test('response limits, transport errors and provider failures are sanitized with no automatic retries', async () => {
  const oversized = youtubeFetch({channels:() => new Response('x'.repeat(300_000),{status:200,headers:{'content-type':'application/json'}})});
  await assert.rejects(samplePublicChannel({env,fetchImpl:oversized.fetchImpl,input}), e => e.status===502 && !e.message.includes('test-private-key'));
  assert.equal(oversized.calls.length,1);
  // Provider response bodies, including any key or detailed error, are never forwarded.
  await assert.rejects(samplePublicChannel({env,fetchImpl:async () => new Response('test-private-key',{status:403}),input}), e => e.status===503 && !e.message.includes('test-private-key'));
  let calls=0;
  await assert.rejects(samplePublicChannel({env,input,fetchImpl:async () => { calls++; throw new Error('test-private-key'); }}),e => e.status===503 && !e.message.includes('test-private-key'));
  assert.equal(calls,1);
});

test('bridge requires session, owner access, same-origin, explicit consent and shared reservation', async () => {
  const youtube = youtubeFetch(), ledger = [];
  let allowReservation = true;
  const userId = 'aaaaaaaa-0000-4000-8000-000000000001';
  const fetchImpl = async (url,init) => {
    const u = new URL(url);
    if (u.host === 'www.googleapis.com') return youtube.fetchImpl(url,init);
    assert.equal(u.host,'example.supabase.co');
    if (u.pathname === '/auth/v1/user') return init.headers.authorization === 'Bearer alice-token' ? ok({id:userId,email:'alice@example.test'}) : new Response('{}',{status:401});
    if (u.pathname.endsWith('/vimax_reserve_ai_call')) {
      ledger.push(JSON.parse(init.body));
      return ok(allowReservation ? {allowed:true,id:'bbbbbbbb-0000-4000-8000-000000000002',finish_secret:'cccccccc-0000-4000-8000-000000000003',remaining_user:8} : {allowed:false,reason:'paused'});
    }
    if (u.pathname.endsWith('/vimax_finish_ai_call')) {ledger.push(JSON.parse(init.body)); return ok(true);}
    throw new Error('unexpected supabase call');
  };
  const bridge = createBridge({env:{...env,SUPABASE_URL:'https://example.supabase.co',SUPABASE_PUBLISHABLE_KEY:'sb_publishable_test',VIMAX_AI_ALLOWED_USER_IDS:userId},fetchImpl});
  const req = (path,{cookie='',origin='https://vimax.example',payload}={}) => new Request(`https://vimax.example${path}`,{method:payload ? 'POST':'GET',headers:{origin,...(cookie ? {cookie}:{}),...(payload ? {'content-type':'application/json'}:{})},...(payload ? {body:JSON.stringify(payload)}:{})});
  const cookie='__Host-vimax_access=alice-token';
  assert.equal((await bridge.fetch(req('/api/cloud/youtube-public/status'))).status,401);
  const status=await bridge.fetch(req('/api/cloud/youtube-public/status',{cookie}));
  assert.deepEqual(await status.json(),{state:'configured_unverified',allowed:true});
  const rewritten=await bridge.fetch(req('/api/bridge?__vimax_path=cloud/youtube-public/status',{cookie}));
  assert.equal(rewritten.status,200); assert.equal((await rewritten.json()).state,'configured_unverified');
  assert.equal((await bridge.fetch(req('/api/cloud/youtube-public/sample',{cookie,origin:'https://evil.example',payload:input}))).status,403);
  assert.equal((await bridge.fetch(req('/api/cloud/youtube-public/sample',{cookie,payload:{...input,confirm_quota:false}}))).status,422);
  const baseEnv={...env,SUPABASE_URL:'https://example.supabase.co',SUPABASE_PUBLISHABLE_KEY:'sb_publishable_test'};
  const denied=createBridge({env:baseEnv,fetchImpl});
  assert.equal((await denied.fetch(req('/api/cloud/youtube-public/sample',{cookie,payload:input}))).status,403);
  const disabled=createBridge({env:{...baseEnv,VIMAX_YOUTUBE_PUBLIC_RESEARCH_ENABLED:'false',VIMAX_AI_ALLOWED_USER_IDS:userId},fetchImpl});
  assert.equal((await disabled.fetch(req('/api/cloud/youtube-public/sample',{cookie,payload:input}))).status,503);
  assert.equal(ledger.length,0); assert.equal(youtube.calls.length,0);
  allowReservation=false;
  assert.equal((await bridge.fetch(req('/api/cloud/youtube-public/sample',{cookie,payload:input}))).status,409);
  assert.equal(youtube.calls.length,0);
  allowReservation=true;
  const response=await bridge.fetch(req('/api/cloud/youtube-public/sample',{cookie,payload:input}));
  assert.equal(response.status,200);
  const result=await response.json(); assert.equal(result.audit_saved,true); assert.equal(result.sample.videos.length,2);
  assert.deepEqual(ledger.at(-2),{p_feature:'stock_search',p_provider:'youtube',p_model:''});
  assert.equal(ledger.at(-1).p_status,'succeeded'); assert.equal(youtube.calls.length,3);
  assert.ok(!JSON.stringify(result).includes('test-private-key'));
  youtube.fetchImpl=async () => new Response('test-private-key',{status:403});
  const rejected=await bridge.fetch(req('/api/cloud/youtube-public/sample',{cookie,payload:input}));
  assert.equal(rejected.status,503); assert.equal(ledger.at(-1).p_status,'failed');
  assert.ok(!(await rejected.text()).includes('test-private-key'));
});
