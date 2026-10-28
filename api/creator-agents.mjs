// Role specifications are server-owned, descriptive configurations. Only the
// fixed handlers below execute; a planned specification is not an agent process,
// scheduler, permission grant or authorization to call a provider.
import {SkillError} from './skill-error.mjs';
import {runHostedSkill} from './workforce-skills.mjs';

// id, display name, distinct responsibility, input key, output key,
// required capability, success criterion. Unavailable roles fail closed.
const departments = [
  ['Executive orchestration', [
    ['studio_manager','Creator review coordinator','Run a fixed set of read-only checks on a supplied draft.','draft','review','creator_review','Requested checks return their real results with non-publishing notices.'],
    ['brief_intake','Brief intake coordinator','Identify missing audience, format and goal in a proposed brief.','brief','brief_gaps','brief_validator','Missing requirements are listed without inventing facts.'],
    ['dependency_planner','Dependency planner','Order creative tasks by their declared dependencies.','task_graph','ordered_tasks','dependency_planner','Tasks are ordered and dependency cycles are reported.'],
    ['budget_reviewer','Budget reviewer','Compare a priced job estimate against the approved spending limit.','cost_estimate','budget_decision','price_and_budget_service','Unknown prices block approval rather than being called free.'],
    ['approval_coordinator','Approval coordinator','Prepare an explicit human approval request for an external action.','proposed_action','approval_request','approval_store','The exact action and target are presented to the owner.'],
    ['job_dispatcher','Job dispatcher','Dispatch an authorized task to an available isolated worker.','authorized_task','dispatch_receipt','durable_media_queue','The worker and durable task identifier are recorded.'],
    ['progress_reporter','Progress reporter','Summarize persisted job events and current progress.','job_events','progress_summary','durable_media_events','Reported progress comes only from actual persisted events.'],
    ['recovery_coordinator','Recovery coordinator','Classify a failed task as retryable, blocked or uncertain.','failure_record','recovery_decision','job_reconciliation','Ambiguous external side effects are not blindly retried.'],
    ['cancellation_coordinator','Cancellation coordinator','Request cancellation and reconcile any in-flight work.','cancel_request','cancellation_status','worker_cancellation','The status distinguishes requested from confirmed cancellation.'],
  ]],
  ['Channel research and setup', [
    ['channel_reference','YouTube reference parser','Normalize a supplied YouTube reference without contacting it.','reference','parsed_reference','youtube_url_parser','A supported complete reference is parsed without claiming verification.'],
    ['channel_identity','Authorized channel identity reviewer','Verify an owner-selected channel against a Google grant.','channel_grant','verified_channel','youtube_authorization','Returned identity matches the separately authorized channel.'],
    ['channel_niche','Niche profile planner','Describe the target niche from the owner-provided channel brief.','niche_brief','niche_profile','channel_profile_store','The profile records supplied assumptions rather than invented data.'],
    ['audience_profile','Audience profile planner','Define an intended audience and its stated needs.','audience_brief','audience_profile','channel_profile_store','The audience description is traceable to owner input.'],
    ['language_profile','Language and locale coordinator','Capture the requested language, locale and accessibility needs.','language_request','language_profile','channel_profile_store','Language and locale are explicitly recorded.'],
    ['brand_voice','Brand voice planner','Record an owner-provided tone, vocabulary and boundaries.','brand_examples','brand_voice','channel_profile_store','The brand voice does not imitate another creator verbatim.'],
    ['channel_visual_identity','Visual identity planner','Record owner-approved colors, type and branding constraints.','brand_assets','visual_profile','licensed_asset_store','Each referenced asset has an owner or permitted source.'],
    ['channel_competitor_refs','Competitor reference librarian','Store distinct owner-provided public competitor references.','public_references','reference_list','channel_profile_store','Stored references remain separate from channel ownership.'],
    ['channel_calendar','Channel calendar coordinator','Organize owner-approved topics into a channel-specific calendar.','topic_schedule','calendar_entries','content_calendar','Dates and channel identity are preserved without publishing.'],
  ]],
  ['Trend and topic research', [
    ['idea_phrasing','Idea phrasing reviewer','Evaluate the wording of a supplied English idea using a heuristic.','idea','idea_review','idea_heuristic','A bounded wording score is returned without claiming demand or views.'],
    ['topic_source_collector','Topic source collector','Collect permitted source links for a proposed topic.','research_question','source_list','safe_public_research','Each source is reachable, attributable and date-stamped.'],
    ['trend_evidence','Trend evidence reviewer','Compare topic observations against dated public evidence.','source_list','trend_observations','safe_public_research','Observations cite dates and do not assume future popularity.'],
    ['topic_competitor_sample','Competitor sample researcher','Compile a verified public sample of competitor video metadata.','channel_reference','video_sample','youtube_public_metadata','Every item belongs to the verified channel and includes its source.'],
    ['audience_questions','Audience question researcher','Group questions from approved, attributable inputs.','question_corpus','question_clusters','rights_scoped_research','Clusters distinguish observations from assumptions.'],
    ['topic_fact_check','Topic claim verifier','Check proposed factual claims against supplied authoritative evidence.','claims_and_sources','claim_findings','citation_verifier','Unsupported or conflicting claims are flagged.'],
    ['topic_originality','Topic originality reviewer','Compare a draft idea with authorized references for duplication risk.','idea_and_refs','originality_notes','rights_scoped_research','Potential overlap is documented without copying source text.'],
    ['topic_selection','Topic selection planner','Rank explicitly supplied topics against owner-selected criteria.','topic_candidates','ranked_topics','topic_selection_workflow','Ranking explains the supplied criteria and uncertainty.'],
    ['content_history','Content history checker','Check a proposed topic against the owner channel history.','proposed_topic','history_matches','channel_content_history','Matches are restricted to the selected owner channel.'],
  ]],
  ['Scriptwriting', [
    ['hook_phrasing','Hook phrasing reviewer','Evaluate a supplied English opening with a deterministic heuristic.','hook','hook_review','hook_heuristic','The supplied hook receives a qualified, non-predictive review.'],
    ['script_outline','Script outline planner','Structure a supplied topic into an original, time-bounded outline.','topic_brief','script_outline','script_drafting','Sections meet the owner’s requested format and length.'],
    ['script_drafter','Original script drafter','Draft original narration from an approved outline and sources.','approved_outline','draft_script','script_drafting','Claims are attributed and copied narration is avoided.'],
    ['script_citations','Script citation reviewer','Map factual statements in a draft to its supporting sources.','draft_and_sources','citation_map','citation_verifier','Unverified statements are clearly marked.'],
    ['script_timing','Script timing estimator','Estimate narration duration from the draft and chosen reading rate.','narration_and_rate','timing_estimate','timing_estimator','The estimate states its assumed speech rate.'],
    ['script_clarity','Script clarity editor','Identify unclear passages and suggest clearer original wording.','script_text','clarity_edits','script_editing','Suggestions preserve meaning and do not assert fact checks.'],
    ['script_tone','Script tone editor','Compare an original script with the selected brand voice.','script_and_voice','tone_notes','script_editing','Notes cite specific wording and owner-provided preferences.'],
    ['script_structure','Narrative structure reviewer','Check a draft for an opening, development and conclusion.','script_text','structure_notes','script_editing','Missing sections are identified without fabricating content.'],
    ['script_caption_alignment','Caption alignment planner','Prepare caption segments aligned to an approved narration draft.','approved_script','caption_plan','caption_alignment','Segments correspond to the approved script and timing.'],
  ]],
  ['Visuals and stock assets', [
    ['storyboard_planner','Storyboard planner','Map each narration section to a proposed visual need.','approved_script','storyboard','storyboard_generator','Every visual cue maps to a section of the approved script.'],
    ['stock_searcher','Licensed stock researcher','Search a configured stock provider for a specific visual need.','visual_query','stock_candidates','licensed_stock_api','Results include original provider links and licensing context.'],
    ['stock_rights','Stock rights reviewer','Record source, license and limitations for a selected asset.','asset_evidence','rights_record','licensed_asset_store','The usage rights and attribution requirement are recorded.'],
    ['visual_downloader','Authorized asset retriever','Retrieve only an owner-approved, rights-cleared visual asset.','approved_asset','asset_artifact','safe_asset_fetcher','The stored artifact matches the approved asset and size limits.'],
    ['visual_duration','Visual duration planner','Assign supplied clip durations to storyboard segments.','storyboard_and_clips','visual_timeline','timeline_planner','The visual timeline covers the intended duration.'],
    ['image_generator','Image generation coordinator','Prepare an approved image-generation task with a known provider.','image_brief','image_artifact','image_generation_worker','The returned artifact and cost are verified before use.'],
    ['visual_caption_safety','Visual accessibility reviewer','Check supplied visuals for readable caption-safe space.','visual_layout','accessibility_notes','visual_analysis_worker','The review identifies overlap and contrast limitations.'],
    ['asset_deduplicator','Asset reuse checker','Find duplicate assets in the owner-authorized media set.','asset_manifest','duplicate_report','media_manifest_store','Duplicate candidates reference actual owner artifacts.'],
    ['visual_provenance','Visual provenance recorder','Attach source and usage evidence to chosen visual artifacts.','selected_visuals','visual_provenance','licensed_asset_store','Every chosen visual has a traceable source and rights record.'],
  ]],
  ['Voice and audio', [
    ['voice_selector','Voice selection planner','Match an owner-approved language and style to available voices.','voice_preferences','voice_choice','voice_catalog','Voice availability and provider costs are explicit.'],
    ['narration_synthesizer','Narration generator','Synthesize an approved script with the selected voice.','approved_script','narration_artifact','tts_worker','The actual audio artifact and provider response are recorded.'],
    ['pronunciation_editor','Pronunciation reviewer','Flag specified names or terms needing pronunciation review.','pronunciation_list','pronunciation_notes','voice_pronunciation_tool','The selected pronunciation is approved before synthesis.'],
    ['audio_duration','Audio duration inspector','Measure the duration of a generated narration artifact.','audio_artifact','measured_duration','media_probe','Duration comes from the actual artifact, not an estimate.'],
    ['audio_level','Audio level reviewer','Measure loudness and clipping on an authorized audio artifact.','audio_artifact','audio_levels','audio_analysis_worker','Measured levels and warnings are returned.'],
    ['music_researcher','Licensed music researcher','Locate music with documented rights for the project.','music_brief','music_candidates','licensed_music_catalog','Each candidate includes its source and usage terms.'],
    ['music_rights','Music rights recorder','Document the selected music license and attribution.','music_evidence','music_rights_record','licensed_asset_store','Usage and attribution requirements are explicit.'],
    ['audio_mix','Audio mixing coordinator','Mix approved narration and music to a requested level.','approved_audio_tracks','audio_mix_artifact','audio_render_worker','The produced mix is measured and saved.'],
    ['audio_qc','Audio quality reviewer','Check a rendered mix for silence, clipping and duration errors.','mixed_audio','audio_qc_report','audio_analysis_worker','The report is based on measured artifact properties.'],
  ]],
  ['Editing and rendering', [
    ['timeline_builder','Timeline builder','Assemble approved assets and narration into a timeline.','approved_assets','timeline','timeline_worker','Timeline segments refer only to approved artifacts.'],
    ['landscape_editor','Landscape editor','Prepare a landscape timeline for an approved long-form video.','landscape_timeline','landscape_edit','media_render_worker','Output dimensions and duration match the approved brief.'],
    ['shorts_editor','Shorts editor','Prepare a vertical 9:16 edit for a selected short video.','shorts_timeline','vertical_edit','media_render_worker','Actual output has the intended aspect ratio and duration.'],
    ['caption_transcriber','Caption transcriber','Transcribe authorized audio into timed caption segments.','authorized_audio','caption_segments','transcription_worker','Captions include timestamps and disclose transcription uncertainty.'],
    ['caption_renderer','Caption renderer','Burn or attach approved captions to the chosen edit.','approved_captions','captioned_video','media_render_worker','Captions are present and synchronized in the actual artifact.'],
    ['transition_editor','Transition planner','Select transitions between owner-approved timeline segments.','timeline_segments','transition_plan','timeline_worker','Transitions fit segment timing and project style.'],
    ['render_dispatcher','Render dispatcher','Send an approved bounded render job to a separate worker.','approved_render_job','render_receipt','durable_media_queue','A real worker acknowledges the durable job.'],
    ['render_inspector','Render inspector','Inspect actual duration, streams and dimensions after rendering.','rendered_video','probe_report','media_probe','A probe of the final artifact supplies its measured properties.'],
    ['video_qc','Final video quality reviewer','Check a rendered artifact against the approved production brief.','final_video_and_brief','video_qc_report','media_quality_worker','Missing streams, captions and mismatched duration are flagged.'],
  ]],
  ['Thumbnails and SEO', [
    ['title_thumbnail','Title and thumbnail text reviewer','Lint a supplied title and thumbnail text using an English heuristic.','title_and_thumbnail','title_review','title_lint','Actual text issues are returned without claiming image analysis or clicks.'],
    ['metadata_reviewer','Metadata preflight reviewer','Validate and normalize a supplied draft using the pinned metadata validator.','metadata','metadata_preview','metadata_preflight','A normalized advisory preview and warnings are returned.'],
    ['thumbnail_brief','Thumbnail brief planner','Describe an original thumbnail from an approved creative brief.','creative_brief','thumbnail_brief','thumbnail_planner','The brief avoids copying another creator’s artwork.'],
    ['thumbnail_image','Thumbnail image creator','Create an image from an approved, rights-cleared thumbnail brief.','thumbnail_brief','thumbnail_artifact','image_generation_worker','The actual image is saved with provenance.'],
    ['thumbnail_dimensions','Thumbnail dimension checker','Check an actual image against the intended upload dimensions.','thumbnail_artifact','dimension_report','image_probe','Reported dimensions come from the actual image.'],
    ['title_alternatives','Title alternatives planner','Generate original alternative titles from an approved topic.','approved_topic','title_options','title_generation','Each option is distinct and avoids unsupported promises.'],
    ['description_writer','Description writer','Draft an original description with supplied links and disclosures.','approved_script','description_draft','description_generation','Sources and required disclosures are preserved.'],
    ['tag_reviewer','Tag reviewer','Check supplied tags for relevance and size restrictions.','draft_tags','tag_review','tag_validation','The review identifies invalid or unrelated tags.'],
    ['metadata_final_check','Final metadata reviewer','Compare proposed final metadata against the approved draft.','final_metadata','final_metadata_report','approval_store','Differences are shown before any upload.'],
  ]],
  ['Upload and scheduling', [
    ['upload_permission','Upload permission verifier','Verify the chosen channel grant includes upload permission.','selected_channel','permission_result','youtube_authorization','The grant is checked for that channel before an upload.'],
    ['upload_approval','Upload approval coordinator','Present the final file and metadata for owner approval.','final_upload_package','approval_record','approval_store','Approval binds the target channel, file and privacy.'],
    ['upload_initiator','Resumable upload initiator','Create an authorized resumable upload for an approved file.','approved_upload','upload_session','youtube_resumable_upload','A real provider session is recorded without leaking its URL.'],
    ['upload_progress','Upload progress reporter','Report provider-confirmed uploaded bytes and state.','upload_session','upload_progress','youtube_resumable_upload','Progress comes from provider-confirmed offsets.'],
    ['upload_reconciler','Upload uncertainty reconciler','Check an ambiguous upload with the provider before retry.','uncertain_upload','reconciliation_result','youtube_resumable_upload','No duplicate is started without reconciliation.'],
    ['upload_thumbnail','Authorized thumbnail uploader','Apply an approved thumbnail to the verified target video.','video_and_thumbnail','thumbnail_status','youtube_thumbnail_upload','The actual provider status is recorded.'],
    ['upload_captions','Authorized caption uploader','Attach approved captions to the verified target video.','video_and_captions','caption_status','youtube_caption_upload','The actual provider response is recorded.'],
    ['publish_scheduler','Publish schedule coordinator','Prepare a supported schedule for explicit public approval.','approved_schedule','schedule_status','youtube_scheduling','The confirmed privacy and schedule match the provider response.'],
    ['upload_quota','Upload quota monitor','Record known request usage and surface unknown quota costs.','quota_observations','quota_report','quota_monitor','Unknown limits are not presented as confirmed availability.'],
  ]],
  ['Analytics and growth', [
    ['supplied_funnel','Supplied-metrics reviewer','Review manually supplied funnel metrics with qualified thresholds.','metrics','funnel_review','funnel_heuristic','Only supplied values are reviewed; Shorts context and estimates are explicit.'],
    ['analytics_consent','Analytics permission reviewer','Confirm the selected channel has separate Analytics consent.','channel_grant','analytics_permission','youtube_analytics_authorization','Missing or expired consent blocks reporting.'],
    ['analytics_fetcher','Authorized analytics reporter','Request a bounded report for the selected authorized channel.','report_request','analytics_report','youtube_analytics_api','The actual report source, period and delay are shown.'],
    ['retention_reviewer','Retention curve reviewer','Interpret a supplied authorized retention curve.','retention_curve','retention_notes','retention_analysis','Observations refer to actual curve points and avoid causal claims.'],
    ['traffic_reviewer','Traffic source reviewer','Compare authorized traffic-source metrics for a video.','traffic_report','traffic_notes','traffic_source_analysis','Source names and reporting period are preserved.'],
    ['shorts_metrics','Shorts metrics reviewer','Compare engaged views and stayed-to-watch for similar Shorts.','shorts_report','shorts_notes','shorts_analytics','Ordinary views are not substituted for engaged views.'],
    ['topic_history_analytics','Topic history reviewer','Summarize authorized historical topics and performance.','authorized_history','topic_history_notes','channel_content_history','Comparisons identify time windows and missing values.'],
    ['experiment_planner','Content experiment planner','Propose an owner-approved test based on available evidence.','evidence_and_goal','experiment_plan','experiment_planning','The hypothesis and unknowns are explicit.'],
    ['growth_reporter','Growth report coordinator','Combine verified reports with clearly labeled estimates.','authorized_reports','growth_summary','report_composition','Every metric is labeled verified, estimated or unavailable.'],
  ]],
  ['Monetization readiness', [
    ['eligibility_sources','Eligibility source librarian','Collect official, current monetization requirement sources.','region_and_program','official_requirements','official_policy_research','Each requirement cites an official dated source.'],
    ['subscriber_evidence','Subscriber evidence reviewer','Read authorized subscriber evidence for the selected channel.','subscriber_report','subscriber_status','youtube_analytics_api','The displayed count has an identified source and date.'],
    ['watch_hours_evidence','Watch-hour evidence reviewer','Identify verified eligible watch hours when available.','watch_hour_report','watch_hour_status','monetization_eligibility_api','Unavailable eligibility totals are not inferred as verified.'],
    ['shorts_views_evidence','Shorts eligibility reviewer','Identify verified eligible Shorts views when available.','shorts_eligibility_report','shorts_view_status','monetization_eligibility_api','Ordinary views are not substituted for eligible views.'],
    ['policy_checklist','Policy checklist coordinator','Prepare a checklist of official owner-facing policy requirements.','channel_context','policy_checklist','official_policy_research','The checklist identifies policy review as owner responsibility.'],
    ['rights_checklist','Rights checklist reviewer','Collect project source and license evidence for owner review.','asset_rights_records','rights_checklist','licensed_asset_store','Missing rights evidence is flagged, not approved automatically.'],
    ['account_action','Manual account action coordinator','Identify owner-only identity, tax and terms actions.','eligibility_context','manual_actions','monetization_checklist','No identity, tax or acceptance action is performed automatically.'],
    ['application_link','Application link coordinator','Direct the owner to the official application flow.','program_region','official_application_link','official_policy_research','The destination is an official current owner-facing link.'],
    ['monetization_report','Readiness report coordinator','Combine available evidence without claiming approval.','eligibility_evidence','readiness_report','report_composition','Verified data, estimates and unknowns remain separate.'],
  ]],
  ['Security and compliance', [
    ['secret_exposure','Secret exposure reviewer','Detect possible secrets in an owner-supplied draft before sharing.','draft_text','exposure_warnings','secret_scanner','Possible credentials are flagged without logging their values.'],
    ['permission_scope','Permission scope reviewer','Compare a proposed external action to its granted permissions.','action_and_grant','scope_decision','permission_engine','Actions outside the grant are denied.'],
    ['owner_isolation','Owner isolation reviewer','Verify a task references only the current owner’s resources.','owner_and_resource','isolation_decision','owner_scoped_storage','Cross-owner references fail closed.'],
    ['source_rights','Source rights reviewer','Check documented media rights before a proposed use.','asset_and_use','rights_decision','licensed_asset_store','Unknown or insufficient rights block the action.'],
    ['prompt_injection','Untrusted content reviewer','Flag instructions embedded in untrusted source material.','source_excerpt','injection_warnings','untrusted_content_guard','Source text cannot change system permissions or approval.'],
    ['url_safety','Outbound URL policy reviewer','Check a proposed network destination against an approved host policy.','outbound_request','url_decision','egress_policy','Unapproved or private destinations are blocked.'],
    ['engagement_policy','Engagement policy reviewer','Flag proposals for artificial engagement or spam.','growth_proposal','policy_warnings','compliance_rules','Fake views, likes, subscribers and spam are blocked.'],
    ['action_audit','External action auditor','Record a scoped action and its verified outcome.','action_result','audit_event','durable_audit_store','Uncertain outcomes are not labeled successful.'],
    ['retention_policy','Data retention coordinator','Apply an owner-approved retention rule to project artifacts.','retention_request','retention_result','owner_scoped_storage','Deletion affects only the specified owner resources.'],
  ]],
];

