# Base44 Development Notes

- Run the preview stack with `docker compose -f docker-compose.base44.yml up -d`.
- The FastAPI app is served from `main.py`; the separate `app/` package is not the active entry point for this preview.
- The frontend is the static `bglabs_complete.html` served by FastAPI and calls same-origin `/api` routes.
- PostgreSQL tables are created by the app lifespan hook, so no separate migration command is needed for this entry point.
- Verify locally with `curl http://localhost:3000/health` and externally with `curl -H 'Host: external-preview.example.com' http://localhost:3000/`.
- The app service bind-mounts the repository and runs Uvicorn with reload; Python edits should appear without rebuilding the image.
