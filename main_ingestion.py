from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import httpx

from ingestion.betaseries_client import BetaSeriesClient
from ingestion.crunchyroll_client import CrunchyrollClient, CrunchyrollCredentials
from ingestion.db import StreamingDB
from ingestion.logging_config import configure_logging
from ingestion.ollama_client import OllamaClient
from ingestion.rpa_self_healing import SelfHealingRPA, load_platform_configs
from ingestion.settings import Settings
from ingestion.catalog_pipeline import CatalogPipeline
from ingestion.title_resolution import IMDbClient, TitleResolver


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Streaming ingestion orchestrator")
    parser.add_argument("--skip-betaseries", action="store_true")
    parser.add_argument("--skip-crunchyroll-api", action="store_true")
    parser.add_argument(
        "--skip-crunchyroll-watchlist",
        action="store_true",
        help="Compatibility option: watchlists are no longer imported as history.",
    )
    parser.add_argument("--skip-crunchyroll-history", action="store_true")
    parser.add_argument("--skip-rpa", action="store_true")
    parser.add_argument(
        "--rpa-mode",
        choices=("full", "differential"),
        default="full",
        help="RPA collection mode: full scrolls to the configured limits; differential stops after known history cards.",
    )
    parser.add_argument(
        "--rpa-differential-known-threshold",
        type=int,
        default=20,
        help="Consecutive already-known cards before stopping a differential RPA run.",
    )
    parser.add_argument(
        "--content-type",
        choices=("all", "series", "movie"),
        default="all",
        help="Deprecated: history now always collects both movies and series.",
    )
    parser.add_argument(
        "--reconcile-existing",
        action="store_true",
        help="Back up, reidentify and deduplicate existing local records.",
    )
    parser.add_argument("--retry-unresolved", action="store_true")
    parser.add_argument(
        "--skip-resolution", action="store_true", help="Collect raw history only."
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--platform",
        help="Run RPA for one platform only (e.g. netflix, prime_video, disney_plus, canal_plus, crunchyroll)",
    )
    parser.add_argument(
        "--cdp-url",
        default=None,
        help="Connect to an already running Chrome through CDP, e.g. http://127.0.0.1:9222",
    )
    parser.add_argument(
        "--cdp-timeout-ms",
        type=int,
        default=None,
        help="Maximum time to attach to Chrome CDP before skipping RPA.",
    )
    parser.add_argument(
        "--no-auto-start-chrome",
        action="store_true",
        help="Do not start Windows Chrome automatically when the CDP endpoint is unreachable.",
    )
    parser.add_argument("--pause-seconds", type=float, default=2.0)
    parser.add_argument("--betaseries-days-before", type=int, default=30)
    parser.add_argument("--betaseries-days-after", type=int, default=90)
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=Path(".continue/ingestion.lock"),
        help="Prevent concurrent ingestion runs with a filesystem lock.",
    )
    parser.add_argument("--no-lock", action="store_true")
    return parser.parse_args()


def build_betaseries_client(settings: Settings, db: StreamingDB) -> BetaSeriesClient:
    return BetaSeriesClient(
        api_key=settings.betaseries_api_key,
        access_token=settings.betaseries_access_token,
        db=db,
        member_id=(
            int(settings.betaseries_user_id) if settings.betaseries_user_id else None
        ),
    )


def main() -> None:
    args = parse_args()
    configure_logging("ingestion", platform=args.platform)
    with _ingestion_lock(args.lock_file, disabled=args.no_lock):
        run(args)


