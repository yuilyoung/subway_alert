const {test} = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const d = require(path.join(process.env.CORE_OUT, 'favorites.js'));
const station = (id) => ({id, lineId: '1002', name: id, topisId: id, latitude: null, longitude: null});
const favorite = (id) => ({id, label: `경로 ${id}`, origin: station('A'), destination: station('D'+id), direction: '0', enabled: false, days: [1,2,3,4,5], start: '07:00', end: '10:00'});
test('stores up to five favorites without mutating the source', () => {
  let list = [];
  for (let i=0;i<5;i++) {const old=list; list=d.upsertFavorite(list, favorite(String(i))); assert.equal(old.length,i);}
  assert.equal(list.length,5);
  assert.throws(() => d.upsertFavorite(list, favorite('6')), /5/);
});
test('editing a favorite at the limit does not consume a slot', () => {
  const list=Array.from({length:5},(_,i)=>favorite(String(i)));
  assert.equal(d.upsertFavorite(list,{...list[2],label:'퇴근'}).length,5);
  assert.equal(d.upsertFavorite(list,{...list[2],label:'퇴근'})[2].label,'퇴근');
});
test('rejects duplicate routes under different IDs', () => {
  const f=favorite('1'); assert.throws(()=>d.upsertFavorite([f],{...f,id:'other'}),/이미/);
});
test('rejects invalid routes, schedules and unidentified free text', () => {
  for(const patch of [{destination:station('A')},{direction:'2'},{days:[]},{days:[8]},{days:[1,1]},{start:'24:00'},{end:'7:30'},{start:'07:00',end:'07:00'},{origin:{...station('A'),id:''}},{label:' '}]) {
    assert.throws(()=>d.upsertFavorite([],{...favorite('a'),...patch}));
  }
  assert.throws(()=>d.upsertFavorite([],{...favorite('a'),destination:{...station('Z'),lineId:'1003'}}),/동일/);
});
test('auto commute requires known coordinates', () => {
  assert.throws(()=>d.upsertFavorite([],{...favorite('1'),enabled:true}),/좌표/);
  const f={...favorite('1'),enabled:true,origin:{...station('A'),latitude:37.5,longitude:127}};
  assert.equal(d.upsertFavorite([],f)[0].enabled,true);
});
test('search normalization preserves meaningful station names', () => {
  assert.equal(d.normalizeQuery('  서울  역  '),'서울 역');
  assert.equal(d.normalizeQuery('아차산(어린이대공원후문)'),'아차산(어린이대공원후문)');
});
