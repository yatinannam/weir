from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from weir.metrics.logger import RequestLogRow
from weir.metrics.prometheus import LossCollector, MetricsSink, WeirMetrics

from .fakes import ListSink

PUB = "weir-general/en/public"


def row(**over):
    base = dict(request_id=uuid4(), ts=datetime.now(UTC), namespace=PUB, cache_status="miss", route="large",
                status="ok", latency_total_ms=800, query_hash="h" * 64, cost_usd=Decimal("0.0001"),
                counterfactual_cost_usd=Decimal("0.0001"), model_calls=1, route_reason="default_large",
                grounding_passed=True, config_label="full")
    return RequestLogRow(**{**base, **over})


def setup():
    registry = CollectorRegistry()
    metrics = WeirMetrics(registry, "full")
    return registry, metrics, MetricsSink(ListSink(), metrics)


def value(registry, name, **labels):
    return registry.get_sample_value(name, labels) or 0.0


def test_large_miss_updates_requests_latency_cost_and_calls():
    registry, metrics, _ = setup()
    metrics.record(row(cost_usd=Decimal("0.0004"), counterfactual_cost_usd=Decimal("0.0004")))
    labels = dict(namespace=PUB, cache_status="miss", route="large", status="ok")
    assert value(registry, "weir_requests_total", **labels) == 1
    assert value(registry, "weir_request_latency_seconds_count", cache_status="miss", route="large") == 1
    assert value(registry, "weir_request_latency_seconds_sum", cache_status="miss", route="large") == 0.8
    assert value(registry, "weir_cost_usd_total", namespace=PUB) == pytest.approx(0.0004)
    assert value(registry, "weir_counterfactual_cost_usd_total", namespace=PUB) == pytest.approx(0.0004)
    assert value(registry, "weir_model_calls_total") == 1


def test_cache_hit_costs_nothing_but_counts_its_counterfactual():
    registry, metrics, _ = setup()
    metrics.record(row(cache_status="hit", route="none", model_calls=0, cost_usd=Decimal(0),
                       counterfactual_cost_usd=Decimal("0.0005"), route_reason=None, grounding_passed=None))
    assert value(registry, "weir_requests_total", namespace=PUB, cache_status="hit", route="none", status="ok") == 1
    assert value(registry, "weir_cost_usd_total", namespace=PUB) == 0
    assert value(registry, "weir_counterfactual_cost_usd_total", namespace=PUB) == pytest.approx(0.0005)
    assert value(registry, "weir_grounding_total", passed="true", reason="none") == 0   # hits aren't graded


def test_escalation_fallback_and_grounding():
    registry, metrics, _ = setup()
    metrics.record(row(route="small", escalated=True, model_calls=2, route_reason="simple"))
    metrics.record(row(route="small", model_calls=2, route_reason="simple+fallback"))
    metrics.record(row(route="large", grounding_passed=False, grounding_reason="low_overlap"))
    assert value(registry, "weir_escalations_total") == 1
    assert value(registry, "weir_fallbacks_total", routed_tier="small") == 1
    assert value(registry, "weir_model_calls_total") == 5
    assert value(registry, "weir_grounding_total", passed="true", reason="none") == 2
    assert value(registry, "weir_grounding_total", passed="false", reason="low_overlap") == 1


def test_errors_and_timeouts_are_labelled_by_status():
    registry, metrics, _ = setup()
    metrics.record(row(status="error", grounding_passed=None, model_calls=2))
    metrics.record(row(status="timeout", grounding_passed=None))
    assert value(registry, "weir_requests_total", namespace=PUB, cache_status="miss", route="large",
                 status="error") == 1
    assert value(registry, "weir_requests_total", namespace=PUB, cache_status="miss", route="large",
                 status="timeout") == 1


def test_sink_records_then_forwards_the_row():
    registry, metrics, sink = setup()
    r = row()
    sink.submit(r)
    assert sink._writer.rows == [r]
    assert value(registry, "weir_requests_total", namespace=PUB, cache_status="miss", route="large", status="ok") == 1


def test_metrics_failure_never_blocks_the_log_row():  # Review Focus 1
    registry, metrics, sink = setup()

    def broken(_row):
        raise RuntimeError("boom")

    metrics.record = broken
    r = row()
    sink.submit(r)                                   # must not raise
    assert sink._writer.rows == [r]
    assert value(registry, "weir_metrics_failed_total") == 1


def test_no_request_text_or_ids_in_metrics():  # Review Focus 5
    registry, metrics, _ = setup()
    r = row(namespace="weir-general/en/staff", query_text="patient John Doe 9876543210 room 12")
    metrics.record(r)
    text = generate_latest(registry).decode()
    assert "John Doe" not in text and "9876543210" not in text and str(r.request_id) not in text


def test_info_and_loss_collector():
    class Q:
        dropped, failed = 2, 3

    registry = CollectorRegistry()
    WeirMetrics(registry, "router_only")
    registry.register(LossCollector({"log_rows": Q(), "cache_jobs": Q()}))
    assert value(registry, "weir_info", config_label="router_only") == 1
    assert value(registry, "weir_log_rows_dropped_total") == 2
    assert value(registry, "weir_cache_jobs_failed_total") == 3


def test_alerting_series_exist_at_zero_before_any_request():
    """Final review I1: a labelled series that first appears at 1 hides its first increment from increase(), so the
    first fallback / error after a restart went unreported. Every series an alert divides or sums starts at 0."""
    registry = CollectorRegistry()
    WeirMetrics(registry, "full", namespaces=[PUB, "weir-general/en/staff"])
    for tier in ("small", "large"):
        assert registry.get_sample_value("weir_fallbacks_total", {"routed_tier": tier}) == 0
    for ns in (PUB, "weir-general/en/staff"):
        assert registry.get_sample_value("weir_cost_usd_total", {"namespace": ns}) == 0
        assert registry.get_sample_value("weir_counterfactual_cost_usd_total", {"namespace": ns}) == 0
        for cache_status in ("hit", "miss", "bypass"):
            for route in ("none", "small", "large"):
                for status in ("ok", "error", "timeout"):
                    labels = dict(namespace=ns, cache_status=cache_status, route=route, status=status)
                    assert registry.get_sample_value("weir_requests_total", labels) == 0, labels
    assert registry.get_sample_value("weir_request_latency_seconds_count", {"cache_status": "miss",
                                                                           "route": "large"}) == 0
