const DAY_ORDER = [1, 2, 3, 4, 5, 6, 0];
const DAY_LABELS = ['일', '월', '화', '수', '목', '금', '토'];

function normalizeSchedule(schedule) {
  if (!schedule || !Array.isArray(schedule.days) || schedule.days.length === 0) {
    throw new Error('요일을 하나 이상 선택해 주세요.');
  }
  const days = new Set();
  for (const day of schedule.days) {
    if (!Number.isInteger(day) || day < 0 || day > 6 || days.has(day)) {
      throw new Error('요일 조건을 확인해 주세요.');
    }
    days.add(day);
  }
  const validTime = (value) => typeof value === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
  if (!validTime(schedule.start) || !validTime(schedule.end)) {
    throw new Error('시간을 HH:MM 24시간 형식으로 입력해 주세요.');
  }
  if (schedule.start === schedule.end) throw new Error('시작과 종료 시간을 다르게 설정해 주세요.');
  return {
    days: DAY_ORDER.filter((day) => days.has(day)),
    start: schedule.start,
    end: schedule.end,
  };
}

function scheduleOccurrence(schedule, date) {
  if (!(date instanceof Date) || !Number.isFinite(date.getTime())) return null;
  let normalized;
  try {
    normalized = normalizeSchedule(schedule);
  } catch {
    return null;
  }
  const minutes = (value) => Number(value.slice(0, 2)) * 60 + Number(value.slice(3));
  const start = minutes(normalized.start),
    end = minutes(normalized.end);
  const current = date.getHours() * 60 + date.getMinutes();
  const startDate = new Date(date.getTime());
  if (start < end) {
    if (current < start || current >= end) return null;
  } else if (current < end) {
    // Move by local calendar day so DST transitions do not shift the occurrence date.
    startDate.setDate(startDate.getDate() - 1);
  } else if (current < start) {
    return null;
  }
  if (!normalized.days.includes(startDate.getDay())) return null;
  const pad = (value) => String(value).padStart(2, '0');
  const day = `${String(startDate.getFullYear()).padStart(4, '0')}-${pad(startDate.getMonth() + 1)}-${pad(startDate.getDate())}`;
  return `${day}|${normalized.start}|${normalized.end}`;
}

function formatSchedule(schedule) {
  let normalized;
  try {
    normalized = normalizeSchedule(schedule);
  } catch {
    return '시간 조건 확인 필요';
  }
  return `${normalized.days.map((day) => DAY_LABELS[day]).join('·')} ${normalized.start}–${normalized.end}`;
}

module.exports = { normalizeSchedule, scheduleOccurrence, formatSchedule };
