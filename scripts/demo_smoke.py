"""Live smoke for the demo page (Phase 6A addendum §6). Free: Playwright's headless Chromium.

    uv run --with playwright python -m playwright install chromium   # once, ~150 MB
    uv run demo.py --stub --no-browser                               # a fresh stack and an empty demo cache
    uv run --with playwright python scripts/demo_smoke.py

Clicks the five guided steps and checks every badge and tick, the savings panel, the key leaving the address
bar, a repeated step, and the three error paths (no key, a wrong key, a Groq rate limit).
Saves docs/images/demo.png. Never prints a key.
"""
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import demo  # noqa: E402

SHOT = ROOT / "docs" / "images" / "demo.png"
CACHE_WRITE_WAIT_MS = 2000
PASS = re.compile(r"\bpass\b")
OTHER = re.compile(r"\bother\b")
BADGE = {2: "CACHE HIT", 3: "CACHE REFUSED", 4: "SMALL MODEL", 5: "LARGE MODEL"}


def ask_free_text(page, question: str) -> None:
    page.fill("#question", question)
    page.click("#send")


def guided_steps(page) -> None:
    for n in range(1, 6):
        step = page.locator(f'button.step[data-step="{n}"]')
        step.click()
        expect(step.locator(".result")).not_to_be_empty(timeout=60_000)
        expect(step).to_have_class(PASS)
        badges = page.locator(".card").first.locator(".badge").all_inner_texts()
        assert n not in BADGE or BADGE[n] in badges, f"step {n}: badges {badges}"
        assert n != 1 or "CACHE HIT" not in badges, f"step 1 was a hit: {badges}"
        page.wait_for_timeout(CACHE_WRITE_WAIT_MS)


def main() -> None:
    key = demo.read_env(demo.ROOT / ".env")["WEIR_KEY_PUBLIC"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=1)

        page.goto(demo.demo_url(key, "stub"))
        expect(page.locator("#mode")).to_have_text("stub answers (no Groq key)")
        assert "key=" not in page.url, "the key stayed in the address bar"
        expect(page.locator("button.step")).to_have_count(5)
        guided_steps(page)
        expect(page.locator("#s-n")).to_have_text("5")
        expect(page.locator("#s-hit")).to_have_text("20%")
        assert int(page.locator("#s-saved").inner_text().rstrip("%")) > 0
        page.screenshot(path=str(SHOT), full_page=True)

        step1 = page.locator('button.step[data-step="1"]')            # Review Focus 5: a repeat is reported
        step1.click()
        expect(step1).to_have_class(OTHER, timeout=60_000)
        expect(step1.locator(".result")).to_contain_text("already cached")

        page.route("**/v1/query", lambda route: route.fulfill(           # Review Focus 4: the Groq limit
            status=503, content_type="application/json", body=json.dumps({"error": "rate_limited", "retry_after": 30})))
        ask_free_text(page, "Is there a pharmacy open at night?")
        expect(page.locator(".card").first).to_contain_text("Groq free-tier limit")
        page.unroute("**/v1/query")

        wrong = browser.new_context().new_page()                          # Review Focus 3: a wrong key
        wrong.goto(demo.demo_url("not-the-key", "stub"))
        ask_free_text(wrong, "Is there a pharmacy open at night?")
        expect(wrong.locator(".card.error").first).to_contain_text("The key was rejected")

        missing = browser.new_context().new_page()                        # Review Focus 3: no key at all
        missing.once("dialog", lambda dialog: dialog.accept(key))
        missing.goto(f"{demo.WEIR}/demo")
        expect(missing.locator("#mode")).to_have_text("mode unknown")
        ask_free_text(missing, "Is there a pharmacy open at night?")
        expect(missing.locator(".card").first.locator(".badge").first).to_be_visible(timeout=60_000)

        browser.close()
    print(f"demo smoke: every check passed; wrote {SHOT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
