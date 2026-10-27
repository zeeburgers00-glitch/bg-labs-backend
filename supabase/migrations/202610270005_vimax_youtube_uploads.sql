-- Private, user-initiated YouTube uploads. No Google token or plaintext upload
-- session URL is stored here. The bridge encrypts session URLs using a key that
-- is not in this database. Public/unattended publishing is deliberately absent.
-- Only a privileged administrator can grant account access. This independent
-- database allowlist prevents direct PostgREST calls from bypassing the bridge's
-- Vercel allowlist and consuming the shared attempt budget.
create table public.vimax_youtube_allowed_users (
  owner_id uuid primary key references auth.users(id) on delete cascade
);
alter table public.vimax_youtube_allowed_users enable row level security;
revoke all on public.vimax_youtube_allowed_users from public, anon, authenticated;

create table public.vimax_youtube_uploads (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  client_key uuid not null,
  channel_id text not null check (channel_id ~ '^UC[A-Za-z0-9_-]{22}$'),
  title text not null check (char_length(btrim(title)) between 1 and 100),
  size_bytes bigint not null check (size_bytes between 1 and 104857600),
  file_sha256 text not null check (file_sha256 ~ '^[a-f0-9]{64}$'),
  request_sha256 text not null check (request_sha256 ~ '^[a-f0-9]{64}$'),
  status text not null default 'starting' check (status in ('starting','uploading','uncertain','verifying','completed','failed','cancelled')),
  offset_bytes bigint not null default 0 check (offset_bytes >= 0 and offset_bytes <= size_bytes),
  video_id text check (video_id is null or video_id ~ '^[A-Za-z0-9_-]{11}$'),
  session_cipher text check (session_cipher is null or char_length(session_cipher) between 40 and 4096),
  cancel_requested boolean not null default false,
  lease_token uuid,
  lease_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(owner_id, client_key)
);
create index vimax_youtube_uploads_owner_idx on public.vimax_youtube_uploads(owner_id, created_at desc);
alter table public.vimax_youtube_uploads enable row level security;
revoke all on public.vimax_youtube_uploads from public, anon, authenticated;
grant select (id,client_key,channel_id,title,size_bytes,file_sha256,status,offset_bytes,video_id,cancel_requested,created_at,updated_at)
  on public.vimax_youtube_uploads to authenticated;
create policy vimax_youtube_uploads_select_own on public.vimax_youtube_uploads
  for select to authenticated using ((select auth.uid()) = owner_id);

create table public.vimax_youtube_daily_budget (
  day date primary key,
  attempts integer not null default 0 check (attempts >= 0)
);
create table public.vimax_youtube_user_daily_budget (
  owner_id uuid not null references auth.users(id) on delete cascade,
  day date not null,
  attempts integer not null default 0 check (attempts >= 0),
  primary key(owner_id,day)
);
alter table public.vimax_youtube_daily_budget enable row level security;
alter table public.vimax_youtube_user_daily_budget enable row level security;
revoke all on public.vimax_youtube_daily_budget, public.vimax_youtube_user_daily_budget from public, anon, authenticated;

-- Exposes only the caller's own allowlist decision, never the table contents.
create function public.vimax_youtube_account_allowed()
returns boolean language sql stable security definer set search_path = pg_catalog, public as $$
  select auth.uid() is not null and exists(select 1 from public.vimax_youtube_allowed_users where owner_id=auth.uid())
$$;
revoke all on function public.vimax_youtube_account_allowed() from public, anon, authenticated;
grant execute on function public.vimax_youtube_account_allowed() to authenticated;

