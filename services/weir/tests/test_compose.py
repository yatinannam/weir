"""Compose wiring the monitoring design depends on (Phase 4 addendum §2)."""
import yaml

from .conftest import REPO

COMPOSE = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]


def test_every_published_port_is_localhost_only():
    for name, service in SERVICES.items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} on every interface"


def test_monitoring_services_are_opt_in_and_pinned():
    assert SERVICES["prometheus"]["profiles"] == ["monitoring"]
    assert SERVICES["grafana"]["profiles"] == ["monitoring"]
    assert SERVICES["prometheus"]["image"] == "prom/prometheus:v2.55.1"
    assert SERVICES["grafana"]["image"] == "grafana/grafana-oss:11.3.0"
    assert all("profiles" not in SERVICES[s] for s in ("postgres", "migrate", "hospital-rag", "weir"))


def test_grafana_has_no_anonymous_access_or_signup():
    env = SERVICES["grafana"]["environment"]
    assert env["GF_AUTH_ANONYMOUS_ENABLED"] == "false" and env["GF_USERS_ALLOW_SIGN_UP"] == "false"
    assert "GRAFANA_ADMIN_PASSWORD" in env["GF_SECURITY_ADMIN_PASSWORD"]


def test_prometheus_scrapes_weir_every_5s_and_keeps_15_days():
    prom = yaml.safe_load((REPO / "monitoring" / "prometheus" / "prometheus.yml").read_text(encoding="utf-8"))
    assert prom["global"]["scrape_interval"] == "5s" and prom["global"]["evaluation_interval"] == "30s"
    [job] = prom["scrape_configs"]
    assert job["job_name"] == "weir" and job["static_configs"][0]["targets"] == ["weir:8000"]
    assert "--storage.tsdb.retention.time=15d" in SERVICES["prometheus"]["command"]


def test_grafana_datasources_use_the_read_only_login():
    ds = yaml.safe_load((REPO / "monitoring" / "grafana" / "provisioning" / "datasources" / "datasources.yml")
                        .read_text(encoding="utf-8"))["datasources"]
    by_uid = {d["uid"]: d for d in ds}
    assert by_uid["weir-prom"]["url"] == "http://prometheus:9090"
    assert by_uid["weir-pg"]["user"] == "weir_reader" and by_uid["weir-pg"]["jsonData"]["database"] == "weir"
