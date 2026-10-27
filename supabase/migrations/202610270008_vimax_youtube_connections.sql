-- Saved YouTube channel grants. Google refresh tokens are encrypted by the
-- server before storage; plaintext keys/tokens must never be written here.
-- Authenticated users can operate on their own records only. They can call
-- these RPCs directly, so metadata is not an independently trustworthy audit.
create table public.vimax_youtube_connections (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id text not null check (channel_id ~ '^UC[A-Za-z0-9_-]{22}$'),
  channel_title text not null check (char_length(btrim(channel_title)) between 1 and 200),
  refresh_cipher text not null check (char_length(refresh_cipher) between 40 and 4096 and refresh_cipher ~ '^v1\.[A-Za-z0-9_-]+$'),
  status text not null default 'active' check (status in ('active','needs_reauth','uncertain')),
  is_default boolean not null default false,
  lease_token uuid,
  lease_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(owner_id, channel_id)
);
create unique index vimax_youtube_one_default on public.vimax_youtube_connections(owner_id) where is_default;
create index vimax_youtube_connections_owner on public.vimax_youtube_connections(owner_id, updated_at desc);
alter table public.vimax_youtube_connections enable row level security;
revoke all on public.vimax_youtube_connections from public, anon, authenticated;
grant select (id,channel_id,channel_title,status,is_default,created_at,updated_at)
  on public.vimax_youtube_connections to authenticated;
create policy vimax_youtube_connections_select_own on public.vimax_youtube_connections
  for select to authenticated using ((select auth.uid()) = owner_id);

-- The bridge verifies the channel with Google before saving and encrypts the
-- refresh token with owner + channel bound as authenticated associated data.
create function public.vimax_youtube_connection_save(p_channel_id text, p_channel_title text, p_refresh_cipher text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_owner uuid:=auth.uid(); v_row public.vimax_youtube_connections%rowtype;
begin
  if v_owner is null then raise exception 'Authentication required'; end if;
  if not exists(select 1 from public.vimax_youtube_allowed_users where owner_id=v_owner) then
    return jsonb_build_object('allowed',false,'reason','not_allowed');
  end if;
  if p_channel_id is null or p_channel_id !~ '^UC[A-Za-z0-9_-]{22}$'
     or p_channel_title is null or char_length(btrim(p_channel_title)) not between 1 and 200
     or p_refresh_cipher is null or char_length(p_refresh_cipher) not between 40 and 4096
     or p_refresh_cipher !~ '^v1\.[A-Za-z0-9_-]+$' then
    raise exception 'Invalid channel connection';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('vimax-youtube-connection:'||v_owner::text,0));
  select * into v_row from public.vimax_youtube_connections where owner_id=v_owner and channel_id=p_channel_id for update;
  if found and v_row.lease_until > now() then return jsonb_build_object('allowed',false,'reason','busy'); end if;
  if not found and (select count(*) from public.vimax_youtube_connections where owner_id=v_owner) >= 10 then
    return jsonb_build_object('allowed',false,'reason','limit');
  end if;
  update public.vimax_youtube_connections set is_default=false where owner_id=v_owner and is_default;
  insert into public.vimax_youtube_connections(owner_id,channel_id,channel_title,refresh_cipher,is_default)
    values(v_owner,p_channel_id,btrim(p_channel_title),p_refresh_cipher,true)
    on conflict(owner_id,channel_id) do update set channel_title=excluded.channel_title,refresh_cipher=excluded.refresh_cipher,
      status='active',is_default=true,lease_token=null,lease_until=null,updated_at=now()
    returning * into v_row;
  return jsonb_build_object('allowed',true,'id',v_row.id,'channel_id',v_row.channel_id);
end $$;

