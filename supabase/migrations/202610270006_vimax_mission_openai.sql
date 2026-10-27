-- Add OpenAI to the existing planning queue without changing its limits or grants.
create or replace function public.vimax_mission_submit(p_channel_id uuid, p_client_key uuid, p_topic text, p_provider text, p_model text, p_not_before timestamptz default null)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_owner uuid := auth.uid(); v_job public.vimax_mission_jobs%rowtype; v_profile public.vimax_channels%rowtype; v_snapshot jsonb; v_when timestamptz := coalesce(p_not_before,now());
begin
  if v_owner is null then raise exception 'Authentication is required'; end if;
  if p_channel_id is null or p_client_key is null or p_topic is null or char_length(btrim(p_topic)) not between 1 and 1600
    or p_provider is null or p_provider not in ('openai','groq','gemini','mistral','zai','openrouter','huggingface','opencode')
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
