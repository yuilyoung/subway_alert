const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createCommuteSuggester}=require('../src/commuteSuggestions');
const {createStorage,suggestionKey}=require('../src/storage');
const stations=require('../src/stations');

const local=(day,hour,minute=0)=>new Date(2026,9,day,hour,minute);
const favorite=(overrides={})=>({id:'morning',from:'samsung',to:'gyodae',enabled:true,schedule:{days:[0],start:'23:00',end:'01:00'},...overrides});
async function fixture({favorites=[favorite()],automation=true,active=null,date=local(25,23,59),notify}={}) {
  const map=new Map(),hooks={},notifications=[];
  let clock=date;
  const storage={
    async getItem(key) {
      const value=map.get(key) ?? null;
      if (key.startsWith('@subway-alert/suggestion/') && hooks.read) await hooks.read(key,value);
      return value;
    },
    async setItem(key,value) {
      if (key.startsWith('@subway-alert/suggestion/') && hooks.beforeWrite) await hooks.beforeWrite(key,value);
      map.set(key,value);
      if (key.startsWith('@subway-alert/suggestion/') && hooks.afterWrite) await hooks.afterWrite(key,value);
    }
  };
  const store=createStorage(storage);
  await store.writeConfig({favorites,automation,active});
  const point=()=>({latitude:37.5088,longitude:127.0630,accuracy:10,timestamp:clock.getTime()});
  const suggest=createCommuteSuggester({store,storage,stations,now:()=>new Date(clock),notify:async(title,body)=>{
    if (notify) await notify(title,body);
    notifications.push({title,body});
  }});
  return {map,hooks,storage,store,point,suggest,notifications,setDate:value=>{clock=value;}};
}

test('one overnight occurrence is claimed before notify and stays claimed after midnight',async()=>{
  const f=await fixture();
  f.hooks.afterWrite=async()=>assert.equal(f.notifications.length,0);
  assert.equal(await f.suggest(f.point()),true);
  assert.deepEqual(JSON.parse(f.map.get(suggestionKey('morning'))),{version:1,claims:['2026-10-25|23:00|01:00']});
  assert.match(f.notifications[0].body,/삼성 → 교대/);
  f.setDate(local(26,0,1));
  assert.equal(await f.suggest(f.point()),false);
  assert.equal(f.notifications.length,1);
});

test('the next selected overnight occurrence can issue another suggestion',async()=>{
  const f=await fixture();
  await f.suggest(f.point());
  f.setDate(new Date(2026,10,1,23,1));
  assert.equal(await f.suggest(f.point()),true);
  assert.deepEqual(JSON.parse(f.map.get(suggestionKey('morning'))),{version:1,claims:['2026-11-01|23:00|01:00']});
  assert.equal(f.notifications.length,2);
});

test('a claimed favorite does not starve the next eligible favorite in the same event',async()=>{
  const f=await fixture({favorites:[favorite(),favorite({id:'second',to:'gangnam'})]});
  f.map.set(suggestionKey('morning'),'2026-10-25|23:00|01:00');
  assert.equal(await f.suggest(f.point()),true);
  assert.deepEqual(JSON.parse(f.map.get(suggestionKey('second'))),{version:1,claims:['2026-10-25|23:00|01:00']});
  assert.equal(f.notifications.length,1);
  assert.match(f.notifications[0].body,/삼성 → 강남/);
});

test('one event requests at most one notification even with multiple unclaimed candidates',async()=>{
  const f=await fixture({favorites:[favorite(),favorite({id:'second',to:'gangnam'})]});
  assert.equal(await f.suggest(f.point()),true);
  assert.equal(f.notifications.length,1);
  assert.equal(f.map.has(suggestionKey('second')),false);
});

test('legacy daily markers suppress their current day or overnight start day',async t=>{
  for (const marker of ['2026-10-25','2026-10-26']) await t.test(marker,async()=>{
    const f=await fixture({date:local(26,0,1)});
    f.map.set(suggestionKey('morning'),marker);
    assert.equal(await f.suggest(f.point()),false);
    assert.equal(f.notifications.length,0);
  });
});

