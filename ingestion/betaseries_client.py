from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

import httpx

from .db import StreamingDB

LOGGER = logging.getLogger(__name__)


class BetaSeriesClient:
    BASE_URL = "https://api.betaseries.com"

    def __init__(
        self,
        api_key: str,
        access_token: str,
        db: StreamingDB,
        member_id: int | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("BETASERIES_API_KEY is required")
        if not access_token:
            raise ValueError("BETASERIES_ACCESS_TOKEN is required")
        self.api_key = api_key
        self.access_token = access_token
        self.db = db
        self._member_id = member_id
        self._title_search_cache = {}
        self._title_details_cache = {}

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float = 45.0,
        retries: int = 2,
        retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504),
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        for attempt in range(retries + 1):
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.get(
                        url,
                        headers=self._headers(),
                        params=params,
                    )
                if response.status_code in retry_statuses and attempt < retries:
                    LOGGER.warning(
                        "BetaSeries GET %s returned %s; retrying",
                        path,
                        response.status_code,
                    )
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if response.is_error:
                    LOGGER.warning(
                        "BetaSeries GET %s failed: status=%s body=%s",
                        path,
                        response.status_code,
                        response.text[:500],
                    )
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, dict) else {}
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt >= retries:
                    break
                LOGGER.warning("BetaSeries GET %s timed out; retrying", path)
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(
            f"BetaSeries GET {path} failed after retries"
        ) from last_error

    def _headers(self) -> dict[str, str]:
        return {
            "X-BetaSeries-Key": self.api_key,
            "X-BetaSeries-Version": "3.3",
            "X-BetaSeries-Token": self.access_token,
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

    def fetch_calendar(
        self, days_before: int = 30, days_after: int = 90
    ) -> list[dict[str, Any]]:
        member_id = self.fetch_member_id()
        params = {
            "id": member_id,
            "before": days_before,
            "after": days_after,
            "unseen": "false",
        }
        payload = self._get_json("planning/member", params=params)
        return payload.get("episodes", [])

    def fetch_member_id(self) -> int:
        if self._member_id is not None:
            return self._member_id

        payload = self._get_json("members/infos")

        member = payload.get("member") or payload.get("user") or {}
        member_id = member.get("id")
        if member_id is None:
            raise ValueError("BetaSeries member id was not present in /members/infos")
        self._member_id = int(member_id)
        return self._member_id

    def sync_calendar(self, days_before: int = 30, days_after: int = 90) -> int:
        episodes = self.fetch_calendar(days_before=days_before, days_after=days_after)
        count = 0
        for item in episodes:
            normalized = self._normalize_calendar_item(item)
            if normalized:
                self.db.upsert_calendar_episode(normalized)
                count += 1
        LOGGER.info("BetaSeries calendar synced: %s episodes", count)
        return count

    def sync_calendar_for_titles(
        self,
        titles: list[str],
        *,
        days_after: int = 365,
    ) -> int:
        count = 0
        for title in titles:
            show = self.search_show(title)
            if not show:
                LOGGER.warning("BetaSeries show not found for title: %s", title)
                continue
            self.db.upsert_series(**self._normalize_show(show))
            show_id = show.get("id")
            episodes = self.fetch_show_episodes(show_id)
            max_date = date.today() + timedelta(days=days_after)
            for item in episodes:
                normalized = self._normalize_show_episode(item, show)
                if normalized and self._is_upcoming(
                    normalized.get("air_date"), max_date
                ):
                    self.db.upsert_calendar_episode(normalized)
                    count += 1
        LOGGER.info("BetaSeries title calendar synced: %s episodes", count)
        return count

    def sync_local_series_calendars(
        self,
        *,
        platform: str | None = None,
        days_before: int = 30,
        days_after: int = 180,
        limit: int | None = None,
    ) -> int:
        """Sync calendars for locally resolved BetaSeries shows."""
        query = """
            SELECT id, titre, betaseries_id
            FROM series
            WHERE betaseries_id IS NOT NULL
              AND COALESCE(LOWER(imdb_kind), '') NOT IN ('movie', 'film')
        """
        params: list[Any] = []
        if platform:
            query += """
              AND (
                plateforme = ?
                OR id IN (
                    SELECT DISTINCT serie_id
                    FROM history
                    WHERE plateforme_source = ?
                )
              )
            """
            params.extend([platform, platform])
        query += " ORDER BY updated_at DESC, id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with self.db.connect() as conn:
            rows = conn.execute(query, params).fetchall()

        min_date = date.today() - timedelta(days=days_before)
        max_date = date.today() + timedelta(days=days_after)
        synced = 0
        for row in rows:
            show_id = row["betaseries_id"]
            details = self.title_details(show_id, "series")
            show = details or {"id": show_id, "title": row["titre"]}
            if details:
                self.db.update_series_metadata(
                    int(row["id"]), **self._normalize_show(details)
                )
            for episode in self.fetch_show_episodes(show_id):
                normalized = self._normalize_show_episode(episode, show)
                if not normalized:
                    continue
                if (
                    normalized.get("season") is None
                    or normalized.get("episode") is None
                    or not normalized.get("air_date")
                ):
                    continue
                air_date = _parse_iso_date(normalized.get("air_date"))
                if air_date is None or not (min_date <= air_date <= max_date):
                    continue
                self.db.upsert_calendar_episode(normalized)
                synced += 1
        LOGGER.info("BetaSeries local series calendars synced: %s episodes", synced)
        return synced

    def search_show(self, title: str) -> dict[str, Any] | None:
        try:
            shows = self._get_json("shows/search", params={"title": title}).get(
                "shows", []
            )
        except RuntimeError as exc:
            LOGGER.warning("BetaSeries search failed for %s: %s", title, exc)
            return None
        return shows[0] if shows else None

    def search_titles(self, title: str, kind: str) -> list[dict[str, Any]]:
        cache_key = (title, kind)
        if cache_key in self._title_search_cache:
            return self._title_search_cache[cache_key]
        resource = "movies" if kind == "movie" else "shows"
        results = self._get_json(f"{resource}/search", params={"title": title}).get(
            resource, []
        )
        self._title_search_cache[cache_key] = results
        return results

    def title_details(
        self, title_id: int | str, kind: str, *, imdb: bool = False
    ) -> dict:
        cache_key = (title_id, kind, imdb)
        if cache_key in self._title_details_cache:
            return self._title_details_cache[cache_key]
        endpoint, key = (
            ("movies/movie", "movie") if kind == "movie" else ("shows/display", "show")
        )
        try:
            details = self._get_json(
                endpoint,
                params={"imdb_id" if imdb else "id": title_id},
            ).get(key, {})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400, 404):
                return {}
            raise
        self._title_details_cache[cache_key] = details
        return details

    def search_movie(self, title: str) -> dict[str, Any] | None:
        """Find a BetaSeries movie without confusing it with a TV show."""
        try:
            movies = self._get_json("movies/search", params={"title": title}).get(
                "movies", []
            )
        except RuntimeError as exc:
            LOGGER.warning("BetaSeries movie search failed for %s: %s", title, exc)
            return None
        return movies[0] if movies else None

    def sync_movies(self, titles: list[str]) -> int:
        """Synchronize movie metadata into the shared content table."""
        synced = 0
        for title in titles:
            movie = self.search_movie(title)
            if not movie:
                LOGGER.warning("BetaSeries movie not found for title: %s", title)
                continue
            movie_id = movie.get("id")
            self.db.upsert_series(
                title=movie.get("title") or title,
                betaseries_id=movie_id,
                platform=movie.get("platform"),
                synopsis=movie.get("description") or movie.get("synopsis"),
                poster_url=self._pick_image_url(movie, preferred=("poster", "movie")),
                banner_url=self._pick_image_url(
                    movie, preferred=("banner", "background")
                ),
                genres=movie.get("genres"),
                creation_year=movie.get("release_date") or movie.get("production_year"),
            )
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE series SET imdb_kind = 'movie', updated_at = CURRENT_TIMESTAMP WHERE betaseries_id = ?",
                    (movie_id,),
                )
            synced += 1
        return synced

    def fetch_show_episodes(self, show_id: int | str) -> list[dict[str, Any]]:
        try:
            return self._get_json("shows/episodes", params={"id": show_id}).get(
                "episodes", []
            )
        except RuntimeError as exc:
            LOGGER.warning("BetaSeries episodes failed for show %s: %s", show_id, exc)
            return []

    def find_episode(
        self,
        *,
        show_title: str,
        season: int | None,
        episode: int | None,
    ) -> dict[str, Any] | None:
        if season is None or episode is None:
            if episode is None:
                return None
        if episode is None:
            return None

        show = self.search_show(show_title)
        if not show:
            return None

        episodes = self.fetch_show_episodes(show["id"])
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

    def enrich_local_series(
        self, *, platform: str | None = None, limit: int = 500
    ) -> int:
        query = """
            SELECT id, titre
            FROM series
            WHERE (
                betaseries_id IS NULL
                OR synopsis IS NULL
                OR poster_url IS NULL
                OR betaseries_status IS NULL
                OR genres IS NULL
                OR seasons_count IS NULL
                OR episodes_count IS NULL
            )
        """
        params: list[Any] = []
        if platform:
            query += " AND plateforme = ?"
            params.append(platform)
        query += " ORDER BY updated_at ASC LIMIT ?"
        params.append(limit)

        count = 0
        with self.db.connect() as conn:
            rows = conn.execute(query, params).fetchall()

        for row in rows:
            show = self.search_show(str(row["titre"]))
            if not show:
                continue
            normalized = self._normalize_show(show)
            target_id = int(row["id"])
            existing_id = self._find_local_series_id_by_betaseries_id(
                normalized.get("betaseries_id")
            )
            if existing_id is not None and existing_id != target_id:
                self.db.merge_series(source_id=existing_id, target_id=target_id)
            self.db.update_series_metadata(
                target_id,
                **normalized,
            )
            count += 1
        LOGGER.info("BetaSeries local series metadata enriched: %s", count)
        return count

    def enrich_local_movies(
        self, *, platform: str | None = None, limit: int = 500
    ) -> int:
        """Fill missing movie metadata without treating movie titles as shows."""
        query = """
            SELECT id, titre
            FROM series
            WHERE LOWER(COALESCE(imdb_kind, '')) IN ('movie', 'film')
              AND (poster_url IS NULL OR banner_url IS NULL OR synopsis IS NULL
                   OR betaseries_id IS NULL)
        """
        params: list[Any] = []
        if platform:
            query += " AND plateforme = ?"
            params.append(platform)
        query += " ORDER BY updated_at ASC LIMIT ?"
        params.append(limit)

        with self.db.connect() as conn:
            rows = conn.execute(query, params).fetchall()

        count = 0
        for row in rows:
            movie = self.search_movie(str(row["titre"]))
            if not movie:
                continue
            self.db.update_series_metadata(
                int(row["id"]),
                betaseries_id=movie.get("id"),
                title=movie.get("title") or movie.get("original_title"),
                synopsis=movie.get("synopsis") or movie.get("description"),
                poster_url=movie.get("poster"),
                banner_url=movie.get("backdrop"),
                betaseries_url=movie.get("resource_url") or movie.get("url"),
                genres=movie.get("genres"),
                creation_year=movie.get("production_year"),
                runtime_minutes=(movie.get("length") or 0) // 60 or None,
                language=movie.get("language"),
            )
            count += 1
        LOGGER.info("BetaSeries local movie metadata enriched: %s", count)
        return count

    def _find_local_series_id_by_betaseries_id(
        self, betaseries_id: int | None
    ) -> int | None:
        if betaseries_id is None:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id FROM series WHERE betaseries_id = ?",
                (betaseries_id,),
            ).fetchone()
        return int(row["id"]) if row else None

    def mark_episode_watched(
        self,
        episode_id: int | str,
        *,
        bulk: bool = False,
        delete_future: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, str] = {
            "id": str(episode_id),
            "bulk": "true" if bulk else "false",
        }
        if delete_future:
            params["delete"] = "true"

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{self.BASE_URL}/episodes/watched",
                headers=self._headers(),
                params=params,
            )
            if response.is_error:
                LOGGER.error(
                    "BetaSeries watched update failed for episode %s: status=%s body=%s",
                    episode_id,
                    response.status_code,
                    response.text[:1000],
                )
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _normalize_calendar_item(item: dict[str, Any]) -> dict[str, Any] | None:
        show = item.get("show") or {}
        if not show.get("title"):
            return None

        platform = None
        for broadcaster in item.get("platforms") or item.get("svods") or []:
            if isinstance(broadcaster, dict):
                country = (broadcaster.get("country") or "").lower()
                if country in {"fr", "france", ""}:
                    platform = broadcaster.get("name")
                    break

        return {
            "betaseries_id": show.get("id"),
            "serie_title": show["title"],
            "season": item.get("season") or item.get("saison"),
            "episode": item.get("episode"),
            "episode_title": item.get("title"),
            "air_date": item.get("date") or item.get("release_date"),
            "platform": platform,
            "synopsis": item.get("description") or item.get("synopsis"),
            "image_url": BetaSeriesClient._pick_image_url(item),
            "episode_url": item.get("url") or item.get("link"),
        }

    @staticmethod
    def _normalize_show_episode(
        item: dict[str, Any], show: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not show.get("title"):
            return None
        return {
            "betaseries_id": show.get("id"),
            "serie_title": show["title"],
            "season": item.get("season") or item.get("saison"),
            "episode": item.get("episode"),
            "episode_title": item.get("title"),
            "air_date": item.get("date") or item.get("release_date"),
            "platform": None,
            "synopsis": item.get("description") or item.get("synopsis"),
            "image_url": BetaSeriesClient._pick_image_url(item),
            "episode_url": item.get("url") or item.get("link"),
        }

    @staticmethod
    def _normalize_show(show: dict[str, Any]) -> dict[str, Any]:
        notes = show.get("notes") if isinstance(show.get("notes"), dict) else {}
        return {
            "title": show.get("title") or show.get("original_title") or "Unknown",
            "betaseries_id": show.get("id"),
            "synopsis": show.get("description") or show.get("synopsis"),
            "poster_url": BetaSeriesClient._pick_image_url(
                show, preferred=("poster", "show")
            ),
            "banner_url": BetaSeriesClient._pick_image_url(
                show, preferred=("banner", "background")
            ),
            "betaseries_url": show.get("resource_url")
            or show.get("url")
            or show.get("link"),
            "betaseries_status": show.get("status"),
            "genres": show.get("genres"),
            "seasons_count": show.get("seasons"),
            "episodes_count": show.get("episodes"),
            "followers_count": show.get("followers"),
            "comments_count": show.get("comments"),
            "creation_year": show.get("creation"),
            "runtime_minutes": show.get("length"),
            "network": show.get("network"),
            "country": show.get("country"),
            "rating": show.get("rating"),
            "language": show.get("language"),
            "original_language": show.get("originalLanguage")
            or show.get("original_language"),
            "notes_mean": notes.get("mean"),
            "notes_total": notes.get("total"),
            "last_updated_at": show.get("last_update") or show.get("last_updated_at"),
        }

    @staticmethod
    def _pick_image_url(
        payload: dict[str, Any],
        *,
        preferred: tuple[str, ...] = ("poster", "image", "banner", "show"),
    ) -> str | None:
        images = payload.get("images")
        if isinstance(images, dict):
            for key in preferred:
                value = images.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
                if isinstance(value, dict):
                    nested = BetaSeriesClient._pick_image_url(value)
                    if nested:
                        return nested
            for value in images.values():
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
                if isinstance(value, dict):
                    nested = BetaSeriesClient._pick_image_url(value)
                    if nested:
                        return nested

        for key in preferred:
            value = payload.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
            if isinstance(value, dict):
                nested = BetaSeriesClient._pick_image_url(value)
                if nested:
                    return nested
        return None

    @staticmethod
    def _is_upcoming(raw_date: str | None, max_date: date) -> bool:
        if not raw_date:
            return False
        try:
            air_date = date.fromisoformat(raw_date[:10])
        except ValueError:
            return False
        today = date.today()
        return today <= air_date <= max_date


def _parse_iso_date(raw_date: str | None) -> date | None:
    if not raw_date:
        return None
    try:
        return date.fromisoformat(raw_date[:10])
    except ValueError:
        return None
