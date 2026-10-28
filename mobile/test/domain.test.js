const { test } = require('node:test');
const assert = require('node:assert/strict');
const { addFavorite, saveFavorite, findRoute, shouldAlert, matchesSchedule } = require('../src/domain');

test('favorites are limited to five and duplicates are rejected', () => {
  let f = []; for (let i=0; i<5; i++) f = addFavorite(f,{id:String(i),from:'a',to:String(i)});
  assert.equal(f.length,5);
  assert.throws(() => addFavorite(f,{id:'x',from:'a',to:'x'}), /5/);
  assert.throws(() => addFavorite(f,{id:'x',from:'a',to:'0'}), /이미/);
});
test('route finds preceding station in either direction', () => {
 const stations=[{id:'a'},{id:'b'},{id:'c'}];
 assert.equal(findRoute(stations,'a','c').previous.id,'b');
 assert.equal(findRoute(stations,'c','a').previous.id,'b');
 assert.equal(findRoute(stations,'a','a'),null);
});
test('location alert rejects stale and inaccurate readings and requires entering from outside', () => {
 const target={lat:37,lon:127}; const now=100000;
 assert.equal(shouldAlert({target,point:{latitude:37,longitude:127,accuracy:20,timestamp:now},now,wasOutside:true}),true);
 assert.equal(shouldAlert({target,point:{latitude:37,longitude:127,accuracy:200,timestamp:now},now,wasOutside:true}),false);
 assert.equal(shouldAlert({target,point:{latitude:37,longitude:127,accuracy:20,timestamp:1},now,wasOutside:true}),false);
 assert.equal(shouldAlert({target,point:{latitude:37,longitude:127,accuracy:20,timestamp:now},now,wasOutside:false}),false);
});
test('commute schedule matches weekday and time including midnight spans', () => {
 const mon = new Date(2026,9,26,23,30);
 assert.equal(matchesSchedule({days:[1],start:'23:00',end:'01:00'},mon),true);
 assert.equal(matchesSchedule({days:[1],start:'23:00',end:'01:00'},new Date(2026,9,27,0,30)),true);
 assert.equal(matchesSchedule({days:[2],start:'09:00',end:'10:00'},mon),false);
});

test('matchesSchedule rejects damaged weekdays and invalid dates instead of matching them', () => {
 const schedule = {days:[1],start:'07:00',end:'09:00'};
 assert.equal(matchesSchedule({...schedule,days:[1,1]},new Date(2026,9,26,8)),false);
 assert.equal(matchesSchedule(schedule,new Date(NaN)),false);
 assert.equal(matchesSchedule(schedule,null),false);
});

const morning = () => ({days:[1,2,3,4,5],start:'07:00',end:'09:00'});

test('saving a new favorite canonicalizes its schedule and defaults enabled without mutating drafts', () => {
 const favorites = [{id:'old',from:'a',to:'b',enabled:false,schedule:morning()}];
 const draft = {id:'new',from:'b',to:'a',schedule:{days:[0,1,5],start:'23:00',end:'01:00'}};
 const before = structuredClone({favorites,draft});
 const result = saveFavorite(favorites,draft);
 assert.deepEqual(result,[favorites[0],{
   id:'new',from:'b',to:'a',enabled:true,schedule:{days:[1,5,0],start:'23:00',end:'01:00'}
 }]);
 assert.deepEqual({favorites,draft},before);
 result[1].schedule.days.push(3);
 assert.deepEqual(draft.schedule.days,[0,1,5]);
 assert.equal(saveFavorite([],{...draft,enabled:false})[0].enabled,false);
});

test('editing at capacity keeps original identity disabled state metadata and every other favorite', () => {
 const favorites = Array.from({length:5},(_,i)=>({
   id:`id-${i}`,from:`from-${i}`,to:`to-${i}`,enabled:i!==2,schedule:morning(),note:`note-${i}`
 }));
 const before = structuredClone(favorites);
 const draft = {id:'replacement-id',from:'a',to:'b',enabled:true,note:'replace note',schedule:{days:[0],start:'23:00',end:'01:00'}};
 const result = saveFavorite(favorites,draft,'id-2');
 assert.equal(result.length,5);
 assert.deepEqual(result[2],{
   id:'id-2',from:'a',to:'b',enabled:false,note:'note-2',schedule:{days:[0],start:'23:00',end:'01:00'}
 });
 for (const i of [0,1,3,4]) assert.deepEqual(result[i],before[i]);
 assert.deepEqual(favorites,before);
 assert.deepEqual(draft.schedule.days,[0]);
 result[2].schedule.days.push(1);
 assert.deepEqual(draft.schedule.days,[0]);
 assert.deepEqual(favorites,before);
});

test('favorite additions require a unique nonempty ID and still enforce the capacity limit', () => {
 const favorites = Array.from({length:5},(_,i)=>({id:`id-${i}`,from:'a',to:`to-${i}`,enabled:true,schedule:morning()}));
 assert.throws(()=>saveFavorite(favorites,{id:'new',from:'b',to:'c',schedule:morning()}),/5/);
 for (const id of [undefined,null,'',' ',42]) {
   assert.throws(()=>saveFavorite([],{id,from:'a',to:'b',schedule:morning()}),/[가-힣]/);
 }
 assert.throws(()=>saveFavorite(favorites.slice(0,1),{id:'id-0',from:'b',to:'c',schedule:morning()}),/[가-힣]/);
});

test('saving rejects missing or identical endpoints and malformed schedules', () => {
 for (const [from,to] of [['','b'],['a',''],[' ','b'],[null,'b'],['a',undefined],['a','a'],[1,'b']]) {
   assert.throws(()=>saveFavorite([],{id:'new',from,to,schedule:morning()}),/[가-힣]/);
 }
 for (const schedule of [null,{...morning(),days:[]},{...morning(),days:[1,1]},
   {...morning(),start:'25:00'},{...morning(),end:'07:00'}]) {
   assert.throws(()=>saveFavorite([],{id:'new',from:'a',to:'b',schedule}),/[가-힣]/);
 }
});

test('duplicate other routes are rejected for additions and edits while unchanged self routes can save', () => {
 const favorites = [
   {id:'first',from:'a',to:'b',enabled:true,schedule:morning()},
   {id:'second',from:'b',to:'a',enabled:false,schedule:morning()}
 ];
 const before = structuredClone(favorites);
 assert.throws(()=>saveFavorite(favorites,{id:'new',from:'a',to:'b',schedule:morning()}),/이미/);
 assert.throws(()=>saveFavorite(favorites,{from:'a',to:'b',schedule:morning()},'second'),/이미/);
 const result = saveFavorite(favorites,{from:'a',to:'b',schedule:{days:[6],start:'10:00',end:'11:00'}},'first');
 assert.deepEqual(result[0],{...favorites[0],schedule:{days:[6],start:'10:00',end:'11:00'}});
 assert.deepEqual(favorites,before);
});

test('saving a deleted editing ID fails rather than registering a replacement', () => {
 const favorites = [{id:'kept',from:'a',to:'b',enabled:true,schedule:morning()}];
 const before = structuredClone(favorites);
 assert.throws(()=>saveFavorite(favorites,{id:'replacement',from:'b',to:'c',schedule:morning()},'deleted'),/[가-힣]/);
 assert.deepEqual(favorites,before);
 assert.equal(favorites.length,1);
});
