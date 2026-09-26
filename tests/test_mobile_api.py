import tempfile
import unittest
from pathlib import Path

from ingestion.db import StreamingDB
from web_app import create_app


class MobileApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = StreamingDB(Path(folder.name) / "test.db")
        self.db.init_schema()
        self.series_id = self.db.upsert_series(
            title="Mobile Series",
            platform="crunchyroll",
            episodes_count=12,
            seasons_count=1,
            poster_url="https://example.test/poster.jpg",
        )
        self.db.insert_history_item(
            {
                "serie_title": "Mobile Series",
                "platform": "crunchyroll",
                "season": 1,
                "episode": 1,
                "watched_at": "2030-01-02",
                "episode_url": "https://www.crunchyroll.com/watch/ABC",
            }
        )
        self.db.upsert_calendar_episode(
            {
                "serie_title": "Mobile Series",
                "platform": "crunchyroll",
                "season": 1,
                "episode": 2,
                "air_date": "2030-01-09",
                "episode_url": "https://www.crunchyroll.com/watch/DEF",
            }
        )
        app = create_app()
        app.config["DB_PATH"] = self.db.db_path
        self.client = app.test_client()

    def test_mobile_titles_expose_deep_links(self):
        response = self.client.get("/api/mobile/titles?type=series&q=mobile")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        item = payload["items"][0]
        self.assertEqual(item["title"], "Mobile Series")
        self.assertEqual(item["deep_link_url"], "https://www.crunchyroll.com/watch/ABC")

    def test_mobile_detail_and_calendar_are_json(self):
        detail = self.client.get(f"/api/mobile/titles/{self.series_id}").get_json()
        self.assertEqual(detail["watched_count"], 1)
        self.assertEqual(detail["history"][0]["deep_link_url"], "https://www.crunchyroll.com/watch/ABC")

        calendar = self.client.get("/api/mobile/calendar?month=2030-01").get_json()
        self.assertEqual(calendar["month"], "2030-01")
        self.assertEqual(calendar["episodes"][0]["deep_link_url"], "https://www.crunchyroll.com/watch/DEF")


if __name__ == "__main__":
    unittest.main()
