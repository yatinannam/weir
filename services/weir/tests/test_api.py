from uuid import uuid4

import httpx
import pytest

from weir.admin import RequestRef
from weir.auth import TenantRegistry
from weir.config import load_config
from weir.main import AppDeps, create_app

from .conftest import CONFIGS
from .fakes import FakeAdmin
from .test_pipeline import PUBLIC, STAFF, fake_rag, harness

ENV = {"WEIR_KEY_PUBLIC": "pub-key", "WEIR_KEY_STAFF": "staff-key", "WEIR_KEY_ADMIN": "admin-key"}
PUB = {"X-API-Key": "pub-key"}
ADMIN = {"X-API-Key": "admin-key"}


def app_client(rag=None, health_ok=True, admin=None, metrics=None):
    h = harness(rag or fake_rag())

    async def health():
        return {"db": health_ok, "rag": True}

    deps = AppDeps(h.p, TenantRegistry.from_yaml(CONFIGS / "tenants.yaml", ENV), load_config(CONFIGS / "weir.yaml"),
                   health, admin or FakeAdmin(), feedback_lookup_delay_s=0, metrics=metrics)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://t")
    return client, h.sink


async def test_query_ok_sets_request_id_header():
    client, sink = app_client()
    async with client:
        r = await client.post("/v1/query", headers=PUB, json={"query": "hi", "namespace": PUBLIC})
    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == r.json()["meta"]["request_id"] == str(sink.rows[0].request_id)


async def test_missing_key_401():
    client, sink = app_client()
    async with client:
        r1 = await client.post("/v1/query", json={"query": "hi", "namespace": PUBLIC})
        r2 = await client.post("/v1/query", headers={"X-API-Key": "bad"}, json={"query": "hi", "namespace": PUBLIC})
    assert r1.status_code == r2.status_code == 401 and sink.rows == []


async def test_wrong_namespace_403():
    client, sink = app_client()
    async with client:
        r = await client.post("/v1/query", headers=PUB, json={"query": "hi", "namespace": STAFF})
    assert r.status_code == 403 and sink.rows == []


async def test_blank_query_422():
    client, _ = app_client()
    async with client:
        r = await client.post("/v1/query", headers=PUB, json={"query": "  ", "namespace": PUBLIC})
    assert r.status_code == 422


async def test_rate_limited_generate_returns_503_with_request_id():
    limited = httpx.Response(503, json={"error": "rate_limited", "retry_after": 12.0})
    client, sink = app_client(rag=fake_rag(generate_response=limited))
    async with client:
        r = await client.post("/v1/query", headers=PUB, json={"query": "hi", "namespace": PUBLIC})
    assert r.status_code == 503 and r.headers["Retry-After"] == "12"
    assert r.json() == {"error": "rate_limited", "request_id": str(sink.rows[0].request_id)}


@pytest.mark.parametrize(("ok", "status"), [(True, 200), (False, 503)])
async def test_healthz(ok, status):
    client, _ = app_client(health_ok=ok)
    async with client:
        r = await client.get("/healthz")
    assert r.status_code == status and r.json()["checks"]["db"] is ok


async def test_feedback_negative_evicts_entry():
    rid, entry = uuid4(), uuid4()
    admin = FakeAdmin({rid: RequestRef(PUBLIC, entry)})
    client, _ = app_client(admin=admin)
    async with client:
        r = await client.post("/v1/feedback", headers=PUB, json={"request_id": str(rid), "rating": -1, "comment": "wrong"})
    assert r.status_code == 200 and r.json() == {"evicted": True}
    assert admin.evicted == [entry] and admin.feedback == [(rid, -1, "wrong")]


async def test_feedback_positive_does_not_evict():
    rid = uuid4()
    admin = FakeAdmin({rid: RequestRef(PUBLIC, uuid4())})
    client, _ = app_client(admin=admin)
    async with client:
        r = await client.post("/v1/feedback", headers=PUB, json={"request_id": str(rid), "rating": 1})
    assert r.json() == {"evicted": False} and admin.evicted == []


async def test_feedback_waits_for_log_row():
    rid = uuid4()
    admin = FakeAdmin({rid: RequestRef(PUBLIC, None)}, appear_after=2)
    client, _ = app_client(admin=admin)
    async with client:
        r = await client.post("/v1/feedback", headers=PUB, json={"request_id": str(rid), "rating": 1})
    assert r.status_code == 200 and admin.lookups == 3


