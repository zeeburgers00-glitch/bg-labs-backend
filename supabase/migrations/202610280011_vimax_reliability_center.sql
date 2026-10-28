-- Agent Reliability Center: durable jobs with idempotency, bounded retries, timeouts, resumable execution.
-- Distinguishes queued, running, failed, completed, awaiting-approval and cancelled states.
-- Never marks successful without verification. Additive only.

create table public.vimax_production_jobs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id uuid references public.vimax_channels(id) on delete set null,
  client_key uuid not null,
  job_type text not null check (job_type in ('research','script','voice','visuals','captions','render','thumbnail','seo','full_video','shorts')),
  pipeline_stage text not null default 'queued' check (pipeline_stage in ('queued','researching','scripting','voicing','visuals','captioning','rendering','thumbnail','seo','preview','awaiting_approval','completed','failed','cancelled')),
  status text not null default 'queued' check (status in ('queued','running','awaiting_approval','completed','failed','cancelled')),
  idempotency_key text not null check (idempotency_key ~ '^[a-f0-9]{64}$'),
  input_payload jsonb not null default '{}'::jsonb,
  output_payload jsonb,
  error_code text check (error_code is null or error_code in ('rate_limit','provider_unavailable','credentials','bad_response','ambiguous','worker_config','lease_expired','timeout','quota_exceeded','validation_failed','cancelled_by_user','dependency_failed')),
  retry_count integer not null default 0 check (retry_count between 0 and 5),
  max_retries integer not null default 3 check (max_retries between 0 and 5),
  timeout_seconds integer not null default 300 check (timeout_seconds between 30 and 3600),
  not_before timestamptz not null default now(),
  lease_token uuid,
  lease_expires_at timestamptz,
  worker_id uuid,
  cancel_requested boolean not null default false,
  cancel_confirmed boolean not null default false,
  last_heartbeat_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,
  unique(owner_id, client_key),
  unique(id, owner_id)
);
create index vimax_production_jobs_owner_status_idx on public.vimax_production_jobs(owner_id, status, pipeline_stage, created_at desc);
create index vimax_production_jobs_claim_idx on public.vimax_production_jobs(owner_id, status, not_before) where status = 'queued';
create index vimax_production_jobs_lease_idx on public.vimax_production_jobs(lease_expires_at) where lease_expires_at is not null;

create table public.vimax_production_logs (
  id bigint generated always as identity primary key,
  owner_id uuid not null,
  job_id uuid not null,
  level text not null check (level in ('info','warn','error','debug')),
  message text not null check (char_length(message) between 1 and 2000),
  agent_id text check (agent_id is null or agent_id ~ '^[A-Z][0-9]{2}$'),
  pipeline_stage text check (pipeline_stage is null or pipeline_stage in ('queued','researching','scripting','voicing','visuals','captioning','rendering','thumbnail','seo','preview','awaiting_approval','completed','failed','cancelled')),
  retry_attempt integer check (retry_attempt is null or retry_attempt between 0 and 5),
  created_at timestamptz not null default now(),
  foreign key (job_id, owner_id) references public.vimax_production_jobs(id, owner_id) on delete cascade
);
create index vimax_production_logs_job_idx on public.vimax_production_logs(owner_id, job_id, id desc);

create table public.vimax_production_events (
  id bigint generated always as identity primary key,
  owner_id uuid not null,
  job_id uuid not null,
  event text not null check (event in ('queued','claimed','stage_started','stage_completed','retry_scheduled','awaiting_approval','approved','rejected','completed','cancel_requested','cancelled','failed','lease_recovered','heartbeat','released')),
  from_stage text,
  to_stage text,
  retry_count integer,
  created_at timestamptz not null default now(),
  foreign key (job_id, owner_id) references public.vimax_production_jobs(id, owner_id) on delete cascade
);
create index vimax_production_events_job_idx on public.vimax_production_events(owner_id, job_id, id desc);

create table public.vimax_production_artifacts (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid not null,
  artifact_type text not null check (artifact_type in ('script','audio','video','thumbnail','captions','metadata','research_sources')),
  file_path text check (file_path is null or char_length(file_path) between 1 and 500),
  file_size_bytes bigint check (file_size_bytes is null or file_size_bytes between 0 and 10737418240),
  duration_seconds numeric(8,2) check (duration_seconds is null or duration_seconds between 0 and 43200),
  resolution text check (resolution is null or resolution ~ '^[0-9]{1,4}x[0-9]{1,4}$'),
  has_audio boolean,
  has_captions boolean,
  validation_status text not null default 'pending' check (validation_status in ('pending','valid','invalid')),
  validation_details jsonb,
  license_info jsonb,
  created_at timestamptz not null default now(),
  foreign key (job_id, owner_id) references public.vimax_production_jobs(id, owner_id) on delete cascade
);
create index vimax_production_artifacts_job_idx on public.vimax_production_artifacts(owner_id, job_id);

alter table public.vimax_production_jobs enable row level security;
alter table public.vimax_production_logs enable row level security;
alter table public.vimax_production_events enable row level security;
alter table public.vimax_production_artifacts enable row level security;

revoke all on public.vimax_production_jobs, public.vimax_production_logs, public.vimax_production_events, public.vimax_production_artifacts from public, anon, authenticated;

grant select (id, channel_id, client_key, job_type, pipeline_stage, status, idempotency_key, input_payload, output_payload, error_code, retry_count, max_retries, timeout_seconds, not_before, cancel_requested, cancel_confirmed, created_at, updated_at, completed_at) on public.vimax_production_jobs to authenticated;
grant select on public.vimax_production_logs to authenticated;
grant select on public.vimax_production_events to authenticated;
grant select on public.vimax_production_artifacts to authenticated;

