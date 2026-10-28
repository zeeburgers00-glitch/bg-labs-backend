# YouTube workforce source audit and integration

Assessment date: 2026-10-28. This is a **sampled source/dependency and license review**, not a full security, legal or performance audit. GitHub default-branch revisions and `pushed_at` dates were captured on that date; a recent push alone does not establish quality or ongoing support. All 15 repository trees were enumerated; the linked source files, root license when present, manifests and installation docs were inspected. No upstream repository was executed wholesale.

## What is actually integrated

- **Hosted:** an authenticated, same-origin, read-only metadata preflight based on the MIT darkzOGx validator. The Creator tools dialog displays the normalized preview, changes, warnings and source registry. It does not save the draft, call YouTube or publish. It rejects overlong inputs *before* upstream truncation, and rejects unsafe/unsupported inputs. Its normalization removes line breaks in the preview; never treat that preview as an upload authorization.
- **Local companion and actual pinned ViMax ToolRegistry:** a bounded URL parser and a supplied-metrics funnel heuristic based on the MIT Serge and Pro sources. These perform no network calls. The parser validates HTTPS hosts, paths and complete IDs before invoking upstream and repairs its `/user/` canonicalization. Shorts analysis ignores impressions/CTR and does not estimate views from those metrics. Neither tool verifies identity, fetches Analytics, diagnoses a cause or promises results.
- Previously integrated local idea, hook, title lint, scene detection and FFmpeg tools remain. The registry lists them to prevent duplicate installations. The Python companion is **single-user/loopback only**, not a hosted or owner-isolated multi-user worker.
- The workforce registry provides **proposed specialist roles**, not running agents; no 120-agent scheduler, automatic tool dispatch, public publishing or full video backend was added. A listed permission describes the fixed adapter; it is not a general OS sandbox or a future agent authorization engine. Paid providers were not contacted or enabled.

The single authoritative machine-readable registry is [`catalog/workforce-skills.json`](../catalog/workforce-skills.json), served to authenticated hosted users at `GET /api/cloud/skills/registry` and to the local companion at `GET /api/skills/workforce`. Its fields include source, revision, license, proposed specialist roles, setup, credentials, permissions, and dated test scope/results. The older broad catalog is a separate source inventory, not an installation list.

## Skills and assignments

| Skill | Proposed specialist role(s) | Setup | Test result |
|---|---|---|---|
| YouTube metadata preflight | SEO specialist, Publishing reviewer | integrated hosted | passed |
| Short-video rendering workflow | Shorts editor, Video production specialist | not integrated | not run |
| YouTube marketing MCP | Marketing specialist, Publishing reviewer | not integrated | not run |
| English idea phrasing heuristic | Content strategist | integrated local | passed |
| Supplied video funnel review | Audience analytics specialist | integrated local | passed |
| Search and research agent | Research specialist | not integrated | not run |
| YouTube reference URL parser | Research specialist, Channel specialist | integrated local | passed |
| Marketing prompt playbooks | Marketing specialist | not integrated | not run |
| OpenMontage media workflow | Video production specialist | not integrated | not run |
| Desktop creator daemon | Production manager | not integrated | not run |
| Shotcraft animation templates | Motion designer | not integrated | not run |
| Local FFmpeg rendering and clips | Video editor | integrated local | passed |
| ComfyUI visual workflow | Visual production specialist | not integrated | not run |
| Kokoro local TTS | Voice specialist | not integrated | not run |
| Faster Whisper transcription | Caption specialist | not integrated | not run |
| Google API Node client | Channel specialist | not integrated | not run |
| English hook phrasing heuristic | Script specialist | integrated local | passed |
| Title and thumbnail-text lint | Packaging specialist | integrated local | passed |
| Local scene-cut estimation | Video editor | integrated local | passed |

“Not run” means source inspection only. `integrated_local` means code is present but the local companion and its prerequisites must be set up; it does **not** mean it is running on Vercel. `integrated_hosted` describes this code path after deployment, not a verified provider or channel connection.

## Proposed 120-slot role plan

This is an illustrative allocation for future design, **not** 120 configured/running workers, an authorization grant, or a scheduling guarantee. Uninstalled skills remain unavailable.

