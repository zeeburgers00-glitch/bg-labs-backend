// Optional official YouTube Data API public-channel sampling. This does not use
// an account's channel grant, download media, fetch transcripts or infer visual
// templates. The sole outbound host and requested resources are fixed.
import {youtubeReference} from './creator-skills.mjs';
import {SkillError} from './skill-error.mjs';

const HOST = 'https://www.googleapis.com/youtube/v3/';
const MAX_BYTES = 256 * 1024, MAX_VIDEOS = 10;
const CHANNEL = /^UC[A-Za-z0-9_-]{22}$/, VIDEO = /^[A-Za-z0-9_-]{11}$/, PLAYLIST = /^[A-Za-z0-9_-]{1,128}$/;
const clean = (value, max) => typeof value === 'string' ? Array.from(value.replace(/[\u0000-\u001f\u007f]/g, ' ')).slice(0,max).join('').trim() : '';
const safeDate = value => typeof value === 'string' && value.length <= 40 && Number.isFinite(Date.parse(value)) ? new Date(value).toISOString() : null;
function safeCount(value) {
  if (typeof value !== 'string' || !/^\d{1,13}$/.test(value)) return null;
  const number = Number(value); return Number.isSafeInteger(number) && number <= 1_000_000_000_000 ? number : null;
}
export function youtubePublicStatus(env) {
  if (env.VIMAX_YOUTUBE_PUBLIC_RESEARCH_ENABLED !== 'true') return 'disabled';
  const key = env.YOUTUBE_PUBLIC_DATA_API_KEY || '';
  return !key ? 'not_configured' : /^[\x21-\x7e]{1,2048}$/.test(key) ? 'configured_unverified' : 'invalid_configuration';
}
export function youtubeResearchInput(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)
      || Object.keys(input).some(key => !['reference','confirm_quota'].includes(key))
      || input.confirm_quota !== true) throw new SkillError(422, 'Confirm the public lookup and its Google API quota before continuing.');
  const parsed = youtubeReference({reference:input.reference});
  if (!['handle','channel'].includes(parsed.reference_kind)) throw new SkillError(422, 'Enter a YouTube channel handle or channel ID URL.');
  return parsed;
}
async function apiJson(fetchImpl, key, path, params) {
  const url = new URL(path, HOST);
  for (const [k,v] of Object.entries(params)) url.searchParams.set(k,v);
  let response;
  try {
    response = await fetchImpl(url, {method:'GET',headers:{accept:'application/json','x-goog-api-key':key},
      signal:AbortSignal.timeout(12_000),redirect:'error',cache:'no-store'});
  } catch { throw new SkillError(503, 'YouTube public metadata could not be reached. No automatic retry was sent.'); }
  if (!response.ok) {
    try { await response.body?.cancel(); } catch { /* never expose provider error bodies */ }
    throw new SkillError(response.status === 429 ? 429 : 503, 'YouTube rejected the public metadata request or quota. Check the API key, permissions and quota privately.');
  }
  const declared = response.headers.get('content-length');
  if (declared && Number(declared) > MAX_BYTES) throw new SkillError(502, 'The YouTube response exceeded the size limit.');
  const reader = response.body?.getReader();
  if (!reader) throw new SkillError(502, 'YouTube returned an empty response.');
  let size = 0; const chunks = [];
  try {
    while (true) {
      const {done,value} = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > MAX_BYTES) { await reader.cancel(); throw new SkillError(502, 'The YouTube response exceeded the size limit.'); }
      chunks.push(value);
    }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk,offset); offset += chunk.byteLength; }
    const parsed = JSON.parse(new TextDecoder().decode(bytes));
    if (!parsed || typeof parsed !== 'object' || !Array.isArray(parsed.items)) throw new Error('Invalid response.');
    return parsed;
  } catch (error) {
    if (error instanceof SkillError) throw error;
    throw new SkillError(502, 'YouTube returned invalid public metadata.');
  }
}

