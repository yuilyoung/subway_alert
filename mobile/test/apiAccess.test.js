const test = require('node:test');
const assert = require('node:assert/strict');
const { requestJson, validateAccessToken } = require('../src/apiAccess');
const { createConnectionStore, sessionAccessToken } = require('../src/connectionStore');
const KEY = 'A'.repeat(43),
  OTHER = 'B'.repeat(43);
function response(status = 200, data = { ok: true }, retryAfter = null) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => (name.toLowerCase() === 'retry-after' ? retryAfter : null) },
    json: async () => data,
  };
}

test('credentials travel only in headers to the selected origin with redirects disabled', async () => {
  let request;
  const data = await requestJson(
    'https://api.example.com',
    '/api/lines',
    {},
    KEY,
    false,
    async (url, options) => {
      request = { url, options };
      return response();
    },
  );
  assert.deepEqual(data, { ok: true });
  assert.equal(request.url, 'https://api.example.com/api/lines');
  assert.equal(request.options.headers.Authorization, `Bearer ${KEY}`);
  assert.equal(request.options.redirect, 'error');
  assert.ok(!request.url.includes(KEY));
});

test('invalid keys and unsafe URLs fail before any network request', async () => {
  let calls = 0;
  const transport = async () => {
    calls++;
    return response();
  };
  for (const key of ['', null, 'short', `${KEY}\r\nInjected: yes`, 'x'.repeat(129)])
    await assert.rejects(() =>
      requestJson('https://api.example.com', '/api/lines', {}, key, false, transport),
    );
  await assert.rejects(() =>
    requestJson('http://evil.example', '/api/lines', {}, KEY, true, transport),
  );
  await assert.rejects(() =>
    requestJson('https://api.example.com', '//evil.example/api', {}, KEY, false, transport),
  );
  await assert.rejects(() =>
    requestJson('https://api.example.com', '/api/lines', {}, KEY, false, undefined),
  );
  assert.equal(calls, 0);
  assert.equal(validateAccessToken(` ${KEY} `), KEY);
});

test('authentication and quota rejections have safe actionable messages without automatic retries', async () => {
  let calls = 0;
  for (const [status, pattern] of [
    [401, /접근 키/],
    [403, /권한/],
    [429, /7초/],
    [503, /서버/],
  ]) {
    await assert.rejects(
      () =>
        requestJson('https://api.example.com', '/api/lines', {}, KEY, false, async () => {
          calls++;
          return response(status, { secret: KEY }, '7');
        }),
      (e) => e.status === status && pattern.test(e.message) && !e.message.includes(KEY),
    );
  }
  assert.equal(calls, 4);
  await assert.rejects(
    () =>
      requestJson('https://api.example.com', '/api/lines', {}, KEY, false, async () =>
        response(429, {}, 'secret-value'),
      ),
    (e) => !e.message.includes('secret-value'),
  );
});

test('network errors are sanitized and uncertain mutations retain the ambiguity warning', async () => {
  const broken = async () => {
    throw Error(KEY);
  };
  await assert.rejects(
    () => requestJson('https://api.example.com', '/api/lines', {}, KEY, false, broken),
    (e) => !e.message.includes(KEY) && /연결/.test(e.message),
  );
  await assert.rejects(
    () =>
      requestJson(
        'https://api.example.com',
        '/api/monitor-sessions',
        { method: 'POST' },
        KEY,
        false,
        broken,
      ),
    (e) => !e.message.includes(KEY) && /처리되었을 수/.test(e.message),
  );
});

test('connection storage validates before writing and round-trips an origin-bound key', async () => {
  let raw = null,
    writes = 0;
  const adapter = {
    getItemAsync: async () => raw,
    setItemAsync: async (_, value) => {
      writes++;
      raw = value;
    },
    deleteItemAsync: async () => {
      raw = null;
    },
  };
  const store = createConnectionStore(adapter, false);
  assert.equal(await store.read(), null);
  await assert.rejects(() => store.save('http://evil.example', KEY));
  assert.equal(writes, 0);
  const connection = await store.save('https://API.EXAMPLE.com/', ` ${KEY} `);
  assert.deepEqual(connection, { server: 'https://api.example.com', accessToken: KEY });
  assert.deepEqual(await store.read(), connection);
  await store.clear();
  assert.equal(await store.read(), null);
  raw = '{invalid';
  await assert.rejects(
    () => store.read(),
    (e) => !e.message.includes(raw),
  );
});

test('storage failures do not pretend the connection was saved or cleared', async () => {
  const store = createConnectionStore(
    {
      getItemAsync: async () => {
        throw Error(KEY);
      },
      setItemAsync: async () => {
        throw Error(KEY);
      },
      deleteItemAsync: async () => {
        throw Error(KEY);
      },
    },
    false,
  );
  for (const run of [
    () => store.read(),
    () => store.save('https://api.example.com', KEY),
    () => store.clear(),
  ])
    await assert.rejects(run, (e) => !e.message.includes(KEY));
});

test('a key from a different origin never replaces an existing session credential', () => {
  const session = { server: 'https://old.example', accessToken: KEY };
  assert.equal(
    sessionAccessToken(session, { server: 'https://new.example', accessToken: OTHER }, false),
    KEY,
  );
  assert.equal(
    sessionAccessToken(session, { server: 'https://old.example/', accessToken: OTHER }, false),
    OTHER,
  );
  assert.equal(sessionAccessToken(session, null, false), KEY);
  assert.throws(
    () =>
      sessionAccessToken(
        { server: 'https://old.example' },
        { server: 'https://new.example', accessToken: OTHER },
        false,
      ),
    /연결 키/,
  );
  assert.equal(
    sessionAccessToken(
      { server: 'https://old.example' },
      { server: 'https://old.example', accessToken: OTHER },
      false,
    ),
    OTHER,
  );
});

test('equivalent default ports use the rotated key for the same web origin', () => {
  const session = { server: 'https://api.example.com', accessToken: KEY };
  assert.equal(
    sessionAccessToken(
      session,
      { server: 'https://api.example.com:0443/', accessToken: OTHER },
      false,
    ),
    OTHER,
  );
  assert.equal(
    sessionAccessToken(
      { server: 'http://localhost', accessToken: KEY },
      { server: 'http://localhost:080', accessToken: OTHER },
      true,
    ),
    OTHER,
  );
  assert.equal(
    sessionAccessToken(
      session,
      { server: 'https://api.example.com:8443', accessToken: OTHER },
      false,
    ),
    KEY,
  );
});
