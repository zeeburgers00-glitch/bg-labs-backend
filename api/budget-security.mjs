// Budget & Security Controls — per-user/job cost limits, usage, rate limits, concurrency, tenant isolation, audit trails.
export class BudgetError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const U = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function createBudgetSecurity({supa}) {
  async function getLimits(session) {
    const {response, value} = await supa(`/rest/v1/vimax_budget_limits?select=*&owner_id=eq.${session.user.id}&limit=1`, {token: session.access});
    if (!response.ok) throw new BudgetError(503, 'Budget limits unavailable.');
    if (!value || value.length === 0) return {daily_cost_limit_cents: 500, per_job_cost_limit_cents: 100, max_concurrent_jobs: 3, defaults: true};
    return value[0];
  }

  async function setLimits(session, {daily_cost_limit_cents, per_job_cost_limit_cents, max_concurrent_jobs}) {
    if (daily_cost_limit_cents !== undefined && (!Number.isInteger(daily_cost_limit_cents) || daily_cost_limit_cents < 0 || daily_cost_limit_cents > 100000)) throw new BudgetError(422, 'Invalid daily_cost_limit_cents.');
    if (per_job_cost_limit_cents !== undefined && (!Number.isInteger(per_job_cost_limit_cents) || per_job_cost_limit_cents < 0 || per_job_cost_limit_cents > 10000)) throw new BudgetError(422, 'Invalid per_job_cost_limit_cents.');
    if (max_concurrent_jobs !== undefined && (!Number.isInteger(max_concurrent_jobs) || max_concurrent_jobs < 1 || max_concurrent_jobs > 10)) throw new BudgetError(422, 'Invalid max_concurrent_jobs.');
    const patch = {};
    if (daily_cost_limit_cents !== undefined) patch.daily_cost_limit_cents = daily_cost_limit_cents;
    if (per_job_cost_limit_cents !== undefined) patch.per_job_cost_limit_cents = per_job_cost_limit_cents;
    if (max_concurrent_jobs !== undefined) patch.max_concurrent_jobs = max_concurrent_jobs;
    if (Object.keys(patch).length === 0) throw new BudgetError(422, 'No limits to update.');
    patch.owner_id = session.user.id;
    patch.updated_at = new Date().toISOString();
    const {response, value} = await supa('/rest/v1/vimax_budget_limits', {
      method: 'POST', token: session.access, data: patch,
      extraHeaders: {prefer: 'resolution=merge-duplicates,return=representation'}
    });
    if (!response.ok) throw new BudgetError(503, 'Failed to set budget limits.');
    // Audit
    await supa('/rest/v1/vimax_audit_trail', {method: 'POST', token: session.access, data: {owner_id: session.user.id, action: 'cost_limit_changed', target_type: 'budget', details: patch}});
    return value[0];
  }

  async function getUsage(session, {limit = 20} = {}) {
    const {response, value} = await supa(`/rest/v1/vimax_usage_reports?select=*&order=created_at.desc&limit=${Math.min(limit,100)}`, {token: session.access});
    if (!response.ok || !Array.isArray(value)) throw new BudgetError(503, 'Usage reports unavailable.');
    const totalCents = value.reduce((s,r) => s + (r.cost_cents||0), 0);
    return {reports: value, total_cents: totalCents, total_dollars: (totalCents/100).toFixed(2)};
  }

  async function getAuditTrail(session, {limit = 50} = {}) {
    const {response, value} = await supa(`/rest/v1/vimax_audit_trail?select=*&order=created_at.desc&limit=${Math.min(limit,100)}`, {token: session.access});
    if (!response.ok || !Array.isArray(value)) throw new BudgetError(503, 'Audit trail unavailable.');
    return value;
  }

  async function checkConcurrency(session) {
    const limits = await getLimits(session);
    const {response, value} = await supa(`/rest/v1/vimax_production_jobs?select=id&status=eq.running&limit=20`, {token: session.access});
    if (!response.ok || !Array.isArray(value)) throw new BudgetError(503, 'Concurrency check failed.');
    return {running: value.length, limit: limits.max_concurrent_jobs, allowed: value.length < limits.max_concurrent_jobs};
  }

  return {getLimits, setLimits, getUsage, getAuditTrail, checkConcurrency};
}
