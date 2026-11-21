const KEY='@subway-alert/config-v2';
const progressKey=id=>`@subway-alert/trip/${id}`;
const suggestionKey=id=>`@subway-alert/suggestion/${id}`;
const READ_ERROR='저장된 경로 정보를 읽지 못했습니다. 저장 상태를 확인하고 다시 시도하세요.';

function withEnabledCommute(config) {
 if(config.automation && !config.favorites?.some(favorite=>favorite.enabled))return {...config,automation:false};
 return config;
}

function createStorage(storage){
 async function readJson(key){
  try {
   const raw=await storage.getItem(key);
   if(raw===null)return {};
   const value=JSON.parse(raw);
   if(!value || typeof value!=='object' || Array.isArray(value))throw Error();
   return value;
  } catch (_) {throw new Error(READ_ERROR);}
 }
 async function readConfig(){
  const config=await readJson(KEY);
  if('favorites' in config && (!Array.isArray(config.favorites) || !config.favorites.every(f=>
   f && typeof f.id==='string' && typeof f.from==='string' && typeof f.to==='string' &&
   typeof f.schedule?.start==='string' && typeof f.schedule?.end==='string' &&
   Array.isArray(f.schedule.days))))throw new Error(READ_ERROR);
  return config;
 }
 async function writeConfig(s){await storage.setItem(KEY,JSON.stringify(s))}
 async function readProgress(id){return readJson(progressKey(id))}
 async function writeProgress(id,p){await storage.setItem(progressKey(id),JSON.stringify(p))}
 async function readState(){
  const config=withEnabledCommute(await readConfig());
  if(config.active?.id && (await readProgress(config.active.id)).completed)config.active=null;
  return config;
 }
 return {readConfig,writeConfig,readProgress,writeProgress,readState};
}
async function updateMonitoringConfig(store,change,{enable,disable}){
 const current=await store.readState();
 const next=withEnabledCommute(change(current));
 const starting=(next.automation && !current.automation) ||
  (next.active && next.active.id!==current.active?.id);
 if(starting)await enable();
 try {await store.writeConfig(next);}
 catch(error){
  if(starting && !current.automation && !current.active)await disable();
  throw error;
 }
 if(!next.automation && !next.active && (current.automation || current.active))await disable();
 return next;
}
module.exports={KEY,progressKey,suggestionKey,createStorage,updateMonitoringConfig};