const implemented = Object.freeze({
  studio_manager:'creator_review', channel_reference:'youtube_url_parser', idea_phrasing:'idea_heuristic',
  hook_phrasing:'hook_heuristic', title_thumbnail:'title_lint', metadata_reviewer:'metadata_preflight', supplied_funnel:'funnel_heuristic',
});
const str = (max=400) => ({type:'string',maxLength:max});
const record = (properties, required=[]) => ({type:'object',additionalProperties:false,properties,required});
const metrics = record({impressions:{type:'integer',minimum:0,maximum:1e12},views:{type:'integer',minimum:0,maximum:1e12},
  ctr:{type:'number',minimum:0,maximum:100},avd_seconds:{type:'number',minimum:0,maximum:86400},
  length_seconds:{type:'number',minimum:0.001,maximum:86400}});
metrics.minProperties = 1;
const funnel = record({format:{type:'string',enum:['long','shorts']},metrics},['metrics']);
const metadata = record({title:str(100),description:str(5000),tags:str(450),categoryId:str(3),defaultLanguage:str(35)},['title']);
// Schemas describe the stable, required output keys. Some implementations also
// return optional fields; strict runtime validators remain authoritative.
const output = properties => ({type:'object',properties,required:Object.keys(properties)});
const stringOut = {type:'string'}, stringsOut = {type:'array',items:stringOut};
const scoreOut = {type:'number',minimum:0,maximum:100};
const bandOut = {type:'string',enum:['STRONG','WORKABLE','WEAK']};
const schemas = {
  studio_manager:[record({metadata,reference:str(2048),idea:str(),hook:str(),thumbnail:str(),funnel},['metadata']),
    output({status:{type:'string',enum:['review_ready','metadata_needs_changes']},steps:{type:'array',items:output({skill:stringOut,result:{type:'object'}})},notice:stringOut})],
  channel_reference:[record({reference:str(2048)},['reference']),output({canonical_url:stringOut,
    reference_kind:{type:'string',enum:['video','shorts','handle','channel','user','c']},notice:stringOut})],
  idea_phrasing:[record({idea:str()},['idea']),output({idea:stringOut,axes:{type:'object'},score:scoreOut,band:bandOut,
    life:{type:'string',enum:['timely','evergreen','mixed']},notice:stringOut})],
  hook_phrasing:[record({hook:str()},['hook']),output({hook:stringOut,properties:{type:'object'},score:scoreOut,band:bandOut,formula:stringOut,notice:stringOut})],
  title_thumbnail:[record({title:str(),thumbnail:str()},['title']),output({title:stringOut,chars:{type:'integer',minimum:0},score:scoreOut,
    issues:{type:'array',items:{type:'array',items:stringOut}},good:stringsOut,notice:stringOut})],
  metadata_reviewer:[metadata,output({valid:{type:'boolean'},errors:stringsOut,warnings:stringsOut,changes:stringsOut,preview:{type:'object'},notice:stringOut})],
  supplied_funnel:[funnel,output({format:{type:'string',enum:['long','shorts']},status:{type:'string',enum:['review','insufficient_data','partial_data','within_heuristic_bands','shorts_requires_context']},
    verdict:stringOut,links:{type:'array',items:{type:'object'}},notice:stringOut})],
};

