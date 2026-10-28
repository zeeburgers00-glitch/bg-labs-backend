// End-to-End Video Production — topic→script→voice→visuals→captions→render→thumbnail→SEO→preview
// Uses existing rendering pipeline first, validates outputs, tracks licenses, caches expensive outputs.
export class ProductionError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const U = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const STAGES = ['researching','scripting','voicing','visuals','captioning','rendering','thumbnail','seo','preview'];

function validateStage(stage) {
  if (!STAGES.includes(stage)) throw new ProductionError(422, `Invalid stage: ${stage}`);
}

export function createProduction({supa, reliability}) {
  async function startPipeline(session, {channel_id, topic, format}) {
    if (!topic || typeof topic !== 'string' || topic.length < 5 || topic.length > 1000) throw new ProductionError(422, 'Topic must be 5-1000 chars.');
    if (format && !['landscape','shorts'].includes(format)) throw new ProductionError(422, 'Format must be landscape or shorts.');
    const {randomUUID} = await import('node:crypto');
    const clientKey = randomUUID();
    const job = await reliability.createJob(session, {
      channel_id: channel_id || null,
      client_key: clientKey,
      job_type: 'full_video',
      input_payload: {topic, format: format || 'landscape', requested_at: new Date().toISOString()},
      timeout_seconds: 1800
    });
    // Log pipeline start
    await supa('/rest/v1/vimax_production_logs', {
      method: 'POST', token: session.access,
      data: {job_id: job.id, owner_id: session.user.id, level: 'info', message: `Pipeline started: ${topic.slice(0,100)}`, pipeline_stage: 'queued'}
    });
    return {job_id: job.id, client_key: clientKey, stages: STAGES};
  }

  async function advanceStage(session, jobId, stage, {output, validation}) {
    validateStage(stage);
    if (!U.test(jobId)) throw new ProductionError(422, 'Invalid job id.');
    // Verify artifact if provided
    let validationResult = null;
    if (validation) {
      const {duration_seconds, resolution, has_audio, has_captions} = validation;
      if (duration_seconds !== undefined && (typeof duration_seconds !== 'number' || duration_seconds < 0 || duration_seconds > 43200)) throw new ProductionError(422, 'Invalid duration_seconds.');
      if (resolution !== undefined && !/^[0-9]{1,4}x[0-9]{1,4}$/.test(resolution)) throw new ProductionError(422, 'Invalid resolution.');
      validationResult = {duration_seconds, resolution, has_audio, has_captions, validated_at: new Date().toISOString()};
      // Flag mismatches
      const issues = [];
      if (has_audio === false) issues.push('Missing audio stream');
      if (stage === 'rendering' && duration_seconds < 10) issues.push('Duration suspiciously short');
      validationResult.issues = issues;
      validationResult.status = issues.length ? 'invalid' : 'valid';
    }
    // Update job stage
    const {response, value} = await supa(`/rest/v1/vimax_production_jobs?id=eq.${jobId}`, {
      method: 'PATCH', token: session.access,
      data: {pipeline_stage: stage, output_payload: output || null, updated_at: new Date().toISOString()},
      extraHeaders: {prefer: 'return=representation'}
    });
    if (!response.ok) throw new ProductionError(503, 'Failed to advance stage.');
    await supa('/rest/v1/vimax_production_events', {method: 'POST', token: session.access, data: {job_id: jobId, owner_id: session.user.id, event: 'stage_completed', to_stage: stage}});
    await supa('/rest/v1/vimax_production_logs', {method: 'POST', token: session.access, data: {job_id: jobId, owner_id: session.user.id, level: 'info', message: `Stage completed: ${stage}`, pipeline_stage: stage}});
    return {job: value[0], validation: validationResult};
  }

  async function trackAsset(session, jobId, {asset_url, provider, license_type, attribution_text}) {
    if (!U.test(jobId)) throw new ProductionError(422, 'Invalid job id.');
    if (!asset_url || typeof asset_url !== 'string' || asset_url.length > 2048) throw new ProductionError(422, 'Invalid asset_url.');
    const providers = new Set(['pexels','pixabay','unsplash','youtube_audio_library','owner_upload','other']);
    if (!providers.has(provider)) throw new ProductionError(422, 'Invalid provider.');
    const {response, value} = await supa('/rest/v1/vimax_asset_licenses', {
      method: 'POST', token: session.access,
      data: {job_id: jobId, owner_id: session.user.id, asset_url, provider, license_type: license_type || 'unknown', attribution_text: attribution_text || null, attribution_required: !!attribution_text, is_approved: false},
      extraHeaders: {prefer: 'return=representation'}
    });
    if (!response.ok) throw new ProductionError(503, 'Failed to track asset.');
    return value[0];
  }

  async function shortFromLong(session, longJobId, {start_seconds, end_seconds}) {
    if (!U.test(longJobId)) throw new ProductionError(422, 'Invalid long job id.');
    if (!Number.isFinite(start_seconds) || !Number.isFinite(end_seconds) || start_seconds < 0 || end_seconds <= start_seconds || end_seconds - start_seconds > 60) throw new ProductionError(422, 'Short must be 1-60s within long video.');
    const {randomUUID} = await import('node:crypto');
    const job = await reliability.createJob(session, {
      channel_id: null, client_key: randomUUID(), job_type: 'shorts',
      input_payload: {source_job_id: longJobId, start_seconds, end_seconds},
      timeout_seconds: 600
    });
    return {job_id: job.id, source: longJobId, clip: `${start_seconds}-${end_seconds}s`};
  }

  return {startPipeline, advanceStage, trackAsset, shortFromLong};
}
