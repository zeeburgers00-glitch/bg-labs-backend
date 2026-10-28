-- Multi-Channel Intelligence: per-channel niche, audience, language, branding, content strategy, schedule.
-- Isolates each user's tokens/settings/analytics. Supports 10+ channels per user.
-- Additive: extends vimax_channels, adds analytics isolation + topic recommendations.

-- Extend existing vimax_channels with intelligence fields
alter table public.vimax_channels
  add column if not exists description text not null default '' check (char_length(description) <= 1000),
  add column if not exists content_strategy text not null default '' check (char_length(content_strategy) <= 2000),
  add column if not exists upload_schedule jsonb not null default '{}'::jsonb check (jsonb_typeof(upload_schedule) = 'object' and octet_length(upload_schedule::text) <= 2000),
  add column if not exists branding jsonb not null default '{}'::jsonb check (jsonb_typeof(branding) = 'object' and octet_length(branding::text) <= 2000),
  add column if not exists analytics_snapshot jsonb check (analytics_snapshot is null or (jsonb_typeof(analytics_snapshot) = 'object' and octet_length(analytics_snapshot::text) <= 10000)),
  add column if not exists youtube_channel_id text check (youtube_channel_id is null or youtube_channel_id ~ '^UC[A-Za-z0-9_-]{22}$'),
  add column if not exists is_connected boolean not null default false;

create unique index if not exists vimax_channels_youtube_unique on public.vimax_channels(owner_id, youtube_channel_id) where youtube_channel_id is not null;

-- Per-channel analytics cache (isolated by owner_id, never cross-user)
create table public.vimax_channel_analytics (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id uuid not null,
  metric_type text not null check (metric_type in ('views','subscribers','watch_time','videos','engagement','retention')),
  metric_value bigint not null check (metric_value >= 0),
  period_start date not null,
  period_end date not null check (period_end >= period_start),
  source text not null default 'youtube_api' check (source in ('youtube_api','manual','imported')),
  fetched_at timestamptz not null default now(),
  foreign key (channel_id, owner_id) references public.vimax_channels(id, owner_id) on delete cascade,
  unique(channel_id, metric_type, period_start)
);
create index vimax_channel_analytics_owner_idx on public.vimax_channel_analytics(owner_id, channel_id, fetched_at desc);
alter table public.vimax_channel_analytics enable row level security;
revoke all on public.vimax_channel_analytics from public, anon, authenticated;
grant select on public.vimax_channel_analytics to authenticated;
create policy vimax_channel_analytics_select_own on public.vimax_channel_analytics for select to authenticated using ((select auth.uid()) = owner_id);

-- Topic recommendations (from analytics + real research, never fabricated)
create table public.vimax_topic_recommendations (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id uuid not null,
  topic text not null check (char_length(btrim(topic)) between 1 and 500),
  rationale text not null check (char_length(rationale) between 1 and 2000),
  source_type text not null check (source_type in ('analytics','research','competitor','history')),
  source_refs jsonb not null default '[]'::jsonb check (jsonb_typeof(source_refs) = 'array' and octet_length(source_refs::text) <= 5000),
  confidence text not null check (confidence in ('low','medium','high')),
  status text not null default 'suggested' check (status in ('suggested','approved','rejected','used')),
  created_at timestamptz not null default now(),
  foreign key (channel_id, owner_id) references public.vimax_channels(id, owner_id) on delete cascade
);
create index vimax_topic_recommendations_owner_idx on public.vimax_topic_recommendations(owner_id, channel_id, created_at desc);
alter table public.vimax_topic_recommendations enable row level security;
revoke all on public.vimax_topic_recommendations from public, anon, authenticated;
grant select on public.vimax_topic_recommendations to authenticated;
create policy vimax_topic_recommendations_select_own on public.vimax_topic_recommendations for select to authenticated using ((select auth.uid()) = owner_id);

-- Guard: max 10 channels per user (matches youtube.mjs limit, enforced in DB too)
create or replace function public.vimax_guard_channel_limit() returns trigger
language plpgsql security definer set search_path = pg_catalog, public as $$
begin
  if (select count(*) from public.vimax_channels where owner_id = new.owner_id) >= 10 then
    raise exception 'Maximum 10 channels per account';
  end if;
  return new;
end $$;
drop trigger if exists vimax_channels_limit_trigger on public.vimax_channels;
create trigger vimax_channels_limit_trigger before insert on public.vimax_channels
  for each row execute function public.vimax_guard_channel_limit();
