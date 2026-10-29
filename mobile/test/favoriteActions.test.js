const { test } = require('node:test');
const assert = require('node:assert/strict');
const { saveFavoriteDraft } = require('../src/favoriteActions');
const schedule = { days: [1, 2, 3, 4, 5], start: '07:00', end: '09:00' };
const draft = () => ({
  from: 'gangnam',
  to: 'samsung',
  schedule: { ...schedule, days: [...schedule.days] },
});

test('saving an edit reads latest config and preserves disabled ID, active trip and other favorites', async () => {
  const original = { id: 'favorite', ...draft(), enabled: false };
  const other = { id: 'other', from: 'seolleung', to: 'yeoksam', enabled: true, schedule };
  const latest = { automation: true, active: { id: 'trip' }, favorites: [original, other] };
  let written;
  const next = await saveFavoriteDraft(
    {
      readState: async () => latest,
      writeState: async (s) => {
        written = s;
      },
      createId: () => {
        throw Error('must not allocate ID for edit');
      },
    },
    { ...draft(), schedule: { days: [0], start: '23:00', end: '01:00' } },
    'favorite',
  );
  assert.equal(next, written);
  assert.equal(next.automation, true);
  assert.equal(next.active, latest.active);
  assert.equal(next.favorites[0].id, 'favorite');
  assert.equal(next.favorites[0].enabled, false);
  assert.deepEqual(next.favorites[0].schedule, { days: [0], start: '23:00', end: '01:00' });
  assert.deepEqual(next.favorites[1], other);
  assert.deepEqual(latest.favorites[0], original);
});

test('save captures the complete draft before asynchronous storage reads', async () => {
  let release;
  const wait = new Promise((resolve) => {
    release = resolve;
  });
  let written;
  const input = draft();
  const pending = saveFavoriteDraft(
    {
      readState: async () => {
        await wait;
        return { favorites: [] };
      },
      writeState: async (s) => {
        written = s;
      },
      createId: () => 'new-favorite',
    },
    input,
  );
  input.from = 'gyodae';
  input.schedule.days.push(0);
  input.schedule.start = '10:00';
  release();
  await pending;
  assert.equal(written.favorites[0].from, 'gangnam');
  assert.deepEqual(written.favorites[0].schedule, schedule);
  assert.equal(written.favorites[0].id, 'new-favorite');
});

test('a favorite deleted before saving an edit cannot become a new favorite', async () => {
  let writes = 0;
  await assert.rejects(() =>
    saveFavoriteDraft(
      {
        readState: async () => ({ favorites: [] }),
        writeState: async () => {
          writes++;
        },
        createId: () => 'replacement',
      },
      draft(),
      'deleted',
    ),
  );
  assert.equal(writes, 0);
});

test('write failure is returned to the editor without clearing or mutating its draft', async () => {
  const input = draft(),
    before = JSON.stringify(input);
  await assert.rejects(
    () =>
      saveFavoriteDraft(
        {
          readState: async () => ({ favorites: [] }),
          writeState: async () => {
            throw Error('storage unavailable');
          },
          createId: () => 'new',
        },
        input,
      ),
    /storage unavailable/,
  );
  assert.equal(JSON.stringify(input), before);
});
