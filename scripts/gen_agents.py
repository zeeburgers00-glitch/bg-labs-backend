#!/usr/bin/env python3
"""Generate catalog/agents.json — the 120-agent workforce registry.

Re-runnable: definitions live here, output is deterministic JSON.
Tool names must exist in lib/agents.mjs TOOL_MANIFEST (enforced by
test/agent-workforce.test.mjs).
"""
from __future__ import annotations
import json, collections, pathlib

DEPTS = {
    "A": "Executive Planning and Orchestration",
    "B": "Channel Creation and Strategy",
    "C": "Trends and Topic Research",
    "D": "Scriptwriting",
    "E": "Visual Production",
    "F": "Voice and Audio",
    "G": "Video Editing and Rendering",
    "H": "Thumbnails and Packaging",
    "I": "Publishing and Scheduling",
    "J": "Growth and Analytics",
    "K": "Monetization Readiness",
    "L": "Infrastructure, Security, and Compliance",
}
WRK = "planning worker not hosted"
YTS = "VIMAX_YOUTUBE_CLIENT_SECRET not configured in Vercel"
CLI = ["sandbox-local-cli"]
LOC = ["local-companion"]
BR = ["vercel-bridge"]

# (title, responsibility, tools, capability, gated_by, inputs, outputs, deps, success)
ROWS = [
("CEO Orchestrator Agent","Set channel mission objectives, authorise plans and require human sign-off before anything public",["bridge:mission-create","bridge:mission-events","gate:human-approval"],"config-gated",WRK,["objective","channel_id"],["mission_plan","approval_requests"],["B10"],"mission row created with stages and approval flag"),
("Task Decomposition Agent","Break an approved objective into ordered, independently testable mission stages",["bridge:mission-create","bridge:mission-events"],"config-gated",WRK,["mission_plan"],["stage_graph"],[],"every stage lists inputs, outputs and owner"),
("Workflow Planning Agent","Order stages so dependencies resolve before side effects and retries stay idempotent",["bridge:mission-create"],"config-gated",WRK,["stage_graph"],["workflow"],[],"workflow validates with no cyclic dependencies"),
("Agent Assignment Agent","Map each stage to exactly one registered agent with the required tool permissions",["bridge:mission-events"],"config-gated",WRK,["workflow"],["assignments"],[],"each stage maps to one agent id from the registry"),
("Dependency Management Agent","Track cross-stage inputs and block downstream stages until artefacts exist",["bridge:mission-events"],"config-gated",WRK,["assignments"],["dependency_map"],[],"blocked stage never runs before its input artefact"),
("Budget and Cost Control Agent","Enforce per-user and shared daily attempt budgets before new provider calls",["bridge:usage-report"],"wired",None,["estimate"],["budget_decision"],[],"call rejected server-side once daily attempts exhausted"),
("Priority Management Agent","Reorder queued missions by owner priority without violating dependencies",["bridge:mission-create","bridge:mission-events"],"config-gated",WRK,["queue"],["priority_order"],[],"priority change does not break stage ordering"),
("Progress Monitoring Agent","Summarise live mission stage states, lease health and failure counts",["bridge:mission-events"],"config-gated",WRK,["mission_id"],["progress_report"],[],"report matches stage rows and events exactly"),
("Failure Recovery Agent","Classify failed stages, apply bounded retries and mark ambiguous outcomes uncertain",["bridge:mission-events","bridge:usage-report"],"config-gated",WRK,["failure"],["recovery_decision"],[],"no automatic replay of ambiguous billable calls"),
("Final Quality Approval Agent","Verify the artefact checklist of a finished mission and hold it for owner approval",["gate:human-approval","bridge:mission-events"],"config-gated",WRK,["artefacts"],["approval_decision"],[],"mission stays awaiting-approval until owner acts"),
("Niche Discovery Agent","Propose channel niches from owner inputs using structured scoring, never invented demand data",["bridge:channel-profiles","skill:ideascore"],"wired",None,["interests"],["niche_options"],[],"each option carries a scored rationale string"),
("Market Research Agent","Collect owner-provided market notes into the channel profile; no fabricated market figures",["bridge:channel-profiles","bridge:projects-notes"],"wired",None,["niche"],["market_notes"],[],"profile stores cited owner-supplied notes only"),
("Competitor Analysis Agent","Maintain the owner-curated competitor URL list and snapshot what the owner pastes",["bridge:competitors"],"wired",None,["competitor_urls"],["competitor_list"],[],"only owner-approved URLs stored with timestamps"),
("Audience Persona Agent","Draft audience personas from owner research and record the source of every claim",["bridge:channel-profiles"],"wired",None,["market_notes"],["personas"],[],"persona fields mark unverified assumptions"),
("Channel Name Generator Agent","Generate name candidates and lint each for length, readability and duplication risks",["skill:title-lint","bridge:channel-profiles"],"wired",None,["niche"],["name_candidates"],[],"every candidate passes title lint or is flagged"),
("Brand Identity Agent","Record brand voice, tone and visual rules in the channel profile for downstream agents",["bridge:channel-profiles"],"wired",None,["personas"],["brand_voice"],[],"brand rules consumed by script and packaging stages"),
("Channel Description Agent","Draft a channel description within YouTube limits with honest positioning",["bridge:channel-profiles","skill:title-lint"],"wired",None,["brand_voice"],["description_draft"],[],"description within limits and free of guaranteed-outcome claims"),
("Channel Keywords Agent","Compile channel keywords from niche and description without keyword-stuffing",["bridge:channel-profiles"],"wired",None,["description_draft"],["keyword_set"],[],"keyword list under limit and deduplicated"),
("Channel Banner and Logo Agent","Prepare banner/logo briefs and track generation once an image provider is configured",["bridge:channel-profiles","external:comfyui"],"config-gated","image generation provider not configured; ComfyUI requires GPU hardware",["brand_voice"],["asset_briefs"],[],"brief stored; render marked unavailable until provider added"),
("Channel Setup Checklist Agent","Assemble the owner-action checklist for steps the YouTube API cannot perform",["bridge:channel-profiles","gate:human-approval"],"wired",None,["profile"],["checklist"],[],"checklist separates API-done items from owner-manual items"),
("YouTube Trend Research Agent","Fetch YouTube trending or topic data once an authorised data source is connected",["bridge:youtube-analytics"],"config-gated",YTS,["region"],["trend_snapshot"],[],"snapshot cites source and time or reports unavailable"),
("Google Trends Research Agent","Read Google Trends through a configured research provider only",["external:web-search"],"planned","web research provider not integrated (SearXNG/crawl4ai pending)",["niche"],["trend_series"],[],"no trend numbers without a fetched source"),
("Search Demand Analysis Agent","Compute demand signals from owner-supplied or fetched query data with provenance",["external:web-search"],"planned","web research provider not integrated",["keywords"],["demand_report"],[],"every demand value links to a source URL or is marked estimated"),
("Competitor Video Research Agent","Organise competitor video metadata the owner exports; no scraping of private data",["bridge:competitors","bridge:projects-notes"],"wired",None,["competitor_list"],["video_matrix"],[],"matrix built only from owner-supplied exports"),
("Topic Scoring Agent","Score topic candidates with the local idea heuristic and record advisory bands",["skill:ideascore"],"wired",None,["topic_candidates"],["scored_topics"],[],"each candidate has a stored score with advisory notice"),
("Audience Question Research Agent","Collect real audience questions from owner-provided comments and searches",["bridge:projects-notes"],"wired",None,["comments_export"],["question_bank"],[],"questions retain their original source text"),
("Evergreen Topic Agent","Flag topics as evergreen only against stored evidence, not by assertion",["skill:ideascore","bridge:projects-notes"],"wired",None,["scored_topics"],["evergreen_list"],[],"evergreen flag includes supporting note"),
("News Verification Agent","Mark time-sensitive claims as requiring current-source verification by the owner",["bridge:projects-notes","gate:human-approval"],"wired",None,["script_draft"],["verification_flags"],[],"no news claim passes without a source or explicit flag"),
("Fact-Checking Agent","Inventory factual claims in drafts and require sources before they are stated as fact",["bridge:projects-notes","gate:human-approval"],"wired",None,["script_draft"],["claim_register"],[],"unsourced claims are flagged, never asserted"),
("Topic Selection Agent","Choose the final topic by combining scores, evergreen status and verification flags",["skill:ideascore","bridge:mission-events"],"wired",None,["scored_topics","evergreen_list","verification_flags"],["selected_topic"],[],"selection rationale stored with the chosen topic"),
("Video Outline Agent","Build a beat-by-beat outline from the selected topic inside the target duration",["worker:mission-run","bridge:projects-notes"],"config-gated",WRK,["selected_topic"],["outline"],[],"outline has ordered beats with time budgets"),
("Long-Form Script Agent","Draft the full narration script stage of the mission queue for owner review",["worker:mission-run"],"config-gated",WRK,["outline"],["script_draft"],[],"script stored as a mission step artefact"),
("Shorts Script Agent","Draft a compressed Shorts script with a hook inside the first seconds",["worker:mission-run"],"config-gated",WRK,["selected_topic"],["shorts_script"],[],"shorts script under target duration with early hook"),
("Storytelling Agent","Apply narrative structure of setup, tension and payoff to outline revisions",["worker:mission-run"],"config-gated",WRK,["outline"],["structured_outline"],[],"beats map to narrative roles explicitly"),
("Hook and Opening Agent","Generate hook variants and score each with the local hook heuristic before selection",["skill:hookscore","worker:mission-run"],"wired",None,["topic"],["hook_variants","hook_scores"],[],"at least two scored hook variants stored with panels"),
("Retention Optimization Agent","Read owner-provided retention exports to locate leaks and suggest script fixes",["skill:retention"],"wired",None,["retention_csv"],["retention_findings"],[],"findings cite timestamps from the export"),
("Educational Content Agent","Restructure drafts into teaching sequences with checks for understanding",["worker:mission-run"],"config-gated",WRK,["script_draft"],["lesson_script"],[],"each concept has an example and a recap"),
("Documentary Script Agent","Assemble sourced narrative scripts that separate fact from interpretation",["worker:mission-run","bridge:projects-notes"],"config-gated",WRK,["claim_register"],["documentary_script"],[],"every factual segment carries a source note"),
("Dialogue and Narration Agent","Adapt scripts to spoken-word rhythm and mark pronunciation risk words",["skill:voiceprint","worker:mission-run"],"config-gated",WRK,["script_draft"],["narration_script"],[],"filler rate and sentence lengths recorded"),
("Script Originality and Quality Agent","Run originality and quality checks against competitor material the owner supplies",["skill:ideascore","skill:voiceprint","gate:human-approval"],"wired",None,["script_draft","competitor_list"],["quality_report"],[],"report flags imitation risk and requires owner sign-off"),
("Storyboard Agent","Convert approved scripts into shot lists with an on-screen description per beat",["local:pipeline"],"config-gated","local companion dependencies not installed (Piper/FFmpeg/python env)",["script_draft"],["storyboard"],[],"every beat has an on-screen description"),
("Scene Planning Agent","Plan scene order, durations and transitions against the storyboard",["local:pipeline"],"config-gated","local companion dependencies not installed",["storyboard"],["scene_plan"],[],"scene durations sum to target runtime"),
("AI Image Generation Agent","Generate visuals through a configured provider only; never fake output",["external:comfyui","bridge:gpu-preview"],"config-gated","image and video providers not configured; ComfyUI needs GPU, Runpod needs key plus flag",["scene_plan"],["image_assets"],[],"provider availability confirmed before promising images"),
("AI Video Generation Agent","Request optional GPU clip previews with cost display and approval before spend",["bridge:gpu-preview"],"config-gated","VIMAX_GPU_ENABLED=false and RUNPOD_API_KEY missing",["scene_plan"],["video_clips"],[],"no job without enabled flag, key and owner approval"),
("Stock Footage Research Agent","Search Pexels once a key is configured and record licence terms per asset",["api:pexels"],"config-gated","PEXELS_API_KEY not configured",["scene_plan"],["stock_candidates"],[],"each candidate stores URL, owner and licence"),
("Stock Image Research Agent","Source still images from configured free providers with licence capture",["api:pexels"],"config-gated","PEXELS_API_KEY not configured",["scene_plan"],["image_candidates"],[],"licence metadata present for every candidate"),
("Visual Asset Licensing Agent","Maintain the licence register and block assets whose terms are unknown",["bridge:projects-notes","gate:human-approval"],"wired",None,["stock_candidates","image_candidates"],["licence_register"],[],"asset without known licence cannot reach render"),
("B-Roll Selection Agent","Match B-roll candidates to script beats and mark unmatched beats for fill",["local:pipeline"],"config-gated","local companion dependencies not installed",["scene_plan","stock_candidates"],["broll_map"],[],"every beat has B-roll or an explicit gap flag"),
("Animation Agent","Produce motion and transition specs for the renderer from the scene plan",["local:pipeline","external:comfyui"],"config-gated","local companion dependencies not installed; GPU providers unavailable",["scene_plan"],["motion_specs"],[],"specs reference renderer-supported effects only"),
("Visual Continuity Agent","Check style consistency across shots using stored style rules and reports",["bridge:projects-notes","skill:scene-cuts"],"wired",None,["image_assets","brand_voice"],["continuity_report"],[],"style violations listed with shot references"),
("Text-to-Speech Agent","Produce voiceovers with the configured local TTS engine after verifying availability",["local:pipeline","external:kokoro-tts"],"config-gated","Piper and Kokoro not installed here; svai TTS edge function pending security hardening",["narration_script"],["voiceover_audio"],[],"audio generated only when engine present, else marked unavailable"),
("Voice Selection Agent","Select among browser voices with language fit and record the chosen voice id",["bridge:chat-history"],"wired",None,["language_pref"],["voice_choice"],[],"selection limited to voices actually available on the device"),
("Pronunciation Correction Agent","Flag risky words and store phonetic hints for the TTS input",["skill:voiceprint","local:pipeline"],"config-gated","local companion dependencies not installed",["narration_script"],["pronunciation_map"],[],"every flagged word has a stored hint"),
("Voice Timing Agent","Estimate runtime at 150 words per minute and warn when script exceeds target duration",["skill:voiceprint"],"wired",None,["narration_script"],["timing_plan"],[],"runtime estimate stored before rendering"),
("Background Music Agent","Attach music only from sources with recorded licences; keep music optional",["bridge:projects-notes"],"wired",None,["scene_plan"],["music_plan"],[],"track without licence record blocks the step"),
("Sound Effects Agent","Plan SFX cues against beats using only cleared libraries",["bridge:projects-notes"],"wired",None,["scene_plan"],["sfx_plan"],[],"each cue references a cleared source or is dropped"),
("Audio Cleanup Agent","Schedule noise reduction and cleanup passes in the local render pipeline",["local:pipeline"],"config-gated","local companion dependencies not installed",["voiceover_audio"],["clean_audio"],[],"cleanup settings logged with the artefact"),
("Loudness Normalization Agent","Normalize loudness to YouTube targets inside the render step",["local:pipeline"],"config-gated","local companion dependencies not installed",["clean_audio"],["master_audio"],[],"measured loudness within target range"),
("Music Licensing Verification Agent","Verify and store licence text for every audio asset before use",["bridge:projects-notes","gate:human-approval"],"wired",None,["music_plan","sfx_plan"],["licence_proof"],[],"missing licence proof holds the asset"),
("Audio Quality Agent","Inspect final audio for clipping, sync drift and silence anomalies",["local:pipeline","skill:deadair"],"config-gated","local companion dependencies not installed",["master_audio"],["audio_report"],[],"report lists defects with timestamps"),
("Long-Form Editor Agent","Assemble long-form timelines from approved scene and audio artefacts",["local:pipeline"],"config-gated","local companion dependencies not installed",["scene_plan","master_audio"],["long_cut"],[],"assembly completes with approved assets only"),
("Shorts Editor Agent","Assemble vertical 9 by 16 Shorts cuts with early-hook pacing",["local:pipeline"],"config-gated","local companion dependencies not installed",["shorts_script","scene_plan"],["shorts_cut"],[],"output matches Shorts aspect and duration targets"),
("Scene Assembly Agent","Stitch scenes with transitions and keep the frame timeline continuous",["local:pipeline"],"config-gated","local companion dependencies not installed",["scene_plan"],["video_cut"],[],"stitched timeline passes duration checks"),
("Subtitle Synchronization Agent","Generate SRT or VTT from transcript timing and verify cue alignment",["local:pipeline","skill:chapters"],"config-gated","local companion dependencies not installed",["narration_script","video_cut"],["subtitle_file"],[],"cue offsets validated against audio"),
("Automatic Caption Agent","Transcribe audio locally with Whisper-family models when installed",["external:faster-whisper"],"config-gated","faster-whisper model not installed",["master_audio"],["captions"],[],"captions produced only from real audio"),
("Vertical Reframing Agent","Reframe 16:9 sources to 9:16 with subject-safe cropping rules",["local:pipeline"],"config-gated","local companion dependencies not installed",["long_cut"],["vertical_cut"],[],"reframe keeps subject within safe area"),
("Transition and Motion Graphics Agent","Apply approved transitions and reject decorative motion that harms retention",["local:pipeline"],"config-gated","local companion dependencies not installed",["video_cut"],["graphics_pass"],[],"transition list stored with rationale"),
("Color and Image Quality Agent","Run colour and exposure checks and record corrective filters per shot",["local:pipeline"],"config-gated","local companion dependencies not installed",["video_cut"],["colour_report"],[],"no shot silently exceeds luma limits"),
("FFmpeg Rendering Agent","Execute the bounded FFmpeg render for approved inputs with logged settings",["local:pipeline"],"config-gated","local companion dependencies not installed (imageio-ffmpeg exists only in companion env)",["video_cut","master_audio"],["render_mp4"],[],"render exits zero with matching audio and video duration"),
("Final Video Inspection Agent","Verify container duration, streams, resolution and checksum before approval",["local:pipeline","skill:deadair"],"config-gated","local companion dependencies not installed",["render_mp4"],["inspection_report"],[],"report must pass every hard check"),
("Thumbnail Concept Agent","Draft thumbnail concepts tied to the title and hook promise",["skill:title-lint","bridge:projects-notes"],"wired",None,["title","hook_variants"],["thumbnail_concepts"],[],"concepts consistent with title promise"),
("Thumbnail Image Generation Agent","Render thumbnails via configured image provider or local tool when available",["external:comfyui","local:pipeline"],"config-gated","image provider not configured; GPU unavailable",["thumbnail_concepts"],["thumbnail_images"],[],"no thumbnail claimed without an actual image file"),
("Thumbnail Text Agent","Shorten thumbnail text to readable limits and lint contrast rules",["skill:title-lint"],"wired",None,["thumbnail_concepts"],["thumbnail_text"],[],"text within mobile readability limit"),
("Thumbnail Composition Agent","Compose final thumbnail layout with brand rules and safe margins",["local:pipeline","external:comfyui"],"config-gated","image tooling not available in this environment",["thumbnail_images","thumbnail_text"],["composed_thumbnail"],[],"composed file passes dimension checks"),
("Title Generation Agent","Generate title variants and lint each against the paired thumbnail",["skill:title-lint","worker:mission-run"],"wired",None,["script_draft","composed_thumbnail"],["title_variants"],[],"top variants linted as pairings, not standalone"),
("Title Variant Testing Agent","Rank title variants by lint results and record why each ranks where it does",["skill:title-lint"],"wired",None,["title_variants"],["title_ranking"],[],"ranking includes stored lint evidence"),
("Description Writing Agent","Draft the description with hook, timestamps and honest claims only",["worker:mission-run","skill:title-lint"],"config-gated",WRK,["script_draft"],["description_draft"],[],"description within limits and no invented links"),
("Chapters and Timestamps Agent","Generate validated chapter marks that will render on YouTube",["skill:chapters"],"wired",None,["transcript"],["chapter_marks"],[],"chapters pass YouTube rendering rules or are marked invalid"),
("Tags and Hashtags Agent","Build tag sets within YouTube limits, deduplicated and niche-relevant",["worker:mission-run","bridge:channel-profiles"],"config-gated",WRK,["description_draft"],["tag_set"],[],"tags under 500 characters and unique"),
("Metadata Validation Agent","Validate the final metadata bundle against platform limits and policy checks",["skill:title-lint","gate:human-approval"],"wired",None,["title_variants","description_draft","tag_set","composed_thumbnail"],["metadata_bundle"],[],"bundle passes validation before upload stage"),
("Upload Preparation Agent","Assemble the upload payload with private privacy and idempotency keys",["bridge:youtube-upload","bridge:mission-events"],"config-gated",YTS,["render_mp4","metadata_bundle"],["upload_payload"],[],"payload hashed for duplicate prevention"),
("YouTube OAuth and Permission Agent","Manage per-channel consent, scope checks and encrypted grant storage",["bridge:youtube-oauth","bridge:youtube-status"],"config-gated",YTS,["channel_id"],["grant_status"],[],"grant verified against allowlist before any upload"),
("Channel Destination Verification Agent","Confirm the target channel id matches the selected connection before upload",["bridge:youtube-status","gate:human-approval"],"wired",None,["upload_payload","grant_status"],["destination_check"],[],"mismatched destination blocks the upload"),
("Video Upload Agent","Execute resumable upload with progress, retry and cancellation",["bridge:youtube-upload"],"config-gated",YTS,["upload_payload","destination_check"],["upload_record"],[],"video_id recorded or failure stored with retry state"),
("Playlist Management Agent","Add uploaded videos to owner-defined playlists through the official API",["bridge:youtube-upload"],"config-gated",YTS,["upload_record"],["playlist_ops"],[],"playlist changes limited to owner-approved lists"),
("Publishing Schedule Agent","Schedule publication times via mission not_before after approval",["bridge:mission-create","gate:human-approval"],"config-gated",WRK,["upload_record","approval"],["schedule"],[],"nothing public without recorded approval"),
("Subtitle Upload Agent","Attach subtitle files through the API where supported",["bridge:youtube-upload"],"config-gated",YTS,["subtitle_file","upload_record"],["caption_upload"],[],"caption upload result recorded honestly"),
("Thumbnail Upload Agent","Set custom thumbnails through the API after approval",["bridge:youtube-upload","gate:human-approval"],"config-gated",YTS,["composed_thumbnail","upload_record"],["thumbnail_upload"],[],"thumbnail change only on approved video"),
("Upload Status Verification Agent","Poll upload and processing state until terminal, with timeout",["bridge:youtube-upload","bridge:mission-events"],"config-gated",YTS,["upload_record"],["status_report"],[],"terminal states reached or reported stuck"),
("Publishing Error Recovery Agent","Classify upload failures and require review before expensive retries",["bridge:youtube-upload","gate:human-approval"],"config-gated",YTS,["status_report"],["recovery_action"],[],"no duplicate uploads after ambiguous failures"),
("YouTube Analytics Agent","Fetch authorised channel metrics when analytics flag and consent are enabled",["bridge:youtube-analytics"],"config-gated","VIMAX_YOUTUBE_ANALYTICS_ENABLED=false; separate read-only consent required",["channel_id"],["analytics_snapshot"],[],"metrics labelled confirmed versus unavailable"),
("Click-Through Rate Analysis Agent","Analyse CTR from real analytics or owner-pasted stats, else report unavailable",["skill:funnel","bridge:youtube-analytics"],"config-gated","YouTube Analytics API not enabled; local funnel works on pasted stats",["stats_input"],["ctr_report"],[],"no CTR number without a source"),
("Audience Retention Agent","Parse owner-provided retention exports into hook leak, cliff and slide findings",["skill:retention"],"wired",None,["retention_csv"],["retention_findings"],[],"findings cite exact timestamps"),
("Watch-Time Analysis Agent","Compute watch-time summaries from authorised analytics or mark unavailable",["bridge:youtube-analytics"],"config-gated","YouTube Analytics API not enabled",["analytics_snapshot"],["watchtime_report"],[],"estimates clearly separated from confirmed data"),
("Subscriber Growth Agent","Track subscriber deltas over time with confirmed data only",["bridge:youtube-analytics"],"config-gated","YouTube Analytics API not enabled",["analytics_snapshot"],["growth_report"],[],"no projected subscriber claims"),
("Content Performance Agent","Rank videos by outlier multiple over the channel's own median",["skill:funnel","bridge:youtube-analytics"],"config-gated","Analytics API not enabled; manual stats accepted via funnel tool",["stats_input"],["performance_ranking"],[],"ranking uses own-channel baselines, not raw views"),
("Publishing Time Analysis Agent","Correlate publish slots with performance from recorded history",["bridge:projects-notes","bridge:youtube-analytics"],"config-gated","Analytics API not enabled",["schedule","analytics_snapshot"],["timing_insights"],[],"insights require real datapoints"),
("Content Experiment Agent","Define measurable A/B experiments and record outcomes without guarantees",["bridge:projects-notes","gate:human-approval"],"wired",None,["hypothesis"],["experiment_plan"],[],"experiment has metric, window and stop rule"),
("Underperforming Video Diagnosis Agent","Diagnose weak performers from available signals and label missing data",["skill:funnel","skill:retention"],"wired",None,["stats_input","retention_csv"],["diagnosis"],[],"diagnosis lists which signals were unavailable"),
("Growth Strategy Agent","Recommend next-video actions grounded in stored reports, never virality promises",["bridge:projects-notes","skill:ideascore"],"wired",None,["diagnosis","performance_ranking"],["strategy_notes"],[],"recommendations cite stored reports"),
("YouTube Partner Program Eligibility Agent","Display official eligibility criteria beside confirmed metrics; never guarantee acceptance",["bridge:youtube-analytics","bridge:projects-notes"],"config-gated","Analytics API not enabled; eligibility needs owner confirmation",["analytics_snapshot"],["eligibility_view"],[],"criteria marked confirmed, estimated or unavailable"),
("Public Watch-Hour Tracking Agent","Track public watch hours from confirmed analytics only",["bridge:youtube-analytics"],"config-gated","YouTube Analytics API not enabled",["analytics_snapshot"],["watchhours_tracker"],[],"no rounding up to threshold"),
("Valid Shorts Views Tracking Agent","Track eligible Shorts views when the official metric is available",["bridge:youtube-analytics"],"config-gated","YouTube Analytics API not enabled",["analytics_snapshot"],["shorts_views_tracker"],[],"metric absent means unavailable, not estimated"),
("Subscriber Eligibility Tracking Agent","Show current subscribers against threshold with source timestamp",["bridge:youtube-analytics","bridge:youtube-status"],"config-gated","Analytics API not enabled",["analytics_snapshot"],["subscriber_tracker"],[],"snapshot carries source time"),
("Originality and Reused Content Review Agent","Run advisory originality checks and assemble owner review evidence",["skill:ideascore","skill:voiceprint","gate:human-approval"],"wired",None,["script_draft","render_mp4"],["originality_review"],[],"review flags reuse risk; owner confirms"),
("Copyright Risk Review Agent","Inventory third-party assets and their licences; block unknowns",["bridge:projects-notes","gate:human-approval"],"wired",None,["licence_register","music_plan"],["copyright_review"],[],"any unknown licence halts readiness"),
("Community Guidelines Review Agent","Check content against a policy checklist and require owner attestation",["bridge:projects-notes","gate:human-approval"],"wired",None,["metadata_bundle","render_mp4"],["policy_review"],[],"attestation stored with checklist answers"),
("Monetization Policy Checklist Agent","Assemble the full readiness checklist with per-item evidence links",["bridge:projects-notes"],"wired",None,["eligibility_view","copyright_review","policy_review"],["readiness_checklist"],[],"every item links to evidence or is marked missing"),
("Monetization Application Preparation Agent","Prepare application materials; the owner submits in YouTube Studio",["bridge:projects-notes","gate:human-approval"],"wired",None,["readiness_checklist"],["application_packet"],[],"packet marked draft; no submission claimed"),
("Monetization Status Monitoring Agent","Record owner-reported application status; official status only via supported data",["bridge:projects-notes","bridge:youtube-analytics"],"config-gated","no supported API for application status; owner input required",["owner_status"],["status_monitor"],[],"status provenance always recorded"),
("API Integration Agent","Maintain fixed-host provider adapters, OAuth callbacks and health checks",["bridge:health","bridge:providers-test"],"wired",None,["provider_config"],["integration_health"],[],"health endpoint reports each configured adapter"),
("Database Management Agent","Apply additive migrations with RLS preserved and no destructive SQL",["bridge:health"],"wired",None,["migration_plan"],["migration_state"],[],"migrations additive; RLS tests pass"),
("Background Job Queue Agent","Operate the mission queue leases, heartbeats and cancellation",["worker:mission-run","bridge:mission-events"],"config-gated",WRK,["jobs"],["queue_state"],[],"leases expire safely with no double execution"),
("Secret and Credential Security Agent","Keep secrets in server-side sensitive env vars and cipher columns only",["bridge:health","bridge:usage-report"],"wired",None,["secret_inventory"],["security_state"],[],"no secret in client bundle or logs"),
("Storage and Asset Cleanup Agent","Prune expired artefacts with retention rules once object storage exists",["bridge:projects-notes"],"planned","per-user object storage not implemented yet",["artefact_list"],["cleanup_plan"],[],"deletion requires retention window and owner rule"),
("Retry and Recovery Agent","Apply bounded retries with backoff and mark ambiguous outcomes uncertain",["bridge:mission-events","bridge:usage-report"],"config-gated",WRK,["failure"],["retry_decision"],[],"no retry storms; attempts capped per stage"),
("System Health Monitor Agent","Expose service health, database status and queue liveness",["bridge:health"],"wired",None,[],["health_report"],[],"health endpoint answers with component states"),
("Cost and Usage Reporting Agent","Report attempt counts and provider-reported tokens without fake money precision",["bridge:usage-report"],"wired",None,[],["usage_report"],[],"report matches recorded attempts and tokens"),
("Audit Log Agent","Record sensitive operations for review once database audit logging is enabled",["bridge:mission-events"],"planned","postgres audit logging currently disabled",["operations"],["audit_entries"],[],"entries immutable and user-scoped"),
("Human Approval and Safety Gate Agent","Hold every public or destructive action until explicit owner confirmation",["gate:human-approval","bridge:mission-events"],"wired",None,["pending_action"],["approval_record"],[],"no public action without stored approval record"),
]

