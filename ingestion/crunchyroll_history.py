from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urljoin


def history_from_cards(rows: list[str]) -> list[dict]:
    """Read platform evidence without inventing seasons or viewing dates."""
    items = []
    for row in rows:
        card = json.loads(row)
        title = card.get("title", "").strip()
        url = card.get("episode_url")
        match = re.search(r"\bE(\d+)\b", card.get("episode_text", ""), re.IGNORECASE)
        if not title or not url or not match:
            continue
        season = re.search(
            r"\bS(\d+)\b|(?:Saison|Season)\s+(\d+)", card.get("text", ""), re.IGNORECASE
        )
        try:
            watched_at = (
                datetime.strptime(card.get("date_text", "").strip(), "%d/%m/%Y")
                .date()
                .isoformat()
            )
        except ValueError:
            watched_at = None
        progress = card.get("progress_percent")
        source = re.search(r"/series/([^/]+)", card.get("series_url") or "")
        items.append(
            {
                "serie_title": title,
                "season": (
                    int(next(value for value in season.groups() if value))
                    if season
                    else None
                ),
                "episode": int(match.group(1)),
                "episode_title": card.get("episode_text", "").split(" - ", 1)[-1],
                "episode_url": urljoin("https://www.crunchyroll.com", url),
                "watched_at": watched_at,
                "progress_percent": progress,
                "status": (
                    "watched"
                    if progress is not None and progress >= 99.5
                    else "in_progress" if progress is not None else "viewed"
                ),
                "platform": "crunchyroll",
                "raw_title": card.get("text") or card.get("episode_text"),
                "confidence": 1.0,
                "series_source_key": source.group(1) if source else None,
            }
        )
    return items
