# CISePOS rebuild workspace

Independent CISePOS-compatible retail + restaurant POS implementation, isolated under this folder so the existing BG Labs AI platform remains intact.

## Architecture
- `frontend/`: React + Vite web app, intended for Vercel.
- `backend/`: Hono + Bun API, intended for Railway.
- Database: Supabase PostgreSQL with additive `pos_*` schema and RLS.

## Supabase
The migration `supabase/migrations/202611040001_cisepos_full_pos_core.sql` creates isolated POS tables, organization membership helpers, RLS policies, and an atomic checkout RPC. Existing `ros_*`, AI Studio, and other application tables are not dropped or modified.

## Deployment
Frontend root: `cisepos/frontend`
Backend root: `cisepos/backend`
