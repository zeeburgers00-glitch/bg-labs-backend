"""AI Video Studio orchestration service.

Pipeline: Title → Research (opt) → Outline → Sections → Quality Check →
          Script Structuring → Voice Generation (chunked) → Audio Assembly → Final Audio

Entire workflow is asynchronous and job-based. Resume from failed chunks.
"""
import os
import json
import uuid
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime

from core import get_pool, load_settings, get_setting_int
from llm_provider import chat_with_fallback, llm_status, LLMError
from providers import get_provider, TTSProviderError
from secure_storage import save_generation_audio, GENERATIONS_DIR

logger = logging.getLogger("bglabs.ai_studio")

# ── Constants ─────────────────────────────────────────────
WPM_BY_LANGUAGE = {
    "en": 145, "ur": 120, "hi": 130, "ar": 130, "zh": 160,
    "ja": 120, "ko": 130, "es": 140, "fr": 140, "de": 130,
    "it": 140, "pt": 140, "ru": 130, "tr": 130, "pl": 130,
    "nl": 140, "sv": 135, "da": 140, "fi": 130, "id": 130,
    "th": 110, "vi": 130, "ms": 130, "fil": 130, "bn": 120,
}

TONES = {
    "documentary": "Documentary — authoritative, measured, informative",
    "cinematic": "Cinematic — dramatic, evocative, immersive",
    "educational": "Educational — clear, structured, accessible",
    "news": "News — professional, concise, factual",
    "storytelling": "Storytelling — narrative, engaging, character-driven",
    "podcast": "Podcast — conversational, relaxed, intimate",
    "professional": "Professional — polished, confident, corporate",
    "casual": "Casual — friendly, informal, approachable",
    "dramatic": "Dramatic — intense, emotional, impactful",
}

LANGUAGES = [
    {"code": "en", "name": "English"},
    {"code": "ur", "name": "Urdu"},
    {"code": "hi", "name": "Hindi"},
    {"code": "ar", "name": "Arabic"},
    {"code": "zh", "name": "Chinese"},
    {"code": "ja", "name": "Japanese"},
    {"code": "ko", "name": "Korean"},
    {"code": "es", "name": "Spanish"},
    {"code": "fr", "name": "French"},
    {"code": "de", "name": "German"},
    {"code": "it", "name": "Italian"},
    {"code": "pt", "name": "Portuguese"},
    {"code": "ru", "name": "Russian"},
    {"code": "tr", "name": "Turkish"},
    {"code": "pl", "name": "Polish"},
    {"code": "nl", "name": "Dutch"},
    {"code": "sv", "name": "Swedish"},
    {"code": "da", "name": "Danish"},
    {"code": "fi", "name": "Finnish"},
    {"code": "id", "name": "Indonesian"},
    {"code": "th", "name": "Thai"},
    {"code": "vi", "name": "Vietnamese"},
    {"code": "ms", "name": "Malay"},
    {"code": "fil", "name": "Filipino"},
    {"code": "bn", "name": "Bengali"},
]

DURATIONS = [5, 10, 15, 30, 45, 60]

AI_STORAGE = GENERATIONS_DIR.parent / "ai_projects"
AI_STORAGE.mkdir(parents=True, exist_ok=True)


def calculate_word_count(target_minutes: int, language: str, wpm_override: int = None) -> int:
    wpm = wpm_override or WPM_BY_LANGUAGE.get(language, 145)
    return int(target_minutes * wpm)


