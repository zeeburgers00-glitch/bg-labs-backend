import {test} from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID, randomBytes} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import pg from 'pg';

// Opt-in only: creates and removes an empty throwaway database in the isolated
// *local* test cluster. It refuses TCP, a production data directory, another
// user/port, or any existing application roles. Never point it at Supabase.
const enabled=process.env.VIMAX_TEST_PG_SOCKET === '/tmp/vimax-pgconcurrency/socket';
test('real PostgreSQL 17 concurrent queue claims and provider budgets', {skip:!enabled,timeout:120_000}, async t => {
  const config={host:'/tmp/vimax-pgconcurrency/socket',port:55432,user:'vimax_test',database:'postgres',ssl:false};
  const admin=new pg.Client(config); let pool,createdDb=false,createdRoles=false;
  const name=`vimax_isolated_${randomBytes(6).toString('hex')}`;
  await admin.connect();
  try {
    const safety=(await admin.query("select current_user as usr,inet_server_addr() as addr,current_setting('data_directory') as dir,current_setting('server_version_num')::int as version")).rows[0];
    assert.equal(safety.usr,'vimax_test'); assert.equal(safety.addr,null);
    assert.equal(safety.dir,'/tmp/vimax-pgconcurrency/data'); assert.ok(safety.version>=170000 && safety.version<180000);
    const existing=await admin.query("select rolname from pg_roles where rolname in ('anon','authenticated')");
    assert.equal(existing.rowCount,0,'test cluster must not contain application roles');
    await admin.query('create role anon; create role authenticated;'); createdRoles=true;
    await admin.query(`create database ${name}`); createdDb=true;
    pool=new pg.Pool({...config,database:name,max:24});
    await pool.query(`create schema auth; create table auth.users(id uuid primary key);
      create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
      grant usage on schema auth to anon,authenticated;`);
    const users=Array.from({length:12},(_,n)=>`12345678-0000-4000-8000-${String(n+1).padStart(12,'0')}`);
    for(const id of users) await pool.query('insert into auth.users(id) values($1)',[id]);
    for(const file of ['202610270001_vimax_projects.sql','202610270002_vimax_cloud_ai.sql','202610270003_vimax_ai_finish_token.sql','202610270004_vimax_mission_queue.sql']) {
      await pool.query(await readFile(new URL(`../supabase/migrations/${file}`,import.meta.url),'utf8'));
    }
    async function as(id,action) {
      const client=await pool.connect();
      try { await client.query('set role authenticated'); await client.query("select set_config('request.jwt.claim.sub',$1,false)",[id]); return await action(client); }
      finally { try{await client.query('reset role')}finally{client.release()} }
    }
    const rpc=(id,name,...args)=>as(id,async c=>(await c.query(`select public.${name}(${args.map((_,i)=>`$${i+1}`).join(',')}) as result`,args)).rows[0].result);
    const channel=id=>as(id,async c=>(await c.query("insert into public.vimax_channels(name,niche) values($1,'Science') returning id",[`Profile ${randomUUID()}`])).rows[0].id);
    const submit=(id,ch,key=randomUUID())=>rpc(id,'vimax_mission_submit',ch,key,'Original space topic','groq','llama-3.1-8b-instant',null);
    const worker=async id=>{const w=randomUUID();assert.equal(await rpc(id,'vimax_mission_heartbeat',w),true);return w;};
    await t.test('parallel submissions with one idempotency key produce exactly one job',async()=>{
      const ch=await channel(users[0]), key=randomUUID();
      const results=await Promise.all(Array.from({length:24},()=>submit(users[0],ch,key)));
      assert.equal(new Set(results.map(result=>result.id)).size,1);
      assert.equal(results.filter(result=>result.existing===false).length,1);
      assert.equal((await pool.query('select count(*)::int as n from public.vimax_mission_jobs where owner_id=$1',[users[0]])).rows[0].n,1);
    });
    await t.test('parallel workers cannot claim the same job or more than one per profile',async()=>{
      const id=users[1], a=await channel(id),b=await channel(id);
      for(let n=0;n<4;n++){await submit(id,a);await submit(id,b);}
      const workers=await Promise.all(Array.from({length:5},()=>worker(id)));
      const results=(await Promise.all(workers.map(w=>rpc(id,'vimax_mission_claim',w)))).filter(Boolean);
      assert.equal(results.length,2); assert.equal(new Set(results.map(x=>x.id)).size,2);
      const rows=(await pool.query("select channel_id,count(*)::int as n from public.vimax_mission_jobs where owner_id=$1 and status='running' group by channel_id",[id])).rows;
      assert.deepEqual(rows.map(row=>row.n).sort(),[1,1]);
    });
    await t.test('per-account claim cap and one in-flight provider call hold across connections',async()=>{
      const id=users[2]; for(let n=0;n<5;n++) await submit(id,await channel(id));
      const workers=await Promise.all(Array.from({length:5},()=>worker(id)));
      const claims=(await Promise.all(workers.map(w=>rpc(id,'vimax_mission_claim',w)))).filter(Boolean);
      assert.equal(claims.length,3); assert.equal(new Set(claims.map(x=>x.id)).size,3);
      const starts=await Promise.all(claims.map(x=>rpc(id,'vimax_mission_begin',x.id,x.lease,'ideas')));
      assert.equal(starts.filter(x=>x.allowed===true).length,1);
      assert.deepEqual(starts.filter(x=>x.allowed===false).map(x=>x.reason).sort(),['in_flight','in_flight']);
      const audit=(await pool.query("select count(*)::int as n from public.vimax_ai_calls where owner_id=$1 and feature='job_stage'",[id])).rows[0];
      assert.equal(audit.n,1);
    });
    await t.test('global 50-attempt limit remains atomic across six users',async()=>{
      // Only this throwaway database is cleared between subtests.
      await pool.query('delete from public.vimax_ai_calls; delete from public.vimax_ai_daily_budget;');
      const totals=await Promise.all(users.slice(3,9).map(async id=>{
        let allowed=0,denied=0;
        for(let n=0;n<10;n++){
          const reservation=await rpc(id,'vimax_reserve_ai_call','job_stage','groq','llama-3.1-8b-instant');
          if(!reservation.allowed){assert.equal(reservation.reason,'global_daily_limit');denied++;continue;}
          allowed++; assert.equal(await rpc(id,'vimax_finish_ai_call',reservation.id,reservation.finish_secret,'succeeded',1,1),true);
        }
        return {allowed,denied};
      }));
      assert.equal(totals.reduce((n,x)=>n+x.allowed,0),50); assert.equal(totals.reduce((n,x)=>n+x.denied,0),10);
      assert.equal((await pool.query('select attempts from public.vimax_ai_daily_budget')).rows[0].attempts,50);
    });
  } finally {
    if(pool) await pool.end();
    if(createdDb) await admin.query(`drop database ${name}`);
    if(createdRoles) await admin.query('drop role anon; drop role authenticated;');
    await admin.end();
  }
});
