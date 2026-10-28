const { test } = require('node:test');
const assert = require('node:assert/strict');

const { normalizeSchedule, scheduleOccurrence, formatSchedule } = require('../src/commute');

test('schedule normalization orders unique days Monday first without changing the input', () => {
  const input = { days: [0, 5, 1, 3], start: '07:00', end: '09:00', extra: true };
  const result = normalizeSchedule(input);
  assert.deepEqual(result, { days: [1, 3, 5, 0], start: '07:00', end: '09:00' });
  assert.deepEqual(input.days, [0, 5, 1, 3]);
  result.days.push(2);
  assert.deepEqual(input.days, [0, 5, 1, 3]);
});

test('schedule normalization rejects empty, duplicated, noninteger and out-of-range days', () => {
  for (const days of [undefined, null, [], [1, 1], [-1], [7], [1.5], ['1'], [NaN], Array(1)]) {
    assert.throws(() => normalizeSchedule({ days, start: '07:00', end: '09:00' }), /[가-힣]/);
  }
  for (const value of [undefined, null, {}, '07:00']) {
    assert.throws(() => normalizeSchedule(value), /[가-힣]/);
  }
});

test('schedule normalization requires distinct valid HH:MM times', () => {
  for (const [start, end] of [
    ['7:00', '09:00'], ['24:00', '09:00'], ['07:60', '09:00'],
    ['07:00', '9:00'], ['07:00', '24:00'], ['07:00', '09:60'],
    ['07:00', '07:00'], ['', '09:00'], [700, '09:00'], ['07:00', null],
    [' 07:00', '09:00'], ['07:00', '09:00:00'], ['07:00\n', '09:00'], ['07:00', '09:00\n']
  ]) {
    assert.throws(() => normalizeSchedule({ days: [1], start, end }), /[가-힣]/);
  }
  assert.deepEqual(normalizeSchedule({ days: [6], start: '00:00', end: '23:59' }),
    { days: [6], start: '00:00', end: '23:59' });
});

test('daytime occurrence includes its start and excludes its end in local device time', () => {
  const schedule = { days: [1], start: '07:00', end: '09:00' };
  const cases = [
    [new Date(2026, 9, 26, 6, 59, 59), null],
    [new Date(2026, 9, 26, 7, 0), '2026-10-26|07:00|09:00'],
    [new Date(2026, 9, 26, 8, 59, 59), '2026-10-26|07:00|09:00'],
    [new Date(2026, 9, 26, 9, 0), null],
    [new Date(2026, 9, 27, 8, 0), null]
  ];
  for (const [date, expected] of cases) assert.equal(scheduleOccurrence(schedule, date), expected);
});

test('overnight occurrences belong to the selected starting day across Sunday and month boundaries', () => {
  const schedule = { days: [0], start: '23:00', end: '01:00' };
  const cases = [
    [new Date(2026, 10, 1, 0, 30), null],
    [new Date(2026, 10, 1, 22, 59), null],
    [new Date(2026, 10, 1, 23, 0), '2026-11-01|23:00|01:00'],
    [new Date(2026, 10, 2, 0, 0), '2026-11-01|23:00|01:00'],
    [new Date(2026, 10, 2, 0, 59, 59), '2026-11-01|23:00|01:00'],
    [new Date(2026, 10, 2, 1, 0), null]
  ];
  for (const [date, expected] of cases) assert.equal(scheduleOccurrence(schedule, date), expected);
  const date = new Date(2026, 10, 1, 0, 30);
  assert.equal(scheduleOccurrence({ days: [6], start: '23:00', end: '01:00' }, date),
    '2026-10-31|23:00|01:00');
  assert.equal(date.getDate(), 1);
});

test('invalid schedules and dates never produce an occurrence', () => {
  const valid = { days: [1], start: '07:00', end: '09:00' };
  for (const date of [new Date(NaN), undefined, null, '2026-10-26', 0, {}]) {
    assert.equal(scheduleOccurrence(valid, date), null);
  }
  for (const schedule of [null, { ...valid, days: [1, 1] }, { ...valid, days: [] },
    { ...valid, days: [7] }, { ...valid, start: '24:00' }, { ...valid, end: '07:00' }]) {
    assert.equal(scheduleOccurrence(schedule, new Date(2026, 9, 26, 8)), null);
  }
});

test('schedule labels show the actual canonical Korean weekdays and saved times', () => {
  assert.equal(formatSchedule({ days: [5, 1, 3], start: '07:00', end: '09:00' }), '월·수·금 07:00–09:00');
  assert.equal(formatSchedule({ days: [0, 6], start: '23:00', end: '01:00' }), '토·일 23:00–01:00');
  assert.equal(formatSchedule({ days: [0, 6, 5, 4, 3, 2, 1], start: '00:00', end: '23:59' }),
    '월·화·수·목·금·토·일 00:00–23:59');
  assert.equal(formatSchedule({ days: [], start: '07:00', end: '09:00' }), '시간 조건 확인 필요');
  assert.equal(formatSchedule(null), '시간 조건 확인 필요');
});
