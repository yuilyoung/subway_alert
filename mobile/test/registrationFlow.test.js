const test = require('node:test');
const assert = require('node:assert/strict');
const { createRegistrationFlow } = require('../src/registrationFlow');
const NOW = Date.parse('2026-10-27T00:00:00Z');
const ID = 'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',
  SECRET = '0a'.repeat(32),
  API = 'A'.repeat(43);
const connection = { server: 'https://old.example', accessToken: API };
const selection = {
  train: {
    lineId: '2',
    trainId: '0021',
    direction: 'INNER',
    express: false,
    observedAt: '2026-10-27T00:00:00Z',
  },
  previousStation: ' 선릉 ',
  destinationStation: ' 삼성 ',
};
const request = {
  lineId: '2',
  trainId: '0021',
  direction: 'INNER',
  previousStation: '선릉',
  destinationStation: '삼성',
  fcmToken: 'original-native-token',
  mode: 'TEST',
};
const pending = {
  phase: 'PENDING',
  id: ID,
  sessionToken: SECRET,
  server: connection.server,
  accessToken: API,
  request,
  observedAt: selection.train.observedAt,
};
const result = {
  id: ID,
  sessionToken: SECRET,
  status: 'TRACKING',
  mode: 'TEST',
  expiresAt: '2026-10-27T02:00:00Z',
};
const reply = (data, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => data,
});
function harness({
  raw = null,
  fetchImpl = async () => reply(result),
  readFailure = false,
  failWrite = 0,
  failDelete = false,
} = {}) {
  let saved = raw,
    clock = NOW,
    writes = 0,
    randomCalls = 0,
    tokenCalls = 0;
  const calls = [],
    events = [];
  const storage = {
    getItemAsync: async (key) => {
      assert.equal(key, 'subway-monitor-session-v1');
      if (readFailure) throw Error(API);
      return saved;
    },
    setItemAsync: async (key, value) => {
      writes++;
      events.push(`save:${JSON.parse(value).phase}`);
      if (writes === failWrite) throw Error(API);
      saved = value;
    },
    deleteItemAsync: async () => {
      if (failDelete) throw Error(API);
      saved = null;
      events.push('delete');
    },
  };
  const crypto = {
    randomUUID: () => {
      randomCalls++;
      return ID;
    },
    getRandomBytesAsync: async (count) => {
      assert.equal(count, 32);
      randomCalls++;
      return Uint8Array.from({ length: 32 }, () => 10);
    },
  };
  const flow = createRegistrationFlow({
    secureStore: storage,
    crypto,
    now: () => clock,
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      events.push(options.method);
      return fetchImpl(url, options);
    },
  });
  const start = () =>
    flow.start(
      connection,
      () => connection,
      selection,
      async () => {
        tokenCalls++;
        return 'original-native-token';
      },
    );
  return {
    flow,
    start,
    calls,
    events,
    get raw() {
      return saved;
    },
    get randomCalls() {
      return randomCalls;
    },
    get tokenCalls() {
      return tokenCalls;
    },
    setTime: (value) => {
      clock = value;
    },
  };
}

test('registration saves recoverable PENDING credentials and immutable original request before its first POST', async () => {
  const h = harness();
  await h.flow.restore();
  await h.start();
  assert.deepEqual(h.events, ['save:PENDING', 'POST', 'save:ACTIVE']);
  const sent = h.calls[0];
  assert.equal(sent.options.headers['Idempotency-Key'], ID);
  assert.equal(sent.options.headers['X-Session-Token'], SECRET);
  assert.deepEqual(JSON.parse(sent.options.body), request);
  assert.deepEqual(JSON.parse(h.raw), {
    phase: 'ACTIVE',
    id: ID,
    sessionToken: SECRET,
    server: connection.server,
    accessToken: API,
    expiresAt: result.expiresAt,
  });
  assert.equal(h.flow.getState().record.phase, 'ACTIVE');
  assert.equal(h.randomCalls, 2);
});

