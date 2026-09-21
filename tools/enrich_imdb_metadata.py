"""Reidentify the local catalog using the same resolver as history ingestion."""

from __future__ import annotations

import argparse
import logging
import json

import httpx

from ingestion.catalog_pipeline import CatalogPipeline
from ingestion.db import StreamingDB
from ingestion.logging_config import configure_logging
from ingestion.settings import Settings
from ingestion.title_resolution import IMDbClient, TitleResolver
from main_ingestion import build_betaseries_client


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument(
        "--inspect-title", help="Read-only identity diagnostic for one title."
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print unresolved titles without network requests.",
    )
    parser.add_argument(
        "--movies-only",
        action="store_true",
        help="Deprecated: old classifications must also be rechecked.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Compatibility option; all selected rows are rechecked.",
    )
    args = parser.parse_args()
    configure_logging("enrichment", platform=args.platform)
    if args.movies_only:
        logging.warning(
            "--movies-only is deprecated; verifying both movies and series."
        )
    settings = Settings.from_env()
    db = StreamingDB(settings.db_path)
    if args.report:
        db.init_schema()
        print(
            json.dumps(CatalogPipeline(db, None).report(), ensure_ascii=False, indent=2)
        )
        return
    beta = None
    if settings.betaseries_api_key and settings.betaseries_access_token:
        beta = build_betaseries_client(settings, db)
    with httpx.Client(timeout=30.0) as client:
        resolver = TitleResolver(IMDbClient(client), beta)
        if args.inspect_title:
            result = resolver.resolve(args.inspect_title, args.platform or "unknown")
            print(
                json.dumps(
                    {
                        "status": "resolved" if result else "unresolved",
                        "imdb_id": result.imdb["id"] if result else None,
                        "kind": result.kind if result else None,
                        "betaseries_id": (
                            (result.beta or {}).get("id") if result else None
                        ),
                    }
                )
            )
            return
        db.init_schema()
        pipeline = CatalogPipeline(db, resolver)
        print(pipeline.reconcile_existing(platform=args.platform, limit=args.limit))


if __name__ == "__main__":
    main()