async def test_feedback_unknown_or_other_tenant_404():
    staff_rid = uuid4()
    admin = FakeAdmin({staff_rid: RequestRef(STAFF, uuid4())})
    client, _ = app_client(admin=admin)
    async with client:
        unknown = await client.post("/v1/feedback", headers=PUB, json={"request_id": str(uuid4()), "rating": -1})
        other = await client.post("/v1/feedback", headers=PUB, json={"request_id": str(staff_rid), "rating": -1})
        nokey = await client.post("/v1/feedback", json={"request_id": str(staff_rid), "rating": -1})
        bad = await client.post("/v1/feedback", headers=PUB, json={"request_id": str(staff_rid), "rating": 5})
    assert unknown.status_code == other.status_code == 404 and admin.evicted == [] and admin.feedback == []
    assert nokey.status_code == 401 and bad.status_code == 422


async def test_purge_requires_admin():
    client, _ = app_client()
    async with client:
        r1 = await client.delete("/v1/cache", params={"namespace": PUBLIC})
        r2 = await client.delete("/v1/cache", headers=PUB, params={"namespace": PUBLIC})
    assert r1.status_code == 401 and r2.status_code == 403


async def test_purge_needs_exactly_one_valid_selector():
    admin = FakeAdmin()
    client, _ = app_client(admin=admin)
    async with client:
        none = await client.delete("/v1/cache", headers=ADMIN)
        two = await client.delete("/v1/cache", headers=ADMIN, params={"namespace": PUBLIC, "source_id": "pub-a"})
        bad_id = await client.delete("/v1/cache", headers=ADMIN, params={"entry_id": "nope"})
        ok = await client.delete("/v1/cache", headers=ADMIN, params={"source_id": "pub-a"})
    assert none.status_code == two.status_code == bad_id.status_code == 422
    assert ok.status_code == 200 and ok.json() == {"deleted": 3} and admin.purged == [{"source_id": "pub-a"}]


from prometheus_client import CollectorRegistry  # noqa: E402

from weir.metrics.prometheus import LossCollector, WeirMetrics  # noqa: E402


def _metrics():
    class Q:
        dropped = failed = 0

    registry = CollectorRegistry()
    m = WeirMetrics(registry, "dev")
    registry.register(LossCollector({"log_rows": Q(), "cache_jobs": Q()}))
    return m


async def test_metrics_before_any_request():  # Review Focus 2: scrape before traffic
    client, sink = app_client(metrics=_metrics())
    async with client:
        r = await client.get("/metrics")                                  # no API key needed
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert 'weir_info{config_label="dev"} 1.0' in body
    for name in ("weir_log_rows_dropped_total", "weir_log_rows_failed_total",
                 "weir_cache_jobs_dropped_total", "weir_cache_jobs_failed_total"):
        assert f"{name} 0.0" in body
    assert sink.rows == []                                                # scraping isn't a logged request


async def test_metrics_reflect_requests_recorded_by_the_sink():
    m = _metrics()
    client, _ = app_client(metrics=m)
    m.record(_row_for_metrics())
    async with client:
        body = (await client.get("/metrics")).text
    from prometheus_client.parser import text_string_to_metric_families  # label order is the library's choice

    samples = {(s.name, tuple(sorted(s.labels.items()))): s.value
               for family in text_string_to_metric_families(body) for s in family.samples}
    labels = tuple(sorted({"namespace": PUBLIC, "cache_status": "miss", "route": "large", "status": "ok"}.items()))
    assert samples[("weir_requests_total", labels)] == 1.0


async def test_metrics_off_returns_404():
    client, _ = app_client()
    async with client:
        assert (await client.get("/metrics")).status_code == 404


def _row_for_metrics():
    from datetime import UTC, datetime
    from decimal import Decimal
    from uuid import uuid4

    from weir.metrics.logger import RequestLogRow

    return RequestLogRow(request_id=uuid4(), ts=datetime.now(UTC), namespace=PUBLIC, cache_status="miss",
                         route="large", status="ok", latency_total_ms=500, query_hash="h" * 64,
                         cost_usd=Decimal("0.0001"), counterfactual_cost_usd=Decimal("0.0001"))
