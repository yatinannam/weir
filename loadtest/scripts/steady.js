import { ask, summary, SUMMARY_STATS } from './lib.js';

export const options = {
  summaryTrendStats: SUMMARY_STATS,
  scenarios: {
    traffic: {
      executor: 'constant-arrival-rate', rate: Number(__ENV.RATE || 10), timeUnit: '1s',
      duration: __ENV.DURATION || '5m', preAllocatedVUs: 50, maxVUs: 500, exec: 'traffic',
    },
  },
};
export function traffic() { ask(); }
export function handleSummary(data) { return summary(data); }