def calculate_section_count(target_minutes: int) -> int:
    if target_minutes <= 5:
        return 3
    elif target_minutes <= 10:
        return 4
    elif target_minutes <= 15:
        return 5
    elif target_minutes <= 30:
        return 7
    elif target_minutes <= 45:
        return 9
    elif target_minutes <= 60:
        return 12
    else:
        return min(20, max(8, target_minutes // 5))


def estimate_generation_time(target_minutes: int, chunk_count: int) -> float:
    """Rough estimate in seconds: ~2s per chunk + 3s per section for LLM."""
    return chunk_count * 2 + calculate_section_count(target_minutes) * 3


# ── Worker ────────────────────────────────────────────────
_ai_worker_task: Optional[asyncio.Task] = None
_ai_running = False


def start_ai_worker():
    global _ai_worker_task
    if _ai_worker_task is None or _ai_worker_task.done():
        _ai_worker_task = asyncio.create_task(_ai_worker_loop())


def stop_ai_worker():
    global _ai_running
    _ai_running = False


async def _ai_worker_loop():
    global _ai_running
    _ai_running = True
    logger.info("AI Studio worker started")
    # Recover stale jobs
    await _recover_stale_ai_jobs()
    while _ai_running:
        pool = get_pool()
        if not pool:
            await asyncio.sleep(2)
            continue
        try:
            processed = await _process_next_stage()
            if not processed:
                await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"AI worker loop error: {e}")
            await asyncio.sleep(2)


async def _recover_stale_ai_jobs():
    pool = get_pool()
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE ai_project_jobs SET status='pending', error_message='Recovered from stale state'
                   WHERE status='processing' AND started_at < NOW() - INTERVAL '10 minutes'"""
            )
            await conn.execute(
                """UPDATE ai_projects SET status='failed', error_message='Worker recovered mid-processing'
                   WHERE status IN ('generating_script','generating_audio','assembling')
                   AND updated_at < NOW() - INTERVAL '15 minutes'"""
            )
    except Exception as e:
        logger.warning(f"AI stale recovery failed: {e}")


async def _process_next_stage() -> bool:
    """Find and process the next pending job. Returns True if something was processed."""
    pool = get_pool()
    # Claim one pending job atomically
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE ai_project_jobs SET status='processing', started_at=NOW(), attempts=attempts+1
               WHERE id = (SELECT j.id FROM ai_project_jobs j
                           JOIN ai_projects p ON j.project_id = p.id
                           WHERE j.status='pending'
                           AND p.status NOT IN ('draft','cancelled','failed')
                           ORDER BY j.created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
               RETURNING j.*, p.title AS project_title, p.language, p.target_duration,
                         p.tone, p.script AS project_script, p.voice_id, p.voice_key,
                         p.voice_name, p.engine, p.research_enabled, p.mode, p.id AS pid"""
        )
    if not row:
        return False

    job = dict(row)
    job_type = job["type"]
    project_id = job["pid"]

    try:
        if job_type == "research":
            await _do_research(job, project_id)
        elif job_type == "outline":
            await _do_outline(job, project_id)
        elif job_type == "script":
            await _do_script_section(job, project_id)
        elif job_type == "validation":
            await _do_validation(job, project_id)
        elif job_type == "tts":
            await _do_tts_chunk(job, project_id)
        elif job_type == "assembly":
            await _do_assembly(job, project_id)
        else:
            await _complete_job(job["id"], {"error": "Unknown job type"})
        return True
    except Exception as e:
        logger.error(f"AI job {job['id']} ({job_type}) failed: {e}")
        await _fail_job(job["id"], str(e))
        return True


# ── Job lifecycle ──────────────────────────────────────────
async def _complete_job(job_id: int, result: dict):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE ai_project_jobs SET status='completed', result=$1, completed_at=NOW() WHERE id=$2",
            json.dumps(result), job_id,
        )


async def _fail_job(job_id: int, error: str):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE ai_project_jobs SET status='failed', error_message=$1, completed_at=NOW() WHERE id=$2",
            error[:500], job_id,
        )


# ── Pipeline stages ────────────────────────────────────────

async def _do_research(job: dict, project_id: int):
    """Optional research layer: use LLM to generate factual notes about the topic."""
    title = job["project_title"]
    language = job["language"]
    settings = await load_settings()
    temperature = float(settings.get("llm_temperature", "0.7"))
    max_tokens = get_setting_int(settings, "llm_max_tokens", 4000)

    messages = [
        {"role": "system", "content": "You are a research assistant. Generate factual notes about the given topic. "
         "Include key facts, dates, names, and data points. Be accurate and cite sources where possible. "
         "Do NOT write a narration script — only research notes in bullet-point format."},
        {"role": "user", "content": f"Topic: {title}\nLanguage: {language}\n\nGenerate comprehensive research notes "
         f"with verified facts, key concepts, and important context for creating a narration script."},
    ]
    text, provider = await chat_with_fallback(messages, temperature=temperature, max_tokens=max_tokens)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE ai_projects SET research_notes=$1, updated_at=NOW() WHERE id=$2",
            text, project_id,
        )
    await _complete_job(job["id"], {"notes": text[:500], "provider": provider})


