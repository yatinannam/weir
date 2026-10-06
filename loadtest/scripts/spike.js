import { ask, summary, SUMMARY_STATS } from './lib.js';

const base = Number(__ENV.BASE_RATE || 5);
const burst = Number(__ENV.BURST_RATE || 60);
const s = (name, dflt) => Number(__ENV[name] || dflt);

export const options = {
  summaryTrendStats: SUMMARY_STATS,
  scenarios: {
    traffic: {
      executor: 'ramping-arrival-rate', startRate: base, timeUnit: '1s', preAllocatedVUs: 100, maxVUs: 500,
      exec: 'traffic',
      stages: [
        { target: base, duration: `${s('BASE_S', 120)}s` },
        { target: burst, duration: '1s' }, { target: burst, duration: `${s('BURST_S', 30) - 1}s` },
        { target: base, duration: '1s' }, { target: base, duration: `${s('AFTER_S', 180) - 1}s` },
      ],
    },
  },
};
export function traffic() { ask(); }
export function handleSummary(data) { return summary(data); }
