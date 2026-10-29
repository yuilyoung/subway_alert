import * as TaskManager from 'expo-task-manager';
import * as Location from 'expo-location';
import * as Notifications from 'expo-notifications';
import AsyncStorage from '@react-native-async-storage/async-storage';
const stations = require('./stations');
const { findRoute, distanceMeters, shouldAlert } = require('./domain');
const { createCommuteSuggester } = require('./commuteSuggestions');
export const TASK = 'subway-location-monitor';
const { createStorage } = require('./storage');
const store = createStorage(AsyncStorage);
const config = store.readConfig;
export const readState = store.readState;
export const writeState = store.writeConfig;
async function notify(title, body) {
  await Notifications.scheduleNotificationAsync({
    content: { title, body, sound: true, priority: Notifications.AndroidNotificationPriority.HIGH },
    trigger: null,
  });
}
const suggestCommute = createCommuteSuggester({ store, storage: AsyncStorage, stations, notify });
TaskManager.defineTask(TASK, async ({ data, error }) => {
  if (error || !data?.locations?.length) return;
  const loc = data.locations[data.locations.length - 1],
    point = { ...loc.coords, timestamp: loc.timestamp },
    now = Date.now();
  if (
    !Number.isFinite(point.accuracy) ||
    point.accuracy > 80 ||
    point.accuracy < 0 ||
    now - point.timestamp > 30000 ||
    point.timestamp > now + 5000
  )
    return;
  const state = await store.readState();
  if (!state.active && state.automation) {
    await suggestCommute(point);
  }
  if (state.active?.id) {
    const trip = state.active,
      route = findRoute(stations, trip.from, trip.to),
      progress = await store.readProgress(trip.id);
    if (route && route.count > 1 && !progress.completed) {
      if (distanceMeters(route.previous, point) > 500) progress.wasOutside = true;
      if (shouldAlert({ target: route.previous, point, now, wasOutside: progress.wasOutside })) {
        progress.completed = true;
        await store.writeProgress(trip.id, progress);
        const latest = await config();
        if (latest.active?.id === trip.id) {
          await notify(
            '하차 전 역 근처 (데모)',
            `${route.previous.name} 근처입니다. 다음 역 ${route.to.name}에서 하차할 준비를 하세요. 실제 열차 위치는 확인되지 않았습니다.`,
          );
          const final = await config();
          if (
            final.active?.id === trip.id &&
            !final.automation &&
            (await Location.hasStartedLocationUpdatesAsync(TASK))
          )
            await Location.stopLocationUpdatesAsync(TASK);
        }
      } else await store.writeProgress(trip.id, progress);
    }
  }
});
export async function requestNotificationPermissions() {
  await Notifications.setNotificationChannelAsync('default', {
    name: '하차 알림',
    importance: Notifications.AndroidImportance.HIGH,
    vibrationPattern: [0, 500, 250, 500],
    lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
  });
  const n = await Notifications.requestPermissionsAsync();
  if (!n.granted) throw new Error('알림 권한이 필요합니다.');
}
export async function enableMonitoring() {
  await requestNotificationPermissions();
  const fg = await Location.requestForegroundPermissionsAsync();
  if (!fg.granted) throw new Error('위치 권한이 필요합니다.');
  const bg = await Location.requestBackgroundPermissionsAsync();
  if (!bg.granted)
    throw new Error(
      '백그라운드 위치 권한이 필요합니다. Android 설정에서 항상 허용을 선택해 주세요.',
    );
  if (!(await Location.hasStartedLocationUpdatesAsync(TASK)))
    await Location.startLocationUpdatesAsync(TASK, {
      accuracy: Location.Accuracy.High,
      timeInterval: 15000,
      distanceInterval: 40,
      deferredUpdatesInterval: 15000,
      foregroundService: {
        notificationTitle: '지하철 경로 감시 중 (데모)',
        notificationBody: '위치 감시가 실행 중입니다. 앱에서 중지할 수 있습니다.',
        notificationColor: '#2854d5',
      },
    });
}
export async function disableMonitoring() {
  if (await Location.hasStartedLocationUpdatesAsync(TASK))
    await Location.stopLocationUpdatesAsync(TASK);
}
