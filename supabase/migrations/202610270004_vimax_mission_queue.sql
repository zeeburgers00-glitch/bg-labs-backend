-- Additive ViMax-only mission-control queue. It uses the caller's Auth JWT;
-- no service-role key is required. The existing feature constraint is extended
-- without changing or deleting any existing audit rows.
alter table public.vimax_ai_calls drop constraint vimax_ai_calls_feature_check;
alter table public.vimax_ai_calls add constraint vimax_ai_calls_feature_check
  check (feature in ('chat', 'provider_test', 'stock_search', 'job_stage'));

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
  if p_feature is null or p_feature not in ('chat', 'provider_test', 'stock_search', 'job_stage')
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


create table public.vimax_channels (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 100),
  niche text not null check (char_length(btrim(niche)) between 1 and 500),
  audience text not null default '' check (char_length(audience) <= 500),
  language text not null default 'en' check (language ~ '^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$' and char_length(language) <= 35),
  timezone text not null default 'UTC' check (timezone ~ '^[A-Za-z0-9_+/-]{1,80}$'),
  brand_voice text not null default '' check (char_length(brand_voice) <= 500),
  format text not null default 'shorts' check (format in ('shorts','landscape')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, owner_id)
);
create index vimax_channels_owner_idx on public.vimax_channels(owner_id, created_at desc);
alter table public.vimax_channels enable row level security;
revoke all on public.vimax_channels from public, anon, authenticated;
grant select, delete on public.vimax_channels to authenticated;
grant insert (name,niche,audience,language,timezone,brand_voice,format),
      update (name,niche,audience,language,timezone,brand_voice,format) on public.vimax_channels to authenticated;
create policy vimax_channels_select_own on public.vimax_channels for select to authenticated using ((select auth.uid()) = owner_id);
create policy vimax_channels_insert_own on public.vimax_channels for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy vimax_channels_update_own on public.vimax_channels for update to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy vimax_channels_delete_own on public.vimax_channels for delete to authenticated using ((select auth.uid()) = owner_id);

create function public.vimax_guard_channel_insert() returns trigger
language plpgsql security definer set search_path = pg_catalog, public as $$
begin
  if auth.uid() is null or new.owner_id <> auth.uid() then raise exception 'Authentication is required'; end if;
  perform pg_advisory_xact_lock(hashtextextended(new.owner_id::text, 7039091));
  if (select count(*) from public.vimax_channels where owner_id = new.owner_id) >= 25 then raise exception 'Channel profile limit reached'; end if;
  return new;
end $$;
revoke all on function public.vimax_guard_channel_insert() from public, anon, authenticated;
create trigger vimax_channels_limit before insert on public.vimax_channels for each row execute function public.vimax_guard_channel_insert();
create trigger vimax_channels_touch before update on public.vimax_channels for each row execute function public.vimax_touch_project();

-- These are user-supplied references, not verified research or proof of channel ownership.
create table public.vimax_competitors (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  channel_id uuid not null,
  url text not null check (char_length(url) <= 300 and url ~ '^https://(www[.])?youtube[.]com/(@[A-Za-z0-9_.-]+|channel/[A-Za-z0-9_-]+|c/[A-Za-z0-9_.-]+|user/[A-Za-z0-9_.-]+)$'),
  created_at timestamptz not null default now(),
  unique(owner_id,channel_id,url),
  foreign key (channel_id,owner_id) references public.vimax_channels(id,owner_id) on delete cascade
);
create index vimax_competitors_owner_idx on public.vimax_competitors(owner_id,channel_id);
alter table public.vimax_competitors enable row level security;
revoke all on public.vimax_competitors from public, anon, authenticated;
grant select, delete on public.vimax_competitors to authenticated;
grant insert (channel_id,url) on public.vimax_competitors to authenticated;
create policy vimax_competitors_select_own on public.vimax_competitors for select to authenticated using ((select auth.uid()) = owner_id);
create policy vimax_competitors_insert_own on public.vimax_competitors for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy vimax_competitors_delete_own on public.vimax_competitors for delete to authenticated using ((select auth.uid()) = owner_id);
create function public.vimax_guard_competitor_insert() returns trigger
language plpgsql security definer set search_path = pg_catalog, public as $$
begin
  if auth.uid() is null or new.owner_id <> auth.uid() then raise exception 'Authentication is required'; end if;
  perform pg_advisory_xact_lock(hashtextextended(new.owner_id::text, 7039091));
  if (select count(*) from public.vimax_competitors where owner_id = new.owner_id and channel_id = new.channel_id) >= 25 then raise exception 'Competitor limit reached'; end if;
  return new;