-- A refresh lease serializes token rotation. An expired lease is ambiguous and
-- cannot be retried automatically; the owner must reconnect instead.
create function public.vimax_youtube_connection_claim(p_id uuid)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_owner uuid:=auth.uid(); v_row public.vimax_youtube_connections%rowtype; v_lease uuid;
begin
  if v_owner is null then raise exception 'Authentication required'; end if;
  if not exists(select 1 from public.vimax_youtube_allowed_users where owner_id=v_owner) then
    return jsonb_build_object('allowed',false,'reason','not_allowed');
  end if;
  select * into v_row from public.vimax_youtube_connections where id=p_id and owner_id=v_owner for update;
  if not found then return jsonb_build_object('allowed',false,'reason','not_found'); end if;
  if v_row.status <> 'active' then return jsonb_build_object('allowed',false,'reason',v_row.status); end if;
  if v_row.lease_until > now() then return jsonb_build_object('allowed',false,'reason','busy'); end if;
  if v_row.lease_token is not null then
    update public.vimax_youtube_connections set status='uncertain',lease_token=null,lease_until=null,updated_at=now() where id=p_id;
    return jsonb_build_object('allowed',false,'reason','uncertain');
  end if;
  v_lease:=gen_random_uuid();
  update public.vimax_youtube_connections set lease_token=v_lease,lease_until=now()+interval '120 seconds',updated_at=now() where id=p_id;
  return jsonb_build_object('allowed',true,'id',v_row.id,'channel_id',v_row.channel_id,'channel_title',v_row.channel_title,
    'refresh_cipher',v_row.refresh_cipher,'lease',v_lease);
end $$;

create function public.vimax_youtube_connection_finish(p_id uuid,p_lease uuid,p_status text,p_refresh_cipher text)
returns boolean language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_owner uuid:=auth.uid(); v_count integer;
begin
  if v_owner is null or p_status is null or p_status not in ('active','needs_reauth','uncertain')
     or p_refresh_cipher is null or char_length(p_refresh_cipher) not between 40 and 4096
     or p_refresh_cipher !~ '^v1\.[A-Za-z0-9_-]+$' then raise exception 'Invalid connection state'; end if;
  perform pg_advisory_xact_lock(hashtextextended('vimax-youtube-connection:'||v_owner::text,0));
  update public.vimax_youtube_connections set status=p_status,refresh_cipher=p_refresh_cipher,
    lease_token=null,lease_until=null,updated_at=now()
    where id=p_id and owner_id=v_owner and status='active' and lease_token=p_lease and lease_until>now();
  get diagnostics v_count=row_count;
  if v_count=1 and p_status='active' then
    update public.vimax_youtube_connections set is_default=false where owner_id=v_owner and is_default and id<>p_id;
    update public.vimax_youtube_connections set is_default=true where owner_id=v_owner and id=p_id;
  end if;
  return v_count=1;
end $$;

-- Before a saved access cookie can be used, check that its exact channel record
-- still exists and remains active. This makes disconnect effective in all app
-- sessions even if provider-side revocation could not be confirmed.
create function public.vimax_youtube_connection_valid(p_id uuid,p_channel_id text)
returns boolean language sql stable security definer set search_path=pg_catalog,public as $$
  select auth.uid() is not null and exists(select 1 from public.vimax_youtube_connections
    where id=p_id and owner_id=auth.uid() and channel_id=p_channel_id and status='active')
$$;

-- Forget locally first; the bridge then attempts provider revocation. A live
-- refresh lease blocks removal. An expired lease means provider state could be
-- ambiguous and the owner must also revoke the grant in Google account settings.
create function public.vimax_youtube_connection_remove(p_id uuid)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_owner uuid:=auth.uid(); v_row public.vimax_youtube_connections%rowtype;
begin
  if v_owner is null then raise exception 'Authentication required'; end if;
  perform pg_advisory_xact_lock(hashtextextended('vimax-youtube-connection:'||v_owner::text,0));
  select * into v_row from public.vimax_youtube_connections where id=p_id and owner_id=v_owner for update;
  if not found then return jsonb_build_object('removed',false,'reason','not_found'); end if;
  if v_row.lease_until > now() then return jsonb_build_object('removed',false,'reason','busy'); end if;
  delete from public.vimax_youtube_connections where id=p_id;
  return jsonb_build_object('removed',true,'channel_id',v_row.channel_id,'refresh_cipher',v_row.refresh_cipher,
    'ambiguous',v_row.lease_token is not null or v_row.status='uncertain');
end $$;

revoke all on function public.vimax_youtube_connection_save(text,text,text), public.vimax_youtube_connection_claim(uuid),
  public.vimax_youtube_connection_finish(uuid,uuid,text,text), public.vimax_youtube_connection_valid(uuid,text),
  public.vimax_youtube_connection_remove(uuid) from public, anon, authenticated;
grant execute on function public.vimax_youtube_connection_save(text,text,text), public.vimax_youtube_connection_claim(uuid),
  public.vimax_youtube_connection_finish(uuid,uuid,text,text), public.vimax_youtube_connection_valid(uuid,text),
  public.vimax_youtube_connection_remove(uuid) to authenticated;
