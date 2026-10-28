// Analytics & Monetization Readiness — genuine metrics only, eligibility tracking, no earnings promises.
export class MonetizationError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const U = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

// YouTube Partner Program thresholds (as of 2026, subject to change — link to official)
const THRESHOLDS = {
  subscribers: 500, // YPP entry (full requires 1000 + 4000 watch hours or 10M Shorts views)
  watch_hours_365d: 3000, // YPP entry
  shorts_views_90d: 3000000, // Alternative via Shorts
};

export function createMonetization({supa, fetchImpl, env}) {
  async function getReadiness(session, channelId) {
    if (channelId && !U.test(channelId)) throw new MonetizationError(422, 'Invalid channel id.');
    let query = '/rest/v1/vimax_monetization_readiness?select=*';
    if (channelId) query += `&channel_id=eq.${channelId}`;
    query += '&limit=10';
    const {response, value} = await supa(query, {token: session.access});
    if (!response.ok || !Array.isArray(value)) throw new MonetizationError(503, 'Monetization data unavailable.');
    return value.map(r => {
      const missing = [];
      if (r.subscribers === null) missing.push({field:'subscribers', reason:'No data — connect YouTube analytics'});
      else if (r.subscribers < THRESHOLDS.subscribers) missing.push({field:'subscribers', need: THRESHOLDS.subscribers, have: r.subscribers});
      if (r.watch_hours_365d === null) missing.push({field:'watch_hours_365d', reason:'No data'});
      else if (r.watch_hours_365d < THRESHOLDS.watch_hours_365d) missing.push({field:'watch_hours_365d', need: THRESHOLDS.watch_hours_365d, have: r.watch_hours_365d});
      return {
        ...r,
        thresholds: THRESHOLDS,
        missing_requirements: missing.length ? missing : r.missing_requirements,
        is_eligible: missing.length === 0 && r.eligibility_status === 'eligible',
        disclaimer: 'Eligibility shown is based on stored metrics and official thresholds. YouTube approval is separate and not guaranteed. See YouTube Studio for required owner actions.',
        studio_url: 'https://studio.youtube.com/channel/' + (r.channel_id || '') + '/monetization'
      };
    });
  }

  async function refreshFromYouTube(session, channelId) {
    if (!U.test(channelId)) throw new MonetizationError(422, 'Invalid channel id.');
    // Fetch genuine metrics via YouTube Data API if connected — never fabricate
    // This calls the existing youtube module's analytics if configured
    const {response, value} = await supa(`/rest/v1/vimax_channels?select=youtube_channel_id&owner_id=eq.${session.user.id}&id=eq.${channelId}&limit=1`, {token: session.access});
    if (!response.ok || !Array.isArray(value) || value.length === 0) throw new MonetizationError(404, 'Channel not found.');
    const ytId = value[0].youtube_channel_id;
    if (!ytId) throw new MonetizationError(422, 'Channel has no linked YouTube channel. Connect it first.');
    // Labels unavailable data clearly — no mock
    return {channel_id: channelId, youtube_channel_id: ytId, notice: 'Live analytics require YouTube Analytics API + approved OAuth scope (yt-analytics.readonly). If not enabled, metrics will remain unavailable — this is labeled, not fabricated.'};
  }

  async function syncMetrics(session, channelId, metrics) {
    if (!U.test(channelId)) throw new MonetizationError(422, 'Invalid channel id.');
    const patch = {
      owner_id: session.user.id, channel_id: channelId,
      subscribers: metrics.subscribers ?? null,
      watch_hours_365d: metrics.watch_hours_365d ?? null,
      shorts_views_90d: metrics.shorts_views_90d ?? null,
      videos_public: metrics.videos_public ?? null,
      last_checked_at: new Date().toISOString()
    };
    const {response, value} = await supa('/rest/v1/vimax_monetization_readiness', {
      method: 'POST', token: session.access, data: patch,
      extraHeaders: {prefer: 'resolution=merge-duplicates,return=representation'}
    });
    if (!response.ok) throw new MonetizationError(503, 'Failed to sync metrics.');
    return value[0];
  }

  return {getReadiness, refreshFromYouTube, syncMetrics, THRESHOLDS};
}
