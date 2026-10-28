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