test('disabled and invalid favorites are skipped without blocking a later valid route',async()=>{
  const f=await fixture({favorites:[
    favorite({id:'disabled',enabled:false}),
    favorite({id:'unknown',to:'missing'}),
    favorite({id:'same',to:'samsung'}),
    favorite({id:'bad-days',schedule:{days:[],start:'23:00',end:'01:00'}}),
    favorite({id:'bad-time',schedule:{days:[0],start:'29:00',end:'01:00'}}),
    favorite({id:'outside',from:'gyodae',to:'gangnam'}),
    favorite({id:'valid'})
  ]});
  assert.equal(await f.suggest(f.point()),true);
  assert.equal(f.map.has(suggestionKey('valid')),true);
  assert.equal(f.notifications.length,1);
});

test('active trips and disabled automation suppress suggestions',async t=>{
  for (const config of [{active:{id:'trip',from:'samsung',to:'gyodae'}},{automation:false}]) await t.test(JSON.stringify(config),async()=>{
    const f=await fixture(config);
    assert.equal(await f.suggest(f.point()),false);
    assert.equal(f.notifications.length,0);
    assert.equal(f.map.has(suggestionKey('morning')),false);
  });
});

test('a completed persisted trip does not block later commute suggestions',async()=>{
  const f=await fixture({
    active:{id:'completed-trip',from:'samsung',to:'gyodae'},
    favorites:[favorite({schedule:{days:[3],start:'07:00',end:'09:00'}})],
    date:local(28,7,30)
  });
  await f.store.writeProgress('completed-trip',{completed:true});
  assert.equal((await f.store.readState()).active,null);
  assert.equal((await f.store.readConfig()).active.id,'completed-trip');
  assert.equal(await f.suggest(f.point()),true);
  assert.deepEqual(JSON.parse(f.map.get(suggestionKey('morning'))),{version:1,claims:['2026-10-28|07:00|09:00']});
  assert.equal(f.notifications.length,1);
});

test('unfresh, inaccurate or malformed locations cannot claim an occurrence',async t=>{
  const cases=[
    {accuracy:81},{accuracy:-1},{accuracy:NaN},{accuracy:null},
    {timestamp:local(25,23,58).getTime()},{timestamp:local(26,0,0).getTime()},
    {timestamp:NaN},{timestamp:undefined},{latitude:NaN},{longitude:NaN},
    {latitude:91},{longitude:181},{latitude:0,longitude:0}
  ];
  for (const fields of cases) await t.test(JSON.stringify(fields),async()=>{
    const f=await fixture();
    assert.equal(await f.suggest({...f.point(),...fields}),false);
    assert.equal(f.notifications.length,0);
    assert.equal(f.map.has(suggestionKey('morning')),false);
  });
});

const changes=[
  ['route edited',s=>({...s,favorites:[{...s.favorites[0],to:'gangnam'}]})],
  ['days edited while occurrence still matches',s=>({...s,favorites:[{...s.favorites[0],schedule:{...s.favorites[0].schedule,days:[0,1]}}]})],
  ['time edited while occurrence still matches',s=>({...s,favorites:[{...s.favorites[0],schedule:{...s.favorites[0].schedule,start:'22:00'}}]})],
  ['favorite disabled',s=>({...s,favorites:[{...s.favorites[0],enabled:false}]})],
  ['favorite deleted',s=>({...s,favorites:[]})],
  ['same route replaced under a new ID',s=>({...s,favorites:[{...s.favorites[0],id:'replacement'}]})],
  ['automation stopped',s=>({...s,automation:false})],
  ['active trip started',s=>({...s,active:{id:'trip',from:'samsung',to:'gyodae'}})]
];
for (const phase of ['read','afterWrite']) test(`configuration changes during marker ${phase} suppress the obsolete request`,async t=>{
  for (const [label,change] of changes) await t.test(label,async()=>{
    const f=await fixture();
    f.hooks[phase]=async()=>f.store.writeConfig(change(await f.store.readConfig()));
    assert.equal(await f.suggest(f.point()),false);
    assert.equal(f.notifications.length,0);
    assert.equal(f.map.has(suggestionKey('morning')),phase==='afterWrite');
  });
});

for (const phase of ['read','afterWrite']) test(`clock and point freshness are rechecked after marker ${phase}`,async t=>{
  const cases=[
    ['schedule expired',local(26,1)],
    ['point became stale',new Date(local(25,23,59).getTime()+30001)],
    ['clock moved before point timestamp',new Date(local(25,23,59).getTime()-5001)]
  ];
  for (const [label,date] of cases) await t.test(label,async()=>{
    const f=await fixture(),point=f.point();
    f.hooks[phase]=async()=>f.setDate(date);
    assert.equal(await f.suggest(point),false);
    assert.equal(f.notifications.length,0);
    assert.equal(f.map.has(suggestionKey('morning')),phase==='afterWrite');
  });
});

