const stations = require('./stations');
const {findRoute, distanceMeters, scheduleWindowStartDay, shouldAlert, usableLocation} = require('./domain');
const {suggestionKey} = require('./storage');
const byId = id => stations.find(s => s.id === id);

const LOCATION_CHANNEL = 'default';
function scheduleLocationNotification(notifications, title, body) {
  return notifications.scheduleNotificationAsync({
    content: {title, body, sound:true, priority:notifications.AndroidNotificationPriority.HIGH},
    trigger: {channelId:LOCATION_CHANNEL}
  });
}

function createLocationTask({storage, store, notify, stopMonitoring, now = Date.now}) {
  // Expo can deliver another batch while an earlier callback is awaiting native I/O.
  // UI changes share this queue so a finishing trip cannot stop a newly started service.
  let pending = Promise.resolve();
  const completionListeners = new Set();
  function subscribeToTripCompletion(listener) {
    completionListeners.add(listener);
    return () => completionListeners.delete(listener);
  }
  function runExclusive(operation) {
    const result = pending.then(operation);
    pending = result.catch(() => {});
    return result;
  }

  async function suggestCommute(state, point) {
    const date = new Date(point.timestamp);
    const observationDay = date.toLocaleDateString('en-CA');
    for (const favorite of state.favorites || []) {
      const from = byId(favorite.from), to = byId(favorite.to);
      if (!favorite.enabled || !from || !to || distanceMeters(from, point) > 180) continue;
      const startDay = scheduleWindowStartDay(favorite.schedule, date);
      if (!startDay) continue;
      const day = startDay.toLocaleDateString('en-CA');
      const key = suggestionKey(favorite.id);
      const lastSuggestion = await storage.getItem(key);
      if (lastSuggestion === day) continue;
      // Older releases saved the observation date after midnight.
      if (day !== observationDay && lastSuggestion === observationDay) {
        await storage.setItem(key, day);
        continue;
      }
      const latest = await store.readState();
      if (latest.active || !latest.automation || !latest.favorites?.some(f => f.id === favorite.id && f.enabled)) return;
      await notify('출퇴근 경로 확인 (데모)', `${from.name} → ${to.name}. 앱에서 탑승과 방향을 확인한 뒤 감시를 시작하세요.`);
      await storage.setItem(key, day);
      return;
    }
  }

  async function stopIfIdle() {
    const latest = await store.readState();
    if (!latest.active && !latest.automation) await stopMonitoring();
  }

  async function processLocations(locations) {
    if (!Array.isArray(locations)) return;
    const currentTime = now();
    const points = locations.map(loc => ({...loc?.coords, timestamp:loc?.timestamp}))
      .filter(point => usableLocation(point, currentTime))
      .sort((a,b) => a.timestamp - b.timestamp);
    if (!points.length) return;

    const state = await store.readState();
    const trip = state.active;
    if (!trip) {
      if (state.automation) await suggestCommute(state, points[points.length-1]);
      else await stopIfIdle();
      return;
    }
    const route = findRoute(stations, trip.from, trip.to);
    if (!route || route.count < 2) return;
    const progress = await store.readProgress(trip.id);
    for (const point of points) {
      if (point.timestamp < trip.startedAt || point.timestamp <= progress.lastTimestamp) continue;
      if (shouldAlert({target:route.previous, point, now:currentTime, wasOutside:progress.wasOutside})) {
        if ((await store.readState()).active?.id !== trip.id) return;
        await notify('하차 전 역 근처 (데모)', `${route.previous.name} 근처입니다. 다음 역 ${route.to.name}에서 하차할 준비를 하세요. 실제 열차 위치는 확인되지 않았습니다.`);
        await store.writeProgress(trip.id, {...progress, completed:true, lastTimestamp:point.timestamp});
        for (const listener of completionListeners) listener();
        await stopIfIdle();
        return;
      }
      if (distanceMeters(route.previous, point) > 500) progress.wasOutside = true;
      progress.lastTimestamp = point.timestamp;
      await store.writeProgress(trip.id, progress);
    }
  }
  return {runExclusive, subscribeToTripCompletion, handleLocations:locations => runExclusive(() => processLocations(locations))};
}
module.exports = {createLocationTask, LOCATION_CHANNEL, scheduleLocationNotification};
