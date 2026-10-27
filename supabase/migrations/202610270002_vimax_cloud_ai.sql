-- Additive ViMax-only objects. No existing table, role or policy is changed.
-- Provider secrets stay in server environment variables, never in this DB.
-- A harmless, anonymous DB round trip allows the public health endpoint to
-- distinguish an available Auth service from a working PostgREST/database.
create function public.vimax_cloud_health() returns boolean
language sql stable set search_path = pg_catalog as $$ select true $$;
revoke all on function public.vimax_cloud_health() from public, anon, authenticated;
grant execute on function public.vimax_cloud_health() to anon, authenticated;

create table public.vimax_chat_turns (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  prompt text not null check (char_length(btrim(prompt)) between 1 and 1600),
  reply text not null check (char_length(btrim(reply)) between 1 and 6000),
  provider text not null check (provider ~ '^[a-z]{1,24}$'),
  model text not null check (char_length(model) between 1 and 128),
  created_at timestamptz not null default now()
);
create index vimax_chat_turns_owner_created_idx on public.vimax_chat_turns (owner_id, created_at desc, id desc);
alter table public.vimax_chat_turns enable row level security;
revoke all on public.vimax_chat_turns from public, anon, authenticated;
grant select, delete on public.vimax_chat_turns to authenticated;
grant insert (prompt, reply, provider, model) on public.vimax_chat_turns to authenticated;
create policy vimax_chat_select_own on public.vimax_chat_turns
  for select to authenticated using ((select auth.uid()) = owner_id);
create policy vimax_chat_insert_own on public.vimax_chat_turns
  for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy vimax_chat_delete_own on public.vimax_chat_turns
  for delete to authenticated using ((select auth.uid()) = owner_id);

create function public.vimax_guard_chat_insert() returns trigger
language plpgsql security definer set search_path = pg_catalog, public
as $$
begin
  if auth.uid() is null or new.owner_id <> auth.uid() then
    raise exception 'Authentication is required';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(new.owner_id::text, 7039072));
  if (select count(*) from public.vimax_chat_turns t where t.owner_id = new.owner_id) >= 200 then
    raise exception 'Chat history limit reached';
  end if;
  return new;
end
$$;
revoke all on function public.vimax_guard_chat_insert() from public, anon, authenticated;
create trigger vimax_chat_limit before insert on public.vimax_chat_turns
  for each row execute function public.vimax_guard_chat_insert();

-- Audit one entry per outbound provider attempt (including explicit health
-- tests and Pexels searches). No prompt, reply, API key or raw error is stored.
create table public.vimax_ai_calls (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  feature text not null check (feature in ('chat', 'provider_test', 'stock_search')),
  provider text not null check (provider ~ '^[a-z]{1,24}$'),
  model text not null check (char_length(model) <= 128),
  status text not null default 'reserved' check (status in ('reserved', 'succeeded', 'failed')),
  input_tokens integer check (input_tokens between 0 and 10000000),
  output_tokens integer check (output_tokens between 0 and 10000000),
  created_at timestamptz not null default now(),
  completed_at timestamptz
);
create index vimax_ai_calls_created_idx on public.vimax_ai_calls (created_at desc);
create index vimax_ai_calls_owner_created_idx on public.vimax_ai_calls (owner_id, created_at desc);
alter table public.vimax_ai_calls enable row level security;
revoke all on public.vimax_ai_calls from public, anon, authenticated;
grant select (id, feature, provider, model, status, input_tokens, output_tokens, created_at, completed_at)
  on public.vimax_ai_calls to authenticated;
create policy vimax_ai_calls_select_own on public.vimax_ai_calls
  for select to authenticated using ((select auth.uid()) = owner_id);

-- Each account can immediately stop its own future provider calls. This does
-- not cancel a request already reserved or in flight.
create table public.vimax_ai_preferences (
  owner_id uuid primary key references auth.users(id) on delete cascade,
  paused boolean not null default false,
  updated_at timestamptz not null default now()
);
alter table public.vimax_ai_preferences enable row level security;
revoke all on public.vimax_ai_preferences from public, anon, authenticated;
grant select (paused) on public.vimax_ai_preferences to authenticated;
create policy vimax_ai_preferences_select_own on public.vimax_ai_preferences
  for select to authenticated using ((select auth.uid()) = owner_id);

create function public.vimax_set_ai_paused(p_paused boolean) returns boolean
language plpgsql security definer set search_path = pg_catalog, public
as $$
begin
  if auth.uid() is null or p_paused is null then raise exception 'Authentication and a pause choice are required'; end if;
  -- Use the same lock as reservations: once pausing returns, no later reserve
  -- can race past the stop. Already reserved requests may still complete.
  perform pg_advisory_xact_lock(7039073001::bigint);
  insert into public.vimax_ai_preferences(owner_id, paused, updated_at)
    values(auth.uid(), p_paused, now())
    on conflict (owner_id) do update set paused = excluded.paused, updated_at = excluded.updated_at;
  return p_paused;