test('overlapping callbacks for one occurrence issue one notification',async()=>{
  const f=await fixture();
  const results=await Promise.all([f.suggest(f.point()),f.suggest(f.point()),f.suggest(f.point())]);
  assert.deepEqual(results,[true,false,false]);
  assert.equal(f.notifications.length,1);
});

function deferred() {
  let resolve;
  const promise=new Promise(r=>{resolve=r;});
  return {promise,resolve};
}

test('a queued location is revalidated when earlier notification work finishes',async()=>{
  const entered=deferred(),release=deferred();
  const f=await fixture({favorites:[favorite(),favorite({id:'second',to:'gangnam'})],notify:async()=>{
    entered.resolve();
    await release.promise;
  }});
  const point=f.point(),first=f.suggest(point);
  await entered.promise;
  const second=f.suggest(point);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.map.has(suggestionKey('second')),false);
  assert.equal(f.notifications.length,0);
  f.setDate(new Date(local(25,23,59).getTime()+30001));
  release.resolve();
  assert.deepEqual(await Promise.all([first,second]),[true,false]);
  assert.equal(f.notifications.length,1);
  assert.equal(f.map.has(suggestionKey('second')),false);
});

test('a marker write failure rejects without notifying and leaves the queue usable',async()=>{
  const f=await fixture();
  const failure=new Error('marker unavailable');
  f.hooks.beforeWrite=async()=>{throw failure;};
  await assert.rejects(f.suggest(f.point()),error=>error===failure);
  assert.equal(f.notifications.length,0);
  assert.equal(f.map.has(suggestionKey('morning')),false);
  delete f.hooks.beforeWrite;
  assert.equal(await f.suggest(f.point()),true);
  assert.equal(f.notifications.length,1);
});

test('a rejected notification keeps its marker and later events can use another favorite',async()=>{
  let fail=true;
  const failure=new Error('OS notification unavailable');
  const f=await fixture({favorites:[favorite(),favorite({id:'second',to:'gangnam'})],notify:async()=>{if(fail)throw failure;}});
  await assert.rejects(f.suggest(f.point()),error=>error===failure);
  assert.deepEqual(JSON.parse(f.map.get(suggestionKey('morning'))),{version:1,claims:['2026-10-25|23:00|01:00']});
  assert.equal(f.notifications.length,0);
  fail=false;
  assert.equal(await f.suggest(f.point()),true);
  assert.equal(f.map.has(suggestionKey('second')),true);
  assert.equal(f.notifications.length,1);
  assert.equal(await f.suggest(f.point()),false);
});

test('editing A to B and back across midnight retains both consumed occurrences',async()=>{
  const f=await fixture({date:local(25,23,30)});
  assert.equal(await f.suggest(f.point()),true);
  await f.store.writeConfig({...await f.store.readConfig(),favorites:[favorite({schedule:{days:[0],start:'22:00',end:'02:00'}})]});
  assert.equal(await f.suggest(f.point()),true);
  f.setDate(local(26,0,30));
  await f.store.writeConfig({...await f.store.readConfig(),favorites:[favorite()]});
  assert.equal(await f.suggest(f.point()),false);
  assert.equal(f.notifications.length,2);
  assert.deepEqual(JSON.parse(f.map.get(suggestionKey('morning'))),{version:1,claims:[
    '2026-10-25|23:00|01:00','2026-10-25|22:00|02:00'
  ]});
});

test('history prunes only dates before the previous local day and retains future claims',async()=>{
  const f=await fixture();
  f.map.set(suggestionKey('morning'),JSON.stringify({version:1,claims:[
    '2026-10-23|22:00|02:00','2026-10-24|23:00|01:00','2026-10-25|22:00|02:00','2026-10-26|22:00|02:00'
  ]}));
  assert.equal(await f.suggest(f.point()),true);
  assert.deepEqual(JSON.parse(f.map.get(suggestionKey('morning'))),{version:1,claims:[
    '2026-10-24|23:00|01:00','2026-10-25|22:00|02:00','2026-10-26|22:00|02:00','2026-10-25|23:00|01:00'
  ]});
  assert.equal(f.notifications.length,1);
});

