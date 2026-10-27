import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {PGlite} from '@electric-sql/pglite';

test('analytics reservation is account-isolated, separately budgeted and survives account deletion',async()=>{
  const db=new PGlite();try {
    await db.exec(`create schema auth; create role anon; create role authenticated; create table auth.users(id uuid primary key);
      create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
      grant usage on schema auth to anon,authenticated;
      create table public.vimax_youtube_allowed_users(owner_id uuid primary key references auth.users(id) on delete cascade);`);
    const users=Array.from({length:6},(_,n)=>`12345678-0000-4000-8000-${String(n+1).padStart(12,'0')}`);
    for(const id of users) await db.query('insert into auth.users(id) values($1)',[id]);
    for(const id of users.slice(0,5)) await db.query('insert into public.vimax_youtube_allowed_users(owner_id) values($1)',[id]);
    await db.exec(await readFile(new URL('../supabase/migrations/202610280010_vimax_youtube_analytics.sql',import.meta.url),'utf8'));
    async function as(id,fn) {
      try {await db.exec('set role authenticated');await db.query("select set_config('request.jwt.claim.sub',$1,false)",[id]);return await fn();}
      finally {await db.exec('reset role');}
    }
    const reserve=id=>as(id,async()=>(await db.query('select public.vimax_youtube_analytics_reserve() result')).rows[0].result);
    assert.deepEqual(await reserve(users[5]),{allowed:false,reason:'not_allowed'});
    await assert.rejects(as(users[0],()=>db.query('select * from public.vimax_youtube_analytics_user_budget')),/permission denied/);
    await assert.rejects(as(users[0],()=>db.query('update public.vimax_youtube_analytics_daily_budget set attempts=0')),/permission denied/);
    for(let n=0;n<5;n++) assert.equal((await reserve(users[0])).allowed,true);
    assert.equal((await reserve(users[0])).reason,'user_daily_limit');
    for(const id of users.slice(1,4)) for(let n=0;n<5;n++) assert.equal((await reserve(id)).allowed,true);
    assert.equal((await reserve(users[4])).reason,'global_daily_limit');
    await db.query('delete from auth.users where id=$1',[users[0]]);
    assert.equal((await reserve(users[4])).reason,'global_daily_limit');
    assert.equal((await db.query('select attempts from public.vimax_youtube_analytics_daily_budget')).rows[0].attempts,20);
    assert.equal((await db.query('select count(*)::int n from public.vimax_youtube_analytics_user_budget where owner_id=$1',[users[0]])).rows[0].n,0);
    await db.exec('set role anon');
    await assert.rejects(db.query('select public.vimax_youtube_analytics_reserve()'),/permission denied/);
    await assert.rejects(db.query('select * from public.vimax_youtube_analytics_daily_budget'),/permission denied/);
    await db.exec('reset role');
  } finally {await db.close();}
});