def run(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    db = StreamingDB(settings.db_path)
    db.init_schema()
    collector_db = StreamingDB(settings.db_path, stage_history=True)
    if args.content_type != "all":
        logging.warning(
            "--content-type is deprecated: collecting all history; IMDb determines the type."
        )

    beta = None
    if not args.skip_betaseries:
        beta = build_betaseries_client(settings, db)

    if (
        not args.skip_crunchyroll_api
        and settings.crunchyroll_email
        and args.platform in (None, "crunchyroll")
    ):
        try:
            crunchyroll = CrunchyrollClient(
                credentials=CrunchyrollCredentials(
                    email=settings.crunchyroll_email,
                    password=settings.crunchyroll_password,
                    authorization=settings.crunchyroll_authorization or None,
                    profile_id=settings.crunchyroll_profile_id or None,
                    locale=settings.crunchyroll_locale,
                ),
                db=collector_db,
            )
            if not args.skip_crunchyroll_history:
                crunchyroll.sync_history()
            time.sleep(args.pause_seconds)
        except RuntimeError as exc:
            logging.getLogger(__name__).warning("Crunchyroll API skipped: %s", exc)

    if not args.skip_rpa:
        ollama = OllamaClient(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            num_ctx=settings.ollama_num_ctx,
            num_predict=settings.ollama_num_predict,
            timeout=settings.ollama_timeout,
        )
        platform_configs = load_platform_configs(settings.platform_config_path)
        if args.platform:
            platform_configs = [
                platform_config
                for platform_config in platform_configs
                if platform_config.name == args.platform
            ]
            if not platform_configs:
                raise SystemExit(f"Unknown platform: {args.platform}")
        for platform_config in platform_configs:
            platform_config.content_type = args.content_type
        cdp_url = args.cdp_url or settings.rpa_cdp_url or None
        cdp_timeout_ms = args.cdp_timeout_ms or settings.rpa_cdp_timeout_ms
        if cdp_url and not args.no_auto_start_chrome:
            ensure_chrome_cdp(cdp_url, timeout_ms=cdp_timeout_ms)
        rpa = SelfHealingRPA(
            db=collector_db,
            ollama=ollama,
            user_data_dir=settings.rpa_user_data_dir,
            headless=args.headless,
            browser_extension_path=settings.rpa_browser_extension_path,
            cdp_url=cdp_url,
            cdp_timeout_ms=cdp_timeout_ms,
            rpa_mode=args.rpa_mode,
            differential_known_threshold=args.rpa_differential_known_threshold,
        )
        rpa.run_platforms(platform_configs)

    if not args.skip_resolution:
        with httpx.Client(timeout=30.0) as client:
            pipeline = CatalogPipeline(db, TitleResolver(IMDbClient(client), beta))
            logging.info(
                "Existing catalog: %s",
                pipeline.reconcile_existing(
                    platform=args.platform,
                    only_unverified=not args.reconcile_existing,
                ),
            )
            pipeline.run(platform=args.platform, retry=args.retry_unresolved)
    if beta:
        try:
            beta.sync_calendar(
                days_before=args.betaseries_days_before,
                days_after=args.betaseries_days_after,
            )
        except (httpx.HTTPError, RuntimeError) as exc:
            logging.getLogger(__name__).warning(
                "BetaSeries calendar skipped after ingestion: %s", exc
            )


def ensure_chrome_cdp(cdp_url: str, *, timeout_ms: int) -> None:
    """Start Windows Chrome for Playwright CDP when the endpoint is down."""
    logger = logging.getLogger(__name__)
    if _chrome_cdp_ready(cdp_url):
        return

    logger.warning("Chrome CDP is not reachable at %s; starting Chrome.", cdp_url)
    command = (
        "Start-Process chrome.exe "
        "'--remote-debugging-port=9222 --remote-allow-origins=\\* "
        "--user-data-dir=$env:LOCALAPPDATA\\Google\\Chrome\\User Data'"
    )
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.warning("Unable to auto-start Windows Chrome for CDP: %s", exc)
        return

    deadline = time.monotonic() + max(5.0, timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if _chrome_cdp_ready(cdp_url):
            logger.info("Chrome CDP is ready: %s", cdp_url)
            return
        time.sleep(0.5)
    logger.warning("Chrome was started but CDP did not answer before timeout: %s", cdp_url)


def _chrome_cdp_ready(cdp_url: str) -> bool:
    version_url = urljoin(cdp_url.rstrip("/") + "/", "json/version")
    try:
        request = Request(version_url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    return bool(payload.get("webSocketDebuggerUrl"))


@contextlib.contextmanager
def _ingestion_lock(path: Path, *, disabled: bool = False) -> Iterator[None]:
    if disabled:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit(
                f"Another ingestion run is already active: {path}"
            ) from exc
        handle.write(f"{time.time():.0f}\n")
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    main()
