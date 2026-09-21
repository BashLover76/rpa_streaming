from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from ingestion.logging_config import configure_logging
from ingestion.rpa_self_healing import PlatformConfig, SelfHealingRPA

SELECTORS = [
    "[data-uia='viewing-activity']",
    ".retable",
    ".retableRow",
    ".col-title a",
    "[data-testid='activity-history-item']",
    "a[href*='/title/']",
    "button:has-text('Show More')",
    "button:has-text('Afficher plus')",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Netflix viewing activity DOM")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    args = parser.parse_args()
    configure_logging("diagnostics", platform="netflix")

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp_url, timeout=30_000)
        try:
            context = browser.contexts[0]
            page = next(
                (
                    candidate
                    for candidate in context.pages
                    if "netflix.com/viewingactivity" in candidate.url
                ),
                None,
            )
            if page is None:
                page = context.new_page()
                page.goto(
                    "https://www.netflix.com/viewingactivity",
                    wait_until="networkidle",
                    timeout=60_000,
                )

            print(f"url={page.url}")
            print(f"title={page.title()}")
            for selector in SELECTORS:
                print(f"{selector}={page.locator(selector).count()}")
            config = PlatformConfig.from_dict(
                json.loads(Path("config/platforms/netflix.json").read_text())
            )
            cards = SelfHealingRPA._collect_history_rows(
                page, config.selectors["history_rows"]
            )
            print(f"collector_cards={len(cards)}")
            if cards:
                print(f"first_card={cards[0]}")
                structured, unknown = SelfHealingRPA._extract_structured_cards(
                    [cards[0]], "netflix"
                )
                print(f"first_structured={structured[0] if structured else None}")
                print(f"first_unknown={len(unknown)}")

            text = page.locator("body").inner_text(timeout=5_000)
            print("body_sample=" + text[:2000].replace("\n", " | "))
            react = page.evaluate("""() => ({
                    keys: Object.keys(window.netflix?.reactContext?.models || {}),
                    pageName: window.netflix?.reactContext?.pageName,
                    apiRoot: window.netflix?.reactContext?.models?.serverDefs?.data?.API_ROOT,
                    bodyLength: document.body.innerText.length
                })""")
            print(f"react={react}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
