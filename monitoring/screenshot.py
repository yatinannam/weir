"""Capture the Weir dashboard into docs/images/ (Phase 4 addendum §7). Free: Playwright's headless Chromium.

    uv run --with playwright python -m playwright install chromium     # once, ~150 MB
    GRAFANA_ADMIN_PASSWORD=... uv run --with playwright python monitoring/screenshot.py
"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

GRAFANA = "http://127.0.0.1:3000"
OUT = Path(__file__).resolve().parents[1] / "docs" / "images"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 2350}, device_scale_factor=1)
        page.goto(f"{GRAFANA}/login")
        page.fill('input[name="user"]', "admin")
        page.fill('input[name="password"]', os.environ.get("GRAFANA_ADMIN_PASSWORD") or "admin")
        page.click('button[type="submit"]')
        page.wait_for_url(lambda url: "/login" not in url, timeout=30_000)  # Grafana 11 lands on /?from=...
        page.goto(f"{GRAFANA}/d/weir/weir?orgId=1&from=now-30d&to=now&kiosk", wait_until="networkidle")
        page.wait_for_timeout(5_000)                       # let every panel finish rendering
        page.screenshot(path=str(OUT / "dashboard.png"), full_page=True)
        page.screenshot(path=str(OUT / "dashboard-headline.png"), clip={"x": 0, "y": 0, "width": 1600, "height": 640})
        browser.close()
    print(f"wrote {OUT / 'dashboard.png'} and {OUT / 'dashboard-headline.png'}")


if __name__ == "__main__":
    main()
