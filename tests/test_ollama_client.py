import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import httpx

from ingestion.ollama_client import OllamaClient
from ingestion.rpa_self_healing import SelfHealingRPA, PlatformConfig
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


class OllamaClientTests(unittest.TestCase):
    def test_streaming_content_and_budget(self):
        response = httpx.Response(
            200,
            text="\n".join(
                [
                    json.dumps({"message": {"content": '{"selector":'}, "done": False}),
                    json.dumps({"message": {"content": '"body"}'}, "done": False}),
                    json.dumps(
                        {
                            "message": {"content": ""},
                            "done": True,
                            "done_reason": "stop",
                        }
                    ),
                ]
            ),
        )
        schema = {"type": "object"}
        with patch("ingestion.ollama_client.httpx.Client") as factory:
            client = factory.return_value.__enter__.return_value
            client.stream.return_value.__enter__.return_value = response
            result = OllamaClient("http://localhost:11434", "test").json_chat(
                prompt="test", schema=schema, max_tokens=768
            )
            self.assertEqual(result, {"selector": "body"})
            body = client.stream.call_args.kwargs["json"]
            self.assertEqual(body["options"]["num_ctx"], 32768)
            self.assertEqual(body["options"]["num_predict"], 768)
            self.assertEqual(body["format"], schema)
            self.assertTrue(body["stream"])

    def test_truncated_output_is_rejected(self):
        response = httpx.Response(
            200,
            json={
                "message": {"content": '{"items":'},
                "done": True,
                "done_reason": "length",
            },
        )
        with patch("ingestion.ollama_client.httpx.Client") as factory:
            factory.return_value.__enter__.return_value.stream.return_value.__enter__.return_value = (
                response
            )
            with self.assertRaisesRegex(ValueError, "truncated"):
                OllamaClient("http://localhost:11434", "test").chat(prompt="test")

    def test_scripts_are_removed_before_dom_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.html"
            path.write_text(
                '<script type="text/template">'
                + "x" * 30000
                + '</script><style>secret</style><main data-testid="activity-history-items">History</main>',
                encoding="utf-8",
            )
            dom = SelfHealingRPA._compact_dom(path, max_chars=500)
            self.assertIn("activity-history-items", dom)
            self.assertNotIn("secret", dom)
            self.assertNotIn("<script", dom)

    def test_extraction_keeps_all_batches_and_unknown_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.html"
            path.write_text("<main>History</main>", encoding="utf-8")
            with patch.object(
                OllamaClient,
                "json_chat",
                side_effect=[
                    {"items": [{"serie_title": "A"}]},
                    {"items": [{"serie_title": "B"}]},
                    {"items": [{"serie_title": "C"}]},
                ],
            ) as chat:
                rpa = SelfHealingRPA(
                    db=None,
                    ollama=OllamaClient("http://localhost:11434", "test"),
                    user_data_dir=Path(folder),
                )
                result = rpa._extract_history_with_vision(
                    config=PlatformConfig("prime_video", "", {}),
                    screenshot_path=path.with_suffix(".png"),
                    dom_path=path,
                    rows_text=[f"A B C row {i}" for i in range(21)],
                    container_hint="main",
                    extension_candidates=[],
                )
            self.assertEqual(chat.call_count, 3)
            self.assertEqual([item["serie_title"] for item in result], ["A", "B", "C"])
            self.assertTrue(all(item["episode"] is None for item in result))
            self.assertTrue(
                all(call.kwargs["image_paths"] == [] for call in chat.call_args_list)
            )

    def test_disney_titles_use_accessible_evidence_without_franchise_shortening(self):
        row = json.dumps(
            {"title": "Star Wars : The Clone Wars", "text": "", "labels": []}
        )
        self.assertTrue(
            SelfHealingRPA._title_matches_row("Star Wars: The Clone Wars", row)
        )
        self.assertFalse(SelfHealingRPA._title_matches_row("Star Wars", row))
        row = json.dumps({"text": "", "labels": ["L’Épisode inédit"]})
        self.assertTrue(SelfHealingRPA._title_matches_row("L'Episode inedit", row))

    def test_unverified_title_does_not_drop_verified_items(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.html"
            path.write_text("<main>History</main>", encoding="utf-8")
            row = json.dumps(
                {
                    "title": "Star Wars Resistance",
                    "text": "",
                    "labels": ["Épisode suivant"],
                    "episode_url": "https://www.disneyplus.com/fr-fr/play/example",
                },
                ensure_ascii=False,
            )
            with patch.object(
                OllamaClient,
                "json_chat",
                return_value={
                    "items": [
                        {"serie_title": "Star Wars"},
                        {"serie_title": ""},
                        None,
                        {"serie_title": "Star Wars Resistance", "episode": 6},
                    ]
                },
            ):
                rpa = SelfHealingRPA(
                    db=None,
                    ollama=OllamaClient("http://localhost:11434", "test"),
                    user_data_dir=Path(folder),
                )
                result = rpa._extract_history_with_vision(
                    config=PlatformConfig("disney_plus", "", {}),
                    screenshot_path=path.with_suffix(".png"),
                    dom_path=path,
                    rows_text=[row],
                    container_hint="main",
                    extension_candidates=[],
                )
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["serie_title"], "Star Wars Resistance")
            self.assertEqual(
                result[0]["episode_url"],
                "https://www.disneyplus.com/fr-fr/play/example",
            )
            self.assertIsNone(result[0]["episode"])

    def test_screenshot_timeout_keeps_dom_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            page = MagicMock()
            page.content.return_value = "<main>History</main>"
            page.screenshot.side_effect = PlaywrightTimeoutError("fonts timeout")
            rpa = SelfHealingRPA(
                db=None,
                ollama=None,
                user_data_dir=Path(folder),
                artifacts_dir=Path(folder),
            )
            screenshot, dom = rpa._capture_state(page, "canal_plus", "extract")
            self.assertEqual(dom.read_text(encoding="utf-8"), "<main>History</main>")
            self.assertFalse(screenshot.exists())

    def test_crunchyroll_metadata_comes_from_card_not_model_guesses(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "page.html"
            path.write_text("<div class='history-body'></div>", encoding="utf-8")
            row = json.dumps(
                {
                    "title": "The Outcast",
                    "episode_text": "E4 - Episode 4",
                    "date_text": "17/09/2026",
                    "episode_url": "https://www.crunchyroll.com/fr/watch/example",
                }
            )
            with patch.object(
                OllamaClient,
                "json_chat",
                return_value={
                    "items": [
                        {
                            "serie_title": "The Outcast",
                            "episode": 99,
                            "season": 1,
                            "watched_at": "2020-01-01",
                        }
                    ]
                },
            ):
                rpa = SelfHealingRPA(
                    db=None,
                    ollama=OllamaClient("http://localhost:11434", "test"),
                    user_data_dir=Path(folder),
                )
                result = rpa._extract_history_with_vision(
                    config=PlatformConfig("crunchyroll", "", {}),
                    screenshot_path=path.with_suffix(".png"),
                    dom_path=path,
                    rows_text=[row],
                    container_hint=".history-body",
                    extension_candidates=[],
                )
            self.assertEqual(result[0]["episode"], 4)
            self.assertEqual(result[0]["watched_at"], "2026-09-17")
            self.assertIsNone(result[0]["season"])


if __name__ == "__main__":
    unittest.main()
