const {validateServerUrl,validateAccessToken}=require('./apiAccess');
const {startMonitor,startConfirmedMonitor,monitorRequest,cancelStaleSession,UUID4,SECRET,validTime}=require('./monitorApi');
const {observationStatus}=require('./liveApi');
const {sessionAccessToken}=require('./connectionStore');
const KEY='subway-monitor-session-v1';
const STORAGE_ERROR='저장된 시험 감시 정보를 안전하게 읽지 못했습니다. 새 등록을 차단했습니다. 저장 상태를 다시 확인해 주세요.';
const BODY_KEYS=['lineId','trainId','direction','previousStation','destinationStation','fcmToken','mode'];

function validRequest(body){
 const station=value=>typeof value==='string'&&value.length>0&&value===value.trim()&&value.length<=40;
 return body&&typeof body==='object'&&Object.keys(body).length===7&&BODY_KEYS.every(key=>Object.hasOwn(body,key))&&body.lineId==='2'&&body.mode==='TEST'&&
  typeof body.trainId==='string'&&body.trainId.trim().length>0&&body.trainId.length<=64&&['INNER','OUTER'].includes(body.direction)&&
  station(body.previousStation)&&station(body.destinationStation)&&body.previousStation!==body.destinationStation&&
  typeof body.fcmToken==='string'&&body.fcmToken.trim().length>0&&body.fcmToken.length<=4096;
}
function validateStored(value,development){
 if(!value||typeof value!=='object'||Array.isArray(value))throw Error();
 const server=validateServerUrl(value.server,development);
 const legacy=value.phase==null;
 if(!UUID4.test(value.id||'')||typeof value.sessionToken!=='string'||!(legacy?/^[A-Za-z0-9_-]{1,512}$/:SECRET).test(value.sessionToken))throw Error();
 if(!legacy&&!['PENDING','ACTIVE'].includes(value.phase))throw Error();
 const phase=legacy?'ACTIVE':value.phase;
 const accessToken=value.accessToken==null&&legacy?undefined:validateAccessToken(value.accessToken);
 const record={phase,id:value.id,sessionToken:value.sessionToken,server,...(accessToken?{accessToken}:{})};
 if(phase==='PENDING'){
  if(!validRequest(value.request)||!validTime(value.observedAt))throw Error();
  record.request=Object.freeze({...value.request});record.observedAt=value.observedAt;
 }else{
  if(!legacy&&!validTime(value.expiresAt))throw Error();
  if(value.expiresAt!=null){if(!validTime(value.expiresAt))throw Error();record.expiresAt=value.expiresAt;}
 }
 return Object.freeze(record);
}

// The storage and native boundaries are injected so recovery can be tested without
// claiming that Node tests exercise an Android keystore or Firebase installation.
function createRegistrationFlow({secureStore,crypto,fetchImpl,development=false,now=()=>Date.now(),onChange=()=>{}}){
 let record=null,ready=false,blocked=false,locked=false;
 const getState=()=>({record,ready,blocked});
 function publish(){onChange(getState());}
 function requireReady(){if(!ready||blocked)throw new Error(STORAGE_ERROR);}
 function current(){requireReady();if(!record)throw new Error('진행 중인 시험 감시가 없습니다.');return record;}
 async function exclusive(operation){
  if(locked)throw new Error('시험 감시 작업을 처리 중입니다.');
  locked=true;try{return await operation();}finally{locked=false;}
 }
 async function save(value){
  try{await secureStore.setItemAsync(KEY,JSON.stringify(value));}
  catch(_){throw new Error('감시 복구 정보를 안전하게 저장하지 못했습니다. 저장된 등록 결과를 조회하거나 종료해 주세요.');}
  record=Object.freeze(value);publish();
 }
 async function activate(value){
  const active={phase:'ACTIVE',id:record.id,sessionToken:record.sessionToken,server:record.server,accessToken:record.accessToken,expiresAt:value.expiresAt};
  await save(active);return value;
 }
 function replaySelection(saved){return {train:{lineId:'2',trainId:saved.request.trainId,direction:saved.request.direction,express:false,observedAt:saved.observedAt},previousStation:saved.request.previousStation,destinationStation:saved.request.destinationStation};}
 return {
  getState,
  restore:()=>exclusive(async()=>{
   try{
    const raw=await secureStore.getItemAsync(KEY);
    if(raw==null)record=null;
    else{if(typeof raw!=='string'||raw.length>32768)throw Error();record=validateStored(JSON.parse(raw),development);}
    blocked=false;ready=true;publish();return record;
   }catch(_){blocked=true;ready=true;publish();throw new Error(STORAGE_ERROR);}
  }),
  start:(confirmed,getCurrentConnection,selection,deviceToken)=>exclusive(async()=>{
   requireReady();if(record)throw new Error('기존 시험 감시를 먼저 조회하거나 종료하세요.');
   const original={...selection,train:{...selection.train}};
   const out=await startConfirmedMonitor(confirmed,getCurrentConnection,original,deviceToken,development,fetchImpl,now,async({train,previousStation,destinationStation,fcmToken},connection)=>{
    let id,sessionToken;
    try{
     id=crypto.randomUUID();const bytes=await crypto.getRandomBytesAsync(32);
     if(!(bytes instanceof Uint8Array)||bytes.length!==32)throw Error();
     sessionToken=Array.from(bytes,byte=>byte.toString(16).padStart(2,'0')).join('');
     if(!UUID4.test(id)||!SECRET.test(sessionToken))throw Error();
    }catch(_){throw new Error('안전한 등록 ID와 세션 비밀을 만들지 못했습니다. 다시 시도하세요.');}
    const request=Object.freeze({lineId:'2',trainId:train.trainId,direction:train.direction,previousStation:previousStation.trim(),destinationStation:destinationStation.trim(),fcmToken,mode:'TEST'});
    const pending={phase:'PENDING',id,sessionToken,server:validateServerUrl(connection.server,development),accessToken:validateAccessToken(connection.accessToken),request,observedAt:train.observedAt};
    await save(pending);return {id,sessionToken};
   });
   await activate(out.created);return out;
  }),
  retry:connection=>exclusive(async()=>{
   const saved=current();if(saved.phase!=='PENDING')throw new Error('PENDING 등록 대기 정보만 같은 요청으로 재시도할 수 있습니다.');
   if(observationStatus(saved.observedAt,now())!=='fresh')throw new Error('원래 열차 관측이 60초를 넘었거나 오래되었습니다. 등록 결과를 조회하거나 종료해 주세요.');
   const value=await startMonitor(saved.server,{...replaySelection(saved),id:saved.id,sessionToken:saved.sessionToken,fcmToken:saved.request.fcmToken,accessToken:sessionAccessToken(saved,connection,development)},development,fetchImpl,now());
   return activate(value);
  }),
  status:connection=>exclusive(async()=>{
   const saved=current();const value=await monitorRequest(saved.server,saved,'status',development,fetchImpl,sessionAccessToken(saved,connection,development));
   if(saved.phase==='PENDING')await activate(value);
   return value;
  }),
  cancel:connection=>exclusive(async()=>{
   const saved=current();const value=await cancelStaleSession(saved,development,fetchImpl,async()=>{
    try{await secureStore.deleteItemAsync(KEY);}catch(_){throw new Error('종료된 감시의 저장 정보를 지우지 못했습니다. 다시 종료를 확인해 주세요.');}
   },sessionAccessToken(saved,connection,development));
   record=null;publish();return value;
  })
 };
}
module.exports={KEY,createRegistrationFlow};
