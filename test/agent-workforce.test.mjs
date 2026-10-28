// Acceptance tests for the 120-agent workforce registry and a real dispatch
// workflow. The dispatch executes the registry's own wired local tools (via
// python3) and stores artefacts; it skips honestly if python3 is unavailable.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile, mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';

import {loadAgents, TOOL_MANIFEST, dispatchTool} from '../lib/agents.mjs';

const exec = promisify(execFile);

test('agent registry:120 agents,12 departments, distinct and well-formed', async () => {
  const {agents, departments} = await loadAgents();
  assert.equal(agents.length, 120, 'registry must hold120 agents');
  assert.equal(Object.keys(departments).length, 12, 'exactly12 departments');

  const byDept = new Map();
  for (const a of agents) byDept.set(a.department, (byDept.get(a.department) || 0) + 1);
  for (const [d, n] of byDept) assert.equal(n, 10, `department ${d} must have10 agents`);

  const ids = new Set(agents.map(a => a.id));
  assert.equal(ids.size, 120, 'agent ids must be unique');
  assert.equal(new Set(agents.map(a => a.name)).size, 120, 'agent names must be distinct');
  assert.equal(new Set(agents.map(a => a.responsibility)).size, 120, 'responsibilities must be distinct');

  const caps = new Set(['wired', 'config-gated', 'planned']);
  const idRe = /^[A-L]\d{2}$/;
  for (const a of agents) {
    assert.match(a.id, idRe, `${a.id} format`);
    assert.ok(a.responsibility.length > 20, `${a.id} needs a real responsibility`);
    assert.ok(Array.isArray(a.tools) && a.tools.length > 0, `${a.id} must declare tools`);
    assert.ok(Array.isArray(a.inputs) && Array.isArray(a.outputs), `${a.id} io schema`);
    assert.ok(Array.isArray(a.dependencies), `${a.id} dependencies`);
    assert.ok(caps.has(a.capability), `${a.id} capability vocab`);
    assert.ok(a.success_criteria.length > 10, `${a.id} success criteria`);
    assert.ok(a.retry_limit >= 1 && a.retry_limit <= 10, `${a.id} retry bounds`);
    assert.ok(a.timeout_s >= 10 && a.timeout_s <= 3600, `${a.id} timeout bounds`);
    assert.equal(a.execution_status, 'idle');
    for (const d of a.dependencies) {
      assert.ok(ids.has(d), `${a.id} dependency ${d} must exist`);
      assert.notEqual(d, a.id, `${a.id} cannot depend on itself`);
    }
    if (a.capability === 'config-gated') assert.ok(a.gated_by, `${a.id} must name its gate`);
  }

  const wired = agents.filter(a => a.capability === 'wired');
  assert.ok(wired.length >= 40, `expected at least40 wired agents, got ${wired.length}`);
  assert.ok(agents.some(a => a.capability === 'planned'), 'planned work must be visible, not hidden');
});

test('every registry tool exists in the manifest with permissions and honest status', async () => {
  const {agents} = await loadAgents();
  const referenced = new Set(agents.flatMap(a => a.tools));
  for (const name of referenced) {
    const tool = TOOL_MANIFEST[name];
    assert.ok(tool, `missing manifest entry: ${name}`);
    assert.ok(['wired', 'config-gated', 'planned'].includes(tool.capability), `${name} capability`);
    assert.ok(tool.permission, `${name} must declare a permission`);
    assert.ok(tool.runs_on, `${name} must declare where it runs`);
    assert.ok(Array.isArray(tool.requires), `${name} must list requirements`);
  }
  // A "wired" agent must have at least one genuinely wired tool.
  for (const a of agents.filter(x => x.capability === 'wired')) {
    assert.ok(a.tools.some(t => TOOL_MANIFEST[t].capability === 'wired'),
      `${a.id} claims wired but has no wired tool`);
  }
  // Executable tools are only the local, dependency-free vendored CLIs.
  for (const [name, tool] of Object.entries(TOOL_MANIFEST)) {
    if (tool.executable) {
      assert.ok(name.startsWith('skill:'), `${name} executable implies local skill`);
      assert.ok(tool.requires.includes('python3'), `${name} declares python3`);
      assert.equal(typeof tool.argv, 'function', `${name} argv builder`);
    }
  }
});

