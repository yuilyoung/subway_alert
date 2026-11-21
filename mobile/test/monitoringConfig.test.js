const test=require('node:test');
const assert=require('node:assert/strict');
const {createStorage,updateMonitoringConfig}=require('../src/storage');

test('a failed trip configuration write stops a newly enabled location service',async()=>{
 const events=[];
 const store=createStorage({getItem:async()=>null,setItem:async()=>{throw Error('storage full');}});
 await assert.rejects(()=>updateMonitoringConfig(store,()=>({active:{id:'trip'}}),{
  enable:async()=>events.push('start'),disable:async()=>events.push('stop')
 }),/storage full/);
 assert.deepEqual(events,['start','stop']);
});

test('a failed replacement leaves an existing route service running',async()=>{
 const events=[];
 const store=createStorage({getItem:async key=>key.includes('config')?JSON.stringify({active:{id:'existing'}}):null,
  setItem:async()=>{throw Error('storage full');}});
 await assert.rejects(()=>updateMonitoringConfig(store,()=>({active:{id:'replacement'}}),{
  enable:async()=>events.push('start'),disable:async()=>events.push('stop')
 }),/storage full/);
 assert.deepEqual(events,['start']);
});

test('removing or disabling the last enabled commute favorite stops automation and keeps an active trip running', async () => {
 const favorite={id:'fav',from:'samsung',to:'gangnam',enabled:true,schedule:{days:[1],start:'07:00',end:'09:00'}};
 for (const favorites of [[],[{...favorite,enabled:false}]]) {
  for (const active of [null,{id:'trip',from:'samsung',to:'gangnam'}]) {
   const data=new Map();
   const store=createStorage({getItem:async key=>data.get(key)??null,setItem:async (key,value)=>data.set(key,value)});
   await store.writeConfig({favorites:[favorite],automation:true,active});
   let stops=0;
   await updateMonitoringConfig(store,s=>({...s,favorites}),{enable:async()=>assert.fail('unexpected start'),disable:async()=>{stops++;}});
   assert.equal((await store.readConfig()).automation,false);
   assert.deepEqual((await store.readState()).active,active);
   assert.equal(stops,active?0:1);
  }
 }
});

test('a stored commute setting without an enabled favorite is inactive after upgrade', async () => {
 const store=createStorage({getItem:async()=>JSON.stringify({favorites:[],automation:true,active:null})});
 assert.equal((await store.readState()).automation,false);
});
