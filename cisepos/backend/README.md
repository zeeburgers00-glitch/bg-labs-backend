# CISePOS API

Fast Hono/Bun API for the CISePOS retail + restaurant POS platform.

## Required environment
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `APP_ORIGIN` (Vercel frontend origin)
- `PORT` (Railway provides this)

All business requests require a Supabase access token in the Authorization header. The API uses the user's token and Supabase RLS; it does not use the service-role key.

## Local run
```bash
bun install
bun run dev
```

Health: `GET /health`
