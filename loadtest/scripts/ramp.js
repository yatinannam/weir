import { ask, summary, SUMMARY_STATS } from './lib.js';

const rates = (__ENV.RAMP_STEPS || '5,10,20,40,60,80,100').split(',').map(Number);
const step = Number(__ENV.STEP_S || 90);
const stages = rates.flatMap((r) => [{ target: r, duration: '1s' }, { target: r, duration: `${step - 1}s` }]);

export const options = {
  summaryTrendStats: SUMMARY_STATS,
  thresholds: { errors: [{ threshold: 'rate<0.05', abortOnFail: true, delayAbortEval: '20s' }] },
  scenarios: {
    traffic: {
      executor: 'ramping-arrival-rate', startRate: rates[0], timeUnit: '1s',
      preAllocatedVUs: 100, maxVUs: 500, stages, exec: 'traffic',
    },
  },
};
export function traffic() { ask(); }
export function handleSummary(data) { return summary(data); }
