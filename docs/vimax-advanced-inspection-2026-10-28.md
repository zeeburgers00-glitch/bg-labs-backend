# ViMax Advanced Upgrade — Pre-Implementation Inspection (2026-10-28)

> Covers Section 8 "Engineering Requirements" first bullet: review existing audit docs, API routes, DB migrations, provider adapters and tests **before** editing.

## 1. Existing audit documents reviewed
| Document | Verdict |
|----------|---------|
| `docs/audit-2026-10-28.md` (Phase 1 second pass) | 162 catalog entries, 120 agents, provider live-test matrix, deployment `dpl_Ez73…` |
| `docs/skill-registry.md` (16 repos ×8 fields) | 6 integrated, 5 catalogued-ready, 5 gated/excluded with licenses |
| `docs/vimax-ai-studio-audit.md`, `super-assistant-audit.md`, `repository-audit.md` | Confirmed preserved prod DB, no fake claims |
| `docs/youtube-upload.md`, `youtube-analytics.md`, `ai-provider-setup.md`, etc. | Per-feature deep dives |

**Conclusion:** No rebuild needed; all describe additive architecture.

## 2. API routes (api/bridge.mjs) — 20+ endpoints
- Auth: `/api/cloud/signup`, `/login`, `/logout`, `/session`, `/resend-confirmation`
- Google OAuth: `/api/cloud/google/{status,start,callback}`
- Mission queue: `/api/cloud/mission`, `/channels`, `/competitors`, `/jobs`, `/pause`, `/jobs-page/:n`, `/mission/jobs/:id`
- Providers: `/api/cloud/providers`, `/providers/test`, `/ai/pause`, `/usage`
- Chat: `/api/cloud/chat`, `/chat/history`
- YouTube: `/api/cloud/youtube/*` (via `api/youtube.mjs` — PKCE, encrypted grants, ≤10 channels, resumable upload)
- Social: `/api/cloud/social/*`, GPU: `/api/cloud/gpu/*`
- YouTube public research: `/api/cloud/youtube-public/*`
- **Agentic:** `/api/cloud/agents`, `/agents/run`, `/skills/registry`, `/skills/run` (via `api/workforce-skills.mjs` + `api/creator-agents.mjs`)
- System: `/api/health`, `/api/sessions`, `/api/events`, `/api/skills/system`
- All use `pathFor()` validation, `HttpError`, `authenticated()` guard, `json()` helper.

## 3. Database migrations (supabase/migrations/)
| File | Purpose |
|------|---------|
| `202610270001_vimax_projects.sql` | Projects table |
| `202610270002_vimax_cloud_ai.sql` | AI calls, budgets |
| `202610270003_vimax_ai_finish_token.sql` | Finish token for AI |
| `202610270004_vimax_mission_queue.sql` | Mission queue + `vimax_channels` (name,niche,audience,language,timezone,brand_voice,format) |
| `202610270005_vimax_youtube_uploads.sql` | Uploads table (sha256 idempotency, lease, cancel) |
| `202610270006_vimax_mission_openai.sql` | OpenAI variant |
| `202610270007_vimax_gpu_previews.sql` | GPU previews (S3) |
| `202610270008_vimax_youtube_connections.sql` | Encrypted OAuth grants (≤10/channel/user) |
| `202610270009_vimax_social_connections.sql` | Facebook/TikTok |
| `202610280010_vimax_youtube_analytics.sql` | Analytics budgets |

RLS pattern: `enable row level security` + `revoke all` + `grant` to `authenticated` + `auth.uid() = owner_id` policies + `security definer` functions with `pg_advisory_xact_lock`.

## 4. Provider adapters (api/*.mjs, lib/*.mjs)
- `api/youtube.mjs` (620 lines): `seal`/`unseal` AES-256-GCM, `configuration()` validates clientId/secret/key/redirect origin, `allowed()` allowlist, `tokenSession()`, resumable upload with quota checks — **reference for new modules**.
- `api/gpu.mjs`, `api/social.mjs`, `api/youtube-public-research.mjs` (SSRF-safe)
- `lib/agents.mjs`: `TOOL_MANIFEST` with `executable:true` only for 5 local CLIs; rest `executable:false` → honest capability gating.
- `catalog/agents.json` (120), `catalog/catalog.json` (162), `lib/upstream.mjs`

## 5. Tests (test/)
- `test/agent-workforce.test.mjs` (4 tests: registry 120, manifest coverage, real dispatch A01→D05→H07→L10 with artifacts, gated fail-closed)
- `test/cloud.test.mjs`, `creator-agents.test.mjs`, `creator-skills.test.mjs`, `google-signin.test.mjs`, `gpu-integration.test.mjs`, `youtube-browser-smoke.cjs`, etc.
- Total: **98 tests →97 pass, 1 skipped** (Postgres opt-in) — baseline for regression.

## 6. Deployment
- Project `prj_dcgtXiSwz9TBAav6pCUzUUvqIymK`, framework `vite`, `functions: { "api/bridge.mjs": {maxDuration:300}}`, `rewrites: /api/:path* → /api/bridge`
- Last deploy `4833d21` (READY, PROMOTED) with 13 env vars (9 provider keys) injected — live-tested 2026-10-28.

## 7. Gaps vs. Master Prompt → Planned additions
| Prompt requirement | Existing state | Planned migration/module |
|--------------------|----------------|--------------------------|
| Agent Reliability Center (durable jobs, retries, cancellation, logs) | Mission queue has basic durability; no explicit retry/cancel states | `vimax_reliability_center` table + `api/reliability.mjs` |
| Multi-Channel Intelligence (analytics isolation, 10+ channels, niche/audience/language/schedule/branding/strategy) | `vimax_channels` has 8 fields; no analytics/schedule/branding | Extend table + `api/channel-intelligence.mjs` |
| End-to-End Video Production (topic→script→voice→visuals→captions→render→thumbnail→SEO→preview + validation) | Local pipeline exists (Piper/FFmpeg) but no durable orchestrator | `vimax_production_jobs` + `api/production.mjs` |
| Research & Fact Verification (SSRF, URL validation, citations, prompt-injection defense) | `youtube-public-research.mjs` has some; need hardened `api/research.mjs` | New table + module |
| Publishing & Approval (private review, explicit approval, scheduling, duplicate prevention, quota) | `vimax_youtube_uploads` has idempotency/lease; needs approval gate | `vimax_publish_approvals` + `api/publishing.mjs` |
| Budget & Security (per-user/job cost limits, usage reporting, rate limits, concurrency, tenant isolation, audit trails) | `vimax_ai_calls` has 10/50 limits; need cost+concurrency+audits | `vimax_budget_controls` + `api/budget-security.mjs` |
| Analytics & Monetization Readiness (genuine metrics, eligibility tracking) | Analytics budgets exist; no readiness tracker | `vimax_monetization_readiness` + `api/monetization.mjs` |

## 8. Constraints honored
- Additive only — no column drops, no table deletes, no RLS loosening.
- No fake controls — unavailable providers labeled `unavailable`, not mocked.
- No secrets in client bundle — `sensitive` env vars only.
- Background workers first — Vercel `maxDuration:300` but full renders delegated.
