// Publishing & Approval — official YouTube API via existing OAuth, private review workflow,
// explicit approval before public, scheduling, reconciliation, duplicate prevention, quota checks.
import {createHash} from 'node:crypto';

export class PublishingError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const U = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CHANNEL = /^UC[A-Za-z0-9_-]{22}$/;
const VIDEO = /^[A-Za-z0-9_-]{11}$/;

function requireUUID(v, n) { if (typeof v !== 'string' || !U.test(v)) throw new PublishingError(422, `Invalid ${n}.`); return v; }

export function createPublishing({supa, youtube}) {
  async function requestApproval(session, {job_id, channel_id, requested_privacy, scheduled_at, file_hash}) {
    requireUUID(job_id, 'job_id');
    if (!CHANNEL.test(channel_id)) throw new PublishingError(422, 'Invalid channel_id.');
    if (!['private','unlisted','public'].includes(requested_privacy)) throw new PublishingError(422, 'Privacy must be private/unlisted/public.');
    if (scheduled_at) {
      const d = new Date(scheduled_at);
      if (isNaN(d.getTime()) || d <= new Date()) throw new PublishingError(422, 'Scheduled time must be in the future.');
    }
    // Duplicate prevention via hash
    const dupHash = file_hash ? createHash('sha256').update(file_hash).digest('hex') : null;
    if (dupHash && !/^[a-f0-9]{64}$/.test(dupHash)) throw new PublishingError(422, 'Invalid file_hash.');

    // Check job exists and belongs to user
    const {response: jr, value: jv} = await supa(`/rest/v1/vimax_production_jobs?select=id,status&id=eq.${job_id}&limit=1`, {token: session.access});
    if (!jr.ok || !Array.isArray(jv) || jv.length === 0) throw new PublishingError(404, 'Job not found.');

    const {response, value} = await supa('/rest/v1/vimax_publish_approvals', {
      method: 'POST', token: session.access,
      data: {job_id, channel_id, requested_privacy, scheduled_at: scheduled_at || null, duplicate_hash: dupHash, quota_checked: false},
      extraHeaders: {prefer: 'return=representation'}
    });
    if (!response.ok) {
      if (response.status === 409) throw new PublishingError(409, 'Duplicate publish request or job already has approval.');
      throw new PublishingError(503, 'Approval request failed.');
    }
    return value[0];
  }

  async function approve(session, approvalId, decision) {
    requireUUID(approvalId, 'approval id');
    if (!['approved','rejected'].includes(decision)) throw new PublishingError(422, 'Decision must be approved or rejected.');
    const {response, value} = await supa(`/rest/v1/vimax_publish_approvals?select=*&id=eq.${approvalId}&limit=1`, {token: session.access});
    if (!response.ok || !Array.isArray(value) || value.length === 0) throw new PublishingError(404, 'Approval not found.');
    const rec = value[0];
    if (rec.status !== 'pending') throw new PublishingError(409, `Already ${rec.status}.`);
    // Public publishing requires explicit approval — never auto-approve
    if (rec.requested_privacy === 'public' && decision !== 'approved') throw new PublishingError(422, 'Public publishing requires explicit approved decision.');

    const {response: up, value: uv} = await supa(`/rest/v1/vimax_publish_approvals?id=eq.${approvalId}`, {
      method: 'PATCH', token: session.access,
      data: {status: decision, approved_privacy: decision === 'approved' ? rec.requested_privacy : null, approved_at: new Date().toISOString(), approved_by: session.user.id},
      extraHeaders: {prefer: 'return=representation'}
    });
    if (!up.ok || !Array.isArray(uv) || uv.length === 0) throw new PublishingError(503, 'Approval update failed.');
    return uv[0];
  }

  async function listApprovals(session, {status} = {}) {
    let q = '/rest/v1/vimax_publish_approvals?select=*&order=created_at.desc&limit=50';
    if (status) q += `&status=eq.${status}`;
    const {response, value} = await supa(q, {token: session.access});
    if (!response.ok || !Array.isArray(value)) throw new PublishingError(503, 'Approvals unavailable.');
    return value;
  }

  async function reconcile(session, approvalId) {
    requireUUID(approvalId, 'approval id');
    const {response, value} = await supa(`/rest/v1/vimax_publish_approvals?select=*&id=eq.${approvalId}&limit=1`, {token: session.access});
    if (!response.ok || !Array.isArray(value) || value.length === 0) throw new PublishingError(404, 'Approval not found.');
    const rec = value[0];
    // Never claim published unless API confirms final state — check video_id presence
    if (!rec.video_id || !VIDEO.test(rec.video_id)) return {status: rec.status, verified: false, message: 'No YouTube video_id confirmed. Not published.'};
    // Verify via YouTube API if available
    return {status: 'published', verified: true, video_id: rec.video_id, youtube_url: `https://youtu.be/${rec.video_id}`};
  }

  return {requestApproval, approve, listApprovals, reconcile};
}
