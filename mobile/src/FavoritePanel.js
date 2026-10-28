import React, {useState} from 'react';
import {Alert,StyleSheet,Text,TextInput,TouchableOpacity,View} from 'react-native';
import * as Crypto from 'expo-crypto';
const stations=require('./stations');
const {findRoute}=require('./domain');
const {formatSchedule,normalizeSchedule}=require('./commute');
const {saveFavoriteDraft}=require('./favoriteActions');
const WEEKDAYS=[{day:1,name:'월'},{day:2,name:'화'},{day:3,name:'수'},{day:4,name:'목'},{day:5,name:'금'},{day:6,name:'토'},{day:0,name:'일'}];
const DEFAULT_DAYS=[1,2,3,4,5];
const stationName=id=>stations.find(s=>s.id===id)?.name||'확인되지 않은 역';
function Button({label,onPress,disabled}){
 return <TouchableOpacity accessibilityRole="button" disabled={disabled} onPress={onPress} style={[styles.button,disabled&&styles.disabled]}><Text style={styles.buttonText}>{label}</Text></TouchableOpacity>;
}

export default function FavoritePanel({favorites,route,disabled,run,onSelect,onUpdate,onSaved,readState,writeState}){
 const [editing,setEditing]=useState(null),[days,setDays]=useState(DEFAULT_DAYS),[start,setStart]=useState('07:00'),[end,setEnd]=useState('09:00');
 const selected=editing?findRoute(stations,editing.from,editing.to):route;
 function reset(){setEditing(null);setDays([...DEFAULT_DAYS]);setStart('07:00');setEnd('09:00');}
 function edit(favorite){
  let schedule;
  try{schedule=normalizeSchedule(favorite.schedule);}
  catch(_){schedule={days:[...DEFAULT_DAYS],start:'07:00',end:'09:00'};Alert.alert('시간 조건 확인','저장된 시간 조건을 읽을 수 없어 기본값을 표시합니다. 확인 후 저장해 주세요.');}
  setEditing({id:favorite.id,from:favorite.from,to:favorite.to});
  setDays([...schedule.days]);setStart(schedule.start);setEnd(schedule.end);
 }
 async function save(){return run(async()=>{
  if(!selected)throw Error('서로 다른 출발역과 도착역을 먼저 선택하세요.');
  const next=await saveFavoriteDraft({readState,writeState,createId:()=>Crypto.randomUUID()},
   {from:selected.from.id,to:selected.to.id,schedule:{days,start,end}},editing?.id??null);
  onSaved(next);reset();
 });}
 async function remove(id){return run(async()=>{
  await onUpdate(s=>({...s,favorites:s.favorites.filter(f=>f.id!==id)}));
  if(editing?.id===id)reset();
 });}
 return <>
  <Text style={styles.heading}>2. 출퇴근 즐겨찾기 ({favorites.length}/5)</Text>
  <View style={styles.card}>
   <Text style={styles.bold}>{editing?'출퇴근 조건 수정':'새 즐겨찾기 조건'}</Text>
   <Text>{selected?`${selected.from.name} → ${selected.to.name}`:'위에서 출발역과 도착역을 선택하세요.'}</Text>
   <Text style={styles.help}>{editing?'저장 전에는 기존 감지 조건이 유지됩니다.':'기본값은 월~금 07:00–09:00입니다.'}</Text>
   <View style={styles.row}>{WEEKDAYS.map(({day,name})=><TouchableOpacity key={day} accessibilityRole="checkbox" accessibilityLabel={`${name}요일`} accessibilityState={{checked:days.includes(day),disabled}} disabled={disabled} onPress={()=>setDays(previous=>previous.includes(day)?previous.filter(value=>value!==day):[...previous,day])} style={[styles.day,days.includes(day)&&styles.selectedDay,disabled&&styles.disabled]}><Text style={days.includes(day)?styles.selectedDayText:styles.dayText}>{name}</Text></TouchableOpacity>)}</View>
   <Text>감지 시간 · 기기 현지 시간</Text>
   <View style={styles.row}><TextInput accessibilityLabel="출퇴근 시작 시간" style={styles.input} editable={!disabled} value={start} onChangeText={setStart} maxLength={5} placeholder="07:00"/><Text>~</Text><TextInput accessibilityLabel="출퇴근 종료 시간" style={styles.input} editable={!disabled} value={end} onChangeText={setEnd} maxLength={5} placeholder="09:00"/></View>
   <Text style={styles.help}>종료 시각이 시작보다 빠르면 다음 날까지입니다. 예: 일요일 23:00–01:00은 월요일 새벽까지 감지합니다. 종료 시각은 포함하지 않습니다.</Text>
   <View style={styles.row}><Button label={editing?'조건 수정 저장':'선택 경로 즐겨찾기에 추가'} disabled={disabled} onPress={save}/>{editing&&<Button label="수정 취소" disabled={disabled} onPress={reset}/>}</View>
  </View>
  {favorites.map(f=><View key={f.id} style={styles.card}>
   <Text style={styles.bold}>{stationName(f.from)} → {stationName(f.to)}</Text>
   <Text>{formatSchedule(f.schedule)} · {f.enabled?'자동 감지 사용':'자동 감지 꺼짐'}</Text>
   <View style={styles.row}>
    <Button label="선택" disabled={disabled} onPress={()=>onSelect(f)}/>
    <Button label="요일·시간 수정" disabled={disabled} onPress={()=>edit(f)}/>
    <Button label={f.enabled?'자동 끄기':'자동 켜기'} disabled={disabled} onPress={()=>run(()=>onUpdate(s=>({...s,favorites:s.favorites.map(x=>x.id===f.id?{...x,enabled:!x.enabled}:x)})))}/>
    <Button label="삭제" disabled={disabled} onPress={()=>remove(f.id)}/>
   </View>
  </View>)}
 </>;
}
const styles=StyleSheet.create({heading:{fontSize:19,fontWeight:'700',marginTop:24,marginBottom:12,color:'#172b50'},card:{backgroundColor:'white',borderRadius:10,padding:14,marginVertical:6,gap:6},bold:{fontWeight:'700'},row:{flexDirection:'row',alignItems:'center',gap:8,marginVertical:6,flexWrap:'wrap'},button:{backgroundColor:'#e5eaf7',paddingHorizontal:12,paddingVertical:11,borderRadius:8},buttonText:{color:'#273e70',fontWeight:'700'},disabled:{opacity:0.5},day:{borderWidth:1,borderColor:'#cbd4e5',padding:11,borderRadius:8,minWidth:40,alignItems:'center'},selectedDay:{backgroundColor:'#2854d5',borderColor:'#2854d5'},dayText:{color:'#273e70'},selectedDayText:{color:'white',fontWeight:'700'},input:{minWidth:90,backgroundColor:'white',borderColor:'#cbd4e5',borderWidth:1,borderRadius:8,padding:12},help:{fontSize:12,color:'#5a6780',lineHeight:18}});
