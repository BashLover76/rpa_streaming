from __future__ import annotations

import logging
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
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{self.BASE_URL}/planning/member",
                headers=self._headers(),
                params=params,
            )
            if response.is_error:
                LOGGER.error(
                    "BetaSeries calendar request failed: status=%s",
                    response.status_code,
                )
            response.raise_for_status()
            payload = response.json()
        return payload.get("episodes", [])

    def fetch_member_id(self) -> int:
        if self._member_id is not None:
            return self._member_id

        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{self.BASE_URL}/members/infos",
                headers=self._headers(),
            )
            if response.is_error:
                LOGGER.error(
                    "BetaSeries member info request failed: status=%s",
                    response.status_code,
                )
            response.raise_for_status()
            payload = response.json()

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

    def search_show(self, title: str) -> dict[str, Any] | None:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{self.BASE_URL}/shows/search",
                headers=self._headers(),
                params={"title": title},
            )
            if response.is_error:
                LOGGER.warning(
                    "BetaSeries search failed for %s: status=%s",
                    title,
                    response.status_code,
                )
                return None
            shows = response.json().get("shows", [])
        return shows[0] if shows else None

    def fetch_show_episodes(self, show_id: int | str) -> list[dict[str, Any]]:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{self.BASE_URL}/shows/episodes",
                headers=self._headers(),
                params={"id": show_id},
            )
            if response.is_error:
                LOGGER.warning(
                    "BetaSeries episodes failed for show %s: status=%s",
                    show_id,
                    response.status_code,
                )
                return []
            return response.json().get("episodes", [])

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
