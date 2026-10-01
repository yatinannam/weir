import httpx
import pytest

from weir.auth import TenantRegistry
from weir.config import load_config
from weir.main import AppDeps, create_app

from .conftest import CONFIGS
from .test_pipeline import PUBLIC, STAFF, fake_rag, pipeline

ENV = {"WEIR_KEY_PUBLIC": "pub-key", "WEIR_KEY_STAFF": "staff-key", "WEIR_KEY_ADMIN": "admin-key"}


def app_client(rag=None, health_ok=True):
    p, sink = pipeline(rag or fake_rag())

    async def health():
        return {"db": health_ok, "rag": True}

    deps = AppDeps(p, TenantRegistry.from_yaml(CONFIGS / "tenants.yaml", ENV), load_config(CONFIGS / "weir.yaml"), health)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://t")
    return client, sink


async def test_query_ok_sets_request_id_header():
    client, sink = app_client()
    async with client:
        r = await client.post("/v1/query", headers={"X-API-Key": "pub-key"}, json={"query": "hi", "namespace": PUBLIC})
    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == r.json()["meta"]["request_id"] == str(sink.rows[0].request_id)


async def test_missing_key_401():
    client, sink = app_client()
    async with client:
        r1 = await client.post("/v1/query", json={"query": "hi", "namespace": PUBLIC})
        r2 = await client.post("/v1/query", headers={"X-API-Key": "bad"}, json={"query": "hi", "namespace": PUBLIC})
    assert r1.status_code == r2.status_code == 401
    assert sink.rows == []


async def test_wrong_namespace_403():
    client, sink = app_client()
    async with client:
        r = await client.post("/v1/query", headers={"X-API-Key": "pub-key"}, json={"query": "hi", "namespace": STAFF})
    assert r.status_code == 403 and sink.rows == []


async def test_blank_query_422():
    client, _ = app_client()
    async with client:
        r = await client.post("/v1/query", headers={"X-API-Key": "pub-key"}, json={"query": "  ", "namespace": PUBLIC})
    assert r.status_code == 422


async def test_rate_limited_generate_returns_503_with_request_id():
    limited = httpx.Response(503, json={"error": "rate_limited", "retry_after": 12.0})
    client, sink = app_client(rag=fake_rag(generate_response=limited))
    async with client:
        r = await client.post("/v1/query", headers={"X-API-Key": "pub-key"}, json={"query": "hi", "namespace": PUBLIC})
    assert r.status_code == 503
    assert r.json() == {"error": "rate_limited", "request_id": str(sink.rows[0].request_id)}
    assert r.headers["Retry-After"] == "12"
    assert r.headers["X-Request-ID"] == str(sink.rows[0].request_id)


@pytest.mark.parametrize(("ok", "status"), [(True, 200), (False, 503)])
async def test_healthz(ok, status):
    client, _ = app_client(health_ok=ok)
    async with client:
        r = await client.get("/healthz")
    assert r.status_code == status
    assert r.json()["config_label"] == "dev" and r.json()["checks"]["db"] is ok
