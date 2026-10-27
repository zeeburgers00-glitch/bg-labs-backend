// Vercel is configured with web/ as its root and includes files outside that
// directory. Reuse the one canonical build, then copy its output into web/dist.
import {execFileSync} from 'node:child_process';
import {cp, rm} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
execFileSync(process.execPath, [path.join(root, 'scripts', 'build.mjs')], {cwd:root, stdio:'inherit'});
const destination = path.join(root, 'web', 'dist');
await rm(destination, {recursive:true, force:true});
await cp(path.join(root, 'dist'), destination, {recursive:true});
