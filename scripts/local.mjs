// Single-user, loopback-only local companion. Do not bind this to the Internet.
import {createServer, request as httpRequest} from 'node:http';
import {createReadStream, existsSync} from 'node:fs';
import {mkdtemp, readFile, rm, stat, writeFile} from 'node:fs/promises';
import {randomBytes} from 'node:crypto';
import {spawn} from 'node:child_process';
import {createConnection} from 'node:net';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Transform} from 'node:stream';
import {secureUpstream} from './secure-upstream.mjs';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = path.resolve(process.env.VIMAX_SOURCE_DIR || '');
if (!process.env.VIMAX_SOURCE_DIR || !existsSync(path.join(source, 'web', 'server.mjs')) || !existsSync(path.join(source, 'main_agent.py'))) {
  throw new Error('Set VIMAX_SOURCE_DIR to your pinned ViMax checkout (see README.md).');
}
const dist = path.join(project, 'dist');
if (!existsSync(path.join(dist, 'index.html'))) throw new Error('Run npm run build in the ViMax project root first.');
const windows = process.platform === 'win32';
const pythonIn = (root) => path.join(root, '.venv', windows ? 'Scripts' : 'bin', windows ? 'python.exe' : 'python');
const skillPython = process.env.VIMAX_SKILLS_PYTHON || pythonIn(path.join(project, 'skills'));
const agentPython = process.env.VIMAX_AGENT_PYTHON || pythonIn(source);
if (!existsSync(skillPython)) throw new Error('Skills Python environment not found. Set VIMAX_SKILLS_PYTHON or follow the setup guide.');
if (!existsSync(agentPython)) throw new Error('ViMax Python environment not found. Set VIMAX_AGENT_PYTHON or follow the upstream setup.');
const portNumber = (name, fallback) => {
  const port = Number(process.env[name] || fallback);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error(`${name} must be a port from 1024 to 65535.`);
  return port;
};
const port = portNumber('VIMAX_LOCAL_PORT', 4173);
const upstreamPort = portNumber('VIMAX_UPSTREAM_PORT', 4174);
const skillsPort = portNumber('VIMAX_SKILLS_PORT', 4175);
if (new Set([port, upstreamPort, skillsPort]).size !== 3) throw new Error('The three local ports must be different.');
const token = randomBytes(32).toString('hex');
const pythonPath = [path.join(project, 'skills'), source, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter);
const commonEnv = {...process.env, PYTHONPATH: pythonPath, VIMAX_SKILLS_INTERNAL_TOKEN: token};
const temporary = await mkdtemp(path.join(tmpdir(), 'vimax-local-'));
const serverSource = await readFile(path.join(source, 'web', 'server.mjs'), 'utf8');
await writeFile(path.join(temporary, 'server.mjs'), secureUpstream(serverSource, path.join(source, 'web')), {mode: 0o600});
const upstream = spawn(process.execPath, [path.join(temporary, 'server.mjs')], {
  cwd: path.join(source, 'web'), stdio: 'inherit', env: {...commonEnv, VIMAX_SOURCE_ROOT: source, VIMAX_WEB_HOST: '127.0.0.1',
    VIMAX_WEB_PORT: String(upstreamPort), VIMAX_AGENT_COMMAND: agentPython, VIMAX_AGENT_ARGS: '-m vimax_skills.agent_entry'},
});
const skills = spawn(skillPython, ['-m', 'uvicorn', 'vimax_skills.service:create_app', '--factory', '--host', '127.0.0.1', '--port', String(skillsPort)],
  {cwd: project, stdio: 'inherit', env: commonEnv});
const children = [upstream, skills];
let closing = false;
let proxy;
async function cleanup(code = 0) {
  if (closing) return;
  closing = true;
  if (proxy) proxy.close();
  for (const child of children) if (child.exitCode === null) child.kill('SIGTERM');
  await rm(temporary, {recursive:true, force:true});
  process.exit(code);
}
for (const child of children) {
  child.on('error', error => { console.error(`Could not start a local service: ${error.message}`); void cleanup(1); });
  child.on('exit', (code, signal) => { if (!closing) { console.error(`Local service exited (${code ?? signal}).`); void cleanup(1); } });
}
process.on('SIGINT', () => void cleanup());
process.on('SIGTERM', () => void cleanup());

