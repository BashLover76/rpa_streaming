from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.db import StreamingDB
from ingestion.settings import Settings

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fallback metadata enrichment from IMDb for local titles."
    )
    parser.add_argument("--platform", help="Limit enrichment to one local platform.")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Enrich all rows, not only rows missing BetaSeries metadata.",
    )
    return parser.parse_args()


def fetch_candidates(
    db: StreamingDB, *, platform: str | None, limit: int, all_rows: bool
):
    where = []
    params: list[Any] = []
    if platform:
        where.append("plateforme = ?")
        params.append(platform)
    if not all_rows:
        where.append("""
            (
                betaseries_id IS NULL
                OR synopsis IS NULL
                OR poster_url IS NULL
                OR imdb_url IS NULL
            )
            """)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(limit)
    with db.connect() as conn:
        return conn.execute(
            f"""
            SELECT id, titre
            FROM series
            {where_sql}
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            params,
        ).fetchall()


def normalize_movie(movie) -> dict[str, Any]:
    imdb_id = movie.movieID
    genres = movie.get("genres")
    plot = movie.get("plot outline")
    if not plot:
        plots = movie.get("plot")
        if isinstance(plots, list) and plots:
            plot = str(plots[0]).split("::", 1)[0]
    cover_url = movie.get("full-size cover url") or movie.get("cover url")
    return {
        "imdb_url": (
            f"https://www.imdb.com/title/tt{int(imdb_id):07d}/" if imdb_id else None
        ),
        "imdb_rating": movie.get("rating"),
        "imdb_votes": movie.get("votes"),
        "imdb_kind": movie.get("kind"),
        "imdb_year": movie.get("year"),
        "imdb_plot": plot,
        "poster_url": cover_url,
        "synopsis": plot,
        "genres": genres,
    }


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        from imdb import Cinemagoer
    except ImportError as exc:
        raise SystemExit(
            "Cinemagoer is missing. Install dependencies with: pip install -r requirements.txt"
        ) from exc

    settings = Settings.from_env()
    db = StreamingDB(settings.db_path)
    db.init_schema()
    ia = Cinemagoer()

    rows = fetch_candidates(
        db,
        platform=args.platform,
        limit=args.limit,
        all_rows=args.all,
    )
    enriched = 0
    missed = 0
    for row in rows:
        title = str(row["titre"])
        results = ia.search_movie(title)
        if not results:
            missed += 1
            LOGGER.warning("IMDb title not found: %s", title)
            continue
        movie = results[0]
        ia.update(movie)
        db.update_imdb_metadata(int(row["id"]), **normalize_movie(movie))
        enriched += 1
        LOGGER.info("IMDb enriched: %s -> tt%s", title, movie.movieID)

    print({"imdb_enriched": enriched, "imdb_missed": missed})


if __name__ == "__main__":
    main()
