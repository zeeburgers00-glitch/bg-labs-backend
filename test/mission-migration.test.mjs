import {test} from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {PGlite} from '@electric-sql/pglite';

// Simulated JWTs in an isolated PostgreSQL-WASM instance. This is not a
// substitute for live Auth/PostgREST or a multi-connection race/load test.
test('mission migration isolates owners and implements real, cautious queue transitions', async t => {
  const db = new PGlite();
  const users = Array.from({length:10}, (_, n) => `12345678-0000-4000-8000-${String(n + 1).padStart(12, '0')}`);
  const role = async id => { await db.exec('reset role; set role authenticated;'); await db.query("select set_config('request.jwt.claim.sub',$1,false)", [id]); };
  const admin = async () => { await db.exec('reset role;'); };
  const rpc = async (name, ...args) => (await db.query(`select public.${name}(${args.map((_, i) => `$${i+1}`).join(',')}) as result`, args)).rows[0].result;
  const channel = async (name = 'Channel') => (await db.query("insert into public.vimax_channels(name,niche,audience,language,timezone,brand_voice,format) values($1,'Learning','Adults','en','UTC','Helpful','shorts') returning id", [name])).rows[0].id;
  const submit = async (channelId, key = randomUUID(), topic = 'Original idea') => rpc('vimax_mission_submit',channelId,key,topic,'groq','llama-3.1-8b-instant',null);
  const worker = async () => { const id=randomUUID(); assert.equal(await rpc('vimax_mission_heartbeat',id),true); return id; };
  const start = (job, stage) => rpc('vimax_mission_begin',job.id,job.lease,stage);
  const finish = (job, stage, call, text = `${stage} output`) => rpc('vimax_mission_finish',job.id,job.lease,stage,call.call_id,call.finish_secret,text,12,8);
  try {
    await db.exec(`create schema auth; create role anon; create role authenticated; create table auth.users(id uuid primary key);
      create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
      grant usage on schema auth to anon,authenticated;`);
    for (const id of users) await db.query('insert into auth.users(id) values ($1)', [id]);
    for (const file of ['202610270001_vimax_projects.sql','202610270002_vimax_cloud_ai.sql','202610270003_vimax_ai_finish_token.sql','202610270004_vimax_mission_queue.sql','202610270006_vimax_mission_openai.sql']) {
      await db.exec(await readFile(new URL(`../supabase/migrations/${file}`, import.meta.url), 'utf8'));
    }
    await t.test('profiles, competitor references, jobs and capabilities are owner-isolated', async () => {
      await db.exec('set role anon;');
      await assert.rejects(db.query('select id from public.vimax_channels'), /permission denied/);
      await assert.rejects(rpc('vimax_mission_claim',randomUUID()), /permission denied/);
      await assert.rejects(rpc('vimax_mission_submit',randomUUID(),randomUUID(),'Topic','openai','gpt-5.4-nano',null), /permission denied/);
      await role(users[0]);
      const alice = await channel('Alice');
      await db.query("insert into public.vimax_competitors(channel_id,url) values($1,'https://www.youtube.com/@example')",[alice]);
      await assert.rejects(db.query("insert into public.vimax_competitors(channel_id,url) values($1,'https://evil.example/@example')",[alice]), /check constraint/);
      const key=randomUUID(), job=await submit(alice,key);
      assert.equal(job.existing,false);
      assert.deepEqual(await submit(alice,key), {...job,existing:true});
      await assert.rejects(submit(alice,key,'Changed request'), /Idempotency key/);
      await assert.rejects(db.query('select lease_token from public.vimax_mission_jobs'), /permission denied/);
      await assert.rejects(db.query("update public.vimax_mission_jobs set status='completed'"), /permission denied/);
      await assert.rejects(db.query('select profile_snapshot from public.vimax_mission_jobs'), /permission denied/);
      const w=await worker(), claim=await rpc('vimax_mission_claim',w);
      assert.equal(claim.id,job.id); assert.deepEqual(claim.channel.competitors,['https://www.youtube.com/@example']);
      const call=await start(claim,'ideas'); assert.equal(call.allowed,true);
      await role(users[1]);
      assert.equal((await db.query('select id from public.vimax_channels')).rows.length,0);
      assert.equal((await db.query('select id from public.vimax_mission_jobs')).rows.length,0);
      assert.equal((await db.query('select id from public.vimax_mission_steps')).rows.length,0);
      await assert.rejects(db.query("insert into public.vimax_competitors(channel_id,url) values($1,'https://youtube.com/@other')",[alice]), /foreign key/);
      await assert.rejects(finish(claim,'ideas',call), /Job not found/);
      await role(users[0]);
      await assert.rejects(finish(claim,'ideas',{...call,finish_secret:randomUUID()}), /Reservation is not valid/);
      assert.equal((await finish(claim,'ideas',call)).status,'running');
      const repeat=await finish(claim,'ideas',call); assert.equal(repeat.existing,true);
      await assert.rejects(start(claim,'review'), /Unexpected stage/);
      for(const step of ['script','review']) { const c=await start(claim,step); assert.equal(c.allowed,true); await finish(claim,step,c); }
      const record=(await db.query('select status,review_reason from public.vimax_mission_jobs where id=$1',[job.id])).rows[0];
      assert.deepEqual(record,{status:'needs_review',review_reason:'plan_ready'});
      assert.equal((await db.query("select count(*)::int as n from public.vimax_ai_calls where feature='job_stage' and status='succeeded'")).rows[0].n,3);
      assert.equal((await rpc('vimax_mission_action',job.id,'approve',false)).event,'completed');
      await assert.rejects(rpc('vimax_mission_action',job.id,'approve',false), /not available/);
      assert.equal((await rpc('vimax_mission_action',job.id,'purge',false)).event,'purged');
      assert.equal((await db.query('select id from public.vimax_mission_jobs')).rows.length,0);
      await admin();
    });
    await t.test('pause prevents new work and stops after the in-flight stage without losing its result', async () => {
      await role(users[2]); const c=await channel(), first=await submit(c), second=await submit(c), w=await worker();
      const claim=await rpc('vimax_mission_claim',w); assert.equal(claim.id,first.id);
      assert.equal(await rpc('vimax_mission_claim',w),null,'per-channel concurrency');
      const call=await start(claim,'ideas'); assert.equal(call.allowed,true);
      assert.equal(await rpc('vimax_mission_pause',true),true);
      assert.equal((await finish(claim,'ideas',call)).status,'cancelled');
      assert.equal(await rpc('vimax_mission_claim',w),null);
      assert.equal((await db.query('select status from public.vimax_mission_jobs where id=$1',[second.id])).rows[0].status,'queued');
      assert.equal((await db.query("select output from public.vimax_mission_steps where job_id=$1 and stage='ideas'",[first.id])).rows[0].output,'ideas output');
      assert.equal(await rpc('vimax_mission_pause',false),false);
      assert.equal((await rpc('vimax_mission_claim',w)).id,second.id);
      await admin();
    });
    await t.test('recovery does not replay ambiguous provider calls or let stale workers write', async () => {
      await role(users[3]); const c=await channel(), job=await submit(c), w=await worker();
      const stale=await rpc('vimax_mission_claim',w); await admin();
      await db.query("update public.vimax_mission_jobs set lease_expires_at=now()-interval '1 second' where id=$1",[job.id]);
      await role(users[3]); const safe=await rpc('vimax_mission_claim',w);
      assert.equal(safe.id,job.id); assert.notEqual(safe.lease,stale.lease);
      await assert.rejects(start(stale,'ideas'), /Lease is not valid/);
      const call=await start(safe,'ideas'); assert.equal(call.allowed,true);
      await admin(); await db.query("update public.vimax_mission_jobs set lease_expires_at=now()-interval '1 second' where id=$1",[job.id]);
      await role(users[3]); assert.equal(await rpc('vimax_mission_claim',w),null);
      assert.deepEqual((await db.query('select status,review_reason from public.vimax_mission_jobs where id=$1',[job.id])).rows[0],{status:'needs_review',review_reason:'uncertain'});
      assert.equal((await db.query('select status from public.vimax_mission_steps where job_id=$1',[job.id])).rows[0].status,'uncertain');
      await assert.rejects(finish(safe,'ideas',call), /Lease is not valid/);
      await assert.rejects(rpc('vimax_mission_action',job.id,'retry',false), /duplicate provider charges/);
      assert.equal((await rpc('vimax_mission_action',job.id,'retry',true)).event,'manual_retry');
      const newClaim=await rpc('vimax_mission_claim',w);
      assert.equal((await start(newClaim,'ideas')).reason,'in_flight','an unresolved reservation cannot be reused immediately');
      await admin();
    });
    await t.test('explicit rate limits back off; ambiguous failure requires informed retry', async () => {
      await role(users[4]); const c=await channel(), job=await submit(c), w=await worker(); let claim=await rpc('vimax_mission_claim',w);
      let call=await start(claim,'ideas');
      assert.equal((await rpc('vimax_mission_fail',claim.id,claim.lease,'ideas',call.call_id,call.finish_secret,'rate_limit')).status,'queued');
      let row=(await db.query('select status,attempts,not_before>now() as delayed from public.vimax_mission_jobs where id=$1',[job.id])).rows[0];
      assert.deepEqual(row,{status:'queued',attempts:1,delayed:true});
      await admin(); await db.query('update public.vimax_mission_jobs set not_before=now() where id=$1',[job.id]); await role(users[4]);
      claim=await rpc('vimax_mission_claim',w); call=await start(claim,'ideas');
      assert.equal((await rpc('vimax_mission_fail',claim.id,claim.lease,'ideas',call.call_id,call.finish_secret,'ambiguous')).status,'needs_review');
      await assert.rejects(rpc('vimax_mission_action',job.id,'approve',false), /not available/);
      await assert.rejects(rpc('vimax_mission_action',job.id,'retry',false), /duplicate provider charges/);
      assert.equal((await rpc('vimax_mission_action',job.id,'retry',true)).event,'manual_retry');
      await admin();
    });
    await t.test('retry cannot bypass the 1,000 active-job capacity', async () => {
      await role(users[6]); const c=await channel(); await admin();
      await db.query(`insert into public.vimax_mission_jobs(owner_id,channel_id,client_key,topic,profile_snapshot,provider,model,status)
        select $1,$2,gen_random_uuid(),'capacity test','{}'::jsonb,'groq','model','queued' from generate_series(1,1000)`,[users[6],c]);
      const failed=(await db.query(`insert into public.vimax_mission_jobs(owner_id,channel_id,client_key,topic,profile_snapshot,provider,model,status)
        values($1,$2,gen_random_uuid(),'failed test','{}'::jsonb,'groq','model','failed') returning id`,[users[6],c])).rows[0].id;
      await role(users[6]); await assert.rejects(rpc('vimax_mission_action',failed,'retry',false),/capacity reached/);
      await assert.rejects(submit(c),/storage limit reached/);
      await admin(); await db.query(`update public.vimax_mission_jobs set status='cancelled' where id=(select id from public.vimax_mission_jobs where owner_id=$1 and status='queued' limit 1)`,[users[6]]);
      await role(users[6]); assert.equal((await rpc('vimax_mission_action',failed,'retry',false)).event,'manual_retry'); await admin();
    });
    await t.test('deleting an account cascades through its own mission data', async () => {
      await role(users[5]); const c=await channel(); await submit(c); await admin();
      await db.query('delete from auth.users where id=$1',[users[5]]);
      assert.equal((await db.query('select id from public.vimax_channels where owner_id=$1',[users[5]])).rows.length,0);
      assert.equal((await db.query('select id from public.vimax_mission_jobs where owner_id=$1',[users[5]])).rows.length,0);
    });
  } finally { await db.close(); }
});