export async function samplePublicChannel({env,fetchImpl,input}) {
  const reference = youtubeResearchInput(input);
  if (youtubePublicStatus(env) !== 'configured_unverified') throw new SkillError(503, 'Public YouTube research is not enabled and configured on this deployment.');
  const key = env.YOUTUBE_PUBLIC_DATA_API_KEY;
  const criteria = reference.reference_kind === 'handle' ? {forHandle:`@${reference.handle}`} : {id:reference.channel_id};
  const channelResult = await apiJson(fetchImpl,key,'channels',{part:'snippet,contentDetails,statistics',...criteria,maxResults:'1'});
  if (channelResult.items.length === 0) throw new SkillError(404, 'No public channel matched that reference.');
  if (channelResult.items.length !== 1) throw new SkillError(502, 'YouTube returned an unexpected channel result.');
  const item = channelResult.items[0], channelId = item?.id, uploadPlaylist = item?.contentDetails?.relatedPlaylists?.uploads;
  if (!CHANNEL.test(channelId || '') || !PLAYLIST.test(uploadPlaylist || '')
      || (reference.channel_id && reference.channel_id !== channelId)) throw new SkillError(502, 'YouTube returned an invalid channel identity.');
  const channel = {id:channelId, title:clean(item.snippet?.title,150), description:clean(item.snippet?.description,2000),
    url:`https://www.youtube.com/channel/${channelId}`, published_at:safeDate(item.snippet?.publishedAt),
    subscribers:item.statistics?.hiddenSubscriberCount === true ? null : safeCount(item.statistics?.subscriberCount),
    total_views:safeCount(item.statistics?.viewCount), video_count:safeCount(item.statistics?.videoCount)};
  if (!channel.title) throw new SkillError(502, 'YouTube returned a channel without a title.');
  const playlist = await apiJson(fetchImpl,key,'playlistItems',{part:'contentDetails',playlistId:uploadPlaylist,maxResults:String(MAX_VIDEOS)});
  if (playlist.items.length > MAX_VIDEOS) throw new SkillError(502, 'YouTube returned too many playlist items.');
  const ids = [...new Set(playlist.items.map(x => x?.contentDetails?.videoId).filter(x => VIDEO.test(x || '')))];
  let videos = [];
  if (ids.length) {
    const details = await apiJson(fetchImpl,key,'videos',{part:'snippet,contentDetails,statistics,status',id:ids.join(',')});
    if (details.items.length > MAX_VIDEOS) throw new SkillError(502, 'YouTube returned too many video records.');
    const allowed = new Set(ids), seen = new Set();
    for (const v of details.items) {
      if (!VIDEO.test(v?.id || '') || !allowed.has(v.id) || seen.has(v.id)
          || v.snippet?.channelId !== channelId || v.status?.privacyStatus !== 'public') continue;
      seen.add(v.id);
      const duration = typeof v.contentDetails?.duration === 'string' && /^P(?:(?:\d{1,4})D)?(?:T(?:(?:\d{1,4})H)?(?:(?:\d{1,4})M)?(?:(?:\d{1,4})S)?)?$/.test(v.contentDetails.duration) ? v.contentDetails.duration : null;
      videos.push({id:v.id, title:clean(v.snippet?.title,200), url:`https://www.youtube.com/watch?v=${v.id}`,
        published_at:safeDate(v.snippet?.publishedAt), duration_iso:duration,
        views:safeCount(v.statistics?.viewCount), likes:safeCount(v.statistics?.likeCount), comments:safeCount(v.statistics?.commentCount)});
    }
    // Keep the public uploads-playlist order, not the provider's detail ordering.
    videos.sort((a,b) => ids.indexOf(a.id) - ids.indexOf(b.id));
  }
  return {channel, videos, sample_requested:MAX_VIDEOS, missing_videos:Math.max(0,playlist.items.length-videos.length), sampled_at:new Date().toISOString(),
    notice:'Public metadata sample only, up to 10 recent uploads. Counts may be rounded or unavailable. No media, script, audio, visual template, private Analytics, ownership or future performance was verified. Nothing was saved or published.'};
}
