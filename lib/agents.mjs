// Agent workforce registry access + deterministic local skill dispatch.
//
// The registry (catalog/agents.json) is configuration, not execution: agents
// are role definitions whose tools live in TOOL_MANIFEST below. Only tools
// marked executable:true can run in this process, and only the local,
// dependency-free vendored CLIs qualify. Everything else is served by the
// Vercel bridge, the separately hosted planning worker, or is gated on
// credentials/hardware — the manifest says which, honestly.
import {execFile} from 'node:child_process';
import {readFile, mkdir, writeFile} from 'node:fs/promises';
import {promisify} from 'node:util';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const exec = promisify(execFile);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const local = (script, argv) => ({executable: true, script, argv});

export const TOOL_MANIFEST = {
  // Local dependency-free vendored heuristics (pinned, reviewed, CLI-smoke-tested 2026-10-28).
  'skill:hookscore': {
    capability: 'wired', runs_on: 'sandbox-local-cli', permission: 'read-only', requires: ['python3'],
    ...local('skills/vendor/youtube-agent-skill/yt-script/hookscore.py', a => ['--hook', a.hook, '--json']),
  },
  'skill:title-lint': {
    capability: 'wired', runs_on: 'sandbox-local-cli', permission: 'read-only', requires: ['python3'],
    ...local('skills/vendor/youtube-agent-skill/yt-package/title.py', a => ['--title', a.title, '--thumb', a.thumbnail || '', '--json']),
  },
  'skill:ideascore': {
    capability: 'wired', runs_on: 'sandbox-local-cli', permission: 'read-only', requires: ['python3'],
    ...local('skills/vendor/youtube-agent-pro/yt-idea/ideascore.py', a => ['--idea', a.idea, '--json']),
  },
  'skill:ratecard': {
    capability: 'wired', runs_on: 'sandbox-local-cli', permission: 'read-only', requires: ['python3'],
    ...local('skills/vendor/youtube-agent-pro/yt-sponsor/ratecard.py', a => ['--views', String(a.views), '--niche', a.niche || 'general', '--placement', a.placement || 'integrated', '--json']),
  },
  'skill:funnel': {
    capability: 'wired', runs_on: 'sandbox-local-cli', permission: 'read-only', requires: ['python3'],
    ...local('skills/vendor/youtube-agent-pro/yt-analytics/funnel.py', a => ['--format', a.format || 'long', '--impressions', String(a.impressions), '--ctr', String(a.ctr), '--avd', String(a.avd), '--length', String(a.length), '--json']),
  },
  // Wired inside the local companion skills service (FastAPI + vendored modules);
  // exposed to the agent runtime as read-only ToolSpecs, not to the public bridge.
  'skill:scene-cuts': {capability: 'wired', runs_on: 'local-companion', permission: 'read-only', requires: ['local companion job video'], executable: false},
  // File-input vendored CLIs: exposed as ToolSpecs in the local companion
  // (skills/vimax_skills/agent_tools.py), smoke-tested 2026-10-28; not invoked
  // from this Node process because their inputs are files, not scalars.
  'skill:retention': {capability: 'wired', runs_on: 'local-companion', permission: 'read-only', requires: ['python3', 'retention CSV file input'], executable: false},
  'skill:deadair': {capability: 'wired', runs_on: 'local-companion', permission: 'read-only', requires: ['python3', 'transcript file input'], executable: false},
  'skill:chapters': {capability: 'wired', runs_on: 'local-companion', permission: 'read-only', requires: ['python3', 'transcript file input'], executable: false},
  'skill:voiceprint': {capability: 'wired', runs_on: 'local-companion', permission: 'read-only', requires: ['python3', 'transcript file input'], executable: false},
  // Existing Vercel bridge routes (verified against api/bridge.mjs route table).
  'bridge:mission-create': {capability: 'wired', runs_on: 'vercel-bridge', permission: 'write', requires: ['signed-in session'], executable: false},
  'bridge:mission-events': {capability: 'wired', runs_on: 'vercel-bridge', permission: 'read', requires: ['signed-in session'], executable: false},
  'bridge:channel-profiles': {capability: 'wired', runs_on: 'vercel-bridge', permission: 'write', requires: ['signed-in session'], executable: false},
  'bridge:competitors': {capability: 'wired', runs_on: 'vercel-bridge', permission: 'write', requires: ['signed-in session'], executable: false},
  'bridge:projects-notes': {capability: 'wired', runs_on: 'vercel-bridge', permission: 'write', requires: ['signed-in session'], executable: false},
  'bridge:chat-history': {capability: 'wired', runs_on: 'vercel-bridge', permission: 'read', requires: ['signed-in session'], executable: false},
  'bridge:usage-report': {capability: 'wired', runs_on: 'vercel-bridge', permission: 'read', requires: ['signed-in session'], executable: false},
  'bridge:health': {capability: 'wired', runs_on: 'vercel-bridge', permission: 'read', requires: [], executable: false},
  'bridge:github-repo-lookup': {capability: 'wired', runs_on: 'vercel-bridge', permission: 'network-public', requires: [], executable: false},
  'bridge:youtube-status': {capability: 'wired', runs_on: 'vercel-bridge', permission: 'read', requires: ['signed-in session'], executable: false},
  'bridge:providers-test': {capability: 'config-gated', runs_on: 'vercel-bridge', permission: 'write', requires: ['provider API key'], executable: false},
  'gate:human-approval': {capability: 'wired', runs_on: 'vercel-bridge', permission: 'write', requires: ['owner approval'], executable: false},
  // Config-gated bridge routes: real code exists but a credential/flag is missing.
  'bridge:chat-completion': {capability: 'config-gated', runs_on: 'vercel-bridge', permission: 'network-provider', requires: ['provider key or gateway free route'], executable: false},
  'bridge:youtube-oauth': {capability: 'config-gated', runs_on: 'vercel-bridge', permission: 'oauth', requires: ['VIMAX_YOUTUBE_CLIENT_SECRET'], executable: false},
  'bridge:youtube-analytics': {capability: 'config-gated', runs_on: 'vercel-bridge', permission: 'read', requires: ['VIMAX_YOUTUBE_ANALYTICS_ENABLED=true', 'read-only analytics consent'], executable: false},
  'bridge:youtube-upload': {capability: 'config-gated', runs_on: 'vercel-bridge', permission: 'write-public', requires: ['VIMAX_YOUTUBE_CLIENT_SECRET', 'DB allowlists', 'owner approval'], executable: false},
  'bridge:social-connect': {capability: 'config-gated', runs_on: 'vercel-bridge', permission: 'oauth', requires: ['Meta/TikTok app credentials'], executable: false},
  'bridge:gpu-preview': {capability: 'config-gated', runs_on: 'vercel-bridge', permission: 'network-paid', requires: ['VIMAX_GPU_ENABLED=true', 'RUNPOD_API_KEY', 'owner approval'], executable: false},
  // Separately hosted worker (scripts/planning-worker.mjs exists; not hosted yet).
  'worker:mission-run': {capability: 'config-gated', runs_on: 'worker-host', permission: 'network-provider', requires: ['planning worker host', 'VIMAX_WORKER_* credentials', 'provider key'], executable: false},
  // Local companion pipeline (code exists in skills/, dependencies not installed here).
  'local:pipeline': {capability: 'config-gated', runs_on: 'local-companion', permission: 'local-exec', requires: ['skills venv: piper-tts, imageio-ffmpeg, Pillow'], executable: false},
  // Paid/optional external services.
  'api:pexels': {capability: 'config-gated', runs_on: 'vercel-bridge', permission: 'network-public', requires: ['PEXELS_API_KEY'], executable: false},
  'external:comfyui': {capability: 'planned', runs_on: 'gpu-host', permission: 'local-exec', requires: ['CUDA GPU host', 'ComfyUI (GPL-3.0) install'], executable: false},
  'external:kokoro-tts': {capability: 'planned', runs_on: 'local-companion', permission: 'local-exec', requires: ['Kokoro-82M model weights', 'python deps'], executable: false},
  'external:faster-whisper': {capability: 'planned', runs_on: 'local-companion', permission: 'local-exec', requires: ['whisper model download', 'ctranslate2'], executable: false},
  'external:web-search': {capability: 'planned', runs_on: 'worker-host', permission: 'network-public', requires: ['SearXNG or crawl4ai integration'], executable: false},
  'browser:playwright': {capability: 'planned', runs_on: 'worker-host', permission: 'browser', requires: ['Playwright install', 'allowlisted targets'], executable: false},
};

