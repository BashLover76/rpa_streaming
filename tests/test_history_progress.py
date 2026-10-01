import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ingestion.db import StreamingDB
from ingestion.rpa_self_healing import SelfHealingRPA, PlatformConfig
from web_app import create_app, count_watched_episodes
from tools.repair_crunchyroll_history import bind_saved_series


class HistoryProgressTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = StreamingDB(Path(self.folder.name) / "test.db")
        self.db.init_schema()

    def test_nullable_history_is_idempotent_and_survives_rename(self):
        item = {
            "serie_title": "Original title",
            "platform": "crunchyroll",
            "season": None,
            "episode": 2,
            "watched_at": "2026-09-17",
            "episode_url": "https://example.com/watch/ABC",
        }
        self.db.insert_history_item(item)
        with self.db.connect() as conn:
            series_id = conn.execute("SELECT id FROM series").fetchone()[0]
        self.db.update_series_metadata(series_id, title="Canonical title")
        self.db.insert_history_item(item)
        self.db.insert_history_item(
            {**item, "episode": 3, "episode_url": "https://example.com/watch/DEF"}
        )
        with self.db.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM history").fetchone()[0], 2
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM series").fetchone()[0], 1
            )

    def test_history_update_conflict_is_idempotent(self):
        base_item = {
            "serie_title": "Conflict title",
            "platform": "crunchyroll",
            "season": None,
            "episode": None,
            "watched_at": "2026-10-01",
            "episode_url": "https://example.com/watch/ABC",
        }
        self.db.insert_history_item(base_item)
        self.db.insert_history_item(
            {
                **base_item,
                "season": 1,
                "episode": 1,
                "episode_url": None,
            }
        )

        self.assertFalse(
            self.db.insert_history_item({**base_item, "season": 1, "episode": 1})
        )
        with self.db.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM history").fetchone()[0], 2
            )

    def test_detail_counts_unique_episodes_over_total_not_events_or_limit(self):
        series_id = self.db.upsert_series(
            title="A", platform="crunchyroll", episodes_count=24
        )
        for episode, date in [(1, "2026-09-01"), (1, "2026-09-02"), (2, "2026-09-03")]:
            self.db.insert_history_item(
                {
                    "serie_title": "A",
                    "platform": "crunchyroll",
                    "season": 1,
                    "episode": episode,
                    "watched_at": date,
                }
            )
        app = create_app()
        app.config["DB_PATH"] = self.db.db_path
        html = app.test_client().get(f"/series/{series_id}").get_data(as_text=True)
        self.assertIn("2 sur 24", html)
        self.assertIn("E2", html)
        self.assertEqual(
            count_watched_episodes(
                [{"episode": 1, "saison": 1, "status": "in_progress"}]
            ),
            0,
        )

    def test_detail_count_includes_history_older_than_display_limit(self):
        series_id = self.db.upsert_series(
            title="Long series", platform="crunchyroll", episodes_count=60
        )
        for episode in range(1, 57):
            self.db.insert_history_item(
                {
                    "serie_title": "Long series",
                    "platform": "crunchyroll",
                    "season": 1,
                    "episode": episode,
                    "watched_at": "2026-09-17",
                }
            )
        app = create_app()
        app.config["DB_PATH"] = self.db.db_path
        html = app.test_client().get(f"/series/{series_id}").get_data(as_text=True)
        self.assertIn("56 sur 60", html)

    def test_stable_series_id_survives_localized_titles_and_season_reset(self):
        item = {
            "serie_title": "French title",
            "platform": "crunchyroll",
            "series_source_key": "SERIES1",
            "season": None,
            "episode": 1,
            "watched_at": "2026-09-17",
            "episode_url": "https://example.com/watch/ABC",
        }
        self.db.insert_history_item(item)
        self.db.insert_history_item(
            {
                **item,
                "serie_title": "English title",
                "episode_url": "https://example.com/watch/DEF",
            }
        )
        with self.db.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM series").fetchone()[0], 1
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM history").fetchone()[0], 2
            )

    def test_legacy_episode_without_url_is_not_counted_twice(self):
        history = [
            {"episode": 1, "saison": None, "betaseries_episode_id": 123},
            {"episode": 1, "saison": 1, "episode_url": "https://example.com/watch/ABC"},
        ]
        self.assertEqual(count_watched_episodes(history), 1)
        history.append(
            {"episode": 1, "saison": 2, "episode_url": "https://example.com/watch/DEF"}
        )
        self.assertEqual(count_watched_episodes(history), 3)

    def test_saved_links_restore_history_to_enriched_series(self):
        target = self.db.upsert_series(
            title="French title", platform="crunchyroll", betaseries_id=42
        )
        item = {
            "serie_title": "English title",
            "platform": "crunchyroll",
            "season": None,
            "episode": 1,
            "watched_at": "2026-09-17",
            "episode_url": "https://example.com/watch/ABC",
        }
        self.db.insert_history_item(item)
        self.db.insert_history_item(
            {
                **item,
                "serie_title": "French title",
                "episode_url": "https://example.com/watch/DEF",
            }
        )
        cards = [
            {**item, "series_source_key": "SERIES1"},
            {
                **item,
                "series_source_key": "SERIES1",
                "episode_url": "https://example.com/watch/DEF",
            },
        ]
        bind_saved_series(self.db, cards)
        with self.db.connect() as conn:
            self.assertEqual(
                [
                    row[0]
                    for row in conn.execute("SELECT DISTINCT serie_id FROM history")
                ],
                [target],
            )
        self.db.insert_history_item(
            {**cards[0], "episode": 2, "episode_url": "https://example.com/watch/GHI"}
        )
        with self.db.connect() as conn:
            self.assertEqual(
                [
                    row[0]
                    for row in conn.execute("SELECT DISTINCT serie_id FROM history")
                ],
                [target],
            )

    def test_delete_series_removes_all_local_dependents(self):
        series_id = self.db.upsert_series(title="To remove", platform="netflix")
        self.db.insert_history_item(
            {
                "serie_title": "To remove",
                "platform": "netflix",
                "episode": 1,
                "watched_at": "2026-09-18",
            }
        )
        self.db.upsert_calendar_episode(
            {
                "serie_title": "To remove",
                "platform": "netflix",
                "season": 1,
                "episode": 2,
                "air_date": "2026-09-20",
            }
        )

        counts = self.db.delete_series(series_id)

        self.assertEqual(counts, {"series": 1, "history": 1, "calendar": 1})
        with self.db.connect() as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT id FROM series WHERE id = ?", (series_id,)
                ).fetchone()
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM history WHERE serie_id = ?", (series_id,)
                ).fetchone()[0],
                0,
            )

    def test_virtual_list_collects_cards_across_scrolls(self):
        page = MagicMock()
        page.evaluate.side_effect = [{"top": 0, "height": 100, "viewport": 100}] * 10
        row1 = json.dumps(
            {
                "title": "A",
                "episode_url": "https://example.com/watch/1",
                "date_text": "01/09/2026",
            }
        )
        row2 = json.dumps(
            {
                "title": "B",
                "episode_url": "https://example.com/watch/2",
                "date_text": "02/09/2026",
            }
        )
        rpa = SelfHealingRPA(
            db=None,
            ollama=None,
            user_data_dir=Path(self.folder.name),
            artifacts_dir=Path(self.folder.name),
        )
        with patch.object(
            rpa,
            "_collect_history_rows",
            side_effect=[[row1], [row2], [row2], [row2], [row2]],
        ):
            rows = rpa._collect_all_crunchyroll_history(
                page,
                PlatformConfig("crunchyroll", "", {}, max_scroll_steps=10),
                "selector",
            )
        self.assertEqual(len(rows), 2)

    def test_differential_collects_only_unknown_cards(self):
        page = MagicMock()
        page.locator.return_value.first.evaluate.return_value = False
        page.locator.return_value.first.is_visible.return_value = False
        known = json.dumps(
            {
                "title": "Known",
                "episode_url": "https://example.com/watch/1",
                "date_text": "01/09/2026",
            }
        )
        new = json.dumps(
            {
                "title": "New",
                "episode_url": "https://example.com/watch/2",
                "date_text": "02/09/2026",
            }
        )
        self.db.record_history_cards("netflix", [known])
        rpa = SelfHealingRPA(
            db=self.db,
            ollama=None,
            user_data_dir=Path(self.folder.name),
            artifacts_dir=Path(self.folder.name),
            rpa_mode="differential",
            differential_known_threshold=2,
        )
        with patch.object(
            rpa,
            "_collect_history_rows",
            side_effect=[[new], [known], [known]],
        ):
            rows = rpa._collect_all_history(
                page,
                PlatformConfig("netflix", "", {}, max_scroll_steps=5),
                "selector",
                "container",
            )

        self.assertEqual(rows, [new])


if __name__ == "__main__":
    unittest.main()
