function validateServerUrl(input,development=false) {
  const match=String(input).trim().match(/^(https?):\/\/([a-zA-Z0-9.-]+|\[::1\])(?::(\d{1,5}))?\/?$/i);
  if(!match || (match[3] && (Number(match[3])<1 || Number(match[3])>65535)) || match[2].includes('..')) throw new Error('서버 주소를 확인하세요. 경로, 계정 정보 또는 쿼리는 사용할 수 없습니다.');
  const protocol=match[1].toLowerCase(),hostname=match[2].toLowerCase();
  const local=['localhost','127.0.0.1','[::1]','10.0.2.2'].includes(hostname);
  if(protocol!=='https' && !(development && local && protocol==='http')) throw new Error('HTTPS 주소가 필요합니다. HTTP는 개발 빌드의 로컬 테스트만 허용됩니다.');
  const port=match[3]?Number(match[3]):null;
  const defaultPort=protocol==='https'?443:80;
  return `${protocol}://${hostname}${port&&port!==defaultPort?':'+port:''}`;
}

function validateAccessToken(value) {
  const token=typeof value==='string'?value.trim():'';
  if(!/^[A-Za-z0-9_-]{32,128}$/.test(token)) throw new Error('서버에서 발급한 접근 키를 입력하세요.');
  return token;
}

class ApiResponseError extends Error {
  constructor(status,retryAfter=null) {
    const message=status===401?'접근 키가 없거나 만료·회수되었습니다. 서버 연결 키를 확인하세요.':
      status===403?'이 요청을 수행할 권한이 없습니다.':
      status===429?`요청 한도에 도달했습니다. ${retryAfter?`${retryAfter}초 후에 `:''}다시 시도하세요.`:
      status===503?'서버가 요청을 처리할 수 없습니다. 서버의 접근 키 설정과 실행 상태를 확인하세요.':
      `서버 응답 오류 (${status})`;
    super(`${message} (HTTP ${status})`);this.status=status;this.retryAfter=retryAfter;
  }
}

async function requestJson(server,path,options={},accessToken,development=false,fetchImpl) {
  const base=validateServerUrl(server,development),token=validateAccessToken(accessToken);
  if(typeof path!=='string' || !path.startsWith('/api/') || /[\\\r\n#]/.test(path)) throw new Error('서버 요청 경로가 올바르지 않습니다.');
  if(typeof fetchImpl!=='function') throw new Error('안전한 네이티브 전송 수단이 필요합니다.');
  const headers=Object.fromEntries(Object.entries(options.headers||{}).filter(([name])=>name.toLowerCase()!=='authorization'));
  const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),10000);
  try {
    const response=await fetchImpl(`${base}${path}`,{...options,signal:abort.signal,redirect:'error',headers:{...headers,Accept:'application/json',Authorization:`Bearer ${token}`}});
    if(!response.ok) {
      const raw=response.headers?.get?.('Retry-After');
      const retryAfter=typeof raw==='string' && /^\d{1,5}$/.test(raw) && Number(raw)>0 && Number(raw)<=86400?Number(raw):null;
      throw new ApiResponseError(response.status,retryAfter);
    }
    return await response.json();
  } catch(error) {
    if(error instanceof ApiResponseError) throw error;
    if((options.method||'GET')!=='GET') throw new Error('요청 결과를 확인할 수 없습니다. 서버에서 이미 처리되었을 수 있습니다. 중복 요청 전 상태를 확인하세요. 등록 결과를 잃은 경우 세션은 최대 2시간 후 만료됩니다.');
    throw new Error(abort.signal.aborted?'서버 응답 시간이 초과되었습니다.':'서버에 연결할 수 없거나 응답을 읽을 수 없습니다.');
  } finally {clearTimeout(timer);}
}
module.exports={validateServerUrl,validateAccessToken,requestJson};
