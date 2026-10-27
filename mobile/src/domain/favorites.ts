export type Station = {
  id: string;
  lineId: string;
  name: string;
  topisId: string;
  latitude: number | null;
  longitude: number | null;
  source?: string;
  sourceUrl?: string;
};
export type Favorite = {
  id: string;
  label: string;
  origin: Station;
  destination: Station;
  direction: '0' | '1';
  enabled: boolean;
  days: number[]; // ISO weekday: Monday=1, Sunday=7. Overnight windows belong to their starting day.
  start: string;
  end: string;
};
export const MAX_FAVORITES = 5;
const timePattern = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
export function normalizeQuery(query: string): string {
  return query.trim().replace(/\s+/g, ' ').slice(0, 80);
}
export function validateFavorite(item: Favorite): void {
  if (!item || typeof item.id !== 'string' || !/^[A-Za-z0-9_-]{1,100}$/.test(item.id)) throw new Error('잘못된 즐겨찾기 ID입니다.');
  if (typeof item.label !== 'string' || !item.label.trim() || item.label.length > 40) throw new Error('이름은 1~40자로 입력하세요.');
  for (const station of [item.origin, item.destination]) {
    if (!station || typeof station.id !== 'string' || !station.id || !station.lineId || !station.name)
      throw new Error('검색 결과에서 역을 선택하세요.');
  }
  if (item.origin.id === item.destination.id) throw new Error('출발역과 도착역은 달라야 합니다.');
  if (item.origin.lineId !== item.destination.lineId) throw new Error('현재는 동일 호선 경로만 지원합니다.');
  if (item.direction !== '0' && item.direction !== '1') throw new Error('진행 방향을 선택하세요.');
  if (!Array.isArray(item.days) || item.days.length === 0 || new Set(item.days).size !== item.days.length
    || item.days.some(day => !Number.isInteger(day) || day < 1 || day > 7)) throw new Error('요일을 선택하세요.');
  if (!timePattern.test(item.start) || !timePattern.test(item.end) || item.start === item.end)
    throw new Error('서로 다른 시작·종료 시간을 HH:mm 형식으로 입력하세요.');
  if (typeof item.enabled !== 'boolean') throw new Error('자동 시작 설정이 올바르지 않습니다.');
  if (item.enabled) {
    const {latitude, longitude} = item.origin;
    if (latitude === null || longitude === null || !Number.isFinite(latitude) || !Number.isFinite(longitude)
      || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) throw new Error('검증된 출발역 좌표가 있어야 자동 시작할 수 있습니다.');
  }
}
const routeKey = (f: Favorite): string => `${f.origin.id}\0${f.destination.id}\0${f.direction}`;
export function upsertFavorite(items: readonly Favorite[], item: Favorite): Favorite[] {
  validateFavorite(item);
  if (items.some(existing => existing.id !== item.id && routeKey(existing) === routeKey(item)))
    throw new Error('이미 등록된 경로입니다.');
  const index = items.findIndex(existing => existing.id === item.id);
  if (index < 0 && items.length >= MAX_FAVORITES) throw new Error('즐겨찾기는 최대 5개까지 등록할 수 있습니다.');
  const copy = {...item, label: item.label.trim(), days: [...item.days]};
  return index < 0 ? [...items, copy] : items.map((existing, i) => i === index ? copy : existing);
}
export function parseFavorites(json: string): Favorite[] {
  const value: unknown = JSON.parse(json);
  if (!Array.isArray(value) || value.length > MAX_FAVORITES) throw new Error('저장된 즐겨찾기 형식이 올바르지 않습니다.');
  let result: Favorite[] = [];
  for (const item of value as Favorite[]) {
    if (result.some(existing => existing.id === item.id)) throw new Error('중복 즐겨찾기 ID입니다.');
    result = upsertFavorite(result, item);
  }
  return result;
}
