from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.db import StreamingDB
from ingestion.settings import Settings

EPISODE_RE = re.compile(r"(?:Épisode|Episode)\s+([0-9]+)", re.IGNORECASE)
SHORT_EPISODE_RE = re.compile(r"\bE([0-9]+)\b", re.IGNORECASE)
SEASON_RE = re.compile(r"Saison\s+([0-9]+)", re.IGNORECASE)
FRENCH_DATE_RE = re.compile(r"\b([0-9]{2})/([0-9]{2})/([0-9]{4})\b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import Crunchyroll data extracted from a logged-in browser page."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="artifacts/crunchyroll_browser_extract.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings.from_env()
    db = StreamingDB(settings.db_path)
    db.init_schema()

    payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
    watchlist_titles = unique_titles(payload.get("watchlist", []))
    history_titles = unique_titles(payload.get("history_series", []))
    history_items = build_history_items(
        payload.get("history_watches", []), payload.get("history_series", [])
    )
    history_items.extend(build_series_page_history(payload.get("series_pages", [])))

    for title in watchlist_titles | history_titles:
        db.upsert_series(title=title, platform="crunchyroll")

    inserted_history = 0
    for item in history_items:
        db.insert_history_item(item)
        inserted_history += 1

    print(
        {
            "watchlist_series": len(watchlist_titles),
            "history_series": len(history_titles),
            "history_items": inserted_history,
        }
    )


def unique_titles(items: list[dict]) -> set[str]:
    return {
        item["title"].strip()
        for item in items
        if isinstance(item, dict) and item.get("title", "").strip()
    }


def build_history_items(watches: list[dict], series: list[dict]) -> list[dict]:
    series_by_href_prefix = {
        item["href"].rsplit("/", 1)[0]: item["title"].strip()
        for item in series
        if item.get("href") and item.get("title")
    }
    titles = [item["title"].strip() for item in series if item.get("title")]
    fallback_title = titles[0] if titles else "Crunchyroll Unknown"

    items = []
    seen_watch_urls = set()
    current_title = fallback_title
    title_iter = iter(titles)

    for watch in watches:
        label = watch.get("label", "")
        href = watch.get("href", "")
        if not href or href in seen_watch_urls:
            continue
        seen_watch_urls.add(href)

        title_from_label = extract_title_from_label(label)
        if title_from_label:
            current_title = title_from_label
        elif "E" in label:
            current_title = current_title or fallback_title
        else:
            current_title = next(title_iter, current_title)

        episode = extract_episode(label)
        items.append(
            {
                "serie_title": current_title or fallback_title,
                "season": None,
                "episode": episode,
                "watched_at": date.today().isoformat(),
                "platform": "crunchyroll",
                "raw_title": label,
                "episode_url": href,
                "confidence": 0.65 if episode else 0.5,
            }
        )

    return items


def extract_title_from_label(label: str) -> str | None:
    match = re.search(
        r"(?:Épisode|Episode)\s+[0-9]+\s+(?:de|of)\s+(.+)$",
        label,
        re.IGNORECASE,
    )
    if match and not label.startswith("E"):
        return match.group(1).strip()
    return None


def extract_episode(label: str) -> int | None:
    for pattern in (EPISODE_RE, SHORT_EPISODE_RE):
        match = pattern.search(label)
        if match:
            return int(match.group(1))
    return None


def build_series_page_history(pages: list[dict]) -> list[dict]:
    items: list[dict] = []
    for page in pages:
        title = page.get("title") or page.get("serie_title")
        text = page.get("text") or ""
        if not title or not text:
            continue
        season = extract_page_season(text)
        for episode in extract_seen_page_episodes(text):
            items.append(
                {
                    "serie_title": title,
                    "season": season,
                    "episode": episode["episode"],
                    "watched_at": episode.get("date"),
                    "platform": "crunchyroll",
                    "raw_title": episode["raw_title"],
                    "episode_title": episode.get("episode_title"),
                    "episode_url": episode.get("episode_url"),
                    "status": "watched",
                    "confidence": 0.9 if season else 0.75,
                }
            )
    return items


def extract_page_season(text: str) -> int | None:
    match = SEASON_RE.search(text)
    return int(match.group(1)) if match else None


def extract_seen_page_episodes(text: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    items = []
    for index, line in enumerate(lines):
        if line != "Vu":
            continue
        window = lines[index : index + 8]
        episode_line = next(
            (value for value in window if re.match(r"E[0-9]+\s+-", value)), None
        )
        if not episode_line:
            continue
        episode = extract_episode(episode_line)
        date_value = next(
            (
                normalize_french_numeric_date(value)
                for value in window
                if FRENCH_DATE_RE.search(value)
            ),
            None,
        )
        title = episode_line.split("-", 1)[1].strip() if "-" in episode_line else None
        items.append(
            {
                "episode": episode,
                "episode_title": title,
                "date": date_value,
                "raw_title": " / ".join(window[:5]),
            }
        )
    return [item for item in items if item.get("episode") is not None]


def normalize_french_numeric_date(value: str) -> str | None:
    match = FRENCH_DATE_RE.search(value)
    if not match:
        return None
    day, month, year = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


if __name__ == "__main__":
    main()
