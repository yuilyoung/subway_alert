import {Alert, PermissionsAndroid, Platform} from 'react-native';
import NativeSubway from './native/NativeSubway';
import type {Capabilities} from './types';
export async function capabilities(): Promise<Capabilities> { return JSON.parse(await NativeSubway.capabilities()) as Capabilities; }
export async function requireNotifications(): Promise<void> {
  if (Platform.OS === 'android' && Number(Platform.Version) >= 33) {
    await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS);
  }
  if (!(await capabilities()).notifications) throw new Error('알림이 꺼져 있습니다. 앱 설정에서 알림을 허용하세요.');
}
export async function requireLocation(): Promise<void> {
  const result = await PermissionsAndroid.requestMultiple([
    PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION, PermissionsAndroid.PERMISSIONS.ACCESS_COARSE_LOCATION,
  ]);
  if (result[PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION] !== PermissionsAndroid.RESULTS.GRANTED)
    throw new Error('정확한 위치를 허용해야 출발역 접근을 감지할 수 있습니다. 수동 경로 입력은 위치 권한 없이 사용할 수 있습니다.');
}
export async function prepareAutomatic(demo: boolean): Promise<boolean> {
  if (demo) throw new Error('자동 출퇴근은 검증된 역 좌표와 Firebase가 있는 실사용 모드에서 설정하세요.');
  if (!(await capabilities()).firebaseConfigured) throw new Error('먼저 Firebase 설정을 포함한 앱을 빌드하세요.');
  await requireNotifications();
  await requireLocation();
  if (!(await capabilities()).backgroundLocation) {
    if (Number(Platform.Version) === 29) {
      await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.ACCESS_BACKGROUND_LOCATION);
    } else {
      Alert.alert('백그라운드 위치 동의', '출퇴근 시간에 출발역 접근을 감지하려면 설정 → 권한 → 위치에서 ‘항상 허용’을 선택하세요. 현재 위치를 서버에 계속 전송하지 않습니다. 돌아온 뒤 저장을 다시 누르세요.', [
        {text: '취소', style: 'cancel'}, {text: '설정 열기', onPress: () => NativeSubway.openSettings()},
      ]);
      return false;
    }
  }
  if (!(await capabilities()).backgroundLocation) throw new Error('백그라운드 위치 권한이 허용되지 않았습니다.');
  return true;
}