end $$;
revoke all on function public.vimax_guard_competitor_insert() from public, anon, authenticated;
create trigger vimax_competitors_limit before insert on public.vimax_competitors for each row execute function public.vimax_guard_competitor_insert();

create table public.vimax_mission_settings (
  owner_id uuid primary key references auth.users(id) on delete cascade,
  paused boolean not null default false,
  updated_at timestamptz not null default now()
);
create table public.vimax_mission_jobs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id uuid not null,
  client_key uuid not null,
  topic text not null check (char_length(btrim(topic)) between 1 and 1600),
  profile_snapshot jsonb not null,
  provider text not null check (provider ~ '^[a-z]{1,24}$'),
  model text not null check (model ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'),
  status text not null default 'queued' check (status in ('queued','running','needs_review','completed','failed','cancelled')),
  review_reason text check (review_reason is null or review_reason in ('plan_ready','uncertain')),
  not_before timestamptz not null default now(),
  requested_not_before timestamptz,
  attempts integer not null default 0 check (attempts between 0 and 3),
  cancel_requested boolean not null default false,
  last_error text check (last_error is null or last_error in ('in_flight','paused','user_daily_limit','global_daily_limit','rate_limit','provider_unavailable','credentials','bad_response','ambiguous','worker_config','lease_expired')),
  lease_token uuid,
  lease_expires_at timestamptz,
  worker_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (owner_id,client_key),
  unique (id,owner_id),
  foreign key (channel_id,owner_id) references public.vimax_channels(id,owner_id) on delete no action
);
create index vimax_mission_jobs_claim_idx on public.vimax_mission_jobs(owner_id,status,not_before,created_at);
create index vimax_mission_jobs_recent_idx on public.vimax_mission_jobs(owner_id,created_at desc);
create table public.vimax_mission_steps (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null,
  job_id uuid not null,
  stage text not null check (stage in ('ideas','script','review')),
  status text not null check (status in ('running','completed','failed','uncertain')),
  call_id uuid references public.vimax_ai_calls(id) on delete set null,
  output text check (output is null or char_length(output) <= 6000),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  unique (job_id,stage),
  foreign key (job_id,owner_id) references public.vimax_mission_jobs(id,owner_id) on delete cascade
);
create index vimax_mission_steps_owner_idx on public.vimax_mission_steps(owner_id,job_id);
create table public.vimax_mission_events (
  id bigint generated always as identity primary key,
  owner_id uuid not null,
  job_id uuid not null,
  event text not null check (event in ('queued','claimed','stage_started','stage_completed','retry_scheduled','needs_review','completed','cancel_requested','cancelled','failed','manual_retry','lease_recovered','released')),
  stage text check (stage is null or stage in ('ideas','script','review')),
  created_at timestamptz not null default now(),
  foreign key (job_id,owner_id) references public.vimax_mission_jobs(id,owner_id) on delete cascade
);
create index vimax_mission_events_owner_idx on public.vimax_mission_events(owner_id,job_id,id desc);
create table public.vimax_mission_workers (
  owner_id uuid not null references auth.users(id) on delete cascade,
  worker_id uuid not null,
  last_seen_at timestamptz not null default now(),
  primary key(owner_id,worker_id)
);

