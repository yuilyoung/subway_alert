const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createStorage, progressKey, suggestionKey } = require('../src/storage');
const { createCommuteSuggester } = require('../src/commuteSuggestions');
const stations = require('../src/stations');

const changes = [
  ['automation stops', (state) => ({ ...state, automation: false })],
  [
    'a new trip starts',
    (state) => ({ ...state, active: { id: 'new-trip', from: 'samsung', to: 'gyodae' } }),
  ],
  [
    'the schedule changes',
    (state) => ({
      ...state,
      favorites: [
        {
          ...state.favorites[0],
          schedule: { days: [3], start: '06:00', end: '09:00' },
        },
      ],
    }),
  ],
];

for (const [label, change] of changes)
  test(`${label} during final completed-progress read suppresses notification`, async () => {
    const map = new Map(),
      notifications = [];
    let store,
      progressReads = 0;
    const storage = {
      async getItem(key) {
        const value = map.get(key) ?? null;
        if (key === progressKey('completed-trip') && ++progressReads === 3) {
          await store.writeConfig(change(await store.readConfig()));
        }
        return value;
      },
      setItem: async (key, value) => map.set(key, value),
    };
    store = createStorage(storage);
    await store.writeConfig({
      automation: true,
      active: { id: 'completed-trip', from: 'samsung', to: 'gyodae' },
      favorites: [
        {
          id: 'morning',
          from: 'samsung',
          to: 'gyodae',
          enabled: true,
          schedule: { days: [3], start: '07:00', end: '09:00' },
        },
      ],
    });
    await store.writeProgress('completed-trip', { completed: true });
    const date = new Date(2026, 9, 28, 7, 30);
    const suggest = createCommuteSuggester({
      store,
      storage,
      stations,
      now: () => new Date(date),
      notify: async (title, body) => notifications.push({ title, body }),
    });
    const result = await suggest({
      latitude: 37.5088,
      longitude: 127.063,
      accuracy: 10,
      timestamp: date.getTime(),
    });
    assert.equal(progressReads, 3);
    assert.equal(map.has(suggestionKey('morning')), true);
    assert.equal(notifications.length, 0);
    assert.equal(result, false);
  });
