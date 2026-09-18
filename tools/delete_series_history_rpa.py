"""Remove one series from streaming history through the logged-in browser.

The command is deliberately preview-only unless both --apply and
--confirm-title are supplied. Platform layouts are not uniform, so every
candidate is saved to an artifact and only a delete control inside a matching
history card is clicked.
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from ingestion.rpa_self_healing import load_platform_configs
from ingestion.settings import Settings

LOGGER = logging.getLogger("delete_series_history_rpa")


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview or remove a series from platform history"
    )
    parser.add_argument(
        "--title", required=True, help="Exact series title as displayed by the platform"
    )
    parser.add_argument(
        "--platform",
        action="append",
        help="Platform name; repeat to target several platforms",
    )
    parser.add_argument("--cdp-url", default=None)
    parser.add_argument(
        "--apply", action="store_true", help="Click the platform deletion controls"
    )
    parser.add_argument(
        "--confirm-title", help="Must exactly equal --title when --apply is used"
    )
    parser.add_argument(
        "--artifacts-dir", type=Path, default=Path("artifacts/rpa/delete-history")
    )
    args = parser.parse_args()
    if args.apply and args.confirm_title != args.title:
        raise SystemExit(
            "Refusing deletion: --confirm-title must exactly match --title"
        )

    settings = Settings.from_env()
    platform_configs = load_platform_configs(settings.platform_config_path)
    requested_platforms = set(
        args.platform or [platform_config.name for platform_config in platform_configs]
    )
    platform_configs = [
        platform_config
        for platform_config in platform_configs
        if platform_config.name in requested_platforms
        and platform_config.name != "arte_tv"
    ]
    if not platform_configs:
        raise SystemExit("No matching active platform configuration")

    args.artifacts_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = None
        context = None
        if args.cdp_url or settings.rpa_cdp_url:
            browser = playwright.chromium.connect_over_cdp(
                args.cdp_url or settings.rpa_cdp_url
            )
            if not browser.contexts:
                raise RuntimeError("Chrome CDP exposes no browser context")
            context = browser.contexts[0]
        else:
            context = playwright.chromium.launch_persistent_context(
                str(settings.rpa_user_data_dir), headless=False, locale="fr-FR"
            )
        try:
            for platform_config in platform_configs:
                page = context.new_page()
                try:
                    _process_platform(page, platform_config, args)
                except Exception:
                    LOGGER.exception(
                        "History deletion failed for %s", platform_config.name
                    )
                finally:
                    page.close()
        finally:
            if browser is not None:
                browser.close()
            elif context is not None:
                context.close()


def _process_platform(page, config, args) -> None:
    page.goto(config.start_url, wait_until="domcontentloaded", timeout=60_000)
    time.sleep(config.wait_after_login_seconds)
    selector = config.selectors.get("history_rows", "article, li")
    try:
        page.wait_for_selector(selector, state="attached", timeout=15_000)
    except Exception:
        LOGGER.warning(
            "No history rows found for %s; save the current page for inspection",
            config.name,
        )
    title = norm(args.title)
    cards = page.locator(selector)
    candidates = []
    seen_cards: set[str] = set()
    idle_bottom = 0
    for _ in range(config.max_scroll_steps):
        before = len(seen_cards)
        cards = page.locator(selector)
        for index in range(cards.count()):
            card = cards.nth(index)
            text = card.inner_text(timeout=3_000)
            if title in norm(text):
                key = norm(text)
                if key not in seen_cards:
                    seen_cards.add(key)
                    candidates.append((text[:500], card))
        state = page.evaluate("""() => {
            let node = document.querySelector('.history-body');
            while (node && !(node.scrollHeight > node.clientHeight && /auto|scroll/.test(getComputedStyle(node).overflowY))) node = node.parentElement;
            node ||= document.scrollingElement;
            node.scrollBy(0, Math.max(300, node.clientHeight * .8));
            return {top: node.scrollTop, height: node.scrollHeight, viewport: node.clientHeight};
        }""")
        page.wait_for_timeout(config.scroll_wait_ms)
        bottom = state["top"] + state["viewport"] >= state["height"] - 2
        idle_bottom = idle_bottom + 1 if bottom and len(seen_cards) == before else 0
        if idle_bottom >= 3:
            break
    artifact = args.artifacts_dir / f"{config.name}-{int(time.time())}.html"
    artifact.write_text(page.content(), encoding="utf-8")
    LOGGER.info(
        "%s: %s matching history card(s); artifact=%s",
        config.name,
        len(candidates),
        artifact,
    )
    if not args.apply:
        for text, _card in candidates:
            LOGGER.info("PREVIEW %s: %s", config.name, text.replace("\n", " | "))
        return

    deleted = 0
    for _text, card in candidates:
        buttons = card.locator("button, [role='button'], a")
        action = None
        for button_index in range(buttons.count()):
            button = buttons.nth(button_index)
            label = norm(
                (button.get_attribute("aria-label") or "")
                + " "
                + button.inner_text(timeout=500)
            )
            if any(
                word in label for word in ("supprimer", "remove", "delete", "retirer")
            ):
                action = button
                break
        if action is None:
            LOGGER.warning(
                "%s card=%s matches but has no visible delete control; skipped",
                config.name,
                index,
            )
            continue
        page.once("dialog", lambda dialog: dialog.accept())
        action.click(timeout=5_000)
        page.wait_for_timeout(1_000)
        deleted += 1
    LOGGER.info("%s: clicked %s deletion control(s)", config.name, deleted)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
    )
    main()