const liveClaims=()=>Array.from({length:128},(_,i)=>`2026-10-25|${String(Math.floor(i/60)).padStart(2,'0')}:${String(i%60).padStart(2,'0')}|23:59`);
test('a full live history is preserved and does not starve another favorite',async()=>{
  const f=await fixture({favorites:[favorite(),favorite({id:'second',to:'gangnam'})]});
  const raw=JSON.stringify({version:1,claims:liveClaims()});
  f.map.set(suggestionKey('morning'),raw);
  assert.equal(await f.suggest(f.point()),true);
  assert.equal(f.map.get(suggestionKey('morning')),raw);
  assert.deepEqual(JSON.parse(f.map.get(suggestionKey('second'))),{version:1,claims:['2026-10-25|23:00|01:00']});
  assert.equal(f.notifications.length,1);
  assert.match(f.notifications[0].body,/삼성 → 강남/);
});

test('one expired entry can make room at the cap without evicting any live claim',async()=>{
  const f=await fixture(),claims=liveClaims();
  claims[0]='2026-10-23|23:00|01:00';
  f.map.set(suggestionKey('morning'),JSON.stringify({version:1,claims}));
  assert.equal(await f.suggest(f.point()),true);
  const saved=JSON.parse(f.map.get(suggestionKey('morning')));
  assert.equal(saved.claims.length,128);
  assert.deepEqual(saved.claims,[...claims.slice(1),'2026-10-25|23:00|01:00']);
  assert.equal(f.notifications.length,1);
});

test('malformed or unknown histories stay untouched while another favorite remains eligible',async t=>{
  const a='2026-10-25|23:00|01:00';
  const cases=[
    '', '{broken', JSON.stringify({version:2,claims:[a]}), JSON.stringify({version:1,claims:null}),
    JSON.stringify({version:1,claims:[a,'unknown']}), JSON.stringify({version:1,claims:[a,a]}),
    JSON.stringify({version:1,claims:['2026-02-30|23:00|01:00']}),
    JSON.stringify({version:1,claims:['2026-10-25|25:00|01:00']}),
    JSON.stringify({version:1,claims:['2026-10-25|01:00|01:00']}),
    JSON.stringify({version:1,claims:[...liveClaims(),a]})
  ];
  for (const raw of cases) await t.test(raw.slice(0,90),async()=>{
    const f=await fixture({favorites:[favorite(),favorite({id:'second',to:'gangnam'})]});
    f.map.set(suggestionKey('morning'),raw);
    assert.equal(await f.suggest(f.point()),true);
    assert.equal(f.map.get(suggestionKey('morning')),raw);
    assert.equal(f.notifications.length,1);
    assert.match(f.notifications[0].body,/삼성 → 강남/);
  });
});

test('legacy occurrence and date markers migrate without losing still-live claims',async t=>{
  const cases=[
    ['2026-10-25|22:00|02:00',['2026-10-25|22:00|02:00','2026-10-25|23:00|01:00']],
    ['2026-10-24',['2026-10-24','2026-10-25|23:00|01:00']],
    ['2026-10-23',['2026-10-25|23:00|01:00']]
  ];
  for (const [raw,claims] of cases) await t.test(raw,async()=>{
    const f=await fixture();
    f.map.set(suggestionKey('morning'),raw);
    assert.equal(await f.suggest(f.point()),true);
    assert.deepEqual(JSON.parse(f.map.get(suggestionKey('morning'))),{version:1,claims});
    assert.equal(f.notifications.length,1);
  });
});

test('failed history persistence preserves prior claims and blocks notification',async()=>{
  const f=await fixture(),raw=JSON.stringify({version:1,claims:['2026-10-25|22:00|02:00']});
  f.map.set(suggestionKey('morning'),raw);
  f.hooks.beforeWrite=async()=>{throw new Error('history write failed');};
  await assert.rejects(f.suggest(f.point()),/history write failed/);
  assert.equal(f.map.get(suggestionKey('morning')),raw);
  assert.equal(f.notifications.length,0);
  delete f.hooks.beforeWrite;
  assert.equal(await f.suggest(f.point()),true);
  assert.deepEqual(JSON.parse(f.map.get(suggestionKey('morning'))),{version:1,claims:[
    '2026-10-25|22:00|02:00','2026-10-25|23:00|01:00'
  ]});
});
