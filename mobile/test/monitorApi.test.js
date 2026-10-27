const test=require('node:test');
const assert=require('node:assert/strict');
const {startMonitor,monitorRequest,validateSelection}=require('../src/monitorApi');
const KEY='A'.repeat(43);
const ID='c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',SECRET='ab'.repeat(32);
const identity={id:ID,sessionToken:SECRET};
const now=Date.parse('2026-10-27T00:00:00Z');
const train={lineId:'2',trainId:'0021',direction:'INNER',station:'역삼',state:'ARRIVED',observedAt:new Date(now).toISOString(),express:false};
function reply(data,status=200){return {ok:status>=200&&status<300,status,json:async()=>data}}
test('starts only a clearly marked test session preserving leading zero and submits native token in body',async()=>{
 let call;
 const session=await startMonitor('https://example.com',{...identity,train,previousStation:'선릉',destinationStation:'삼성',fcmToken:'device-secret',accessToken:KEY},false,async(url,options)=>{call={url,options};return reply({id:'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',sessionToken:SECRET,status:'TRACKING',mode:'TEST',expiresAt:'2026-10-27T01:00:00Z'})},now);
 assert.equal(call.options.headers['Idempotency-Key'],ID);assert.equal(call.options.headers['X-Session-Token'],SECRET);
 assert.equal(call.url,'https://example.com/api/monitor-sessions');assert.equal(call.options.method,'POST');
 assert.deepEqual(JSON.parse(call.options.body),{lineId:'2',trainId:'0021',direction:'INNER',previousStation:'선릉',destinationStation:'삼성',fcmToken:'device-secret',mode:'TEST'});
 assert.equal(session.sessionToken,SECRET);
});
test('requires fresh, ordinary train and distinct explicit stations',()=>{
 assert.throws(()=>validateSelection({...train,observedAt:'2026-10-26T23:00:00Z'},'선릉','삼성',now));
 assert.throws(()=>validateSelection({...train,express:true},'선릉','삼성',now));
 assert.throws(()=>validateSelection(train,'선릉','선릉',now));
});
test('sends secret in header, never URL, and rejects unsafe origins',async()=>{
 let call;
 await monitorRequest('https://example.com',{id:'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',sessionToken:'abc-secret',server:'https://example.com',accessToken:KEY},'status',false,async(url,options)=>{call={url,options};return reply({id:ID,mode:'TEST',expiresAt:'2026-10-27T02:00:00Z',status:'TRACKING'})});
 assert.equal(call.options.headers['X-Session-Token'],'abc-secret');assert.ok(!call.url.includes('abc-secret'));
 await assert.rejects(()=>monitorRequest('http://evil.example',{id:'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',sessionToken:'secret',server:'http://evil.example',accessToken:KEY},'status',false,async()=>reply({})));
});
test('network failures are sanitized and malformed sessions rejected',async()=>{
 await assert.rejects(()=>startMonitor('https://example.com',{...identity,train,previousStation:'선릉',destinationStation:'삼성',fcmToken:'device-secret',accessToken:KEY},false,async()=>{throw Error('device-secret')},now), e=>!e.message.includes('device-secret'));
 await assert.rejects(()=>startMonitor('https://example.com',{...identity,train,previousStation:'선릉',destinationStation:'삼성',fcmToken:'device-secret',accessToken:KEY},false,async()=>reply({id:'x',sessionToken:'',mode:'LIVE'}),now));
});
test('test result preserves only recognized delivery and polling states',async()=>{
 const sess={id:'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',sessionToken:'token',server:'https://example.com',accessToken:KEY};
 const out=await monitorRequest('https://example.com',sess,'test',false,async()=>reply({id:ID,mode:'TEST',expiresAt:'2026-10-27T02:00:00Z',status:'TRACKING',deliveryStatus:'FCM_ACCEPTED',pollStatus:'SAMPLE_PARTIAL'}));
 assert.equal(out.deliveryStatus,'FCM_ACCEPTED');assert.equal(out.pollStatus,'SAMPLE_PARTIAL');
 await assert.rejects(()=>monitorRequest('https://example.com',sess,'status',false,async()=>reply({id:ID,mode:'TEST',expiresAt:'2026-10-27T02:00:00Z',status:'TRACKING',deliveryStatus:'SECRET',pollStatus:'SAMPLE_PARTIAL'})));
});
test('restored cancelled monitor preserves unknown delivery result after restart',async()=>{
 const session={...identity,server:'https://example.com',accessToken:KEY};
 const result=await monitorRequest(session.server,session,'status',false,async()=>reply({id:ID,mode:'TEST',expiresAt:'2026-10-27T02:00:00Z',status:'CANCELLED',deliveryStatus:'UNKNOWN',pollStatus:'NOT_POLLED'}));
 assert.deepEqual(result,{status:'CANCELLED',mode:'TEST',expiresAt:'2026-10-27T02:00:00Z',deliveryStatus:'UNKNOWN',pollStatus:'NOT_POLLED'});
});
test('Firebase configuration is opt-in at build time',()=>{
 const config=require('../app.config');const original=process.env.GOOGLE_SERVICES_JSON;
 try {delete process.env.GOOGLE_SERVICES_JSON;assert.equal(config({config:{android:{package:'com.yuilyoung.subwayalert'}}}).android.googleServicesFile,undefined);
 process.env.GOOGLE_SERVICES_JSON='/private/google-services.json';assert.equal(config({config:{android:{package:'com.yuilyoung.subwayalert'}}}).android.googleServicesFile,'/private/google-services.json');}
 finally {if(original===undefined)delete process.env.GOOGLE_SERVICES_JSON;else process.env.GOOGLE_SERVICES_JSON=original;}
});
test('monitor requests require an explicit redirect-safe transport',async()=>{
 await assert.rejects(()=>startMonitor('https://example.com',{...identity,train,previousStation:'선릉',destinationStation:'삼성',fcmToken:'token',accessToken:KEY},false,undefined,now),/전송/);
});
test('restored sessions and rotated tokens require re-registration',()=>{
 const {needsRegistration}=require('../src/monitorApi');
 assert.equal(needsRegistration({id:'active'},null,null),true);
 assert.equal(needsRegistration({id:'active'},'old','new'),true);
 assert.equal(needsRegistration({id:'active'},'old','old'),false);
 assert.equal(needsRegistration(null,null,'new'),false);
});
test('ambiguous POST failure warns it may already have been processed',async()=>{
 await assert.rejects(()=>startMonitor('https://example.com',{...identity,train,previousStation:'선릉',destinationStation:'삼성',fcmToken:'token',accessToken:KEY},false,async()=>{throw new Error('timeout')},now),/처리되었을 수/);
});
test('stale token cancellation clears local secret only after server confirms terminal state',async()=>{
 const {cancelStaleSession}=require('../src/monitorApi');let deleted=false;
 const session={id:'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',sessionToken:'secret',server:'https://example.com',accessToken:KEY};
 await assert.rejects(()=>cancelStaleSession(session,false,async()=>{throw Error('offline')},async()=>{deleted=true}));assert.equal(deleted,false);
 await assert.rejects(()=>cancelStaleSession(session,false,async()=>reply({id:ID,mode:'TEST',expiresAt:'2026-10-27T02:00:00Z',status:'TRACKING'}),async()=>{deleted=true}));assert.equal(deleted,false);
 await cancelStaleSession(session,false,async()=>reply({id:ID,mode:'TEST',expiresAt:'2026-10-27T02:00:00Z',status:'CANCELLED'}),async()=>{deleted=true});assert.equal(deleted,true);
});

