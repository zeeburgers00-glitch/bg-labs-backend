-- ViMax: remove the legacy remaining-attempt counter that caused a false daily-limit message.
-- Provider quotas/billing still apply. Keep auth, pause, concurrency protection and history retention.
create or replace function public.vimax_reserve_ai_call(p_feature text, p_provider text, p_model text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public
as $$
declare
  v_owner uuid := auth.uid();
  v_since timestamptz := date_trunc('day', now() at time zone 'utc') at time zone 'utc';
  v_today date := (now() at time zone 'utc')::date;
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
  select count(*) filter (where status = 'reserved' and created_at > now() - interval '60 seconds')
    into v_in_flight
    from public.vimax_ai_calls
    where owner_id = v_owner and created_at >= least(v_since, now() - interval '60 seconds');
  if v_in_flight >= 3 then
    return jsonb_build_object('allowed', false, 'reason', 'in_flight');
  end if;
  if p_feature = 'chat' and (select count(*) from public.vimax_chat_turns where owner_id = v_owner) >= 10000 then
    return jsonb_build_object('allowed', false, 'reason', 'history_limit');
  end if;
  insert into public.vimax_ai_daily_budget (day, attempts) values (v_today, 1)
    on conflict (day) do update set attempts = public.vimax_ai_daily_budget.attempts + 1;
  insert into public.vimax_ai_calls (owner_id, feature, provider, model)
    values (v_owner, p_feature, p_provider, p_model) returning id, completion_secret into v_id, v_secret;
  return jsonb_build_object('allowed', true, 'id', v_id, 'finish_secret', v_secret,
    'remaining_user', null);
end
$$;
revoke all on function public.vimax_reserve_ai_call(text, text, text) from public, anon, authenticated;
grant execute on function public.vimax_reserve_ai_call(text, text, text) to authenticated;
