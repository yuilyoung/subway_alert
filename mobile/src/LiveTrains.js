import React, {useEffect, useRef, useState} from 'react';
import {ActivityIndicator, StyleSheet, Text, TextInput, TouchableOpacity, View} from 'react-native';
import MonitorPanel from './MonitorPanel';
const {fetchTrains, observationStatus, filterTrains}=require('./liveApi');
const directionLabels={INNER:'내선',OUTER:'외선'};
const stateLabels={ENTERING:'진입',ARRIVED:'도착',DEPARTED:'출발',PREVIOUS_DEPARTED:'전역 출발'};
const freshnessLabels={fresh:'최근 정보 (60초 이내)',stale:'오래된 정보 (60초 초과)',unknown:'정보 시각 확인 불가'};

export default function LiveTrains() {
  const [server,setServer]=useState(__DEV__?'http://10.0.2.2:8080':'');
  const [result,setResult]=useState(null), [error,setError]=useState(''), [selected,setSelected]=useState(null), [loading,setLoading]=useState(false), [clock,setClock]=useState(Date.now()), [query,setQuery]=useState('');
  const sequence=useRef(0);
  useEffect(()=>{
    const timer=setInterval(()=>setClock(Date.now()),15000);
    return ()=>{clearInterval(timer);sequence.current++};
  },[]);
  function changeServer(value){sequence.current++;setServer(value);setLoading(false);setResult(null);setSelected(null);setError('');}
  async function refresh(){
    const current=++sequence.current;
    setLoading(true);setError('');setResult(null);setSelected(null);
    try {const next=await fetchTrains(server,__DEV__);if(current===sequence.current){setResult(next);setClock(Date.now());}}
    catch(e){if(current===sequence.current)setError(e.message || '서버 연결을 확인하세요.');}
    finally {if(current===sequence.current)setLoading(false);}
  }
  return <View>
    <Text style={styles.heading}>4. 열차 정보 조회 (시험 기능)</Text>
    <Text style={styles.help}>서울 2호선의 서버 조회 결과를 확인합니다. 열차 선택은 조회용이며 탑승을 확인하거나 하차 알림과 연결하지 않습니다.</Text>
    <Text style={styles.help}>서버 주소: HTTPS 사용. Metro 개발 모드에서 Android 에뮬레이터의 PC 서버는 http://10.0.2.2:8080, USB 연결 기기는 adb reverse 후 http://127.0.0.1:8080을 사용할 수 있습니다. 실제 기기의 HTTPS 서버 연결은 별도 설정이 필요합니다.</Text>
    <TextInput accessibilityLabel="열차 조회 서버 주소" style={styles.input} autoCapitalize="none" autoCorrect={false} value={server} onChangeText={changeServer} placeholder="https://서버주소" />
    <TouchableOpacity style={styles.button} accessibilityRole="button" disabled={loading} onPress={refresh}><Text style={styles.buttonText}>{loading?'조회 중…':'2호선 열차 조회'}</Text></TouchableOpacity>
    {loading && <ActivityIndicator accessibilityLabel="열차 조회 중" />}
    {!!error && <Text accessibilityRole="alert" style={styles.error}>조회 실패: {error}</Text>}
    {result && <View>
      <Text style={styles.source}>{result.mode==='SAMPLE'?'서울시 공개 샘플 · 최대 5건 · 서버↔서울 API 평문 전송':'서울시 실시간 데이터 · 서버 제공'}</Text>
      <Text style={styles.help}>표시 시각의 시간대는 서울시 응답을 기준으로 추정했으며 현장 확인이 필요합니다. 위치는 지연되거나 부정확할 수 있습니다.</Text>
      {!!result.warning && <Text style={styles.warning}>{result.warning}</Text>}
      {!result.trains.length && <Text style={styles.help}>조회된 열차가 없습니다.</Text>}
      {result.trains.length>0 && <TextInput accessibilityLabel="열차번호 또는 역 검색" style={styles.input} value={query} onChangeText={setQuery} placeholder="열차번호 또는 역 검색" />}
      {filterTrains(result.trains,query).length>100 && <Text style={styles.help}>검색 결과 중 처음 100건만 표시합니다. 열차번호 또는 역을 입력해 좁혀 주세요.</Text>}
      {filterTrains(result.trains,query).slice(0,100).map((train,index)=>{
        const freshness=observationStatus(train.observedAt,clock);
        const stamp=train.observedAt && Number.isFinite(Date.parse(train.observedAt)) ? new Date(train.observedAt).toLocaleString() : '확인 불가';
        const isSelected=selected===train;
        return <TouchableOpacity accessibilityRole="button" accessibilityState={{selected:isSelected}} key={`${train.lineId}-${train.trainId}-${index}`} style={[styles.card,isSelected&&styles.selected]} onPress={()=>setSelected(train)}>
          <Text style={styles.bold}>{train.trainId} 열차 · {directionLabels[train.direction] || train.direction}</Text>
          <Text>{train.station} · {stateLabels[train.state] || train.state}{train.express===true?' · 급행':train.express===false?' · 일반':''}</Text>
          <Text>정보 시각: {stamp}</Text><Text style={freshness==='fresh'?styles.help:styles.warning}>{freshnessLabels[freshness]}</Text>
          {isSelected && <Text style={styles.selectedText}>조회용 선택 · 하차 알림은 설정되지 않았습니다</Text>}
        </TouchableOpacity>;
      })}
    </View>}
    <MonitorPanel server={server} train={selected} sourceMode={result?.mode} />
  </View>;
}
const styles=StyleSheet.create({heading:{fontSize:19,fontWeight:'700',marginTop:24,marginBottom:12,color:'#172b50'},help:{fontSize:12,lineHeight:18,color:'#5a6780',marginVertical:5},input:{backgroundColor:'white',borderColor:'#cbd4e5',borderWidth:1,borderRadius:8,padding:12,marginVertical:8},button:{backgroundColor:'#2854d5',padding:11,borderRadius:8,alignItems:'center'},buttonText:{color:'white',fontWeight:'700'},source:{fontWeight:'700',color:'#273e70',marginTop:12},error:{color:'#a32424',marginTop:8},warning:{color:'#8b5900',lineHeight:19,marginVertical:4},card:{backgroundColor:'white',borderRadius:8,padding:12,marginTop:8,gap:4,borderWidth:1,borderColor:'#e0e5ef'},selected:{borderColor:'#2854d5',borderWidth:2},bold:{fontWeight:'700'},selectedText:{color:'#2854d5',fontWeight:'700'}});
