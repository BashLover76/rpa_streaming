import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from ingestion.db import StreamingDB
from web_app import create_app, fetch_upcoming_releases


class CalendarViewTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = StreamingDB(Path(folder.name) / "test.db")
        self.db.init_schema()
        self.app = create_app()
        self.app.config["DB_PATH"] = self.db.db_path
        self.client = self.app.test_client()
        self.db.upsert_series(title="No scheduled episode", platform="prime_video")
        self.db.insert_history_item(
            {
                "serie_title": "Anime A",
                "platform": "crunchyroll",
                "season": 1,
                "episode": 2,
                "watched_at": "2030-09-18",
                "status": "watched",
            }
        )
        for title, platform, release in [
            ("Anime A", "crunchyroll", "2030-09-18"),
            ("Netflix B", "netflix", "2030-09-19"),
            ("Disney C", "disney_plus", "2030-09-20"),
            ("Old episode", "crunchyroll", "2030-09-01"),
            ("Next month", "crunchyroll", "2030-10-01"),
        ]:
            self.db.upsert_calendar_episode(
                {
                    "serie_title": title,
                    "platform": platform,
                    "season": 1,
                    "episode": 2,
                    "air_date": release,
                }
            )

    def get_calendar(self, query=""):
        with patch("web_app.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2030, 9, 17, 12)
            return self.client.get("/calendar" + query)

    def test_default_month_keeps_past_and_future_releases(self):
        response = self.get_calendar()
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Septembre 2030", html)
        for title in ("Anime A", "Netflix B", "Disney C"):
            self.assertIn(title, html)
        self.assertIn("Old episode", html)
        self.assertNotIn("Next month", html)
        self.assertIn("4 sorties", html)
        self.assertIn('data-platform="prime_video"', html)
        self.assertIn("watched-mark", html)

    def test_watched_filter_separates_seen_and_unseen_releases(self):
        watched = self.get_calendar("?watched=watched").get_data(as_text=True)
        self.assertIn("Anime A", watched)
        self.assertNotIn("Netflix B", watched)
        unseen = self.get_calendar("?watched=unwatched").get_data(as_text=True)
        self.assertNotIn("Anime A", unseen)
        self.assertIn("Old episode", unseen)

    def test_multiple_platforms_and_preserved_navigation(self):
        html = self.get_calendar("?platform=crunchyroll&platform=netflix").get_data(
            as_text=True
        )
        self.assertIn("Anime A", html)
        self.assertIn("Netflix B", html)
        self.assertNotIn("Disney C", html)
        self.assertIn("month=2030-10", html)
        self.assertIn("platform=crunchyroll", html)
        self.assertIn("platform=netflix", html)
        self.assertIn('data-platform="crunchyroll"', html)

    def test_month_navigation_and_empty_state(self):
        html = self.get_calendar("?month=2030-10").get_data(as_text=True)
        self.assertIn("Next month", html)
        self.assertNotIn("Anime A", html)
        html = self.get_calendar("?month=2030-11").get_data(as_text=True)
        self.assertIn("Aucune sortie connue", html)
        html = self.get_calendar("?month=2030-12").get_data(as_text=True)
        self.assertIn("month=2031-01", html)

    def test_invalid_month_returns_400(self):
        for month in ("bad", "2030-13", "0001-01", "9999-12"):
            self.assertEqual(self.get_calendar("?month=" + month).status_code, 400)

    def test_series_platform_is_used_and_filters_are_parameterized(self):
        with self.db.connect() as conn:
            conn.execute("UPDATE calendar SET plateforme='French broadcaster'")
        with self.app.app_context():
            rows = fetch_upcoming_releases(
                date(2030, 9, 1), date(2030, 9, 17), ["crunchyroll", "netflix"]
            )
            self.assertEqual(
                {row["serie_title"] for row in rows},
                {"Anime A", "Netflix B", "Old episode"},
            )
            self.assertEqual(
                fetch_upcoming_releases(
                    date(2030, 9, 1), date(2030, 9, 17), ["' OR 1=1 --"]
                ),
                [],
            )

    def test_search_is_case_insensitive_and_matches_inside_title(self):
        self.db.upsert_series(
            title="Moi, quand je me réincarne en slime", platform="crunchyroll"
        )
        response = self.client.get("/?q=SLIME")
        self.assertIn(
            "Moi, quand je me réincarne en slime",
            response.get_data(as_text=True),
        )
        suggestions = self.client.get("/api/series/suggest?q=SLIME")
        self.assertEqual(suggestions.status_code, 200)
        self.assertIn(
            "Moi, quand je me réincarne en slime",
            [item["titre"] for item in suggestions.get_json()],
        )


if __name__ == "__main__":
    unittest.main()