test('monitor requests require both credentials and keep the API key out of body and URL',async()=>{
 let sent;
 const value=await startMonitor('https://example.com',{...identity,train,previousStation:'선릉',destinationStation:'삼성',fcmToken:'native-token',accessToken:KEY},false,async(url,options)=>{sent={url,options};return reply({id:'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',sessionToken:SECRET,status:'TRACKING',mode:'TEST',expiresAt:'2026-10-27T01:00:00Z'});},now);
 assert.equal(sent.options.headers.Authorization,`Bearer ${KEY}`);
 assert.ok(!sent.options.body.includes(KEY));assert.ok(!sent.url.includes(KEY));
 assert.equal(value.accessToken,KEY);
 await monitorRequest(value.server,value,'status',false,async(url,options)=>{sent={url,options};return reply({id:ID,mode:'TEST',expiresAt:'2026-10-27T02:00:00Z',status:'TRACKING'});});
 assert.equal(sent.options.headers.Authorization,`Bearer ${KEY}`);
 assert.equal(sent.options.headers['X-Session-Token'],SECRET);
});

test('a saved session cannot send credentials to another origin',async()=>{
 let calls=0;
 const saved={id:'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',sessionToken:'secret',server:'https://old.example',accessToken:KEY};
 await assert.rejects(()=>monitorRequest('https://new.example',saved,'cancel',false,async()=>{calls++;return reply({id:ID,mode:'TEST',expiresAt:'2026-10-27T02:00:00Z',status:'CANCELLED'});}));
 assert.equal(calls,0);
});

