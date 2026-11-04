# CISePOS deployment

## Frontend (Vercel)
- Root directory: `cisepos/frontend`
- Framework: Vite
- Install: `npm install`
- Build: `npm run build`
- Output: `dist`
- Environment: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_URL`

## Backend (Railway)
- Root directory: `cisepos/backend`
- Builder: Railpack / Bun
- Start command: `bun run start`
- Health check: `/health`
- Environment: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `APP_ORIGIN`

The API deliberately uses the user's Supabase access token and publishable key. Do not add a service-role key to the frontend or expose it to client code.

## Database
The additive `pos_*` tables, membership functions, RLS policies and checkout RPC have been applied to Supabase project `ai-youtube-studio-autopilot`. Existing application tables are retained. See the Supabase migration history for the applied migration names.

## Current rollout status
Source code and the initial database foundation are committed on `feature/cisepos-pos-rebuild`. Railway deployment is blocked until the connected Railway workspace has an active plan. Vercel production deployment is held until the API has a live Railway URL so the frontend is not published in a non-functional state.
