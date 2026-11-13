/* Local hass stub: a callWS that can succeed, throw, hang or return a response without
   `response` — everything the calendar layer has to cope with. */
import { addDays, dayKey, midnight } from '../../src/schedule.js';

/* All-day events for the given 'YYYY-MM-DD' days. */
export const allDay = days => days.map(date => ({
  start: { date },
  end: { date: dayKey(addDays(new Date(`${date}T00:00:00`), 1)) },
}));

export function response(entityId, events) {
  return { response: { [entityId]: { events } } };
}

export function createHass({ entity = 'calendar.bins', state = 'on', startTime = null, events = [] } = {}) {
  const calls = [];
  const hass = {
    states: { [entity]: { entity_id: entity, state, attributes: startTime ? { start_time: startTime } : {} } },
    entities: {},
    locale: { language: 'en' },
    calls,
    /* behaviour of the next calls: 'ok' (default), 'error', 'abort', 'timeout' or 'invalid' */
    mode: 'ok',
    events,
    callWS: async msg => {
      calls.push(msg);
      const id = msg.target.entity_id;
      switch (hass.mode) {
        case 'error': throw new Error('Service calendar.get_events not found');
        case 'abort': {
          const err = new Error('The operation was aborted');
          err.name = 'TimeoutError';
          throw err;
        }
        case 'timeout': return new Promise(() => {}); // hangs: the caller must enforce its deadline
        case 'invalid': return {};                    // no `response` field
        default: return response(id, hass.events);
      }
    },
  };
  return hass;
}

/* Local day keys relative to today (the card compares calendar days to the local day). */
export const inDays = n => dayKey(addDays(midnight(new Date()), n));
