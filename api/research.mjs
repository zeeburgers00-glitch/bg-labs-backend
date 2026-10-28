// Research & Fact Verification — configured search providers, citations, timestamps.
// Treats external content as untrusted. SSRF protection, URL validation, prompt-injection defenses.
export class ResearchError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

// SSRF-safe URL allowlist
const ALLOWED_HOSTS = new Set([
  'en.wikipedia.org','www.youtube.com','youtube.com','www.google.com',
  'pexels.com','api.pexels.com','pixabay.com','unsplash.com',
  'github.com','api.github.com','raw.githubusercontent.com'
]);
const BLOCKED_PATTERNS = [
  /^https?:\/\/localhost/i, /^https?:\/\/127\./i, /^https?:\/\/10\./i,
  /^https?:\/\/192\.168\./i, /^https?:\/\/172\.(1[6-9]|2[0-9]|3[0-1])\./i,
  /^https?:\/\/0\.0\.0\.0/i, /^https?:\/\/\[::/i, /^https?:\/\/169\.254\./i
];

function isSafeUrl(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:') return false;
    if (u.username || u.password || u.port) return false;
    if (u.search.length > 2000 || u.pathname.length > 2000) return false;
    for (const p of BLOCKED_PATTERNS) if (p.test(url)) return false;
    // Private IP ranges already blocked; allow only known hosts or youtube/google for now
    // For general research, allow any public https host that passes private-IP checks
    return true;
  } catch { return false; }
}

function sanitizeInput(text, maxLen = 2000) {
  if (typeof text !== 'string' || text.length > maxLen) throw new ResearchError(422, `Input too long or invalid (max ${maxLen}).`);
  // Prompt-injection defense: strip hidden instruction patterns
  const suspicious = [/ignore previous instructions/i, /system:\s*you are/i, /\[INST\]/i, /<\|im_start\|>/i];
  for (const p of suspicious) if (p.test(text)) throw new ResearchError(422, 'Input contains disallowed instruction patterns.');
  if (/[<>]/.test(text) || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(text)) throw new ResearchError(422, 'Invalid characters in input.');
  return text.trim();
}

export function createResearch({supa, fetchImpl}) {
  async function validateUrl(url) {
    const clean = sanitizeInput(url, 2048);
    if (!isSafeUrl(clean)) throw new ResearchError(422, 'URL is not allowed. Use public https URLs only (no localhost/private IPs).');
    return clean;
  }

  async function fetchSource(url, session) {
    const safeUrl = await validateUrl(url);
    // Never auto-execute fetched content; return raw for citation
    let response;
    try {
      response = await fetchImpl(safeUrl, {
        method: 'GET',
        headers: {'user-agent': 'ViMax-Research/1.0', 'accept': 'text/html,application/json'},
        redirect: 'error', signal: AbortSignal.timeout(8000)
      });
    } catch { throw new ResearchError(503, 'Source fetch failed or timed out.'); }
    if (!response.ok) throw new ResearchError(502, `Source returned ${response.status}.`);
    const ct = response.headers.get('content-type') || '';
    if (!ct.includes('text/') && !ct.includes('application/json') && !ct.includes('application/xml')) {
      throw new ResearchError(422, 'Source content type not allowed.');
    }
    const text = await response.text();
    if (text.length > 50000) throw new ResearchError(422, 'Source content too large (max 50KB).');
    return {url: safeUrl, contentType: ct, body: text.slice(0, 50000), fetchedAt: new Date().toISOString(), treated_as: 'untrusted_data'};
  }

  async function saveCitation(session, {job_id, url, title, claim_text, verification_status}) {
    if (job_id) sanitizeInput(job_id, 36);
    const safeUrl = await validateUrl(url);
    if (title) sanitizeInput(title, 500);
    if (claim_text) sanitizeInput(claim_text, 2000);
    const validStatuses = new Set(['verified','unverified','conflicting','unsupported']);
    if (verification_status && !validStatuses.has(verification_status)) throw new ResearchError(422, 'Invalid verification_status.');
    const {response, value} = await supa('/rest/v1/vimax_research_sources', {
      method: 'POST', token: session.access,
      data: {job_id: job_id || null, url: safeUrl, title: title || null, claim_text: claim_text || null, verification_status: verification_status || 'unverified'},
      extraHeaders: {prefer: 'return=representation'}
    });
    if (!response.ok) throw new ResearchError(503, 'Failed to save citation.');
    return value[0];
  }

  async function listCitations(session, jobId) {
    let query = '/rest/v1/vimax_research_sources?select=*&order=accessed_at.desc&limit=50';
    if (jobId) query += `&job_id=eq.${jobId}`;
    const {response, value} = await supa(query, {token: session.access});
    if (!response.ok || !Array.isArray(value)) throw new ResearchError(503, 'Citations unavailable.');
    return value;
  }

  return {validateUrl, fetchSource, saveCitation, listCitations, isSafeUrl, sanitizeInput};
}
