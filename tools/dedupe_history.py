from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.db import StreamingDB
from ingestion.settings import Settings


def main() -> None:
    settings = Settings.from_env()
    db = StreamingDB(settings.db_path)
    db.init_schema()
    with db.connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        conn.execute("""
            DELETE FROM history
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY
                                serie_id,
                                COALESCE(saison, -1),
                                COALESCE(episode, -1),
                                COALESCE(date_vu, ''),
                                plateforme_source,
                                COALESCE(raw_title, '')
                            ORDER BY
                                CASE sync_status
                                    WHEN 'synced' THEN 0
                                    WHEN 'matched' THEN 1
                                    WHEN 'unmatched' THEN 2
                                    ELSE 3
                                END,
                                CASE WHEN episode_url IS NOT NULL THEN 0 ELSE 1 END,
                                id ASC
                        ) AS rank
                    FROM history
                )
                WHERE rank > 1
            )
            """)
        after = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    print({"before": before, "after": after, "deleted": before - after})


if __name__ == "__main__":
    main()