test('PENDING save failure blocks all HTTP and a concurrent or second registration cannot replace pending recovery', async () => {
  const failed = harness({ failWrite: 1 });
  await failed.flow.restore();
  await assert.rejects(failed.start, /저장/);
  assert.equal(failed.calls.length, 0);
  const h = harness({
    fetchImpl: async () => {
      throw Error('response lost');
    },
  });
  await h.flow.restore();
  await assert.rejects(h.start, /처리되었을 수/);
  assert.deepEqual(JSON.parse(h.raw), pending);
  await assert.rejects(h.start, /기존/);
  assert.equal(h.calls.length, 1);
});

test('a server-created registration whose response is lost retries exactly the same ID secret body and token', async () => {
  let first = true,
    created;
  const h = harness({
    fetchImpl: async (url, options) => {
      if (first) {
        first = false;
        created = { url, headers: options.headers, body: options.body };
        throw Error('lost after create');
      }
      assert.equal(url, created.url);
      assert.deepEqual(options.headers, created.headers);
      assert.equal(options.body, created.body);
      return reply({ ...result, status: 'SAMPLE_MATCHED' });
    },
  });
  await h.flow.restore();
  await assert.rejects(h.start);
  assert.equal(h.flow.getState().record.phase, 'PENDING');
  selection.train.trainId = '9999';
  try {
    const value = await h.flow.retry(connection);
    assert.equal(value.status, 'SAMPLE_MATCHED');
  } finally {
    selection.train.trainId = '0021';
  }
  assert.equal(h.calls.length, 2);
  assert.equal(h.randomCalls, 2);
  assert.equal(h.tokenCalls, 1);
  assert.equal(h.flow.getState().record.phase, 'ACTIVE');
});

test('a malformed registration response and failed ACTIVE write retain the original PENDING identity', async () => {
  for (const options of [
    { fetchImpl: async () => reply({ ...result, id: 'd9ee7169-01cf-4e7e-bc6b-cbd706b3f362' }) },
    { failWrite: 2 },
  ]) {
    const h = harness(options);
    await h.flow.restore();
    await assert.rejects(h.start);
    assert.deepEqual(JSON.parse(h.raw), pending);
    assert.deepEqual(h.flow.getState().record, pending);
    await assert.rejects(h.start, /기존/);
  }
});

test('restoring PENDING performs no POST and supports lookup without ever receiving registration response', async () => {
  const h = harness({
    raw: JSON.stringify(pending),
    fetchImpl: async () =>
      reply({
        id: ID,
        status: 'TRACKING',
        mode: 'TEST',
        expiresAt: result.expiresAt,
        deliveryStatus: 'NONE',
        pollStatus: 'NOT_POLLED',
      }),
  });
  await h.flow.restore();
  assert.equal(h.calls.length, 0);
  assert.equal(h.flow.getState().record.phase, 'PENDING');
  await h.flow.status(connection);
  assert.equal(h.calls[0].options.method, 'GET');
  assert.equal(h.calls[0].url, `https://old.example/api/monitor-sessions/${ID}`);
  assert.equal(h.flow.getState().record.phase, 'ACTIVE');
  assert.equal(h.randomCalls, 0);
  assert.equal(h.tokenCalls, 0);
});

test('an expired original observation blocks POST retry while lookup and cancellation still work', async () => {
  const h = harness({
    raw: JSON.stringify(pending),
    fetchImpl: async (url, options) =>
      options.method === 'GET'
        ? reply({}, 404)
        : reply({ id: ID, status: 'CANCELLED', mode: 'TEST', expiresAt: result.expiresAt }),
  });
  await h.flow.restore();
  h.setTime(NOW + 60001);
  await assert.rejects(() => h.flow.retry(connection), /60초|오래/);
  assert.equal(h.calls.length, 0);
  await assert.rejects(
    () => h.flow.status(connection),
    (e) => e.status === 404,
  );
  assert.equal(h.flow.getState().record.phase, 'PENDING');
  await h.flow.cancel(connection);
  assert.deepEqual(
    h.calls.map((x) => x.options.method),
    ['GET', 'DELETE'],
  );
  assert.equal(h.raw, null);
  assert.equal(h.flow.getState().record, null);
});

