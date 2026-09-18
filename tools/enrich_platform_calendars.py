from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.betaseries_client import BetaSeriesClient
from ingestion.db import StreamingDB
from ingestion.settings import Settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich local platform series with BetaSeries calendars."
    )
    parser.add_argument("platforms", nargs="+")
    parser.add_argument("--days-after", type=int, default=365)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings.from_env()
    db = StreamingDB(settings.db_path)
    beta = BetaSeriesClient(
        settings.betaseries_api_key,
        settings.betaseries_access_token,
        db,
        int(settings.betaseries_user_id) if settings.betaseries_user_id else None,
    )

    total = 0
    for platform in args.platforms:
        titles = db.list_series_titles(platform)
        print({platform: len(titles)})
        total += beta.sync_calendar_for_titles(titles, days_after=args.days_after)
    print({"calendar_inserted": total})


if __name__ == "__main__":
    main()
