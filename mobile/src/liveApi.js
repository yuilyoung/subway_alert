// Seoul/Firebase credentials remain on the server. Only a private tester key is sent.
const { validateServerUrl, requestJson } = require('./apiAccess');
const MAX_ROWS = 5000;
function normalizeResponse(payload) {
  if (
    !payload ||
    !['SAMPLE', 'LIVE'].includes(payload.mode) ||
    !Array.isArray(payload.trains) ||
    payload.trains.length > MAX_ROWS ||
    (payload.warning != null && typeof payload.warning !== 'string')
  )
    throw new Error('서버 응답 형식이 올바르지 않습니다.');
  const trains = payload.trains.map((row) => {
    if (
      !row ||
      !['lineId', 'station', 'trainId', 'direction', 'state'].every(
        (k) => typeof row[k] === 'string' && row[k].length > 0 && row[k].length <= 100,
      ) ||
      !(row.observedAt == null || typeof row.observedAt === 'string') ||
      !(row.express == null || typeof row.express === 'boolean')
    )
      throw new Error('서버 응답 형식이 올바르지 않습니다.');
    return {
      lineId: row.lineId,
      station: row.station,
      trainId: row.trainId,
      direction: row.direction,
      state: row.state,
      observedAt: row.observedAt || null,
      express: row.express ?? null,
    };
  });
  return { mode: payload.mode, warning: payload.warning || '', trains };
}
function observationStatus(value, now = Date.now()) {
  if (!value || !/(Z|[+-]\d\d:\d\d)$/.test(value)) return 'unknown';
  const stamp = Date.parse(value);
  if (!Number.isFinite(stamp) || stamp > now + 5000) return 'unknown';
  return now - stamp <= 60000 ? 'fresh' : 'stale';
}
function filterTrains(trains, query) {
  const needle = String(query).trim();
  return trains.filter((t) => t.trainId.includes(needle) || t.station.includes(needle));
}
async function fetchTrains(serverUrl, development = false, fetchImpl, accessToken) {
  return normalizeResponse(
    await requestJson(
      serverUrl,
      '/api/live/trains?line=2',
      {},
      accessToken,
      development,
      fetchImpl,
    ),
  );
}
module.exports = {
  validateServerUrl,
  normalizeResponse,
  observationStatus,
  filterTrains,
  fetchTrains,
};
