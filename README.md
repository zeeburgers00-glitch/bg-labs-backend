# BG LABS - Complete AI Platform Backend

100% free, runs 24/7 in the cloud. No dependency on user's PC.

## Features

- **TTS**: Edge TTS (Microsoft) - FREE, unlimited, 26+ voices, 14+ languages
- **Image Gen**: Pollinations.ai - FREE, no API key needed
- **Voice Cloning**: Profile-based voice customization
- **Script Writer**: Template-based script generation
- **Avatar Studio**: SVG avatar generation
- **Video**: FFmpeg-based text-to-video
- **Admin Panel**: Stats, user management
- **Keep-Alive**: Self-ping system for 24/7 uptime

## Stack

- **Backend**: FastAPI + asyncpg
- **Database**: Neon PostgreSQL (free tier: 3GB, 24/7)
- **TTS**: Edge TTS (Microsoft, free unlimited)
- **Images**: Pollinations.ai (free, no API key)
- **Video**: FFmpeg (free, open source)
- **Deploy**: Render.com (free tier)

## Deployment

### 1. Create Neon Database
1. Go to [neon.tech](https://neon.tech)
2. Create free account
3. Create a new project
4. Copy the connection string

### 2. Deploy to Render
1. Push this repo to GitHub
2. Go to [render.com](https://render.com)
3. Create new Web Service
4. Connect your GitHub repo
5. Set environment variable:
   - `DATABASE_URL` = your Neon connection string
6. Deploy!

### 3. Set Up Keep-Alive (Optional)
The backend has a built-in keep-alive system that pings itself every 10 minutes. For extra reliability:
1. Go to [cron-job.org](https://cron-job.org)
2. Create a free account
3. Add a cron job:
   - URL: `https://your-app.onrender.com/keep-alive`
   - Schedule: Every 10 minutes

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API info |
| GET | `/health` | Health check |
| GET | `/keep-alive` | Keep-alive ping |
| POST | `/api/auth/register` | Register user |
| POST | `/api/auth/login` | Login |
| GET | `/api/auth/me` | Get profile |
| PUT | `/api/auth/me` | Update profile |
| GET | `/api/voices` | List voices |
| POST | `/api/studio/generate` | Generate TTS |
| GET | `/api/studio/audio` | Audio history |
| POST | `/api/image/generate` | Generate image |
| GET | `/api/image/history` | Image history |
| POST | `/api/video/generate` | Generate video |
| POST | `/api/avatar/generate` | Generate avatar |
| POST | `/api/voice-clone/create` | Create voice clone |
| GET | `/api/voice-clone/list` | List voice clones |
| POST | `/api/voice-clone/generate` | Generate with clone |
| POST | `/api/script/write` | Write script |
| GET | `/api/admin/stats` | Admin stats |
| GET | `/api/admin/users` | Admin users |
| PUT | `/api/admin/users/{id}` | Update user |
| GET | `/api/billing/plans` | Billing plans |
| GET | `/api/referral/code` | Referral code |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | Neon PostgreSQL connection string |
| `SECRET_KEY` | Yes | JWT secret key |
| `PORT` | No | Server port (default: 7860) |

## Local Development

```bash
# Clone
git clone <repo-url>
cd bg-labs-backend

# Create virtual env
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Mac/Linux

# Install deps
pip install -r requirements.txt

# Set env vars
cp .env.example .env
# Edit .env with your DATABASE_URL

# Run
python main.py
```

## Frontend

The `bglabs_complete.html` file is a complete frontend that connects to this backend. Update the `API_BASE` variable to point to your deployed backend URL.

## License

MIT
