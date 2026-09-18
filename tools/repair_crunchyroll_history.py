from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from ingestion.crunchyroll_history import history_from_cards
from ingestion.db import StreamingDB
from ingestion.rpa_self_healing import SelfHealingRPA
from ingestion.settings import Settings


def bind_saved_series(db: StreamingDB, cards: list[dict]) -> None:
    """Resolve localized titles using stable series IDs and verified episode links."""
    groups = {}
    for item in cards:
        if item.get("series_source_key"):
            groups.setdefault(item["series_source_key"], []).append(item)
    with db.connect() as conn:
        for key, items in groups.items():
            candidates = {}
            for item in items:
                relative_url = urlsplit(item["episode_url"]).path
                for row in conn.execute(
                    """SELECT DISTINCT s.id, s.betaseries_id FROM series s
                       LEFT JOIN history h ON h.serie_id=s.id
                       LEFT JOIN series_aliases a ON a.serie_id=s.id
                       WHERE s.plateforme='crunchyroll'
                       AND (s.titre=? OR a.titre=? OR h.episode_url IN (?, ?))""",
                    (
                        item["serie_title"],
                        item["serie_title"],
                        item["episode_url"],
                        relative_url,
                    ),
                ):
                    candidates[row["id"]] = row["betaseries_id"]
            known = conn.execute(
                "SELECT serie_id FROM series_sources WHERE source_key=? AND plateforme='crunchyroll'",
                (key,),
            ).fetchone()
            enriched = [sid for sid, beta_id in candidates.items() if beta_id]
            target = (
                enriched[0]
                if len(enriched) == 1
                else (
                    known["serie_id"]
                    if known
                    else next(iter(candidates)) if len(candidates) == 1 else None
                )
            )
            if target is None:
                continue
            conn.execute(
                """INSERT INTO series_sources VALUES(?, 'crunchyroll', ?)
                         ON CONFLICT(source_key, plateforme) DO UPDATE SET serie_id=excluded.serie_id""",
                (key, target),
            )
            for item in items:
                conn.execute(
                    """INSERT INTO series_aliases VALUES(?, 'crunchyroll', ?)
                       ON CONFLICT(titre, plateforme) DO UPDATE SET serie_id=excluded.serie_id""",
                    (item["serie_title"], target),
                )
                # Only the exact episode link from the saved history card is evidence.
                conn.execute(
                    """UPDATE OR IGNORE history SET serie_id=?
                       WHERE plateforme_source='crunchyroll' AND episode_url IN (?, ?)""",
                    (target, item["episode_url"], urlsplit(item["episode_url"]).path),
                )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore Crunchyroll history from saved HTML; no external sync"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Back up SQLite and import the verified cards",
    )
    parser.add_argument(
        "--snapshots-dir", type=Path, default=Path("artifacts/rpa/crunchyroll")
    )
    args = parser.parse_args()
    settings = Settings.from_env()
    files = sorted(args.snapshots_dir.glob("*.html"))
    if not files:
        raise SystemExit("No saved Crunchyroll HTML snapshots found")
    cards = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(java_script_enabled=False)
            context.route("**/*", lambda route: route.abort())
            page = context.new_page()
            for path in files:
                page.set_content(
                    path.read_text(encoding="utf-8"), wait_until="domcontentloaded"
                )
                for item in history_from_cards(
                    SelfHealingRPA._collect_history_rows(
                        page, ".history-body [class^='history-playable-card--']"
                    )
                ):
                    cards[(item["episode_url"], item["watched_at"])] = item
        finally:
            browser.close()
    print(
        f"Verified history events: {len(cards)}; series in saved snapshots: {len({item['serie_title'] for item in cards.values()})}"
    )
    if not args.apply:
        print(
            "Preview only. Use --apply to import; no streaming-platform or BetaSeries API is called."
        )
        return
    backup = (
        settings.db_path.parent
        / "backups"
        / f"streaming-before-history-repair-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.db_path) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    db = StreamingDB(settings.db_path)
    db.init_schema()
    bind_saved_series(db, list(cards.values()))
    for item in cards.values():
        db.insert_history_item(item)
    print(
        f"Local repair complete. Backup: {backup}. No external synchronization performed."
    )


if __name__ == "__main__":
    main()
