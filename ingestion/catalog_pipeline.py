"""Stage history, resolve identities, enrich records and merge confirmed duplicates."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import httpx

from .betaseries_client import BetaSeriesClient
from .db import StreamingDB
from .title_resolution import Resolution, TitleResolver, clean_title

LOGGER = logging.getLogger(__name__)


def backup_database(db: StreamingDB) -> Path:
    target = (
        db.db_path.parent
        / "backups"
        / f"before-resolution-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with db.connect() as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    return target


class CatalogPipeline:
    def __init__(self, db: StreamingDB, resolver: TitleResolver):
        self.db = db
        self.resolver = resolver

    def enrich(self, series_id: int, result: Resolution) -> int:
        candidate, beta = result.imdb, result.beta or {}
        image = candidate.get("i") or {}
        with self.db.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM series WHERE resolved_imdb_id=? AND id != ? ORDER BY id",
                (candidate["id"], series_id),
            ).fetchall()
            conn.execute(
                "UPDATE series SET resolved_imdb_id=?, imdb_kind=?, imdb_url=?, imdb_year=?, resolution_status='resolved' WHERE id=?",
                (
                    candidate["id"],
                    "movie" if result.kind == "movie" else "tv series",
                    f"https://www.imdb.com/title/{candidate['id']}/",
                    candidate.get("y"),
                    series_id,
                ),
            )
            if result.kind == "movie":
                conn.execute(
                    """UPDATE series SET betaseries_movie_id=?, betaseries_id=NULL,
                       seasons_count=NULL, episodes_count=NULL, betaseries_status=NULL WHERE id=?""",
                    (beta.get("id"), series_id),
                )
            else:
                conn.execute(
                    "UPDATE series SET betaseries_movie_id=NULL WHERE id=?",
                    (series_id,),
                )
        self.db.update_imdb_metadata(series_id, poster_url=image.get("imageUrl"))
        if beta:
            if result.kind == "series":
                metadata = BetaSeriesClient._normalize_show(beta)
            else:
                metadata = dict(
                    title=beta.get("title"),
                    synopsis=beta.get("synopsis") or beta.get("description"),
                    poster_url=beta.get("poster"),
                    banner_url=beta.get("backdrop"),
                    betaseries_url=beta.get("resource_url"),
                    genres=beta.get("genres"),
                    creation_year=beta.get("production_year"),
                    language=beta.get("language"),
                    runtime_minutes=int(beta.get("length") or 0) // 60 or None,
                )
            self.db.update_series_metadata(series_id, **metadata)
        for duplicate in existing:
            target = min(series_id, duplicate["id"])
            self.db.merge_series(
                source_id=max(series_id, duplicate["id"]), target_id=target
            )
            series_id = target
        return series_id

    def run(self, *, platform=None, limit=None, retry=False) -> dict:
        query = "SELECT * FROM raw_history WHERE status " + (
            "!= 'resolved'" if retry else "= 'pending'"
        )
        params = []
        if platform:
            query += " AND platform=?"
            params.append(platform)
        query += " ORDER BY collected_at, fingerprint"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self.db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        stats = dict(resolved=0, unresolved=0, errors=0)
        identities = {}
        failed = set()
        for row in rows:
            item = json.loads(row["payload"])
            title = clean_title(item["serie_title"])
            lookup_key = (
                title,
                row["platform"],
                item.get("episode") is not None,
                item.get("year"),
            )
            if lookup_key in failed:
                self._status(
                    row["fingerprint"], "error", "Lookup already failed in this run"
                )
                stats["errors"] += 1
                continue
            try:
                result = self.resolver.resolve(
                    title,
                    row["platform"],
                    episodic=item.get("episode") is not None,
                    year=item.get("year"),
                )
                if result is None:
                    self._status(
                        row["fingerprint"], "unresolved", "No unambiguous IMDb identity"
                    )
                    stats["unresolved"] += 1
                    continue
                external_id = result.imdb["id"]
                series_id = identities.get(external_id)
                if series_id is None:
                    with self.db.connect() as conn:
                        known = conn.execute(
                            "SELECT id FROM series WHERE resolved_imdb_id=? ORDER BY id LIMIT 1",
                            (external_id,),
                        ).fetchone()
                        if known:
                            series_id = known["id"]
                        else:
                            # A title alone must not join two remakes or homonyms.
                            series_id = conn.execute(
                                "INSERT INTO series(titre, plateforme) VALUES (?, ?)",
                                (title, row["platform"]),
                            ).lastrowid
                    series_id = self.enrich(series_id, result)
                    identities[external_id] = series_id
                item["serie_id"] = series_id
                item["serie_title"] = title
                if result.kind == "movie":
                    item["season"] = item["episode"] = None
                self.db.insert_history_item(item)
                self._status(row["fingerprint"], "resolved", None, series_id)
                stats["resolved"] += 1
            except (httpx.HTTPError, RuntimeError, ValueError, TypeError) as exc:
                failed.add(lookup_key)
                self._status(row["fingerprint"], "error", type(exc).__name__)
                LOGGER.warning(
                    "Resolution failed for %s (%s)", title, type(exc).__name__
                )
                stats["errors"] += 1
        LOGGER.info("Catalog resolution: %s", stats)
        return stats

    def _status(self, fingerprint, status, reason, series_id=None):
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE raw_history SET status=?, reason=?, serie_id=? WHERE fingerprint=?",
                (status, reason, series_id, fingerprint),
            )

    def reconcile_existing(
        self, *, platform=None, limit=None, only_unverified=False
    ) -> dict:
        """Recheck legacy records; only confirmed IMDb matches may be merged."""
        with self.db.connect() as conn:
            query = "SELECT id, titre, plateforme FROM series WHERE 1=1"
            params = []
            if platform:
                query += " AND (plateforme=? OR id IN (SELECT serie_id FROM history WHERE plateforme_source=?))"
                params.append(platform)
                params.append(platform)
            if only_unverified:
                query += " AND resolution_status IS NULL"
            query += " ORDER BY id"
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)
            rows = conn.execute(query, params).fetchall()
        if rows:
            LOGGER.info("Database backup: %s", backup_database(self.db))
        stats = dict(resolved=0, unresolved=0, errors=0)
        for row in rows:
            with self.db.connect() as conn:
                if not conn.execute(
                    "SELECT id FROM series WHERE id=?", (row["id"],)
                ).fetchone():
                    continue
                episodic = (
                    conn.execute(
                        "SELECT 1 FROM history WHERE serie_id=? AND episode IS NOT NULL LIMIT 1",
                        (row["id"],),
                    ).fetchone()
                    is not None
                )
            try:
                result = self.resolver.resolve(
                    row["titre"], row["plateforme"] or "unknown", episodic=episodic
                )
                if result:
                    self.enrich(row["id"], result)
                    stats["resolved"] += 1
                    LOGGER.info(
                        "Identified local id=%s: %s (%s)",
                        row["id"],
                        result.imdb["id"],
                        result.kind,
                    )
                else:
                    stats["unresolved"] += 1
                    with self.db.connect() as conn:
                        conn.execute(
                            "UPDATE series SET resolution_status='unresolved' WHERE id=?",
                            (row["id"],),
                        )
            except (httpx.HTTPError, RuntimeError, ValueError, TypeError) as exc:
                LOGGER.warning(
                    "Legacy resolution failed: id=%s (%s)",
                    row["id"],
                    type(exc).__name__,
                )
                stats["errors"] += 1
        return stats

    def report(self) -> dict:
        with self.db.connect() as conn:
            cards = [
                dict(row)
                for row in conn.execute(
                    "SELECT platform, COUNT(*) AS cards FROM raw_history_cards GROUP BY platform"
                )
            ]
            history = [
                dict(row)
                for row in conn.execute(
                    "SELECT platform, status, COUNT(*) AS events FROM raw_history GROUP BY platform,status"
                )
            ]
            unresolved = [
                dict(row)
                for row in conn.execute(
                    "SELECT id,titre,plateforme,resolution_status FROM series WHERE resolution_status='unresolved'"
                )
            ]
            pending = [
                dict(row)
                for row in conn.execute(
                    """SELECT platform, json_extract(payload,'$.serie_title') AS title, status, reason,
                   COUNT(*) AS events FROM raw_history WHERE status!='resolved'
                   GROUP BY platform,title,status,reason"""
                )
            ]
        return dict(
            source_cards=cards,
            history=history,
            unresolved_catalog=unresolved,
            pending_titles=pending,
        )
