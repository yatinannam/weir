"""Phase 6A demo page: the two static routes and the page's own guarantees."""
import re
from pathlib import Path

from .test_api import app_client

DEMO = Path(__file__).resolve().parents[1] / "src" / "weir" / "demo"


async def test_demo_page_is_served_with_a_strict_policy():
    client, _ = app_client()
    async with client:
        r = await client.get("/demo")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


async def test_guided_questions_are_served_and_well_formed():
    client, _ = app_client()
    async with client:
        r = await client.get("/demo/questions.json")
    data = r.json()
    assert r.status_code == 200 and data["namespace"] == "weir-general/en/public"
    assert [s["n"] for s in data["steps"]] == [1, 2, 3, 4, 5]
    assert [s["expect"] for s in data["steps"]] == ["miss", "hit", "guard_refused", "small", "large"]
    assert all(s["question"].strip() and s["title"] and s["hint"] for s in data["steps"])


async def test_demo_routes_need_no_key_and_stay_out_of_the_api_docs():
    client, _ = app_client()
    async with client:
        schema = (await client.get("/openapi.json")).json()
    assert "/demo" not in schema["paths"] and "/demo/questions.json" not in schema["paths"]


def test_demo_files_hold_no_keys_or_external_urls():
    for f in DEMO.iterdir():
        text = f.read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, f.name
        assert not re.search(r"[A-Za-z0-9_-]{32}", text), f"{f.name} holds a key-like value"


def page_html() -> str:
    return (DEMO / "index.html").read_text(encoding="utf-8")


def test_page_reads_the_key_from_the_fragment_and_never_puts_it_in_the_url():
    html = page_html()
    assert "location.hash" in html and "history.replaceState" in html and "sessionStorage" in html
    assert "?key=" not in html


def test_page_shows_every_badge_mode_and_error_message():  # Review Focus 4
    html = page_html()
    for text in ("CACHE HIT", "SMALL MODEL", "LARGE MODEL", "SMALL → LARGE", "CACHE REFUSED", "CACHE SKIPPED",
                 "stub answers (no Groq key)", "real answers (Groq)", "The key was rejected",
                 "Groq free-tier limit", "isn't reachable", "already cached", "/v1/query", "/demo/questions.json",
                 "counterfactual_cost_usd", "guard_refused"):
        assert text in html, text


def test_page_renders_server_text_safely():
    assert "innerHTML" not in page_html()          # answers and errors go through textContent only