function waitForPort(target, timeout = 30_000) {
  const end = Date.now() + timeout;
  return new Promise((resolve, reject) => {
    function connect() {
      if (closing || Date.now() > end) return reject(new Error(`Local service on port ${target} failed to start.`));
      const socket = createConnection({host:'127.0.0.1',port:target});
      socket.once('connect', () => { socket.destroy(); resolve(); });
      socket.once('error', () => { socket.destroy(); setTimeout(connect, 100); });
    }
    connect();
  });
}
try { await Promise.all([waitForPort(upstreamPort), waitForPort(skillsPort)]); }
catch (error) { console.error(error.message); await cleanup(1); }

function reply(res, status, error) {
  res.writeHead(status, {'content-type':'application/json; charset=utf-8', 'cache-control':'no-store', 'x-content-type-options':'nosniff'});
  res.end(JSON.stringify({error}));
}
function forward(req, res, target, bounded) {
  const headers = {...req.headers, host:`127.0.0.1:${target}`, 'x-vimax-local-token':token};
  delete headers.connection;
  const remote = httpRequest({host:'127.0.0.1', port:target, path:req.url, method:req.method, headers}, upstreamResponse => {
    res.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
    upstreamResponse.pipe(res);
  });
  remote.on('error', () => { if (!res.headersSent) reply(res, 503, 'Local ViMax service is unavailable.'); else res.destroy(); });
  req.on('aborted', () => remote.destroy());
  res.on('close', () => remote.destroy());
  if (bounded) {
    let received = 0;
    const limiter = new Transform({transform(chunk, encoding, done) {
      received += chunk.length;
      if (received > 32768) return done(new Error('Request too large'));
      done(null, chunk);
    }});
    limiter.on('error', () => { remote.destroy(); if (!res.headersSent) reply(res, 413, 'Request is too large.'); });
    req.pipe(limiter).pipe(remote);
  } else req.pipe(remote);
}
const types = {'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8',
  '.json':'application/json; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon','.woff2':'font/woff2'};
proxy = createServer(async (req, res) => {
  const host = (req.headers.host || '').toLowerCase();
  if (![ `127.0.0.1:${port}`, `localhost:${port}` ].includes(host)) return reply(res, 403, 'Invalid local host.');
  const origin = req.headers.origin;
  const site = req.headers['sec-fetch-site'];
  if ((origin && origin !== `http://${host}`) || (site && !['same-origin','none'].includes(site))) return reply(res, 403, 'Cross-origin requests are not allowed.');
  if (!['GET','HEAD'].includes(req.method) && origin !== `http://${host}`) return reply(res, 403, 'A same-origin request is required.');
  let url;
  try { url = new URL(req.url, `http://${host}`); } catch { return reply(res, 400, 'Invalid request URL.'); }
  if (url.pathname.startsWith('/api/skills/')) return forward(req, res, skillsPort, true);
  if (url.pathname.startsWith('/api/') || url.pathname === '/assets/vimax.png') return forward(req, res, upstreamPort, false);
  if (!['GET','HEAD'].includes(req.method)) return reply(res, 405, 'Method not allowed.');
  if (url.pathname === '/skills') { res.writeHead(308, {location:'/skills/'}); return res.end(); }
  let name;
  try { name = decodeURIComponent(url.pathname); } catch { return reply(res, 400, 'Invalid path.'); }
  if (name.includes('\0') || name.includes('\\')) return reply(res, 400, 'Invalid path.');
  let file = path.resolve(dist, '.' + name);
  if (file !== dist && !file.startsWith(dist + path.sep)) return reply(res, 403, 'Invalid path.');
  try {
    const info = await stat(file);
    if (info.isDirectory()) file = path.join(file, 'index.html');
    await stat(file);
  } catch {
    if (!path.extname(name)) file = path.join(dist, 'index.html');
    else return reply(res, 404, 'File not found.');
  }
  res.writeHead(200, {'content-type':types[path.extname(file)] || 'application/octet-stream', 'x-content-type-options':'nosniff', 'cache-control':'no-store'});
  if (req.method === 'HEAD') return res.end();
  const stream = createReadStream(file); stream.on('error', () => res.destroy()); stream.pipe(res);
});
proxy.on('error', error => { console.error(`Local proxy error: ${error.message}`); void cleanup(1); });
proxy.listen(port, '127.0.0.1', () => console.log(`ViMax local companion ready: http://127.0.0.1:${port} (single-user only)`));
