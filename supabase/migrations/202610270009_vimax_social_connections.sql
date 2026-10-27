-- Optional, separately configured TikTok and Facebook Page connections.
-- Provider credentials are encrypted by the server; only owner-scoped metadata
-- is selectable. These tables do not grant publishing permissions or run jobs.
create table public.vimax_social_allowed_users (
  owner_id uuid not null references auth.users(id) on delete cascade,
  provider text not null check (provider in ('tiktok','facebook')),
  primary key(owner_id,provider)
);
alter table public.vimax_social_allowed_users enable row level security;
revoke all on public.vimax_social_allowed_users from public,anon,authenticated;

create table public.vimax_social_connections (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  provider text not null check (provider in ('tiktok','facebook')),
  external_id text not null check (char_length(external_id) between 1 and 160),
  display_name text not null check (char_length(btrim(display_name)) between 1 and 200),
  credential_cipher text not null check (char_length(credential_cipher) between 40 and 12000 and credential_cipher ~ '^v1\.[A-Za-z0-9_-]+$'),
  status text not null default 'active' check (status in ('active','needs_reauth','uncertain')),
  is_default boolean not null default false,
  verified_at timestamptz,
  lease_token uuid,
  lease_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(owner_id,provider,external_id)
);
create unique index vimax_social_one_default on public.vimax_social_connections(owner_id,provider) where is_default;
alter table public.vimax_social_connections enable row level security;
revoke all on public.vimax_social_connections from public,anon,authenticated;
grant select (id,provider,external_id,display_name,status,is_default,verified_at,created_at,updated_at)
  on public.vimax_social_connections to authenticated;
create policy vimax_social_connections_select_own on public.vimax_social_connections
  for select to authenticated using ((select auth.uid())=owner_id);

create function public.vimax_social_account_allowed(p_provider text) returns boolean
language sql stable security definer set search_path=pg_catalog,public as $$
  select auth.uid() is not null and exists(select 1 from public.vimax_social_allowed_users where owner_id=auth.uid() and provider=p_provider)
$$;

-- Save the pages returned by one consent exchange atomically; never silently
-- discard pages or partially persist a grant when the per-provider limit is hit.
create function public.vimax_social_connection_save(p_provider text,p_items jsonb) returns jsonb
language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_owner uuid:=auth.uid(); v_item jsonb; v_external text; v_name text; v_cipher text;
  v_count integer; v_existing integer; v_first text; v_result jsonb:='[]'::jsonb; v_row public.vimax_social_connections%rowtype;
begin
  if v_owner is null then raise exception 'Authentication required'; end if;
  if p_provider not in ('tiktok','facebook') or not public.vimax_social_account_allowed(p_provider) then
    return jsonb_build_object('allowed',false,'reason','not_allowed');
  end if;
  if p_items is null or jsonb_typeof(p_items)<>'array' or jsonb_array_length(p_items) not between 1 and 10 then raise exception 'Invalid social connections'; end if;
  if p_provider='tiktok' and jsonb_array_length(p_items)<>1 then raise exception 'Invalid TikTok connection'; end if;
  if octet_length(p_items::text)>130000 then raise exception 'Social connections too large'; end if;
  perform pg_advisory_xact_lock(hashtextextended('vimax-social:'||v_owner::text||':'||p_provider,0));
  for v_item in select value from jsonb_array_elements(p_items) loop
    v_external:=v_item->>'external_id';v_name:=v_item->>'display_name';v_cipher:=v_item->>'credential_cipher';
    if v_external is null or (p_provider='facebook' and v_external !~ '^[0-9]{1,32}$')
       or (p_provider='tiktok' and v_external !~ '^[A-Za-z0-9_-]{1,160}$')
       or v_name is null or char_length(btrim(v_name)) not between 1 and 200
       or v_cipher is null or char_length(v_cipher) not between 40 and 12000 or v_cipher !~ '^v1\.[A-Za-z0-9_-]+$' then
      raise exception 'Invalid social connection';
    end if;
    if v_first is null then v_first:=v_external; end if;
  end loop;
  select count(distinct value->>'external_id') into v_count from jsonb_array_elements(p_items);
  if v_count<>jsonb_array_length(p_items) then raise exception 'Duplicate social connection'; end if;
  select count(*) into v_existing from public.vimax_social_connections where owner_id=v_owner and provider=p_provider;
  select count(*) into v_count from jsonb_array_elements(p_items) a
    where not exists(select 1 from public.vimax_social_connections c where c.owner_id=v_owner and c.provider=p_provider and c.external_id=a.value->>'external_id');
  if v_existing+v_count>10 then return jsonb_build_object('allowed',false,'reason','limit'); end if;
  perform 1 from public.vimax_social_connections c where c.owner_id=v_owner and c.provider=p_provider
    and c.external_id in (select value->>'external_id' from jsonb_array_elements(p_items)) for update;
  if exists(select 1 from public.vimax_social_connections c where c.owner_id=v_owner and c.provider=p_provider and c.lease_until>now()
    and c.external_id in (select value->>'external_id' from jsonb_array_elements(p_items))) then
    return jsonb_build_object('allowed',false,'reason','busy');
  end if;
  update public.vimax_social_connections set is_default=false where owner_id=v_owner and provider=p_provider and is_default;
  for v_item in select value from jsonb_array_elements(p_items) loop
    insert into public.vimax_social_connections(owner_id,provider,external_id,display_name,credential_cipher,is_default,verified_at)
      values(v_owner,p_provider,v_item->>'external_id',btrim(v_item->>'display_name'),v_item->>'credential_cipher',(v_item->>'external_id')=v_first,now())
      on conflict(owner_id,provider,external_id) do update set display_name=excluded.display_name,credential_cipher=excluded.credential_cipher,
        status='active',is_default=excluded.is_default,verified_at=now(),lease_token=null,lease_until=null,updated_at=now()
      returning * into v_row;
    v_result:=v_result||jsonb_build_array(jsonb_build_object('id',v_row.id,'external_id',v_row.external_id));
  end loop;
  return jsonb_build_object('allowed',true,'connections',v_result);
