-- Optional paid GPU-backed video previews. Disabled by default: an administrator
-- must explicitly allow an account and configure the Vercel-side credentials.
-- No provider key or plaintext provider job/output capability is stored here.
create table public.vimax_gpu_allowed_users (
  owner_id uuid primary key references auth.users(id) on delete cascade
);
alter table public.vimax_gpu_allowed_users enable row level security;
revoke all on public.vimax_gpu_allowed_users from public, anon, authenticated;

create table public.vimax_gpu_jobs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  client_key uuid not null,
  request_hash text not null check (request_hash ~ '^[a-f0-9]{64}$'),
  prompt text not null check (char_length(btrim(prompt)) between 1 and 600),
  aspect text not null check (aspect in ('landscape','shorts')),
  status text not null default 'starting' check (status in ('starting','queued','running','completed','failed','cancelled','uncertain','expired')),
  provider_cipher text check (provider_cipher is null or char_length(provider_cipher) between 40 and 4096),
  output_cipher text check (output_cipher is null or char_length(output_cipher) between 40 and 4096),
  reported_cost numeric check (reported_cost is null or reported_cost between 0 and 100),
  cancel_requested boolean not null default false,
  lease_token uuid,
  lease_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(owner_id,client_key)
);
create index vimax_gpu_jobs_owner_idx on public.vimax_gpu_jobs(owner_id,created_at desc);
alter table public.vimax_gpu_jobs enable row level security;
revoke all on public.vimax_gpu_jobs from public, anon, authenticated;
grant select (id,client_key,prompt,aspect,status,reported_cost,cancel_requested,created_at,updated_at)
  on public.vimax_gpu_jobs to authenticated;
create policy vimax_gpu_jobs_select_own on public.vimax_gpu_jobs for select to authenticated
  using ((select auth.uid())=owner_id);

-- The global counter does not cascade when accounts or job records are deleted.
create table public.vimax_gpu_daily_budget (day date primary key, attempts integer not null check (attempts between 0 and 3));
create table public.vimax_gpu_user_daily_budget (
  owner_id uuid not null references auth.users(id) on delete cascade,
  day date not null, attempts integer not null check (attempts between 0 and 1), primary key(owner_id,day)
);
alter table public.vimax_gpu_daily_budget enable row level security;
alter table public.vimax_gpu_user_daily_budget enable row level security;
revoke all on public.vimax_gpu_daily_budget, public.vimax_gpu_user_daily_budget from public, anon, authenticated;

create function public.vimax_gpu_account_allowed() returns boolean
language sql stable security definer set search_path=pg_catalog,public as $$
  select auth.uid() is not null and exists(select 1 from public.vimax_gpu_allowed_users where owner_id=auth.uid())
$$;

