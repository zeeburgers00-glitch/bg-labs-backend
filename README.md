# ViMax Skills & Agents

This project is an **additive overlay for ViMax**, pinned to upstream commit `fd4b72e7731be6e5f88486206d25ea59849b0285`. The previous BG Labs files were removed from this working branch at the owner's request; the Git history and other branches are unchanged. The overlay does not replace the upstream ViMax backend.

## What works, and what does not

| Capability | Status |
|---|---|
| Searchable catalog | 118 repositories and 38 topic/API/discovery links. Three requested repository URLs were unavailable. Existing detailed entries are preserved; most new entries are **machine-assisted surface triage**, not deep security audits or integrations. See the [original triage](docs/repository-audit.md) and [expanded source inventory](docs/requested-sources-triage.md). |
| Creator skills | Reviewed, pinned subsets from `Jakeschincariol/youtube-agent-skill` (hook + title lint) and `ahmedsakri/youtube-agent-pro` (idea score). They are exposed through the local API and added as read-only ViMax ToolRegistry entries. Scores are English-language heuristics, **not forecasts or research**. |
| Local video | User-provided script and notes → simple storyboard/text-card visuals → local Piper speech → timed SRT/VTT → FFmpeg H.264/AAC MP4 → thumbnail → preview → explicit local approval. Tested on Linux with a Piper test voice, in both 9:16 and 16:9. |
| Visual cut detection & clips | On demand, **PySceneDetect 0.7.2 + OpenCV 4.13.0.92** analyze a completed local job's video, estimate visual cuts and produce a `scene-detection.json` report. Export up to 30 seconds from a detected scene as an MP4 using FFmpeg. Detection is also a read-only `video_scene_cuts` ViMax tool by job ID. This is not AI semantic understanding, and is not hosted on Vercel. |
| Choices and transparency | Format, installed voice/language, 5–180 second target, visual style and draft/standard quality; queue, stages, logs, failures, bounded retries, local output paths and $0 **API** cost for this local path. Electricity/hardware/hosting are not included. |
| Cloud text planning | Server-side adapters for Groq, Gemini, Mistral, Z.ai's general API, OpenRouter, Hugging Face Inference and selected OpenCode chat-completion models; private per-user chat history and idea/script/review prompts. **Not live-verified until a rotated key is configured and its real test succeeds.** These are text-planning modes, not an autonomous agent or web research. Hacker AI is not connected. |
| Voice chat and stock search | Browser dictation and speech playback when supported, with selectable available voice, stop controls and text fallback; real Pexels video search once configured. Browser speech services can transmit audio/text off-device, and voice gender/language availability varies. Pexels search does not download assets or assemble video. |
| Research, local AI writing, visual models | **Not implemented by the local companion**. Notes and script must be supplied by the user; visuals are generated graphic text cards, not AI imagery. The optional cloud text assistant cannot browse or verify claims. Other listed repos are not integrated merely because they appear in the catalog. |
| YouTube upload and OAuth | **Not implemented**. Local approval is stored and uploads nothing; the API returns 501. Multi-channel OAuth, an optional fully automatic mode, a publishing stop switch and an authorized end-to-end test still need implementation. |
| Mission control | Private channel profiles, competitor reference lists and a durable **text-planning** queue with leases, cautious recovery, cancellation and review. A separately hosted, configured account-scoped worker is required; no worker is automatically hosted. This does not research, render, connect to YouTube or publish. See [setup and limitations](docs/mission-control.md). |
| Public Vercel backend | Supabase Auth, private ideas, optional cloud text planning and the text-queue API use an isolated bridge. Online ViMax video rendering, YouTube OAuth/upload and analytics are **not connected**. Unsupported routes fail closed. Upstream ViMax is a single-workspace process without multi-user isolation and is never exposed to the Internet. |
| Unlimited free hosting | Not promised. Local processing uses your own device and electricity; Vercel and external providers enforce quotas and may charge. |

The `Unexpected token 'T' … is not valid JSON` is addressed by guarded JSON parsing and JSON error responses. Connecting Supabase does **not** mean the video agent is connected. The cloud status explicitly distinguishes these components.

A rendering fix now expands slideshow stills into constant-rate frames before duration trimming; older generated MP4s can contain audio longer than their video stream. Regenerate those jobs to get the fix. The tests now verify the actual frame timeline, not just the MP4 container duration.