function pendingSchema(key, description) {
  return record({[key]:{type:'string',minLength:1,maxLength:5000,description}},[key]);
}

const roles = departments.flatMap(([department, rows]) => rows.map(([id,name,responsibility,inputKey,outputKey,capability,success]) => {
  const available = Object.hasOwn(implemented,id), [input_schema,output_schema] = available ? schemas[id]
    : [pendingSchema(inputKey, `Planned input for ${name}.`), pendingSchema(outputKey, `Planned output for ${name}.`)];
  return {id,name,department,responsibility,input_schema,output_schema,
    assigned_tools:available ? [implemented[id]] : [], required_capabilities:[capability],
    dependencies:available ? ['Authenticated ViMax session','Supplied text or metrics'] : [`Not implemented: ${capability}`],
    execution_status:available ? 'implemented_read_only' : 'awaiting_integration',
    test_status:available ? 'automated_local_tests' : 'not_run',
    error_handling:available ? 'Reject invalid inputs; no network action, save or automatic retry.' : 'Fail closed; no task, provider call or external action is started.',
    success_criteria:success};
}));

export function creatorAgentRegistry() {
  return structuredClone({notice:'Role specifications are not running agents. Seven roles execute fixed, read-only checks; all other roles are awaiting integration and cannot run. No role grants YouTube or publishing permission.',
    implemented_count:Object.keys(implemented).length, planned_count:roles.length-Object.keys(implemented).length,
    departments:departments.map(([name])=>name), roles});
}

export function runCreatorAgent(id, input) {
  if (typeof id !== 'string' || !roles.some(role=>role.id === id)) throw new SkillError(404, 'That role is not in the creator registry.');
  if (!Object.hasOwn(implemented,id)) throw new SkillError(409, 'This role is awaiting integration and cannot run.');
  return runHostedSkill(implemented[id], input);
}