assert len(ROWS) == 120, len(ROWS)
assert len({r[0] for r in ROWS}) == 120, "agent names must be distinct"
assert len({r[1] for r in ROWS}) == 120, "responsibilities must be distinct"

RUNS = {"wired": {"all-skill": CLI}, "config-gated": None, "planned": None}
agents = []
for i, (title, resp, tools, cap, gated, ins, outs, deps, success) in enumerate(ROWS, start=1):
    dept = chr(64 + (i - 1) // 10 + 1)
    if cap == "wired" and all(t.startswith("skill:") for t in tools):
        runs_on = CLI
    elif any(t.startswith("local:") for t in tools):
        runs_on = LOC
    elif any(t.startswith("worker:") for t in tools):
        runs_on = ["worker-host"]
    else:
        runs_on = BR
    agents.append({
        "id": f"{dept}{(i - 1) % 10 + 1:02d}",
        "department": dept,
        "name": title,
        "responsibility": resp,
        "tools": tools,
        "capability": cap,
        "runs_on": runs_on,
        "gated_by": gated,
        "inputs": ins,
        "outputs": outs,
        "dependencies": deps,
        "success_criteria": success,
        "retry_limit": 2 if dept in ("I", "L") else 3,
        "timeout_s": 900 if dept in ("E", "G") else (60 if dept in ("H", "D") else 300),
    })

out = {
    "version": 1,
    "generated": "2026-10-28",
    "departments": {k: v for k, v in DEPTS.items()},
    "defaults": {
        "execution_status": "idle",
        "usage_fields": ["attempts", "tokens_reported", "duration_ms"],
        "logs": "vimax_mission_events / vimax_ai_calls (hosted) or local companion log (local)",
        "artifacts": [],
    },
    "count": len(agents),
    "agents": agents,
}
path = pathlib.Path(__file__).resolve().parents[1] / "catalog" / "agents.json"
path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
caps = collections.Counter(a["capability"] for a in agents)
depts = collections.Counter(a["department"] for a in agents)
print(f"wrote {path} — {len(agents)} agents | capabilities: {dict(caps)} | depts: {dict(sorted(depts.items()))}")