The connected Supabase project is shared with another application. ViMax uses separate `vimax_` tables with row-level security and per-user policies; it does not modify the other application's tables. A project-specific **publishable** key and Supabase URL were set on the ViMax Vercel project; no Supabase service-role key is used. Publishable keys share the project's `anon` role: the existing `orders` table already has a policy allowing anonymous inserts. The new API does not return the key to browsers, but a publishable key is not a security boundary; review the existing policy or use a dedicated Supabase project before exposing keys or widely sharing the app. The Supabase Auth confirmation redirect allow-list was extended to the public ViMax skills page while leaving the previous site URL unchanged. The account pool and quota are shared. With Supabase's default email sender, confirmation emails are restricted to organization-team addresses and currently only two emails/hour across the project. To let other people sign up, configure [custom SMTP](https://supabase.com/docs/guides/auth/auth-smtp) directly in the Supabase dashboard; do not paste its credentials into chat. Hosting and provider quotas still apply.

For Vercel, the small `web/` wrapper runs the canonical root build and re-exports the tested API. Set the project root to `web`, build command to `npm run build`, output directory to `dist`, and enable access to files outside the root directory. The previous interim deployment's custom upstream-only build command must be replaced. Vercel deployment-specific protection does not provide per-user isolation of the ViMax workspace.

## Enable cloud text planning safely

