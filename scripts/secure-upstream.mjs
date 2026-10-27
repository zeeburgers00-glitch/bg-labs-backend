// Create a temporary, token-gated copy of ViMax's local web server. The source
// checkout itself is not modified. The exact pinned source is intentionally
// checked by structural anchors so unexpected upstream changes fail closed.
import {pathToFileURL} from 'node:url';
import path from 'node:path';

function replaceOnce(source, before, after, label) {
  if (source.split(before).length !== 2) throw new Error(`Unexpected ViMax ${label}; review this overlay before starting.`);
  return source.replace(before, after);
}
export function secureUpstream(source, webDirectory) {
  source = replaceOnce(source, "import {createServer} from 'node:http';", "import {createServer} from 'node:http';\nimport {timingSafeEqual} from 'node:crypto';", 'HTTP import');
  source = replaceOnce(source, "from './config-store.mjs'", `from '${pathToFileURL(path.join(webDirectory, 'config-store.mjs')).href}'`, 'config import');
  source = replaceOnce(source, "from './server-lib.mjs'", `from '${pathToFileURL(path.join(webDirectory, 'server-lib.mjs')).href}'`, 'server library import');
  source = replaceOnce(source, "const repoRoot = path.resolve(webRoot, '..');", "const repoRoot = path.resolve(process.env.VIMAX_SOURCE_ROOT);", 'workspace root');
  const needle = 'const server = createServer(async (request, response) => {';
  const guard = `\n  const expected = Buffer.from(process.env.VIMAX_SKILLS_INTERNAL_TOKEN || '');\n  const received = Buffer.from(typeof request.headers['x-vimax-local-token'] === 'string' ? request.headers['x-vimax-local-token'] : '');\n  if (expected.length < 32 || received.length !== expected.length || !timingSafeEqual(expected, received)) {\n    response.writeHead(403, {'content-type': 'application/json', 'cache-control': 'no-store'});\n    response.end(JSON.stringify({error: 'Local ViMax access denied.'}));\n    return;\n  }\n`;
  return replaceOnce(source, needle, needle + guard, 'request handler');
}
