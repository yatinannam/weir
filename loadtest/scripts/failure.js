// Failure injection (Phase 5 addendum §3.4): traffic plus a chaos track that flips faults at fixed offsets.
import http from 'k6/http';
import { sleep } from 'k6';
import { ask, summary, SUMMARY_STATS } from './lib.js';

const PHASE = Number(__ENV.PHASE_S || 60);
const RAG = __ENV.RAG_URL || 'http://hospital-rag:8001';
const TOXI = __ENV.TOXI_URL || 'http://toxiproxy:8474';
const SMALL = 'openai/gpt-oss-20b';
const LARGE = 'openai/gpt-oss-120b';
const JSON_HDR = { headers: { 'content-type': 'application/json' }, tags: { name: 'chaos' } };

export const options = {
  summaryTrendStats: SUMMARY_STATS,
  scenarios: {
    traffic: {
      executor: 'constant-arrival-rate', rate: Number(__ENV.RATE || 10), timeUnit: '1s',
      duration: `${7 * PHASE}s`, preAllocatedVUs: 50, maxVUs: 500, exec: 'traffic',
    },
    chaos: { executor: 'per-vu-iterations', vus: 1, iterations: 1, maxDuration: `${8 * PHASE}s`, exec: 'chaos' },
  },
};

function fault(model, mode, delayMs) {
  http.post(`${RAG}/stub/faults`, JSON.stringify({ model, mode, delay_ms: delayMs || 5000 }), JSON_HDR);
}
function dbDelay(on) {
  if (on) {
    http.post(`${TOXI}/proxies/weir-db/toxics`, JSON.stringify(
      { name: 'db_latency', type: 'latency', stream: 'downstream', attributes: { latency: 2000 } }), JSON_HDR);
  } else {
    http.del(`${TOXI}/proxies/weir-db/toxics/db_latency`, null, JSON_HDR);
  }
}

export function traffic() { ask(); }
export function chaos() {
  sleep(2 * PHASE); fault(LARGE, 'rate_limit');
  sleep(PHASE); fault(LARGE, 'none');
  sleep(PHASE); fault(SMALL, 'timeout', 5000);
  sleep(PHASE); fault(SMALL, 'none'); dbDelay(true);
  sleep(PHASE); dbDelay(false);
}
export function teardown() { fault('*', 'none'); dbDelay(false); }   // always restore, even after an abort
export function handleSummary(data) { return summary(data); }
