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

LINK_RE = re.compile(r"link Description: (?P<label>.*?), Value: (?P<href>[^\s]+)")
DATE_RE = re.compile(r"\b([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})\b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import Netflix, Prime Video and Disney+ browser extracts."
    )
    parser.add_argument("--netflix", default="artifacts/netflix_ax_extract.json")
    parser.add_argument("--prime", default="artifacts/primevideo_ax_extract.json")
    parser.add_argument("--disney", default="artifacts/disneyplus_extract.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings.from_env()
    db = StreamingDB(settings.db_path)
    db.init_schema()

    stats = {}
    stats["netflix_history"] = import_netflix(db, Path(args.netflix))
    stats["prime_video_history"] = import_prime(db, Path(args.prime))
    disney_stats = import_disney(db, Path(args.disney))
    stats.update(disney_stats)
    print(stats)


def import_netflix(db: StreamingDB, path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = payload.get("activity", "")
    count = 0
    current_date = None
    for line in text.splitlines():
        date_match = DATE_RE.search(line)
        if date_match:
            current_date = normalize_short_date(date_match.group(1))
            continue
        match = LINK_RE.search(line)
        if not match:
            continue
        label = match.group("label")
        href = match.group("href")
        if "netflix.com/title/" not in href:
            continue
        title = label.split(":", 1)[0].strip()
        if not title or title in {"Report a problem"}:
            continue
        db.insert_history_item(
            {
                "serie_title": title,
                "season": extract_season(label),
                "episode": None,
                "watched_at": current_date,
                "platform": "netflix",
                "raw_title": label,
                "episode_url": href,
                "confidence": 0.75,
            }
        )
        count += 1
    return count


def import_prime(db: StreamingDB, path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = payload.get("history", "")
    count = 0
    current_date = None
    seen = set()
    for line in text.splitlines():
        if "heading" in line and re.search(r"[0-9]{4}", line):
            current_date = normalize_french_date(line)
            continue
        match = LINK_RE.search(line)
        if not match:
            continue
        label = match.group("label")
        href = match.group("href")
        if "primevideo.com/detail/" not in href or label in seen:
            continue
        seen.add(label)
        title = clean_season_suffix(label)
        db.insert_history_item(
            {
                "serie_title": title,
                "season": extract_season(label),
                "episode": None,
                "watched_at": current_date,
                "platform": "prime_video",
                "raw_title": label,
                "episode_url": href,
                "confidence": 0.7,
            }
        )
        db.upsert_series(title=title, platform="prime_video")
        count += 1
    return count


def import_disney(db: StreamingDB, path: Path) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    history_count = 0
    watchlist_count = 0

    for item in payload.get("dom", []):
        label = item.get("aria") or item.get("text") or ""
        href = item.get("href", "")
        if not href or "/browse/entity" not in href:
            continue
        title = clean_disney_title(label)
        if not title:
            continue
        if any(
            marker in label
            for marker in ["Il reste", "Épisode suivant", "S1:E", "S2:E", "S3:E"]
        ):
            db.insert_history_item(
                {
                    "serie_title": title,
                    "season": extract_disney_season(label),
                    "episode": extract_disney_episode(label),
                    "watched_at": date.today().isoformat(),
                    "platform": "disney_plus",
                    "raw_title": label,
                    "episode_url": href,
                    "confidence": 0.65,
                }
            )
            history_count += 1

    seen_watchlist = set()
    for item in payload.get("watchlist_dom", []):
        label = item.get("aria") or item.get("text") or ""
        href = item.get("href", "")
        if not href or "/browse/entity" not in href:
            continue
        title = clean_disney_title(label)
        if not title or title.casefold() in seen_watchlist:
            continue
        seen_watchlist.add(title.casefold())
        db.upsert_series(title=title, platform="disney_plus")
        watchlist_count += 1

    return {
        "disney_plus_history": history_count,
        "disney_plus_watchlist": watchlist_count,
    }


def clean_season_suffix(label: str) -> str:
    return re.sub(
        r"\s+-\s+(Season|Saison)\s+[0-9]+.*$", "", label, flags=re.IGNORECASE
    ).strip()


def clean_disney_title(label: str) -> str | None:
    value = label.split(" Sélectionnez cette option", 1)[0]
    value = re.sub(r"^(Il reste\s+[^A-ZÀ-Ý]+)", "", value)
    value = re.sub(r"^Épisode suivant\s+", "", value)
    value = re.sub(r"^(min)+", "", value)
    value = re.sub(
        r"\s+(Classé|Sortie|Hulu Original|Disney\+ Original|ADN|S[0-9]+:E[0-9]+).*$",
        "",
        value,
    )
    value = re.sub(r"S[0-9]+:E[0-9]+.*$", "", value)
    value = re.sub(r"[0-9]{4}•.*$", "", value)
    value = re.sub(r"\s+(Il reste|Épisode suivant).*$", "", value)
    value = value.strip()
    return value or None


def extract_season(label: str) -> int | None:
    match = re.search(r"(?:Season|Saison)\s+([0-9]+)", label, re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_disney_season(label: str) -> int | None:
    match = re.search(r"S([0-9]+):E[0-9]+", label)
    return int(match.group(1)) if match else None


def extract_disney_episode(label: str) -> int | None:
    match = re.search(r"S[0-9]+:E([0-9]+)", label)
    return int(match.group(1)) if match else None


def normalize_short_date(value: str) -> str:
    day, month, year = value.split("/")
    year_int = int(year)
    if year_int < 100:
        year_int += 2000
    return f"{year_int:04d}-{int(month):02d}-{int(day):02d}"


def normalize_french_date(line: str) -> str | None:
    months = {
        "janvier": 1,
        "février": 2,
        "mars": 3,
        "avril": 4,
        "mai": 5,
        "juin": 6,
        "juillet": 7,
        "août": 8,
        "septembre": 9,
        "octobre": 10,
        "novembre": 11,
        "décembre": 12,
    }
    match = re.search(r"([0-9]{1,2})\s+([A-Za-zéûîôàèùç]+)\s+([0-9]{4})", line)
    if not match:
        return None
    month = months.get(match.group(2).lower())
    if not month:
        return None
    return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(1)):02d}"


if __name__ == "__main__":
    main()
