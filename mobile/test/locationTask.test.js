const test = require('node:test');
const assert = require('node:assert/strict');
const { createStorage } = require('../src/storage');
const { createLocationTask } = require('../src/locationTask');

const monday = new Date(2026, 9, 26, 8).getTime();
const outside = { coords: {latitude:37.5088,longitude:127.063,accuracy:10}, timestamp:monday-15000 };
const inside = { coords: {latitude:37.5045,longitude:127.049,accuracy:10}, timestamp:monday };
const trip = {id:'local-trip',from:'samsung',to:'yeoksam'};
const favorite = {...trip, id:'fav',enabled:true,schedule:{days:[1],start:'07:00',end:'09:00'}};

async function setup(config, notify = async () => {}, onStop = async () => {}) {
 const data=new Map();
 const storage={getItem:async key=>data.get(key)??null,setItem:async (key,value)=>data.set(key,value)};
 const store=createStorage(storage);
 await store.writeConfig(config);
 let stopped=0, running=true;
 const {handleLocations:task,runExclusive}=createLocationTask({storage,store,notify,stopMonitoring:async()=>{if(running){await onStop();stopped++;running=false;}},now:()=>monday});
 return {task,store,runExclusive,stopped:()=>stopped};
}

test('batched locations preserve entry into the previous station and overlapping updates finish the trip once', async () => {
 let alerts=0;
 const {task,store,stopped}=await setup({active:trip},async()=>{alerts++;});
 await Promise.all([task([outside,inside]),task([inside])]);
 assert.equal(alerts,1);
 assert.equal((await store.readState()).active,null);
 assert.equal(stopped(),1);
});

test('a native trip notification failure keeps the trip available for a later fix', async () => {
 let attempts=0;
 const {task,store}=await setup({active:trip},async()=>{if(++attempts===1)throw Error('unavailable');});
 await task([outside]);
 await assert.rejects(()=>task([inside]),/unavailable/);
 assert.equal((await store.readState()).active.id,trip.id);
 await task([inside]);
 assert.equal(attempts,2);
 assert.equal((await store.readState()).active,null);
});

test('commute suggestions reject undated fixes and retry after a failed notification', async () => {
 let attempts=0;
 const {task}=await setup({automation:true,favorites:[favorite]},async()=>{if(++attempts===1)throw Error('unavailable');});
 await task([{coords:outside.coords}]);
 assert.equal(attempts,0);
 await assert.rejects(()=>task([outside]),/unavailable/);
 await Promise.all([task([outside]),task([outside])]);
 assert.equal(attempts,2);
});

test('a fix captured before route start or before the latest processed fix cannot arm the trip', async () => {
 let alerts=0;
 const {task,store}=await setup({active:{...trip,startedAt:monday-1000}},async()=>{alerts++;});
 await task([outside,inside]);
 await task([{...outside,timestamp:monday-500}]);
 await task([{...inside,timestamp:monday+1000}]);
 assert.equal(alerts,0);
 assert.equal((await store.readState()).active.id,trip.id);
});

test('a finishing location task releases the service before a new route operation may start it', async () => {
 let release;
 const wait=new Promise(resolve=>{release=resolve;});
 let notifying;
 const started=new Promise(resolve=>{notifying=resolve;});
 const services=[];
 const {task,runExclusive}=await setup({active:trip},async()=>{notifying();await wait;},async()=>{services.push('stop');});
 const completion=task([outside,inside]);
 await started;
 const replacing=runExclusive(async()=>{services.push('start');});
 release();
 await Promise.all([completion,replacing]);
 assert.deepEqual(services,['stop','start']);
});

test('replacement configuration saved while scheduling an alert keeps its location service',async()=>{
 let settings;
 const {task,store,stopped}=await setup({active:trip},async()=>{
  await settings.writeConfig({active:{...trip,id:'next'}});
 });
 settings=store;
 await task([outside,inside]);
 assert.equal((await store.readState()).active.id,'next');
 assert.equal(stopped(),0);
});

test('a failed native stop gets another attempt when the service sends more fixes',async()=>{
 let stops=0,alerts=0;
 const {task}=await setup({active:trip},async()=>{alerts++;},async()=>{if(++stops===1)throw Error('stop failed');});
 await assert.rejects(()=>task([outside,inside]),/stop failed/);
 await task([inside]);
 assert.equal(stops,2);
 assert.equal(alerts,1);
});

test('Android sends local alerts on the route notification channel configured for the user',async()=>{
 const {scheduleLocationNotification}=require('../src/locationTask');
 let request;
 const notifications={AndroidNotificationPriority:{HIGH:'high'},scheduleNotificationAsync:async input=>{request=input;}};
 await scheduleLocationNotification(notifications,'제목','내용');
 assert.equal(request.trigger?.channelId,'default');
 assert.equal(request.content.title,'제목');
 assert.equal(request.content.body,'내용');
});
