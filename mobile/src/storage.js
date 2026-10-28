const KEY='@subway-alert/config-v2';
const progressKey=id=>`@subway-alert/trip/${id}`;
const suggestionKey=id=>`@subway-alert/suggestion/${id}`;
function createStorage(storage){
 async function readJson(key){try{return JSON.parse(await storage.getItem(key))||{}}catch(_){return {}}}
 async function readConfig(){return readJson(KEY)}
 async function writeConfig(s){await storage.setItem(KEY,JSON.stringify(s))}
 async function readProgress(id){return readJson(progressKey(id))}
 async function writeProgress(id,p){await storage.setItem(progressKey(id),JSON.stringify(p))}
 async function readState(){
  const s=await readConfig(),id=s.active?.id;
  if(!id)return s;
  const progress=await readProgress(id),latest=await readConfig();
  if(latest.active?.id===id&&progress.completed)latest.active=null;
  return latest;
 }
 return {readConfig,writeConfig,readProgress,writeProgress,readState};
}
module.exports={KEY,progressKey,suggestionKey,createStorage};
