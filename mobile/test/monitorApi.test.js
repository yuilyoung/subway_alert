const test=require('node:test');
const assert=require('node:assert/strict');
const {startMonitor,monitorRequest,validateSelection}=require('../src/monitorApi');
const now=Date.parse('2026-10-27T00:00:00Z');
const train={lineId:'2',trainId:'0021',direction:'INNER',station:'역삼',state:'ARRIVED',observedAt:new Date(now).toISOString(),express:false};
function reply(data,status=200){return {ok:status>=200&&status<300,status,json:async()=>data}}
test('starts only a clearly marked test session preserving leading zero and submits native token in body',async()=>{
 let call;
 const session=await startMonitor('https://example.com',{train,previousStation:'선릉',destinationStation:'삼성',fcmToken:'device-secret'},false,async(url,options)=>{call={url,options};return reply({id:'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',sessionToken:'secret-session-token',status:'TRACKING',mode:'TEST',expiresAt:'2026-10-27T01:00:00Z'})},now);
 assert.equal(call.url,'https://example.com/api/monitor-sessions');assert.equal(call.options.method,'POST');
 assert.deepEqual(JSON.parse(call.options.body),{lineId:'2',trainId:'0021',direction:'INNER',previousStation:'선릉',destinationStation:'삼성',fcmToken:'device-secret',mode:'TEST'});
 assert.equal(session.sessionToken,'secret-session-token');
});
test('requires fresh, ordinary train and distinct explicit stations',()=>{
 assert.throws(()=>validateSelection({...train,observedAt:'2026-10-26T23:00:00Z'},'선릉','삼성',now));
 assert.throws(()=>validateSelection({...train,express:true},'선릉','삼성',now));
 assert.throws(()=>validateSelection(train,'선릉','선릉',now));
});
test('sends secret in header, never URL, and rejects unsafe origins',async()=>{
 let call;
 await monitorRequest('https://example.com',{id:'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',sessionToken:'abc-secret'},'status',false,async(url,options)=>{call={url,options};return reply({status:'TRACKING'})});
 assert.equal(call.options.headers['X-Session-Token'],'abc-secret');assert.ok(!call.url.includes('abc-secret'));
 await assert.rejects(()=>monitorRequest('http://evil.example',{id:'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',sessionToken:'secret'},'status',false,async()=>reply({})));
});
test('network failures are sanitized and malformed sessions rejected',async()=>{
 await assert.rejects(()=>startMonitor('https://example.com',{train,previousStation:'선릉',destinationStation:'삼성',fcmToken:'device-secret'},false,async()=>{throw Error('device-secret')},now), e=>!e.message.includes('device-secret'));
 await assert.rejects(()=>startMonitor('https://example.com',{train,previousStation:'선릉',destinationStation:'삼성',fcmToken:'device-secret'},false,async()=>reply({id:'x',sessionToken:'',mode:'LIVE'}),now));
});
test('test result preserves only recognized delivery and polling states',async()=>{
 const sess={id:'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',sessionToken:'token'};
 const out=await monitorRequest('https://example.com',sess,'test',false,async()=>reply({status:'TRACKING',deliveryStatus:'FCM_ACCEPTED',pollStatus:'SAMPLE_PARTIAL'}));
 assert.equal(out.deliveryStatus,'FCM_ACCEPTED');assert.equal(out.pollStatus,'SAMPLE_PARTIAL');
 await assert.rejects(()=>monitorRequest('https://example.com',sess,'status',false,async()=>reply({status:'TRACKING',deliveryStatus:'SECRET',pollStatus:'SAMPLE_PARTIAL'})));
});
test('Firebase configuration is opt-in at build time',()=>{
 const config=require('../app.config');const original=process.env.GOOGLE_SERVICES_JSON;
 try {delete process.env.GOOGLE_SERVICES_JSON;assert.equal(config({config:{android:{package:'com.yuilyoung.subwayalert'}}}).android.googleServicesFile,undefined);
 process.env.GOOGLE_SERVICES_JSON='/private/google-services.json';assert.equal(config({config:{android:{package:'com.yuilyoung.subwayalert'}}}).android.googleServicesFile,'/private/google-services.json');}
 finally {if(original===undefined)delete process.env.GOOGLE_SERVICES_JSON;else process.env.GOOGLE_SERVICES_JSON=original;}
});
test('monitor requests require an explicit redirect-safe transport',async()=>{
 await assert.rejects(()=>startMonitor('https://example.com',{train,previousStation:'선릉',destinationStation:'삼성',fcmToken:'token'},false,undefined,now),/전송/);
});
test('restored sessions and rotated tokens require re-registration',()=>{
 const {needsRegistration}=require('../src/monitorApi');
 assert.equal(needsRegistration({id:'active'},null,null),true);
 assert.equal(needsRegistration({id:'active'},'old','new'),true);
 assert.equal(needsRegistration({id:'active'},'old','old'),false);
 assert.equal(needsRegistration(null,null,'new'),false);
});
test('ambiguous POST failure warns it may already have been processed',async()=>{
 await assert.rejects(()=>startMonitor('https://example.com',{train,previousStation:'선릉',destinationStation:'삼성',fcmToken:'token'},false,async()=>{throw new Error('timeout')},now),/처리되었을 수/);
});
test('stale token cancellation clears local secret only after server confirms terminal state',async()=>{
 const {cancelStaleSession}=require('../src/monitorApi');let deleted=false;
 const session={id:'c9ee7169-01cf-4e7e-bc6b-cbd706b3f362',sessionToken:'secret',server:'https://example.com'};
 await assert.rejects(()=>cancelStaleSession(session,false,async()=>{throw Error('offline')},async()=>{deleted=true}));assert.equal(deleted,false);
 await assert.rejects(()=>cancelStaleSession(session,false,async()=>reply({status:'TRACKING'}),async()=>{deleted=true}));assert.equal(deleted,false);
 await cancelStaleSession(session,false,async()=>reply({status:'CANCELLED'}),async()=>{deleted=true});assert.equal(deleted,true);
});
