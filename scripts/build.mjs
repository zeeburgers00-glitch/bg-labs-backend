import {mkdtemp, rm, cp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {UPSTREAM_ARCHIVE, UPSTREAM_SHA} from '../lib/upstream.mjs';
import {applyOverlay} from './apply-overlay.mjs';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const temporary = await mkdtemp(path.join(tmpdir(), 'vimax-build-'));
try {
  const archive = path.join(temporary, 'vimax.tar.gz');
  // curl uses the OS trust store (including enterprise CAs); TLS verification
  // remains enabled. The URL is a fixed, pinned GitHub commit, never user input.
  execFileSync('curl', ['--fail', '--location', '--silent', '--show-error', '--connect-timeout', '20', '--max-time', '120', '--output', archive, UPSTREAM_ARCHIVE], {stdio: 'inherit'});
  execFileSync('tar', ['-xzf', archive, '-C', temporary], {stdio: 'inherit'});
  const web = path.join(temporary, `ViMax-${UPSTREAM_SHA}`, 'web');
  await applyOverlay(web);
  // Ignore dependency lifecycle scripts. Vite's locked native binary packages
  // are still installed; this avoids silently running third-party installers.
  const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const opts = {cwd: web, stdio: 'inherit', shell: process.platform === 'win32'};
  execFileSync(npm, ['ci', '--ignore-scripts', '--no-audit', '--no-fund'], opts);
  execFileSync(npm, ['run', 'build'], opts);
  await rm(path.join(project, 'dist'), {recursive: true, force: true});
  await cp(path.join(web, 'dist'), path.join(project, 'dist'), {recursive: true});
  console.log(`Built ViMax ${UPSTREAM_SHA} with the local skills overlay.`);
} finally {
  await rm(temporary, {recursive: true, force: true});
}
