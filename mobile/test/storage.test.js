const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createStorage}=require('../src/storage');
test('late task progress cannot restore cancelled trip or overwrite favorites', async()=>{
 const map=new Map(); const mem={getItem:async k=>map.get(k)||null,setItem:async(k,v)=>map.set(k,v)}; const store=createStorage(mem);
 await store.writeConfig({favorites:[{id:'a'}],active:{id:'trip-1'}});
 const old=await store.readConfig();
 await store.writeConfig({favorites:[{id:'b'}],active:null});
 await store.writeProgress(old.active.id,{completed:true});
 assert.deepEqual(await store.readState(),{favorites:[{id:'b'}],active:null});
});
test('completed progress is scoped to the trip ID',async()=>{
 const map=new Map(); const mem={getItem:async k=>map.get(k)||null,setItem:async(k,v)=>map.set(k,v)};const store=createStorage(mem);
 await store.writeConfig({active:{id:'old'}});await store.writeProgress('old',{completed:true});
 assert.equal((await store.readState()).active,null);
 await store.writeConfig({active:{id:'new'}});assert.equal((await store.readState()).active.id,'new');
});
