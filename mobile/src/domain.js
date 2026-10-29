const { normalizeSchedule, scheduleOccurrence } = require('./commute');

function addFavorite(favorites, favorite) {
  if (favorites.some((f) => f.from === favorite.from && f.to === favorite.to))
    throw new Error('이미 등록된 경로입니다.');
  if (favorites.length >= 5) throw new Error('즐겨찾기는 최대 5개입니다.');
  return [...favorites, favorite];
}
function saveFavorite(favorites, draft, editingId = null) {
  if (
    !draft ||
    typeof draft.from !== 'string' ||
    !draft.from.trim() ||
    typeof draft.to !== 'string' ||
    !draft.to.trim() ||
    draft.from === draft.to
  ) {
    throw new Error('서로 다른 출발역과 도착역을 선택해 주세요.');
  }
  const schedule = normalizeSchedule(draft.schedule);
  const editing = editingId !== null;
  const index = editing ? favorites.findIndex((favorite) => favorite.id === editingId) : -1;
  if (editing && index < 0) throw new Error('수정할 즐겨찾기를 찾을 수 없습니다.');
  if (
    favorites.some(
      (favorite, i) => i !== index && favorite.from === draft.from && favorite.to === draft.to,
    )
  ) {
    throw new Error('이미 등록된 경로입니다.');
  }
  if (editing) {
    return favorites.map((favorite, i) =>
      i === index ? { ...favorite, from: draft.from, to: draft.to, schedule } : favorite,
    );
  }
  if (typeof draft.id !== 'string' || !draft.id.trim())
    throw new Error('즐겨찾기 ID가 필요합니다.');
  if (favorites.some((favorite) => favorite.id === draft.id))
    throw new Error('이미 등록된 즐겨찾기 ID입니다.');
  if (favorites.length >= 5) throw new Error('즐겨찾기는 최대 5개입니다.');
  return [
    ...favorites,
    { ...draft, schedule, enabled: draft.enabled === undefined ? true : draft.enabled },
  ];
}
function findRoute(stations, from, to) {
  const a = stations.findIndex((s) => s.id === from),
    b = stations.findIndex((s) => s.id === to);
  if (a < 0 || b < 0 || a === b) return null;
  return {
    from: stations[a],
    to: stations[b],
    previous: stations[b + (a < b ? -1 : 1)],
    count: Math.abs(a - b),
  };
}
function distanceMeters(a, b) {
  const rad = (x) => (x * Math.PI) / 180,
    R = 6371000;
  const dLat = rad(b.latitude - a.lat),
    dLon = rad(b.longitude - a.lon);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.latitude)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}
function shouldAlert({ target, point, now, wasOutside }) {
  if (
    !target ||
    !point ||
    !wasOutside ||
    !Number.isFinite(point.accuracy) ||
    point.accuracy > 80 ||
    point.accuracy < 0 ||
    !Number.isFinite(point.timestamp) ||
    point.timestamp > now + 5000 ||
    now - point.timestamp > 30000
  )
    return false;
  return distanceMeters(target, point) <= 180;
}
function matchesSchedule(schedule, date) {
  return scheduleOccurrence(schedule, date) !== null;
}
module.exports = {
  addFavorite,
  saveFavorite,
  findRoute,
  distanceMeters,
  shouldAlert,
  matchesSchedule,
};
