from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from .db import StreamingDB

LOGGER = logging.getLogger(__name__)


class CrunchyrollBackend(Protocol):
    def login(self, email: str, password: str) -> None: ...

    def fetch_watch_history(
        self, *, profile_id: str | None = None, locale: str = "fr-FR"
    ) -> list[dict[str, Any]]: ...

    def fetch_watchlist(
        self, *, profile_id: str | None = None, locale: str = "fr-FR"
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class CrunchyrollCredentials:
    email: str
    password: str
    authorization: str | None = None
    profile_id: str | None = None
    locale: str = "fr-FR"


class CrunchyrollClient:
    """
    Adapter boundary for Crunchyroll.

    Crunchyroll does not provide a stable public API for personal watch history.
    Keep unofficial package usage behind this boundary so the rest of the
    ingestion pipeline remains stable when a wrapper changes its API.
    """

    def __init__(
        self,
        *,
        credentials: CrunchyrollCredentials,
        db: StreamingDB,
        backend: CrunchyrollBackend | None = None,
    ) -> None:
        if not credentials.email:
            raise ValueError("CRUNCHYROLL_EMAIL is required")
        if not credentials.password:
            raise ValueError("CRUNCHYROLL_PASSWORD is required")
        self.credentials = credentials
        self.db = db
        self.backend = backend or self._load_backend()

    def sync_history(self) -> int:
        self.backend.login(self.credentials.email, self.credentials.password)
        items = self.backend.fetch_watch_history(
            profile_id=self.credentials.profile_id,
            locale=self.credentials.locale,
        )

        inserted = 0
        for item in items:
            normalized = self._normalize_history_item(item)
            if normalized:
                self.db.insert_history_item(normalized)
                inserted += 1
        LOGGER.info("Crunchyroll API history synced: %s items", inserted)
        return inserted

    def sync_watchlist(self) -> int:
        self.backend.login(self.credentials.email, self.credentials.password)
        items = self.backend.fetch_watchlist(
            profile_id=self.credentials.profile_id,
            locale=self.credentials.locale,
        )

        inserted = 0
        seen_titles = set()
        for item in items:
            title = (
                item.get("serie_title")
                or item.get("series_title")
                or item.get("show_title")
            )
            if title and title not in seen_titles:
                self.db.upsert_series(title=title, platform="crunchyroll")
                seen_titles.add(title)
                inserted += 1
        LOGGER.info("Crunchyroll API watchlist synced: %s series", inserted)
        return inserted

    def _load_backend(self) -> CrunchyrollBackend:
        return CrunchyrollAPIBackend(authorization=self.credentials.authorization)

    @staticmethod
    def _normalize_history_item(item: dict[str, Any]) -> dict[str, Any] | None:
        title = (
            item.get("serie_title")
            or item.get("series_title")
            or item.get("show_title")
        )
        if not title:
            return None
        return {
            "serie_title": title,
            "season": item.get("season") or item.get("season_number"),
            "episode": item.get("episode") or item.get("episode_number"),
            "watched_at": item.get("watched_at") or item.get("date_vu"),
            "platform": "crunchyroll",
            "raw_title": item.get("raw_title") or item.get("title"),
            "confidence": item.get("confidence", 1.0),
        }


class CrunchyrollAPIBackend:
    def __init__(self, authorization: str | None = None) -> None:
        self._client = None
        self._started = False
        self.authorization = authorization

    def login(self, email: str, password: str) -> None:
        if self._started:
            return

        try:
            from CrunchyrollAPI import CrunchyrollAPI, CrunchyrollSettings
        except ImportError as exc:
            raise RuntimeError(
                "CrunchyrollAPI is not installed. Run: pip install -r requirements.txt"
            ) from exc

        if self.authorization:
            CrunchyrollAPI.AUTHORIZATION = self.authorization

        class Settings(CrunchyrollSettings):
            name = "rpa-streaming"
            crunchyroll_username = email
            crunchyroll_password = password
            subtitle = "fr-FR"
            subtitle_fallback = "en-US"
            profile_path = ".crunchyroll-api"
            session_restart = False

        self._client = CrunchyrollAPI(Settings())
        try:
            self._client.start()
        except Exception as exc:
            raise RuntimeError(
                "Crunchyroll API login failed. The unofficial wrapper's built-in "
                "client is likely inactive. Set CRUNCHYROLL_AUTHORIZATION to a "
                "valid 'Basic ...' client header extracted from your Crunchyroll "
                "web session or extension."
            ) from exc
        self._started = True

    def fetch_watch_history(
        self, *, profile_id: str | None = None, locale: str = "fr-FR"
    ) -> list[dict[str, Any]]:
        del profile_id
        self._set_locale(locale)
        episodes = self._client.get_episodes_by_history()
        return [self._episode_to_dict(item, watched=True) for item in episodes]

    def fetch_watchlist(
        self, *, profile_id: str | None = None, locale: str = "fr-FR"
    ) -> list[dict[str, Any]]:
        del profile_id
        self._set_locale(locale)
        items = self._client.get_episodes_by_playlist()
        return [self._episode_to_dict(item, watched=False) for item in items]

    def _set_locale(self, locale: str) -> None:
        if self._client is not None:
            self._client.accountSetting.subtitle = locale or "fr-FR"

    @staticmethod
    def _episode_to_dict(item: Any, *, watched: bool) -> dict[str, Any]:
        return {
            "serie_title": getattr(item, "series_title", None)
            or getattr(item, "season_title", None)
            or getattr(item, "title", None),
            "season": getattr(item, "season", None),
            "episode": getattr(item, "episode_number", None)
            or getattr(item, "episode", None),
            "watched_at": date.today().isoformat() if watched else None,
            "platform": "crunchyroll",
            "raw_title": getattr(item, "long_title", None)
            or getattr(item, "title", None),
            "confidence": 0.9,
        }