alter table public.vimax_mission_settings enable row level security;
alter table public.vimax_mission_jobs enable row level security;
alter table public.vimax_mission_steps enable row level security;
alter table public.vimax_mission_events enable row level security;
alter table public.vimax_mission_workers enable row level security;
revoke all on public.vimax_mission_settings,public.vimax_mission_jobs,public.vimax_mission_steps,public.vimax_mission_events,public.vimax_mission_workers from public,anon,authenticated;
grant select on public.vimax_mission_settings,public.vimax_mission_steps,public.vimax_mission_events,public.vimax_mission_workers to authenticated;
-- Lease capabilities stay server-side/worker-only and cannot be read through SELECT.
grant select (id,owner_id,channel_id,client_key,topic,provider,model,status,review_reason,not_before,attempts,cancel_requested,last_error,lease_expires_at,worker_id,created_at,updated_at) on public.vimax_mission_jobs to authenticated;
create policy vimax_mission_settings_select_own on public.vimax_mission_settings for select to authenticated using ((select auth.uid()) = owner_id);
create policy vimax_mission_jobs_select_own on public.vimax_mission_jobs for select to authenticated using ((select auth.uid()) = owner_id);
create policy vimax_mission_steps_select_own on public.vimax_mission_steps for select to authenticated using ((select auth.uid()) = owner_id);
create policy vimax_mission_events_select_own on public.vimax_mission_events for select to authenticated using ((select auth.uid()) = owner_id);
create policy vimax_mission_workers_select_own on public.vimax_mission_workers for select to authenticated using ((select auth.uid()) = owner_id);

create function public.vimax_mission_submit(p_channel_id uuid, p_client_key uuid, p_topic text, p_provider text, p_model text, p_not_before timestamptz default null)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_job public.vimax_mission_jobs%rowtype; v_profile public.vimax_channels%rowtype; v_snapshot jsonb; v_when timestamptz := coalesce(p_not_before,now());
begin
  if v_owner is null then raise exception 'Authentication is required'; end if;
  if p_channel_id is null or p_client_key is null or p_topic is null or char_length(btrim(p_topic)) not between 1 and 1600
    or p_provider is null or p_provider not in ('groq','gemini','mistral','zai','openrouter','huggingface','opencode')
    or p_model is null or p_model !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$' then raise exception 'Invalid planning job'; end if;
  perform pg_advisory_xact_lock(7039092::bigint);
  perform pg_advisory_xact_lock(hashtextextended(v_owner::text, 7039091));
  select * into v_job from public.vimax_mission_jobs where owner_id=v_owner and client_key=p_client_key;
  if found then
    if v_job.channel_id <> p_channel_id or v_job.topic <> btrim(p_topic) or v_job.provider <> p_provider or v_job.model <> p_model
       or v_job.requested_not_before is distinct from p_not_before then raise exception 'Idempotency key already used for a different request'; end if;
    return jsonb_build_object('id',v_job.id,'status',v_job.status,'existing',true);
  end if;
  if v_when < now() - interval '1 minute' or v_when > now() + interval '30 days' then raise exception 'Invalid start time'; end if;
  select * into v_profile from public.vimax_channels where id=p_channel_id and owner_id=v_owner;
  if not found then raise exception 'Channel profile not found'; end if;
  v_snapshot := jsonb_build_object('name',v_profile.name,'niche',v_profile.niche,'audience',v_profile.audience,'language',v_profile.language,'timezone',v_profile.timezone,'brand_voice',v_profile.brand_voice,'format',v_profile.format,
    'competitors',coalesce((select jsonb_agg(url order by created_at,id) from public.vimax_competitors where owner_id=v_owner and channel_id=p_channel_id),'[]'::jsonb));
  if (select count(*) from public.vimax_mission_jobs where owner_id=v_owner) >= 2000
    or (select count(*) from public.vimax_mission_jobs where owner_id=v_owner and status in ('queued','running','needs_review')) >= 1000
    or (select count(*) from public.vimax_mission_jobs) >= 10000 then raise exception 'Planning job storage limit reached'; end if;
  insert into public.vimax_mission_jobs(owner_id,channel_id,client_key,topic,profile_snapshot,provider,model,not_before,requested_not_before)
    values (v_owner,p_channel_id,p_client_key,btrim(p_topic),v_snapshot,p_provider,p_model,v_when,p_not_before) returning * into v_job;
  insert into public.vimax_mission_events(owner_id,job_id,event) values(v_owner,v_job.id,'queued');
  return jsonb_build_object('id',v_job.id,'status',v_job.status,'existing',false);
end $$;

