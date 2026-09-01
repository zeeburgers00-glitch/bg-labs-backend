"""Database schema: extend existing tables safely and add new entities."""
import os
import json
import logging
from datetime import datetime

import asyncpg

from core import hash_pass, DEFAULT_SETTINGS

logger = logging.getLogger("bglabs.schema")


async def migrate(pool: asyncpg.Pool):
    """Run all migrations idempotently. Preserves existing data."""
    async with pool.acquire() as conn:
        # ── Extend users ──
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'")

        # ── Extend voice_profiles (voice cloning) ──
        for col, typ in [
            ("description", "TEXT DEFAULT ''"),
            ("reference_audio_url", "TEXT DEFAULT ''"),
            ("reference_text", "TEXT DEFAULT ''"),
            ("language", "TEXT DEFAULT 'en'"),
            ("duration", "REAL DEFAULT 0"),
            ("sample_rate", "INTEGER DEFAULT 22050"),
            ("status", "TEXT DEFAULT 'ready'"),
            ("visibility", "TEXT DEFAULT 'private'"),
            ("consent_confirmed", "BOOLEAN DEFAULT FALSE"),
            ("consent_timestamp", "TIMESTAMP"),
            ("engine", "TEXT DEFAULT 'edge-tts'"),
            ("updated_at", "TIMESTAMP DEFAULT NOW()"),
        ]:
            await conn.execute(f"ALTER TABLE voice_profiles ADD COLUMN IF NOT EXISTS {col} {typ}")

        # ── Generations (job + record combined) ──
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS generations (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                voice_id INTEGER,
                voice_label TEXT DEFAULT '',
                text TEXT NOT NULL,
                engine TEXT DEFAULT 'edge-tts',
                status TEXT DEFAULT 'queued',
                settings TEXT DEFAULT '{}',
                audio_url TEXT DEFAULT '',
                duration REAL DEFAULT 0,
                chars INTEGER DEFAULT 0,
                error_code TEXT DEFAULT '',
                error_message TEXT DEFAULT '',
                retry_count INTEGER DEFAULT 0,
                priority INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                started_at TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_gen_user ON generations(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_gen_status ON generations(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_gen_created ON generations(created_at DESC)")

        # ── Usage tracking ──
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS usage (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                period_start DATE NOT NULL,
                characters_used INTEGER DEFAULT 0,
                audio_seconds REAL DEFAULT 0,
                generation_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id, period_start)
            )
        """)

        # ── Admin logs ──
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id SERIAL PRIMARY KEY,
                admin_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                action TEXT NOT NULL,
                target_type TEXT DEFAULT '',
                target_id TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # ── System settings ──
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                id SERIAL PRIMARY KEY,
                key TEXT UNIQUE NOT NULL,
                value TEXT,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # ── TTS workers ──
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tts_workers (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT 'unknown',
                gpu BOOLEAN DEFAULT FALSE,
                model TEXT DEFAULT '',
                last_heartbeat TIMESTAMP,
                current_job INTEGER,
                total_jobs INTEGER DEFAULT 0,
                failed_jobs INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # ── Seed default settings ──
        for k, v in DEFAULT_SETTINGS.items():
            await conn.execute(
                "INSERT INTO system_settings (key, value) VALUES ($1,$2) ON CONFLICT (key) DO NOTHING",
                k, v,
            )

        # ── Seed F5 worker row ──
        await conn.execute(
            "INSERT INTO tts_workers (name, status, gpu, model) VALUES ('f5-tts','unknown',TRUE,'F5-TTS') ON CONFLICT (name) DO NOTHING"
        )

        # ── AI Projects ──
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_projects (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                language TEXT DEFAULT 'en',
                target_duration INTEGER DEFAULT 5,
                actual_duration REAL DEFAULT 0,
                voice_id INTEGER,
                voice_key TEXT DEFAULT '',
                voice_name TEXT DEFAULT '',
                engine TEXT DEFAULT 'edge-tts',
                tone TEXT DEFAULT 'documentary',
                mode TEXT DEFAULT 'auto',
                research_enabled BOOLEAN DEFAULT FALSE,
                status TEXT DEFAULT 'draft',
                script_status TEXT DEFAULT 'pending',
                audio_status TEXT DEFAULT 'pending',
                script JSONB DEFAULT '{}',
                research_notes TEXT DEFAULT '',
                estimated_words INTEGER DEFAULT 0,
                final_audio_url TEXT DEFAULT '',
                error_message TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                completed_at TIMESTAMP
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_aiproj_user ON ai_projects(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_aiproj_status ON ai_projects(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_aiproj_created ON ai_projects(created_at DESC)")

        # ── AI Project Jobs ──
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_project_jobs (
                id SERIAL PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES ai_projects(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                section_id TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                error_message TEXT DEFAULT '',
                result JSONB DEFAULT '{}',
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_aijob_project ON ai_project_jobs(project_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_aijob_status ON ai_project_jobs(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_aijob_type ON ai_project_jobs(type)")

        # ── Seed AI-related default settings ──
        ai_defaults = {
            "llm_provider": "openai-compatible",
            "llm_model": "gpt-4o-mini",
            "llm_temperature": "0.7",
            "llm_max_tokens": "4000",
            "llm_research_enabled": "false",
            "llm_validation_enabled": "true",
            "default_narration_tone": "documentary",
            "default_wpm": "145",
            "f5_tts_model": "F5-TTS",
            "f5_tts_workers": "1",
            "f5_tts_max_concurrent": "1",
            "f5_tts_timeout": "200",
            "f5_tts_retry_count": "2",
            "f5_tts_chunk_size": "500",
        }
        for k, v in ai_defaults.items():
            await conn.execute(
                "INSERT INTO system_settings (key, value) VALUES ($1,$2) ON CONFLICT (key) DO NOTHING",
                k, v,
            )

    # ── Seed default admin account ──
    await seed_admin(pool)


async def seed_admin(pool: asyncpg.Pool):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@bglabs.io")
    admin_password = os.getenv("ADMIN_PASSWORD", "BgLabs#Admin2026!")
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM users WHERE email=$1", admin_email)
        if existing:
            # Ensure existing default admin has admin role + active.
            await conn.execute(
                "UPDATE users SET role='super_admin', is_active=TRUE WHERE email=$1 AND role NOT IN ('admin','super_admin')",
                admin_email,
            )
            return
        await conn.execute(
            """INSERT INTO users (email, username, full_name, password_hash, role, is_active, credits, referral_code)
               VALUES ($1,$2,$3,$4,$5,TRUE,999999,$6)
               ON CONFLICT (email) DO NOTHING""",
            admin_email, "admin", "Platform Admin", hash_pass(admin_password), "super_admin", "BGLABS-ADMIN",
        )
        logger.info(f"Seeded default admin: {admin_email}")
