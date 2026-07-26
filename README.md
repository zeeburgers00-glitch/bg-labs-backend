---
title: BG Labs - Free TTS Platform
emoji: 🎙️
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 8000
pinned: false
license: apache-2.0
---

# BG Labs - Free AI Voice Generation Platform

Free, unlimited AI voice generation with 20+ built-in voices and 17+ language support.

## Features

- 🎙️ 20+ built-in voices (male & female)
- 🌍 17+ languages supported
- 🆓 Completely free and unlimited
- 🎤 Voice cloning support
- 📁 Project management
- 🔊 High-quality MP3 output

## Supported Languages

English, Spanish, French, German, Italian, Portuguese, Polish, Turkish, Russian, Dutch, Czech, Arabic, Chinese, Japanese, Hungarian, Korean, Hindi

## API Endpoints

- `POST /api/auth/register` - Create account
- `POST /api/auth/login` - Login
- `GET /api/voices` - List all voices
- `POST /api/studio/generate` - Generate audio
- `GET /api/studio/audio` - List generated audio

## Tech Stack

- FastAPI (Python)
- Coqui XTTS v2 (Open Source TTS)
- PostgreSQL
- Docker
