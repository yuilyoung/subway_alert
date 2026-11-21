const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createStorage}=require('../src/storage');
test('late task progress cannot restore cancelled trip or overwrite favorites', async()=>{
 const map=new Map(); const mem={getItem:async k=>map.get(k)||null,setItem:async(k,v)=>map.set(k,v)}; const store=createStorage(mem);
 const favorite={id:'a',from:'samsung',to:'gangnam',schedule:{days:[1],start:'07:00',end:'09:00'}};
 const replacement={...favorite,id:'b'};
 await store.writeConfig({favorites:[favorite],active:{id:'trip-1'}});
 const old=await store.readConfig();
 await store.writeConfig({favorites:[replacement],active:null});
 await store.writeProgress(old.active.id,{completed:true});
 assert.deepEqual(await store.readState(),{favorites:[replacement],active:null});
});
test('completed progress is scoped to the trip ID',async()=>{
 const map=new Map(); const mem={getItem:async k=>map.get(k)||null,setItem:async(k,v)=>map.set(k,v)};const store=createStorage(mem);
 await store.writeConfig({active:{id:'old'}});await store.writeProgress('old',{completed:true});
 assert.equal((await store.readState()).active,null);
 await store.writeConfig({active:{id:'new'}});assert.equal((await store.readState()).active.id,'new');
});

test('failed or corrupt local reads cannot masquerade as an empty configuration or trip', async () => {
 for (const getItem of [async()=>{throw Error('temporarily offline');},async()=>'{invalid',async()=>'[]',async()=>'null']) {
  const store=createStorage({getItem});
  await assert.rejects(()=>store.readConfig());
  await assert.rejects(()=>store.readProgress('trip-1'));
 }
 const empty=createStorage({getItem:async()=>null});
 assert.deepEqual(await empty.readState(),{});
});

test('invalid stored favorites cannot crash the route screen when restored', async () => {
 for(const favorites of [null,{},[null],[{id:'bad',schedule:null}]]){
  const store=createStorage({getItem:async()=>JSON.stringify({favorites})});
  await assert.rejects(()=>store.readState());
 }
});
