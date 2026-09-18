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

LINK_RE = re.compile(
    r"link Description: (?P<label>.*?), Value: (?P<href>canalplus\.com/[^\s]+)"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import CANAL+ data extracted from browser AX trees."
    )
    parser.add_argument(
        "path", nargs="?", default="artifacts/canalplus_ax_extract.json"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings.from_env()
    db = StreamingDB(settings.db_path)
    db.init_schema()

    payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
    playlist_items = parse_ax_links(payload.get("playlist", ""))
    recent_items = parse_ax_links(payload.get("recent", "")) + parse_ax_links(
        payload.get("ongoing", "")
    )

    playlist_series = [item for item in playlist_items if "/series/" in item["href"]]
    recent_series = [item for item in recent_items if "/series/" in item["href"]]

    for item in unique_by_title(playlist_series + recent_series):
        db.upsert_series(title=item["title"], platform="canal_plus")

    inserted_history = 0
    for item in unique_by_key(recent_series, key=lambda value: value["href"]):
        db.insert_history_item(
            {
                "serie_title": item["title"],
                "season": item.get("season"),
                "episode": None,
                "watched_at": date.today().isoformat(),
                "platform": "canal_plus",
                "raw_title": item["label"],
                "episode_url": item["href"],
                "confidence": 0.6,
            }
        )
        inserted_history += 1

    print(
        {
            "playlist_series": len(unique_by_title(playlist_series)),
            "recent_series": len(unique_by_title(recent_series)),
            "history_items": inserted_history,
        }
    )


def parse_ax_links(ax_text: str) -> list[dict]:
    items = []
    for match in LINK_RE.finditer(ax_text):
        label = normalize_spaces(match.group("label"))
        href = "https://" + match.group("href")
        title = extract_title(label)
        if not title:
            continue
        items.append(
            {
                "title": title,
                "label": label,
                "href": href,
                "season": extract_season(label),
            }
        )
    return items


def extract_title(label: str) -> str | None:
    title = label.split(",")[0].strip()
    title = re.sub(r"\s+-\s+Saison\s+[0-9]+$", "", title, flags=re.IGNORECASE).strip()
    return title or None


def extract_season(label: str) -> int | None:
    match = re.search(r"Saison\s+([0-9]+)", label, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"Saisons\s+([0-9]+)", label, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def unique_by_title(items: list[dict]) -> list[dict]:
    return unique_by_key(items, key=lambda value: value["title"].casefold())


def unique_by_key(items: list[dict], key) -> list[dict]:
    seen = set()
    output = []
    for item in items:
        item_key = key(item)
        if item_key in seen:
            continue
        seen.add(item_key)
        output.append(item)
    return output


if __name__ == "__main__":
    main()
