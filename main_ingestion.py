from __future__ import annotations

import argparse
import logging
import time

from ingestion.betaseries_client import BetaSeriesClient
from ingestion.crunchyroll_client import CrunchyrollClient, CrunchyrollCredentials
from ingestion.db import StreamingDB
from ingestion.ollama_client import OllamaClient
from ingestion.rpa_self_healing import SelfHealingRPA, load_platform_configs
from ingestion.settings import Settings


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Streaming ingestion orchestrator")
    parser.add_argument("--skip-betaseries", action="store_true")
    parser.add_argument("--skip-crunchyroll-api", action="store_true")
    parser.add_argument("--skip-crunchyroll-watchlist", action="store_true")
    parser.add_argument("--skip-crunchyroll-history", action="store_true")
    parser.add_argument("--skip-rpa", action="store_true")
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
    parser.add_argument("--pause-seconds", type=float, default=2.0)
    parser.add_argument("--betaseries-days-before", type=int, default=30)
    parser.add_argument("--betaseries-days-after", type=int, default=90)
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
    configure_logging()
    args = parse_args()
    settings = Settings.from_env()
    db = StreamingDB(settings.db_path)
    db.init_schema()

    beta = None
    if not args.skip_betaseries:
        beta = build_betaseries_client(settings, db)
        beta.sync_calendar(
            days_before=args.betaseries_days_before,
            days_after=args.betaseries_days_after,
        )
        time.sleep(args.pause_seconds)

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
                db=db,
            )
            if not args.skip_crunchyroll_history:
                crunchyroll.sync_history()
            if not args.skip_crunchyroll_watchlist:
                crunchyroll.sync_watchlist()
            if not args.skip_betaseries:
                beta = beta or build_betaseries_client(settings, db)
                beta.sync_calendar_for_titles(
                    db.list_series_titles(platform="crunchyroll"),
                    days_after=args.betaseries_days_after,
                )
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
        rpa = SelfHealingRPA(
            db=db,
            ollama=ollama,
            user_data_dir=settings.rpa_user_data_dir,
            headless=args.headless,
            browser_extension_path=settings.rpa_browser_extension_path,
            cdp_url=args.cdp_url or settings.rpa_cdp_url or None,
        )
        rpa.run_platforms(platform_configs)


if __name__ == "__main__":
    main()
