import React, {useEffect, useMemo, useRef, useState} from 'react';
import {ActivityIndicator, Alert, AppState, Pressable, ScrollView, StatusBar, Switch, Text, TextInput, View} from 'react-native';
import {SafeAreaProvider, SafeAreaView} from 'react-native-safe-area-context';
import {Api, ApiError} from './src/api';
import {Button} from './src/components/Button';
import {FacilitySheet} from './src/components/FacilitySheet';
import {FavoriteEditor} from './src/components/FavoriteEditor';
import {StationField} from './src/components/StationField';
import {parseFavorites, upsertFavorite} from './src/domain/favorites';
import type {Favorite, Station} from './src/domain/favorites';
import NativeSubway from './src/native/NativeSubway';
import {capabilities, prepareAutomatic, requireLocation, requireNotifications} from './src/permissions';
import type {Capabilities, Candidate, Line, NativeState, Session, StationDetail} from './src/types';
import {colors, styles as s} from './src/theme';

const activeStatuses = ['WAITING_BOARDING', 'TRACKING', 'ALERT_PENDING'];
const statusLabels: Record<Session['status'], string> = {
  WAITING_BOARDING: '탑승할 열차를 확인하세요', TRACKING: '하차 알림 추적 중', ALERT_PENDING: '하차 알림 전송 중',
  ALERTED: '하차 알림을 발송했습니다', CANCELLED: '추적이 취소됐습니다', EXPIRED: '추적 시간이 만료됐습니다', FAILED: '알림 발송에 실패했습니다',
};
const message = (error: unknown) => error instanceof Error ? error.message : '작업을 완료하지 못했습니다.';
const newId = () => `f_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
async function readState(): Promise<NativeState> {
  const value = JSON.parse(await NativeSubway.getState()) as NativeState;
  return {...value, favorites: parseFavorites(JSON.stringify(value.favorites))};
}

function SubwayApp() {
  const [settings, setSettings] = useState<NativeState | null>(null);
  const [tab, setTab] = useState<'route' | 'favorites' | 'settings'>('route');
  const [lines, setLines] = useState<Line[]>([]);
  const [origin, setOrigin] = useState<Station | null>(null);
  const [destination, setDestination] = useState<Station | null>(null);
  const [direction, setDirection] = useState<'0' | '1'>('0');
  const [preview, setPreview] = useState<Station[]>([]);
  const [routeError, setRouteError] = useState('');
  const [session, setSession] = useState<Session | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [detail, setDetail] = useState<StationDetail | null>(null);
  const [editing, setEditing] = useState<Favorite | null>(null);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [nearby, setNearby] = useState<Station[]>([]);
  const [baseDraft, setBaseDraft] = useState('http://10.0.2.2:8080');
  const [demoDraft, setDemoDraft] = useState(true);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [now, setNow] = useState(Date.now());
  const busyRef = useRef(false);
  const version = useRef(0);
  const pendingStart = useRef<{fingerprint: string; key: string} | null>(null);
  const api = useMemo(() => settings ? new Api(settings) : null, [settings?.baseUrl, settings?.demo, settings?.installId]);

  async function perform(action: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true; version.current++; setBusy(true); setError('');
    try { await action(); } catch (e) {setError(message(e)); Alert.alert('확인', message(e));}
    finally {busyRef.current = false; setBusy(false);}
  }
  useEffect(() => {readState().then(setSettings).catch(e => setError(message(e)));}, []);
  useEffect(() => {if (settings) {setBaseDraft(settings.baseUrl); setDemoDraft(settings.demo);}}, [settings?.baseUrl, settings?.demo]);
  useEffect(() => {
    if (!api || !settings) return;
    let alive = true;
    async function refresh() {
      if (busyRef.current) return;
      const stamp = version.current;
      setReady(false);
      try {
        const native = await readState();
        const [health, availableLines, currentCaps] = await Promise.all([api!.health(), api!.lines(), capabilities()]);
        if (health.mode !== (native.demo ? 'DEMO' : 'LIVE')) throw new Error('앱과 서버의 데모/실사용 모드가 다릅니다. 설정을 확인하세요.');
        let current = (await api!.active()).session;
        if (!current && native.sessionId) {
          try {current = await api!.status(native.sessionId);} catch (e) {
            if (e instanceof ApiError && e.status === 404) await NativeSubway.clearActiveSession(native.sessionId);
            else throw e;
          }
        }
        if (current) await NativeSubway.setActiveSession(current.id);
        if (!alive || stamp !== version.current) return;
        setSettings(native); setLines(availableLines); setCaps(currentCaps); setSession(current);
        setReady(health.catalogReady); setError(health.catalogReady ? '' : '검증된 역 데이터가 없습니다. 서버에 역·노선 자료를 먼저 적재하세요.');
        if (current) {setTab('route'); await api!.refreshToken();}
      } catch (e) {if (alive && stamp === version.current) setError(message(e));}
    }
    void refresh();
    const listener = AppState.addEventListener('change', state => {if (state === 'active') void refresh();});
    return () => {alive = false; listener.remove();};
  }, [api, reload]);
  useEffect(() => {
    let alive = true; setPreview([]); setRouteError('');
    if (api && origin && destination) api.route(origin, destination, direction).then(route => {if (alive) setPreview(route);})
      .catch(e => {if (alive) setRouteError(message(e));});
    return () => {alive = false;};
  }, [api, origin, destination, direction]);
  useEffect(() => {
    if (!api || !session || !activeStatuses.includes(session.status)) return;
    let alive = true;
    const id = session.id;
    async function poll() {
      if (busyRef.current || AppState.currentState !== 'active') return;
      const stamp = version.current;
      try {
        const next = await api!.status(id);
        const trains = next.status === 'WAITING_BOARDING' ? await api!.candidates(id) : [];
        if (!alive || stamp !== version.current) return;
        setSession(next); setCandidates(trains);
      } catch (e) {if (alive && stamp === version.current) setError(message(e));}
      finally {if (alive) setNow(Date.now());}
    }
    void poll(); const timer = setInterval(() => {void poll();}, 10_000);
    return () => {alive = false; clearInterval(timer);};
  }, [api, session?.id, session?.status]);

  async function saveFavorites(list: Favorite[]) {
    if (!settings) return;
    const before = settings.favorites;
    await NativeSubway.saveFavorites(JSON.stringify(list));
    try {await NativeSubway.syncGeofences();} catch (e) {
      await NativeSubway.saveFavorites(JSON.stringify(before));
      await NativeSubway.syncGeofences().catch(() => {});
      throw e;
    }
    setSettings({...settings, favorites: list});
  }
  const pickOrigin = (station: Station) => {
    setOrigin(station); setNearby([]);
    if (destination && destination.lineId !== station.lineId) setDestination(null);
  };
  async function start() {
    if (!api || !origin || !destination || preview.length < 2) return;
    await requireNotifications();
    const fingerprint = `${origin.id}|${destination.id}|${direction}`;
    if (pendingStart.current?.fingerprint !== fingerprint) pendingStart.current = {fingerprint, key: newId()};
    const next = await api.start(origin, destination, direction, pendingStart.current.key);
    await NativeSubway.setActiveSession(next.id);
    pendingStart.current = null; setSession(next); setCandidates([]);
  }
  async function dismiss() {
    if (!session || !api) return;
    if (activeStatuses.includes(session.status)) await api.cancel(session.id);
    await NativeSubway.clearActiveSession(session.id);
    setSession(null); setCandidates([]); setReload(n => n + 1);
  }
  const facility = (station: Station) => {void perform(async () => {if (api) setDetail(await api.detail(station.id));});};
  function newFavorite() {
    if (!origin || !destination || !settings) return;
    const existing = settings.favorites.find(f => f.origin.id === origin.id && f.destination.id === destination.id && f.direction === direction);
    setEditing(existing ?? {id: newId(), label: `${origin.name} → ${destination.name}`.slice(0, 40), origin, destination, direction,
      enabled: false, days: [1,2,3,4,5], start: '07:00', end: '10:00'});
  }

  if (!settings || !api) return <SafeAreaView style={s.screen}><View style={s.content}>
    <Text style={s.title}>지하철 하차알림</Text>{error ? <Text style={s.errorText}>{error}</Text> : <ActivityIndicator />}
    <Button label="다시 열기" onPress={() => {void perform(async () => setSettings(await readState()));}} />
  </View></SafeAreaView>;

  const selectedLine = lines.find(line => line.id === origin?.lineId);
  const fresh = !!session?.observedAt && session.dataFresh && now - Date.parse(session.observedAt) <= 90_000;
  return <SafeAreaView style={s.screen}>
    <StatusBar barStyle="dark-content" backgroundColor={colors.background} />
    <View style={s.header}><View><Text style={s.title}>다음 역에서 만나요</Text><Text style={s.subtitle}>지하철 하차알림</Text></View><Text style={s.badge}>{settings.demo ? 'DEMO' : 'LIVE'}</Text></View>
    <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={s.content}>
      {settings.demo && <View style={s.notice}><Text style={s.small}>데모 · 가상 역과 모의 열차입니다. 실제 하차에 사용하지 마세요. 서버 FCM 전송 대신 상태 변화만 확인합니다.</Text></View>}
      {error !== '' && <View style={s.error}><Text style={s.errorText}>{error}</Text><Button label="연결 다시 확인" secondary onPress={() => setReload(n => n + 1)} disabled={busy} /></View>}
      {busy && <ActivityIndicator accessibilityLabel="처리 중" color={colors.accent} />}
      {tab === 'route' && !session && <>
        <View style={s.card}>
          <Text style={s.heading}>어디에서 내리시나요?</Text>
          <StationField label="출발역" api={api} selected={origin} onSelect={pickOrigin} onClear={() => setOrigin(null)} />
          <Button label="GPS로 가까운 출발역 찾기" secondary disabled={busy || settings.demo} onPress={() => {void perform(async () => {
            await requireLocation();
            const fix = JSON.parse(await NativeSubway.location()) as {latitude: number; longitude: number; accuracy: number; ageMillis: number};
            if (fix.accuracy > 150 || fix.ageMillis > 120_000) throw new Error('위치 정확도가 낮습니다. 역을 직접 검색하세요.');
            const found = await api.nearby(fix.latitude, fix.longitude); setNearby(found);
            if (!found.length) throw new Error('1km 이내에 등록된 역이 없습니다. 직접 검색하세요.');
          });}} />
          {nearby.map(station => <Button key={station.id} label={`${station.name} · ${station.lineId}`} secondary onPress={() => pickOrigin(station)} />)}
          <StationField label="도착역" api={api} selected={destination} lineId={origin?.lineId} onSelect={setDestination} onClear={() => setDestination(null)} />
          {selectedLine && <><Text style={s.small}>{selectedLine.name} · 진행 방향</Text><View style={s.row}>
            {selectedLine.directions.map(d => <Pressable key={d.code} accessibilityRole="radio" accessibilityState={{selected: direction === d.code}}
              style={[s.chip, direction === d.code && s.chipSelected]} onPress={() => setDirection(d.code)}><Text style={s.text}>{d.label}</Text></Pressable>)}
          </View></>}
          {routeError !== '' && <Text style={s.errorText}>{routeError}</Text>}
          {preview.length > 1 && <View style={s.notice}><Text style={s.heading}>{preview.length - 1}정거장 · 1정거장 전 알림</Text>
            <Text style={s.small}>{preview.map(station => station.name).join(' → ')}</Text></View>}
          <Button label="탑승 열차 선택하기" disabled={busy || !ready || preview.length < 2} onPress={() => {void perform(start);}} />
          <Button label={`즐겨찾기에 저장 (${settings.favorites.length}/5)`} secondary disabled={busy || preview.length < 2} onPress={newFavorite} />
          <Text style={s.small}>현재는 동일 호선의 일반 열차를 지원합니다. 열차 위치 API로 탑승자를 알 수 없어, 탑승 확인 후 추적합니다.</Text>
        </View>
        {(origin || destination) && <View style={s.card}><Text style={s.heading}>역 이용 안내</Text>
          {origin && <Button label={`${origin.name} · 시설 / 환승 / 출구`} secondary disabled={busy} onPress={() => facility(origin)} />}
          {destination && <Button label={`${destination.name} · 시설 / 환승 / 출구`} secondary disabled={busy} onPress={() => facility(destination)} />}
        </View>}
      </>}
      {tab === 'route' && session && <>
        <View style={s.card}>
          <Text style={s.badge}>{statusLabels[session.status]}</Text>
          <Text style={s.heading}>{session.route[0]?.name} → {session.route.at(-1)?.name}</Text>
          {session.status === 'WAITING_BOARDING' ? <>
            <Text style={s.text}>출발역의 해당 방향 일반 열차를 확인하세요.</Text>
            <Text style={s.small}>다른 열차를 선택하면 잘못된 시점에 알릴 수 있습니다. GPS만으로 실제 탑승 열차를 확정하지 않습니다.</Text>
            {candidates.length === 0 && <Text style={s.small}>선택 가능한 열차가 없습니다. 열차가 출발역에 접근할 때 새로고침하세요. 급행·종착역 미확인 열차는 제외됩니다.</Text>}
            {candidates.map(train => <View key={train.trainNo} style={s.card}>
              <Text style={s.text}>{train.terminalName} 방면 · {train.trainNo}</Text>
              <Text style={s.small}>{train.stationName} · {new Date(train.observedAt).toLocaleTimeString('ko-KR')}</Text>
              <Button label="이 열차에 탔어요" disabled={busy} onPress={() => Alert.alert('탑승 확인', `${train.terminalName} 방면 열차 ${train.trainNo}에 탑승하셨나요?`, [
                {text: '아니요', style: 'cancel'}, {text: '탑승했어요', onPress: () => {void perform(async () => setSession(await api.board(session.id, train.trainNo)));}},
              ])} />
            </View>)}
            <Button label="열차 목록 새로고침" secondary disabled={busy} onPress={() => {void perform(async () => setCandidates(await api.candidates(session.id)));}} />
          </> : <>
            <Text style={s.small}>남은 정거장 (마지막 관측 기준)</Text><Text style={s.bigNumber}>{session.remainingStops}</Text>
            <Text style={s.text}>현재 관측: {session.route[session.currentIndex]?.name ?? '정보 없음'}</Text>
            <Text style={s.small}>열차 {session.trainNo ?? '미선택'} · {session.observedAt ? new Date(session.observedAt).toLocaleTimeString('ko-KR') : '관측 대기'}</Text>
            {session.status === 'TRACKING' && !fresh && <View style={s.notice}><Text style={s.text}>새로운 위치 정보가 없습니다.</Text><Text style={s.small}>오래된 자료로 정거장을 추정하지 않습니다. 차내 안내를 함께 확인하세요.</Text></View>}
            {session.alertKind === 'LATE' && <View style={s.notice}><Text style={s.text}>목적지 도착 후 정보가 확인됐습니다. 사전 알림에 실패했을 수 있습니다.</Text></View>}
            {session.status === 'ALERTED' && <Text style={s.small}>{settings.demo ? '데모 전송 처리입니다. 실제 FCM 메시지는 발송하지 않았습니다.' : 'FCM 발송 승인 상태이며 기기의 실제 수신을 보장하지는 않습니다.'}</Text>}
          </>}
          <Button label={activeStatuses.includes(session.status) ? '추적 취소' : '확인 · 새 경로 선택'} secondary disabled={busy} onPress={() => {void perform(dismiss);}} />
        </View>
        <View style={s.card}><Text style={s.heading}>출발·도착역 안내</Text>
          {[session.route[0], session.route.at(-1)].filter((station): station is Station => !!station).map(station =>
            <Button key={station.id} label={`${station.name} 시설 정보`} secondary disabled={busy} onPress={() => facility(station)} />)}
        </View>
      </>}
      {tab === 'favorites' && <>
        <Text style={s.heading}>자주 가는 경로 · {settings.favorites.length}/5</Text>
        {!settings.favorites.length && <View style={s.card}><Text style={s.text}>아직 저장한 경로가 없습니다.</Text><Text style={s.small}>경로 화면에서 출발·도착역을 검색한 뒤 즐겨찾기에 저장하세요.</Text></View>}
        {settings.favorites.map(f => <View key={f.id} style={s.card}>
          <View style={s.row}><Text style={[s.heading, {flex: 1}]}>{f.label}</Text><Text style={s.badge}>{f.enabled ? '자동 시작' : '수동'}</Text></View>
          <Text style={s.text}>{f.origin.name} → {f.destination.name}</Text>
          <Text style={s.small}>{f.days.map(day => ['월','화','수','목','금','토','일'][day - 1]).join(' · ')} / {f.start}~{f.end}</Text>
          <Button label="이 경로 불러오기" disabled={busy || !!session} onPress={() => {setOrigin(f.origin); setDestination(f.destination); setDirection(f.direction); setTab('route');}} />
          <View style={s.row}><Button label="시간·요일 수정" secondary disabled={busy} onPress={() => setEditing(f)} />
            <Button label="삭제" secondary disabled={busy} onPress={() => Alert.alert('즐겨찾기 삭제', f.label, [
              {text: '취소', style: 'cancel'}, {text: '삭제', style: 'destructive', onPress: () => {void perform(async () => saveFavorites(settings.favorites.filter(item => item.id !== f.id)));}},
            ])} /></View>
        </View>)}
        {settings.autoError !== '' && <View style={s.notice}><Text style={s.small}>{settings.autoError}</Text></View>}
      </>}
      {tab === 'settings' && <>
        <View style={s.card}>
          <Text style={s.heading}>연결 설정</Text>
          <View style={s.row}><Text style={[s.text, {flex: 1}]}>로컬 데모 서버 사용</Text><Switch value={demoDraft} onValueChange={setDemoDraft} accessibilityLabel="데모 모드" /></View>
          <TextInput accessibilityLabel="API 서버 주소" style={s.input} value={baseDraft} onChangeText={setBaseDraft} autoCapitalize="none" autoCorrect={false} keyboardType="url" />
          <Text style={s.small}>에뮬레이터: http://10.0.2.2:8080. 실기기 adb reverse 사용 시 http://127.0.0.1:8080. 실사용은 HTTPS 서버와 Firebase 설정이 필요합니다.</Text>
          <Button label="연결 설정 저장" disabled={busy || !!session} onPress={() => {void perform(async () => {
            await NativeSubway.configure(baseDraft, demoDraft); setSettings(await readState()); setOrigin(null); setDestination(null); setReload(n => n + 1);
          });}} />
          <Text style={s.small}>서버를 바꾸면 기존 자동 시작 규칙이 비활성화됩니다. 추적 중에는 서버를 바꿀 수 없습니다.</Text>
        </View>
        <View style={s.card}><Text style={s.heading}>권한과 알림</Text>
          <Text style={s.text}>알림: {caps?.notifications ? '허용' : '확인 필요'}</Text>
          <Text style={s.text}>정확한 위치: {caps?.fineLocation ? '허용' : '미허용'} / 백그라운드: {caps?.backgroundLocation ? '허용' : '미허용'}</Text>
          <Text style={s.small}>수동 경로 추적은 위치 권한 없이 사용할 수 있습니다. 자동 시작은 별도 위치 동의가 필요합니다.</Text>
          <Button label="10초 이후 테스트 알림 예약" disabled={busy} onPress={() => {void perform(async () => {
            await requireNotifications(); await NativeSubway.demoNotification(); setCaps(await capabilities());
            Alert.alert('테스트 알림 예약', '앱을 홈 화면으로 보내거나 화면을 잠그세요. 최소 10초 뒤 알리며, Android의 작업 제한으로 늦어질 수 있습니다. 실제 열차 알림은 아닙니다.');
          });}} />
          <Button label="앱 권한·알림 설정 열기" secondary onPress={() => NativeSubway.openSettings()} />
          <Text style={s.small}>알림음과 진동은 Android 알림 채널 설정에서 변경합니다. 강제 종료·알림 차단·통신 불량·배터리 제한 상황에서는 도착 전 알림을 보장할 수 없습니다.</Text>
        </View>
      </>}
    </ScrollView>
    <View style={s.tabs}>{([{id: 'route', label: '경로·추적'}, {id: 'favorites', label: '즐겨찾기'}, {id: 'settings', label: '설정'}] as const).map(item =>
      <Pressable key={item.id} accessibilityRole="tab" accessibilityState={{selected: tab === item.id}} style={[s.tab, tab === item.id && s.activeTab]} onPress={() => setTab(item.id)}><Text style={s.text}>{item.label}</Text></Pressable>)}</View>
    <FacilitySheet detail={detail} onClose={() => setDetail(null)} />
    <FavoriteEditor favorite={editing} busy={busy} onClose={() => setEditing(null)} onSave={value => {void perform(async () => {
      const next = upsertFavorite(settings.favorites, value);
      if (value.enabled && !(await prepareAutomatic(settings.demo))) return;
      await saveFavorites(next); setEditing(null);
    });}} />
  </SafeAreaView>;
}
export default function App() { return <SafeAreaProvider><SubwayApp /></SafeAreaProvider>; }
