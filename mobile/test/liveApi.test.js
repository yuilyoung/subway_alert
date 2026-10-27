const {test} = require('node:test');
const assert = require('node:assert/strict');
const KEY='A'.repeat(43);
const {validateServerUrl, normalizeResponse, fetchTrains, observationStatus, filterTrains} = require('../src/liveApi');

test('server URLs use https except explicit development loopback addresses', () => {
  assert.equal(validateServerUrl(' https://api.example.com:8443/ ', false), 'https://api.example.com:8443');
  assert.equal(validateServerUrl('http://10.0.2.2:8080/', true), 'http://10.0.2.2:8080');
  assert.throws(() => validateServerUrl('http://10.0.2.2:8080', false));
  assert.throws(() => validateServerUrl('http://example.com', true));
  assert.throws(() => validateServerUrl('https://user:pass@example.com', false));
  assert.throws(() => validateServerUrl('https://example.com/?token=secret', false));
  assert.throws(() => validateServerUrl('https://example.com/path', false));
  assert.throws(() => validateServerUrl('https://example.com:70000', false));
  assert.throws(() => validateServerUrl('https://example.com.evil@localhost', false));
});

test('finds train by exact number substring without losing leading zeros or station name', () => {
  const rows=[{trainId:'0202',station:'강남'},{trainId:'2020',station:'삼성'}];
  assert.deepEqual(filterTrains(rows,'020').map(x=>x.trainId),['0202','2020']);
  assert.deepEqual(filterTrains(rows,'강남').map(x=>x.trainId),['0202']);
});

test('response preserves leading zeros and rejects invalid mode and shape', () => {
  const result=normalizeResponse({mode:'SAMPLE',warning:'sample only',trains:[{lineId:'2',station:'강남',trainId:'0202',direction:'0',state:'2',observedAt:'2026-10-27T12:00:00Z',express:false}]});
  assert.equal(result.trains[0].trainId,'0202');
  assert.throws(() => normalizeResponse({mode:'FAKE',trains:[]}));
  assert.throws(() => normalizeResponse({mode:'LIVE',trains:[{trainId:202}]}));
});

test('freshness is based on event timestamp and does not infer future or unknown positions', () => {
  const now=Date.parse('2026-10-27T12:02:00Z');
  assert.equal(observationStatus('2026-10-27T12:01:30Z',now),'fresh');
  assert.equal(observationStatus('2026-10-27T12:00:00Z',now),'stale');
  assert.equal(observationStatus('2026-10-27T12:03:00Z',now),'unknown');
  assert.equal(observationStatus('bad',now),'unknown');
});

test('HTTP errors and malformed payloads do not become train data', async () => {
  await assert.rejects(fetchTrains('https://example.com', false, async () => ({ok:false,status:503}),KEY), /503/);
  await assert.rejects(fetchTrains('https://example.com', false, async () => ({ok:true,json:async()=>({})}),KEY), /형식/);
  const response=await fetchTrains('https://example.com', false, async (url) => {
    assert.equal(url,'https://example.com/api/live/trains?line=2');
    return {ok:true,json:async()=>({mode:'LIVE',warning:'',trains:[]})};
  },KEY);
  assert.equal(response.mode,'LIVE');
});

test('train lookup uses the API credential header and refuses redirects',async()=>{
 let sent;
 await fetchTrains('https://example.com',false,async(url,options)=>{sent=options;return {ok:true,json:async()=>({mode:'SAMPLE',trains:[]})};},KEY);
 assert.equal(sent.headers.Authorization,`Bearer ${KEY}`);
 assert.equal(sent.redirect,'error');
 let calls=0;
 await assert.rejects(()=>fetchTrains('https://example.com',false,async()=>{calls++;},''));
 assert.equal(calls,0);
});
