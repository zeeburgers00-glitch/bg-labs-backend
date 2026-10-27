import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const readJson = async path => JSON.parse(await readFile(new URL(path, import.meta.url), 'utf8'));

test('requested repositories and references appear exactly once with honest statuses', async () => {
  const catalog = await readJson('../catalog/catalog.json');
  const requested = await readJson('../catalog/requested-sources.json');
  const ids = catalog.entries.map(entry => entry.id);
  assert.equal(new Set(ids).size, ids.length, 'catalog ids must be unique');
  for (const repo of requested.repositories) {
    const entries = catalog.entries.filter(entry => entry.name.toLowerCase() === repo.name.toLowerCase());
    assert.equal(entries.length, 1, `missing or duplicate ${repo.name}`);
    assert.ok(['partial', 'reviewed', 'unavailable'].includes(entries[0].status));
    assert.equal(entries[0].source, repo.source);
  }
  for (const source of [...requested.topic_pages, ...requested.official_docs, ...requested.discovery_pages]) {
    const entries = catalog.entries.filter(entry => entry.source === source);
    assert.equal(entries.length, 1, `missing or duplicate reference ${source}`);
    assert.equal(entries[0].status, 'reference');
  }
  const integrated = new Set(catalog.entries.filter(entry => entry.status === 'partial').map(entry => entry.name));
  assert.deepEqual(integrated, new Set(['Jakeschincariol/youtube-agent-skill', 'ahmedsakri/youtube-agent-pro',
    'rhasspy/piper', 'FFmpeg/FFmpeg', 'opencv/opencv', 'Breakthrough/PySceneDetect']));
  for (const name of ['shotcut/shotcut', 'electron-vite/electron-vite']) {
    assert.equal(catalog.entries.find(entry => entry.name === name).status, 'unavailable');
  }
  const cgpu = catalog.entries.find(entry => entry.name === 'RohanAdwankar/cgpu');
  assert.equal(cgpu.status, 'reviewed');
  assert.equal(cgpu.revision, '6895aa73c666a66a7220345341998e40c571b343');
  assert.match(cgpu.security, /Not installed or connected/);
  assert.match(cgpu.description, /not a video model or a ViMax GPU worker/i);
});

test('catalog links, features and assessment fields are safe to display', async () => {
  const catalog = await readJson('../catalog/catalog.json');
  const hosts = new Set(['github.com', 'developers.google.com', 'developers.tiktok.com', 'developers.facebook.com']);
  for (const entry of catalog.entries) {
    const url = new URL(entry.source);
    assert.equal(url.protocol, 'https:');
    assert.ok(hosts.has(url.hostname), entry.source);
    for (const key of ['id', 'name', 'description', 'license', 'requirements', 'platform', 'security']) {
      assert.equal(typeof entry[key], 'string', `${entry.name}: ${key}`);
    }
    assert.ok(Array.isArray(entry.features));
  }
});
