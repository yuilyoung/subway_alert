const {validateServerUrl,observationStatus}=require('./liveApi');
const {validateAccessToken,requestJson}=require('./apiAccess');
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function station(value){return typeof value==='string' && value.trim().length>0 && value.trim().length<=40}
function validateSelection(train,previousStation,destinationStation,now=Date.now()){
  if(!train || train.lineId!=='2' || !['INNER','OUTER'].includes(train.direction) || typeof train.trainId!=='string' || !train.trainId.trim() || train.trainId.length>80 || train.express!==false || observationStatus(train.observedAt,now)!=='fresh') throw new Error('최근 수신된 일반 열차를 다시 선택해 주세요.');
  if(!station(previousStation)||!station(destinationStation)||previousStation.trim()===destinationStation.trim()) throw new Error('서로 다른 이전역과 도착역을 입력해 주세요.');
}
async function startMonitor(server,{train,previousStation,destinationStation,fcmToken,accessToken},development=false,fetchImpl,now=Date.now()){
 const base=validateServerUrl(server,development);validateSelection(train,previousStation,destinationStation,now);
 const key=validateAccessToken(accessToken);
 if(typeof fcmToken!=='string'||!fcmToken.trim()||fcmToken.length>4096) throw new Error('Android FCM 등록 토큰이 없습니다. Firebase 설정을 확인하세요.');
 const body={lineId:'2',trainId:train.trainId,direction:train.direction,previousStation:previousStation.trim(),destinationStation:destinationStation.trim(),fcmToken,mode:'TEST'};
 const value=await requestJson(base,'/api/monitor-sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)},key,development,fetchImpl);
 if(!value || !UUID.test(value.id||'') || typeof value.sessionToken!=='string' || !value.sessionToken || value.sessionToken.length>512 || value.mode!=='TEST' || typeof value.status!=='string'||typeof value.expiresAt!=='string') throw new Error('서버 응답 형식이 올바르지 않습니다.');
 return {id:value.id,sessionToken:value.sessionToken,status:value.status,mode:value.mode,expiresAt:value.expiresAt,server:base,accessToken:key};
}
async function monitorRequest(server,session,action,development=false,fetchImpl,accessToken=session?.accessToken){
 const base=validateServerUrl(server,development);
 if(!session||!UUID.test(session.id||'')||typeof session.sessionToken!=='string'||!/^[A-Za-z0-9_-]{1,512}$/.test(session.sessionToken)||!['status','test','cancel'].includes(action)) throw new Error('시험 감시 정보가 올바르지 않습니다.');
 if(base!==validateServerUrl(session.server,development))throw new Error('등록한 감시 서버와 요청 서버가 다릅니다.');
 const path=action==='test'?'/test':'',method=action==='test'?'POST':action==='cancel'?'DELETE':'GET';
 const data=await requestJson(base,`/api/monitor-sessions/${session.id}${path}`,{method,headers:{'X-Session-Token':session.sessionToken}},accessToken,development,fetchImpl);
 if(!data||typeof data.status!=='string'||data.status.length>80||(data.mode!=null&&data.mode!=='TEST'))throw new Error('서버 응답 형식이 올바르지 않습니다.');
 const deliveryStatus=data.deliveryStatus??'NONE',pollStatus=data.pollStatus??'NOT_POLLED';
 if(!['NONE','SENDING','FCM_ACCEPTED','UNAVAILABLE','FAILED'].includes(deliveryStatus)||!['NOT_POLLED','SAMPLE_PARTIAL','SOURCE_BLOCKED','PROVIDER_ERROR','DAILY_LIMIT'].includes(pollStatus))throw new Error('서버 응답 형식이 올바르지 않습니다.');
 return {status:data.status,mode:'TEST',expiresAt:data.expiresAt||null,deliveryStatus,pollStatus};
}
async function cancelStaleSession(session,development,fetchImpl,deleteStored,accessToken=session?.accessToken){
 const result=await monitorRequest(session.server,session,'cancel',development,fetchImpl,accessToken);
 if(!['CANCELLED','EXPIRED'].includes(result.status))throw new Error('서버에서 감시 종료를 확인하지 못했습니다.');
 await deleteStored();
 return result;
}
function needsRegistration(session,currentToken,nextToken){return Boolean(session&&(!currentToken||currentToken!==nextToken));}
async function startConfirmedMonitor(confirmed,getCurrentConnection,selection,deviceToken,development=false,fetchImpl,now=()=>Date.now()){
 function verifyConnection(){
  if(!confirmed||getCurrentConnection()!==confirmed)throw new Error('연결 정보가 바뀌었습니다. 서버 주소와 접근 키를 저장하고 열차를 다시 선택해 주세요.');
 }
 verifyConnection();
 validateSelection(selection.train,selection.previousStation,selection.destinationStation,now());
 const fcmToken=await deviceToken();
 verifyConnection();
 const created=await startMonitor(confirmed.server,{...selection,fcmToken,accessToken:confirmed.accessToken},development,fetchImpl,now());
 return {created,fcmToken};
}
module.exports={validateSelection,startMonitor,monitorRequest,needsRegistration,cancelStaleSession,startConfirmedMonitor};
