const { validateServerUrl, validateAccessToken } = require('./apiAccess');
const KEY = 'subway-api-connection-v1';
function createConnectionStore(secureStore, development = false) {
  function connection(server, accessToken) {
    return {
      server: validateServerUrl(server, development),
      accessToken: validateAccessToken(accessToken),
    };
  }
  return {
    async read() {
      try {
        const raw = await secureStore.getItemAsync(KEY);
        if (raw == null) return null;
        if (typeof raw !== 'string' || raw.length > 4096) throw new Error();
        const value = JSON.parse(raw);
        return connection(value.server, value.accessToken);
      } catch {
        throw new Error('저장된 서버 연결을 읽지 못했습니다. 주소와 접근 키를 다시 입력하세요.');
      }
    },
    async save(server, accessToken) {
      const value = connection(server, accessToken);
      try {
        await secureStore.setItemAsync(KEY, JSON.stringify(value));
      } catch {
        throw new Error('서버 연결을 안전하게 저장하지 못했습니다. 다시 시도하세요.');
      }
      return value;
    },
    async clear() {
      try {
        await secureStore.deleteItemAsync(KEY);
      } catch {
        throw new Error('저장된 서버 연결을 삭제하지 못했습니다. 다시 시도하세요.');
      }
    },
  };
}

function sessionAccessToken(session, connection, development = false) {
  const origin = validateServerUrl(session?.server, development);
  if (connection && validateServerUrl(connection.server, development) === origin)
    return validateAccessToken(connection.accessToken);
  try {
    return validateAccessToken(session?.accessToken);
  } catch {
    throw new Error(
      '기존 감시 서버와 일치하는 연결 키를 저장한 뒤 다시 종료하세요. 종료 확인 전에는 감시 정보를 보존하며 서버 세션은 최대 2시간 후 만료됩니다.',
    );
  }
}
module.exports = { createConnectionStore, sessionAccessToken };
