-- ViMax data is separate from the existing application's tables. All API
-- access uses the caller's Supabase Auth JWT; no service-role key is needed.
create table public.vimax_projects (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  title text not null check (char_length(btrim(title)) between 1 and 160),
  notes text not null default '' check (char_length(notes) <= 4000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index vimax_projects_owner_created_idx on public.vimax_projects (owner_id, created_at desc);
alter table public.vimax_projects enable row level security;
revoke all on public.vimax_projects from public, anon, authenticated;
grant select, delete on public.vimax_projects to authenticated;
grant insert (title, notes), update (title, notes) on public.vimax_projects to authenticated;

create policy vimax_projects_select_own on public.vimax_projects
  for select to authenticated using ((select auth.uid()) = owner_id);
create policy vimax_projects_insert_own on public.vimax_projects
  for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy vimax_projects_update_own on public.vimax_projects
  for update to authenticated using ((select auth.uid()) = owner_id)
  with check ((select auth.uid()) = owner_id);
create policy vimax_projects_delete_own on public.vimax_projects
  for delete to authenticated using ((select auth.uid()) = owner_id);

-- A per-account cap protects shared storage even when clients call the
-- Supabase REST API directly. Lock first so parallel inserts cannot bypass it.
create function public.vimax_guard_project_insert() returns trigger
language plpgsql security definer set search_path = pg_catalog, public
as $$
begin
  if auth.uid() is null or new.owner_id <> auth.uid() then
    raise exception 'Authentication is required';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(new.owner_id::text, 7039071));
  if (select count(*) from public.vimax_projects p where p.owner_id = new.owner_id) >= 100 then
    raise exception 'Project limit reached';
  end if;
  return new;
end
$$;
revoke all on function public.vimax_guard_project_insert() from public, anon, authenticated;
create trigger vimax_projects_limit before insert on public.vimax_projects
  for each row execute function public.vimax_guard_project_insert();

create function public.vimax_touch_project() returns trigger
language plpgsql set search_path = pg_catalog
as $$
begin
  new.updated_at := now();
  return new;
end
$$;
revoke all on function public.vimax_touch_project() from public, anon, authenticated;
create trigger vimax_projects_touch before update on public.vimax_projects
  for each row execute function public.vimax_touch_project();
