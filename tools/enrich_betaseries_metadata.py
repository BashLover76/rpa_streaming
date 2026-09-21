from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

import httpx

from ingestion.betaseries_client import BetaSeriesClient
from ingestion.db import StreamingDB
from ingestion.logging_config import configure_logging
from ingestion.settings import Settings
from ingestion.catalog_pipeline import CatalogPipeline
from ingestion.title_resolution import IMDbClient, TitleResolver


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
    configure_logging("enrichment", platform=args.platform)

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
    with httpx.Client(timeout=30.0) as http:
        pipeline = CatalogPipeline(db, TitleResolver(IMDbClient(http), client))
        metadata_counts = pipeline.reconcile_existing(
            platform=args.platform, limit=args.limit
        )
    calendar_count = 0
    if not args.skip_calendar:
        with db.connect() as conn:
            query = """SELECT id, titre AS title, betaseries_id FROM series
                       WHERE resolved_imdb_id IS NOT NULL AND betaseries_id IS NOT NULL
                       AND imdb_kind='tv series'"""
            params = []
            if args.platform:
                query += " AND (plateforme=? OR id IN (SELECT serie_id FROM history WHERE plateforme_source=?))"
                params.extend([args.platform, args.platform])
            query += " ORDER BY id LIMIT ?"
            params.append(args.limit)
            shows = conn.execute(query, params).fetchall()
        until = (date.today() + timedelta(days=args.calendar_days_after)).isoformat()
        for row in shows:
            show = {"id": row["betaseries_id"], "title": row["title"]}
            for episode in client.fetch_show_episodes(show["id"]):
                normalized = client._normalize_show_episode(episode, show)
                if (
                    normalized
                    and normalized.get("air_date")
                    and "2026-01-01" <= normalized["air_date"][:10] <= until
                ):
                    db.upsert_calendar_episode(normalized)
                    calendar_count += 1

    print(
        {
            "metadata": metadata_counts,
            "calendar_episodes_upserted": calendar_count,
        }
    )


if __name__ == "__main__":
    main()
