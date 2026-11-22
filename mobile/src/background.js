import * as TaskManager from 'expo-task-manager';
import * as Location from 'expo-location';
import * as Notifications from 'expo-notifications';
import AsyncStorage from '@react-native-async-storage/async-storage';
const {createStorage,updateMonitoringConfig} = require('./storage');
const {createLocationTask,LOCATION_CHANNEL,scheduleLocationNotification} = require('./locationTask');
export const TASK = 'subway-location-monitor';
const store=createStorage(AsyncStorage);
export const readState=store.readState;
export const updateState=change=>updateMonitoringConfig(store,change,{enable:enableMonitoring,disable:disableMonitoring});
export const notify=(title,body)=>scheduleLocationNotification(Notifications,title,body);
const {handleLocations,runExclusive,subscribeToTripCompletion} = createLocationTask({storage:AsyncStorage, store, notify, stopMonitoring:disableMonitoring});
export {runExclusive as runMonitoringOperation,subscribeToTripCompletion};
TaskManager.defineTask(TASK, async ({data,error}) => {
  if (!error) await handleLocations(data?.locations);
});
export async function requestNotificationPermissions() {
  await Notifications.setNotificationChannelAsync(LOCATION_CHANNEL,{name:'하차 알림',importance:Notifications.AndroidImportance.HIGH,vibrationPattern:[0,500,250,500],lockscreenVisibility:Notifications.AndroidNotificationVisibility.PUBLIC});
  const n=await Notifications.requestPermissionsAsync();
  if (!n.granted) throw new Error('알림 권한이 필요합니다.');
}
export async function enableMonitoring() {
  await requestNotificationPermissions();
  const fg=await Location.requestForegroundPermissionsAsync();
  if (!fg.granted) throw new Error('위치 권한이 필요합니다.');
  const bg=await Location.requestBackgroundPermissionsAsync();
  if (!bg.granted) throw new Error('백그라운드 위치 권한이 필요합니다. Android 설정에서 항상 허용을 선택해 주세요.');
  if (!(await Location.hasStartedLocationUpdatesAsync(TASK))) await Location.startLocationUpdatesAsync(TASK,{accuracy:Location.Accuracy.High,timeInterval:15000,distanceInterval:40,deferredUpdatesInterval:15000,foregroundService:{notificationTitle:'지하철 경로 감시 중 (데모)',notificationBody:'위치 감시가 실행 중입니다. 앱에서 중지할 수 있습니다.',notificationColor:'#2854d5'}});
}
export async function disableMonitoring() { if (await Location.hasStartedLocationUpdatesAsync(TASK)) await Location.stopLocationUpdatesAsync(TASK); }