async def _do_outline(job: dict, project_id: int):
    """Generate the script outline using LLM."""
    title = job["project_title"]
    language = job["language"]
    target_minutes = job["target_duration"]
    tone = job["tone"]
    settings = await load_settings()
    temperature = float(settings.get("llm_temperature", "0.7"))
    max_tokens = get_setting_int(settings, "llm_max_tokens", 4000)
    wpm = int(settings.get("default_wpm", str(WPM_BY_LANGUAGE.get(language, 145))))
    target_words = calculate_word_count(target_minutes, language, wpm)
    section_count = calculate_section_count(target_minutes)

    research_notes = ""
    pool = get_pool()
    async with pool.acquire() as conn:
        proj = await conn.fetchrow("SELECT research_notes FROM ai_projects WHERE id=$1", project_id)
        if proj and proj["research_notes"]:
            research_notes = proj["research_notes"]

    tone_desc = TONES.get(tone, TONES["documentary"])
    lang_name = next((l["name"] for l in LANGUAGES if l["code"] == language), "English")

    messages = [
        {"role": "system", "content": f"You are a professional scriptwriter creating narration scripts for videos. "
         f"Create an outline for a {target_minutes}-minute {tone_desc.lower()} narration about the given title. "
         f"The script should be in {lang_name}. "
         f"Target approximately {target_words} words total. "
         f"Return ONLY valid JSON with this format: "
         f'{{"sections": [{{"title": "Section Title", "order": 1, "estimated_words": 500}}]}}. '
         f"Create exactly {section_count} sections. "
         f"The first section should be a hook/introduction and the last a conclusion. "
         f"Do NOT include headings that would sound unnatural when spoken."},
        {"role": "user", "content": f"Title: {title}\nTarget duration: {target_minutes} minutes\n"
         f"Language: {lang_name}\nTone: {tone_desc}\n"
         f"{f'Research notes:\\n{research_notes}' if research_notes else ''}\n\n"
         f"Generate the outline as JSON."},
    ]
    text, provider = await chat_with_fallback(messages, temperature=temperature, max_tokens=max_tokens)

    # Parse outline
    outline = _parse_json_response(text)
    sections = outline.get("sections", [])
    if not sections:
        # Fallback: create default sections
        sections = []
        default_titles = ["Introduction", "Background", "Key Concepts", "Analysis", "Conclusion"]
        for i, t in enumerate(default_titles[:section_count]):
            sections.append({"title": t, "order": i + 1, "estimated_words": target_words // section_count})

    # Ensure each section has required fields
    for i, s in enumerate(sections):
        s.setdefault("id", str(uuid.uuid4().hex[:12]))
        s.setdefault("order", i + 1)
        s.setdefault("estimated_words", target_words // len(sections))
        s.setdefault("text", "")
        s.setdefault("status", "pending")

    # Store outline in project script
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE ai_projects SET script=$1, estimated_words=$2, updated_at=NOW() WHERE id=$3",
            json.dumps({"title": title, "language": language, "sections": sections}),
            target_words, project_id,
        )
        # Create script jobs for each section
        for s in sections:
            await conn.execute(
                """INSERT INTO ai_project_jobs (project_id, type, section_id, status)
                   VALUES ($1, 'script', $2, 'pending')""",
                project_id, s["id"],
            )

    await _complete_job(job["id"], {"sections": len(sections), "provider": provider})


async def _do_script_section(job: dict, project_id: int):
    """Generate a single section of the script."""
    section_id = job["section_id"]
    pool = get_pool()
    async with pool.acquire() as conn:
        proj = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not proj:
            raise Exception("Project not found")
        proj = dict(proj)
        script = json.loads(proj["script"]) if isinstance(proj["script"], str) else (proj["script"] or {})
        sections = script.get("sections", [])
        section = next((s for s in sections if s.get("id") == section_id), None)
        if not section:
            raise Exception(f"Section {section_id} not found")

    title = proj["title"]
    language = proj["language"]
    tone = proj["tone"]
    target_minutes = proj["target_duration"]
    settings = await load_settings()
    temperature = float(settings.get("llm_temperature", "0.7"))
    max_tokens = get_setting_int(settings, "llm_max_tokens", 4000)
    tone_desc = TONES.get(tone, TONES["documentary"])
    lang_name = next((l["name"] for l in LANGUAGES if l["code"] == language), "English")
    target_words = section.get("estimated_words", 500)
    section_title = section.get("title", "Section")

    # Build context from previous sections
    prev_summaries = []
    for s in sections:
        if s.get("order", 999) < section.get("order", 999) and s.get("text"):
            prev_summaries.append(f"- {s['title']}: {s['text'][:150]}...")

    outline_titles = [s.get("title", "") for s in sections]
    research_notes = proj.get("research_notes", "") or ""

    messages = [
        {"role": "system", "content": f"You are a professional narration scriptwriter. "
         f"Write the narration text for ONE section of a {tone_desc.lower()} video about: {title}. "
         f"Write in {lang_name}. Target approximately {target_words} words. "
         f"Write ONLY the spoken narration text — no headings, no stage directions, no meta-commentary. "
         f"The text should flow naturally when read aloud. Use clear, engaging language. "
         f"Include transitions at the beginning and end to connect with adjacent sections."},
        {"role": "user", "content": f"Title: {title}\nSection: {section_title} (Section {section.get('order', 1)})\n"
         f"Full outline: {', '.join(outline_titles)}\n"
         f"{f'Previous sections summary:\\n' + chr(10).join(prev_summaries) if prev_summaries else ''}\n"
         f"{f'Research notes:\\n{research_notes[:1000]}' if research_notes else ''}\n\n"
         f"Write the narration text for this section only ({target_words} words)."},
    ]
    text, provider = await chat_with_fallback(messages, temperature=temperature, max_tokens=max_tokens)

    # Update section text
    section["text"] = text.strip()
    section["word_count"] = len(text.split())
    section["status"] = "generated"

    # Save back
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE ai_projects SET script=$1, updated_at=NOW() WHERE id=$2",
            json.dumps(script), project_id,
        )
        # Check if all sections have text
        all_done = all(s.get("text") for s in sections)
        if all_done:
            # Create validation job
            validation_enabled = settings.get("llm_validation_enabled", "true").lower() == "true"
            if validation_enabled:
                await conn.execute(
                    """INSERT INTO ai_project_jobs (project_id, type, status) VALUES ($1, 'validation', 'pending')""",
                    project_id,
                )
            else:
                await conn.execute(
                    "UPDATE ai_projects SET script_status='ready', status='script_ready', updated_at=NOW() WHERE id=$1",
                    project_id,
                )

    await _complete_job(job["id"], {"words": len(text.split()), "provider": provider})


async def _do_validation(job: dict, project_id: int):
    """Run quality check on the full script."""
    pool = get_pool()
    async with pool.acquire() as conn:
        proj = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not proj:
            raise Exception("Project not found")
        proj = dict(proj)
        script = json.loads(proj["script"]) if isinstance(proj["script"], str) else (proj["script"] or {})
        sections = script.get("sections", [])
        full_text = " ".join(s.get("text", "") for s in sections)
        total_words = len(full_text.split())
        target_words = proj["estimated_words"] or 0

    settings = await load_settings()
    temperature = 0.3
    max_tokens = get_setting_int(settings, "llm_max_tokens", 4000)

    messages = [
        {"role": "system", "content": "You are a script quality controller. Validate the narration script. "
         "Check for: missing sections, repetition, unnatural transitions, excessive filler, "
         "word count vs target, language consistency, narration suitability, unsupported factual claims, "
         "incomplete sentences, and accidental meta-commentary. "
         "Return ONLY valid JSON: "
         '{"passed": true/false, "score": 0-100, "issues": ["issue1", "issue2"], '
         '"sections_to_regenerate": ["section_id1"], "summary": "brief assessment"}'},
        {"role": "user", "content": f"Title: {proj['title']}\nTarget words: {target_words}\n"
         f"Actual words: {total_words}\nLanguage: {proj['language']}\n\n"
         f"Script sections:\n" + "\n\n".join(
             f"[{s.get('title', 'Section')}]\n{s.get('text', '')}" for s in sections
         )},
    ]
    text, provider = await chat_with_fallback(messages, temperature=temperature, max_tokens=max_tokens)

    result = _parse_json_response(text)
    passed = result.get("passed", True)
    score = result.get("score", 75)
    issues = result.get("issues", [])
    sections_to_regen = result.get("sections_to_regenerate", [])

    pool = get_pool()
    if not passed and sections_to_regen:
        # Regenerate failed sections
        script_data = json.loads(proj["script"]) if isinstance(proj["script"], str) else (proj["script"] or {})
        for s in script_data.get("sections", []):
            if s.get("id") in sections_to_regen:
                s["text"] = ""
                s["status"] = "pending"
                async with pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO ai_project_jobs (project_id, type, section_id, status)
                           VALUES ($1, 'script', $2, 'pending')""",
                        project_id, s["id"],
                    )
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE ai_projects SET script=$1, updated_at=NOW() WHERE id=$2",
                json.dumps(script_data), project_id,
            )
        await _complete_job(job["id"], {"passed": False, "score": score, "issues": issues, "regenerating": sections_to_regen})
    else:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE ai_projects SET script_status='ready', status='script_ready', updated_at=NOW() WHERE id=$1",
                project_id,
            )
        await _complete_job(job["id"], {"passed": passed, "score": score, "issues": issues, "provider": provider})


async def _do_tts_chunk(job: dict, project_id: int):
    """Generate audio for one TTS chunk."""
    section_id = job["section_id"]
    result = json.loads(job.get("result") or "{}") if isinstance(job.get("result"), str) else (job.get("result") or {})
    chunk_index = result.get("chunk_index", 0)
    chunk_text = result.get("text", "")

    pool = get_pool()
    async with pool.acquire() as conn:
        proj = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not proj:
            raise Exception("Project not found")
        proj = dict(proj)

    if not chunk_text:
        # Load chunk text from project
        script = json.loads(proj["script"]) if isinstance(proj["script"], str) else (proj["script"] or {})
        section = next((s for s in script.get("sections", []) if s.get("id") == section_id), None)
        if not section:
            raise Exception(f"Section {section_id} not found")
        chunks = section.get("chunks", [])
        if chunk_index >= len(chunks):
            raise Exception(f"Chunk {chunk_index} out of range")
        chunk_text = chunks[chunk_index]

    engine = proj["engine"] or "edge-tts"
    voice_id = proj["voice_id"]
    voice_key = proj["voice_key"] or "en-US-AriaNeural"
    settings = await load_settings()
    timeout = get_setting_int(settings, "f5_tts_timeout", 200)

    # Build voice dict
    if engine == "f5-tts" and voice_id:
        async with pool.acquire() as conn:
            vp = await conn.fetchrow("SELECT * FROM voice_profiles WHERE id=$1", voice_id)
        if not vp:
            raise TTSProviderError("VOICE_NOT_FOUND", "Cloned voice not found.")
        voice = {
            "key": vp.get("voice_key") or "",
            "reference_audio_url": vp.get("reference_audio_url") or "",
            "reference_text": vp.get("reference_text") or "",
        }
    else:
        voice = {"key": voice_key}

    provider = get_provider(engine)
    job_settings = {"speed": 1.0, "voice_key": voice_key}

    try:
        audio, duration = await asyncio.wait_for(
            provider.generate(chunk_text, voice, job_settings),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise Exception("TTS generation timed out.")

    ext = ".mp3" if engine != "f5-tts" else ".wav"
    fname = save_generation_audio(audio, ext)
    audio_path = GENERATIONS_DIR / fname

    # Get real duration via ffprobe if not provided
    if not duration:
        duration = _get_audio_duration(audio_path)

    await _complete_job(job["id"], {
        "chunk_index": chunk_index,
        "audio_file": fname,
        "duration": float(duration or 0),
        "section_id": section_id,
    })


async def _do_assembly(job: dict, project_id: int):
    """Assemble all TTS chunk audio files into final audio."""
    pool = get_pool()
    async with pool.acquire() as conn:
        proj = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not proj:
            raise Exception("Project not found")
        proj = dict(proj)

        # Get all completed TTS jobs in order
        jobs = await conn.fetch(
            """SELECT * FROM ai_project_jobs WHERE project_id=$1 AND type='tts' AND status='completed'
               ORDER BY created_at, id""",
            project_id,
        )

    if not jobs:
        raise Exception("No completed TTS chunks to assemble.")

    # Collect audio files in order
    audio_files = []
    total_duration = 0.0
    for j in jobs:
        result = json.loads(j["result"]) if isinstance(j["result"], str) else (j["result"] or {})
        fname = result.get("audio_file")
        if fname:
            path = GENERATIONS_DIR / fname
            if path.exists():
                audio_files.append(path)
                total_duration += float(result.get("duration", 0))

    if not audio_files:
        raise Exception("No audio files found to assemble.")

    # Use ffmpeg to concatenate
    output_name = f"ai_project_{project_id}_{uuid.uuid4().hex[:8]}.mp3"
    output_path = AI_STORAGE / output_name

    # Create concat list file
    list_file = AI_STORAGE / f"concat_{project_id}.txt"
    list_content = "\n".join(f"file '{f.absolute()}'" for f in audio_files)
    list_file.write_text(list_content)

    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-c", "copy", str(output_path)],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            # Try re-encoding if copy fails (different codecs)
            proc = subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                 "-acodec", "libmp3lame", "-ab", "192k", str(output_path)],
                capture_output=True, text=True, timeout=120,
            )
            if proc.returncode != 0:
                raise Exception(f"ffmpeg failed: {proc.stderr[:300]}")
    finally:
        list_file.unlink(missing_ok=True)

    # Get final duration
    final_duration = _get_audio_duration(output_path)
    if not final_duration:
        final_duration = total_duration

    # Move to public storage for serving
    final_fname = f"ai_{uuid.uuid4().hex}.mp3"
    final_path = GENERATIONS_DIR / final_fname
    import shutil
    shutil.copy2(str(output_path), str(final_path))
    output_path.unlink(missing_ok=True)

    final_url = f"/api/storage/generations/{final_fname}"
    minutes = int(final_duration // 60)
    seconds = int(final_duration % 60)

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE ai_projects SET status='completed', audio_status='ready',
               actual_duration=$1, final_audio_url=$2, completed_at=NOW(), updated_at=NOW()
               WHERE id=$3""",
            float(final_duration), final_url, project_id,
        )

    await _complete_job(job["id"], {
        "final_audio_url": final_url,
        "duration": float(final_duration),
        "duration_str": f"{minutes}:{seconds:02d}",
        "chunks_assembled": len(audio_files),
    })