export async function loadAgents() {
  const doc = JSON.parse(await readFile(path.join(ROOT, 'catalog', 'agents.json'), 'utf8'));
  const defaults = doc.defaults || {};
  return {
    departments: doc.departments,
    defaults,
    agents: doc.agents.map(a => ({...defaults, ...a})),
  };
}

export function manifestTool(name) {
  const tool = TOOL_MANIFEST[name];
  if (!tool) throw new Error(`unknown tool: ${name}`);
  return tool;
}

/** Execute an executable manifest tool locally. Rejects gated/non-executable tools. */
export async function dispatchTool(name, args, {artifactDir} = {}) {
  const tool = manifestTool(name);
  if (!tool.executable) {
    const err = new Error(`${name} is not executable in this environment (runs_on=${tool.runs_on}, requires=${(tool.requires || []).join('; ') || 'n/a'})`);
    err.code = 'TOOL_NOT_EXECUTABLE';
    throw err;
  }
  const argv = tool.argv(args);
  const {stdout, stderr} = await exec('python3', [path.join(ROOT, tool.script), ...argv], {
    cwd: ROOT, timeout: 30_000, maxBuffer: 4 * 1024 * 1024,
  });
  let parsed = null;
  const trimmed = stdout.trim();
  if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
    try { parsed = JSON.parse(trimmed); } catch { /* keep raw */ }
  }
  const result = {tool: name, stdout, stderr, parsed, ran_at: new Date().toISOString()};
  if (artifactDir) {
    await mkdir(artifactDir, {recursive: true});
    const file = path.join(artifactDir, `${name.replace(/[^a-z0-9]+/gi, '-')}-${Date.now()}.json`);
    await writeFile(file, JSON.stringify(result, null, 1), 'utf8');
    result.artifact = file;
  }
  return result;
}
