from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


DEFAULT_URLS = [
    "https://www.netflix.com/viewingactivity",
    "https://www.primevideo.com/settings/watch-history",
    "https://www.disneyplus.com/home",
    "https://www.canalplus.com/mes-videos",
    "https://www.crunchyroll.com/fr/history",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export cookies/localStorage from an authenticated Chrome CDP session."
    )
    parser.add_argument(
        "--cdp-url",
        default="http://127.0.0.1:9222",
        help="Chrome DevTools endpoint for the authenticated local browser.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".continue/browser-storage-state.json"),
        help="Destination Playwright storage_state JSON file.",
    )
    parser.add_argument(
        "--url",
        action="append",
        dest="urls",
        help="URL to visit before exporting state. Can be repeated.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    urls = args.urls or DEFAULT_URLS

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp_url, timeout=30_000)
        if not browser.contexts:
            raise RuntimeError("Chrome CDP is reachable but exposes no browser context")
        context = browser.contexts[0]
        page = context.new_page()
        try:
            for url in urls:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(1_000)
                except Exception as exc:
                    print(f"warning: unable to visit {url}: {exc}")
            state = context.storage_state()
        finally:
            page.close()
            browser.close()

    args.output.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"storage_state exported to {args.output} "
        f"({len(state.get('cookies', []))} cookies)"
    )


if __name__ == "__main__":
    main()