# ── Helpers ────────────────────────────────────────────────

def _parse_json_response(text: str) -> dict:
    """Extract JSON from LLM response (may have markdown fences or extra text)."""
    text = text.strip()
    # Remove markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Find first and last ``` 
        start = 0
        end = len(lines) - 1
        for i, line in enumerate(lines):
            if line.strip().startswith("```"):
                start = i + 1
                break
        for i in range(len(lines) - 1, start - 1, -1):
            if lines[i].strip().startswith("```"):
                end = i
                break
        text = "\n".join(lines[start:end])
    # Try to find JSON object
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract {...} or [...]
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}


def _get_audio_duration(path: Path) -> float:
    """Get audio duration in seconds using ffprobe."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return float(proc.stdout.strip())
    except Exception:
        pass
    return 0.0


def split_text_into_chunks(text: str, chunk_size: int = 500) -> List[str]:
    """Split text into TTS-sized chunks at sentence boundaries."""
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks = []
    sentences = text.replace("\n", " ").split(". ")
    current = ""

    for sentence in sentences:
        if not sentence.endswith("."):
            sentence = sentence + "."
        if len(current) + len(sentence) + 1 <= chunk_size:
            current = (current + " " + sentence).strip()
        else:
            if current:
                chunks.append(current)
            # If single sentence is longer than chunk_size, split at commas
            if len(sentence) > chunk_size:
                parts = sentence.split(", ")
                temp = ""
                for part in parts:
                    if len(temp) + len(part) + 1 <= chunk_size:
                        temp = (temp + ", " + part).strip(", ")
                    else:
                        if temp:
                            chunks.append(temp)
                        temp = part
                current = temp
            else:
                current = sentence

    if current:
        chunks.append(current)

    return chunks


# ── Project lifecycle management ───────────────────────────

async def start_script_generation(project_id: int, mode: str = "auto"):
    """Kick off the script generation pipeline."""
    pool = get_pool()
    async with pool.acquire() as conn:
        proj = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not proj:
            raise Exception("Project not found")
        proj = dict(proj)
        settings = await load_settings()
        research_enabled = proj.get("research_enabled", False) or settings.get("llm_research_enabled", "false").lower() == "true"

        # Reset jobs and script
        await conn.execute("DELETE FROM ai_project_jobs WHERE project_id=$1 AND type IN ('outline','script','validation','research')", project_id)
        await conn.execute(
            "UPDATE ai_projects SET status='generating_script', script_status='generating', script='{}', updated_at=NOW() WHERE id=$1",
            project_id,
        )

        if research_enabled:
            await conn.execute(
                "INSERT INTO ai_project_jobs (project_id, type, status) VALUES ($1, 'research', 'pending')",
                project_id,
            )
            # Outline will be queued after research completes
            # For simplicity, also queue outline now — research results will be available when outline runs
        await conn.execute(
            "INSERT INTO ai_project_jobs (project_id, type, status) VALUES ($1, 'outline', 'pending')",
            project_id,
        )


async def start_audio_generation(project_id: int):
    """Split script into chunks and create TTS jobs."""
    pool = get_pool()
    async with pool.acquire() as conn:
        proj = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not proj:
            raise Exception("Project not found")
        proj = dict(proj)
        script = json.loads(proj["script"]) if isinstance(proj["script"], str) else (proj["script"] or {})
        sections = script.get("sections", [])

        settings = await load_settings()
        chunk_size = get_setting_int(settings, "f5_tts_chunk_size", 500)

        # Clear old TTS/assembly jobs
        await conn.execute("DELETE FROM ai_project_jobs WHERE project_id=$1 AND type IN ('tts','assembly')", project_id)
        await conn.execute(
            "UPDATE ai_projects SET status='generating_audio', audio_status='generating', updated_at=NOW() WHERE id=$1",
            project_id,
        )

        # Split each section into chunks and create TTS jobs
        total_chunks = 0
        for section in sections:
            text = section.get("text", "").strip()
            if not text:
                continue
            chunks = split_text_into_chunks(text, chunk_size)
            section["chunks"] = chunks
            for idx, chunk_text in enumerate(chunks):
                await conn.execute(
                    """INSERT INTO ai_project_jobs (project_id, type, section_id, status, result)
                       VALUES ($1, 'tts', $2, 'pending', $3)""",
                    project_id, section["id"],
                    json.dumps({"chunk_index": idx, "text": chunk_text}),
                )
                total_chunks += 1

        # Save updated script with chunk info
        await conn.execute(
            "UPDATE ai_projects SET script=$1, updated_at=NOW() WHERE id=$2",
            json.dumps(script), project_id,
        )

    return total_chunks


async def check_audio_completion(project_id: int):
    """Check if all TTS chunks are done, and if so, create assembly job."""
    pool = get_pool()
    async with pool.acquire() as conn:
        pending = await conn.fetchval(
            "SELECT COUNT(*) FROM ai_project_jobs WHERE project_id=$1 AND type='tts' AND status IN ('pending','processing','failed')",
            project_id,
        )
        if pending == 0:
            completed = await conn.fetchval(
                "SELECT COUNT(*) FROM ai_project_jobs WHERE project_id=$1 AND type='tts' AND status='completed'",
                project_id,
            )
            if completed > 0:
                # Create assembly job
                existing = await conn.fetchval(
                    "SELECT COUNT(*) FROM ai_project_jobs WHERE project_id=$1 AND type='assembly' AND status IN ('pending','processing')",
                    project_id,
                )
                if existing == 0:
                    await conn.execute(
                        "UPDATE ai_projects SET status='assembling', audio_status='assembling', updated_at=NOW() WHERE id=$1",
                        project_id,
                    )
                    await conn.execute(
                        "INSERT INTO ai_project_jobs (project_id, type, status) VALUES ($1, 'assembly', 'pending')",
                        project_id,
                    )


async def resume_project(project_id: int):
    """Resume a failed project from where it left off."""
    pool = get_pool()
    async with pool.acquire() as conn:
        proj = await conn.fetchrow("SELECT * FROM ai_projects WHERE id=$1", project_id)
        if not proj:
            raise Exception("Project not found")
        proj = dict(proj)
        status = proj["status"]

        if status == "failed":
            if proj["script_status"] in ("generating", "pending"):
                # Resume script generation
                await conn.execute(
                    "UPDATE ai_project_jobs SET status='pending', error_message='' WHERE project_id=$1 AND type IN ('outline','script','validation','research') AND status='failed'",
                    project_id,
                )
                await conn.execute(
                    "UPDATE ai_projects SET status='generating_script', error_message='', updated_at=NOW() WHERE id=$1",
                    project_id,
                )
            elif proj["audio_status"] in ("generating", "assembling"):
                # Resume audio generation — only re-queue failed chunks
                await conn.execute(
                    "UPDATE ai_project_jobs SET status='pending', error_message='' WHERE project_id=$1 AND type='tts' AND status='failed'",
                    project_id,
                )
                await conn.execute(
                    "UPDATE ai_project_jobs SET status='pending', error_message='' WHERE project_id=$1 AND type='assembly' AND status='failed'",
                    project_id,
                )
                await conn.execute(
                    "UPDATE ai_projects SET status='generating_audio', error_message='', updated_at=NOW() WHERE id=$1",
                    project_id,
                )
        elif status == "script_ready" and proj["audio_status"] in ("failed", "pending"):
            await start_audio_generation(project_id)


def get_project_status_detail(project: dict, jobs: list) -> dict:
    """Compute real-time progress from actual job states."""
    status = project.get("status", "draft")
    script = project.get("script")
    if isinstance(script, str):
        try:
            script = json.loads(script)
        except Exception:
            script = {}
    elif script is None:
        script = {}

    sections = script.get("sections", []) if isinstance(script, dict) else []
    sections_done = sum(1 for s in sections if s.get("text"))
    sections_total = len(sections)

    tts_jobs = [j for j in jobs if j["type"] == "tts"]
    tts_completed = sum(1 for j in tts_jobs if j["status"] == "completed")
    tts_total = len(tts_jobs)

    # Determine stage
    stage = "idle"
    stage_label = "Idle"
    progress_pct = 0

    if status == "generating_script":
        outline_done = any(j["type"] == "outline" and j["status"] == "completed" for j in jobs)
        if outline_done:
            if sections_total > 0:
                stage = "generating_script"
                stage_label = f"Writing script ({sections_done}/{sections_total} sections)"
                progress_pct = int((sections_done / sections_total) * 60) + 20
            else:
                stage = "generating_script"
                stage_label = "Writing script..."
                progress_pct = 25
        else:
            stage = "outline"
            stage_label = "Creating outline..."
            progress_pct = 10
    elif status == "script_ready":
        stage = "script_ready"
        stage_label = "Script ready"
        progress_pct = 65
    elif status == "generating_audio":
        if tts_total > 0:
            stage = "generating_audio"
            stage_label = f"Generating narration ({tts_completed}/{tts_total})"
            progress_pct = 65 + int((tts_completed / tts_total) * 25)
        else:
            stage = "preparing_audio"
            stage_label = "Preparing voice..."
            progress_pct = 67
    elif status == "assembling":
        stage = "assembling"
        stage_label = "Assembling final audio..."
        progress_pct = 92
    elif status == "completed":
        stage = "completed"
        stage_label = "Completed"
        progress_pct = 100
    elif status == "failed":
        stage = "failed"
        stage_label = "Failed"
        progress_pct = 0
    elif status == "cancelled":
        stage = "cancelled"
        stage_label = "Cancelled"
        progress_pct = 0

    return {
        "stage": stage,
        "stage_label": stage_label,
        "progress_pct": progress_pct,
        "sections_done": sections_done,
        "sections_total": sections_total,
        "tts_completed": tts_completed,
        "tts_total": tts_total,
    }
