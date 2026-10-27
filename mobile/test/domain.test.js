const { test } = require('node:test');
const assert = require('node:assert/strict');
const { addFavorite, findRoute, shouldAlert, matchesSchedule } = require('../src/domain');

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
