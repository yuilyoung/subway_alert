// Called by deploy/smoke_api_access.py against its isolated Spring Boot server.
const assert = require('node:assert/strict');
const {randomBytes, randomUUID} = require('node:crypto');
const {createRegistrationFlow, KEY} = require('../src/registrationFlow');
const {monitorRequest} = require('../src/monitorApi');

async function run() {
  const connection = {server: 'http://127.0.0.1:' + process.argv[2], accessToken: process.env.SMOKE_DEVICE_KEY};
  const values = new Map();
  const secureStore = {
    getItemAsync: async key => values.get(key) ?? null,
    setItemAsync: async (key, value) => values.set(key, value),
    deleteItemAsync: async key => values.delete(key),
  };
  const crypto = {randomUUID, getRandomBytesAsync: async size => randomBytes(size)};
  const flow = fetchImpl => createRegistrationFlow({secureStore, crypto, fetchImpl, development: true});
  let postSucceeded = false;
  const first = flow(async (url, options) => {
    const response = await fetch(url, options);
    postSucceeded = options.method === 'POST' && response.ok;
    await response.body.cancel();
    throw Error('Simulated response loss');
  });
  await first.restore();
  const selection = {
    train: {lineId:'2', trainId:'0007', direction:'INNER', express:false, observedAt:new Date().toISOString()},
    previousStation:'선릉', destinationStation:'삼성',
  };
  await assert.rejects(first.start(connection, () => connection, selection, async () => 'local-test-only'));
  assert.equal(postSucceeded, true);
  const pending = first.getState().record;
  assert.equal(pending.phase, 'PENDING');

  const recovered = flow(fetch);
  await recovered.restore();
  const active = await recovered.retry(connection);
  assert.equal(active.id, pending.id);
  assert.equal(active.status, 'TRACKING');
  assert.equal((await recovered.status(connection)).status, 'TRACKING');
  const owner = recovered.getState().record;
  assert.equal(owner.phase, 'ACTIVE');
  assert.equal((await monitorRequest(connection.server, owner, 'test', true, fetch)).deliveryStatus, 'UNAVAILABLE');
  assert.equal((await recovered.cancel(connection)).status, 'CANCELLED');
  assert.equal(values.size, 0);
  assert.equal((await monitorRequest(connection.server, owner, 'status', true, fetch)).status, 'CANCELLED');

  // Older APKs saved the server-issued base64url secret without phase or expiry.
  values.set(KEY, JSON.stringify({...connection, id:randomUUID(), sessionToken:randomBytes(32).toString('base64url')}));
  const upgraded = flow(fetch);
  await upgraded.restore();
  assert.equal(upgraded.getState().record.phase, 'ACTIVE');
  assert.equal((await upgraded.cancel(connection)).status, 'CANCELLED');
  assert.equal(values.size, 0);
}

run().then(() => console.log('Mobile client → Spring Boot: response loss, retry, status, disabled FCM, cancellation and legacy cleanup passed'))
  .catch(() => { console.error('Mobile registration integration failed'); process.exitCode = 1; });
