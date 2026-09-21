import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import httpx

from ingestion.db import StreamingDB
from ingestion.catalog_pipeline import CatalogPipeline
from ingestion.title_resolution import (
    IMDbClient,
    TitleResolver,
    Resolution,
    clean_title,
    split_streaming_title,
)


class ResolverTests(unittest.TestCase):
    def test_netflix_titles_keep_colons_and_remove_episode_labels(self):
        self.assertEqual(
            clean_title(
                '08/7/26 BAKI-DOU: The Invincible Samurai: BAKI-DOU: The Invincible Samurai: "The Way" Report a problem'
            ),
            "BAKI-DOU: The Invincible Samurai",
        )
        self.assertEqual(
            clean_title(
                '17/6/26 Tomb Raider: The Legend: Season 2: "No Good Deed" Report a problem'
            ),
            "Tomb Raider: The Legend",
        )
        self.assertEqual(clean_title("Alien: Romulus"), "Alien: Romulus")
        self.assertEqual(
            split_streaming_title(
                '08/7/26 BAKI-DOU: The Invincible Samurai: BAKI-DOU: The Invincible Samurai: "The Way of the Sword" Report a problem'
            ),
            ("BAKI-DOU: The Invincible Samurai", "The Way of the Sword"),
        )

    def test_imdb_ignores_pages_people_and_encodes_slashes(self):
        def reply(request):
            self.assertIn(b"%2F", request.url.raw_path)
            return httpx.Response(
                200,
                json={
                    "d": [
                        {"id": "/emmys/"},
                        {"id": "ttbad", "qid": "movie"},
                        {"id": "tt123", "qid": "tvSeries", "l": "A"},
                    ]
                },
            )

        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            self.assertEqual(IMDbClient(client).search("A/B")[0]["id"], "tt123")

    def test_remakes_are_not_resolved_by_result_order(self):
        imdb = Mock()
        imdb.search.return_value = [
            {"id": "tt1", "l": "A", "qid": "movie", "y": 1980},
            {"id": "tt2", "l": "A", "qid": "movie", "y": 2020},
        ]
        resolver = TitleResolver(imdb)
        self.assertIsNone(resolver.resolve("A", "netflix"))
        self.assertEqual(resolver.resolve("A", "netflix", year=2020).imdb["id"], "tt2")

    def test_platform_disambiguates_only_cross_checked_titles(self):
        first = {"id": "tt1", "l": "Watchmen", "qid": "movie"}
        second = {"id": "tt2", "l": "Watchmen", "qid": "tvSeries"}
        imdb = Mock()
        imdb.search.side_effect = lambda title: (
            [first]
            if title == "tt1"
            else [second] if title == "tt2" else [first, second]
        )
        beta = Mock()
        beta.search_titles.side_effect = lambda title, kind: [
            {"id": 1 if kind == "movie" else 2, "title": "Watchmen"}
        ]
        beta.title_details.side_effect = lambda ident, kind: {
            "id": ident,
            "imdb_id": f"tt{ident}",
            "platforms_svod": [{"name": "Netflix" if ident == 1 else "Max"}],
        }
        resolver = TitleResolver(imdb, beta)
        self.assertEqual(resolver.resolve("Watchmen", "netflix").kind, "movie")
        self.assertEqual(resolver.resolve("Watchmen", "canal_plus").kind, "series")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = StreamingDB(Path(self.folder.name) / "test.db")
        self.db.init_schema()

    def test_raw_history_is_kept_without_classification_or_fake_records(self):
        collector = StreamingDB(self.db.db_path, stage_history=True)
        item = {"serie_title": "A", "platform": "netflix", "content_type": "movie"}
        self.assertTrue(collector.insert_history_item(item))
        self.assertFalse(collector.insert_history_item(item))
        resolver = Mock()
        resolver.resolve.return_value = None
        stats = CatalogPipeline(self.db, resolver).run()
        self.assertEqual(stats["unresolved"], 1)
        with self.db.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM series").fetchone()[0], 0
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM raw_history").fetchone()[0], 1
            )

    def test_known_history_cards_detects_previous_platform_cards(self):
        cards = ["card-a", "card-b"]
        self.db.record_history_cards("netflix", cards)

        self.assertEqual(
            self.db.known_history_cards("netflix", ["card-a", "card-c"]),
            {"card-a"},
        )
        self.assertEqual(
            self.db.known_history_cards("prime_video", ["card-a"]),
            set(),
        )

    def test_service_error_keeps_events_and_does_not_repeat_each_episode(self):
        resolver = Mock()
        resolver.resolve.side_effect = httpx.ConnectError("offline")
        for episode in (1, 2):
            self.db.stage_history_item(
                {"serie_title": "A", "platform": "netflix", "episode": episode}
            )
        pipeline = CatalogPipeline(self.db, resolver)
        self.assertEqual(pipeline.run()["errors"], 2)
        self.assertEqual(resolver.resolve.call_count, 1)
        self.assertEqual(len(pipeline.report()["pending_titles"]), 2)
        resolver.resolve.side_effect = None
        resolver.resolve.return_value = Resolution({"id": "tt1"}, "series")
        self.assertEqual(pipeline.run(retry=True)["resolved"], 2)

    def test_unknown_episode_number_is_retained_for_a_movie(self):
        from ingestion.crunchyroll_history import history_from_cards

        rows = [
            json.dumps(
                {
                    "title": "Film",
                    "episode_url": "/watch/ABC",
                    "date_text": "17/09/2026",
                }
            )
        ]
        result = history_from_cards(rows)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["episode"])
        self.assertEqual(result[0]["watched_at"], "2026-09-17")

    def test_same_work_across_platforms_has_one_record_and_preserves_rewatches(self):
        resolver = Mock()
        resolver.resolve.return_value = Resolution({"id": "tt123", "l": "A"}, "series")
        for platform, date in [
            ("netflix", "2026-01-01"),
            ("prime_video", "2026-01-01"),
            ("netflix", "2026-01-02"),
        ]:
            self.db.stage_history_item(
                {
                    "serie_title": "A",
                    "platform": platform,
                    "season": 1,
                    "episode": 1,
                    "watched_at": date,
                }
            )
        pipeline = CatalogPipeline(self.db, resolver)
        self.assertEqual(pipeline.run()["resolved"], 3)
        self.assertEqual(pipeline.run()["resolved"], 0)
        with self.db.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM series").fetchone()[0], 1
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM history").fetchone()[0], 3
            )

    def test_movie_beta_id_cannot_collide_with_show(self):
        show = self.db.upsert_series(title="Show", betaseries_id=42)
        movie = self.db.upsert_series(title="Film")
        result = Resolution({"id": "tt42"}, "movie", {"id": 42, "title": "Film"})
        CatalogPipeline(self.db, Mock()).enrich(movie, result)
        with self.db.connect() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT betaseries_id FROM series WHERE id=?", (show,)
                ).fetchone()[0],
                42,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT betaseries_movie_id FROM series WHERE id=?", (movie,)
                ).fetchone()[0],
                42,
            )

    def test_merge_preserves_nullable_and_unique_events_and_calendar(self):
        ids = [
            self.db.upsert_series(title=title, platform="netflix")
            for title in ("A", "A Season 1")
        ]
        for ident in ids:
            for date in ("2026-01-01", None):
                self.db.insert_history_item(
                    {
                        "serie_id": ident,
                        "serie_title": "A",
                        "platform": "netflix",
                        "season": 1,
                        "episode": 1,
                        "watched_at": date,
                    }
                )
            with self.db.connect() as conn:
                conn.execute(
                    "INSERT INTO calendar(serie_id,saison,episode,date_diffusion) VALUES (?,1,1,?)",
                    (ident, "2026-01-01"),
                )
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE history SET episode_title='Pilot' WHERE serie_id=?", (ids[1],)
            )
        self.db.merge_series(source_id=ids[1], target_id=ids[0])
        with self.db.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM history").fetchone()[0], 2
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM calendar").fetchone()[0], 1
            )
            self.assertEqual(
                conn.execute("SELECT episode_title FROM history LIMIT 1").fetchone()[0],
                "Pilot",
            )


if __name__ == "__main__":
    unittest.main()