create function public.vimax_mission_pause(p_paused boolean) returns boolean
language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid();
begin
  if v_owner is null or p_paused is null then raise exception 'Authentication is required'; end if;
  perform pg_advisory_xact_lock(hashtextextended(v_owner::text, 7039091));
  insert into public.vimax_mission_settings(owner_id,paused) values(v_owner,p_paused)
    on conflict(owner_id) do update set paused=excluded.paused,updated_at=now();
  if p_paused then
    with stopped as (
      update public.vimax_mission_jobs set cancel_requested=true,updated_at=now()
      where owner_id=v_owner and status='running' and not cancel_requested returning id
    ) insert into public.vimax_mission_events(owner_id,job_id,event) select v_owner,id,'cancel_requested' from stopped;
  end if;
  return p_paused;
end $$;

create function public.vimax_mission_action(p_job_id uuid, p_action text, p_confirm_duplicate_charge boolean default false)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_job public.vimax_mission_jobs%rowtype; v_event text;
begin
  if v_owner is null then raise exception 'Authentication is required'; end if;
  if p_job_id is null or p_action is null or p_action not in ('cancel','retry','approve','purge') then raise exception 'Invalid action'; end if;
  perform pg_advisory_xact_lock(hashtextextended(v_owner::text, 7039091));
  select * into v_job from public.vimax_mission_jobs where id=p_job_id and owner_id=v_owner for update;
  if not found then raise exception 'Job not found'; end if;
  if p_action='cancel' and v_job.status='queued' then
    update public.vimax_mission_jobs set status='cancelled',updated_at=now() where id=p_job_id; v_event := 'cancelled';
  elsif p_action='cancel' and v_job.status='running' then
    if v_job.cancel_requested then return jsonb_build_object('ok',true,'event','cancel_requested','existing',true); end if;
    update public.vimax_mission_jobs set cancel_requested=true,updated_at=now() where id=p_job_id; v_event := 'cancel_requested';
  elsif p_action='cancel' and v_job.status='needs_review' then
    update public.vimax_mission_jobs set status='cancelled',updated_at=now() where id=p_job_id; v_event := 'cancelled';
  elsif p_action='approve' and v_job.status='needs_review' and v_job.review_reason='plan_ready' then
    update public.vimax_mission_jobs set status='completed',review_reason=null,updated_at=now() where id=p_job_id; v_event := 'completed';
  elsif p_action='retry' and (v_job.status='failed' or (v_job.status='needs_review' and v_job.review_reason='uncertain')) then
    if v_job.review_reason='uncertain' and p_confirm_duplicate_charge is not true then raise exception 'Confirm possible duplicate provider charges'; end if;
    if v_job.status='failed' and (select count(*) from public.vimax_mission_jobs where owner_id=v_owner and status in ('queued','running','needs_review')) >= 1000 then raise exception 'Planning job capacity reached'; end if;
    update public.vimax_mission_jobs set status='queued',review_reason=null,last_error=null,cancel_requested=false,
      attempts=0,not_before=now(),lease_token=null,lease_expires_at=null,worker_id=null,updated_at=now() where id=p_job_id;
    v_event := 'manual_retry';
  elsif p_action='purge' and v_job.status in ('completed','failed','cancelled') then
    delete from public.vimax_mission_jobs where id=p_job_id;
    return jsonb_build_object('ok',true,'event','purged');
  else raise exception 'Action is not available for this job'; end if;
  insert into public.vimax_mission_events(owner_id,job_id,event) values(v_owner,p_job_id,v_event);
  return jsonb_build_object('ok',true,'event',v_event);
end $$;

create function public.vimax_mission_heartbeat(p_worker_id uuid) returns boolean
language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid();
begin
  if v_owner is null or p_worker_id is null then raise exception 'Authentication is required'; end if;
  perform pg_advisory_xact_lock(hashtextextended(v_owner::text, 7039091));
  delete from public.vimax_mission_workers where owner_id=v_owner and last_seen_at < now() - interval '1 day';
  if not exists(select 1 from public.vimax_mission_workers where owner_id=v_owner and worker_id=p_worker_id)
    and (select count(*) from public.vimax_mission_workers where owner_id=v_owner and last_seen_at > now() - interval '2 minutes') >= 5 then
    raise exception 'Worker limit reached';
  end if;
  insert into public.vimax_mission_workers(owner_id,worker_id) values(v_owner,p_worker_id)
    on conflict(owner_id,worker_id) do update set last_seen_at=now();
  return true;
end $$;