create function public.vimax_youtube_prepare(p_client_key uuid, p_channel_id text, p_title text,
  p_size_bytes bigint, p_file_sha256 text, p_request_sha256 text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare
  v_owner uuid := auth.uid(); v_job public.vimax_youtube_uploads%rowtype;
  v_day date := (now() at time zone 'utc')::date;
  v_token uuid;
begin
  if v_owner is null then raise exception 'Authentication required'; end if;
  if not exists(select 1 from public.vimax_youtube_allowed_users where owner_id=v_owner) then
    return jsonb_build_object('allowed',false,'reason','not_allowed');
  end if;
  if p_client_key is null or p_channel_id is null or p_channel_id !~ '^UC[A-Za-z0-9_-]{22}$'
     or p_title is null or char_length(btrim(p_title)) not between 1 and 100
     or p_size_bytes is null or p_size_bytes not between 1 and 104857600
     or p_file_sha256 is null or p_file_sha256 !~ '^[a-f0-9]{64}$'
     or p_request_sha256 is null or p_request_sha256 !~ '^[a-f0-9]{64}$' then
    raise exception 'Invalid upload request';
  end if;
  -- A shared lock keeps quotas and idempotency atomic across serverless calls.
  perform pg_advisory_xact_lock(7039073099::bigint);
  select * into v_job from public.vimax_youtube_uploads
    where owner_id=v_owner and client_key=p_client_key for update;
  if found then
    if v_job.channel_id <> p_channel_id or v_job.size_bytes <> p_size_bytes
       or v_job.file_sha256 <> p_file_sha256 or v_job.request_sha256 <> p_request_sha256 then
      raise exception 'Idempotency key already used for a different upload';
    end if;
    if v_job.status='starting' and v_job.lease_until < now() then
      update public.vimax_youtube_uploads set status=case when cancel_requested then 'cancelled' else 'uncertain' end,
        lease_token=null, lease_until=null, updated_at=now() where id=v_job.id returning * into v_job;
    end if;
    return jsonb_build_object('created',false,'id',v_job.id,'status',v_job.status);
  end if;
  if (select count(*) from public.vimax_youtube_uploads where owner_id=v_owner) >= 100 then
    return jsonb_build_object('allowed',false,'reason','history_limit');
  end if;
  if exists(select 1 from public.vimax_youtube_uploads where owner_id=v_owner
      and status in ('starting','uploading','uncertain','verifying')) then
    return jsonb_build_object('allowed',false,'reason','active_upload');
  end if;
  if coalesce((select attempts from public.vimax_youtube_user_daily_budget where owner_id=v_owner and day=v_day),0) >= 3 then
    return jsonb_build_object('allowed',false,'reason','user_daily_limit');
  end if;
  if coalesce((select attempts from public.vimax_youtube_daily_budget where day=v_day),0) >= 10 then
    return jsonb_build_object('allowed',false,'reason','global_daily_limit');
  end if;
  insert into public.vimax_youtube_daily_budget(day,attempts) values (v_day,1)
    on conflict(day) do update set attempts=public.vimax_youtube_daily_budget.attempts+1;
  insert into public.vimax_youtube_user_daily_budget(owner_id,day,attempts) values(v_owner,v_day,1)
    on conflict(owner_id,day) do update set attempts=public.vimax_youtube_user_daily_budget.attempts+1;
  v_token := gen_random_uuid();
  insert into public.vimax_youtube_uploads(owner_id,client_key,channel_id,title,size_bytes,file_sha256,request_sha256,lease_token,lease_until)
    values(v_owner,p_client_key,p_channel_id,btrim(p_title),p_size_bytes,p_file_sha256,p_request_sha256,v_token,now()+interval '90 seconds') returning * into v_job;
  return jsonb_build_object('allowed',true,'created',true,'id',v_job.id,'token',v_token);
end $$;

create function public.vimax_youtube_finish_start(p_id uuid, p_token uuid, p_status text, p_session_cipher text)
returns text language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_job public.vimax_youtube_uploads%rowtype; v_status text;
begin
  if v_owner is null or p_status is null or p_status not in ('uploading','uncertain','failed') then raise exception 'Invalid upload state'; end if;
  if p_status='uploading' and (p_session_cipher is null or char_length(p_session_cipher) not between 40 and 4096) then raise exception 'Invalid session'; end if;
  select * into v_job from public.vimax_youtube_uploads where id=p_id and owner_id=v_owner for update;
  if not found or v_job.status<>'starting' or p_token is null or v_job.lease_token is distinct from p_token
      or v_job.lease_until is null or v_job.lease_until <= now() then return null; end if;
  update public.vimax_youtube_uploads set status=case when cancel_requested then 'cancelled' else p_status end,
    session_cipher=case when p_status='uploading' and not cancel_requested then p_session_cipher else null end,
    lease_token=null, lease_until=null, updated_at=now() where id=p_id returning status into v_status;
  return v_status;
end $$;

create function public.vimax_youtube_claim(p_id uuid)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_job public.vimax_youtube_uploads%rowtype; v_token uuid;
begin
  if v_owner is null then raise exception 'Authentication required'; end if;
  if not exists(select 1 from public.vimax_youtube_allowed_users where owner_id=v_owner) then
    return jsonb_build_object('allowed',false,'reason','not_allowed');
  end if;
  select * into v_job from public.vimax_youtube_uploads where id=p_id and owner_id=v_owner for update;
  if not found then return jsonb_build_object('allowed',false,'reason','not_found'); end if;
  if v_job.cancel_requested and (v_job.lease_until is null or v_job.lease_until <= now())
      and v_job.status in ('starting','uploading','uncertain','verifying') then
    update public.vimax_youtube_uploads set status='cancelled',lease_token=null,lease_until=null,updated_at=now() where id=p_id;
    return jsonb_build_object('allowed',false,'reason','not_active','status','cancelled');
  end if;
  if v_job.status='starting' and v_job.lease_until < now() then
    update public.vimax_youtube_uploads set status='uncertain',lease_token=null,lease_until=null,updated_at=now() where id=p_id returning * into v_job;
  end if;
  if v_job.status not in ('uploading','uncertain','verifying') or (v_job.cancel_requested and v_job.status <> 'verifying') then
    return jsonb_build_object('allowed',false,'reason','not_active','status',v_job.status);
  end if;
  if v_job.status <> 'verifying' and v_job.session_cipher is null then
    return jsonb_build_object('allowed',false,'reason','session_unknown','status',v_job.status);
  end if;
  if v_job.lease_until > now() then return jsonb_build_object('allowed',false,'reason','busy'); end if;
  v_token := gen_random_uuid();
  update public.vimax_youtube_uploads set lease_token=v_token,lease_until=now()+interval '90 seconds',updated_at=now() where id=p_id;
  return jsonb_build_object('allowed',true,'token',v_token,'status',v_job.status,'session_cipher',v_job.session_cipher,
    'offset_bytes',v_job.offset_bytes,'size_bytes',v_job.size_bytes,'file_sha256',v_job.file_sha256,
    'channel_id',v_job.channel_id,'video_id',v_job.video_id);
end $$;

create function public.vimax_youtube_finish_chunk(p_id uuid, p_token uuid, p_status text, p_offset_bytes bigint, p_video_id text)
returns text language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_job public.vimax_youtube_uploads%rowtype; v_status text;
begin
  if v_owner is null or p_status is null or p_status not in ('uploading','uncertain','verifying','completed','failed') then raise exception 'Invalid upload state'; end if;
  select * into v_job from public.vimax_youtube_uploads where id=p_id and owner_id=v_owner for update;
  if not found or v_job.status not in ('uploading','uncertain','verifying') or p_token is null
      or v_job.lease_token is distinct from p_token or v_job.lease_until is null or v_job.lease_until <= now() then return null; end if;
  if p_offset_bytes is null or p_offset_bytes < v_job.offset_bytes or p_offset_bytes > v_job.size_bytes then raise exception 'Invalid upload offset'; end if;
  if p_status in ('verifying','completed') and (p_offset_bytes <> v_job.size_bytes or p_video_id is null or p_video_id !~ '^[A-Za-z0-9_-]{11}$') then raise exception 'Invalid video'; end if;
  if p_video_id is not null and p_video_id !~ '^[A-Za-z0-9_-]{11}$' then raise exception 'Invalid video'; end if;
  update public.vimax_youtube_uploads set
    status=case when cancel_requested and p_status <> 'completed' then 'cancelled' else p_status end,
    offset_bytes=p_offset_bytes, video_id=coalesce(p_video_id,video_id), lease_token=null,lease_until=null,updated_at=now()
    where id=p_id returning status into v_status;
  return v_status;
end $$;

create function public.vimax_youtube_cancel(p_id uuid)
returns boolean language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_job public.vimax_youtube_uploads%rowtype;
begin
  if v_owner is null then raise exception 'Authentication required'; end if;
  select * into v_job from public.vimax_youtube_uploads where id=p_id and owner_id=v_owner for update;
  if not found or v_job.status not in ('starting','uploading','uncertain','verifying') then return false; end if;
  update public.vimax_youtube_uploads set cancel_requested=true,
    status=case when lease_until > now() then status else 'cancelled' end,
    updated_at=now() where id=p_id;
  return true;
end $$;

revoke all on function public.vimax_youtube_prepare(uuid,text,text,bigint,text,text) from public, anon, authenticated;
revoke all on function public.vimax_youtube_finish_start(uuid,uuid,text,text) from public, anon, authenticated;
revoke all on function public.vimax_youtube_claim(uuid) from public, anon, authenticated;
revoke all on function public.vimax_youtube_finish_chunk(uuid,uuid,text,bigint,text) from public, anon, authenticated;
revoke all on function public.vimax_youtube_cancel(uuid) from public, anon, authenticated;
grant execute on function public.vimax_youtube_prepare(uuid,text,text,bigint,text,text),
  public.vimax_youtube_finish_start(uuid,uuid,text,text), public.vimax_youtube_claim(uuid),
  public.vimax_youtube_finish_chunk(uuid,uuid,text,bigint,text), public.vimax_youtube_cancel(uuid) to authenticated;

-- Re-check the cancellation flag immediately before sending a chunk. Cancellation
-- can still race a request already being transmitted to Google.
create function public.vimax_youtube_lease_active(p_id uuid, p_token uuid)
returns boolean language plpgsql security definer set search_path = pg_catalog, public as $$
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  return exists(select 1 from public.vimax_youtube_uploads where id=p_id and owner_id=auth.uid()
    and lease_token=p_token and lease_until>now() and not cancel_requested and status in ('uploading','uncertain'));
end $$;
revoke all on function public.vimax_youtube_lease_active(uuid,uuid) from public, anon, authenticated;
grant execute on function public.vimax_youtube_lease_active(uuid,uuid) to authenticated;

-- Forget only a terminal local record; this never deletes a YouTube video or
-- resets daily attempt counters. An uncertain upload must first be stopped.
create function public.vimax_youtube_forget(p_id uuid)
returns boolean language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_count integer;
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  delete from public.vimax_youtube_uploads where id=p_id and owner_id=auth.uid()
    and status in ('completed','failed','cancelled');
  get diagnostics v_count = row_count;
  return v_count=1;
end $$;
revoke all on function public.vimax_youtube_forget(uuid) from public, anon, authenticated;
grant execute on function public.vimax_youtube_forget(uuid) to authenticated;
