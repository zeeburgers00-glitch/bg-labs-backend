# BG Labs Studio — Vercel Deployment

Live production URL: **https://bg-labs-backend.vercel.app**
API docs: https://bg-labs-backend.vercel.app/docs · Health: https://bg-labs-backend.vercel.app/health

## What runs where

| Path | Served by |
| --- | --- |
| `/` and any unknown path | `index.html` via `@vercel/static` (the whole single-page UI) |
| `/api/*`, `/health`, `/keep-alive`, `/docs`, `/redoc`, `/openapi.json` | `main.py` via `@vercel/python` (FastAPI serverless function, 300s timeout, region `iad1`) |

Config lives in `vercel.json` (`builds` + `routes`); `.vercelignore` controls what is uploaded.
`builds` overrides Vercel's project Build & Development Settings on purpose — do not "fix" that warning.

## Required environment variables

Set on the Vercel project (Settings → Environment Variables) for Production, Preview and Development:

| Variable | Purpose |
| --- | --- |
| `SUPABASE_URL` | Project URL, e.g. `https://<ref>.supabase.co` — PostgREST + Storage base |
| `SUPABASE_SERVICE_KEY` | `service_role` key (bypasses RLS). Encrypted. Never expose to the browser. |
| `SUPABASE_STORAGE_BUCKET` | Public bucket for generated audio/images/avatars (default `bglabs-media`) |
| `SECRET_KEY` | JWT signing secret for app login tokens. Encrypted. |
| `PYTHON_VERSION` | Runtime pin (builder also accepts a `.python-version` file) |

Without `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` the app automatically falls back to
**in-memory storage** — everything works, but all data is lost whenever the serverless
instance is recycled. Useful for demos only.

## Database schema

Tables (prefix `bglabs_` so they can share a schema with other apps) and the public
storage bucket are created with plain SQL/REST — see `DEPLOY.md` for the DDL. Row Level
Security is enabled with **no** policies: all access goes through the server with the
service key, the browser never talks to Supabase directly.

## Media URLs

Generated files are uploaded to Supabase Storage and stored as public URLs, so the UI
streams them straight from the bucket (no proxying through the function). Every media
field also keeps a `data_uri` fallback; the frontend resolves whichever is available via
`mediaUrl()` in `index.html`.

## Redeploying

```bash
git push origin <branch>     # or use the Vercel CLI / dashboard "Redeploy"
```

Production deploys are created from the branch you target; `main` is the production branch.

## Known account setting: Deployment Protection

This Vercel account has **Vercel Authentication** (`all_except_custom_domains`) enabled by
default, which puts a Vercel login wall in front of `*.vercel.app` URLs. It cannot be
changed through the API connector — to make the URL public:

1. Vercel dashboard → project **bg-labs-backend** → **Settings** → **Deployment Protection**
2. **Vercel Authentication** → set to *Only Preview Deployments* (or turn it off)
3. Save. Takes effect immediately, no redeploy needed.

Until then, opening the URL asks you to authenticate with the Vercel account that owns the
project, after which the app loads normally.

## Verifying a deployment locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tests/smoke_test.py      # 147 checks: auth, TTS, image, script, avatar,
                                          # youtube, billing, referral, admin, dashboard
```

The smoke test runs twice — once on in-memory storage and once against
`tests/mock_supabase.py`, an in-process PostgREST + Storage mock — so it needs no network
and no real credentials. It stubs out edge-tts and image generation.

Optional extras (SQLAlchemy/Alembic, passlib, Stripe, Celery, torch/numpy) live in
`requirements-full.txt` and stay out of the Vercel bundle; enable the legacy routers with
`ENABLE_EXTRA_ROUTERS=1`.

## AI agents, Google/YouTube, skills and ViMax (Phase 2/3)

The deployment runs with no AI key (built-in agents, `/yt-*`, Edge TTS, free
Pollinations image route, timeline builder). Unlock stronger providers from the
**Models & Providers → AI Keys / Server URLs** screen, or set them in Vercel:

- Chat/images/voice: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`,
  `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `ELEVENLABS_API_KEY`, `HF_TOKEN`
- Hosted GPU: `FAL_KEY`, `REPLICATE_API_TOKEN`
- YouTube OAuth: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`; redirect URI is
  `https://bg-labs-backend.vercel.app/api/youtube/auth/callback`
- Optional self-hosted repos: `COMFYUI_URL`, `COMFYUI_WORKFLOW`, `SD_WEBUI_URL`,
  `INVOKEAI_URL`, `FOOOCUS_URL`, `FASTSD_URL`, `F5_TTS_URL`, `GPTSOVITS_URL`,
  `OPENVOICE_URL`, `CHATTERBOX_URL`, `KOKORO_URL`, `FISH_SPEECH_URL`, `CHATTS_URL`,
  `COQUI_URL`, `QWEN_TTS_URL`, `LIVETALKING_URL`, `MUSETALK_URL`, `SADTALKER_URL`,
  `REALESRGAN_URL`, `RENDER_SERVICE_URL`
- Model overrides are available for every hosted route, including
  `GEMINI_VIDEO_MODEL`, `FAL_VEO_MODEL`, `FAL_SEEDANCE_MODEL`, `FAL_WAN_MODEL`,
  `FAL_HUNYUAN_MODEL`, `REPLICATE_VIDEO_MODEL`, `REPLICATE_F5_TTS_MODEL`, and
  `REPLICATE_SADTALKER_MODEL`.

Vercel cannot execute CUDA/torch model weights, a browser desktop, or an FFmpeg
binary. The backend therefore runs orchestration and connects those open-source
repos to a hosted provider or your GPU worker. `/api/integrations` reports the
truthful status of all requested repos (`active`, `ported`, `adapter`, `reference`).

Key endpoints: `/api/models`, `/api/generate/{capability}`, `/api/vimax`,
`/api/skills`, `/yt-script`, `/api/browse/research`, `/api/integrations`.