create function public.vimax_mission_claim(p_worker_id uuid) returns jsonb
language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_job public.vimax_mission_jobs%rowtype; v_token uuid;
begin
  if v_owner is null or p_worker_id is null then raise exception 'Authentication is required'; end if;
  perform pg_advisory_xact_lock(hashtextextended(v_owner::text, 7039091));
  if not exists(select 1 from public.vimax_mission_workers where owner_id=v_owner and worker_id=p_worker_id and last_seen_at > now()-interval '2 minutes') then raise exception 'Worker heartbeat required'; end if;
  -- An expired lease during a provider request is ambiguous: never replay it automatically.
  update public.vimax_mission_steps s set status='uncertain',finished_at=now()
    from public.vimax_mission_jobs j where s.job_id=j.id and j.owner_id=v_owner and j.status='running'
      and j.lease_expires_at <= now() and s.status='running';
  with recovered as (
    update public.vimax_mission_jobs j set
      status=case when cancel_requested then 'cancelled' when exists(select 1 from public.vimax_mission_steps s where s.job_id=j.id and s.status='uncertain') then 'needs_review' else 'queued' end,
      review_reason=case when not cancel_requested and exists(select 1 from public.vimax_mission_steps s where s.job_id=j.id and s.status='uncertain') then 'uncertain' else null end,
      last_error='lease_expired',lease_token=null,lease_expires_at=null,worker_id=null,updated_at=now()
    where owner_id=v_owner and status='running' and lease_expires_at <= now() returning id
  ) insert into public.vimax_mission_events(owner_id,job_id,event) select v_owner,id,'lease_recovered' from recovered;
  if coalesce((select paused from public.vimax_mission_settings where owner_id=v_owner),false) then return null; end if;
  -- One concurrent job per profile, up to three per account. AI-call budget
  -- still allows only one provider request at a time per account.
  if (select count(*) from public.vimax_mission_jobs where owner_id=v_owner and status='running' and lease_expires_at>now()) >= 3 then return null; end if;
  select * into v_job from public.vimax_mission_jobs j where j.owner_id=v_owner and j.status='queued' and j.not_before<=now()
    and not exists(select 1 from public.vimax_mission_jobs active where active.owner_id=v_owner and active.channel_id=j.channel_id and active.status='running' and active.lease_expires_at>now())
    order by j.not_before,j.created_at,j.id for update skip locked limit 1;
  if not found then return null; end if;
  v_token := gen_random_uuid();
  update public.vimax_mission_jobs set status='running',lease_token=v_token,lease_expires_at=now()+interval '90 seconds',worker_id=p_worker_id,updated_at=now() where id=v_job.id;
  insert into public.vimax_mission_events(owner_id,job_id,event) values(v_owner,v_job.id,'claimed');
  return jsonb_build_object('id',v_job.id,'lease',v_token,'topic',v_job.topic,'provider',v_job.provider,'model',v_job.model,
    'channel',v_job.profile_snapshot,
    'steps',coalesce((select jsonb_object_agg(stage,output) from public.vimax_mission_steps where job_id=v_job.id and status='completed'),'{}'::jsonb));
end $$;

create function public.vimax_mission_lease(p_job_id uuid,p_lease uuid) returns boolean
language plpgsql security definer set search_path = pg_catalog, public as $$
begin
  if auth.uid() is null or p_job_id is null or p_lease is null then raise exception 'Authentication is required'; end if;
  update public.vimax_mission_jobs set lease_expires_at=now()+interval '90 seconds',updated_at=now()
    where id=p_job_id and owner_id=auth.uid() and status='running' and lease_token=p_lease and lease_expires_at>now() and not cancel_requested;
  return found;
end $$;

-- Gracefully hand back an idle lease between stages, never during a paid call.
create function public.vimax_mission_release(p_job_id uuid,p_lease uuid) returns boolean
language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_job public.vimax_mission_jobs%rowtype; v_status text;
begin
  if v_owner is null or p_job_id is null or p_lease is null then raise exception 'Authentication is required'; end if;
  perform pg_advisory_xact_lock(hashtextextended(v_owner::text, 7039091));
  select * into v_job from public.vimax_mission_jobs where id=p_job_id and owner_id=v_owner for update;
  if not found or v_job.status<>'running' or v_job.lease_token is distinct from p_lease or v_job.lease_expires_at<=now()
    or exists(select 1 from public.vimax_mission_steps where job_id=p_job_id and status='running') then raise exception 'Lease is not valid'; end if;
  v_status := case when v_job.cancel_requested then 'cancelled' else 'queued' end;
  update public.vimax_mission_jobs set status=v_status,not_before=now(),lease_token=null,lease_expires_at=null,worker_id=null,updated_at=now() where id=p_job_id;
  insert into public.vimax_mission_events(owner_id,job_id,event) values(v_owner,p_job_id,case when v_status='cancelled' then 'cancelled' else 'released' end);
  return true;
