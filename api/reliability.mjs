// Agent Reliability Center — real-time job/agent status, logs, retry, cancellation, recovery.
// Durable jobs with idempotency, bounded retries, timeouts, resumable execution.
// Never marks successful without verification.
import {randomUUID} from 'node:crypto';

export class ReliabilityError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

const U = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const JOB_TYPES = new Set(['research','script','voice','visuals','captions','render','thumbnail','seo','full_video','shorts']);
const STATUSES = new Set(['queued','running','awaiting_approval','completed','failed','cancelled']);
const STAGES = new Set(['queued','researching','scripting','voicing','visuals','captioning','rendering','thumbnail','seo','preview','awaiting_approval','completed','failed','cancelled']);

function requireUUID(value, name) {
  if (typeof value !== 'string' || !U.test(value)) throw new ReliabilityError(422, `Invalid ${name}.`);
  return value;
}

export function createReliability({supa}) {
  async function listJobs(session, {status, limit = 20} = {}) {
    let query = `/rest/v1/vimax_production_jobs?select=id,channel_id,client_key,job_type,pipeline_stage,status,retry_count,max_retries,timeout_seconds,not_before,cancel_requested,cancel_confirmed,created_at,updated_at,completed_at&order=created_at.desc&limit=${Math.min(Math.max(limit,1),50)}`;
    if (status && STATUSES.has(status)) query += `&status=eq.${status}`;
    const {response, value} = await supa(query, {token: session.access});
    if (!response.ok || !Array.isArray(value)) throw new ReliabilityError(503, 'Reliability jobs unavailable.');
    return value;
  }

  async function getJob(session, jobId) {
    requireUUID(jobId, 'job id');
    const {response, value} = await supa(`/rest/v1/vimax_production_jobs?select=*&id=eq.${jobId}&limit=1`, {token: session.access});
    if (!response.ok || !Array.isArray(value) || value.length === 0) throw new ReliabilityError(404, 'Job not found.');
    const job = value[0];
    const [logs, events, artifacts] = await Promise.all([
      supa(`/rest/v1/vimax_production_logs?select=*&job_id=eq.${jobId}&order=id.desc&limit=50`, {token: session.access}),
      supa(`/rest/v1/vimax_production_events?select=*&job_id=eq.${jobId}&order=id.desc&limit=50`, {token: session.access}),
      supa(`/rest/v1/vimax_production_artifacts?select=*&job_id=eq.${jobId}`, {token: session.access}),
    ]);
    return {job, logs: logs.value || [], events: events.value || [], artifacts: artifacts.value || []};
  }

  async function createJob(session, input) {
    if (!input || typeof input !== 'object' || Array.isArray(input)) throw new ReliabilityError(422, 'Invalid job input.');
    const channelId = input.channel_id ? requireUUID(input.channel_id, 'channel_id') : null;
    const clientKey = input.client_key ? requireUUID(input.client_key, 'client_key') : randomUUID();
    if (!JOB_TYPES.has(input.job_type)) throw new ReliabilityError(422, 'Invalid job_type. Use: ' + [...JOB_TYPES].join(', '));
    const timeout = input.timeout_seconds ? Number(input.timeout_seconds) : 300;
    if (!Number.isInteger(timeout) || timeout < 30 || timeout > 3600) throw new ReliabilityError(422, 'Timeout must be 30-3600 seconds.');
    const payload = input.input_payload && typeof input.input_payload === 'object' ? input.input_payload : {};
    if (JSON.stringify(payload).length > 10000) throw new ReliabilityError(422, 'Input payload too large.');

    const {response, value} = await supa('/rest/v1/rpc/vimax_production_submit', {
      method: 'POST', token: session.access,
      data: {p_channel_id: channelId, p_client_key: clientKey, p_job_type: input.job_type, p_input: payload, p_timeout: timeout}
    });
    if (!response.ok || !value || typeof value.id !== 'string') throw new ReliabilityError(503, 'Job submission failed.');
    return {id: value.id, deduplicated: !!value.deduplicated, client_key: clientKey};
  }

  async function cancelJob(session, jobId) {
    requireUUID(jobId, 'job id');
    const {response, value} = await supa('/rest/v1/rpc/vimax_production_cancel', {method: 'POST', token: session.access, data: {p_job_id: jobId}});
    if (!response.ok) {
      if (response.status === 404) throw new ReliabilityError(404, 'Job not found.');
      throw new ReliabilityError(503, 'Cancellation failed.');
    }
    return value;
  }

  async function retryJob(session, jobId) {
    requireUUID(jobId, 'job id');
    const {response, value} = await supa('/rest/v1/rpc/vimax_production_retry', {method: 'POST', token: session.access, data: {p_job_id: jobId}});
    if (!response.ok) throw new ReliabilityError(503, 'Retry failed.');
    if (value.allowed === false) {
      const reasons = {max_retries_exceeded: 'Maximum retries reached.', non_retryable: `Non-retryable error: ${value.error_code}`, not_failed: 'Only failed jobs can be retried.'};
      throw new ReliabilityError(409, reasons[value.reason] || 'Retry not allowed.');
    }
    return value;
  }

  function recoveryDecision(failureRecord) {
    if (!failureRecord || typeof failureRecord !== 'object') throw new ReliabilityError(422, 'Invalid failure record.');
    const code = failureRecord.error_code;
    const nonRetryable = new Set(['credentials','quota_exceeded','cancelled_by_user']);
    const retryable = new Set(['rate_limit','provider_unavailable','worker_config','lease_expired','timeout']);
    const uncertain = new Set(['ambiguous','bad_response']);
    if (nonRetryable.has(code)) return {decision: 'blocked', reason: `Non-retryable: ${code}`};
    if (retryable.has(code)) return {decision: 'retryable', reason: `Retryable: ${code}`};
    if (uncertain.has(code)) return {decision: 'uncertain', reason: 'Ambiguous — manual review required before retry.'};
    return {decision: 'blocked', reason: 'Unknown error — manual review required.'};
  }

  return {listJobs, getJob, createJob, cancelJob, retryJob, recoveryDecision};
}
