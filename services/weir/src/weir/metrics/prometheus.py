"""Live Prometheus metrics (Phase 4 addendum §3).

Every request metric is derived from the finished RequestLogRow, the same record that goes to Postgres, so the
live and historical numbers can't disagree. Request IDs, question text, similarity and model output are never
labels: they would create unbounded series and could leak text from sensitive namespaces.
"""
import logging
from collections.abc import Iterable

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.core import CounterMetricFamily
from prometheus_client.registry import Collector

from .logger import LogSink, RequestLogRow

log = logging.getLogger("weir.metrics")

LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0)


CACHE_STATUSES = ("hit", "miss", "bypass")
ROUTES = ("none", "small", "large")
STATUSES = ("ok", "error", "timeout")


class WeirMetrics:
    def __init__(self, registry: CollectorRegistry, config_label: str, namespaces: Iterable[str] = ()):
        self.registry = registry
        self.requests = Counter("weir_requests", "Requests handled by Weir",
                                ["namespace", "cache_status", "route", "status"], registry=registry)
        self.latency = Histogram("weir_request_latency_seconds", "End-to-end latency inside Weir",
                                 ["cache_status", "route"], buckets=LATENCY_BUCKETS, registry=registry)
        self.cost = Counter("weir_cost_usd", "Spend at list prices", ["namespace"], registry=registry)
        self.counterfactual = Counter("weir_counterfactual_cost_usd",
                                      "Spend with no cache and always the large model", ["namespace"],
                                      registry=registry)
        self.model_calls = Counter("weir_model_calls", "Model calls attempted", registry=registry)
        self.escalations = Counter("weir_escalations", "Small answers retried on the large model", registry=registry)
        self.fallbacks = Counter("weir_fallbacks", "Requests that switched tier after a provider error",
                                 ["routed_tier"], registry=registry)
        self.grounding = Counter("weir_grounding", "Grounding check results", ["passed", "reason"], registry=registry)
        self.metrics_failed = Counter("weir_metrics_failed", "Rows the metrics layer failed to record",
                                      registry=registry)
        Gauge("weir_info", "Running Weir configuration", ["config_label"],
              registry=registry).labels(config_label).set(1)
        # Final review I1: a labelled series that first appears at 1 hides that increment from increase(), so the
        # first fallback/error after every restart went unreported. Create every series the alerts use at 0.
        for tier in ("small", "large"):
            self.fallbacks.labels(tier)
        for cache_status in CACHE_STATUSES:
            for route in ROUTES:
                self.latency.labels(cache_status, route)
        for ns in namespaces:
            self.cost.labels(ns)
            self.counterfactual.labels(ns)
            for cache_status in CACHE_STATUSES:
                for route in ROUTES:
                    for status in STATUSES:
                        self.requests.labels(ns, cache_status, route, status)

    def record(self, row: RequestLogRow) -> None:
        self.requests.labels(row.namespace, row.cache_status, row.route, row.status).inc()
        self.latency.labels(row.cache_status, row.route).observe(row.latency_total_ms / 1000)
        self.cost.labels(row.namespace).inc(float(row.cost_usd))
        self.counterfactual.labels(row.namespace).inc(float(row.counterfactual_cost_usd))
        if row.model_calls:
            self.model_calls.inc(row.model_calls)
        if row.escalated:
            self.escalations.inc()
        if row.route_reason and row.route_reason.endswith("+fallback"):
            self.fallbacks.labels(row.route).inc()
        if row.grounding_passed is not None:
            self.grounding.labels("true" if row.grounding_passed else "false", row.grounding_reason or "none").inc()


class MetricsSink:
    """A LogSink that records live metrics, then forwards the row to the real writer unchanged."""

    def __init__(self, writer: LogSink, metrics: WeirMetrics):
        self._writer = writer
        self._metrics = metrics

    def submit(self, row: RequestLogRow) -> None:
        try:
            self._metrics.record(row)
        except Exception:  # noqa: BLE001 - monitoring must never fail a request or lose its log row
            self._metrics.metrics_failed.inc()
            log.exception("failed to record metrics for request %s", row.request_id)
        self._writer.submit(row)


class LossCollector(Collector):
    """Exposes the background queues' dropped/failed counts at scrape time (backlog M7)."""

    def __init__(self, sources: dict[str, object]):
        self._sources = sources

    def collect(self):
        for name, source in self._sources.items():
            for attr in ("dropped", "failed"):
                yield CounterMetricFamily(f"weir_{name}_{attr}", f"{name.replace('_', ' ')} {attr}",
                                          value=getattr(source, attr))
