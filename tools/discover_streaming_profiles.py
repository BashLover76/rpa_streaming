from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from ingestion.rpa_self_healing import PlatformConfig, load_platform_configs
from ingestion.settings import Settings


LOGGER = logging.getLogger(__name__)
DEFAULT_OUTPUT = Path(".continue/platform_profiles_discovered.json")

PROFILE_TEXT_SELECTORS = [
    "[data-uia='profile-name']",
    "[data-uia='profile-link']",
    "[data-testid*='profile' i]",
    "[aria-label*='profile' i]",
    "[aria-label*='profil' i]",
    ".profile-name",
    "[class*='profile' i]",
    "[class*='avatar' i]",
    "[data-testid*='avatar' i]",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect visible streaming profile names from Chrome CDP."
    )
    parser.add_argument("--platform", action="append", help="Limit detection to one platform.")
    parser.add_argument("--cdp-url", default=None, help="Chrome CDP URL.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout-ms", type=int, default=20_000)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    args = parse_args()
    settings = Settings.from_env()
    cdp_url = args.cdp_url or settings.rpa_cdp_url
    if not cdp_url:
        raise SystemExit("Missing CDP URL. Use --cdp-url or RPA_CDP_URL.")

    platform_configs = [
        config
        for config in load_platform_configs(settings.platform_config_path)
        if settings.streaming_platforms.get(config.name, True)
    ]
    if args.platform:
        selected = set(args.platform)
        platform_configs = [config for config in platform_configs if config.name in selected]
    if not platform_configs:
        raise SystemExit("No configured platform matched the requested filters.")

    detected: dict[str, list[dict[str, str]]] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(cdp_url, timeout=args.timeout_ms)
        try:
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            for config in platform_configs:
                try:
                    profiles = detect_platform_profiles(page, config, args.timeout_ms)
                    detected[config.name] = [
                        {
                            "profile_key": slugify(profile),
                            "profile_label": profile,
                            "platform_profile_name": profile,
                        }
                        for profile in profiles
                    ]
                except Exception as exc:
                    LOGGER.warning("%s profile detection failed: %s", config.name, exc)
                    detected[config.name] = []
        finally:
            browser.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(detected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(detected, ensure_ascii=False, indent=2))
    LOGGER.info("Discovered profile cache written to %s", args.output)


def detect_platform_profiles(page: Page, config: PlatformConfig, timeout_ms: int) -> list[str]:
    LOGGER.info("Detecting profiles for %s", config.name)
    page.goto(config.start_url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_timeout(2_000)
    candidates = collect_profile_texts(page, config)
    LOGGER.info("%s profiles detected: %s", config.name, candidates or "none")
    return candidates


def collect_profile_texts(page: Page, config: PlatformConfig) -> list[str]:
    selectors = []
    configured_selector = config.selectors.get("profile")
    if configured_selector:
        selectors.append(configured_selector)
    selectors.extend(PROFILE_TEXT_SELECTORS)

    names: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = min(locator.count(), 80)
        except Exception:
            continue
        for index in range(count):
            try:
                item = locator.nth(index)
                if not item.is_visible(timeout=500):
                    continue
                if not looks_like_profile_element(item):
                    continue
                text = (
                    item.inner_text(timeout=500)
                    or item.get_attribute("aria-label")
                    or item.get_attribute("title")
                    or ""
                )
            except (PlaywrightTimeoutError, Exception):
                continue
            profile = profile_text(text)
            if profile and profile.casefold() not in seen:
                seen.add(profile.casefold())
                names.append(profile)
    return names


def profile_text(raw: str) -> str:
    text = " ".join(raw.replace("\n", " ").split()).strip()
    rejected = {
        "",
        "accueil",
        "home",
        "login",
        "connexion",
        "search",
        "rechercher",
        "mes vidéos",
        "mes videos",
        "watchlist",
        "lecture",
        "reprendre",
        "voir plus",
        "show more",
        "gérer",
        "gerer",
        "modifier",
        "ajouter",
        "continue",
        "contact us",
        "faq",
        "help center",
        "get help",
        "help",
        "need help?",
        "conditions of use",
        "terms and privacy notice",
        "send us feedback",
        "create your amazon account",
        "cloudflare",
        "netflix",
        "netflix shop",
        "privacy",
        "terms of use",
        "corporate information",
        "ad choices",
        "cookie preferences",
        "cookies and similar technologies",
        "learn more",
        "reject",
        "accept",
        "close",
    }
    if text.casefold() in rejected:
        return ""
    if len(text) > 40:
        return ""
    lowered = text.casefold()
    rejected_fragments = (
        "cookie",
        "privacy",
        "conditions",
        "terms",
        "help",
        "support",
        "cloudflare",
        "captcha",
        "login",
        "sign in",
        "connexion",
        "account",
        "feedback",
        "footer",
    )
    if any(fragment in lowered for fragment in rejected_fragments):
        return ""
    return text


def looks_like_profile_element(item) -> bool:
    attributes = " ".join(
        value or ""
        for value in [
            item.get_attribute("data-uia"),
            item.get_attribute("data-testid"),
            item.get_attribute("aria-label"),
            item.get_attribute("class"),
            item.get_attribute("href"),
            item.get_attribute("role"),
            item.get_attribute("title"),
        ]
    ).casefold()
    positive = ("profile", "profil", "avatar", "user", "account-menu", "accountswitch")
    negative = (
        "footer",
        "help",
        "privacy",
        "cookie",
        "terms",
        "legal",
        "login",
        "signin",
        "sign-in",
        "register",
        "support",
        "feedback",
    )
    return any(token in attributes for token in positive) and not any(
        token in attributes for token in negative
    )


def slugify(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")


if __name__ == "__main__":
    main()