1. **Rotate any credential exposed in chat, a screenshot or source control.** In Vercel → the `vimax` project → Settings → Environment Variables, enter replacements as **Sensitive** server-side variables for the intended environment. Never send their values in chat or place them in `.env.example`. The template lists names only; the Vercel bridge reads environment variables directly, not an uploaded `.env` file.
2. Apply `supabase/migrations/202610270002_vimax_cloud_ai.sql`, `202610270003_vimax_ai_finish_token.sql`, and `202610270004_vimax_mission_queue.sql` once, in that order, to the intended Supabase project, in addition to the earlier `vimax_projects` migration. They create or modify only ViMax's own tables, policies and functions. Apply all before deploying the corresponding bridge and while provider calls are disabled: the second changes the completion RPC's signature. Public health checks now query both Supabase Auth and a harmless database RPC. Do not reapply a migration already recorded in that project.
3. Cloud provider access is **denied by default**, even if keys exist. Sign in and copy the displayed **Account ID**; set `VIMAX_AI_ALLOWED_USER_IDS` to one or more intended Supabase Auth UUIDs separated by commas. Alternatively, set `VIMAX_AI_ALLOW_ALL_AUTHENTICATED=true` only if you explicitly want **all** accounts in the shared Supabase project to use the owner's keys. Every eligible user shares the same deployment keys. Environment changes require a Vercel redeploy.
4. Set one or more of `GROQ_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `ZAI_API_KEY`, `OPENROUTER_API_KEY`, `HF_TOKEN`, `OPENCODE_API_KEY` and `PEXELS_API_KEY`. The optional corresponding `*_MODELS` variables are comma-separated, owner-controlled allowlists, maximum ten; their defaults are in `.env.example`. OpenCode requires `OPENCODE_MODELS` and permits only the chat-completions models listed in `api/providers.mjs`; the vendor documents different endpoints for other model families and restricts free chat models to the OpenCode client. Z.ai's adapter uses its **general** API, not the separate coding-plan endpoint. Hugging Face tokens need inference permission. Hacker AI's private endpoint has not been verified and is not enabled.
5. Set independent provider-side **spending limits**, review privacy/terms, redeploy, then sign in → Skills & Agents → **Test provider**. A key being present is reported as *configured, unverified*; only a successful real test shows that it responded. Tests and fallback attempts consume real requests and may cost money. No provider is claimed to be connected merely because an environment variable exists. A fallback is opt-in and can send the conversation to a second provider; ambiguous timeouts are not retried automatically.
6. The SQL reservation function enforces at most **10 provider attempts per account and 50 across the deployment per UTC day**, including tests and Pexels searches, plus one in-flight attempt per account. The server receives a per-reservation completion capability that is not exposed to the browser, so a client cannot prematurely release another in-flight reservation. These are not dollar caps; model pricing and token usage vary. Each account can **Pause my provider calls** immediately; already reserved requests may still finish. An abandoned reservation continues to count and releases the in-flight restriction after 60 seconds. These controls do not implement a publishing stop switch, because publishing is not implemented. A user could consume reservations without generating output, so the global cap is also susceptible to denial of service; keep signup restricted, use a dedicated project for public use, and add stronger abuse controls before broad sharing.

The server sends the current prompt plus up to three prior turns to the chosen provider; prompts/replies are saved in Supabase until the user deletes them or the account is deleted, with a 200-turn limit. The UI shows up to 30 turns and lets users delete all saved turns. Provider attempt metadata and reported token counts (not raw prompts, keys or provider errors) are retained for up to roughly 90 days, with cleanup on a later reservation rather than a guaranteed scheduled deletion. A response may still have been charged if a network timeout occurs. If saving fails, the generated text is shown with a warning. Responses may be inaccurate and are not fact-checked.

The browser's Web Speech support differs by device and browser. Dictation fills the textbox for review; it never sends automatically. Speech recognition may use an external browser service, and a voice described as male may not exist or be labeled by gender. Playback is interruptible and has a text fallback. Pexels results link to the original page, credit the creator and require separate license/rights review.

## Security and privacy

- This companion is **single-user, loopback only**. Do not set up port forwarding, bind it to a public interface, or share its URL over the Internet. A random in-memory token gates both internal services; the front proxy also checks host and origin to reduce local cross-site/DNS-rebinding attacks. These are not multi-user authentication.
- No API keys or OAuth tokens are required for the local slideshow. Do not paste secrets into scripts, notes, prompts, screenshots or logs. Outputs and job metadata are stored under `~/.vimax-skills/jobs` by default; protect that directory, including backups. Set `VIMAX_SKILLS_OUTPUT` to a private location if needed. Unix job directories are created with mode `0700`; configure appropriate Windows ACLs yourself.
- For upstream ViMax providers, prefer process/OS secret-manager environment variables such as `VIMAX_LLM_API_KEY`, `VIMAX_IMAGE_API_KEY` and `VIMAX_VIDEO_API_KEY`. Upstream's Settings UI writes `configs/agent.local.yaml` **as plaintext** (with restrictive file permissions on Unix), not encrypted storage. Do not commit or share that file. Provider calls can cost money. This overlay does not solve hosted per-user credential storage.
- Never install arbitrary catalog entries or custom ComfyUI nodes automatically. Prompt text, model files, media, and third-party repos are untrusted. Only the small vendored scripts identified in the audit were reviewed line by line; this is not a full security audit. Scene detection is limited to generated local job videos and decodes media with native libraries; do not expose the local companion publicly or analyze untrusted files.
- No feature creates artificial views, likes, subscribers, comments, or other fake engagement.

## Windows setup (PowerShell)

These instructions are provided for Windows 10/11 x64 and **have not been tested on Windows**. The verified run used Linux x86-64, Node 22 and Python 3.11 for the companion. Upstream ViMax itself requires Python 3.12+ and its much larger dependencies.

1. Install Git, Node.js 22+, Python 3.12, `uv`, and Windows' `curl.exe`/`tar.exe`. Check `git --version`, `node -v`, `py -3.12 --version`, `uv --version`, `curl.exe --version`, and `tar.exe --version`. See upstream [ViMax instructions](https://github.com/HKUDS/ViMax) and [uv installation](https://docs.astral.sh/uv/getting-started/installation/). Build and model downloads need Internet access.
2. Clone the pinned **separate** ViMax source and install its dependencies; this can take substantial disk/RAM and may download packages from upstream indexes:

   ```powershell
   git clone https://github.com/HKUDS/ViMax.git C:\ViMax
   git -C C:\ViMax checkout --detach fd4b72e7731be6e5f88486206d25ea59849b0285
   Set-Location C:\ViMax
   uv sync --frozen --no-dev --python 3.12
   Set-Location C:\ViMax\web
   npm ci --ignore-scripts --no-audit --no-fund
   ```

3. In a second PowerShell window, open this repository's root (replace the example path with your checkout) and build the **temporary-copy** frontend overlay. It downloads the pinned upstream source but does not modify your ViMax checkout:

   ```powershell
   Set-Location C:\path\to\bg-labs-backend
   npm ci --ignore-scripts --no-audit --no-fund
   npm run build
   py -3.12 -m venv skills\.venv
   .\skills\.venv\Scripts\python.exe -m pip install -r skills\requirements.txt
   ```

4. Choose a compatible Piper voice, **review its separate model/data license** and download it yourself. For example, after confirming that the model's terms meet your needs:

   ```powershell
   New-Item -ItemType Directory -Force "$env:USERPROFILE\vimax-voices" | Out-Null
   .\skills\.venv\Scripts\python.exe -m piper.download_voices --download-dir "$env:USERPROFILE\vimax-voices" en_US-ljspeech-medium
   $env:VIMAX_PIPER_MODEL = "$env:USERPROFILE\vimax-voices\en_US-ljspeech-medium.onnx"
   $env:VIMAX_PIPER_LANGUAGE = "en-US"
   ```

   Both the `.onnx` and matching `.onnx.json` must exist. The original `rhasspy/piper` repository is archived; the installed maintained `piper-tts==1.8.0` successor is **GPL-3.0-or-later**, not MIT. Model licenses differ. The [LJ Speech model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/medium/MODEL_CARD) says it was trained from scratch on a public-domain dataset; confirm all relevant rights yourself. Do **not** assume Lessac-trained voices are cleared for commercial use: [Lessac's source data license](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html) is a research license. See [Piper's current project](https://github.com/OHF-Voice/piper1-gpl) and each model's card.

5. Start the local companion in the same window:

   ```powershell
   $env:VIMAX_SOURCE_DIR = "C:\ViMax"
   $env:VIMAX_AGENT_PYTHON = "C:\ViMax\.venv\Scripts\python.exe"
   $env:VIMAX_SKILLS_PYTHON = (Resolve-Path .\skills\.venv\Scripts\python.exe).Path
   npm run start:local
   ```

   Visit **http://127.0.0.1:4173**, then choose **Skills & Agents**. The two internal ports are 4174 and 4175, all bound to loopback. Override `VIMAX_LOCAL_PORT`, `VIMAX_UPSTREAM_PORT`, `VIMAX_SKILLS_PORT` if needed. Stop with Ctrl+C.

   After a video is generated, use **Detect visual cuts locally** in Progress & review. The threshold ranges from 0.1–100 (lower is more sensitive); the 0.1 default is tuned for small text-card changes and can produce false detections. The JSON report and timestamps are estimates, not semantic scene descriptions; fades or text-card changes may be missed. Choose a detected scene and **Export scene clip** to create an MP4 containing up to its first 30 seconds. Each export replaces that job's previous clip; download it first if you want to keep it. Scene analysis and clipping use CPU and send no video to a provider.

### More voices and languages

Copy `skills/voices.example.json` outside the repository, edit the `model` paths, IDs, labels and language tags, and set `VIMAX_SKILLS_VOICES` to that trusted local file. One model and matching JSON are needed for each voice. The UI only allows installed voices and adopts the voice's language; it **does not translate** the script. Complex-script font shaping varies by OS/Pillow build and has not been verified. Set `VIMAX_SKILLS_FONT` to a suitable Unicode `.ttf` if needed.

## Linux / macOS outline

Use upstream ViMax's documented setup at the pinned commit; run `npm ci --ignore-scripts` in its `web` directory. In this repository root, run `npm run build`, create `python3 -m venv skills/.venv`, and `skills/.venv/bin/pip install -r skills/requirements.txt`. Configure `VIMAX_SOURCE_DIR`, `VIMAX_PIPER_MODEL`, `VIMAX_PIPER_LANGUAGE`, `VIMAX_AGENT_PYTHON` (`<ViMax>/.venv/bin/python`), and `VIMAX_SKILLS_PYTHON` (`<this directory>/skills/.venv/bin/python`); then `npm run start:local`. macOS and non-x86 builds are not verified here.

## Private text-planning worker

See [Mission control setup, quotas, privacy and recovery](docs/mission-control.md). This worker requires separate always-on hosting and server-side secrets; it is not running merely because the Vercel app is deployed.

## Hardware and cost checks

- `node -v`, `py -3.12 --version`, and `uv --version` check required toolchains. In the UI, **Progress & review** reports logical CPUs, whether an NVIDIA GPU is detected, FFmpeg/Piper/scene-detection status, and configured voices. On Windows, `nvidia-smi`, `Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory`, and `Get-PSDrive C` show GPU (if installed), RAM and disk space.
- PySceneDetect is BSD-3-Clause; OpenCV is Apache-2.0, with separate third-party and codec licenses in distributed wheels. `skills/requirements.txt` installs their headless CPU packages and NumPy; check the licenses of your actual target-platform wheels before redistribution.
- Text-card/Piper/FFmpeg processing works on CPU and was tested without a GPU. It is not Wan, LTX, ComfyUI, or an AI video model. Those repositories are assessed only; no cloud fallback for them is connected. They can need large downloads, substantial GPU VRAM and model-specific licenses.
- An FFmpeg binary with H.264 (`libx264`) and AAC encoders is required. `imageio-ffmpeg==0.6.0` supplies wheels for common platforms; override with a trusted binary using `VIMAX_FFMPEG`. FFmpeg's LGPL/GPL license depends on build flags; the tested Linux wheel reported GPLv3. Check your own binary with `ffmpeg -version` before redistribution.
- If speech is longer than the selected duration, the job fails with an actionable message rather than truncating speech. A shorter script or longer target is required. Extra duration is silence.

## Tests

From this repository root:

```powershell
npm ci --ignore-scripts --no-audit --no-fund
npm test
.\skills\.venv\Scripts\python.exe -m pip install -r skills\requirements-test.txt
$env:PYTHONPATH = (Resolve-Path .\skills).Path
$env:VIMAX_TEST_SOURCE = "C:\ViMax"
$env:VIMAX_TEST_PIPER_MODEL = $env:VIMAX_PIPER_MODEL
.\skills\.venv\Scripts\python.exe -m pytest -q skills\tests
```

Node tests mock provider and Supabase HTTP responses; they do not prove real provider connectivity. The cloud AI and mission SQL migrations are also exercised against PGlite (PostgreSQL in WASM) with simulated users and roles; the queue integration test drives the bridge and worker against simulated PostgREST and mocked provider responses, not a live Supabase signup. An additional opt-in test exercises parallel claims, idempotency and quotas on a strictly isolated local PostgreSQL 17 cluster; it is not a production load test. Test-only dependencies are pinned `@electric-sql/pglite` (Apache-2.0/PostgreSQL) and `pg` (MIT); neither is used by the deployed runtime. The media and end-to-end proxy tests **skip** unless both a real voice and the pinned source are supplied. They generate real MP4/audio/thumbnail/SRT outputs in temporary test folders, decode the MP4 and check that video frames span the full requested duration. Separate synthetic-video tests verify actual cut timestamps, report output, decoded clip frames, token gating and path restrictions. Registry tests use ViMax's real `ToolRegistry`, but the full ViMax agent process and hosted multi-user deployment were not tested in the Linux sandbox (the upstream runtime requires Python 3.12 and additional providers/dependencies). Tests do not upload or call YouTube.

## Architecture and next steps

- `scripts/apply-overlay.mjs` modifies only a temporary build copy; guards fail if pinned upstream structure changes. The local runner creates a temporary token-gated wrapper around ViMax's server and forwards `/api/skills/*` to the local sidecar; existing ViMax API calls still go to ViMax.
- `skills/vimax_skills/agent_entry.py` extends the existing registry in memory. The original ViMax tools remain available. The read-only scene tool uses the agent's own environment: pinned upstream ViMax includes PySceneDetect 0.6.7.1; the adapter also supports that API, while the companion pins 0.7.2. The full upstream agent process has not been verified. `skills/vendor/` contains only pinned, attributed source under its licenses.
- The cloud API uses Supabase Auth, secure HttpOnly cookies, same-origin checks, per-user RLS, owner-approved AI accounts, fixed-host provider adapters, database-enforced request limits, and an account-level text-call pause. Provider keys live in server environment storage; no hosted per-user OAuth-token storage is implemented. Public multi-user **rendering** still needs isolated render workers and storage, encrypted channel tokens, more abuse controls, official multi-channel OAuth, a publication stop switch, private-by-default publishing and real end-to-end tests. Vercel's free plan and third-party limits still apply. Do not enable a shared single-workspace bridge as a shortcut.