end $$;

-- Reject a job before reserving anything if this worker lacks the requested
-- provider/model configuration; this path cannot spend a provider budget.
create function public.vimax_mission_reject(p_job_id uuid,p_lease uuid) returns boolean
language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_job public.vimax_mission_jobs%rowtype; v_status text;
begin
  if v_owner is null or p_job_id is null or p_lease is null then raise exception 'Authentication is required'; end if;
  perform pg_advisory_xact_lock(hashtextextended(v_owner::text, 7039091));
  select * into v_job from public.vimax_mission_jobs where id=p_job_id and owner_id=v_owner for update;
  if not found or v_job.status<>'running' or v_job.lease_token is distinct from p_lease or v_job.lease_expires_at<=now()
    or exists(select 1 from public.vimax_mission_steps where job_id=p_job_id and status='running') then raise exception 'Lease is not valid'; end if;
  v_status := case when v_job.cancel_requested then 'cancelled' else 'failed' end;
  update public.vimax_mission_jobs set status=v_status,last_error='worker_config',lease_token=null,lease_expires_at=null,worker_id=null,updated_at=now() where id=p_job_id;
  insert into public.vimax_mission_events(owner_id,job_id,event) values(v_owner,p_job_id,v_status);
  return true;
end $$;

create function public.vimax_mission_begin(p_job_id uuid,p_lease uuid,p_stage text) returns jsonb
language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_job public.vimax_mission_jobs%rowtype; v_expected text; v_call jsonb; v_reason text; v_next timestamptz;
begin
  if v_owner is null or p_job_id is null or p_lease is null or p_stage not in ('ideas','script','review') or p_stage is null then raise exception 'Invalid stage'; end if;
  perform pg_advisory_xact_lock(hashtextextended(v_owner::text, 7039091));
  select * into v_job from public.vimax_mission_jobs where id=p_job_id and owner_id=v_owner for update;
  if not found or v_job.status <> 'running' or v_job.lease_token is distinct from p_lease or v_job.lease_expires_at<=now() then raise exception 'Lease is not valid'; end if;
  if v_job.cancel_requested or coalesce((select paused from public.vimax_mission_settings where owner_id=v_owner),false) then
    update public.vimax_mission_jobs set status='cancelled',lease_token=null,lease_expires_at=null,worker_id=null,updated_at=now() where id=p_job_id;
    insert into public.vimax_mission_events(owner_id,job_id,event) values(v_owner,p_job_id,'cancelled');
    return jsonb_build_object('allowed',false,'reason','paused');
  end if;
  select case
    when not exists(select 1 from public.vimax_mission_steps where job_id=p_job_id and stage='ideas' and status='completed') then 'ideas'
    when not exists(select 1 from public.vimax_mission_steps where job_id=p_job_id and stage='script' and status='completed') then 'script'
    when not exists(select 1 from public.vimax_mission_steps where job_id=p_job_id and stage='review' and status='completed') then 'review'
    else null end into v_expected;
  if v_expected is null or v_expected<>p_stage then raise exception 'Unexpected stage'; end if;
  if exists(select 1 from public.vimax_mission_steps where job_id=p_job_id and status='running') then raise exception 'A stage is already in progress'; end if;
  -- Reservation, active-step marker and queue lock commit together *before*
  -- any network call, preventing silent replay after a worker crash.
  v_call := public.vimax_reserve_ai_call('job_stage',v_job.provider,v_job.model);
  if coalesce((v_call->>'allowed')::boolean,false) is not true then
    v_reason := v_call->>'reason';
    if v_reason not in ('paused','in_flight','user_daily_limit','global_daily_limit') then raise exception 'AI safety limits unavailable'; end if;
    v_next := case when v_reason in ('user_daily_limit','global_daily_limit')
      then ((date_trunc('day',now() at time zone 'utc') + interval '1 day') at time zone 'utc') + interval '5 seconds'
      else now()+interval '65 seconds' end;
    update public.vimax_mission_jobs set status='queued',last_error=v_reason,not_before=v_next,lease_token=null,lease_expires_at=null,worker_id=null,updated_at=now() where id=p_job_id;
    return jsonb_build_object('allowed',false,'reason',v_reason);
  end if;
  insert into public.vimax_mission_steps(owner_id,job_id,stage,status,call_id,output,started_at,finished_at)
    values(v_owner,p_job_id,p_stage,'running',(v_call->>'id')::uuid,null,now(),null)
    on conflict(job_id,stage) do update set status='running',call_id=excluded.call_id,output=null,started_at=now(),finished_at=null;
  update public.vimax_mission_jobs set last_error=null,lease_expires_at=now()+interval '90 seconds',updated_at=now() where id=p_job_id;
  insert into public.vimax_mission_events(owner_id,job_id,event,stage) values(v_owner,p_job_id,'stage_started',p_stage);
  return jsonb_build_object('allowed',true,'call_id',v_call->>'id','finish_secret',v_call->>'finish_secret');
