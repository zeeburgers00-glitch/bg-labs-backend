-- Prevent a signed-in client from prematurely completing a reservation that
-- the server made for an in-flight request. Existing audit rows receive a fresh
-- random capability; only the reservation creator gets it in the RPC result.
-- Column-level grants on vimax_ai_calls do not include this column.
alter table public.vimax_ai_calls
  add column completion_secret uuid not null default gen_random_uuid();
revoke select (completion_secret) on public.vimax_ai_calls from public, anon, authenticated;

create or replace function public.vimax_reserve_ai_call(p_feature text, p_provider text, p_model text)
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
  v_secret uuid;
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
    values (v_owner, p_feature, p_provider, p_model) returning id, completion_secret into v_id, v_secret;
  return jsonb_build_object('allowed', true, 'id', v_id, 'finish_secret', v_secret, 'remaining_user', 9 - v_user_count);
end
$$;
revoke all on function public.vimax_reserve_ai_call(text, text, text) from public, anon, authenticated;
grant execute on function public.vimax_reserve_ai_call(text, text, text) to authenticated;

drop function public.vimax_finish_ai_call(uuid, text, integer, integer);
create function public.vimax_finish_ai_call(p_id uuid, p_secret uuid, p_status text, p_input_tokens integer, p_output_tokens integer)
returns boolean language plpgsql security definer set search_path = pg_catalog, public
as $$
begin
  if auth.uid() is null then raise exception 'Authentication is required'; end if;
  if p_secret is null or p_status not in ('succeeded', 'failed') or p_status is null
    or (p_input_tokens is not null and (p_input_tokens < 0 or p_input_tokens > 10000000))
    or (p_output_tokens is not null and (p_output_tokens < 0 or p_output_tokens > 10000000)) then
    raise exception 'Invalid result';
  end if;
  update public.vimax_ai_calls set status = p_status, input_tokens = p_input_tokens,
    output_tokens = p_output_tokens, completed_at = now()
    where id = p_id and owner_id = auth.uid() and completion_secret = p_secret and status = 'reserved';
  return found;
end
$$;
revoke all on function public.vimax_finish_ai_call(uuid, uuid, text, integer, integer) from public, anon, authenticated;
grant execute on function public.vimax_finish_ai_call(uuid, uuid, text, integer, integer) to authenticated;
