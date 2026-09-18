from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.settings import Settings


def main() -> None:
    settings = Settings.from_env()
    conn = sqlite3.connect(settings.db_path)
    queries = {
        "series_with_poster": "SELECT COUNT(*) FROM series WHERE poster_url IS NOT NULL",
        "series_with_synopsis": "SELECT COUNT(*) FROM series WHERE synopsis IS NOT NULL",
        "calendar_with_episode_url": "SELECT COUNT(*) FROM calendar WHERE episode_url IS NOT NULL",
        "history_with_episode_url": "SELECT COUNT(*) FROM history WHERE episode_url IS NOT NULL",
        "history_synced": "SELECT COUNT(*) FROM history WHERE sync_status = 'synced'",
        "history_matched": "SELECT COUNT(*) FROM history WHERE sync_status = 'matched'",
        "history_unmatched": "SELECT COUNT(*) FROM history WHERE sync_status = 'unmatched'",
        "series_with_imdb": "SELECT COUNT(*) FROM series WHERE imdb_url IS NOT NULL",
        "series_missing_betaseries": "SELECT COUNT(*) FROM series WHERE betaseries_id IS NULL",
    }
    print({name: conn.execute(query).fetchone()[0] for name, query in queries.items()})


if __name__ == "__main__":
    main()