end $$;

create function public.vimax_mission_finish(p_job_id uuid,p_lease uuid,p_stage text,p_call_id uuid,p_secret uuid,p_output text,p_input_tokens integer,p_output_tokens integer)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_job public.vimax_mission_jobs%rowtype; v_done boolean; v_status text;
begin
  if v_owner is null or p_job_id is null or p_lease is null or p_call_id is null or p_secret is null or p_stage not in ('ideas','script','review') or p_stage is null
    or p_output is null or char_length(btrim(p_output)) not between 1 and 6000 then raise exception 'Invalid stage result'; end if;
  perform pg_advisory_xact_lock(hashtextextended(v_owner::text, 7039091));
  select * into v_job from public.vimax_mission_jobs where id=p_job_id and owner_id=v_owner for update;
  if not found then raise exception 'Job not found'; end if;
  -- A retry of a lost database response is safe; no second provider call occurs.
  if exists(select 1 from public.vimax_mission_steps s join public.vimax_ai_calls c on c.id=s.call_id
      where s.job_id=p_job_id and s.stage=p_stage and s.status='completed' and s.call_id=p_call_id and c.completion_secret=p_secret and c.owner_id=v_owner) then
    return jsonb_build_object('ok',true,'status',v_job.status,'existing',true);
  end if;
  if v_job.status<>'running' or v_job.lease_token is distinct from p_lease or v_job.lease_expires_at<=now()
    or not exists(select 1 from public.vimax_mission_steps where job_id=p_job_id and stage=p_stage and status='running' and call_id=p_call_id) then raise exception 'Lease is not valid'; end if;
  v_done := public.vimax_finish_ai_call(p_call_id,p_secret,'succeeded',p_input_tokens,p_output_tokens);
  if not v_done then raise exception 'Reservation is not valid'; end if;
  update public.vimax_mission_steps set status='completed',output=btrim(p_output),finished_at=now() where job_id=p_job_id and stage=p_stage;
  insert into public.vimax_mission_events(owner_id,job_id,event,stage) values(v_owner,p_job_id,'stage_completed',p_stage);
  v_status := case when v_job.cancel_requested then 'cancelled' when p_stage='review' then 'needs_review' else 'running' end;
  update public.vimax_mission_jobs set status=v_status,review_reason=case when v_status='needs_review' then 'plan_ready' else null end,
    lease_token=case when v_status='running' then lease_token else null end,
    lease_expires_at=case when v_status='running' then now()+interval '90 seconds' else null end,
    worker_id=case when v_status='running' then worker_id else null end,updated_at=now() where id=p_job_id;
  if v_status='needs_review' then insert into public.vimax_mission_events(owner_id,job_id,event) values(v_owner,p_job_id,'needs_review'); end if;
  if v_status='cancelled' then insert into public.vimax_mission_events(owner_id,job_id,event) values(v_owner,p_job_id,'cancelled'); end if;
  return jsonb_build_object('ok',true,'status',v_status,'existing',false);
end $$;