end
$$;
revoke all on function public.vimax_set_ai_paused(boolean) from public, anon, authenticated;
grant execute on function public.vimax_set_ai_paused(boolean) to authenticated;

-- Aggregate counters survive deletion of an account and its personal audit rows,
-- so creating/deleting accounts cannot reset the deployment-wide allowance.
create table public.vimax_ai_daily_budget (
  day date primary key,
  attempts integer not null check (attempts between 0 and 50)
);
alter table public.vimax_ai_daily_budget enable row level security;
revoke all on public.vimax_ai_daily_budget from public, anon, authenticated;

-- Serialize reservations so simultaneous requests cannot overspend the shared
-- allowance. Daily limits are hard-coded safety defaults: 10 attempts per user,
-- 50 for the whole deployment, UTC day. They are attempt limits, not a dollar
-- budget; configure independent provider-side spending caps too. An abandoned
-- reservation stops blocking concurrency after 60 seconds but still counts.
create function public.vimax_reserve_ai_call(p_feature text, p_provider text, p_model text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public
as $$
declare
  v_owner uuid := auth.uid();
  v_since timestamptz := date_trunc('day', now() at time zone 'utc') at time zone 'utc';
  v_today date := (now() at time zone 'utc')::date;
  v_user_count bigint;
  v_global_count integer;
  v_in_flight bigint;
  v_id uuid;
begin
  if v_owner is null then raise exception 'Authentication is required'; end if;
  if p_feature is null or p_feature not in ('chat', 'provider_test', 'stock_search')
     or p_provider is null or p_provider !~ '^[a-z]{1,24}$'
     or p_model is null or char_length(p_model) > 128 then
    raise exception 'Invalid reservation';
  end if;
  perform pg_advisory_xact_lock(7039073001::bigint);
  if coalesce((select paused from public.vimax_ai_preferences where owner_id = v_owner), false) then
    return jsonb_build_object('allowed', false, 'reason', 'paused');
  end if;
  -- Bounded retention; this touches only ViMax's own audit rows.
  delete from public.vimax_ai_calls where created_at < now() - interval '90 days';
  delete from public.vimax_ai_daily_budget where day < v_today - 90;
  select count(*) filter (where created_at >= v_since),
         count(*) filter (where status = 'reserved' and created_at > now() - interval '60 seconds')
    into v_user_count, v_in_flight from public.vimax_ai_calls
    where owner_id = v_owner and created_at >= least(v_since, now() - interval '60 seconds');
  select coalesce((select attempts from public.vimax_ai_daily_budget where day = v_today), 0) into v_global_count;
  if v_in_flight >= 1 then return jsonb_build_object('allowed', false, 'reason', 'in_flight'); end if;
  if p_feature = 'chat' and (select count(*) from public.vimax_chat_turns where owner_id = v_owner) >= 200 then
    return jsonb_build_object('allowed', false, 'reason', 'history_limit');
  end if;
  if v_user_count >= 10 then return jsonb_build_object('allowed', false, 'reason', 'user_daily_limit'); end if;
  if v_global_count >= 50 then return jsonb_build_object('allowed', false, 'reason', 'global_daily_limit'); end if;
  insert into public.vimax_ai_daily_budget (day, attempts) values (v_today, 1)
    on conflict (day) do update set attempts = public.vimax_ai_daily_budget.attempts + 1;
  insert into public.vimax_ai_calls (owner_id, feature, provider, model)
    values (v_owner, p_feature, p_provider, p_model) returning id into v_id;
  return jsonb_build_object('allowed', true, 'id', v_id, 'remaining_user', 9 - v_user_count);
end
$$;
revoke all on function public.vimax_reserve_ai_call(text, text, text) from public, anon, authenticated;
grant execute on function public.vimax_reserve_ai_call(text, text, text) to authenticated;

create function public.vimax_finish_ai_call(p_id uuid, p_status text, p_input_tokens integer, p_output_tokens integer)
returns boolean language plpgsql security definer set search_path = pg_catalog, public
as $$
begin
  if auth.uid() is null then raise exception 'Authentication is required'; end if;
  if p_status not in ('succeeded', 'failed') or p_status is null
    or (p_input_tokens is not null and (p_input_tokens < 0 or p_input_tokens > 10000000))
    or (p_output_tokens is not null and (p_output_tokens < 0 or p_output_tokens > 10000000)) then
    raise exception 'Invalid result';
  end if;
  update public.vimax_ai_calls set status = p_status, input_tokens = p_input_tokens,
    output_tokens = p_output_tokens, completed_at = now()
    where id = p_id and owner_id = auth.uid() and status = 'reserved';
  return found;
end
$$;
revoke all on function public.vimax_finish_ai_call(uuid, text, integer, integer) from public, anon, authenticated;
grant execute on function public.vimax_finish_ai_call(uuid, text, integer, integer) to authenticated;
