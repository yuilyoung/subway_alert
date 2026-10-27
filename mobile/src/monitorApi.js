const {validateServerUrl,observationStatus}=require('./liveApi');
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function station(value){return typeof value==='string' && value.trim().length>0 && value.trim().length<=40}
function validateSelection(train,previousStation,destinationStation,now=Date.now()){
  if(!train || train.lineId!=='2' || !['INNER','OUTER'].includes(train.direction) || typeof train.trainId!=='string' || !train.trainId.trim() || train.trainId.length>80 || train.express!==false || observationStatus(train.observedAt,now)!=='fresh') throw new Error('최근 수신된 일반 열차를 다시 선택해 주세요.');
  if(!station(previousStation)||!station(destinationStation)||previousStation.trim()===destinationStation.trim()) throw new Error('서로 다른 이전역과 도착역을 입력해 주세요.');
}
async function call(url,options,fetchImpl){
 if(typeof fetchImpl!=='function')throw new Error('안전한 네이티브 전송 수단이 필요합니다.');
 const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),10000);
 try {
  const response=await fetchImpl(url,{...options,signal:abort.signal,redirect:'error'});
  if(!response.ok) throw new Error(`HTTP ${response.status}`);
  return await response.json();
 } catch(e) {
   if(options.method!=='GET')throw new Error('요청 결과를 확인할 수 없습니다. 서버에서 이미 처리되었을 수 있습니다. 중복 요청 전 상태를 확인하세요. 등록 결과를 잃은 경우 세션은 최대 2시간 후 만료됩니다.');
   throw new Error(abort.signal.aborted?'서버 응답 시간이 초과되었습니다.':'서버에 연결할 수 없거나 응답을 읽을 수 없습니다.');
 }
 finally {clearTimeout(timer)}
}
async function startMonitor(server,{train,previousStation,destinationStation,fcmToken},development=false,fetchImpl,now=Date.now()){
 const base=validateServerUrl(server,development);validateSelection(train,previousStation,destinationStation,now);
 if(typeof fcmToken!=='string'||!fcmToken.trim()||fcmToken.length>4096) throw new Error('Android FCM 등록 토큰이 없습니다. Firebase 설정을 확인하세요.');
 const body={lineId:'2',trainId:train.trainId,direction:train.direction,previousStation:previousStation.trim(),destinationStation:destinationStation.trim(),fcmToken,mode:'TEST'};
 const value=await call(`${base}/api/monitor-sessions`,{method:'POST',headers:{Accept:'application/json','Content-Type':'application/json'},body:JSON.stringify(body)},fetchImpl);
 if(!value || !UUID.test(value.id||'') || typeof value.sessionToken!=='string' || !value.sessionToken || value.sessionToken.length>512 || value.mode!=='TEST' || typeof value.status!=='string'||typeof value.expiresAt!=='string') throw new Error('서버 응답 형식이 올바르지 않습니다.');
 return {id:value.id,sessionToken:value.sessionToken,status:value.status,mode:value.mode,expiresAt:value.expiresAt,server:base};
}
async function monitorRequest(server,session,action,development=false,fetchImpl){
 const base=validateServerUrl(server,development);
 if(!session||!UUID.test(session.id||'')||typeof session.sessionToken!=='string'||!session.sessionToken||session.sessionToken.length>512||!['status','test','cancel'].includes(action)) throw new Error('시험 감시 정보가 올바르지 않습니다.');
 const path=action==='test'?'/test':'',method=action==='test'?'POST':action==='cancel'?'DELETE':'GET';
 const data=await call(`${base}/api/monitor-sessions/${session.id}${path}`,{method,headers:{Accept:'application/json','X-Session-Token':session.sessionToken}},fetchImpl);
 if(!data||typeof data.status!=='string'||data.status.length>80||(data.mode!=null&&data.mode!=='TEST'))throw new Error('서버 응답 형식이 올바르지 않습니다.');
 const deliveryStatus=data.deliveryStatus??'NONE',pollStatus=data.pollStatus??'NOT_POLLED';
 if(!['NONE','SENDING','FCM_ACCEPTED','UNAVAILABLE','FAILED'].includes(deliveryStatus)||!['NOT_POLLED','SAMPLE_PARTIAL','SOURCE_BLOCKED','PROVIDER_ERROR','DAILY_LIMIT'].includes(pollStatus))throw new Error('서버 응답 형식이 올바르지 않습니다.');
 return {status:data.status,mode:'TEST',expiresAt:data.expiresAt||null,deliveryStatus,pollStatus};
}
async function cancelStaleSession(session,development,fetchImpl,deleteStored){
 const result=await monitorRequest(session.server,session,'cancel',development,fetchImpl);
 if(!['CANCELLED','EXPIRED'].includes(result.status))throw new Error('서버에서 감시 종료를 확인하지 못했습니다.');
 await deleteStored();
 return result;
}
function needsRegistration(session,currentToken,nextToken){return Boolean(session&&(!currentToken||currentToken!==nextToken));}
module.exports={validateSelection,startMonitor,monitorRequest,needsRegistration,cancelStaleSession};