create function public.vimax_mission_fail(p_job_id uuid,p_lease uuid,p_stage text,p_call_id uuid,p_secret uuid,p_code text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_job public.vimax_mission_jobs%rowtype; v_done boolean; v_status text; v_event text; v_retry boolean;
begin
  if v_owner is null or p_job_id is null or p_lease is null or p_call_id is null or p_secret is null
    or p_stage not in ('ideas','script','review') or p_stage is null
    or p_code not in ('rate_limit','provider_unavailable','credentials','bad_response','ambiguous','worker_config') or p_code is null then raise exception 'Invalid stage failure'; end if;
  perform pg_advisory_xact_lock(hashtextextended(v_owner::text, 7039091));
  select * into v_job from public.vimax_mission_jobs where id=p_job_id and owner_id=v_owner for update;
  if not found or v_job.status<>'running' or v_job.lease_token is distinct from p_lease or v_job.lease_expires_at<=now()
    or not exists(select 1 from public.vimax_mission_steps where job_id=p_job_id and stage=p_stage and status='running' and call_id=p_call_id) then raise exception 'Lease is not valid'; end if;
  v_done := public.vimax_finish_ai_call(p_call_id,p_secret,'failed',null,null);
  if not v_done then raise exception 'Reservation is not valid'; end if;
  v_retry := p_code in ('rate_limit','provider_unavailable') and v_job.attempts<2 and not v_job.cancel_requested;
  v_status := case when v_job.cancel_requested then 'cancelled' when p_code='ambiguous' then 'needs_review' when v_retry then 'queued' else 'failed' end;
  v_event := case when v_status='cancelled' then 'cancelled' when v_status='needs_review' then 'needs_review' when v_status='queued' then 'retry_scheduled' else 'failed' end;
  update public.vimax_mission_steps set status=case when p_code='ambiguous' then 'uncertain' else 'failed' end,finished_at=now() where job_id=p_job_id and stage=p_stage;
  update public.vimax_mission_jobs set status=v_status,review_reason=case when v_status='needs_review' then 'uncertain' else null end,last_error=p_code,
    attempts=least(3,attempts+1),not_before=case when v_retry then now() + make_interval(secs => (30 * (2 ^ v_job.attempts))::integer) else not_before end,
    lease_token=null,lease_expires_at=null,worker_id=null,updated_at=now() where id=p_job_id;
  insert into public.vimax_mission_events(owner_id,job_id,event,stage) values(v_owner,p_job_id,v_event,p_stage);
  return jsonb_build_object('ok',true,'status',v_status);
end $$;

revoke all on function public.vimax_mission_submit(uuid,uuid,text,text,text,timestamptz) from public,anon,authenticated;
revoke all on function public.vimax_mission_pause(boolean) from public,anon,authenticated;
revoke all on function public.vimax_mission_action(uuid,text,boolean) from public,anon,authenticated;
revoke all on function public.vimax_mission_heartbeat(uuid) from public,anon,authenticated;
revoke all on function public.vimax_mission_claim(uuid) from public,anon,authenticated;
revoke all on function public.vimax_mission_lease(uuid,uuid) from public,anon,authenticated;
revoke all on function public.vimax_mission_release(uuid,uuid) from public,anon,authenticated;
revoke all on function public.vimax_mission_reject(uuid,uuid) from public,anon,authenticated;
revoke all on function public.vimax_mission_begin(uuid,uuid,text) from public,anon,authenticated;
revoke all on function public.vimax_mission_finish(uuid,uuid,text,uuid,uuid,text,integer,integer) from public,anon,authenticated;
revoke all on function public.vimax_mission_fail(uuid,uuid,text,uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.vimax_mission_submit(uuid,uuid,text,text,text,timestamptz),public.vimax_mission_pause(boolean),public.vimax_mission_action(uuid,text,boolean),public.vimax_mission_heartbeat(uuid),public.vimax_mission_claim(uuid),public.vimax_mission_lease(uuid,uuid),public.vimax_mission_release(uuid,uuid),public.vimax_mission_reject(uuid,uuid),public.vimax_mission_begin(uuid,uuid,text),public.vimax_mission_finish(uuid,uuid,text,uuid,uuid,text,integer,integer),public.vimax_mission_fail(uuid,uuid,text,uuid,uuid,text) to authenticated;
