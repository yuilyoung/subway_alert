import React, {useEffect, useRef, useState} from 'react';
import {Alert, Platform, StyleSheet, Text, TextInput, TouchableOpacity, View} from 'react-native';
import * as Notifications from 'expo-notifications';
import * as SecureStore from 'expo-secure-store';
import * as Crypto from 'expo-crypto';
import {fetch as expoFetch} from 'expo/fetch';
const {monitorRequest,validateSelection,needsRegistration}=require('./monitorApi');
const {sessionAccessToken}=require('./connectionStore');
const {createRegistrationFlow}=require('./registrationFlow');
const statusLabels={TRACKING:'시험 감시 중',SAMPLE_MATCHED:'공개 샘플 조건 일치 · 실제 하차 아님',CANCELLED:'종료됨',EXPIRED:'만료됨'};
const delivery={NONE:'아직 전송 요청 없음',SENDING:'시험 알림 전송 중',UNKNOWN:'서버 재시작으로 이전 전송 결과를 알 수 없음 · 자동 재전송하지 않음',FCM_ACCEPTED:'FCM 서버가 전송 요청을 수락함 · 기기 수신은 미확인',UNAVAILABLE:'FCM 서버 설정이 없어 전송할 수 없음',FAILED:'시험 알림 전송 실패'};
const polling={NOT_POLLED:'아직 열차 조회 전',SAMPLE_PARTIAL:'공개 샘플 일부를 조회 중',SOURCE_BLOCKED:'해당 데이터 소스는 차단됨',PROVIDER_ERROR:'열차 API 조회 오류',DAILY_LIMIT:'API 조회 한도에 도달함'};
async function deviceToken(){
 if(Platform.OS!=='android')throw new Error('Android 기기에서만 FCM 시험을 지원합니다.');
 await Notifications.setNotificationChannelAsync('subway-alerts',{name:'시험 알림',importance:Notifications.AndroidImportance.HIGH,vibrationPattern:[0,500,250,500]});
 let permission=await Notifications.getPermissionsAsync();
 if(!permission.granted)permission=await Notifications.requestPermissionsAsync();
 if(!permission.granted)throw new Error('Android 알림 권한이 필요합니다.');
 try {
  const value=await Notifications.getDevicePushTokenAsync();
  if(value?.type!=='android'||typeof value.data!=='string'||!value.data.trim())throw new Error('invalid');
  return value.data;
 } catch (_) {throw new Error('FCM 토큰을 얻지 못했습니다. Firebase 설정이 포함된 Android 빌드와 Google Play 서비스 연결을 확인하세요.');}
}
function Button({title,onPress,disabled}){return <TouchableOpacity disabled={disabled} accessibilityRole="button" onPress={onPress} style={[styles.button,disabled&&styles.disabled]}><Text style={styles.buttonText}>{title}</Text></TouchableOpacity>}
export default function MonitorPanel({connection,train,sourceMode}){
 const [previous,setPrevious]=useState(''),[destination,setDestination]=useState('');
 const [session,setSession]=useState(null),[view,setView]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[ready,setReady]=useState(false),[tokenChanged,setTokenChanged]=useState(false),[storageBlocked,setStorageBlocked]=useState(false);
 const lock=useRef(false),tokenRef=useRef(null),sessionRef=useRef(null),latestEvent=useRef(null),autoCancelAttempt=useRef(null),connectionRef=useRef(connection);
 const flowRef=useRef(null);
 if(!flowRef.current)flowRef.current=createRegistrationFlow({secureStore:SecureStore,crypto:Crypto,fetchImpl:expoFetch,development:__DEV__,onChange:state=>{sessionRef.current=state.record;setSession(state.record);setReady(state.ready);setStorageBlocked(state.blocked);}});
 const flow=flowRef.current;
 connectionRef.current=connection;
 useEffect(()=>{
  let alive=true;
  (async()=>{try{const restored=await flow.restore();if(alive&&restored)setTokenChanged(needsRegistration(restored,null,null));}catch(e){if(alive)setError(e.message);}})();
  const subscription=Notifications.addPushTokenListener(next=>{
    if(typeof next?.data!=='string')return;
    latestEvent.current=next.data;
    if(!sessionRef.current)return;
    if(needsRegistration(sessionRef.current,tokenRef.current,next.data)){tokenRef.current=null;setTokenChanged(true);}
  });
  return ()=>{alive=false;subscription.remove()};
 },[]);
 async function run(fn){if(!ready||lock.current)return;lock.current=true;setBusy(true);setError('');try{await fn()}catch(e){setError(e?.message||'시험 감시 처리에 실패했습니다.')}finally{lock.current=false;setBusy(false)}}
 useEffect(()=>{
  if(!ready||busy||storageBlocked||!tokenChanged||!session)return;
  if(autoCancelAttempt.current?.id===session.id&&autoCancelAttempt.current?.connection===connection)return;
  const current=session,currentConnection=connection;autoCancelAttempt.current={id:current.id,connection:currentConnection};
  run(async()=>{
   try{
    await flow.cancel(currentConnection);
    if(!sessionRef.current||sessionRef.current.id===current.id){sessionRef.current=null;setSession(null);tokenRef.current=null;setTokenChanged(false);setView(null);setError('토큰을 확인할 수 없어 기존 시험 감시를 자동 종료했습니다. 다시 등록해 주세요.');}
   }catch(_){throw new Error('기기 토큰을 확인할 수 없어 기존 시험 감시 종료를 시도했지만 확인하지 못했습니다. 기존 토큰으로 시험 알림이 전송될 수 있습니다. 등록한 서버의 연결 주소와 API 키를 확인한 뒤 종료를 다시 시도하세요. 종료를 확인하지 못한 세션은 최대 2시간 후 만료됩니다.');}
  });
 },[ready,busy,storageBlocked,tokenChanged,session?.id,connection]);
 async function register(confirmedConnection){return run(async()=>{
  if(sessionRef.current)throw new Error('기존 시험 감시를 먼저 종료하세요.');
  const currentConnection=connectionRef.current;
  if(!currentConnection)throw new Error('서버 주소와 API 키를 먼저 저장해 주세요.');
  if(sourceMode!=='SAMPLE')throw new Error('현재 시험 감시는 공개 샘플 열차만 사용합니다.');
  validateSelection(train,previous,destination);
  latestEvent.current=null;setView(null);
  try{
   const {created,fcmToken:token}=await flow.start(confirmedConnection,()=>connectionRef.current,{train,previousStation:previous,destinationStation:destination},async()=>{const value=await deviceToken();tokenRef.current=value;return value;});
   tokenRef.current=token;setView({status:created.status,deliveryStatus:created.status==='TRACKING'?'NONE':undefined,pollStatus:created.status==='TRACKING'?'NOT_POLLED':undefined,expiresAt:created.expiresAt});
  }finally{if(sessionRef.current)setTokenChanged(needsRegistration(sessionRef.current,tokenRef.current,latestEvent.current||tokenRef.current));}
 })}
 function confirmRegister(){
  const confirmedConnection=connectionRef.current;
  try{if(!connectionRef.current)throw new Error('서버 주소와 API 키를 먼저 저장해 주세요.');if(sourceMode!=='SAMPLE')throw new Error('공개 샘플 열차를 먼저 선택해 주세요.');validateSelection(train,previous,destination);}
  catch(e){setError(e.message);return;}
  Alert.alert('시험 감시 확인',`${train.trainId} 열차 (${train.direction==='INNER'?'내선':'외선'})\n이전역: ${previous.trim()}\n도착역: ${destination.trim()}\n\n샘플 기반 시험입니다. 실제 하차 알림으로 사용하지 마세요.`,[{text:'취소',style:'cancel'},{text:'시험 시작',onPress:()=>register(confirmedConnection)}]);
 }
 async function action(type){return run(async()=>{
  const current=sessionRef.current;if(!current)throw new Error('진행 중인 시험 감시가 없습니다.');
  if(type==='test'&&tokenChanged)throw new Error('기기 토큰이 바뀌었습니다. 기존 감시를 종료하고 다시 시작하세요.');
  if(type==='retry'&&tokenChanged)throw new Error('기기 토큰이 바뀌었거나 확인되지 않습니다. 기존 감시를 종료하고 다시 시작하세요.');
  if(type==='test'&&current.phase==='PENDING')throw new Error('등록 결과를 먼저 조회해 주세요.');
  const result=type==='cancel'?await flow.cancel(connectionRef.current):type==='retry'?await flow.retry(connectionRef.current):type==='status'?await flow.status(connectionRef.current):await monitorRequest(current.server,current,type,__DEV__,expoFetch,sessionAccessToken(current,connectionRef.current,__DEV__));setView(result);
  if(type==='cancel'){sessionRef.current=null;setSession(null);tokenRef.current=null;setTokenChanged(false);
  }
 })}

 return <View style={styles.panel}>
  <Text style={styles.heading}>5. FCM 시험 알림</Text>
  <Text style={styles.warning}>시험 전용 · 샘플 정보로 동작합니다. 실제 하차 알림과 다르며 서울시 전체 열차를 추적하지 않습니다. 종료 직전에 전송된 시험 알림은 종료 후 도착할 수 있습니다.</Text>
  <Text style={styles.help}>Firebase 설정을 포함하여 앱을 다시 빌드해야 합니다. 서버의 FCM 설정도 필요합니다. 이전역과 도착역은 사용자 입력이며 실제 경로가 검증되지 않습니다.</Text>
  {!session&&<>{!connection&&<Text style={styles.help}>서버 주소와 API 키를 먼저 저장한 뒤 공개 샘플 열차를 선택해 주세요.</Text>}<TextInput accessibilityLabel="시험 이전역" style={styles.input} value={previous} onChangeText={setPrevious} placeholder="목적지 이전역 입력"/><TextInput accessibilityLabel="시험 도착역" style={styles.input} value={destination} onChangeText={setDestination} placeholder="목적지 입력"/><Button title="선택 열차로 시험 감시 시작" disabled={!ready||busy||storageBlocked||!connection||!train||sourceMode!=='SAMPLE'} onPress={confirmRegister}/></>}
  {storageBlocked&&<><Text style={styles.warning}>저장된 감시 정보를 읽지 못해 새 등록을 차단했습니다. 저장된 정보를 복원하기 전에는 다른 감시를 시작할 수 없습니다.</Text><Button title="저장된 감시 다시 읽기" disabled={busy} onPress={()=>run(async()=>{const restored=await flow.restore();if(restored)setTokenChanged(true);})}/></>}
  {session&&<><Text style={styles.help}>새 시험 감시는 서버 주소·API 키·세션 토큰을 함께 안전하게 저장합니다. 서버 주소를 바꿔도 등록한 서버로만 조회·종료합니다. API 키가 없는 이전 세션이나 키를 교체한 세션은 같은 서버의 API 키를 저장해 주세요.</Text><Text style={styles.help}>상태: {statusLabels[view?.status]||'조회 필요'} · 만료: {view?.expiresAt||(typeof session.expiresAt==='string'&&session.expiresAt)||'확인 불가'}</Text><Text style={styles.help}>전송: {delivery[view?.deliveryStatus]||'조회 필요'}</Text><Text style={styles.help}>조회: {polling[view?.pollStatus]||'조회 필요'}</Text><Text style={styles.warning}>API 키가 회수되었거나 조회·종료에 실패하면 등록한 서버의 연결 주소와 API 키를 확인하세요. 종료 확인 전까지 저장된 감시 정보는 유지됩니다. 세션은 최대 2시간 후 만료됩니다.</Text>{tokenChanged&&<Text style={styles.warning}>기기 토큰 확인이 필요해 기존 감시를 자동 종료하려고 합니다. 종료 실패 시 기존 토큰으로 시험 알림이 전송될 수 있으니 서버 연결과 API 키를 확인하고 종료를 다시 시도하세요.</Text>}{session.phase==='PENDING'&&<><Text style={styles.warning}>등록 결과 확인 대기 중입니다. 같은 ID·비밀·원래 요청을 보관하며 새 감시 등록을 차단합니다. 결과 조회 또는 종료는 계속 가능하며, 같은 요청 재시도는 원래 열차 관측 후 60초 이내에만 가능합니다. 재시도에도 서버 요청 한도가 적용됩니다.</Text><Button title="같은 등록 요청 재시도" disabled={busy||storageBlocked||tokenChanged} onPress={()=>action('retry')}/></>}<Button title={session.phase==='PENDING'?'등록 결과 조회':'상태 새로고침'} disabled={busy||storageBlocked} onPress={()=>action('status')}/><Button title="시험 알림 보내기" disabled={busy||storageBlocked||tokenChanged||session.phase==='PENDING'} onPress={()=>action('test')}/><Button title="시험 감시 종료" disabled={busy||storageBlocked} onPress={()=>action('cancel')}/></>}
  {!!error&&<Text accessibilityRole="alert" style={styles.error}>{error}</Text>}
 </View>;
}
const styles=StyleSheet.create({panel:{marginTop:24,padding:12,backgroundColor:'#fff8e7',borderRadius:10},heading:{fontSize:18,fontWeight:'700',color:'#172b50'},help:{fontSize:12,lineHeight:18,color:'#5a6780',marginVertical:5},warning:{color:'#8b5900',lineHeight:19,marginVertical:4},error:{color:'#a32424',marginTop:8},input:{backgroundColor:'white',borderColor:'#cbd4e5',borderWidth:1,borderRadius:8,padding:12,marginVertical:8},button:{backgroundColor:'#2854d5',padding:10,borderRadius:8,alignItems:'center',marginTop:7},disabled:{opacity:0.4},buttonText:{color:'white',fontWeight:'700'}});
