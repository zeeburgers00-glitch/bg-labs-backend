-- End-to-End Video Production + Research & Fact Verification + Publishing & Approval + Budget & Monetization
-- Additive only. Validates artifacts, tracks licenses, SSRF-safe research, approval gates.

-- Research & Fact Verification: citations with timestamps, SSRF-safe URLs only
create table public.vimax_research_sources (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid,
  url text not null check (char_length(url) between 10 and 2048 and url ~ '^https://[^/]+/.+'),
  title text check (title is null or char_length(title) <= 500),
  publication_date date,
  accessed_at timestamptz not null default now(),
  claim_text text check (claim_text is null or char_length(claim_text) <= 2000),
  verification_status text not null default 'unverified' check (verification_status in ('verified','unverified','conflicting','unsupported')),
  is_trusted boolean not null default false,
  foreign key (job_id, owner_id) references public.vimax_production_jobs(id, owner_id) on delete set null
);
create index vimax_research_sources_owner_idx on public.vimax_research_sources(owner_id, job_id, accessed_at desc);
alter table public.vimax_research_sources enable row level security;
revoke all on public.vimax_research_sources from public, anon, authenticated;
grant select on public.vimax_research_sources to authenticated;
create policy vimax_research_sources_select_own on public.vimax_research_sources for select to authenticated using ((select auth.uid()) = owner_id);

-- Asset attribution & license tracking
create table public.vimax_asset_licenses (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid,
  asset_url text not null check (char_length(asset_url) between 10 and 2048),
  provider text not null check (provider in ('pexels','pixabay','unsplash','youtube_audio_library','owner_upload','other')),
  license_type text not null check (license_type in ('cc0','pexels_license','pixabay_license','unsplash_license','commercial','owner','unknown')),
  attribution_required boolean not null default false,
  attribution_text text check (attribution_text is null or char_length(attribution_text) <= 500),
  is_approved boolean not null default false,
  created_at timestamptz not null default now(),
  foreign key (job_id, owner_id) references public.vimax_production_jobs(id, owner_id) on delete set null
);
create index vimax_asset_licenses_owner_idx on public.vimax_asset_licenses(owner_id, job_id);
alter table public.vimax_asset_licenses enable row level security;
revoke all on public.vimax_asset_licenses from public, anon, authenticated;
grant select on public.vimax_asset_licenses to authenticated;
create policy vimax_asset_licenses_select_own on public.vimax_asset_licenses for select to authenticated using ((select auth.uid()) = owner_id);

-- Publishing approvals: explicit approval before public, scheduling, duplicate prevention, quota
create table public.vimax_publish_approvals (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid not null,
  upload_id uuid references public.vimax_youtube_uploads(id) on delete set null,
  channel_id text not null check (channel_id ~ '^UC[A-Za-z0-9_-]{22}$'),
  video_id text check (video_id is null or video_id ~ '^[A-Za-z0-9_-]{11}$'),
  requested_privacy text not null check (requested_privacy in ('private','unlisted','public')),
  approved_privacy text check (approved_privacy is null or approved_privacy in ('private','unlisted','public')),
  status text not null default 'pending' check (status in ('pending','approved','rejected','published','failed')),
  scheduled_at timestamptz check (scheduled_at is null or scheduled_at > now()),
  duplicate_hash text check (duplicate_hash is null or duplicate_hash ~ '^[a-f0-9]{64}$'),
  quota_checked boolean not null default false,
  approved_at timestamptz,
  approved_by uuid references auth.users(id) on delete set null,
  published_at timestamptz,
  created_at timestamptz not null default now(),
  unique(job_id, owner_id),
  unique(owner_id, duplicate_hash) where duplicate_hash is not null,
  foreign key (job_id, owner_id) references public.vimax_production_jobs(id, owner_id) on delete cascade
);
create index vimax_publish_approvals_owner_idx on public.vimax_publish_approvals(owner_id, status, created_at desc);
alter table public.vimax_publish_approvals enable row level security;
revoke all on public.vimax_publish_approvals from public, anon, authenticated;
grant select on public.vimax_publish_approvals to authenticated;
create policy vimax_publish_approvals_select_own on public.vimax_publish_approvals for select to authenticated using ((select auth.uid()) = owner_id);