create policy vimax_production_jobs_select_own on public.vimax_production_jobs for select to authenticated using ((select auth.uid()) = owner_id);
create policy vimax_production_logs_select_own on public.vimax_production_logs for select to authenticated using ((select auth.uid()) = owner_id);
create policy vimax_production_events_select_own on public.vimax_production_events for select to authenticated using ((select auth.uid()) = owner_id);
create policy vimax_production_artifacts_select_own on public.vimax_production_artifacts for select to authenticated using ((select auth.uid()) = owner_id);

create function public.vimax_production_submit(p_channel_id uuid, p_client_key uuid, p_job_type text, p_input jsonb, p_timeout integer default 300)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare
  v_owner uuid := auth.uid();
  v_key text;
  v_job_id uuid;
begin
  if v_owner is null then raise exception 'Authentication is required'; end if;
  if p_client_key is null or p_job_type is null or p_job_type not in ('research','script','voice','visuals','captions','render','thumbnail','seo','full_video','shorts')
     or p_input is null or jsonb_typeof(p_input) != 'object' or octet_length(p_input::text) > 10000
     or p_timeout not between 30 and 3600 then raise exception 'Invalid production job'; end if;
  if p_channel_id is not null and not exists (select 1 from public.vimax_channels where id = p_channel_id and owner_id = v_owner) then
    raise exception 'Channel not found or not owned'; end if;
  perform pg_advisory_xact_lock(7039073012::bigint);
  v_key := encode(sha256((v_owner::text || '|' || p_client_key::text || '|' || p_job_type)::bytea), 'hex');
  insert into public.vimax_production_jobs (owner_id, channel_id, client_key, job_type, idempotency_key, input_payload, timeout_seconds)
    values (v_owner, p_channel_id, p_client_key, p_job_type, v_key, p_input, p_timeout)
    returning id into v_job_id
    on conflict (owner_id, client_key) do nothing;
  if v_job_id is null then
    select id into v_job_id from public.vimax_production_jobs where owner_id = v_owner and client_key = p_client_key;
    return jsonb_build_object('id', v_job_id, 'deduplicated', true);
  end if;
  insert into public.vimax_production_events (owner_id, job_id, event) values (v_owner, v_job_id, 'queued');
  insert into public.vimax_production_logs (owner_id, job_id, level, message, pipeline_stage) values (v_owner, v_job_id, 'info', 'Job queued', 'queued');
  return jsonb_build_object('id', v_job_id, 'deduplicated', false);
end $$;
revoke all on function public.vimax_production_submit(uuid,uuid,text,jsonb,integer) from public, anon, authenticated;
grant execute on function public.vimax_production_submit(uuid,uuid,text,jsonb,integer) to authenticated;

create function public.vimax_production_cancel(p_job_id uuid)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_row public.vimax_production_jobs%rowtype;
begin
  if v_owner is null then raise exception 'Authentication is required'; end if;
  select * into v_row from public.vimax_production_jobs where id = p_job_id and owner_id = v_owner for update;
  if not found then raise exception 'Job not found'; end if;
  if v_row.status in ('completed','cancelled','failed') then return jsonb_build_object('status', v_row.status, 'already_final', true); end if;
  update public.vimax_production_jobs set cancel_requested = true, updated_at = now() where id = p_job_id and owner_id = v_owner;
  insert into public.vimax_production_events (owner_id, job_id, event) values (v_owner, p_job_id, 'cancel_requested');
  insert into public.vimax_production_logs (owner_id, job_id, level, message) values (v_owner, p_job_id, 'warn', 'Cancellation requested');
  return jsonb_build_object('status', 'cancel_requested', 'previous_status', v_row.status);
end $$;
revoke all on function public.vimax_production_cancel(uuid) from public, anon, authenticated;
grant execute on function public.vimax_production_cancel(uuid) to authenticated;

create function public.vimax_production_retry(p_job_id uuid)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_row public.vimax_production_jobs%rowtype;
begin
  if v_owner is null then raise exception 'Authentication is required'; end if;
  select * into v_row from public.vimax_production_jobs where id = p_job_id and owner_id = v_owner for update;
  if not found then raise exception 'Job not found'; end if;
  if v_row.status != 'failed' then return jsonb_build_object('allowed', false, 'reason', 'not_failed'); end if;
  if v_row.retry_count >= v_row.max_retries then return jsonb_build_object('allowed', false, 'reason', 'max_retries_exceeded'); end if;
  if v_row.error_code in ('credentials','quota_exceeded','cancelled_by_user') then return jsonb_build_object('allowed', false, 'reason', 'non_retryable', 'error_code', v_row.error_code); end if;
  update public.vimax_production_jobs set status='queued', pipeline_stage='queued', retry_count = v_row.retry_count + 1, last_heartbeat_at = null, lease_token = null, lease_expires_at = null, updated_at = now(), not_before = now() + (power(2, v_row.retry_count) * interval '30 seconds') where id = p_job_id and owner_id = v_owner;
  insert into public.vimax_production_events (owner_id, job_id, event, retry_count) values (v_owner, p_job_id, 'retry_scheduled', v_row.retry_count + 1);
  return jsonb_build_object('allowed', true, 'retry_count', v_row.retry_count + 1);
end $$;
revoke all on function public.vimax_production_retry(uuid) from public, anon, authenticated;
grant execute on function public.vimax_production_retry(uuid) to authenticated;
