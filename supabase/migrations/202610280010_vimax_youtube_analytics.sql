-- Daily caps for real, read-only YouTube Analytics requests. These budgets are
-- separate from upload and AI calls; they count attempts, not spend or Google
-- quota units. The global aggregate survives account deletion. No report data,
-- channel metrics, provider tokens or request text are stored in these tables.
create table public.vimax_youtube_analytics_daily_budget (
  day date primary key,
  attempts integer not null check (attempts between 0 and 20)
);
create table public.vimax_youtube_analytics_user_budget (
  owner_id uuid not null references auth.users(id) on delete cascade,
  day date not null,
  attempts integer not null check (attempts between 0 and 5),
  primary key(owner_id, day)
);
alter table public.vimax_youtube_analytics_daily_budget enable row level security;
alter table public.vimax_youtube_analytics_user_budget enable row level security;
revoke all on public.vimax_youtube_analytics_daily_budget from public, anon, authenticated;
revoke all on public.vimax_youtube_analytics_user_budget from public, anon, authenticated;

create function public.vimax_youtube_analytics_reserve()
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare
  v_owner uuid := auth.uid();
  v_day date := (now() at time zone 'utc')::date;
  v_user integer;
  v_shared integer;
begin
  if v_owner is null then raise exception 'Authentication required'; end if;
  if not exists (select 1 from public.vimax_youtube_allowed_users where owner_id=v_owner) then
    return jsonb_build_object('allowed',false,'reason','not_allowed');
  end if;
  -- One lock for all accounts prevents parallel reservations exceeding the
  -- deployment-wide or per-account cap. An attempted provider call is never
  -- automatically refunded after a timeout or ambiguous result.
  perform pg_advisory_xact_lock(7039073011::bigint);
  select coalesce((select attempts from public.vimax_youtube_analytics_user_budget where owner_id=v_owner and day=v_day),0) into v_user;
  select coalesce((select attempts from public.vimax_youtube_analytics_daily_budget where day=v_day),0) into v_shared;
  if v_user >= 5 then return jsonb_build_object('allowed',false,'reason','user_daily_limit'); end if;
  if v_shared >= 20 then return jsonb_build_object('allowed',false,'reason','global_daily_limit'); end if;
  insert into public.vimax_youtube_analytics_user_budget(owner_id,day,attempts) values(v_owner,v_day,1)
    on conflict(owner_id,day) do update set attempts=public.vimax_youtube_analytics_user_budget.attempts+1;
  insert into public.vimax_youtube_analytics_daily_budget(day,attempts) values(v_day,1)
    on conflict(day) do update set attempts=public.vimax_youtube_analytics_daily_budget.attempts+1;
  return jsonb_build_object('allowed',true,'remaining_user',4-v_user);
end $$;
revoke all on function public.vimax_youtube_analytics_reserve() from public, anon, authenticated;
grant execute on function public.vimax_youtube_analytics_reserve() to authenticated;