-- Budget & audit trail: per-user and per-job cost limits, usage reporting, tenant isolation
create table public.vimax_budget_limits (
  owner_id uuid primary key references auth.users(id) on delete cascade,
  daily_cost_limit_cents integer not null default 500 check (daily_cost_limit_cents between 0 and 100000),
  per_job_cost_limit_cents integer not null default 100 check (per_job_cost_limit_cents between 0 and 10000),
  max_concurrent_jobs integer not null default 3 check (max_concurrent_jobs between 1 and 10),
  updated_at timestamptz not null default now()
);
alter table public.vimax_budget_limits enable row level security;
revoke all on public.vimax_budget_limits from public, anon, authenticated;
grant select on public.vimax_budget_limits to authenticated;
create policy vimax_budget_limits_select_own on public.vimax_budget_limits for select to authenticated using ((select auth.uid()) = owner_id);

create table public.vimax_usage_reports (
  id bigint generated always as identity primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid,
  provider text not null check (provider ~ '^[a-z]{1,24}$'),
  model text not null check (char_length(model) between 1 and 128),
  cost_cents integer not null check (cost_cents >= 0),
  tokens_used integer check (tokens_used is null or tokens_used >= 0),
  created_at timestamptz not null default now(),
  foreign key (job_id, owner_id) references public.vimax_production_jobs(id, owner_id) on delete set null
);
create index vimax_usage_reports_owner_idx on public.vimax_usage_reports(owner_id, created_at desc);
alter table public.vimax_usage_reports enable row level security;
revoke all on public.vimax_usage_reports from public, anon, authenticated;
grant select on public.vimax_usage_reports to authenticated;
create policy vimax_usage_reports_select_own on public.vimax_usage_reports for select to authenticated using ((select auth.uid()) = owner_id);

create table public.vimax_audit_trail (
  id bigint generated always as identity primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  action text not null check (action in ('job_created','job_cancelled','job_retried','approval_requested','approval_granted','approval_rejected','published','deleted','cost_limit_changed','channel_created','channel_deleted')),
  target_id uuid,
  target_type text check (target_type is null or target_type in ('job','channel','approval','upload','budget')),
  details jsonb check (details is null or (jsonb_typeof(details) = 'object' and octet_length(details::text) <= 5000)),
  ip_address text check (ip_address is null or char_length(ip_address) <= 45),
  created_at timestamptz not null default now()
);
create index vimax_audit_trail_owner_idx on public.vimax_audit_trail(owner_id, created_at desc);
alter table public.vimax_audit_trail enable row level security;
revoke all on public.vimax_audit_trail from public, anon, authenticated;
grant select on public.vimax_audit_trail to authenticated;
create policy vimax_audit_trail_select_own on public.vimax_audit_trail for select to authenticated using ((select auth.uid()) = owner_id);

-- Monetization readiness tracker (genuine metrics only, never fabricated)
create table public.vimax_monetization_readiness (
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id uuid not null,
  subscribers integer check (subscribers is null or subscribers >= 0),
  watch_hours_365d integer check (watch_hours_365d is null or watch_hours_365d >= 0),
  shorts_views_90d bigint check (shorts_views_90d is null or shorts_views_90d >= 0),
  videos_public integer check (videos_public is null or videos_public >= 0),
  eligibility_status text not null default 'unknown' check (eligibility_status in ('unknown','not_eligible','eligible','enabled')),
  last_checked_at timestamptz,
  youtube_studio_url text not null default 'https://studio.youtube.com/' check (youtube_studio_url ~ '^https://studio\\.youtube\\.com.*'),
  missing_requirements jsonb not null default '[]'::jsonb check (jsonb_typeof(missing_requirements) = 'array'),
  primary key(owner_id, channel_id),
  foreign key (channel_id, owner_id) references public.vimax_channels(id, owner_id) on delete cascade
);
alter table public.vimax_monetization_readiness enable row level security;
revoke all on public.vimax_monetization_readiness from public, anon, authenticated;
grant select on public.vimax_monetization_readiness to authenticated;
create policy vimax_monetization_readiness_select_own on public.vimax_monetization_readiness for select to authenticated using ((select auth.uid()) = owner_id);
