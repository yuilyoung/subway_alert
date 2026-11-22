const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createRequire} = require('node:module');
const {compileFunction} = require('node:vm');
const {transformFileSync} = require('@babel/core');
const React = require('react');
const {create,act} = require('react-test-renderer');
const {KEY} = require('../src/storage');

// Load the production JSX and Expo task in Node, substituting the native bridges.
function loadComponentModule(filename, substitutes) {
 const {code} = transformFileSync(filename, {
  presets:['@react-native/babel-preset'], babelrc:false, configFile:false
 });
 const localRequire = createRequire(filename);
 const exports = {};
 compileFunction(code, ['require','exports'], {filename})(
  id => Object.hasOwn(substitutes,id) ? substitutes[id] : localRequire(id), exports
 );
 return exports;
}

test('the open App shows the trip ending when its registered Expo location task completes', async t => {
 globalThis.IS_REACT_ACT_ENVIRONMENT = true;
 t.after(()=>{ delete globalThis.IS_REACT_ACT_ENVIRONMENT; });
 const data = new Map([[KEY,JSON.stringify({active:{id:'ride',from:'samsung',to:'yeoksam'}})]]);
 let onLocation, onAppState, reads = 0;
 const notifications = {setNotificationHandler(){},AndroidNotificationPriority:{HIGH:'high'},scheduleNotificationAsync:async()=>{}};
 const background = loadComponentModule(require.resolve('../src/background'),{
  'expo-task-manager':{defineTask:(_name,callback)=>{onLocation=callback;}},
  'expo-location':{hasStartedLocationUpdatesAsync:async()=>false},
  'expo-notifications':notifications,
  '@react-native-async-storage/async-storage':{
   getItem:async key=>data.get(key)??null, setItem:async (key,value)=>{data.set(key,value);}
  }
 });
 const {default:App} = loadComponentModule(require.resolve('../App'),{
  'react-native':{
   SafeAreaView:'SafeAreaView',ScrollView:'ScrollView',Text:'Text',TextInput:'TextInput',
   TouchableOpacity:'TouchableOpacity',View:'View',StyleSheet:{create:styles=>styles},
   AppState:{addEventListener:(_event,callback)=>{onAppState=callback;return {remove(){}};}}
  },
  'expo-notifications':notifications, './src/LiveTrains':()=>null,
  './src/background':{...background,readState:async()=>{reads++;return background.readState();}}
 });
 let screen;
 await act(async()=>{screen=create(React.createElement(App));});
 const shows=text=>screen.root.findAllByType('Text').some(node=>node.children.includes(text));
 assert.ok(shows('감시 중: 삼성 → 역삼'));
 const now = Date.now();
 await act(async()=>{
  await onLocation({data:{locations:[
   {coords:{latitude:37.5088,longitude:127.063,accuracy:10},timestamp:now-15000},
   {coords:{latitude:37.5045,longitude:127.049,accuracy:10},timestamp:now}
  ]}});
  await background.runMonitoringOperation(()=>{});
 });
 assert.ok(shows('현재 진행 중인 경로 없음'));

 // A foreground refresh already queued behind native work must respect unmount.
 let release;
 const gate = new Promise(resolve=>{release=resolve;});
 const beforeUnmount = reads;
 const blocked = background.runMonitoringOperation(()=>gate);
 onAppState('active');
 await act(async()=>{screen.unmount();});
 release();
 await blocked;
 await background.runMonitoringOperation(()=>{});
 assert.equal(reads,beforeUnmount);
});
