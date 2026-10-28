// A fixed registry of inspected skills; nothing here dynamically loads a repo,
// downloads code, opens files supplied by a user, publishes, or calls a provider.
import registry from '../catalog/workforce-skills.json' with {type:'json'};
import metadata from '../vendor/youtube-automation-agent/youtube-metadata-validator.cjs';
import {SkillError} from './skill-error.mjs';
import {youtubeReference, funnelReview, ideaReview, hookReview, titleReview} from './creator-skills.mjs';
export {SkillError} from './skill-error.mjs';

export function workforceRegistry() {
  // Do not let a caller mutate the shared module cache between requests.
  return structuredClone(registry);
}

function field(input, name, max, fallback = '') {
  const value = input[name] === undefined ? fallback : input[name];
  if (typeof value !== 'string' || value.length > max || /[<>\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value)) {
    throw new SkillError(422, `Check the ${name} field: invalid characters or length.`);
  }
  return value.trim();
}

// This is advisory-only. The upload route has its own stricter validation and
// never consumes this result automatically. The pinned upstream normalizes and
// truncates, so reject too-long values before calling it and disclose changes.
export function metadataPreflight(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)
      || Object.keys(input).some(key => !['title','description','tags','categoryId','defaultLanguage'].includes(key))) {
    throw new SkillError(422, 'Provide only title, description, tags, category and language.');
  }
  const title = field(input, 'title', 100);
  const description = field(input, 'description', 5000);
  const tagsText = field(input, 'tags', 450);
  const categoryId = field(input, 'categoryId', 3, '22');
  const defaultLanguage = field(input, 'defaultLanguage', 35, 'en');
  if (!title || Buffer.byteLength(description, 'utf8') > 5000
      || !/^\d{1,3}$/.test(categoryId) || !/^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(defaultLanguage)) {
    throw new SkillError(422, 'Enter a title, a valid category and language, and a description within the size limit.');
  }
  const tags = tagsText ? tagsText.split(',').map(tag => tag.trim()).filter(Boolean) : [];
  if (tags.length > 30 || tags.some(tag => tag.length > 100)) throw new SkillError(422, 'Use at most 30 tags, each up to 100 characters.');
  const checked = metadata.validateYouTubeMetadata({title, description, tags, categoryId, defaultLanguage, defaultAudioLanguage:defaultLanguage});
  const changes = [];
  if (checked.value.title !== input.title) changes.push('Title whitespace was normalized in this preview.');
  if (checked.value.description !== (input.description || '')) changes.push('Description whitespace or control characters, including line breaks, were normalized in this preview.');
  if (checked.value.tags.join(', ') !== tagsText || JSON.stringify(checked.value.tags) !== JSON.stringify(tags)) changes.push('Tags were normalized or deduplicated in this preview.');
  return {valid:checked.valid, errors:checked.errors, warnings:checked.warnings, changes, preview:checked.value,
    notice:'Advisory preview only. Nothing was saved, sent to YouTube or published; review the final metadata separately.'};
}

// A small, synchronous composition of actual read-only tools. It never fetches
// a competitor, executes agent-provided code, calls an LLM, saves or publishes.
export function creatorReview(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)
      || Object.keys(input).some(key => !['metadata','reference','idea','hook','thumbnail','funnel'].includes(key))
      || !input.metadata) throw new SkillError(422, 'Provide metadata and only supported review fields.');
  const metadataResult = metadataPreflight(input.metadata);
  const steps = [
    {skill:'metadata_preflight', result:metadataResult},
    {skill:'title_lint', result:titleReview({title:input.metadata.title, thumbnail:input.thumbnail ?? ''})},
  ];
  if (input.reference !== undefined) steps.push({skill:'youtube_url_parser', result:youtubeReference({reference:input.reference})});
  if (input.idea !== undefined) steps.push({skill:'idea_heuristic', result:ideaReview({idea:input.idea})});
  if (input.hook !== undefined) steps.push({skill:'hook_heuristic', result:hookReview({hook:input.hook})});
  if (input.funnel !== undefined) steps.push({skill:'funnel_heuristic', result:funnelReview(input.funnel)});
  return {status:metadataResult.valid ? 'review_ready' : 'metadata_needs_changes', steps,
    notice:'Read-only checks of supplied text and numbers. No competitor or channel was fetched, no prediction or publishing approval was made, and nothing was saved or uploaded.'};
}

// Exact server-owned allowlist: registry descriptions never grant permissions
// and cannot cause arbitrary repository code, commands or URLs to be executed.
export function runHostedSkill(id, input) {
  switch (id) {
    case 'metadata_preflight': return metadataPreflight(input);
    case 'youtube_url_parser': return youtubeReference(input);
    case 'funnel_heuristic': return funnelReview(input);
    case 'idea_heuristic': return ideaReview(input);
    case 'hook_heuristic': return hookReview(input);
    case 'title_lint': return titleReview(input);
    case 'creator_review': return creatorReview(input);
    default: throw new SkillError(404, 'That skill is not available in the hosted app.');
  }
}