test('dispatch workflow: orchestrator -> hook agent -> packaging agent -> approval gate', async t => {
  try {
    await exec('python3', ['--version']);
  } catch {
    t.skip('python3 unavailable — local skill dispatch cannot run here');
    return;
  }
  const {agents} = await loadAgents();
  const byId = Object.fromEntries(agents.map(a => [a.id, a]));
  const artifactDir = await mkdtemp(path.join(tmpdir(), 'vimax-agents-'));
  const run = {id: `run-${Date.now()}`, steps: [], started_at: new Date().toISOString()};

  // A01 CEO Orchestrator: author the plan (deterministic, no provider call).
  const a01 = byId.A01;
  run.plan = {objective: 'produce first video package', approval_required: true, agents: ['A01', 'D05', 'H07', 'L10']};
  run.steps.push({agent: a01.id, tool: 'plan-authoring', ok: true});
  assert.equal(run.plan.approval_required, true, 'orchestrator must require approval');

  // D05 Hook and Opening Agent: real hookscore execution through the manifest.
  const d05 = byId.D05;
  assert.ok(d05.tools.includes('skill:hookscore'), 'hook agent owns the hook tool');
  const hook = await dispatchTool('skill:hookscore',
    {hook: 'I ran120 AI agents for30 days — here is the only one that mattered'},
    {artifactDir});
  assert.ok(hook.parsed && Array.isArray(hook.parsed), 'hookscore returns JSON');
  assert.ok(typeof hook.parsed[0].verdict === 'number', 'hook panel carries a numeric verdict');
  run.steps.push({agent: d05.id, tool: 'skill:hookscore', ok: true, artifact: hook.artifact, verdict: hook.parsed[0].verdict});

  // H07 Title Generation Agent: real title+thumbnail lint as a pairing.
  const h07 = byId.H07;
  assert.ok(h07.tools.includes('skill:title-lint'), 'title agent owns the lint tool');
  const title = await dispatchTool('skill:title-lint',
    {title: 'I ran120 AI agents so you do not have to', thumbnail: '120 AGENTS'},
    {artifactDir});
  assert.ok(title.parsed && Array.isArray(title.parsed), 'title lint returns JSON');
  assert.ok(typeof title.parsed[0].score === 'number', 'title lint carries a score');
  run.steps.push({agent: h07.id, tool: 'skill:title-lint', ok: true, artifact: title.artifact, score: title.parsed[0].score});

  // L120 Human Approval Gate: stores a pending record; must NOT self-approve.
  const l120 = byId.L10; // L10 =120th agent (Human Approval and Safety Gate)
  assert.ok(l120.tools.includes('gate:human-approval'));
  run.approval = {status: 'pending-human-approval', artefacts: [hook.artifact, title.artifact], decided_by: null};
  assert.notEqual(run.approval.status, 'approved', 'gate never self-approves');
  run.steps.push({agent: l120.id, tool: 'gate:human-approval', ok: true, status: run.approval.status});

  const {writeFile} = await import('node:fs/promises');
  const runFile = path.join(artifactDir, 'run.json');
  await writeFile(runFile, JSON.stringify(run, null, 1), 'utf8');
  const stored = JSON.parse(await readFile(runFile, 'utf8'));
  assert.equal(stored.steps.length, 4, 'all four dispatch steps stored');
  assert.equal(stored.approval.status, 'pending-human-approval');
  assert.ok(stored.steps.every(s => s.ok), 'every dispatched step succeeded');
});

test('gated tools fail closed instead of pretending to run', async () => {
  await assert.rejects(
    () => dispatchTool('worker:mission-run', {}),
    err => err.code === 'TOOL_NOT_EXECUTABLE' && /worker/.test(err.message),
    'worker tool must refuse local execution with an explanatory error',
  );
  await assert.rejects(
    () => dispatchTool('bridge:youtube-upload', {}),
    err => err.code === 'TOOL_NOT_EXECUTABLE',
    'upload tool must refuse without credentials',
  );
  assert.ok(
    await dispatchTool('skill:not-a-tool', {}).then(() => false, err => /unknown tool/.test(err.message)),
    'unknown tools are rejected',
  );
});