end $$;

create function public.vimax_social_connection_claim(p_provider text,p_id uuid) returns jsonb
language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_owner uuid:=auth.uid();v_row public.vimax_social_connections%rowtype;v_lease uuid;
begin
  if v_owner is null then raise exception 'Authentication required'; end if;
  if not public.vimax_social_account_allowed(p_provider) then return jsonb_build_object('allowed',false,'reason','not_allowed'); end if;
  select * into v_row from public.vimax_social_connections where id=p_id and owner_id=v_owner and provider=p_provider for update;
  if not found then return jsonb_build_object('allowed',false,'reason','not_found'); end if;
  if v_row.status<>'active' then return jsonb_build_object('allowed',false,'reason',v_row.status); end if;
  if v_row.lease_until>now() then return jsonb_build_object('allowed',false,'reason','busy'); end if;
  if v_row.lease_token is not null then
    update public.vimax_social_connections set status='uncertain',lease_token=null,lease_until=null,updated_at=now() where id=p_id;
    return jsonb_build_object('allowed',false,'reason','uncertain');
  end if;
  v_lease:=gen_random_uuid();
  update public.vimax_social_connections set lease_token=v_lease,lease_until=now()+interval '120 seconds',updated_at=now() where id=p_id;
  return jsonb_build_object('allowed',true,'id',v_row.id,'external_id',v_row.external_id,'credential_cipher',v_row.credential_cipher,'lease',v_lease);
end $$;

create function public.vimax_social_connection_finish(p_provider text,p_id uuid,p_lease uuid,p_status text,p_cipher text,p_verified boolean)
returns boolean language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_owner uuid:=auth.uid();v_count integer;
begin
  if v_owner is null or p_provider not in ('tiktok','facebook') or p_status not in ('active','needs_reauth','uncertain')
     or p_status is null or p_verified is null or p_cipher is null or char_length(p_cipher) not between 40 and 12000
     or p_cipher !~ '^v1\.[A-Za-z0-9_-]+$' then raise exception 'Invalid social state'; end if;
  perform pg_advisory_xact_lock(hashtextextended('vimax-social:'||v_owner::text||':'||p_provider,0));
  update public.vimax_social_connections set status=p_status,credential_cipher=p_cipher,
    verified_at=case when p_verified and p_status='active' then now() else verified_at end,
    lease_token=null,lease_until=null,updated_at=now()
    where id=p_id and owner_id=v_owner and provider=p_provider and status='active' and lease_token=p_lease and lease_until>now();
  get diagnostics v_count=row_count;
  if v_count=1 and p_status='active' and p_verified then
    update public.vimax_social_connections set is_default=false where owner_id=v_owner and provider=p_provider and is_default and id<>p_id;
    update public.vimax_social_connections set is_default=true where owner_id=v_owner and provider=p_provider and id=p_id;
  end if;
  return v_count=1;
end $$;

create function public.vimax_social_connection_remove(p_provider text,p_id uuid) returns jsonb
language plpgsql security definer set search_path=pg_catalog,public as $$
declare v_owner uuid:=auth.uid();v_row public.vimax_social_connections%rowtype;
begin
  if v_owner is null then raise exception 'Authentication required'; end if;
  if p_provider not in ('tiktok','facebook') then raise exception 'Invalid provider'; end if;
  perform pg_advisory_xact_lock(hashtextextended('vimax-social:'||v_owner::text||':'||p_provider,0));
  select * into v_row from public.vimax_social_connections where id=p_id and owner_id=v_owner and provider=p_provider for update;
  if not found then return jsonb_build_object('removed',false,'reason','not_found'); end if;
  if v_row.lease_until>now() then return jsonb_build_object('removed',false,'reason','busy'); end if;
  delete from public.vimax_social_connections where id=p_id;
  return jsonb_build_object('removed',true,'external_id',v_row.external_id,'credential_cipher',v_row.credential_cipher,
    'ambiguous',v_row.lease_token is not null or v_row.status='uncertain');
end $$;

revoke all on function public.vimax_social_account_allowed(text),public.vimax_social_connection_save(text,jsonb),
  public.vimax_social_connection_claim(text,uuid),public.vimax_social_connection_finish(text,uuid,uuid,text,text,boolean),
  public.vimax_social_connection_remove(text,uuid) from public,anon,authenticated;
grant execute on function public.vimax_social_account_allowed(text),public.vimax_social_connection_save(text,jsonb),
  public.vimax_social_connection_claim(text,uuid),public.vimax_social_connection_finish(text,uuid,uuid,text,text,boolean),
  public.vimax_social_connection_remove(text,uuid) to authenticated;
