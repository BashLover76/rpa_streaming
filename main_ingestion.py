from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import httpx

from ingestion.betaseries_client import BetaSeriesClient
from ingestion.crunchyroll_client import CrunchyrollClient, CrunchyrollCredentials
from ingestion.db import StreamingDB
from ingestion.logging_config import configure_logging
from ingestion.ollama_client import OllamaClient
from ingestion.rpa_self_healing import SelfHealingRPA, load_platform_configs
from ingestion.runtime_platform import (
    chrome_cdp_ready,
    detect_runtime_platform,
    portable_file_lock,
    start_chrome_cdp,
    terminate_chrome_processes,
    wait_for_chrome_cdp,
)
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
    parser.add_argument(
        "--force-restart-chrome",
        action="store_true",
        help="If Chrome CDP stays unreachable, close Chrome and relaunch it with CDP and the local extension without asking.",
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
    with portable_file_lock(args.lock_file, disabled=args.no_lock):
        run(args)


def run(args: argparse.Namespace) -> None:
    settings = Settings.from_env()
    default_profile = settings.profiles[settings.default_profile_key]
    db = StreamingDB(
        settings.db_path,
        default_profile_key=default_profile.key,
        default_suitable_for_junior=default_profile.is_junior,
    )
    db.init_schema()
    collector_db = StreamingDB(
        settings.db_path,
        stage_history=True,
        default_profile_key=default_profile.key,
        default_suitable_for_junior=default_profile.is_junior,
    )
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
        platform_configs = [
            platform_config
            for platform_config in platform_configs
            if settings.streaming_platforms.get(platform_config.name, True)
        ]
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
            profile_name = settings.rpa_profile_names.get(platform_config.name, "")
            if profile_name.strip():
                platform_config.profile_name = profile_name.strip()
        cdp_url = args.cdp_url or settings.rpa_cdp_url or None
        cdp_timeout_ms = args.cdp_timeout_ms or settings.rpa_cdp_timeout_ms
        if cdp_url and not args.no_auto_start_chrome:
            ensure_chrome_cdp(
                cdp_url,
                timeout_ms=cdp_timeout_ms,
                extension_path=settings.rpa_browser_extension_path,
                force_restart=args.force_restart_chrome,
            )
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
            credentials=settings.rpa_credentials,
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


def ensure_chrome_cdp(
    cdp_url: str,
    *,
    timeout_ms: int,
    extension_path: Path | None = None,
    force_restart: bool = False,
) -> None:
    """Start Chrome for Playwright CDP when the endpoint is down."""
    logger = logging.getLogger(__name__)
    runtime = detect_runtime_platform()
    if chrome_cdp_ready(cdp_url):
        return
    if runtime.is_docker:
        logger.warning(
            "Chrome CDP is not reachable from this Docker container at %s. "
            "Start Chrome on the host with --remote-debugging-port and "
            "--remote-debugging-address=0.0.0.0, or pass --no-auto-start-chrome.",
            cdp_url,
        )
        return

    logger.warning("Chrome CDP is not reachable at %s; starting Chrome.", cdp_url)
    if _start_and_wait_for_chrome(
        cdp_url, timeout_ms=timeout_ms, extension_path=extension_path
    ):
        logger.info("Chrome CDP is ready: %s", cdp_url)
        return

    logger.warning(
        "Chrome was started but CDP did not answer before timeout: %s", cdp_url
    )
    if not _should_restart_chrome(force_restart=force_restart):
        logger.warning(
            "Chrome restart skipped. Close Chrome manually or rerun with "
            "--force-restart-chrome."
        )
        return

    logger.warning("Closing Chrome and relaunching it with CDP and extension support.")
    terminate_chrome_processes()
    time.sleep(2)
    if _start_and_wait_for_chrome(
        cdp_url, timeout_ms=timeout_ms, extension_path=extension_path
    ):
        logger.info("Chrome CDP is ready after restart: %s", cdp_url)
        return
    logger.warning("Chrome CDP still unavailable after forced restart: %s", cdp_url)


def _start_and_wait_for_chrome(
    cdp_url: str,
    *,
    timeout_ms: int,
    extension_path: Path | None,
) -> bool:
    logger = logging.getLogger(__name__)
    try:
        start_chrome_cdp(cdp_url, extension_path=extension_path)
    except (OSError, RuntimeError) as exc:
        logger.warning("Unable to auto-start Chrome for CDP: %s", exc)
        return False
    return wait_for_chrome_cdp(cdp_url, timeout_ms=timeout_ms)


def _should_restart_chrome(*, force_restart: bool) -> bool:
    if detect_runtime_platform().is_docker:
        return False
    if force_restart:
        return True
    if not sys.stdin.isatty():
        return False
    answer = input(
        "Chrome semble déjà ouvert sans CDP/extension. "
        "Fermer Chrome et le relancer avec CDP + extension ? [y/N] "
    )
    return answer.strip().lower() in {"y", "yes", "o", "oui"}


if __name__ == "__main__":
    main()
