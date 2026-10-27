import React, {useEffect, useState} from 'react';
import {Alert, AppState, SafeAreaView, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View} from 'react-native';
import * as Notifications from 'expo-notifications';
import LiveTrains from './src/LiveTrains';
import {readState,writeState,enableMonitoring,disableMonitoring,requestNotificationPermissions} from './src/background';
const stations=require('./src/stations');
const {addFavorite,findRoute}=require('./src/domain');
Notifications.setNotificationHandler({handleNotification:async()=>({shouldShowBanner:true,shouldShowList:true,shouldPlaySound:true,shouldSetBadge:false})});
const defaults={favorites:[],automation:false,active:null};
const name=id=>stations.find(s=>s.id===id)?.name || '역 선택';
function Btn({label,onPress,secondary}) {return <TouchableOpacity onPress={onPress} style={[styles.button,secondary&&styles.secondary]}><Text style={[styles.buttonText,secondary&&styles.secondaryText]}>{label}</Text></TouchableOpacity>}
export default function App(){
 const [state,setState]=useState(defaults), [from,setFrom]=useState(''),[to,setTo]=useState(''),[query,setQuery]=useState(''),[select,setSelect]=useState('from'),[start,setStart]=useState('07:00'),[end,setEnd]=useState('09:00'),[ready,setReady]=useState(false),[busy,setBusy]=useState(false);
 const route=findRoute(stations,from,to);
 async function reload(){let s=await readState();setState({...defaults,...s});setReady(true)}
 useEffect(()=>{reload(); const sub=AppState.addEventListener('change',v=>{if(v==='active') reload()});return ()=>sub.remove()},[]);
 async function update(fn){const current={...defaults,...await readState()};const next=fn(current);await writeState(next);setState(next)}
 async function run(fn){if(!ready||busy)return;setBusy(true);try{await fn()}catch(e){Alert.alert('확인',e.message || '처리 중 오류가 발생했습니다.')}finally{setBusy(false)}}
 const validate=()=>{if(!route)throw Error('서로 다른 출발역과 도착역을 선택하세요.');};
 async function begin(){return run(async()=>{
  validate();
  if(route.count===1){
   await update(s=>({...s,active:null}));
   if(!state.automation) await disableMonitoring();
   await requestNotificationPermissions();
   await Notifications.scheduleNotificationAsync({content:{title:'한 정거장 경로 (데모)',body:`현재 출발역이 ${route.to.name}의 이전 역입니다. 실제 안내방송을 확인하세요.`,sound:true},trigger:null});
   Alert.alert('한 정거장 경로','출발역이 이미 도착역의 이전 역입니다. 감시를 종료하고 데모 알림을 표시합니다.'); return;
  }
  await enableMonitoring();await update(s=>({...s,active:{id:`${Date.now()}-${Math.random()}`,from,to}}));
  Alert.alert('감시 시작 (데모)','상태 표시줄의 위치 서비스 알림을 유지합니다. GPS와 샘플 좌표가 실제 열차를 확인하지 못하므로 실제 하차에 의존하지 마세요.');
 })}
 async function stop(){return run(async()=>{await update(s=>({...s,active:null,automation:false}));await disableMonitoring();})}
 async function saveFavorite(){return run(async()=>{validate();if(!/^([01]\d|2[0-3]):[0-5]\d$/.test(start)||!/^([01]\d|2[0-3]):[0-5]\d$/.test(end)||start===end)throw Error('시간은 HH:MM 형식이며 시작과 종료가 달라야 합니다.');await update(s=>({...s,favorites:addFavorite(s.favorites,{id:String(Date.now()),from,to,enabled:true,schedule:{days:[1,2,3,4,5],start,end}})}));})}
 async function toggleAuto(){return run(async()=>{if(!state.automation){if(!state.favorites.length)throw Error('먼저 즐겨찾기를 등록하세요.');await enableMonitoring();await update(s=>({...s,automation:true}));Alert.alert('출퇴근 감시 시작 (데모)','사용자가 앱을 연 상태에서 서비스가 시작됩니다. 지정한 평일 시간에 출발역 근처를 감지하면 자동 탑승 확인 알림을 보냅니다. 앱에서 직접 감시를 시작해야 합니다.');}else {await update(s=>({...s,automation:false}));if(!state.active)await disableMonitoring();}})}
 return <SafeAreaView style={styles.screen}><ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
 <Text style={styles.title}>지하철 하차 알림</Text><Text style={styles.subtitle}>화면이 꺼져도 경로를 감시하는 Android 데모</Text>
 <View style={styles.warning}><Text style={styles.warningText}>데모 전용 · 서울 2호선 일부 5개 역과 검증되지 않은 대략 좌표입니다. 지하 GPS는 끊길 수 있으며 열차 조회와 알림이 연결되지 않아 실제 하차 알림으로 사용하지 마세요.</Text></View>
 <Text style={styles.heading}>1. 출발역과 도착역</Text>
 <View style={styles.row}><Btn secondary={select!=='from'} label={`출발  ${name(from)}`} onPress={()=>setSelect('from')}/><Btn secondary={select!=='to'} label={`도착  ${name(to)}`} onPress={()=>setSelect('to')}/></View>
 <TextInput style={styles.input} value={query} onChangeText={setQuery} placeholder={`${select==='from'?'출발역':'도착역'} 검색`} />
 {stations.filter(s=>s.name.includes(query.trim())).map(s=><TouchableOpacity key={s.id} style={styles.station} onPress={()=>{select==='from'?setFrom(s.id):setTo(s.id);setQuery('');if(select==='from')setSelect('to')}}><Text>{s.name} · {s.line}</Text></TouchableOpacity>)}
 {route&&<Text style={styles.info}>{route.from.name} → {route.to.name} · {route.count}정거장 · 이전 역 {route.previous.name}</Text>}
 <View style={styles.row}><Btn label="감시 시작" onPress={begin}/><Btn secondary label="전체 감시 중지" onPress={stop}/></View>
 <Text style={styles.status}>{state.active?`감시 중: ${name(state.active.from)} → ${name(state.active.to)}`:'현재 진행 중인 경로 없음'}</Text>
 <Text style={styles.heading}>2. 출퇴근 즐겨찾기 ({state.favorites.length}/5)</Text>
 <Text>평일 자동 감지 시간 (기기 현지 시간)</Text><View style={styles.row}><TextInput style={[styles.input,styles.time]} value={start} onChangeText={setStart} placeholder="07:00"/><Text>~</Text><TextInput style={[styles.input,styles.time]} value={end} onChangeText={setEnd} placeholder="09:00"/></View>
 <Btn secondary label="선택 경로 즐겨찾기에 추가" onPress={saveFavorite}/>
 {state.favorites.map(f=><View key={f.id} style={styles.card}><Text style={styles.bold}>{name(f.from)} → {name(f.to)}</Text><Text>평일 {f.schedule.start}–{f.schedule.end} · {f.enabled?'자동 감지 사용':'자동 감지 꺼짐'}</Text><View style={styles.row}><Btn secondary label="선택" onPress={()=>{setFrom(f.from);setTo(f.to)}}/><Btn secondary label={f.enabled?'자동 끄기':'자동 켜기'} onPress={()=>run(()=>update(s=>({...s,favorites:s.favorites.map(x=>x.id===f.id?{...x,enabled:!x.enabled}:x)})))}/><Btn secondary label="삭제" onPress={()=>run(()=>update(s=>({...s,favorites:s.favorites.filter(x=>x.id!==f.id)})))}/></View></View>)}
 <Btn label={state.automation?'출퇴근 감지 알림 끄기':'출퇴근 감지 알림 켜기'} onPress={toggleAuto}/><Text style={styles.small}>앱에서 감시를 켜야 작동하며 상시 위치 알림이 표시됩니다. 재부팅·강제 종료·절전 정책 및 위치 신호에 따라 중단되거나 지연될 수 있습니다.</Text>
 <Text style={styles.heading}>3. 역 안내</Text>
 {[{id:from,label:'출발'},{id:to,label:'도착'}].filter(x=>x.id).map(({id,label})=><View key={label+id} style={styles.card}><Text style={styles.bold}>{label} · {name(id)}</Text><Text>빠른 환승 · 화장실 · 편의시설 · 개찰구 · 출구: 확인된 정보 없음</Text></View>)}
 <Text style={styles.small}>역 시설 정보는 연결되지 않았습니다. 출발역과 목적지는 이 데모의 5개 역에서만 검색할 수 있습니다.</Text>
 <LiveTrains />
 </ScrollView></SafeAreaView>
}
const styles=StyleSheet.create({screen:{flex:1,backgroundColor:'#f5f7fc'},content:{padding:20,paddingBottom:50},title:{fontSize:28,fontWeight:'800',color:'#132344'},subtitle:{color:'#53627c',marginVertical:8},heading:{fontSize:19,fontWeight:'700',marginTop:24,marginBottom:12,color:'#172b50'},warning:{backgroundColor:'#fff0cf',padding:14,borderRadius:10,marginTop:12},warningText:{color:'#744b00',lineHeight:21},row:{flexDirection:'row',alignItems:'center',gap:8,marginVertical:6,flexWrap:'wrap'},button:{backgroundColor:'#2854d5',paddingHorizontal:13,paddingVertical:11,borderRadius:8,alignItems:'center'},secondary:{backgroundColor:'#e5eaf7'},buttonText:{color:'white',fontWeight:'700'},secondaryText:{color:'#273e70'},input:{backgroundColor:'white',borderColor:'#cbd4e5',borderWidth:1,borderRadius:8,padding:12,marginVertical:8},time:{minWidth:90},station:{padding:12,borderBottomWidth:1,borderColor:'#e0e5ef',backgroundColor:'white'},info:{color:'#2854d5',marginVertical:10},status:{marginVertical:8,color:'#4d607c'},card:{backgroundColor:'white',borderRadius:10,padding:14,marginVertical:6,gap:5},bold:{fontWeight:'700'},small:{color:'#5a6780',fontSize:12,lineHeight:18,marginTop:8}});
