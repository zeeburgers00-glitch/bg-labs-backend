import {readFile, writeFile, cp, mkdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export function patchApi(source) {
  const needle = 'await response.json()';
  const count = source.split(needle).length - 1;
  if (count !== 3) throw new Error(`ViMax API overlay expected 3 JSON parses, found ${count}; review upstream changes.`);
  const helper = `\n// ViMax skills overlay: HTML and platform errors are not JSON.\nasync function readJsonResponse(response: Response): Promise<any> {\n  const type = response.headers.get('content-type') || '';\n  if (!/\\bapplication\\/(?:[a-z0-9.+-]+\\+)?json\\b/i.test(type)) {\n    throw new Error(\`ViMax backend returned a non-JSON response (HTTP \${response.status}). Check that the backend is connected.\`);\n  }\n  try { return await response.json(); }\n  catch { throw new Error(\`ViMax backend returned invalid JSON (HTTP \${response.status}). Check the backend logs.\`); }\n}\n`;
  return source.replaceAll(needle, 'await readJsonResponse(response)') + helper;
}

export function patchApp(source) {
  const needle = '          <button className={activeView === \'settings\' ? \'is-active\' : \'\'} onClick={onSettings}><Settings size={17} /><span>Settings</span></button>';
  if (source.split(needle).length !== 2 || !source.includes('  Film,')) throw new Error('ViMax navigation overlay did not match the pinned upstream source.');
  const added = '          <button onClick={() => window.location.assign(\'/skills/\')}><Film size={17} /><span>Skills &amp; Agents</span></button>\n';
  return source.replace(needle, added + needle);
}

export function patchSessionWarning(api, app) {
  const typeBefore = 'activeSessionId: string; sessions: SessionSummary[]';
  const sessionBefore = '    const state = await getSessions();\n    setSessions(state.sessions);';
  if (api.split(typeBefore).length !== 3 || app.split(sessionBefore).length !== 2) {
    throw new Error('ViMax session warning overlay did not match the pinned upstream source.');
  }
  // Both the read and delete response types contain this shape. The optional
  // field leaves local ViMax responses untouched and makes cloud limits clear.
  return {
    api: api.replaceAll(typeBefore, `${typeBefore}; warning?: string`),
    app: app.replace(sessionBefore, '    const state = await getSessions();\n    if (state.warning) setLoadError(state.warning);\n    setSessions(state.sessions);'),
  };
}

export async function applyOverlay(web) {
  const apiPath = path.join(web, 'src', 'api.ts');
  const appPath = path.join(web, 'src', 'App.tsx');
  const patched = patchSessionWarning(patchApi(await readFile(apiPath, 'utf8')), patchApp(await readFile(appPath, 'utf8')));
  await writeFile(apiPath, patched.api);
  await writeFile(appPath, patched.app);
  const destination = path.join(web, 'public', 'skills');
  await mkdir(destination, {recursive: true});
  await cp(path.join(project, 'frontend', 'skills'), destination, {recursive: true});
  await cp(path.join(project, 'catalog', 'catalog.json'), path.join(destination, 'catalog.json'));
}
