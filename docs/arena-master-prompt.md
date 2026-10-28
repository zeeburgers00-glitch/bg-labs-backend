# ViMax AI Studio — Advanced Reliability & Growth Upgrade

**Source:** User provided extra master prompt (2026-10-28) — saved verbatim for Arena paste + implementation tracking.

---

Continue working inside the EXISTING ViMax AI Studio repository and deployed project. Preserve all existing functionality, integrations, authentication, database schemas, UI and deployment configuration. Inspect the current implementation before editing. Do not rebuild from scratch.

Implement the following additional capabilities, integrating them with existing components instead of creating duplicate systems:

1. **Agent Reliability Center**
  - Real-time job and agent status, execution logs, errors, retry counts, cancellation and recovery.
  - Durable background jobs with idempotency, bounded retries, timeouts and resumable execution.
  - Clearly distinguish queued, running, failed, completed and awaiting-approval states.
  - Never mark an operation successful without verifying its result.
2. **Multi-Channel Intelligence**
  - Isolate each user's connected YouTube channels, OAuth tokens, settings, analytics and content.
  - Support 10+ channels per user where platform limits permit.
  - Store per-channel niche, target audience, language, upload schedule, branding and content strategy.
  - Recommend topics using available analytics and real research data; do not fabricate trends or performance metrics.
3. **End-to-End Video Production**
  - Implement a functioning workflow from topic research through script, voice, visuals, captions, rendering, thumbnail, SEO metadata and preview.
  - Support long-form videos and Shorts using the existing rendering pipeline first.
  - Validate generated files, audio, duration, resolution, subtitles and output metadata.
  - Track source licenses, asset attribution and originality risks.
  - Reuse approved assets and cache expensive outputs where safe.
4. **Research & Fact Verification**
  - Use configured, functioning search providers and source URLs.
  - Save citations and timestamps for important claims.
  - Treat external webpages, documents and model outputs as untrusted data.
  - Add SSRF protection, safe URL validation, download restrictions and prompt-injection defenses.
5. **Publishing & Approval**
  - Use the official YouTube API and the existing OAuth implementation.
  - Provide a private/unlisted review workflow where supported, explicit approval before public publication, scheduling, upload reconciliation and duplicate prevention.
  - Check API quota and permissions; expose errors clearly.
  - Never claim that a video was published unless the API confirms its final state.
6. **Budget & Security Controls**
  - Add per-user and per-job cost limits, provider usage reporting, rate limits and concurrency controls.
  - Keep API keys and OAuth secrets server-side; never expose them in frontend code or logs.
  - Enforce tenant isolation, role-based authorization and audit trails.
  - Require explicit approval for public publishing, destructive actions and unexpected paid services.
7. **Analytics & Monetization Readiness**
  - Show genuine metrics returned by connected APIs and label unavailable data clearly.
  - Track progress toward current official eligibility requirements and link to YouTube Studio for required owner actions.
  - Do not promise earnings, eligibility, acceptance or automatic monetization approval.
8. **Engineering Requirements**
  - Review existing audit documents, API routes, database migrations, provider adapters and tests before changes.
  - Preserve the existing project architecture and existing working features.
  - Add database migrations only when needed; make them safe and backward-compatible.
  - Add tests for authorization, job retries, upload failure recovery, tenant isolation, quota handling and approval gates.
  - Use background workers for long-running rendering tasks; do not depend on a short-lived serverless request for full video rendering.
  - Do not add fake controls, mock success responses, placeholder agents or unverified integrations.
  - Never expose production secrets or modify production data during tests.

**Implementation priority:** first complete and test one real end-to-end workflow, then improve reliability, then expand specialist agents and channels. Finish with a report listing changed files, verified features, tests actually run, required credentials, setup instructions, deployment steps and remaining limitations. Do not push untested changes directly to production.

---

**Paste instructions for Arena:** Copy the block above (from "Continue working inside..." to "...Do not push untested changes directly to production.") into Arena → Master Prompt / System Prompt field.

**Implementation status in this repo:** See `docs/vimax-advanced-inspection-2026-10-28.md` (inspection) and `docs/vimax-advanced-upgrade-report.md` (final report).
