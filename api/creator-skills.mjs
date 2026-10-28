// Bounded, no-network hosted adaptations of reviewed MIT-licensed creator
// heuristics already used by the local ViMax companion. Original Python source
// and notices are retained under skills/vendor; see vendor/README.md.
import formulas from '../skills/vendor/youtube-agent-skill/yt-script/hooks.json' with {type:'json'};
import {SkillError} from './skill-error.mjs';

const NOTICE = 'English-language text heuristic only; not research, analytics, or a prediction of views.';
const URL_NOTICE = 'Parsed locally; this does not fetch the URL or verify a channel, owner, or video.';
const FUNNEL_NOTICE = 'Heuristic suggestions based only on supplied metrics; no YouTube data was fetched. Thresholds are not a causal diagnosis, forecast, or guarantee.';

function object(value, keys, message) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !keys.includes(key))) {
    throw new SkillError(422, message);
  }
}
function text(value, label, {required = true, max = 400} = {}) {
  if (typeof value !== 'string') throw new SkillError(422, `${label} must be text.`);
  const clean = value.trim();
  if (required && !clean) throw new SkillError(422, `${label} is required.`);
  if (Array.from(clean).length > max || /\u0000/.test(clean)) throw new SkillError(422, `${label} is too long or contains invalid characters.`);
  return clean;
}
const count = (s, regex) => [...s.matchAll(regex)].length;
const cap = n => Math.max(0, Math.min(100, n));
const firstIsUpper = s => {
  const c = Array.from(s)[0] || '';
  return c.toLowerCase() !== c.toUpperCase() && c === c.toUpperCase();
};
const words = (s, pattern = /[a-z0-9'$%]+/g) => s.toLowerCase().match(pattern) || [];
// Python's round uses ties-to-even. Inputs are finite and nonnegative here.
function evenRound(n, places = 0) {
  const factor = 10 ** places, scaled = n * factor, floor = Math.floor(scaled), fraction = scaled - floor;
  return (fraction === 0.5 ? (floor % 2 === 0 ? floor : floor + 1) : Math.round(scaled)) / factor;
}

// Derived from sergebulaev/youtube-skills lib/url_parser.py (MIT), but validates
// raw authority and complete path/ID *before* parsing. Never requests the URL.
export function youtubeReference(input) {
  object(input, ['reference'], 'Provide one reference string.');
  if (Object.keys(input).length !== 1 || typeof input.reference !== 'string') throw new SkillError(422, 'Provide one reference string.');
  const reference = input.reference;
  if (!reference || reference.length > 2048 || reference !== reference.trim() || /[\u0000-\u0020\u007f]/.test(reference)) {
    throw new SkillError(422, 'Provide a valid YouTube URL or 11-character video ID.');
  }
  const video = /^[A-Za-z0-9_-]{11}$/, channel = /^UC[A-Za-z0-9_-]{22}$/;
  let canonical, kind, id = null, handle = null, channelId = null;
  if (video.test(reference)) { id = reference; kind = 'video'; canonical = `https://www.youtube.com/watch?v=${id}`; }
  else {
    const parts = /^https:\/\/([^/?#]+)([^?#]*)(?:\?([^#]*))?(?:#.*)?$/.exec(reference);
    if (!parts) throw new SkillError(422, 'Invalid or unsupported YouTube reference.');
    const host = parts[1].toLowerCase(), path = parts[2], query = parts[3] || '';
    const allowed = new Set(['youtube.com','www.youtube.com','m.youtube.com','youtu.be','www.youtu.be']);
    if (!allowed.has(host) || /[%\\]/.test(path) || path.includes('//') || (query && query.split('&').length > 30)) {
      throw new SkillError(422, 'Invalid or unsupported YouTube reference.');
    }
    const segments = path.replace(/\/+$/, '').split('/').slice(1);
    const shortHost = host === 'youtu.be' || host === 'www.youtu.be';
    const cleanPath = path.replace(/\/+$/, '');
    if (shortHost && segments.length === 1 && video.test(segments[0])) {
      id = segments[0]; kind = 'video'; canonical = `https://www.youtube.com/watch?v=${id}`;
    } else if (!shortHost && cleanPath === '/watch') {
      const matches = new URLSearchParams(query).getAll('v');
      if (matches.length !== 1 || !video.test(matches[0])) throw new SkillError(422, 'Watch URL must contain exactly one complete video ID.');
      id = matches[0]; kind = 'video'; canonical = `https://www.youtube.com/watch?v=${id}`;
    } else if (!shortHost && segments.length === 2 && ['shorts','embed','live','v'].includes(segments[0]) && video.test(segments[1])) {
      id = segments[1]; kind = segments[0] === 'shorts' ? 'shorts' : 'video'; canonical = `https://www.youtube.com/watch?v=${id}`;
    } else if (!shortHost && segments.length === 1 && /^@[A-Za-z0-9_.-]{3,30}$/.test(segments[0])) {
      handle = segments[0].slice(1); kind = 'handle'; canonical = `https://www.youtube.com/${segments[0]}`;
    } else if (!shortHost && segments.length === 2 && segments[0] === 'channel' && channel.test(segments[1])) {
      channelId = segments[1]; kind = 'channel'; canonical = `https://www.youtube.com/channel/${channelId}`;
    } else if (!shortHost && segments.length === 2 && ['c','user'].includes(segments[0]) && /^[A-Za-z0-9_-]{1,100}$/.test(segments[1])) {
      handle = segments[1]; kind = segments[0]; canonical = `https://www.youtube.com/${kind}/${handle}`;
    } else throw new SkillError(422, 'Invalid or unsupported YouTube reference.');
  }
  return {video_id:id, handle, channel_id:channelId, is_short:kind === 'shorts', url_type:id ? 'video' : 'channel',
    canonical_url:canonical, reference_kind:kind, notice:URL_NOTICE};
}

// Derived from youtube-agent-pro/yt-analytics/funnel.py (MIT). Manually supplied
// figures only; Shorts never use long-form CTR or impression-derived views.
export function funnelReview(input) {
  object(input, ['format','metrics'], 'Provide format and a metrics object.');
  const form = input.format === undefined ? 'long' : input.format, metrics = input.metrics;
  if (!['long','shorts'].includes(form)) throw new SkillError(422, 'Invalid video format.');
  object(metrics, ['impressions','views','ctr','avd_seconds','length_seconds'], 'Provide supported numeric metrics.');
  if (!Object.keys(metrics).length) throw new SkillError(422, 'Provide one or more supported numeric metrics.');
  for (const [name, value] of Object.entries(metrics)) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1_000_000_000_000) throw new SkillError(422, `Invalid metric: ${name}.`);
    if (['impressions','views'].includes(name) && !Number.isSafeInteger(value)) throw new SkillError(422, `${name} must be a whole number.`);
    if (name === 'ctr' && value > 100) throw new SkillError(422, 'CTR must be between 0 and 100 percent.');
    if (['avd_seconds','length_seconds'].includes(name) && value > 86400) throw new SkillError(422, `${name} exceeds the supported duration.`);
    if (name === 'length_seconds' && value < 0.001) throw new SkillError(422, 'Video length must be at least 0.001 seconds.');
  }
  const impr = form === 'long' ? (metrics.impressions ?? null) : null, ctr = form === 'long' ? (metrics.ctr ?? null) : null;
  const avd = metrics.avd_seconds ?? null, length = metrics.length_seconds ?? null, views = metrics.views ?? null;
  const pct = avd !== null && length !== null ? avd / length * 100 : null;
  const estimate = impr !== null && ctr !== null ? evenRound(impr * ctr / 100) : null;
  const warnings = ['Heuristic review priorities, not a causal diagnosis or a forecast.'];
  if (estimate !== null) warnings.push('Impressions × CTR estimates only views from counted impressions, not total video views.');
  const result = {format:form, impressions:impr, ctr, avd_s:avd, length_s:length, avg_pct_viewed:pct === null ? null : evenRound(pct, 1),
    views, views_est:views ?? estimate, estimated_views_from_impressions:estimate, warnings,
    missing_metrics:[['impressions',impr],['ctr',ctr],['avd',avd],['length',length]].filter(([,v]) => v === null).map(([name]) => name)};
  if (form === 'shorts') {
    if (Object.hasOwn(metrics, 'impressions') || Object.hasOwn(metrics, 'ctr')) warnings.push('Impressions and CTR were ignored for Shorts; they do not describe the Shorts-feed funnel.');
    return {...result, missing_metrics:[['avd',avd],['length',length]].filter(([,v]) => v === null).map(([name]) => name),
      context_required:['engaged_views','stayed_to_watch','shorts_feed_distribution','traffic_sources'], links:[], binding_constraint:null,
      status:'shorts_requires_context', verdict:'Long-form CTR and retention bands are not applied to Shorts. Compare engaged views, stayed-to-watch, retention and traffic sources with similar Shorts.', notice:FUNNEL_NOTICE};
  }
  const links = [];
  if (impr !== null) links.push({name:'IMPRESSIONS',ok:impr >= 1000,severity:1 - Math.min(1,impr/1000),
    note:`${impr.toLocaleString('en-US', {maximumFractionDigits:0})} counted impressions: compare video age and traffic sources before judging reach.`});
  if (ctr !== null) links.push({name:'CTR',ok:ctr >= 4,severity:Math.max(0, Math.min(1, (4-ctr)/4)),
    note:`${ctr.toFixed(1)}% CTR: compare like-for-like traffic sources; review the title and thumbnail with yt-package and yt-thumbnail.`});
  if (pct !== null) links.push({name:'RETENTION',ok:pct >= 50,severity:Math.max(0, Math.min(1, (50-pct)/50)),
    note:`${pct.toFixed(1)}% average viewed: compare similar video lengths and inspect the retention curve with yt-retention.`});
  const broken = links.filter(item => !item.ok).sort((a,b) => b.severity - a.severity);
  let status, verdict, binding = null;
  if (!links.length) { status = 'insufficient_data'; verdict = 'No usable funnel metrics supplied; no performance conclusion is possible.'; }
  else if (broken.length) { status = 'review'; binding = broken[0].name; verdict = broken[0].note; }
  else { status = result.missing_metrics.length ? 'partial_data' : 'within_heuristic_bands'; verdict = 'Available metrics are within the illustrative bands; this does not prove the video is performing well.'; }
  return {...result, links:links.map(({name,ok,note}) => ({name,ok,note})), binding_constraint:binding, status, verdict, notice:FUNNEL_NOTICE};
}

// Derived from youtube-agent-pro/yt-idea/ideascore.py (MIT).
export function ideaReview(input) {
  object(input, ['idea'], 'Provide an idea.');
  const idea = text(input.idea, 'Idea');
  const question = /\b(how|why|what|which|when|where|should|can|is|are|do|does|will)\b/i.test(idea);
  const intent = count(idea, /\b(guide|tutorial|review|vs|versus|best|fix|stop|avoid|build|make|setup|explained|mistakes|beginners?|without|using|in \d+)\b/gi);
  const search = cap(20 + (question ? 26 : 0) + Math.min(30,15*intent) - (/\b(how|why|what|guide|review|vs|fix|build|make|stop)\b/i.test(idea) ? 0 : 12));
  const vague = new Set(['amazing','incredible','insane','crazy','huge','massive','ultimate','best','powerful','secret','revolutionary','epic','perfect','everything','stuff','things','content']);
  const nums = count(idea, /\b(\d[\d,.]*\s?(%|k|m|x|hrs?|hours?|mins?|minutes?|days?|weeks?|months?|years?|dollars?|\$)?)\b/gi);
  const toks = words(idea), proper = idea.split(/\s+/u).slice(1).filter(x => firstIsUpper(x) && Array.from(x).length > 2).length;
  const specific = toks.length ? cap(32 + nums * 20 + proper * 8 - toks.filter(x => vague.has(x)).length * 18) : 0;
  const reach = cap(55 - (/\bfor (everyone|anyone|all|people)\b/i.test(idea) ? 30 : 0)
    - (/\bfor (react|vue|rust|haskell|niche|enterprise|senior|advanced)\b/i.test(idea) ? 10 : 0) + (/\bfor \w+/i.test(idea) ? 15 : 0));
  const ever = count(idea, /\b(how to|guide|explained|beginners?|basics|fundamentals|101|complete|ever|always|principles?|mistakes)\b/gi);
  const timely = count(idea, /\b(202\d|today|this week|this month|right now|new|latest|just|update|breaking|announced|released|beta|v\d)\b/gi);
  const durable = cap(50 + ever * 16 - timely * 20), axes = {SEARCH:search,SPECIFIC:specific,REACH:reach,DURABLE:durable};
  const vals = Object.values(axes), score = evenRound(0.6 * vals.reduce((a,b)=>a+b,0) / vals.length + 0.4 * Math.min(...vals));
  return {idea,axes,score,band:score>=70?'STRONG':score>=52?'WORKABLE':'WEAK',life:durable<45?'timely':durable>62?'evergreen':'mixed',notice:NOTICE};
}

// Derived from youtube-agent-skill/yt-script/hookscore.py and hooks.json (MIT).
const HOOKS = formulas.hooks.map(item => ({name:item.name, match:item.match.map(pattern => new RegExp(pattern, 'i'))}));
export function hookReview(input) {
  object(input, ['hook'], 'Provide a hook.');
  const hook = text(input.hook, 'Hook');
  const tokens = words(hook, /[a-z0-9'%$.]+/g);
  const filler = new Set(['basically','actually','literally','just','really','very','so','kind','sort','like','guys','hey','welcome','today','video','subscribe','channel']);
  const vague = new Set(['amazing','incredible','insane','crazy','huge','massive','game','changer','secret','powerful','ultimate','best','revolutionary','mind','blowing','unbelievable']);
  const concrete = /\b(\d[\d,.]*\s?(%|k|m|x|s|m|h)?|\$\d|\d+\s?(second|minute|hour|day|week|month|year)s?)\b/gi;
  const num = count(hook, concrete), capitals = hook.split(/\s+/u).slice(1).filter(firstIsUpper).length;
  const specificity = tokens.length ? cap(34 + num*22 - tokens.filter(x=>vague.has(x)).length*16 - tokens.filter(x=>filler.has(x)).length*5 + Math.min(18,capitals*6)) : 0;
  const you = /\b(you|your|you're|youre|yourself)\b/gi;
  const address = cap(26 + count(hook,you)*20 + (/\b(you|your|you're|youre|yourself)\b/i.test(hook.split(/\s+/u).slice(0,6).join(' ')) ? 30 : 0));
  const stakes = cap(22 + count(hook,/\b(lose|lost|wasting|waste|quit|fail|broke|cost|risk|before|stop|never|die|dying|dead)\b/gi)*26 + (num ? 14 : 0));
  const curiosity = cap(24 + count(hook,/\b(why|how|what|which|until|before|but|nobody|almost|except|reason|actually)\b/gi)*17
    + (hook.endsWith('?') ? 18 : 0) - (/\b(because|so that|which means)\b/i.test(hook) ? 18 : 0));
  const n = tokens.length, brevity = !n ? 0 : n>=9 && n<=24 ? 100 : n<9 ? Math.max(30,100-(9-n)*11) : Math.max(10,100-(n-24)*7);
  const properties = {SPECIFICITY:specificity,ADDRESS:address,STAKES:stakes,CURIOSITY:curiosity,BREVITY:brevity};
  const vals = Object.values(properties), score = evenRound(0.6 * vals.reduce((a,b)=>a+b,0)/vals.length + 0.4*Math.min(...vals));
  let formula = 'Unclassified', hits = 0;
  for (const item of HOOKS) { const found = item.match.filter(re => re.test(hook)).length; if (found > hits) { formula=item.name; hits=found; } }
  return {hook,properties,score,band:score>=72?'STRONG':score>=55?'WORKABLE':'WEAK',formula,notice:NOTICE};
}

// Derived from youtube-agent-skill/yt-package/title.py (MIT).
export function titleReview(input) {
  object(input, ['title','thumbnail'], 'Provide a title and optional thumbnail text.');
  const title = text(input.title, 'Title'), thumbnail = text(input.thumbnail === undefined ? '' : input.thumbnail, 'Thumbnail text', {required:false});
  const chars = Array.from(title).length, issues = [], good = [];
  if (chars > 100) issues.push(['length', `${chars} characters - YouTube's hard limit is 100`]);
  else if (chars > 60) issues.push(['length', `${chars} characters - desktop search cuts near 60`]);
  else good.push(`${chars} characters, inside the 60-character desktop cut`);
  if (chars > 40) { const start = Array.from(title).slice(0,40).join(''), index = start.lastIndexOf(' '), head = index === -1 ? start : start.slice(0,index);
    issues.push(['mobile', `a mobile feed shows about "${head}..." - check the subject survives`]); }
  const caps = title.split(/\s+/u).filter(w => { const letters=Array.from(w).filter(c=>c.toLowerCase()!==c.toUpperCase()); return Array.from(w).length>2 && letters.length && letters.every(c=>c===c.toUpperCase()); });
  if (caps.length > 2) issues.push(['shouting', `${caps.length} all-caps words - two is the ceiling before it reads as spam`]);
  else if (caps.length) good.push(`${caps.length} all-caps word for emphasis`);
  const pattern = /[a-z0-9']+/g, vague = new Set(['amazing','incredible','insane','crazy','huge','massive','ultimate','best','powerful','secret','revolutionary','mindblowing','epic','perfect','complete','everything']);
  const stop = new Set(['the','a','an','of','for','to','in','on','and','or','is','are','with','your','you','my','i','this','that','it','how','what','why']);
  const titleWords = words(title, pattern), vagues = [...new Set(titleWords.filter(x=>vague.has(x)))].sort();
  if (vagues.length) issues.push(['vague', `${vagues.join(', ')} - swap for a number, a name or a date`]);
  const nums = title.match(/\d[\d,.]*%?/g) || [];
  if (nums.length) good.push(`carries a concrete figure (${nums.slice(0,3).join(', ')})`);
  else issues.push(['no-number','no number, date or name - the most reliable single fix']);
  if (title.endsWith('?')) good.push('open question in the title');
  if (!titleWords.slice(0,3).some(w=>!stop.has(w))) issues.push(['front-load','the first three words are all filler - move the subject forward']);
  if (thumbnail) {
    const thumbWords=words(thumbnail,pattern), tw=new Set(titleWords.filter(x=>!stop.has(x))), shared=[...new Set(thumbWords.filter(x=>!stop.has(x) && tw.has(x)))].sort();
    if (shared.length) issues.push(['duplicate', `thumbnail repeats the title on ${shared.join(', ')} - the thumbnail should say what the title does not`]);
    else good.push('thumbnail and title carry different words');
    if (thumbWords.length > 4) issues.push(['thumb-length', `${thumbWords.length} words on the thumbnail - three is the ceiling at feed size`]);
  }
  return {title, chars, score:cap(100-14*issues.length+4*good.length), issues, good, notice:NOTICE};
}