test('explicit auth denial on a mutation stays actionable and preserves cancellation secrets',async()=>{
 const {cancelStaleSession}=require('../src/monitorApi');let deleted=false;
 const saved={id:'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',sessionToken:'secret',server:'https://example.com',accessToken:KEY};
 await assert.rejects(()=>cancelStaleSession(saved,false,async()=>reply({},401),async()=>{deleted=true;}),/접근 키/);
 assert.equal(deleted,false);
});

test('registration confirmation cannot follow a changed connection before or during permission',async()=>{
 const {startConfirmedMonitor}=require('../src/monitorApi');
 const confirmed={server:'https://old.example',accessToken:KEY};
 const replacement={server:'https://new.example',accessToken:'B'.repeat(43)};
 const selection={...identity,train,previousStation:'선릉',destinationStation:'삼성'};
 let current=replacement,grants=0,requests=0;
 const transport=async()=>{requests++;return reply({});};
 const grant=async()=>{grants++;current=replacement;return 'native-token';};
 await assert.rejects(()=>startConfirmedMonitor(confirmed,()=>current,selection,grant,false,transport,()=>now),/연결 정보/);
 assert.equal(grants,0);assert.equal(requests,0);
 current=confirmed;
 await assert.rejects(()=>startConfirmedMonitor(confirmed,()=>current,selection,grant,false,transport,()=>now),/연결 정보/);
 assert.equal(grants,1);assert.equal(requests,0);
});

test('confirmed registration submits to its original origin after notification permission',async()=>{
 const {startConfirmedMonitor}=require('../src/monitorApi');
 const confirmed={server:'https://old.example',accessToken:KEY};let calls=0;
 const result=await startConfirmedMonitor(confirmed,()=>confirmed,{...identity,train,previousStation:'선릉',destinationStation:'삼성'},async()=>'native-token',false,async(url,options)=>{
  calls++;assert.equal(url,'https://old.example/api/monitor-sessions');
  assert.equal(options.headers.Authorization,`Bearer ${KEY}`);
  return reply({id:'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',sessionToken:SECRET,status:'TRACKING',mode:'TEST',expiresAt:'2026-10-27T01:00:00Z'});
 },()=>now,async()=>identity);
 assert.equal(calls,1);assert.equal(result.fcmToken,'native-token');assert.equal(result.created.server,'https://old.example');
});


test('registration rejects mismatched identity, unknown states and malformed expiry without hiding a conflict',async()=>{
 const options={...identity,train,previousStation:'선릉',destinationStation:'삼성',fcmToken:'native-token',accessToken:KEY};
 const valid={...identity,status:'TRACKING',mode:'TEST',expiresAt:'2026-10-27T02:00:00Z'};
 for(const override of [{id:'d9ee7169-01cf-4e7e-bc6b-cbd706b3f362'},{sessionToken:'cd'.repeat(32)},{status:'MADE_UP'},{expiresAt:'tomorrow'},{expiresAt:'2026-10-27T02:00:00'}]) {
  await assert.rejects(()=>startMonitor('https://example.com',options,false,async()=>reply({...valid,...override}),now),/응답/);
 }
 let requests=0;
 await assert.rejects(()=>startMonitor('https://example.com',options,false,async()=>{requests++;return reply({},409)},now),e=>e.status===409&&/조회.*종료/.test(e.message)&&!e.message.includes(SECRET));
 assert.equal(requests,1);
});

test('status and cancellation validate current state identity mode and expiry before trusting a response',async()=>{
 const session={...identity,server:'https://example.com',accessToken:KEY};
 const value={id:ID,status:'TRACKING',mode:'TEST',expiresAt:'2026-10-27T02:00:00Z'};
 for(const override of [{status:'MADE_UP'},{id:'d9ee7169-01cf-4e7e-bc6b-cbd706b3f362'},{mode:'LIVE'},{expiresAt:'later'},{expiresAt:'2026-10-27T02:00:00'},{expiresAt:null}]){
  await assert.rejects(()=>monitorRequest(session.server,session,'status',false,async()=>reply({...value,...override})),/응답/);
 }
});

test('registration rejects invalid client identities and oversize train identifiers before HTTP',async()=>{
 let calls=0;const fetch=async()=>{calls++;return reply({});};
 const options={...identity,train,previousStation:'선릉',destinationStation:'삼성',fcmToken:'native',accessToken:KEY};
 for(const override of [{id:ID.toUpperCase()},{id:'c9ee7169-01cf-1e7e-bc6b-cbd706b3f362'},{sessionToken:SECRET.toUpperCase()},{sessionToken:'ab'.repeat(31)},{train:{...train,trainId:'x'.repeat(65)}}])await assert.rejects(()=>startMonitor('https://example.com',{...options,...override},false,fetch,now));
 assert.equal(calls,0);
});