test('failed cancellation or failed local deletion retains the saved secret until cancellation can be confirmed', async () => {
  for (const options of [
    { fetchImpl: async () => reply({}, 503) },
    {
      fetchImpl: async () =>
        reply({ id: ID, mode: 'TEST', expiresAt: '2026-10-27T02:00:00Z', status: 'TRACKING' }),
    },
    {
      failDelete: true,
      fetchImpl: async () =>
        reply({ id: ID, mode: 'TEST', expiresAt: '2026-10-27T02:00:00Z', status: 'CANCELLED' }),
    },
  ]) {
    const h = harness({ raw: JSON.stringify(pending), ...options });
    await h.flow.restore();
    await assert.rejects(() => h.flow.cancel(connection));
    assert.deepEqual(JSON.parse(h.raw), pending);
    assert.equal(h.flow.getState().record.sessionToken, SECRET);
  }
});

test('unreadable or malformed records block new registration instead of treating recovery as empty', async () => {
  for (const options of [
    { readFailure: true },
    { raw: '{invalid' },
    { raw: 'null' },
    { raw: JSON.stringify({ ...pending, request: { ...request, mode: 'LIVE' } }) },
    { raw: JSON.stringify({ ...pending, sessionToken: 'bad' }) },
    {
      raw: JSON.stringify({
        phase: 'ACTIVE',
        id: ID,
        sessionToken: SECRET,
        server: connection.server,
        accessToken: API,
      }),
    },
  ]) {
    const h = harness(options);
    await assert.rejects(
      () => h.flow.restore(),
      (e) => /저장/.test(e.message) && !e.message.includes(API),
    );
    assert.equal(h.flow.getState().blocked, true);
    await assert.rejects(h.start, /저장/);
    assert.equal(h.calls.length, 0);
    assert.equal(h.randomCalls, 0);
  }
});

test('secure random generation failures cannot persist a record or issue a registration request', async () => {
  for (const crypto of [
    { randomUUID: () => ID.toUpperCase(), getRandomBytesAsync: async () => new Uint8Array(32) },
    { randomUUID: () => ID, getRandomBytesAsync: async () => new Uint8Array(31) },
    {
      randomUUID: () => ID,
      getRandomBytesAsync: async () => {
        throw Error(API);
      },
    },
  ]) {
    let writes = 0,
      requests = 0;
    const flow = createRegistrationFlow({
      secureStore: {
        getItemAsync: async () => null,
        setItemAsync: async () => {
          writes++;
        },
      },
      crypto,
      now: () => NOW,
      fetchImpl: async () => {
        requests++;
        return reply(result);
      },
    });
    await flow.restore();
    await assert.rejects(
      () =>
        flow.start(
          connection,
          () => connection,
          selection,
          async () => 'original-native-token',
        ),
      (e) => /안전/.test(e.message) && !e.message.includes(API),
    );
    assert.equal(writes, 0);
    assert.equal(requests, 0);
  }
});

test('invalid native tokens cannot create unreadable PENDING records', async () => {
  for (const nativeToken of ['', 'x'.repeat(4097)]) {
    let writes = 0,
      requests = 0;
    const flow = createRegistrationFlow({
      secureStore: {
        getItemAsync: async () => null,
        setItemAsync: async () => {
          writes++;
        },
      },
      crypto: {
        randomUUID: () => ID,
        getRandomBytesAsync: async () => new Uint8Array(32).fill(10),
      },
      now: () => NOW,
      fetchImpl: async () => {
        requests++;
        return reply(result);
      },
    });
    await flow.restore();
    await assert.rejects(() =>
      flow.start(
        connection,
        () => connection,
        selection,
        async () => nativeToken,
      ),
    );
    assert.equal(writes, 0);
    assert.equal(requests, 0);
    assert.equal(flow.getState().record, null);
  }
});

test('a train that becomes stale during permission cannot create an unnecessary PENDING registration', async () => {
  let clock = NOW,
    writes = 0;
  const flow = createRegistrationFlow({
    secureStore: {
      getItemAsync: async () => null,
      setItemAsync: async () => {
        writes++;
      },
    },
    crypto: { randomUUID: () => ID, getRandomBytesAsync: async () => new Uint8Array(32).fill(10) },
    now: () => clock,
    fetchImpl: async () => {
      throw Error('must not POST');
    },
  });
  await flow.restore();
  await assert.rejects(
    () =>
      flow.start(
        connection,
        () => connection,
        selection,
        async () => {
          clock = NOW + 60001;
          return 'original-native-token';
        },
      ),
    /최근/,
  );
  assert.equal(writes, 0);
  assert.equal(flow.getState().record, null);
});

