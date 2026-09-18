from __future__ import annotations

import argparse
import logging

from ingestion.betaseries_client import BetaSeriesClient
from ingestion.db import StreamingDB
from ingestion.settings import Settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich local series metadata and upcoming calendars from BetaSeries."
    )
    parser.add_argument("--platform", help="Limit enrichment to one local platform.")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--calendar-days-after", type=int, default=365)
    parser.add_argument(
        "--skip-calendar",
        action="store_true",
        help="Only enrich series metadata, without fetching upcoming episodes.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    settings = Settings.from_env()
    db = StreamingDB(settings.db_path)
    db.init_schema()
    client = BetaSeriesClient(
        api_key=settings.betaseries_api_key,
        access_token=settings.betaseries_access_token,
        db=db,
        member_id=(
            int(settings.betaseries_user_id) if settings.betaseries_user_id else None
        ),
    )

    metadata_count = client.enrich_local_series(
        platform=args.platform, limit=args.limit
    )
    calendar_count = 0
    if not args.skip_calendar:
        titles = db.list_series_titles(platform=args.platform)
        calendar_count = client.sync_calendar_for_titles(
            titles[: args.limit],
            days_after=args.calendar_days_after,
        )

    print(
        {
            "metadata_enriched": metadata_count,
            "calendar_episodes_upserted": calendar_count,
        }
    )


if __name__ == "__main__":
    main()
