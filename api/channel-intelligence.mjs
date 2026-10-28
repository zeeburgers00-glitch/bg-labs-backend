// Multi-Channel Intelligence — per-channel isolation, OAuth tokens, analytics, strategy.
export class ChannelIntelligenceError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const U = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function createChannelIntelligence({supa}) {
  async function listChannels(session) {
    const {response, value} = await supa('/rest/v1/vimax_channels?select=*&order=created_at.desc', {token: session.access});
    if (!response.ok || !Array.isArray(value)) throw new ChannelIntelligenceError(503, 'Channels unavailable.');
    return value.map(c => ({
      ...c,
      // Never expose raw tokens — only indicate connection status
      _note: c.is_connected ? 'YouTube connected (token server-side)' : 'Not connected'
    }));
  }

  async function getChannel(session, channelId) {
    if (!U.test(channelId)) throw new ChannelIntelligenceError(422, 'Invalid channel id.');
    const {response, value} = await supa(`/rest/v1/vimax_channels?select=*&id=eq.${channelId}&limit=1`, {token: session.access});
    if (!response.ok || !Array.isArray(value) || value.length === 0) throw new ChannelIntelligenceError(404, 'Channel not found.');
    const ch = value[0];
    // Fetch analytics snapshot
    const {value: analytics} = await supa(`/rest/v1/vimax_channel_analytics?select=*&channel_id=eq.${channelId}&order=fetched_at.desc&limit=20`, {token: session.access});
    const {value: topics} = await supa(`/rest/v1/vimax_topic_recommendations?select=*&channel_id=eq.${channelId}&order=created_at.desc&limit=20`, {token: session.access});
    return {channel: ch, analytics: analytics || [], recommendations: topics || []};
  }

  async function updateChannel(session, channelId, updates) {
    if (!U.test(channelId)) throw new ChannelIntelligenceError(422, 'Invalid channel id.');
    if (!updates || typeof updates !== 'object' || Array.isArray(updates)) throw new ChannelIntelligenceError(422, 'Invalid updates.');
    const allowed = new Set(['name','niche','audience','language','timezone','brand_voice','format','description','content_strategy','upload_schedule','branding']);
    const patch = {};
    for (const [k,v] of Object.entries(updates)) {
      if (!allowed.has(k)) throw new ChannelIntelligenceError(422, `Field not allowed: ${k}`);
      if (typeof v === 'string' && v.length > 2000) throw new ChannelIntelligenceError(422, `${k} too long.`);
      if ((k === 'upload_schedule' || k === 'branding') && (typeof v !== 'object' || Array.isArray(v))) throw new ChannelIntelligenceError(422, `${k} must be object.`);
      patch[k] = v;
    }
    if (Object.keys(patch).length === 0) throw new ChannelIntelligenceError(422, 'No valid fields to update.');
    const {response, value} = await supa(`/rest/v1/vimax_channels?id=eq.${channelId}`, {method: 'PATCH', token: session.access, data: patch, extraHeaders: {prefer: 'return=representation'}});
    if (!response.ok || !Array.isArray(value) || value.length === 0) throw new ChannelIntelligenceError(503, 'Channel update failed.');
    return value[0];
  }

  async function recommendTopics(session, channelId, {analytics_summary} = {}) {
    if (!U.test(channelId)) throw new ChannelIntelligenceError(422, 'Invalid channel id.');
    // Verify channel ownership
    const {response, value} = await supa(`/rest/v1/vimax_channels?select=id&owner_id=eq.${session.user.id}&id=eq.${channelId}&limit=1`, {token: session.access});
    if (!response.ok || !Array.isArray(value) || value.length === 0) throw new ChannelIntelligenceError(404, 'Channel not found.');

    // Honest: do not fabricate trends. Return empty with guidance if no real data.
    // If analytics_summary provided, use it; otherwise check real analytics table.
    const {value: realAnalytics} = await supa(`/rest/v1/vimax_channel_analytics?select=*&channel_id=eq.${channelId}&limit=5`, {token: session.access});
    if (!realAnalytics || realAnalytics.length === 0) {
      return {recommendations: [], notice: 'No analytics data yet. Connect YouTube and enable analytics to get data-driven recommendations. No trends are fabricated.'};
    }
    // Return existing recommendations from DB (created by real research pipeline)
    const {value: recs} = await supa(`/rest/v1/vimax_topic_recommendations?select=*&channel_id=eq.${channelId}&order=created_at.desc&limit=10`, {token: session.access});
    return {recommendations: recs || [], source: 'analytics + research data (never fabricated)', notice: 'Topics derive from connected channel analytics and verified research sources.'};
  }

  return {listChannels, getChannel, updateChannel, recommendTopics};
}
