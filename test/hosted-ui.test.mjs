import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {installHostedChat} from '../web/hosted-ui.mjs';

test('hosted root and callback path use chat while prior interfaces remain intact', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'vimax-hosted-ui-'));
  try {
    await mkdir(path.join(root, 'skills'));
    await writeFile(path.join(root, 'index.html'), 'original workspace');
    await writeFile(path.join(root, 'skills', 'index.html'), 'original skills');
    await writeFile(path.join(root, 'skills', 'auth-clean.js'), 'original auth scrubber');
    await installHostedChat(root);
    const main = await readFile(path.join(root, 'index.html'), 'utf8');
    assert.equal(await readFile(path.join(root, 'skills', 'index.html'), 'utf8'), main);
    assert.equal(await readFile(path.join(root, 'workspace.html'), 'utf8'), 'original workspace');
    assert.equal(await readFile(path.join(root, 'skills', 'full.html'), 'utf8'), 'original skills');
    assert.equal(await readFile(path.join(root, 'skills', 'auth-clean.js'), 'utf8'), 'original auth scrubber');
    assert.match(main, /id="chat-form"/);
    assert.match(main, /Continue with Google/);
    assert.match(main, /\/skills\/auth-clean\.js/);
    assert.doesNotMatch(main, /<(?:video|iframe)\b|href="\/(?:workspace\.html|skills\/full\.html)/i);
    assert.match(await readFile(path.join(root, 'chat', 'app.js'), 'utf8'), /\/api\/cloud\/youtube\/oauth\/start/);
  } finally { await rm(root, {recursive:true, force:true}); }
});

test('hosted overlay refuses to discard a missing prior interface', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'vimax-hosted-ui-'));
  try {
    await writeFile(path.join(root, 'index.html'), 'original workspace');
    await assert.rejects(installHostedChat(root), {code:'ENOENT'});
    assert.equal(await readFile(path.join(root, 'index.html'), 'utf8'), 'original workspace');
  } finally { await rm(root, {recursive:true, force:true}); }
});
