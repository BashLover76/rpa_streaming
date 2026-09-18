from __future__ import annotations

import argparse
import logging
from typing import Any

from ingestion.betaseries_client import BetaSeriesClient
from ingestion.db import StreamingDB
from ingestion.settings import Settings

LOGGER = logging.getLogger(__name__)


class CachedBetaSeriesResolver:
    def __init__(self, client: BetaSeriesClient) -> None:
        self.client = client
        self._show_cache: dict[str, dict[str, Any] | None] = {}
        self._episodes_cache: dict[int, list[dict[str, Any]]] = {}

    def find_episode(
        self,
        *,
        show_title: str,
        season: int | None,
        episode: int | None,
    ) -> dict[str, Any] | None:
        if episode is None:
            return None
        show_key = show_title.casefold()
        if show_key not in self._show_cache:
            self._show_cache[show_key] = self.client.search_show(show_title)
        show = self._show_cache[show_key]
        if not show or show.get("id") is None:
            return None

        show_id = int(show["id"])
        if show_id not in self._episodes_cache:
            self._episodes_cache[show_id] = self.client.fetch_show_episodes(show_id)
        episodes = self._episodes_cache[show_id]

        if season is None:
            matches = [
                item
                for item in episodes
                if int(item.get("episode") or 0) == int(episode)
            ]
            return matches[0] if len(matches) == 1 else None

        for item in episodes:
            item_season = item.get("season") or item.get("saison")
            item_episode = item.get("episode")
            if int(item_season or 0) == int(season) and int(item_episode or 0) == int(
                episode
            ):
                return item
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve local streaming history rows to BetaSeries episodes and optionally "
            "mark them as watched on the BetaSeries account."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write watched episodes to BetaSeries. Without this flag, the command is a dry run.",
    )
    parser.add_argument(
        "--platform",
        help="Limit sync to one platform_source, for example crunchyroll or netflix.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of history rows to inspect.",
    )
    parser.add_argument(
        "--bulk",
        action="store_true",
        help="Ask BetaSeries to mark previous episodes as watched too.",
    )
    return parser.parse_args()


def fetch_candidates(
    db: StreamingDB, *, platform: str | None, limit: int
) -> list[dict[str, Any]]:
    where = [
        "h.episode IS NOT NULL",
        "COALESCE(h.status, '') NOT IN ('in_progress', 'next_episode')",
        "(h.sync_status IS NULL OR h.sync_status != 'synced')",
    ]
    params: list[Any] = []
    if platform:
        where.append("h.plateforme_source = ?")
        params.append(platform)
    params.append(limit)

    with db.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                h.id,
                h.saison,
                h.episode,
                h.date_vu,
                h.plateforme_source,
                h.raw_title,
                h.confidence,
                s.titre AS serie_title
            FROM history h
            JOIN series s ON s.id = h.serie_id
            WHERE {' AND '.join(where)}
            ORDER BY h.date_vu DESC, h.created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def episode_id_from_payload(episode: dict[str, Any]) -> int | None:
    raw_id = episode.get("id")
    if raw_id is None:
        return None
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    settings = Settings.from_env()
    db = StreamingDB(settings.db_path)
    db.init_schema()
    betaseries = BetaSeriesClient(
        api_key=settings.betaseries_api_key,
        access_token=settings.betaseries_access_token,
        db=db,
        member_id=(
            int(settings.betaseries_user_id) if settings.betaseries_user_id else None
        ),
    )
    resolver = CachedBetaSeriesResolver(betaseries)

    candidates = fetch_candidates(db, platform=args.platform, limit=args.limit)
    if not candidates:
        print(
            "Aucune ligne d'historique éligible: il faut au minimum saison + épisode."
        )
        return

    matched = 0
    synced = 0
    failed = 0
    posted_episode_ids: set[int] = set()
    for row in candidates:
        season_label = (
            f"S{int(row['saison']):02d}" if row["saison"] is not None else "S??"
        )
        label = (
            f"{row['serie_title']} {season_label}E{int(row['episode']):02d} "
            f"({row['plateforme_source']})"
        )
        episode = resolver.find_episode(
            show_title=row["serie_title"],
            season=int(row["saison"]) if row["saison"] is not None else None,
            episode=int(row["episode"]),
        )
        episode_id = episode_id_from_payload(episode or {})
        if episode_id is None:
            failed += 1
            db.update_history_sync(
                int(row["id"]),
                sync_status="unmatched",
                error="Episode BetaSeries introuvable",
            )
            print(f"[unmatched] {label}")
            continue

        resolved_season = episode.get("season") or episode.get("saison")
        resolved_episode = episode.get("episode")
        db.update_history_episode_metadata(
            int(row["id"]),
            season=int(resolved_season) if resolved_season is not None else None,
            episode=int(resolved_episode) if resolved_episode is not None else None,
            episode_title=episode.get("title"),
        )
        matched += 1
        if not args.apply:
            db.update_history_sync(
                int(row["id"]),
                sync_status="matched",
                betaseries_episode_id=episode_id,
            )
            print(f"[dry-run] {label} -> BetaSeries episode {episode_id}")
            continue

        if episode_id in posted_episode_ids:
            synced += 1
            db.update_history_sync(
                int(row["id"]),
                sync_status="synced",
                betaseries_episode_id=episode_id,
                synced=True,
            )
            print(f"[synced-local] {label} -> BetaSeries episode {episode_id}")
            continue

        try:
            betaseries.mark_episode_watched(episode_id, bulk=args.bulk)
        except Exception as exc:
            failed += 1
            db.update_history_sync(
                int(row["id"]),
                sync_status="error",
                betaseries_episode_id=episode_id,
                error=str(exc)[:500],
            )
            print(f"[error] {label} -> {exc}")
            continue

        synced += 1
        posted_episode_ids.add(episode_id)
        db.update_history_sync(
            int(row["id"]),
            sync_status="synced",
            betaseries_episode_id=episode_id,
            synced=True,
        )
        print(f"[synced] {label} -> BetaSeries episode {episode_id}")

    mode = "apply" if args.apply else "dry-run"
    print(
        f"Résumé {mode}: {matched} correspondances, {synced} envoyés, {failed} échecs."
    )


if __name__ == "__main__":
    main()
