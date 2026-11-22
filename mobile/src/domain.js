function addFavorite(favorites, favorite) {
  if (favorites.some(f => f.from === favorite.from && f.to === favorite.to)) throw new Error('이미 등록된 경로입니다.');
  if (favorites.length >= 5) throw new Error('즐겨찾기는 최대 5개입니다.');
  return [...favorites, favorite];
}
function findRoute(stations, from, to) {
  const a=stations.findIndex(s=>s.id===from), b=stations.findIndex(s=>s.id===to);
  if (a<0 || b<0 || a===b) return null;
  return {from:stations[a], to:stations[b], previous:stations[b+(a<b?-1:1)], count:Math.abs(a-b)};
}
function distanceMeters(a,b) {
  const rad=x=>x*Math.PI/180, R=6371000;
  const dLat=rad(b.latitude-a.lat), dLon=rad(b.longitude-a.lon);
  const h=Math.sin(dLat/2)**2+Math.cos(rad(a.lat))*Math.cos(rad(b.latitude))*Math.sin(dLon/2)**2;
  return 2*R*Math.atan2(Math.sqrt(h),Math.sqrt(1-h));
}
function usableLocation(point,now) {
  return point && Number.isFinite(point.latitude) && Math.abs(point.latitude)<=90 &&
    Number.isFinite(point.longitude) && Math.abs(point.longitude)<=180 &&
    Number.isFinite(point.accuracy) && point.accuracy>=0 && point.accuracy<=80 &&
    Number.isFinite(point.timestamp) && point.timestamp<=now+5000 && now-point.timestamp<=30000;
}
function shouldAlert({target, point, now, wasOutside}) {
  if (!target || !wasOutside || !usableLocation(point,now)) return false;
  return distanceMeters(target,point)<=180;
}
function scheduleWindowStartDay(schedule,date) {
  if (!schedule || !Array.isArray(schedule.days) || !/^\d{2}:\d{2}$/.test(schedule.start || '') || !/^\d{2}:\d{2}$/.test(schedule.end || '')) return null;
  const parse=s=>Number(s.slice(0,2))*60+Number(s.slice(3));
  const valid=s=>Number(s.slice(0,2))<24 && Number(s.slice(3))<60;
  if (!valid(schedule.start)||!valid(schedule.end)) return null;
  const start=parse(schedule.start), end=parse(schedule.end), now=date.getHours()*60+date.getMinutes();
  const overnight = start > end;
  const inWindow = overnight ? now >= start || now < end : now >= start && now < end;
  if (!inWindow) return null;
  const startDay = new Date(date);
  if (overnight && now < end) startDay.setDate(startDay.getDate() - 1);
  return schedule.days.includes(startDay.getDay()) ? startDay : null;
}
function matchesSchedule(schedule,date) { return scheduleWindowStartDay(schedule,date) !== null; }
module.exports={addFavorite,findRoute,distanceMeters,shouldAlert,matchesSchedule,scheduleWindowStartDay,usableLocation};
