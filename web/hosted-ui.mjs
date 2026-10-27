// The hosted default is a focused chat surface. Preserve the previously built
// upstream workspace and skills page at unlinked paths rather than deleting
// their code or changing the local companion build.
import {copyFile, cp, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export async function installHostedChat(destination, chatSource = path.join(project, 'frontend', 'chat')) {
  const root = path.resolve(destination), skills = path.join(root, 'skills');
  // Fail the build rather than silently discarding either previous interface.
  await copyFile(path.join(root, 'index.html'), path.join(root, 'workspace.html'));
  await copyFile(path.join(skills, 'index.html'), path.join(skills, 'full.html'));
  await mkdir(path.join(root, 'chat'), {recursive:true});
  await cp(chatSource, path.join(root, 'chat'), {recursive:true});
  await copyFile(path.join(chatSource, 'index.html'), path.join(root, 'index.html'));
  // Google OAuth and Supabase email confirmation already return to /skills/.
  // Serving the same shell keeps those links working without changing auth.
  await copyFile(path.join(chatSource, 'index.html'), path.join(skills, 'index.html'));
}
