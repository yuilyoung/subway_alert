// API credentials remain on the server; this endpoint returns display-only information.
const MAX_ROWS=5000;
function validateServerUrl(input, development=false) {
  // React Native's built-in URL parser differs from a browser's parser. Restrict
  // inputs to an origin, with no user info, path, query, encoded host or fragment.
  const match=String(input).trim().match(/^(https?):\/\/([a-zA-Z0-9.-]+|\[::1\])(?::(\d{1,5}))?\/?$/i);
  if (!match || (match[3] && (Number(match[3])<1 || Number(match[3])>65535)) || match[2].includes('..')) throw new Error('서버 주소를 확인하세요. 경로, 계정 정보 또는 쿼리는 사용할 수 없습니다.');
  const protocol=match[1].toLowerCase(), hostname=match[2].toLowerCase();
  const local=['localhost','127.0.0.1','[::1]','10.0.2.2'].includes(hostname);
  if (protocol !== 'https' && !(development && local && protocol==='http')) throw new Error('HTTPS 주소가 필요합니다. HTTP는 개발 빌드의 로컬 테스트만 허용됩니다.');
  return `${protocol}://${hostname}${match[3]?':'+match[3]:''}`;
}
function normalizeResponse(payload) {
  if (!payload || !['SAMPLE','LIVE'].includes(payload.mode) || !Array.isArray(payload.trains) || payload.trains.length>MAX_ROWS || (payload.warning!=null && typeof payload.warning!=='string')) throw new Error('서버 응답 형식이 올바르지 않습니다.');
  const trains=payload.trains.map(row=>{
    if (!row || !['lineId','station','trainId','direction','state'].every(k=>typeof row[k]==='string' && row[k].length>0 && row[k].length<=100) || !(row.observedAt==null || typeof row.observedAt==='string') || !(row.express==null || typeof row.express==='boolean')) throw new Error('서버 응답 형식이 올바르지 않습니다.');
    return {lineId:row.lineId,station:row.station,trainId:row.trainId,direction:row.direction,state:row.state,observedAt:row.observedAt||null,express:row.express??null};
  });
  return {mode:payload.mode,warning:payload.warning || '',trains};
}
function observationStatus(value, now=Date.now()) {
  if (!value || !/(Z|[+-]\d\d:\d\d)$/.test(value)) return 'unknown';
  const stamp=Date.parse(value);
  if (!Number.isFinite(stamp) || stamp>now+5000) return 'unknown';
  return now-stamp<=60000 ? 'fresh' : 'stale';
}
function filterTrains(trains, query) {
  const needle=String(query).trim();
  return trains.filter(t=>t.trainId.includes(needle) || t.station.includes(needle));
}
async function fetchTrains(serverUrl,development=false,fetchImpl=fetch) {
  const base=validateServerUrl(serverUrl,development);
  const abort=new AbortController();
  const timer=setTimeout(()=>abort.abort(),10000);
  try {
    const response=await fetchImpl(`${base}/api/live/trains?line=2`,{signal:abort.signal,headers:{Accept:'application/json'}});
    if (!response.ok) throw new Error(`서버 응답 오류 (${response.status})`);
    return normalizeResponse(await response.json());
  } catch(e) {
    if (e?.name==='AbortError') throw new Error('서버 응답 시간이 초과되었습니다.');
    if (e instanceof TypeError || e instanceof SyntaxError) throw new Error('서버에 연결할 수 없거나 응답을 읽을 수 없습니다.');
    throw e;
  } finally { clearTimeout(timer); }
}
module.exports={validateServerUrl,normalizeResponse,observationStatus,filterTrains,fetchTrains};
