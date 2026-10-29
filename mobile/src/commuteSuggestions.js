const { normalizeSchedule, scheduleOccurrence } = require('./commute');
const { findRoute, distanceMeters } = require('./domain');
const { suggestionKey } = require('./storage');

function localDay(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
function freshPoint(point, date) {
  const time = date.getTime();
  return (
    Number.isFinite(time) &&
    point &&
    Number.isFinite(point.latitude) &&
    Math.abs(point.latitude) <= 90 &&
    Number.isFinite(point.longitude) &&
    Math.abs(point.longitude) <= 180 &&
    Number.isFinite(point.accuracy) &&
    point.accuracy >= 0 &&
    point.accuracy <= 80 &&
    Number.isFinite(point.timestamp) &&
    point.timestamp <= time + 5000 &&
    time - point.timestamp <= 30000
  );
}
function candidate(favorite, point, date, stations) {
  if (!favorite || typeof favorite.id !== 'string' || !favorite.id || favorite.enabled !== true)
    return null;
  let schedule;
  try {
    schedule = normalizeSchedule(favorite.schedule);
  } catch {
    return null;
  }
  const occurrence = scheduleOccurrence(schedule, date),
    route = findRoute(stations, favorite.from, favorite.to);
  if (!occurrence || !route || !(distanceMeters(route.from, point) <= 180)) return null;
  const signature = JSON.stringify([
    favorite.id,
    favorite.from,
    favorite.to,
    schedule.days,
    schedule.start,
    schedule.end,
  ]);
  return { id: favorite.id, signature, occurrence, route };
}
function claimed(marker, occurrence, date) {
  return marker === occurrence || marker === localDay(date) || marker === occurrence.split('|')[0];
}
function validClaim(value) {
  if (typeof value !== 'string') return false;
  const parts = value.split('|'),
    day = parts[0];
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return false;
  const [year, month, date] = day.split('-').map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (month < 1 || month > 12 || date < 1 || date > days[month - 1]) return false;
  if (parts.length === 1) return true;
  return (
    parts.length === 3 &&
    /^([01]\d|2[0-3]):[0-5]\d$/.test(parts[1]) &&
    /^([01]\d|2[0-3]):[0-5]\d$/.test(parts[2]) &&
    parts[1] !== parts[2]
  );
}
function claimHistory(marker, date) {
  let claims;
  if (marker === null) claims = [];
  else if (validClaim(marker)) claims = [marker];
  else {
    let history;
    try {
      history = JSON.parse(marker);
    } catch {
      return null;
    }
    if (
      !history ||
      history.version !== 1 ||
      !Array.isArray(history.claims) ||
      history.claims.length > 128 ||
      !history.claims.every(validClaim) ||
      new Set(history.claims).size !== history.claims.length
    )
      return null;
    claims = history.claims;
  }
  const previous = new Date(date);
  previous.setDate(previous.getDate() - 1);
  const oldest = localDay(previous);
  // Keep previous/current start days and future claims; a clock change must not evict live claims.
  return claims.filter((claim) => claim.split('|')[0] >= oldest);
}
function createCommuteSuggester({ store, storage, stations, notify, now = () => new Date() }) {
  let queue = Promise.resolve();
  async function latestCandidate(expected, point) {
    const config = await store.readState(),
      date = now();
    if (!config.automation || config.active || !freshPoint(point, date)) return null;
    const favorite = Array.isArray(config.favorites)
      ? config.favorites.find((f) => f?.id === expected.id)
      : null;
    const current = candidate(favorite, point, date, stations);
    if (
      !current ||
      current.signature !== expected.signature ||
      current.occurrence !== expected.occurrence
    )
      return null;
    return { current, date };
  }
  async function run(point) {
    const state = await store.readState(),
      date = now();
    if (!state.automation || state.active || !freshPoint(point, date)) return false;
    for (const favorite of Array.isArray(state.favorites) ? state.favorites : []) {
      const next = candidate(favorite, point, date, stations);
      if (!next) continue;
      const key = suggestionKey(next.id),
        marker = await storage.getItem(key);
      const beforeClaim = await latestCandidate(next, point);
      if (!beforeClaim) continue;
      const claims = claimHistory(marker, beforeClaim.date);
      if (
        !claims ||
        claims.some((claim) => claimed(claim, next.occurrence, beforeClaim.date)) ||
        claims.length >= 128
      )
        continue;
      await storage.setItem(
        key,
        JSON.stringify({ version: 1, claims: [...claims, next.occurrence] }),
      );
      const beforeNotify = await latestCandidate(next, point);
      if (!beforeNotify) return false;
      const { route } = beforeNotify.current;
      await notify(
        '출퇴근 경로 확인 (데모)',
        `${route.from.name} → ${route.to.name}. 앱에서 탑승과 방향을 확인한 뒤 감시를 시작하세요.`,
      );
      return true;
    }
    return false;
  }
  return function suggest(point) {
    const snapshot = point && { ...point };
    const result = queue.then(() => run(snapshot));
    // Keep failures visible to callers without poisoning subsequent location events.
    queue = result.catch(() => {});
    return result;
  };
}
module.exports = { createCommuteSuggester };
