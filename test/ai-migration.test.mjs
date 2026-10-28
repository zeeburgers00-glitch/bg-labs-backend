import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {PGlite} from '@electric-sql/pglite';

// Real PostgreSQL semantics in a disposable WASM database. Auth identities are
// simulated; this does not substitute for a live Supabase Auth integration test.
test('cloud AI migration enforces RLS and atomic, durable request budgets', async t => {
  const db = new PGlite();
  const users = Array.from({length:6}, (_, n) => `12345678-0000-4000-8000-${String(n + 1).padStart(12, '0')}`);
  const role = async id => { await db.exec('reset role; set role authenticated;'); await db.query("select set_config('request.jwt.claim.sub', $1, false)", [id]); };
  const admin = async () => { await db.exec('reset role;'); };
  const reserve = async () => (await db.query("select public.vimax_reserve_ai_call('chat','groq','llama-3.1-8b-instant') as result")).rows[0].result;
  const finish = async (reservation, secret = reservation.finish_secret) => (await db.query("select public.vimax_finish_ai_call($1,$2,'succeeded',12,8) as result", [reservation.id, secret])).rows[0].result;
  try {
    await db.exec(`create schema auth; create role anon; create role authenticated;
      create table auth.users(id uuid primary key);
      create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
      grant usage on schema auth to anon, authenticated;`);
    for (const id of users) await db.query('insert into auth.users(id) values ($1)', [id]);
    await db.exec(await readFile(new URL('../supabase/migrations/202610270002_vimax_cloud_ai.sql', import.meta.url), 'utf8'));
    await db.exec(await readFile(new URL('../supabase/migrations/202610270003_vimax_ai_finish_token.sql', import.meta.url), 'utf8'));

    await t.test('anonymous health is harmless; anonymous data and budget access are denied', async () => {
      await db.exec('set role anon;');
      assert.equal((await db.query('select public.vimax_cloud_health() as ok')).rows[0].ok, true);
      await assert.rejects(db.query('select * from public.vimax_chat_turns'), /permission denied/);
      await assert.rejects(db.query('select * from public.vimax_ai_daily_budget'), /permission denied/);
      await assert.rejects(db.query("select public.vimax_reserve_ai_call('chat','groq','model')"), /permission denied/);
      await admin();
    });

    await t.test('chat history and audit rows are isolated; clients cannot mutate budgets', async () => {
      await role(users[0]);
      // The free Gateway provider/model must fit the existing live SQL checks;
      // no database migration or widened permission is needed for this route.
      await db.query("insert into public.vimax_chat_turns(prompt,reply,provider,model) values ('Alice private','hello','vercel','reflection/beam-free')");
      const aliceReservation = (await db.query("select public.vimax_reserve_ai_call('chat','vercel','reflection/beam-free') as result")).rows[0].result;
      assert.equal(aliceReservation.allowed, true);
      await assert.rejects(db.query('select completion_secret from public.vimax_ai_calls'), /permission denied/);
      await assert.rejects(db.query('select id from public.vimax_ai_calls where completion_secret=$1', [aliceReservation.finish_secret]), /permission denied/);
      assert.equal(await finish(aliceReservation, users[5]), false, 'a guessed completion capability must not release a reservation');
      assert.equal((await reserve()).reason, 'in_flight');
      await role(users[1]);
      assert.equal((await db.query('select * from public.vimax_chat_turns')).rows.length, 0);
      assert.equal((await db.query('select id,feature from public.vimax_ai_calls')).rows.length, 0);
      assert.equal(await finish(aliceReservation), false);
      await assert.rejects(db.query("insert into public.vimax_chat_turns(owner_id,prompt,reply,provider,model) values ($1,'x','x','groq','model')", [users[0]]), /permission denied/);
      await assert.rejects(db.query('delete from public.vimax_ai_calls'), /permission denied/);
      await assert.rejects(db.query('update public.vimax_ai_daily_budget set attempts=0'), /permission denied/);
      await db.query('delete from public.vimax_chat_turns');
      await role(users[0]);
      assert.equal((await db.query('select prompt from public.vimax_chat_turns')).rows[0].prompt, 'Alice private');
      assert.equal(await finish(aliceReservation), true);
      assert.equal(await finish(aliceReservation), false);
      assert.equal((await db.query('select public.vimax_set_ai_paused(true) as paused')).rows[0].paused, true);
      assert.equal((await reserve()).reason, 'paused');
      await assert.rejects(db.query('update public.vimax_ai_preferences set paused=false'), /permission denied/);
      await role(users[1]);
      assert.equal((await db.query('select paused from public.vimax_ai_preferences')).rows.length, 0);
      await role(users[0]);
      assert.equal((await db.query('select public.vimax_set_ai_paused(false) as paused')).rows[0].paused, false);
      await admin();
    });

    await t.test('in-flight, per-user and global limits survive account deletion', async () => {
      await role(users[0]);
      const pending = await reserve(); assert.equal(pending.allowed, true);
      assert.equal((await reserve()).reason, 'in_flight');
      assert.equal(await finish(pending), true);
      // The isolation test consumed one attempt and the pending call another.
      for (let i = 0; i < 8; i++) { const item = await reserve(); assert.equal(item.allowed, true); assert.equal(await finish(item), true); }
      assert.equal((await reserve()).reason, 'user_daily_limit');
      for (const id of users.slice(1, 5)) {
        await role(id);
        for (let i = 0; i < 10; i++) { const item = await reserve(); assert.equal(item.allowed, true); assert.equal(await finish(item), true); }
      }
      await role(users[5]);
      assert.equal((await reserve()).reason, 'global_daily_limit');
      await admin();
      await db.query('delete from auth.users where id=$1', [users[0]]);
      assert.equal((await db.query('select attempts from public.vimax_ai_daily_budget')).rows[0].attempts, 50);
      await role(users[5]);
      assert.equal((await reserve()).reason, 'global_daily_limit');
      await admin();
    });
  } finally { await db.close(); }
});
