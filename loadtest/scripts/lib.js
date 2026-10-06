// Shared k6 helpers (Phase 5 addendum §2). Keys come from the environment, never from files.
import http from 'k6/http';
import exec from 'k6/execution';
import { SharedArray } from 'k6/data';
import { Trend, Rate } from 'k6/metrics';

export const WEIR = __ENV.WEIR_URL || 'http://weir:8000';
export const SUMMARY_STATS = ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max', 'count'];
const KEYS = {
  'weir-general/en/public': __ENV.WEIR_KEY_PUBLIC,
  'weir-general/en/staff': __ENV.WEIR_KEY_STAFF,
};
const requests = new SharedArray('requests', () => JSON.parse(open(__ENV.WORKLOAD)));
const all = new Trend('latency_all', true);
const byPath = {
  hit: new Trend('latency_hit', true),
  small: new Trend('latency_small', true),
  large: new Trend('latency_large', true),
};
export const errors = new Rate('errors');

// bypassEvery n > 0: every n-th request skips Weir's cache (D54), so it always goes through the router to a model.
export function ask(bypassEvery = 0) {
  const i = exec.scenario.iterationInTest;
  const r = requests[i % requests.length];
  const body = { query: r.query, namespace: r.namespace };
  if (bypassEvery > 0 && i % bypassEvery === 0) body.options = { bypass_cache: true };
  const res = http.post(`${WEIR}/v1/query`, JSON.stringify(body), {
    headers: { 'content-type': 'application/json', 'X-API-Key': KEYS[r.namespace] },
    timeout: '60s',
  });
  const ok = res.status === 200;
  errors.add(!ok);
  all.add(res.timings.duration);
  if (ok) {
    const meta = res.json('meta');
    const path = meta.cache_status === 'hit' ? 'hit' : meta.route;
    if (byPath[path]) byPath[path].add(res.timings.duration);
  }
}

export function summary(data) {
  return { [__ENV.SUMMARY_OUT || '/dev/stdout']: JSON.stringify(data) };
}
