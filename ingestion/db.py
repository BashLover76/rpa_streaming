from __future__ import annotations

import sqlite3
import json
import unicodedata
import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class StreamingDB:
    def __init__(
        self,
        db_path: Path | str,
        *,
        stage_history: bool = False,
        default_profile_key: str | None = None,
        default_suitable_for_junior: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        self.stage_history = stage_history
        self.default_profile_key = default_profile_key
        self.default_suitable_for_junior = default_suitable_for_junior

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript("""
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS series (
                    id INTEGER PRIMARY KEY,
                    betaseries_id INTEGER UNIQUE,
                    titre TEXT NOT NULL,
                    plateforme TEXT,
                    synopsis TEXT,
                    poster_url TEXT,
                    banner_url TEXT,
                    betaseries_url TEXT,
                    betaseries_status TEXT,
                    genres TEXT,
                    seasons_count INTEGER,
                    episodes_count INTEGER,
                    followers_count INTEGER,
                    comments_count INTEGER,
                    creation_year INTEGER,
                    runtime_minutes INTEGER,
                    network TEXT,
                    country TEXT,
                    rating TEXT,
                    language TEXT,
                    original_language TEXT,
                    notes_mean REAL,
                    notes_total INTEGER,
                    last_updated_at TEXT,
                    profile_key TEXT,
                    suitable_for_junior INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS calendar (
                    id INTEGER PRIMARY KEY,
                    serie_id INTEGER NOT NULL,
                    saison INTEGER NOT NULL,
                    episode INTEGER NOT NULL,
                    titre_episode TEXT,
                    date_diffusion TEXT,
                    plateforme TEXT,
                    source TEXT NOT NULL DEFAULT 'betaseries',
                    synopsis TEXT,
                    image_url TEXT,
                    episode_url TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (serie_id) REFERENCES series(id) ON DELETE CASCADE,
                    UNIQUE (serie_id, saison, episode, date_diffusion)
                );

                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY,
                    serie_id INTEGER NOT NULL,
                    saison INTEGER,
                    episode INTEGER,
                    date_vu TEXT,
                    plateforme_source TEXT NOT NULL,
                    raw_title TEXT,
                    confidence REAL,
                    episode_title TEXT,
                    episode_url TEXT,
                    progress_percent REAL,
                    status TEXT,
                    betaseries_episode_id INTEGER,
                    betaseries_synced_at TEXT,
                    sync_status TEXT,
                    sync_error TEXT,
                    profile_key TEXT,
                    suitable_for_junior INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (serie_id) REFERENCES series(id) ON DELETE CASCADE,
                    UNIQUE (serie_id, saison, episode, date_vu, plateforme_source)
                );

                CREATE TABLE IF NOT EXISTS series_aliases (
                    titre TEXT NOT NULL,
                    plateforme TEXT NOT NULL,
                    serie_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
                    PRIMARY KEY(titre, plateforme)
                );
                CREATE TABLE IF NOT EXISTS series_sources (
                    source_key TEXT NOT NULL,
                    plateforme TEXT NOT NULL,
                    serie_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
                    PRIMARY KEY(source_key, plateforme)
                );
                CREATE TABLE IF NOT EXISTS raw_history (
                    fingerprint TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reason TEXT,
                    serie_id INTEGER,
                    collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS raw_history_cards (
                    fingerprint TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """)
            self._ensure_series_columns(conn)
            self._ensure_calendar_columns(conn)
            self._ensure_history_columns(conn)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS series_resolved_imdb ON series(resolved_imdb_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS raw_history_status ON raw_history(status, platform)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS history_recent_profile ON history(profile_key, date_vu DESC, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS series_profile_junior ON series(profile_key, suitable_for_junior)"
            )

    @staticmethod
    def _ensure_series_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(series)").fetchall()
        }
        migrations = {
            "resolved_imdb_id": "ALTER TABLE series ADD COLUMN resolved_imdb_id TEXT",
            "betaseries_movie_id": "ALTER TABLE series ADD COLUMN betaseries_movie_id INTEGER",
            "resolution_status": "ALTER TABLE series ADD COLUMN resolution_status TEXT",
            "synopsis": "ALTER TABLE series ADD COLUMN synopsis TEXT",
            "poster_url": "ALTER TABLE series ADD COLUMN poster_url TEXT",
            "banner_url": "ALTER TABLE series ADD COLUMN banner_url TEXT",
            "betaseries_url": "ALTER TABLE series ADD COLUMN betaseries_url TEXT",
            "betaseries_status": "ALTER TABLE series ADD COLUMN betaseries_status TEXT",
            "genres": "ALTER TABLE series ADD COLUMN genres TEXT",
            "seasons_count": "ALTER TABLE series ADD COLUMN seasons_count INTEGER",
            "episodes_count": "ALTER TABLE series ADD COLUMN episodes_count INTEGER",
            "followers_count": "ALTER TABLE series ADD COLUMN followers_count INTEGER",
            "comments_count": "ALTER TABLE series ADD COLUMN comments_count INTEGER",
            "creation_year": "ALTER TABLE series ADD COLUMN creation_year INTEGER",
            "runtime_minutes": "ALTER TABLE series ADD COLUMN runtime_minutes INTEGER",
            "network": "ALTER TABLE series ADD COLUMN network TEXT",
            "country": "ALTER TABLE series ADD COLUMN country TEXT",
            "rating": "ALTER TABLE series ADD COLUMN rating TEXT",
            "language": "ALTER TABLE series ADD COLUMN language TEXT",
            "original_language": "ALTER TABLE series ADD COLUMN original_language TEXT",
            "notes_mean": "ALTER TABLE series ADD COLUMN notes_mean REAL",
            "notes_total": "ALTER TABLE series ADD COLUMN notes_total INTEGER",
            "last_updated_at": "ALTER TABLE series ADD COLUMN last_updated_at TEXT",
            "imdb_url": "ALTER TABLE series ADD COLUMN imdb_url TEXT",
            "imdb_rating": "ALTER TABLE series ADD COLUMN imdb_rating REAL",
            "imdb_votes": "ALTER TABLE series ADD COLUMN imdb_votes INTEGER",
            "imdb_kind": "ALTER TABLE series ADD COLUMN imdb_kind TEXT",
            "imdb_year": "ALTER TABLE series ADD COLUMN imdb_year INTEGER",
            "imdb_plot": "ALTER TABLE series ADD COLUMN imdb_plot TEXT",
            "profile_key": "ALTER TABLE series ADD COLUMN profile_key TEXT",
            "suitable_for_junior": "ALTER TABLE series ADD COLUMN suitable_for_junior INTEGER NOT NULL DEFAULT 0",
        }
        for column, statement in migrations.items():
            if column not in columns:
                conn.execute(statement)

    @staticmethod
    def _ensure_calendar_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(calendar)").fetchall()
        }
        migrations = {
            "synopsis": "ALTER TABLE calendar ADD COLUMN synopsis TEXT",
            "image_url": "ALTER TABLE calendar ADD COLUMN image_url TEXT",
            "episode_url": "ALTER TABLE calendar ADD COLUMN episode_url TEXT",
        }
        for column, statement in migrations.items():
            if column not in columns:
                conn.execute(statement)

    @staticmethod
    def _ensure_history_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(history)").fetchall()
        }
        migrations = {
            "episode_title": "ALTER TABLE history ADD COLUMN episode_title TEXT",
            "episode_url": "ALTER TABLE history ADD COLUMN episode_url TEXT",
            "progress_percent": "ALTER TABLE history ADD COLUMN progress_percent REAL",
            "status": "ALTER TABLE history ADD COLUMN status TEXT",
            "betaseries_episode_id": "ALTER TABLE history ADD COLUMN betaseries_episode_id INTEGER",
            "betaseries_synced_at": "ALTER TABLE history ADD COLUMN betaseries_synced_at TEXT",
            "sync_status": "ALTER TABLE history ADD COLUMN sync_status TEXT",
            "sync_error": "ALTER TABLE history ADD COLUMN sync_error TEXT",
            "profile_key": "ALTER TABLE history ADD COLUMN profile_key TEXT",
            "suitable_for_junior": "ALTER TABLE history ADD COLUMN suitable_for_junior INTEGER NOT NULL DEFAULT 0",
        }
        for column, statement in migrations.items():
            if column not in columns:
                conn.execute(statement)

    def upsert_series(
        self,
        *,
        title: str,
        betaseries_id: int | None = None,
        platform: str | None = None,
        synopsis: str | None = None,
        poster_url: str | None = None,
        banner_url: str | None = None,
        betaseries_url: str | None = None,
        betaseries_status: str | None = None,
        genres: list[str] | dict[str, str] | str | None = None,
        seasons_count: int | None = None,
        episodes_count: int | None = None,
        followers_count: int | None = None,
        comments_count: int | None = None,
        creation_year: int | None = None,
        runtime_minutes: int | None = None,
        network: str | None = None,
        country: str | None = None,
        rating: str | None = None,
        language: str | None = None,
        original_language: str | None = None,
        notes_mean: float | None = None,
        notes_total: int | None = None,
        last_updated_at: str | None = None,
    ) -> int:
        genres_json = self._serialize_genres(genres)
        with self.connect() as conn:
            if betaseries_id is not None:
                conn.execute(
                    """
                    INSERT INTO series (
                        betaseries_id, titre, plateforme, synopsis, poster_url,
                        banner_url, betaseries_url, betaseries_status, genres,
                        seasons_count, episodes_count, followers_count, comments_count,
                        creation_year, runtime_minutes, network, country, rating,
                        language, original_language, notes_mean, notes_total,
                        last_updated_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(betaseries_id) DO UPDATE SET
                        titre = excluded.titre,
                        plateforme = COALESCE(excluded.plateforme, series.plateforme),
                        synopsis = COALESCE(excluded.synopsis, series.synopsis),
                        poster_url = COALESCE(excluded.poster_url, series.poster_url),
                        banner_url = COALESCE(excluded.banner_url, series.banner_url),
                        betaseries_url = COALESCE(excluded.betaseries_url, series.betaseries_url),
                        betaseries_status = COALESCE(excluded.betaseries_status, series.betaseries_status),
                        genres = COALESCE(excluded.genres, series.genres),
                        seasons_count = COALESCE(excluded.seasons_count, series.seasons_count),
                        episodes_count = COALESCE(excluded.episodes_count, series.episodes_count),
                        followers_count = COALESCE(excluded.followers_count, series.followers_count),
                        comments_count = COALESCE(excluded.comments_count, series.comments_count),
                        creation_year = COALESCE(excluded.creation_year, series.creation_year),
                        runtime_minutes = COALESCE(excluded.runtime_minutes, series.runtime_minutes),
                        network = COALESCE(excluded.network, series.network),
                        country = COALESCE(excluded.country, series.country),
                        rating = COALESCE(excluded.rating, series.rating),
                        language = COALESCE(excluded.language, series.language),
                        original_language = COALESCE(excluded.original_language, series.original_language),
                        notes_mean = COALESCE(excluded.notes_mean, series.notes_mean),
                        notes_total = COALESCE(excluded.notes_total, series.notes_total),
                        last_updated_at = COALESCE(excluded.last_updated_at, series.last_updated_at),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        betaseries_id,
                        title,
                        platform,
                        synopsis,
                        poster_url,
                        banner_url,
                        betaseries_url,
                        betaseries_status,
                        genres_json,
                        seasons_count,
                        episodes_count,
                        followers_count,
                        comments_count,
                        creation_year,
                        runtime_minutes,
                        network,
                        country,
                        rating,
                        language,
                        original_language,
                        notes_mean,
                        notes_total,
                        last_updated_at,
                    ),
                )
                row = conn.execute(
                    "SELECT id FROM series WHERE betaseries_id = ?", (betaseries_id,)
                ).fetchone()
                return int(row["id"])

            row = conn.execute(
                "SELECT id FROM series WHERE titre = ?", (title,)
            ).fetchone()
            if not row and platform:
                row = conn.execute(
                    "SELECT serie_id AS id FROM series_aliases WHERE titre = ? AND plateforme = ?",
                    (title, platform),
                ).fetchone()
            if not row and platform:

                def normalized(value: str) -> str:
                    value = unicodedata.normalize("NFKD", value).casefold()
                    return "".join(char for char in value if char.isalnum())

                candidates = conn.execute(
                    "SELECT id, titre FROM series WHERE plateforme = ?", (platform,)
                ).fetchall()
                matches = [
                    candidate
                    for candidate in candidates
                    if normalized(candidate["titre"]) == normalized(title)
                ]
                if len(matches) == 1:
                    row = matches[0]
            if row:
                conn.execute(
                    """
                    UPDATE series
                    SET
                        plateforme = COALESCE(?, plateforme),
                        synopsis = COALESCE(?, synopsis),
                        poster_url = COALESCE(?, poster_url),
                        banner_url = COALESCE(?, banner_url),
                        betaseries_url = COALESCE(?, betaseries_url),
                        betaseries_status = COALESCE(?, betaseries_status),
                        genres = COALESCE(?, genres),
                        seasons_count = COALESCE(?, seasons_count),
                        episodes_count = COALESCE(?, episodes_count),
                        followers_count = COALESCE(?, followers_count),
                        comments_count = COALESCE(?, comments_count),
                        creation_year = COALESCE(?, creation_year),
                        runtime_minutes = COALESCE(?, runtime_minutes),
                        network = COALESCE(?, network),
                        country = COALESCE(?, country),
                        rating = COALESCE(?, rating),
                        language = COALESCE(?, language),
                        original_language = COALESCE(?, original_language),
                        notes_mean = COALESCE(?, notes_mean),
                        notes_total = COALESCE(?, notes_total),
                        last_updated_at = COALESCE(?, last_updated_at),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        platform,
                        synopsis,
                        poster_url,
                        banner_url,
                        betaseries_url,
                        betaseries_status,
                        genres_json,
                        seasons_count,
                        episodes_count,
                        followers_count,
                        comments_count,
                        creation_year,
                        runtime_minutes,
                        network,
                        country,
                        rating,
                        language,
                        original_language,
                        notes_mean,
                        notes_total,
                        last_updated_at,
                        row["id"],
                    ),
                )
                return int(row["id"])
            cursor = conn.execute(
                """
                INSERT INTO series (
                    titre, plateforme, synopsis, poster_url, banner_url, betaseries_url,
                    betaseries_status, genres, seasons_count, episodes_count,
                    followers_count, comments_count, creation_year, runtime_minutes,
                    network, country, rating, language, original_language, notes_mean,
                    notes_total, last_updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    platform,
                    synopsis,
                    poster_url,
                    banner_url,
                    betaseries_url,
                    betaseries_status,
                    genres_json,
                    seasons_count,
                    episodes_count,
                    followers_count,
                    comments_count,
                    creation_year,
                    runtime_minutes,
                    network,
                    country,
                    rating,
                    language,
                    original_language,
                    notes_mean,
                    notes_total,
                    last_updated_at,
                ),
            )
            return int(cursor.lastrowid)

    def upsert_calendar_episode(self, episode: dict[str, Any]) -> None:
        serie_id = self.upsert_series(
            title=episode["serie_title"],
            betaseries_id=episode.get("betaseries_id"),
            platform=episode.get("platform"),
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO calendar (
                    serie_id, saison, episode, titre_episode, date_diffusion,
                    plateforme, source, synopsis, image_url, episode_url, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'betaseries', ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(serie_id, saison, episode, date_diffusion) DO UPDATE SET
                    titre_episode = excluded.titre_episode,
                    plateforme = excluded.plateforme,
                    synopsis = COALESCE(excluded.synopsis, calendar.synopsis),
                    image_url = COALESCE(excluded.image_url, calendar.image_url),
                    episode_url = COALESCE(excluded.episode_url, calendar.episode_url),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    serie_id,
                    episode["season"],
                    episode["episode"],
                    episode.get("episode_title"),
                    episode.get("air_date"),
                    episode.get("platform"),
                    episode.get("synopsis"),
                    episode.get("image_url"),
                    episode.get("episode_url"),
                ),
            )

    def stage_history_item(self, item: dict[str, Any]) -> bool:
        item = self._with_default_profile(item)
        payload = json.dumps(item, sort_keys=True, ensure_ascii=False)
        fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO raw_history(fingerprint, platform, payload) VALUES (?, ?, ?)",
                (fingerprint, item["platform"], payload),
            )
            return cursor.rowcount > 0

    def record_history_cards(self, platform: str, cards: list[str]) -> None:
        with self.connect() as conn:
            for card in cards:
                fingerprint = hashlib.sha256(
                    (platform + card).encode("utf-8")
                ).hexdigest()
                conn.execute(
                    "INSERT OR IGNORE INTO raw_history_cards(fingerprint, platform, payload) VALUES (?, ?, ?)",
                    (fingerprint, platform, card),
                )

    def known_history_cards(self, platform: str, cards: list[str]) -> set[str]:
        if not cards:
            return set()
        fingerprints = {
            hashlib.sha256((platform + card).encode("utf-8")).hexdigest(): card
            for card in cards
        }
        known: set[str] = set()
        items = list(fingerprints.items())
        with self.connect() as conn:
            for start in range(0, len(items), 500):
                batch = items[start : start + 500]
                placeholders = ",".join("?" for _ in batch)
                rows = conn.execute(
                    f"SELECT fingerprint FROM raw_history_cards WHERE platform=? AND fingerprint IN ({placeholders})",
                    [platform, *[fingerprint for fingerprint, _card in batch]],
                ).fetchall()
                for row in rows:
                    known.add(fingerprints[row["fingerprint"]])
        return known

    def insert_history_item(self, item: dict[str, Any]) -> bool:
        item = self._with_default_profile(item)
        if self.stage_history:
            return self.stage_history_item(item)
        serie_id = item.get("serie_id")
        if serie_id is None and item.get("series_source_key"):
            with self.connect() as conn:
                source = conn.execute(
                    "SELECT serie_id FROM series_sources WHERE source_key=? AND plateforme=?",
                    (item["series_source_key"], item["platform"]),
                ).fetchone()
                serie_id = source["serie_id"] if source else None
        if serie_id is None and item.get("episode_url"):
            with self.connect() as conn:
                known = conn.execute(
                    "SELECT DISTINCT serie_id FROM history WHERE episode_url=? AND plateforme_source=?",
                    (item["episode_url"], item["platform"]),
                ).fetchall()
                if len(known) == 1:
                    serie_id = known[0]["serie_id"]
                    conn.execute(
                        "INSERT OR IGNORE INTO series_aliases(titre, plateforme, serie_id) VALUES(?, ?, ?)",
                        (item["serie_title"], item["platform"], serie_id),
                    )
        serie_id = serie_id or self.upsert_series(
            title=item["serie_title"],
            betaseries_id=item.get("betaseries_id"),
            platform=item.get("platform"),
        )
        profile_key = item.get("profile_key")
        suitable_for_junior = 1 if item.get("suitable_for_junior") else 0
        with self.connect() as conn:
            if profile_key:
                conn.execute(
                    """UPDATE series
                       SET profile_key = COALESCE(profile_key, ?),
                           suitable_for_junior = MAX(COALESCE(suitable_for_junior, 0), ?)
                       WHERE id = ?""",
                    (profile_key, suitable_for_junior, serie_id),
                )
            if item.get("series_source_key"):
                conn.execute(
                    "INSERT OR IGNORE INTO series_sources(source_key, plateforme, serie_id) VALUES(?, ?, ?)",
                    (item["series_source_key"], item["platform"], serie_id),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO series_aliases(titre, plateforme, serie_id) VALUES(?, ?, ?)",
                    (item["serie_title"], item["platform"], serie_id),
                )
            # Nullable season/date fields cannot rely on SQLite's UNIQUE rule.
            existing = conn.execute(
                """SELECT id FROM history WHERE serie_id = ? AND plateforme_source = ?
                   AND date_vu IS ? AND (
                       (? IS NOT NULL AND episode_url = ?) OR
                       (saison IS ? AND episode IS ? AND (episode IS NOT NULL OR raw_title IS ?)
                        AND (? IS NULL OR episode_url IS NULL OR episode_url = ?))
                   ) ORDER BY (sync_status = 'synced') DESC, id LIMIT 1""",
                (
                    serie_id,
                    item["platform"],
                    item.get("watched_at"),
                    item.get("episode_url"),
                    item.get("episode_url"),
                    item.get("season"),
                    item.get("episode"),
                    item.get("raw_title"),
                    item.get("episode_url"),
                    item.get("episode_url"),
                ),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE history SET saison=COALESCE(saison, ?), episode=COALESCE(episode, ?),
                       raw_title=COALESCE(?, raw_title), confidence=COALESCE(?, confidence),
                       episode_title=COALESCE(?, episode_title), episode_url=COALESCE(?, episode_url),
                       progress_percent=COALESCE(?, progress_percent), status=COALESCE(?, status),
                       profile_key=COALESCE(profile_key, ?),
                       suitable_for_junior=MAX(COALESCE(suitable_for_junior, 0), ?)
                       WHERE id=?""",
                    (
                        item.get("season"),
                        item.get("episode"),
                        item.get("raw_title"),
                        item.get("confidence"),
                        item.get("episode_title"),
                        item.get("episode_url"),
                        item.get("progress_percent"),
                        item.get("status"),
                        profile_key,
                        suitable_for_junior,
                        existing["id"],
                    ),
                )
                return False
            cursor = conn.execute(
                """
                INSERT INTO history (
                    serie_id, saison, episode, date_vu, plateforme_source,
                    raw_title, confidence, episode_title, episode_url, progress_percent,
                    status, profile_key, suitable_for_junior
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(serie_id, saison, episode, date_vu, plateforme_source) DO UPDATE SET
                    raw_title = COALESCE(excluded.raw_title, history.raw_title),
                    confidence = COALESCE(excluded.confidence, history.confidence),
                    episode_title = COALESCE(excluded.episode_title, history.episode_title),
                    episode_url = COALESCE(excluded.episode_url, history.episode_url),
                    progress_percent = COALESCE(excluded.progress_percent, history.progress_percent),
                    status = COALESCE(excluded.status, history.status),
                    profile_key = COALESCE(history.profile_key, excluded.profile_key),
                    suitable_for_junior = MAX(COALESCE(history.suitable_for_junior, 0), excluded.suitable_for_junior)
                """,
                (
                    serie_id,
                    item.get("season"),
                    item.get("episode"),
                    item.get("watched_at"),
                    item["platform"],
                    item.get("raw_title"),
                    item.get("confidence"),
                    item.get("episode_title"),
                    item.get("episode_url"),
                    item.get("progress_percent"),
                    item.get("status"),
                    profile_key,
                    suitable_for_junior,
                ),
            )
            return cursor.rowcount > 0

    def _with_default_profile(self, item: dict[str, Any]) -> dict[str, Any]:
        if item.get("profile_key") and "suitable_for_junior" in item:
            return item
        enriched = dict(item)
        if self.default_profile_key and not enriched.get("profile_key"):
            enriched["profile_key"] = self.default_profile_key
        enriched.setdefault("suitable_for_junior", self.default_suitable_for_junior)
        return enriched

    def update_history_sync(
        self,
        history_id: int,
        *,
        sync_status: str,
        betaseries_episode_id: int | None = None,
        error: str | None = None,
        synced: bool = False,
    ) -> None:
        synced_at = "CURRENT_TIMESTAMP" if synced else "betaseries_synced_at"
        with self.connect() as conn:
            conn.execute(
                f"""
                UPDATE history
                SET
                    sync_status = ?,
                    betaseries_episode_id = COALESCE(?, betaseries_episode_id),
                    sync_error = ?,
                    betaseries_synced_at = {synced_at}
                WHERE id = ?
                """,
                (sync_status, betaseries_episode_id, error, history_id),
            )

    def update_history_episode_metadata(
        self,
        history_id: int,
        *,
        season: int | None = None,
        episode: int | None = None,
        episode_title: str | None = None,
    ) -> None:
        with self.connect() as conn:
            try:
                conn.execute(
                    """
                    UPDATE history
                    SET
                        saison = COALESCE(?, saison),
                        episode = COALESCE(?, episode),
                        episode_title = COALESCE(?, episode_title)
                    WHERE id = ?
                    """,
                    (season, episode, episode_title, history_id),
                )
            except sqlite3.IntegrityError:
                conn.execute(
                    """
                    UPDATE history
                    SET
                        episode_title = COALESCE(?, episode_title),
                        sync_status = COALESCE(sync_status, 'duplicate_after_resolution')
                    WHERE id = ?
                    """,
                    (episode_title, history_id),
                )

    def update_series_metadata(
        self,
        series_id: int,
        *,
        betaseries_id: int | None = None,
        title: str | None = None,
        synopsis: str | None = None,
        poster_url: str | None = None,
        banner_url: str | None = None,
        betaseries_url: str | None = None,
        betaseries_status: str | None = None,
        genres: list[str] | dict[str, str] | str | None = None,
        seasons_count: int | None = None,
        episodes_count: int | None = None,
        followers_count: int | None = None,
        comments_count: int | None = None,
        creation_year: int | None = None,
        runtime_minutes: int | None = None,
        network: str | None = None,
        country: str | None = None,
        rating: str | None = None,
        language: str | None = None,
        original_language: str | None = None,
        notes_mean: float | None = None,
        notes_total: int | None = None,
        last_updated_at: str | None = None,
    ) -> None:
        genres_json = self._serialize_genres(genres)
        with self.connect() as conn:
            if title:
                conn.execute(
                    """INSERT OR IGNORE INTO series_aliases(titre, plateforme, serie_id)
                       SELECT titre, plateforme, id FROM series WHERE id=? AND plateforme IS NOT NULL""",
                    (series_id,),
                )
            conn.execute(
                """
                UPDATE series
                SET
                    betaseries_id = CASE
                        WHEN ? IS NOT NULL
                         AND NOT EXISTS (
                            SELECT 1 FROM series other
                            WHERE other.betaseries_id = ? AND other.id != ?
                         )
                        THEN ?
                        ELSE betaseries_id
                    END,
                    titre = COALESCE(?, titre),
                    synopsis = COALESCE(?, synopsis),
                    poster_url = COALESCE(?, poster_url),
                    banner_url = COALESCE(?, banner_url),
                    betaseries_url = COALESCE(?, betaseries_url),
                    betaseries_status = COALESCE(?, betaseries_status),
                    genres = COALESCE(?, genres),
                    seasons_count = COALESCE(?, seasons_count),
                    episodes_count = COALESCE(?, episodes_count),
                    followers_count = COALESCE(?, followers_count),
                    comments_count = COALESCE(?, comments_count),
                    creation_year = COALESCE(?, creation_year),
                    runtime_minutes = COALESCE(?, runtime_minutes),
                    network = COALESCE(?, network),
                    country = COALESCE(?, country),
                    rating = COALESCE(?, rating),
                    language = COALESCE(?, language),
                    original_language = COALESCE(?, original_language),
                    notes_mean = COALESCE(?, notes_mean),
                    notes_total = COALESCE(?, notes_total),
                    last_updated_at = COALESCE(?, last_updated_at),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    betaseries_id,
                    betaseries_id,
                    series_id,
                    betaseries_id,
                    title,
                    synopsis,
                    poster_url,
                    banner_url,
                    betaseries_url,
                    betaseries_status,
                    genres_json,
                    seasons_count,
                    episodes_count,
                    followers_count,
                    comments_count,
                    creation_year,
                    runtime_minutes,
                    network,
                    country,
                    rating,
                    language,
                    original_language,
                    notes_mean,
                    notes_total,
                    last_updated_at,
                    series_id,
                ),
            )

    def merge_series(self, *, source_id: int, target_id: int) -> None:
        if source_id == target_id:
            return
        with self.connect() as conn:
            # Match events with nullable fields too, preserving rewatches on other dates.
            duplicates = conn.execute(
                """SELECT source.id AS source_id, target.id AS target_id FROM history source
                   JOIN history target ON target.serie_id=? AND source.serie_id=?
                   AND target.date_vu IS source.date_vu AND target.plateforme_source=source.plateforme_source
                   AND ((source.episode_url IS NOT NULL AND target.episode_url=source.episode_url)
                     OR (target.saison IS source.saison AND target.episode IS source.episode
                       AND (source.episode IS NOT NULL OR target.raw_title IS source.raw_title)))""",
                (target_id, source_id),
            ).fetchall()
            for pair in duplicates:
                for field in (
                    "episode_url",
                    "episode_title",
                    "raw_title",
                    "progress_percent",
                    "status",
                    "betaseries_episode_id",
                    "betaseries_synced_at",
                    "sync_status",
                ):
                    conn.execute(
                        f"UPDATE history SET {field}=COALESCE({field}, (SELECT {field} FROM history WHERE id=?)) WHERE id=?",
                        (pair["source_id"], pair["target_id"]),
                    )
                conn.execute("DELETE FROM history WHERE id=?", (pair["source_id"],))
            calendar_duplicates = conn.execute(
                """SELECT source.id AS source_id, target.id AS target_id FROM calendar source
                   JOIN calendar target ON target.serie_id=? AND source.serie_id=?
                   AND target.saison=source.saison AND target.episode=source.episode
                   AND target.date_diffusion IS source.date_diffusion""",
                (target_id, source_id),
            ).fetchall()
            for pair in calendar_duplicates:
                for field in (
                    "titre_episode",
                    "synopsis",
                    "image_url",
                    "episode_url",
                    "plateforme",
                ):
                    conn.execute(
                        f"UPDATE calendar SET {field}=COALESCE({field}, (SELECT {field} FROM calendar WHERE id=?)) WHERE id=?",
                        (pair["source_id"], pair["target_id"]),
                    )
                conn.execute("DELETE FROM calendar WHERE id=?", (pair["source_id"],))
            conn.execute(
                "UPDATE raw_history SET serie_id=? WHERE serie_id=?",
                (target_id, source_id),
            )
            conn.execute(
                """UPDATE series SET resolved_imdb_id=COALESCE(resolved_imdb_id,
                   (SELECT resolved_imdb_id FROM series WHERE id=?)),
                   betaseries_movie_id=COALESCE(betaseries_movie_id,
                   (SELECT betaseries_movie_id FROM series WHERE id=?)) WHERE id=?""",
                (source_id, source_id, target_id),
            )
            conn.execute(
                """INSERT OR IGNORE INTO series_aliases(titre, plateforme, serie_id)
                   SELECT titre, plateforme, ? FROM series WHERE id=? AND plateforme IS NOT NULL""",
                (target_id, source_id),
            )
            conn.execute(
                "UPDATE series_aliases SET serie_id=? WHERE serie_id=?",
                (target_id, source_id),
            )
            conn.execute(
                "UPDATE series_sources SET serie_id=? WHERE serie_id=?",
                (target_id, source_id),
            )
            conn.execute(
                "UPDATE calendar SET serie_id = ? WHERE serie_id = ?",
                (target_id, source_id),
            )
            conn.execute(
                "UPDATE history SET serie_id = ? WHERE serie_id = ?",
                (target_id, source_id),
            )
            conn.execute(
                """
                UPDATE series
                SET
                    plateforme = COALESCE(plateforme, (SELECT plateforme FROM series WHERE id = ?)),
                    synopsis = COALESCE(synopsis, (SELECT synopsis FROM series WHERE id = ?)),
                    poster_url = COALESCE(poster_url, (SELECT poster_url FROM series WHERE id = ?)),
                    banner_url = COALESCE(banner_url, (SELECT banner_url FROM series WHERE id = ?)),
                    betaseries_url = COALESCE(betaseries_url, (SELECT betaseries_url FROM series WHERE id = ?)),
                    betaseries_status = COALESCE(betaseries_status, (SELECT betaseries_status FROM series WHERE id = ?)),
                    genres = COALESCE(genres, (SELECT genres FROM series WHERE id = ?)),
                    seasons_count = COALESCE(seasons_count, (SELECT seasons_count FROM series WHERE id = ?)),
                    episodes_count = COALESCE(episodes_count, (SELECT episodes_count FROM series WHERE id = ?)),
                    followers_count = COALESCE(followers_count, (SELECT followers_count FROM series WHERE id = ?)),
                    comments_count = COALESCE(comments_count, (SELECT comments_count FROM series WHERE id = ?)),
                    creation_year = COALESCE(creation_year, (SELECT creation_year FROM series WHERE id = ?)),
                    runtime_minutes = COALESCE(runtime_minutes, (SELECT runtime_minutes FROM series WHERE id = ?)),
                    network = COALESCE(network, (SELECT network FROM series WHERE id = ?)),
                    country = COALESCE(country, (SELECT country FROM series WHERE id = ?)),
                    rating = COALESCE(rating, (SELECT rating FROM series WHERE id = ?)),
                    language = COALESCE(language, (SELECT language FROM series WHERE id = ?)),
                    original_language = COALESCE(original_language, (SELECT original_language FROM series WHERE id = ?)),
                    notes_mean = COALESCE(notes_mean, (SELECT notes_mean FROM series WHERE id = ?)),
                    notes_total = COALESCE(notes_total, (SELECT notes_total FROM series WHERE id = ?)),
                    last_updated_at = COALESCE(last_updated_at, (SELECT last_updated_at FROM series WHERE id = ?)),
                    imdb_url = COALESCE(imdb_url, (SELECT imdb_url FROM series WHERE id = ?)),
                    imdb_rating = COALESCE(imdb_rating, (SELECT imdb_rating FROM series WHERE id = ?)),
                    imdb_votes = COALESCE(imdb_votes, (SELECT imdb_votes FROM series WHERE id = ?)),
                    imdb_kind = COALESCE(imdb_kind, (SELECT imdb_kind FROM series WHERE id = ?)),
                    imdb_year = COALESCE(imdb_year, (SELECT imdb_year FROM series WHERE id = ?)),
                    imdb_plot = COALESCE(imdb_plot, (SELECT imdb_plot FROM series WHERE id = ?)),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                tuple([source_id] * 27 + [target_id]),
            )
            source = conn.execute(
                "SELECT betaseries_id FROM series WHERE id = ?",
                (source_id,),
            ).fetchone()
            conn.execute("DELETE FROM series WHERE id = ?", (source_id,))
            if source and source["betaseries_id"] is not None:
                conn.execute(
                    """
                    UPDATE series
                    SET betaseries_id = COALESCE(betaseries_id, ?)
                    WHERE id = ?
                    """,
                    (source["betaseries_id"], target_id),
                )

    def delete_series(self, series_id: int) -> dict[str, int]:
        """Delete one local series and its dependent rows in one transaction."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM series WHERE id = ?", (series_id,)
            ).fetchone()
            if row is None:
                return {"series": 0, "history": 0, "calendar": 0}
            counts = {
                "history": conn.execute(
                    "SELECT COUNT(*) FROM history WHERE serie_id = ?", (series_id,)
                ).fetchone()[0],
                "calendar": conn.execute(
                    "SELECT COUNT(*) FROM calendar WHERE serie_id = ?", (series_id,)
                ).fetchone()[0],
            }
            conn.execute("DELETE FROM raw_history WHERE serie_id=?", (series_id,))
            conn.execute("DELETE FROM history WHERE serie_id = ?", (series_id,))
            conn.execute("DELETE FROM calendar WHERE serie_id = ?", (series_id,))
            conn.execute("DELETE FROM series_aliases WHERE serie_id = ?", (series_id,))
            conn.execute("DELETE FROM series_sources WHERE serie_id = ?", (series_id,))
            conn.execute("DELETE FROM series WHERE id = ?", (series_id,))
            counts["series"] = 1
            return counts

    def update_imdb_metadata(
        self,
        series_id: int,
        *,
        imdb_url: str | None = None,
        imdb_rating: float | None = None,
        imdb_votes: int | None = None,
        imdb_kind: str | None = None,
        imdb_year: int | None = None,
        imdb_plot: str | None = None,
        poster_url: str | None = None,
        synopsis: str | None = None,
        genres: list[str] | dict[str, str] | str | None = None,
    ) -> None:
        genres_json = self._serialize_genres(genres)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE series
                SET
                    imdb_url = COALESCE(?, imdb_url),
                    imdb_rating = COALESCE(?, imdb_rating),
                    imdb_votes = COALESCE(?, imdb_votes),
                    imdb_kind = COALESCE(?, imdb_kind),
                    imdb_year = COALESCE(?, imdb_year),
                    imdb_plot = COALESCE(?, imdb_plot),
                    poster_url = COALESCE(poster_url, ?),
                    synopsis = COALESCE(synopsis, ?),
                    genres = COALESCE(genres, ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    imdb_url,
                    imdb_rating,
                    imdb_votes,
                    imdb_kind,
                    imdb_year,
                    imdb_plot,
                    poster_url,
                    synopsis,
                    genres_json,
                    series_id,
                ),
            )

    @staticmethod
    def _serialize_genres(
        genres: list[str] | dict[str, str] | str | None,
    ) -> str | None:
        if genres is None:
            return None
        if isinstance(genres, str):
            return genres
        if isinstance(genres, dict):
            return json.dumps(list(genres.values()), ensure_ascii=False)
        return json.dumps(genres, ensure_ascii=False)

    def list_series_titles(self, platform: str | None = None) -> list[str]:
        query = "SELECT titre FROM series"
        params: tuple[Any, ...] = ()
        if platform:
            query += " WHERE plateforme = ?"
            params = (platform,)
        query += " ORDER BY titre"
        with self.connect() as conn:
            return [str(row["titre"]) for row in conn.execute(query, params).fetchall()]