-- At most one attempt/account and three shared attempts per UTC day, one active
-- job/account. Attempts are not dollar caps. An ambiguous start never retries.
create function public.vimax_gpu_prepare(p_client_key uuid,p_prompt text,p_aspect text,p_request_hash text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_owner uuid:=auth.uid(); v_job public.vimax_gpu_jobs%rowtype;
  v_day date:=(now() at time zone 'utc')::date; v_token uuid;
begin
  if v_owner is null then raise exception 'Authentication required'; end if;
  if not exists(select 1 from public.vimax_gpu_allowed_users where owner_id=v_owner) then
    return jsonb_build_object('allowed',false,'reason','not_allowed');
  end if;
  if p_client_key is null or p_prompt is null or char_length(btrim(p_prompt)) not between 1 and 600
    or p_aspect is null or p_aspect not in ('landscape','shorts')
    or p_request_hash is null or p_request_hash !~ '^[a-f0-9]{64}$' then raise exception 'Invalid GPU request'; end if;
  perform pg_advisory_xact_lock(7039073111::bigint);
  select * into v_job from public.vimax_gpu_jobs where owner_id=v_owner and client_key=p_client_key for update;
  if found then
    if v_job.request_hash<>p_request_hash or v_job.prompt<>btrim(p_prompt) or v_job.aspect<>p_aspect then
      raise exception 'Idempotency key already used for a different request';
    end if;
    if v_job.status='starting' and v_job.lease_until<=now() then
      update public.vimax_gpu_jobs set status='uncertain',lease_token=null,lease_until=null,updated_at=now()
        where id=v_job.id returning * into v_job;
    end if;
    return jsonb_build_object('created',false,'id',v_job.id,'status',v_job.status);
  end if;
  if (select count(*) from public.vimax_gpu_jobs where owner_id=v_owner)>=30 then
    return jsonb_build_object('allowed',false,'reason','history_limit');
  end if;
  if exists(select 1 from public.vimax_gpu_jobs where owner_id=v_owner and status in ('starting','queued','running','uncertain')) then
    return jsonb_build_object('allowed',false,'reason','active_job');
  end if;
  if coalesce((select attempts from public.vimax_gpu_user_daily_budget where owner_id=v_owner and day=v_day),0)>=1 then
    return jsonb_build_object('allowed',false,'reason','user_daily_limit');
  end if;
  if coalesce((select attempts from public.vimax_gpu_daily_budget where day=v_day),0)>=3 then
    return jsonb_build_object('allowed',false,'reason','global_daily_limit');
  end if;
  insert into public.vimax_gpu_daily_budget(day,attempts) values(v_day,1)
    on conflict(day) do update set attempts=public.vimax_gpu_daily_budget.attempts+1;
  insert into public.vimax_gpu_user_daily_budget(owner_id,day,attempts) values(v_owner,v_day,1)
    on conflict(owner_id,day) do update set attempts=public.vimax_gpu_user_daily_budget.attempts+1;
  v_token:=gen_random_uuid();
  insert into public.vimax_gpu_jobs(owner_id,client_key,request_hash,prompt,aspect,lease_token,lease_until)
    values(v_owner,p_client_key,p_request_hash,btrim(p_prompt),p_aspect,v_token,now()+interval '60 seconds') returning * into v_job;
  return jsonb_build_object('allowed',true,'created',true,'id',v_job.id,'token',v_token);
end $$;

create function public.vimax_gpu_start_active(p_id uuid,p_token uuid) returns boolean
language sql stable security definer set search_path=pg_catalog,public as $$
  select auth.uid() is not null and p_token is not null and exists(
    select 1 from public.vimax_gpu_jobs where id=p_id and owner_id=auth.uid() and status='starting'
      and lease_token=p_token and lease_until>now() and not cancel_requested)
$$;

create function public.vimax_gpu_finish_start(p_id uuid,p_token uuid,p_status text,p_provider_cipher text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_job public.vimax_gpu_jobs%rowtype;
begin
  if auth.uid() is null or p_status is null or p_status not in ('queued','failed','uncertain','cancelled') then raise exception 'Invalid GPU start'; end if;
  if p_status='queued' and (p_provider_cipher is null or char_length(p_provider_cipher) not between 40 and 4096) then raise exception 'Invalid provider capability'; end if;
  select * into v_job from public.vimax_gpu_jobs where id=p_id and owner_id=auth.uid() for update;
  if not found or v_job.status<>'starting' or p_token is null or v_job.lease_token is distinct from p_token
    or v_job.lease_until is null or v_job.lease_until<=now() then return null; end if;
  update public.vimax_gpu_jobs set status=p_status,provider_cipher=case when p_status='queued' then p_provider_cipher else null end,
    lease_token=null,lease_until=null,updated_at=now() where id=p_id returning * into v_job;
  return jsonb_build_object('status',v_job.status,'cancel_requested',v_job.cancel_requested);
end $$;

create function public.vimax_gpu_claim(p_id uuid) returns jsonb
language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_job public.vimax_gpu_jobs%rowtype; v_token uuid;
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  if not exists(select 1 from public.vimax_gpu_allowed_users where owner_id=auth.uid()) then
    return jsonb_build_object('allowed',false,'reason','not_allowed');
  end if;
  select * into v_job from public.vimax_gpu_jobs where id=p_id and owner_id=auth.uid() for update;
  if not found then return jsonb_build_object('allowed',false,'reason','not_found'); end if;
  if v_job.status='starting' and v_job.lease_until<=now() then
    update public.vimax_gpu_jobs set status='uncertain',lease_token=null,lease_until=null,updated_at=now() where id=p_id returning * into v_job;
  end if;
  if v_job.status not in ('queued','running','completed') or v_job.provider_cipher is null then
    return jsonb_build_object('allowed',false,'reason','not_active','status',v_job.status,'cancel_requested',v_job.cancel_requested);
  end if;
  if v_job.lease_until>now() then return jsonb_build_object('allowed',false,'reason','busy'); end if;
  v_token:=gen_random_uuid();
  update public.vimax_gpu_jobs set lease_token=v_token,lease_until=now()+interval '60 seconds',updated_at=now() where id=p_id;
  return jsonb_build_object('allowed',true,'token',v_token,'status',v_job.status,'provider_cipher',v_job.provider_cipher,
    'output_cipher',v_job.output_cipher,'cancel_requested',v_job.cancel_requested);
end $$;

create function public.vimax_gpu_finish(p_id uuid,p_token uuid,p_status text,p_output_cipher text,p_cost numeric)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_job public.vimax_gpu_jobs%rowtype;
begin
  if auth.uid() is null or p_status is null or p_status not in ('queued','running','completed','failed','cancelled','uncertain','expired') then raise exception 'Invalid GPU status'; end if;
  if p_cost is not null and (p_cost<0 or p_cost>100) then raise exception 'Invalid reported cost'; end if;
  if p_status='completed' and (p_output_cipher is null or char_length(p_output_cipher) not between 40 and 4096) then raise exception 'Invalid output capability'; end if;
  select * into v_job from public.vimax_gpu_jobs where id=p_id and owner_id=auth.uid() for update;
  if not found or v_job.status not in ('queued','running','completed') or p_token is null
     or v_job.lease_token is distinct from p_token or v_job.lease_until is null or v_job.lease_until<=now() then return null; end if;
  -- A completed job cannot be downgraded by a stale status check.
  if v_job.status='completed' and p_status<>'completed' then p_status:='completed'; p_output_cipher:=v_job.output_cipher; end if;
  update public.vimax_gpu_jobs set status=p_status,output_cipher=case when p_status='completed' then p_output_cipher else null end,
    reported_cost=coalesce(p_cost,reported_cost),lease_token=null,lease_until=null,updated_at=now() where id=p_id returning * into v_job;
  return jsonb_build_object('status',v_job.status,'cancel_requested',v_job.cancel_requested);
end $$;

create function public.vimax_gpu_request_cancel(p_id uuid) returns boolean
language plpgsql security definer set search_path=pg_catalog,public as $$
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  update public.vimax_gpu_jobs set cancel_requested=true,updated_at=now()
    where id=p_id and owner_id=auth.uid() and status in ('starting','queued','running','uncertain');
  return found;
end $$;

-- Removing a local record does not cancel a remote job, delete remote output,
-- or restore the daily budget. Uncertain starts need an explicit warning.
create function public.vimax_gpu_forget(p_id uuid,p_confirm_uncertain boolean) returns boolean
language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_job public.vimax_gpu_jobs%rowtype;
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  select * into v_job from public.vimax_gpu_jobs where id=p_id and owner_id=auth.uid() for update;
  if not found then return false; end if;
  if v_job.status='starting' and v_job.lease_until<=now() then
    update public.vimax_gpu_jobs set status='uncertain',lease_token=null,lease_until=null where id=p_id returning * into v_job;
  end if;
  if v_job.status not in ('completed','failed','cancelled','uncertain','expired') or (v_job.status in ('uncertain','expired') and p_confirm_uncertain is not true)
    or v_job.lease_until>now() then return false; end if;
  delete from public.vimax_gpu_jobs where id=p_id and owner_id=auth.uid(); return found;
end $$;

revoke all on function public.vimax_gpu_account_allowed(),public.vimax_gpu_prepare(uuid,text,text,text),
  public.vimax_gpu_start_active(uuid,uuid),public.vimax_gpu_finish_start(uuid,uuid,text,text),public.vimax_gpu_claim(uuid),
  public.vimax_gpu_finish(uuid,uuid,text,text,numeric),public.vimax_gpu_request_cancel(uuid),public.vimax_gpu_forget(uuid,boolean)
  from public,anon,authenticated;
grant execute on function public.vimax_gpu_account_allowed(),public.vimax_gpu_prepare(uuid,text,text,text),
  public.vimax_gpu_start_active(uuid,uuid),public.vimax_gpu_finish_start(uuid,uuid,text,text),public.vimax_gpu_claim(uuid),
  public.vimax_gpu_finish(uuid,uuid,text,text,numeric),public.vimax_gpu_request_cancel(uuid),public.vimax_gpu_forget(uuid,boolean)
  to authenticated;