| Proposed role | Slots |
|---|---:|
| Content strategist | 8 |
| SEO specialist | 6 |
| Publishing reviewer | 4 |
| Shorts editor | 8 |
| Video production specialist | 10 |
| Marketing specialist | 6 |
| Research specialist | 12 |
| Audience analytics specialist | 6 |
| Channel specialist | 4 |
| Production manager | 4 |
| Motion designer | 6 |
| Video editor | 8 |
| Visual production specialist | 8 |
| Voice specialist | 6 |
| Caption specialist | 6 |
| Script specialist | 10 |
| Packaging specialist | 8 |

Total: **120 proposed slots**. Each skill in the registry names the matching role(s); this mapping does not start agents.

## Repository-by-repository evidence

### 1. [darkzOGx/youtube-automation-agent](https://github.com/darkzOGx/youtube-automation-agent)

- **Revision/license/maintenance:** `e973d515aef90c467da2289144df737a3bd03859`; MIT; last pushed 2026-10-27 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`package.json`](https://github.com/darkzOGx/youtube-automation-agent/blob/e973d515aef90c467da2289144df737a3bd03859/package.json), [`agents/seo-optimizer-agent.js`](https://github.com/darkzOGx/youtube-automation-agent/blob/e973d515aef90c467da2289144df737a3bd03859/agents/seo-optimizer-agent.js), [`utils/youtube-metadata-validator.js`](https://github.com/darkzOGx/youtube-automation-agent/blob/e973d515aef90c467da2289144df737a3bd03859/utils/youtube-metadata-validator.js), [`utils/credential-manager.js`](https://github.com/darkzOGx/youtube-automation-agent/blob/e973d515aef90c467da2289144df737a3bd03859/utils/credential-manager.js), [`schedules/daily-automation.js`](https://github.com/darkzOGx/youtube-automation-agent/blob/e973d515aef90c467da2289144df737a3bd03859/schedules/daily-automation.js).
- **Installation:** Node >=18.17; npm install; Playwright Chromium and FFmpeg for its renderer.
- **Dependencies:** googleapis, Playwright, SQLite, Express, optional ffmpeg-static, optional provider SDKs.
- **Capabilities:** Seven Node workflows, SEO/metadata validation, local scheduling and credential handling.
- **Decision:** Only the dependency-free metadata validator is vendored. Upstream truncates and normalizes input, so ViMax validates first and shows a non-publishing preview. The full server and scheduler are not installed.

### 2. [gyoridavid/short-video-maker](https://github.com/gyoridavid/short-video-maker)

- **Revision/license/maintenance:** `9bb9a212ced86caa7e09099c382da1a44d638760`; MIT; last pushed 2025-06-21 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`package.json`](https://github.com/gyoridavid/short-video-maker/blob/9bb9a212ced86caa7e09099c382da1a44d638760/package.json), [`src/short-creator/ShortCreator.ts`](https://github.com/gyoridavid/short-video-maker/blob/9bb9a212ced86caa7e09099c382da1a44d638760/src/short-creator/ShortCreator.ts), [`src/short-creator/libraries/Pexels.ts`](https://github.com/gyoridavid/short-video-maker/blob/9bb9a212ced86caa7e09099c382da1a44d638760/src/short-creator/libraries/Pexels.ts), [`src/short-creator/libraries/Kokoro.ts`](https://github.com/gyoridavid/short-video-maker/blob/9bb9a212ced86caa7e09099c382da1a44d638760/src/short-creator/libraries/Kokoro.ts), [`src/short-creator/libraries/Whisper.ts`](https://github.com/gyoridavid/short-video-maker/blob/9bb9a212ced86caa7e09099c382da1a44d638760/src/short-creator/libraries/Whisper.ts), [`src/server/routers/rest.ts`](https://github.com/gyoridavid/short-video-maker/blob/9bb9a212ced86caa7e09099c382da1a44d638760/src/server/routers/rest.ts), [`main.Dockerfile`](https://github.com/gyoridavid/short-video-maker/blob/9bb9a212ced86caa7e09099c382da1a44d638760/main.Dockerfile).
- **Installation:** Docker recommended; alternatively Node/npm, FFmpeg, Chromium and whisper.cpp build dependencies.
- **Dependencies:** Remotion, Kokoro JS, whisper.cpp, Pexels, Express/MCP, FFmpeg.
- **Capabilities:** Shorts queue combining stock footage, TTS, transcription and Remotion rendering.
- **Decision:** Not installed: large separate media stack, third-party models and Pexels access; duplicates parts of the local renderer. Windows support is not established by upstream.

### 3. [adityaarsharma/youtube-marketing-skills](https://github.com/adityaarsharma/youtube-marketing-skills)

- **Revision/license/maintenance:** `e9136cb39379a82801ee5ae542ff53a1d1109bd2`; MIT; last pushed 2026-10-10 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`package.json`](https://github.com/adityaarsharma/youtube-marketing-skills/blob/e9136cb39379a82801ee5ae542ff53a1d1109bd2/package.json), [`server.js`](https://github.com/adityaarsharma/youtube-marketing-skills/blob/e9136cb39379a82801ee5ae542ff53a1d1109bd2/server.js), [`auth.js`](https://github.com/adityaarsharma/youtube-marketing-skills/blob/e9136cb39379a82801ee5ae542ff53a1d1109bd2/auth.js), [`skills/youtube-marketing/SKILL.md`](https://github.com/adityaarsharma/youtube-marketing-skills/blob/e9136cb39379a82801ee5ae542ff53a1d1109bd2/skills/youtube-marketing/SKILL.md), [`INSTALL.md`](https://github.com/adityaarsharma/youtube-marketing-skills/blob/e9136cb39379a82801ee5ae542ff53a1d1109bd2/INSTALL.md).
- **Installation:** Node/npm plus Google OAuth and MCP-compatible host; follow INSTALL.md.
- **Dependencies:** googleapis, MCP SDK, Express, OAuth local callback.
- **Capabilities:** YouTube data, analytics, thumbnail, video, comment and playlist operations via MCP.
- **Decision:** Not installed: local plaintext token persistence and broad write scopes do not match ViMax owner-isolated OAuth and explicit approval. ViMax already has a separate private-upload path.

### 4. [ahmedsakri/youtube-agent-pro](https://github.com/ahmedsakri/youtube-agent-pro)

- **Revision/license/maintenance:** `45e8e2603d4bf8e17c1147ba870a4ea00eaecbc5`; MIT; last pushed 2026-10-09 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`skills/yt-idea/ideascore.py`](https://github.com/ahmedsakri/youtube-agent-pro/blob/45e8e2603d4bf8e17c1147ba870a4ea00eaecbc5/skills/yt-idea/ideascore.py), [`skills/yt-analytics/funnel.py`](https://github.com/ahmedsakri/youtube-agent-pro/blob/45e8e2603d4bf8e17c1147ba870a4ea00eaecbc5/skills/yt-analytics/funnel.py), [`skills/yt-chapters/chapters.py`](https://github.com/ahmedsakri/youtube-agent-pro/blob/45e8e2603d4bf8e17c1147ba870a4ea00eaecbc5/skills/yt-chapters/chapters.py), [`skills/yt-retention/retention.py`](https://github.com/ahmedsakri/youtube-agent-pro/blob/45e8e2603d4bf8e17c1147ba870a4ea00eaecbc5/skills/yt-retention/retention.py), [`skills/yt-edit/deadair.py`](https://github.com/ahmedsakri/youtube-agent-pro/blob/45e8e2603d4bf8e17c1147ba870a4ea00eaecbc5/skills/yt-edit/deadair.py), [`skills/yt-thumbnail/thumblint.py`](https://github.com/ahmedsakri/youtube-agent-pro/blob/45e8e2603d4bf8e17c1147ba870a4ea00eaecbc5/skills/yt-thumbnail/thumblint.py).
- **Installation:** Python 3; selected heuristics use only the standard library; prompt packs require a compatible agent host.
- **Dependencies:** Python standard library for selected scripts, optional agent host.
- **Capabilities:** Deterministic idea, funnel, chapter, retention and editing heuristics; not live analytics or forecasting.
- **Decision:** Idea scorer was already integrated; funnel analysis is newly integrated for supplied metrics. Other overlapping/prompt-only scripts are not installed.

### 5. [Salimzaks/Youtube-content-creation-agent](https://github.com/Salimzaks/Youtube-content-creation-agent)

- **Revision/license/maintenance:** `018deb20b141a4290716682a3b587de7acf31315`; Unverified: no license file at inspected commit; last pushed 2026-03-15 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`requirements.txt`](https://github.com/Salimzaks/Youtube-content-creation-agent/blob/018deb20b141a4290716682a3b587de7acf31315/requirements.txt), [`agents/modular_langgraph_research_agent.py`](https://github.com/Salimzaks/Youtube-content-creation-agent/blob/018deb20b141a4290716682a3b587de7acf31315/agents/modular_langgraph_research_agent.py), [`tools/brave_search.py`](https://github.com/Salimzaks/Youtube-content-creation-agent/blob/018deb20b141a4290716682a3b587de7acf31315/tools/brave_search.py), [`tools/youtube.py`](https://github.com/Salimzaks/Youtube-content-creation-agent/blob/018deb20b141a4290716682a3b587de7acf31315/tools/youtube.py), [`utils/deepseek_client.py`](https://github.com/Salimzaks/Youtube-content-creation-agent/blob/018deb20b141a4290716682a3b587de7acf31315/utils/deepseek_client.py).
- **Installation:** Python 3.10+, pip install requirements.txt; search, YouTube and model credentials depend on selected features.
- **Dependencies:** LangGraph, LangChain, Streamlit, pandas, Brave/Tavily/YouTube and model APIs.
- **Capabilities:** Multi-model research pipeline with search and YouTube integrations; source also contains demo/fallback pathways.
- **Decision:** Not installed: README links an MIT badge but the inspected tree contains no LICENSE file; clarify rights and remove demo-as-real risk before integration.

### 6. [sergebulaev/youtube-skills](https://github.com/sergebulaev/youtube-skills)

- **Revision/license/maintenance:** `73cd16a05b589d755bf2eef3e4ee9db9e2df5494`; MIT; last pushed 2026-10-27 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`requirements.txt`](https://github.com/sergebulaev/youtube-skills/blob/73cd16a05b589d755bf2eef3e4ee9db9e2df5494/requirements.txt), [`lib/url_parser.py`](https://github.com/sergebulaev/youtube-skills/blob/73cd16a05b589d755bf2eef3e4ee9db9e2df5494/lib/url_parser.py), [`lib/youtube_client.py`](https://github.com/sergebulaev/youtube-skills/blob/73cd16a05b589d755bf2eef3e4ee9db9e2df5494/lib/youtube_client.py), [`lib/approval.py`](https://github.com/sergebulaev/youtube-skills/blob/73cd16a05b589d755bf2eef3e4ee9db9e2df5494/lib/approval.py), [`lib/backend_selector.py`](https://github.com/sergebulaev/youtube-skills/blob/73cd16a05b589d755bf2eef3e4ee9db9e2df5494/lib/backend_selector.py).
- **Installation:** Python, requests and python-dotenv for clients; plugin instructions target agent hosts.
- **Dependencies:** requests, python-dotenv, optional YouTube Data API, optional Publora/Pixfaro.
- **Capabilities:** YouTube URL parsing, API data retrieval, draft skills and optional publishing/image-provider clients.
- **Decision:** Only the dependency-free URL parser is vendored with strict host/path validation. Publishing and network clients are not installed.

### 7. [realjaymes/marketingagentskills](https://github.com/realjaymes/marketingagentskills)

- **Revision/license/maintenance:** `4e02d518f11fedd2f3ad0af3adedef8a576c96e5`; MIT; last pushed 2026-10-23 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`package.json`](https://github.com/realjaymes/marketingagentskills/blob/4e02d518f11fedd2f3ad0af3adedef8a576c96e5/package.json), [`skills/ai-content-generation/SKILL.md`](https://github.com/realjaymes/marketingagentskills/blob/4e02d518f11fedd2f3ad0af3adedef8a576c96e5/skills/ai-content-generation/SKILL.md), [`skills/domain-health/scripts/domain_health.py`](https://github.com/realjaymes/marketingagentskills/blob/4e02d518f11fedd2f3ad0af3adedef8a576c96e5/skills/domain-health/scripts/domain_health.py).
- **Installation:** Agent-host skill documents; package.json lists optional pptxgenjs; domain utilities have separate runtime needs.
- **Dependencies:** agent-host instructions, optional pptxgenjs, Python network tools.
- **Capabilities:** Marketing prompt playbooks and standalone network-oriented scripts.
- **Decision:** Not installed: mostly prompts; overlaps creator planning, and executing networking/scraping would need separate egress and consent review.

### 8. [calesthio/OpenMontage](https://github.com/calesthio/OpenMontage)

- **Revision/license/maintenance:** `e01dbf433f46eeb91d39bf905e194162921019a3`; AGPL-3.0; last pushed 2026-10-24 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`requirements.txt`](https://github.com/calesthio/OpenMontage/blob/e01dbf433f46eeb91d39bf905e194162921019a3/requirements.txt), [`lib/config_model.py`](https://github.com/calesthio/OpenMontage/blob/e01dbf433f46eeb91d39bf905e194162921019a3/lib/config_model.py), [`lib/paths.py`](https://github.com/calesthio/OpenMontage/blob/e01dbf433f46eeb91d39bf905e194162921019a3/lib/paths.py), [`lib/asset_cache.py`](https://github.com/calesthio/OpenMontage/blob/e01dbf433f46eeb91d39bf905e194162921019a3/lib/asset_cache.py), [`lib/slideshow_risk.py`](https://github.com/calesthio/OpenMontage/blob/e01dbf433f46eeb91d39bf905e194162921019a3/lib/slideshow_risk.py).
- **Installation:** Python >=3.10, FFmpeg and npm/Remotion; optional media/model providers.
- **Dependencies:** Python, FastAPI, Remotion, FFmpeg, optional Gemini/OpenAI/other paid providers.
- **Capabilities:** Local creative pipeline with media cache, storyboard, scoring, rendering and optional providers.
- **Decision:** Not installed: AGPL distribution/service obligations, large runtime and external-cost/egress controls need legal and security review.

### 9. [krillinai/OpenCreator](https://github.com/krillinai/OpenCreator)

- **Revision/license/maintenance:** `d17bdc16d431db7a45b138c3180bdae533df003a`; Apache-2.0; last pushed 2026-10-26 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`package.json`](https://github.com/krillinai/OpenCreator/blob/d17bdc16d431db7a45b138c3180bdae533df003a/package.json), [`pnpm-workspace.yaml`](https://github.com/krillinai/OpenCreator/blob/d17bdc16d431db7a45b138c3180bdae533df003a/pnpm-workspace.yaml), [`apps/daemon/package.json`](https://github.com/krillinai/OpenCreator/blob/d17bdc16d431db7a45b138c3180bdae533df003a/apps/daemon/package.json), [`apps/daemon/src/agent-tools/creator-tools.ts`](https://github.com/krillinai/OpenCreator/blob/d17bdc16d431db7a45b138c3180bdae533df003a/apps/daemon/src/agent-tools/creator-tools.ts), [`apps/daemon/src/agent-tools/capability-token.ts`](https://github.com/krillinai/OpenCreator/blob/d17bdc16d431db7a45b138c3180bdae533df003a/apps/daemon/src/agent-tools/capability-token.ts), [`apps/daemon/src/api/routes.approvals.ts`](https://github.com/krillinai/OpenCreator/blob/d17bdc16d431db7a45b138c3180bdae533df003a/apps/daemon/src/api/routes.approvals.ts).
- **Installation:** pnpm workspace with desktop/daemon dependencies and an agent/model runtime.
- **Dependencies:** Node/pnpm, desktop/daemon, Codex runtime, optional media providers.
- **Capabilities:** Desktop daemon with capability tokens, approvals, tasks and media tools.
- **Decision:** Not installed: separate desktop/daemon trust model, large workspace and process capabilities are incompatible with a drop-in Vercel function.

### 10. [Vincentwei1021/video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft)

- **Revision/license/maintenance:** `43bd349a136651865ecfa6ea1cf012f6e957d304`; Apache-2.0; last pushed 2026-10-17 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`package.json`](https://github.com/Vincentwei1021/video-shotcraft/blob/43bd349a136651865ecfa6ea1cf012f6e957d304/package.json), [`template/package.json`](https://github.com/Vincentwei1021/video-shotcraft/blob/43bd349a136651865ecfa6ea1cf012f6e957d304/template/package.json), [`workbench/package.json`](https://github.com/Vincentwei1021/video-shotcraft/blob/43bd349a136651865ecfa6ea1cf012f6e957d304/workbench/package.json), [`assets/lib/helpers/motion.ts`](https://github.com/Vincentwei1021/video-shotcraft/blob/43bd349a136651865ecfa6ea1cf012f6e957d304/assets/lib/helpers/motion.ts), [`assets/audio/ATTRIBUTION.md`](https://github.com/Vincentwei1021/video-shotcraft/blob/43bd349a136651865ecfa6ea1cf012f6e957d304/assets/audio/ATTRIBUTION.md).
- **Installation:** Node/npm, Remotion/React, Chromium and FFmpeg for render templates; review bundled asset terms.
- **Dependencies:** Remotion, React, Vite, Chromium, FFmpeg.
- **Capabilities:** Remotion templates, pure motion helpers and a visual workbench.
- **Decision:** Not installed: a separate rendering stack overlaps current media tools; audio/font assets have separate attribution and rights.

### 11. [FFmpeg/FFmpeg](https://github.com/FFmpeg/FFmpeg)

- **Revision/license/maintenance:** `c69954c34522c53234dfd43fa7a0cb3b02f39e47`; LGPL-2.1-or-later or GPL depending on build; last pushed 2026-10-28 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`LICENSE.md`](https://github.com/FFmpeg/FFmpeg/blob/c69954c34522c53234dfd43fa7a0cb3b02f39e47/LICENSE.md), [`INSTALL.md`](https://github.com/FFmpeg/FFmpeg/blob/c69954c34522c53234dfd43fa7a0cb3b02f39e47/INSTALL.md), [`fftools/ffmpeg.c`](https://github.com/FFmpeg/FFmpeg/blob/c69954c34522c53234dfd43fa7a0cb3b02f39e47/fftools/ffmpeg.c), [`configure`](https://github.com/FFmpeg/FFmpeg/blob/c69954c34522c53234dfd43fa7a0cb3b02f39e47/configure).
- **Installation:** Install a compatible FFmpeg binary with libx264 and AAC, or use imageio-ffmpeg; verify the exact binary license.
- **Dependencies:** FFmpeg executable, libx264 and AAC for the existing renderer.
- **Capabilities:** Audio/video processing and encoding; local ViMax renderer and bounded scene-clip exporter already call FFmpeg.
- **Decision:** Existing local integration; not a hosted online video worker. FFmpeg/model/codec licensing depends on each actual build.

### 12. [comfyanonymous/ComfyUI](https://github.com/comfyanonymous/ComfyUI)

- **Revision/license/maintenance:** `e1df394db644987bfbdd05c887a78b9115d49261`; GPL-3.0; last pushed 2026-10-28 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`requirements.txt`](https://github.com/Comfy-Org/ComfyUI/blob/e1df394db644987bfbdd05c887a78b9115d49261/requirements.txt), [`pyproject.toml`](https://github.com/Comfy-Org/ComfyUI/blob/e1df394db644987bfbdd05c887a78b9115d49261/pyproject.toml), [`main.py`](https://github.com/Comfy-Org/ComfyUI/blob/e1df394db644987bfbdd05c887a78b9115d49261/main.py), [`server.py`](https://github.com/Comfy-Org/ComfyUI/blob/e1df394db644987bfbdd05c887a78b9115d49261/server.py), [`nodes.py`](https://github.com/Comfy-Org/ComfyUI/blob/e1df394db644987bfbdd05c887a78b9115d49261/nodes.py).
- **Installation:** Separate ComfyUI runtime, PyTorch and downloaded model weights; GPU strongly recommended for demanding video workflows.
- **Dependencies:** Python, PyTorch, GPU-specific runtime, model weights, custom nodes.
- **Capabilities:** Node graph for local image/video/model workflows with a separate HTTP server and extensible custom nodes.
- **Decision:** Not installed: arbitrary custom nodes, network access, model rights, resource isolation and GPL obligations need review. A CPU path exists but may be impractical.

### 13. [hexgrad/kokoro](https://github.com/hexgrad/kokoro)

- **Revision/license/maintenance:** `dfb907a02bba8152ca444717ca5d78747ccb4bec`; Apache-2.0; last pushed 2025-08-06 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`pyproject.toml`](https://github.com/hexgrad/kokoro/blob/dfb907a02bba8152ca444717ca5d78747ccb4bec/pyproject.toml), [`kokoro/pipeline.py`](https://github.com/hexgrad/kokoro/blob/dfb907a02bba8152ca444717ca5d78747ccb4bec/kokoro/pipeline.py), [`kokoro/model.py`](https://github.com/hexgrad/kokoro/blob/dfb907a02bba8152ca444717ca5d78747ccb4bec/kokoro/model.py), [`kokoro.js/package.json`](https://github.com/hexgrad/kokoro/blob/dfb907a02bba8152ca444717ca5d78747ccb4bec/kokoro.js/package.json).
- **Installation:** Install Python kokoro/misaki with PyTorch and language-specific phonemizers; download compatible model and voice weights.
- **Dependencies:** PyTorch, misaki, phonemizers/espeak-ng, model/voice weights.
- **Capabilities:** Local text-to-speech pipeline with voice/model loading; model and language support require separate verification.
- **Decision:** Not installed: duplicates existing Piper path; large weights and language/model licenses need review. Urdu availability is not assumed.

### 14. [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper)

- **Revision/license/maintenance:** `9e472ae9de8bb374552f531f752654554b76b2d6`; MIT; last pushed 2026-10-25 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`requirements.txt`](https://github.com/SYSTRAN/faster-whisper/blob/9e472ae9de8bb374552f531f752654554b76b2d6/requirements.txt), [`setup.py`](https://github.com/SYSTRAN/faster-whisper/blob/9e472ae9de8bb374552f531f752654554b76b2d6/setup.py), [`faster_whisper/transcribe.py`](https://github.com/SYSTRAN/faster-whisper/blob/9e472ae9de8bb374552f531f752654554b76b2d6/faster_whisper/transcribe.py), [`faster_whisper/audio.py`](https://github.com/SYSTRAN/faster-whisper/blob/9e472ae9de8bb374552f531f752654554b76b2d6/faster_whisper/audio.py).
- **Installation:** Install faster-whisper/CTranslate2/PyAV and a compatible model; CPU supported, CUDA needs matching runtime.
- **Dependencies:** CTranslate2, PyAV, tokenizers, model weights, optional CUDA/cuDNN.
- **Capabilities:** Speech transcription and timestamps with selectable CPU/GPU inference.
- **Decision:** Not installed: requires model download, CPU/GPU resources and file-isolated worker; no live transcription was tested.

### 15. [googleapis/google-api-nodejs-client](https://github.com/googleapis/google-api-nodejs-client)

- **Revision/license/maintenance:** `206bd0334f32aee0fefe02595f88641a5899c2d1`; Apache-2.0; last pushed 2026-10-22 UTC; GitHub reported not archived at assessment.
- **Source inspected:** [`package.json`](https://github.com/googleapis/google-api-nodejs-client/blob/206bd0334f32aee0fefe02595f88641a5899c2d1/package.json), [`src/googleapis.ts`](https://github.com/googleapis/google-api-nodejs-client/blob/206bd0334f32aee0fefe02595f88641a5899c2d1/src/googleapis.ts), [`src/apis/youtube/index.ts`](https://github.com/googleapis/google-api-nodejs-client/blob/206bd0334f32aee0fefe02595f88641a5899c2d1/src/apis/youtube/index.ts), [`samples/youtube/upload.js`](https://github.com/googleapis/google-api-nodejs-client/blob/206bd0334f32aee0fefe02595f88641a5899c2d1/samples/youtube/upload.js).
- **Installation:** Node/npm googleapis client and Google OAuth with only required YouTube scopes.
- **Dependencies:** googleapis, Google OAuth, YouTube API quota.
- **Capabilities:** Official Google API client including YouTube v3 operations and a private upload sample.
- **Decision:** Client not installed: ViMax already implements official, owner-scoped YouTube REST OAuth/Analytics/private upload; adding a second client would duplicate auth and upload behavior.

## Use and setup

1. On the hosted app, sign in, choose **Creator tools**, enter draft text and select **Preview metadata**. Expand registry entries for source, permissions and tests. The preview remains separate from the existing private-upload code. The server uses the existing session and same-origin POST checks; no migration or new environment variable is required.
2. For local use, follow the existing [local setup](../README.md#windows-setup-powershell), or the Linux/macOS paragraph there. The pinned ViMax entry point registers `youtube_reference_parse` and `youtube_funnel_review` alongside existing tools. These two pure functions need no model, API key or GPU, but a full local companion still needs its separately documented Python/ViMax setup. An LLM-enabled upstream agent can use them only when that local agent is actually configured and running.
3. Once the local **single-user loopback** proxy is running at the documented default port, the registry and local adapters can be called without exposing the internal token:

   ```sh
   curl http://127.0.0.1:4173/api/skills/workforce
   curl -X POST http://127.0.0.1:4173/api/skills/workforce/youtube_url_parser \
     -H "Origin: http://127.0.0.1:4173" -H "Content-Type: application/json" \
     -d '{"input":{"reference":"https://youtu.be/dQw4w9WgXcQ"}}'
   curl -X POST http://127.0.0.1:4173/api/skills/workforce/funnel_heuristic \
     -H "Origin: http://127.0.0.1:4173" -H "Content-Type: application/json" \
     -d '{"input":{"format":"long","metrics":{"impressions":4000,"ctr":2,"avd_seconds":40,"length_seconds":100}}}'
   ```

   Do not bind or port-forward the local services to the Internet. The hosted endpoint allowlists only `metadata_preflight`; it does not dynamically import or run registry entries. The read-only registry does not enable channel APIs, credentials or any external service.

4. Video/voice/transcription stacks remain optional and uninstalled here. Any future integration needs isolated compute and storage, explicit model/asset license checks, per-user permissions, resource limits, egress controls, separate provider setup, and informed cost approval. Never install arbitrary ComfyUI nodes or execute retrieved prompt instructions as code.

## Verification and limitations

- `npm test`: 77 passed, 1 skipped (real PostgreSQL concurrency test not rerun in this increment). Separate Vercel OIDC tests: 3 passed. Hosted build succeeded; production dependency audits for root and `web` reported zero findings at test time.
- Local Python suite in an isolated temporary environment: 71 passed, 3 skipped (no licensed Piper voice model, so full local media and proxy end-to-end were not rerun). One Starlette/anyio deprecation warning. The pinned ViMax ToolRegistry itself was imported and executed for the new local tools; that does not prove a full agent or LLM session is live.
- A synthetic three-scene video and scene clip were processed locally with PySceneDetect/OpenCV and imageio-ffmpeg 7.0.2-static. That temporary binary was built with `--enable-gpl --enable-version3`; the audited FFmpeg commit is not necessarily the binary used. License and codec availability vary by build.
- Chromium tested the hosted UI against the real local metadata adapter and mocked session/Supabase, including mobile layout and sign-out cleanup. The wider hosted chat browser smoke used mocked services. These are not a production-authenticated end-to-end test and do not verify Groq, Google OAuth, YouTube or a live model.
- Source instructions and heuristic outputs are untrusted/advisory. The checks are conservative rather than a complete representation of YouTube rules, international handles, or current policy. No production database changes, source-provider calls, model downloads, paid calls, uploads or publishing were performed for this increment.
