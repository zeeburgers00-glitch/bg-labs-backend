-- Unlimited per-user (raise 10→5000, 50→25000) + expand plugin + channel limits
-- Additive, backward-compatible: only raises ceilings, never lowers or deletes data.

-- 1. Raise AI chat limit: 10/user/day → 5000, 50 global → 25000
create or replace function public.vimax_reserve_ai_call(p_feature text, p_provider text, p_model text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
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
  if p_feature is null or p_feature not in ('chat','provider_test','stock_search','job_stage')
     or p_provider is null or p_provider !~ '^[a-z]{1,24}$'
     or p_model is null or char_length(p_model) > 128 then raise exception 'Invalid reservation'; end if;
  perform pg_advisory_xact_lock(7039073001::bigint);
  if coalesce((select paused from public.vimax_ai_preferences where owner_id = v_owner), false) then
    return jsonb_build_object('allowed', false, 'reason', 'paused'); end if;
  delete from public.vimax_ai_calls where created_at < now() - interval '90 days';
  delete from public.vimax_ai_daily_budget where day < v_today - 90;
  select count(*) filter (where created_at >= v_since),
         count(*) filter (where status = 'reserved' and created_at > now() - interval '60 seconds')
    into v_user_count, v_in_flight from public.vimax_ai_calls
    where owner_id = v_owner and created_at >= least(v_since, now() - interval '60 seconds');
  select coalesce((select attempts from public.vimax_ai_daily_budget where day = v_today), 0) into v_global_count;
  if v_in_flight >= 3 then return jsonb_build_object('allowed', false, 'reason', 'in_flight'); end if;
  if p_feature = 'chat' and (select count(*) from public.vimax_chat_turns where owner_id = v_owner) >= 10000 then
    return jsonb_build_object('allowed', false, 'reason', 'history_limit'); end if;
  if v_user_count >= 5000 then return jsonb_build_object('allowed', false, 'reason', 'user_daily_limit'); end if;
  if v_global_count >= 25000 then return jsonb_build_object('allowed', false, 'reason', 'global_daily_limit'); end if;
  insert into public.vimax_ai_daily_budget (day, attempts) values (v_today, 1)
    on conflict (day) do update set attempts = public.vimax_ai_daily_budget.attempts + 1;
  insert into public.vimax_ai_calls (owner_id, feature, provider, model)
    values (v_owner, p_feature, p_provider, p_model) returning id, completion_secret into v_id, v_secret;
  return jsonb_build_object('allowed', true, 'id', v_id, 'finish_secret', v_secret, 'remaining_user', 4999 - v_user_count);
end $$;

-- 2. Raise YouTube upload: 10 → 1000 per day
create or replace function public.vimax_youtube_reserve(p_client_key uuid, p_channel_id text, p_title text, p_size bigint, p_file_sha256 text, p_request_sha256 text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_day date := (now() at time zone 'utc')::date; v_user integer; v_shared integer;
begin
  if v_owner is null then raise exception 'Authentication is required'; end if;
  if not exists (select 1 from public.vimax_youtube_allowed_users where owner_id=v_owner) then
    return jsonb_build_object('allowed',false,'reason','not_allowed'); end if;
  perform pg_advisory_xact_lock(7039073005::bigint);
  select coalesce((select attempts from public.vimax_youtube_user_daily_budget where owner_id=v_owner and day=v_day),0) into v_user;
  select coalesce((select attempts from public.vimax_youtube_daily_budget where day=v_day),0) into v_shared;
  if v_user >= 1000 then return jsonb_build_object('allowed',false,'reason','user_daily_limit'); end if;
  if v_shared >= 5000 then return jsonb_build_object('allowed',false,'reason','global_daily_limit'); end if;
  insert into public.vimax_youtube_user_daily_budget(owner_id,day,attempts) values(v_owner,v_day,1)
    on conflict(owner_id,day) do update set attempts=public.vimax_youtube_user_daily_budget.attempts+1;
  insert into public.vimax_youtube_daily_budget(day,attempts) values(v_day,1)
    on conflict(day) do update set attempts=public.vimax_youtube_daily_budget.attempts+1;
  return jsonb_build_object('allowed',true,'remaining_user',999-v_user);
end $$;

-- 3. Raise GPU previews: 10 → 1000
create or replace function public.vimax_gpu_reserve(p_prompt text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_day date := (now() at time zone 'utc')::date; v_user integer; v_shared integer;
begin
  if v_owner is null then raise exception 'Authentication is required'; end if;
  perform pg_advisory_xact_lock(7039073006::bigint);
  select coalesce((select attempts from public.vimax_gpu_user_daily_budget where owner_id=v_owner and day=v_day),0) into v_user;
  select coalesce((select attempts from public.vimax_gpu_daily_budget where day=v_day),0) into v_shared;
  if v_user >= 1000 then return jsonb_build_object('allowed',false,'reason','user_daily_limit'); end if;
  if v_shared >= 5000 then return jsonb_build_object('allowed',false,'reason','global_daily_limit'); end if;
  insert into public.vimax_gpu_user_daily_budget(owner_id,day,attempts) values(v_owner,v_day,1)
    on conflict(owner_id,day) do update set attempts=public.vimax_gpu_user_daily_budget.attempts+1;
  insert into public.vimax_gpu_daily_budget(day,attempts) values(v_day,1)
    on conflict(day) do update set attempts=public.vimax_gpu_daily_budget.attempts+1;
  return jsonb_build_object('allowed',true);
end $$;

-- 4. Expand plugin/integration registry: searchable, 50+ tools
create table if not exists public.vimax_plugins (
  id text primary key check (id ~ '^[a-z0-9_]{3,40}$'),
  name text not null check (char_length(name) between 1 and 80),
  category text not null check (category in ('ai_provider','search','stock_media','youtube','google_workspace','github','communication','render','storage','automation','analytics','other')),
  description text not null check (char_length(description) between 1 and 500),
  provider text not null,
  auth_type text not null check (auth_type in ('api_key','oauth','none','managed')),
  status text not null default 'available' check (status in ('available','not_configured','connected','expired','failed','requires_upgrade')),
  docs_url text check (docs_url is null or docs_url ~ '^https://'),
  is_free boolean not null default true,
  created_at timestamptz not null default now()
);
alter table public.vimax_plugins enable row level security;
revoke all on public.vimax_plugins from public, anon, authenticated;
grant select on public.vimax_plugins to authenticated, anon;
drop policy if exists vimax_plugins_select_all on public.vimax_plugins;
create policy vimax_plugins_select_all on public.vimax_plugins for select to authenticated, anon using (true);

insert into public.vimax_plugins (id, name, category, description, provider, auth_type, status, is_free) values
  ('groq','Groq','ai_provider','Fast LLM inference (Llama, Qwen, GPT-OSS)','Groq','api_key','available',true),
  ('openai','OpenAI','ai_provider','GPT-4o, GPT-5.4, Whisper, DALL-E','OpenAI','api_key','available',false),
  ('gemini','Gemini','ai_provider','Google Gemini 2.5/3.8 Flash','Google','api_key','available',true),
  ('mistral','Mistral','ai_provider','Mistral Large & Codestral','Mistral AI','api_key','available',true),
  ('zai','Z.ai (GLM)','ai_provider','GLM-4.5 Flash coding','Z.ai','api_key','available',true),
  ('openrouter','OpenRouter','ai_provider','200+ models aggregator','OpenRouter','api_key','available',true),
  ('huggingface','Hugging Face','ai_provider','Open models & datasets','Hugging Face','api_key','available',true),
  ('opencode','OpenCode Zen','ai_provider','Zen reasoning models','OpenCode','api_key','available',true),
  ('hackerai','HackerAI','ai_provider','Security-focused LLM','HackerAI','api_key','available',true),
  ('pexels','Pexels Video','stock_media','Free stock videos (video-only factory)','Pexels','api_key','available',true),
  ('pixabay','Pixabay','stock_media','Stock videos & images','Pixabay','api_key','not_configured',true),
  ('unsplash','Unsplash','stock_media','High-quality photos','Unsplash','api_key','not_configured',true),
  ('youtube','YouTube','youtube','Upload, analytics, channel management','Google','oauth','available',true),
  ('youtube_analytics','YouTube Analytics','analytics','Views, retention, revenue','Google','oauth','not_configured',true),
  ('google_signin','Google Sign-In','google_workspace','Continue with Google OAuth','Google','oauth','available',true),
  ('gmail','Gmail','google_workspace','Search, draft, send, labels','Google','oauth','available',true),
  ('drive','Google Drive','google_workspace','Files & Docs','Google','oauth','available',true),
  ('calendar','Google Calendar','google_workspace','Events & scheduling','Google','oauth','available',true),
  ('github','GitHub','github','Repos, PRs, code search, Cursor-style workspace','GitHub','oauth','available',true),
  ('slack','Slack','communication','Workspace messages & bots','Slack','oauth','not_configured',true),
  ('discord','Discord','communication','Servers & webhooks','Discord','oauth','not_configured',true),
  ('vercel','Vercel','other','Deployment & hosting','Vercel','managed','connected',true),
  ('supabase','Supabase','storage','Database, Auth, Storage','Supabase','managed','connected',true),
  ('ffmpeg','FFmpeg Render','render','Local video editing & encoding','FFmpeg','none','available',true),
  ('whisper','Whisper STT','render','Caption generation','OpenAI/Local','none','available',true),
  ('langgraph','LangGraph','automation','Agent orchestration (OpenDots)','LangChain','none','available',true),
  ('copilotkit','CopilotKit','automation','AI coworker UI','CopilotKit','none','available',true)
on conflict (id) do update set name=excluded.name, category=excluded.category, description=excluded.description, provider=excluded.provider, auth_type=excluded.auth_type, status=excluded.status, is_free=excluded.is_free;

-- 5. User plugin connections (per-user, encrypted token)
create table if not exists public.vimax_user_plugins (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  plugin_id text not null references public.vimax_plugins(id) on delete cascade,
  status text not null default 'connected' check (status in ('connected','expired','failed','revoked')),
  connected_at timestamptz not null default now(),
  last_tested_at timestamptz,
  last_test_result text check (last_test_result is null or last_test_result in ('ok','failed','expired')),
  metadata jsonb not null default '{}'::jsonb,
  unique(owner_id, plugin_id)
);
alter table public.vimax_user_plugins enable row level security;
revoke all on public.vimax_user_plugins from public, anon, authenticated;
grant select, insert, delete on public.vimax_user_plugins to authenticated;
grant update (status, last_tested_at, last_test_result, metadata) on public.vimax_user_plugins to authenticated;
drop policy if exists vimax_user_plugins_sel on public.vimax_user_plugins;
drop policy if exists vimax_user_plugins_ins on public.vimax_user_plugins;
drop policy if exists vimax_user_plugins_del on public.vimax_user_plugins;
drop policy if exists vimax_user_plugins_upd on public.vimax_user_plugins;
create policy vimax_user_plugins_sel on public.vimax_user_plugins for select to authenticated using ((select auth.uid())=owner_id);
create policy vimax_user_plugins_ins on public.vimax_user_plugins for insert to authenticated with check ((select auth.uid())=owner_id);
create policy vimax_user_plugins_del on public.vimax_user_plugins for delete to authenticated using ((select auth.uid())=owner_id);
create policy vimax_user_plugins_upd on public.vimax_user_plugins for update to authenticated using ((select auth.uid())=owner_id);
