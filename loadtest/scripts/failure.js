// Failure injection (Phase 5 addendum §3.4): traffic plus a chaos track that flips faults at fixed offsets.
import http from 'k6/http';
import exec from 'k6/execution';
import { sleep } from 'k6';
import { Counter } from 'k6/metrics';
import { ask, summary, SUMMARY_STATS } from './lib.js';

const PHASE = Number(__ENV.PHASE_S || 60);
const RAG = __ENV.RAG_URL || 'http://hospital-rag:8001';
const TOXI = __ENV.TOXI_URL || 'http://toxiproxy:8474';
const SMALL = 'openai/gpt-oss-20b';
const LARGE = 'openai/gpt-oss-120b';
// Connection: close: a switch must never reuse a keep-alive connection the server has just timed out (uvicorn
// closes idle ones after 5 s), which reset one in the Task 7 smoke and left a fault on for two phases.
const JSON_HDR = { headers: { 'content-type': 'application/json', connection: 'close' }, tags: { name: 'chaos' } };
const chaosFailed = new Counter('chaos_failed');

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

// One switch, retried; `done` lists the statuses that mean the switch is in the wanted state.
function call(method, url, body, done) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const res = http.request(method, url, body === null ? null : JSON.stringify(body), JSON_HDR);
    if (done.includes(res.status)) return true;
    sleep(0.2);
  }
  return false;
}
function fault(model, mode, delayMs) {
  return call('POST', `${RAG}/stub/faults`, { model, mode, delay_ms: delayMs || 5000 }, [200]);
}
function dbDelay(on) {
  return on
    ? call('POST', `${TOXI}/proxies/weir-db/toxics`,
      { name: 'db_latency', type: 'latency', stream: 'downstream', attributes: { latency: 2000 } }, [200, 409])
    : call('DELETE', `${TOXI}/proxies/weir-db/toxics/db_latency`, null, [204, 404]);
}
// A scheduled switch that cannot be applied would leave a phase measuring the wrong fault: count it and stop.
function must(ok, what) {
  chaosFailed.add(ok ? 0 : 1);
  if (!ok) exec.test.abort(`chaos switch failed: ${what}`);
}

// D54: with a warm cache every request would be a hit and the model faults would meet no traffic, so 1 in 3 skip it
export function traffic() { ask(Number(__ENV.BYPASS_EVERY || 3)); }
export function chaos() {
  sleep(2 * PHASE); must(fault(LARGE, 'rate_limit'), 'large rate_limit');
  sleep(PHASE); must(fault(LARGE, 'none'), 'large none');
  sleep(PHASE); must(fault(SMALL, 'timeout', 5000), 'small timeout');
  sleep(PHASE); must(fault(SMALL, 'none'), 'small none'); must(dbDelay(true), 'db delay on');
  sleep(PHASE); must(dbDelay(false), 'db delay off');
}
export function teardown() { fault('*', 'none'); dbDelay(false); }   // always restore, even after an abort
export function handleSummary(data) { return summary(data); }