test('concurrent starts cannot both pass the empty-record check while notification permission is pending', async () => {
  let release;
  const permission = new Promise((resolve) => {
    release = resolve;
  });
  let requests = 0,
    randomCalls = 0;
  const flow = createRegistrationFlow({
    secureStore: { getItemAsync: async () => null, setItemAsync: async () => {} },
    crypto: {
      randomUUID: () => {
        randomCalls++;
        return ID;
      },
      getRandomBytesAsync: async () => new Uint8Array(32).fill(10),
    },
    now: () => NOW,
    fetchImpl: async () => {
      requests++;
      return reply(result);
    },
  });
  await flow.restore();
  const first = flow.start(
    connection,
    () => connection,
    selection,
    () => permission,
  );
  await assert.rejects(
    () =>
      flow.start(
        connection,
        () => connection,
        selection,
        async () => 'another-token',
      ),
    /처리 중/,
  );
  release('original-native-token');
  await first;
  assert.equal(requests, 1);
  assert.equal(randomCalls, 1);
});

test('retry permits exactly sixty seconds but rejects future and older original observations', async () => {
  const atBoundary = harness({ raw: JSON.stringify(pending) });
  await atBoundary.flow.restore();
  atBoundary.setTime(NOW + 60000);
  await atBoundary.flow.retry(connection);
  assert.equal(atBoundary.calls.length, 1);
  const future = harness({ raw: JSON.stringify(pending) });
  await future.flow.restore();
  future.setTime(NOW - 5001);
  await assert.rejects(() => future.flow.retry(connection), /60초|오래/);
  assert.equal(future.calls.length, 0);
});

test('legacy records without a phase remain ACTIVE and cannot be replayed as registrations', async () => {
  const legacy = {
    id: ID,
    sessionToken: 'legacy_secret',
    server: connection.server,
    accessToken: API,
    expiresAt: result.expiresAt,
  };
  const h = harness({ raw: JSON.stringify(legacy) });
  await h.flow.restore();
  assert.equal(h.flow.getState().record.phase, 'ACTIVE');
  await assert.rejects(() => h.flow.retry(connection), /대기|PENDING/);
  assert.equal(h.calls.length, 0);
});

test('recovery uses a same-origin rotated API key and never sends original secrets to a different origin', async () => {
  for (const current of [
    { server: 'https://old.example:443/', accessToken: 'B'.repeat(43) },
    { server: 'https://new.example', accessToken: 'C'.repeat(43) },
  ]) {
    const h = harness({ raw: JSON.stringify(pending) });
    await h.flow.restore();
    await h.flow.retry(current);
    assert.equal(h.calls[0].url, 'https://old.example/api/monitor-sessions');
    assert.equal(
      h.calls[0].options.headers.Authorization,
      `Bearer ${current.server.includes('old.example') ? 'B'.repeat(43) : API}`,
    );
    assert.equal(h.calls[0].options.headers['X-Session-Token'], SECRET);
  }
});

test('connection changes during permission or PENDING storage prevent a registration POST', async () => {
  let current = connection,
    calls = 0,
    writes = 0;
  const flow = createRegistrationFlow({
    secureStore: {
      getItemAsync: async () => null,
      setItemAsync: async () => {
        writes++;
        current = { ...connection };
      },
    },
    crypto: { randomUUID: () => ID, getRandomBytesAsync: async () => new Uint8Array(32).fill(10) },
    now: () => NOW,
    fetchImpl: async () => {
      calls++;
      return reply(result);
    },
  });
  await flow.restore();
  await assert.rejects(
    () =>
      flow.start(
        connection,
        () => current,
        selection,
        async () => {
          current = { ...connection };
          return 'original-native-token';
        },
      ),
    /연결 정보/,
  );
  assert.equal(writes, 0);
  current = connection;
  await assert.rejects(
    () =>
      flow.start(
        connection,
        () => current,
        selection,
        async () => 'original-native-token',
      ),
    /연결 정보/,
  );
  assert.equal(writes, 1);
  assert.equal(calls, 0);
  assert.equal(flow.getState().record.phase, 'PENDING');
});
