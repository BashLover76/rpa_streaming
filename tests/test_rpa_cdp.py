from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from ingestion.rpa_self_healing import (
    CDPConnectionError,
    PlatformConfig,
    SelfHealingRPA,
    _cdp_playwright_headers,
    _cdp_request_headers,
    _looks_like_selector,
    _sanitize_storage_state_cookies,
)


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class _ChallengePage:
    def title(self) -> str:
        return "Just a moment..."

    def locator(self, _selector: str) -> "_ChallengePage":
        return self

    def inner_text(self, timeout: int = 0) -> str:
        return "Checking your browser before accessing Crunchyroll."


class CDPPreflightTest(unittest.TestCase):
    def test_preflight_rejects_endpoint_without_websocket_url(self) -> None:
        rpa = SelfHealingRPA(
            db=object(),
            ollama=object(),
            user_data_dir=Path(".playwright-profile"),
            cdp_url="http://127.0.0.1:9222",
        )

        with patch(
            "ingestion.rpa_self_healing.urlopen",
            return_value=_Response(b'{"Browser":"Chrome/140"}'),
        ):
            with self.assertRaises(CDPConnectionError) as raised:
                rpa._preflight_cdp_endpoint()

        self.assertIn("webSocketDebuggerUrl", str(raised.exception))

    def test_preflight_wraps_unreachable_endpoint(self) -> None:
        rpa = SelfHealingRPA(
            db=object(),
            ollama=object(),
            user_data_dir=Path(".playwright-profile"),
            cdp_url="http://127.0.0.1:9222",
        )

        with patch(
            "ingestion.rpa_self_healing.urlopen",
            side_effect=OSError("connection refused"),
        ):
            with self.assertRaises(CDPConnectionError) as raised:
                rpa._preflight_cdp_endpoint()

        self.assertIn("Start Chrome", str(raised.exception))

    def test_selector_placeholder_from_ollama_is_rejected(self) -> None:
        self.assertFalse(_looks_like_selector("selerctor"))
        self.assertFalse(_looks_like_selector("selector"))
        self.assertTrue(_looks_like_selector(".retableRow:has(a[href*='/title/'])"))

    def test_cdp_host_header_formats_match_clients(self) -> None:
        cdp_url = "http://host.docker.internal:9222"

        self.assertEqual(
            _cdp_request_headers(cdp_url),
            {"Host": "127.0.0.1:9222"},
        )
        self.assertEqual(
            _cdp_playwright_headers(cdp_url),
            [{"name": "Host", "value": "127.0.0.1:9222"}],
        )
        self.assertEqual(_cdp_playwright_headers("http://127.0.0.1:9222"), [])

    def test_history_self_healing_rejects_login_selectors(self) -> None:
        rpa = SelfHealingRPA(
            db=object(),
            ollama=object(),
            user_data_dir=Path(".playwright-profile"),
        )
        config = PlatformConfig(
            name="netflix",
            start_url="https://www.netflix.com/viewingactivity",
            selectors={},
            strict_history_scope=True,
        )

        with self.assertRaises(ValueError) as raised:
            rpa._validate_history_selector_candidate(
                page=object(),
                config=config,
                selector_key="history_container",
                selector="input[name='userLoginId']",
            )

        self.assertIn("authentication UI", str(raised.exception))

    def test_storage_state_cookie_sanitizer_removes_chrome_only_fields(self) -> None:
        cookies = _sanitize_storage_state_cookies(
            [
                {
                    "name": "session",
                    "value": "redacted",
                    "domain": ".example.test",
                    "path": "/",
                    "expires": "123",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax",
                    "partitionKey": "https://example.test",
                    "_crHasCrossSiteAncestor": False,
                }
            ]
        )

        self.assertEqual(len(cookies), 1)
        self.assertNotIn("partitionKey", cookies[0])
        self.assertNotIn("_crHasCrossSiteAncestor", cookies[0])
        self.assertEqual(cookies[0]["expires"], 123.0)

    def test_antibot_challenge_is_detected(self) -> None:
        self.assertTrue(
            SelfHealingRPA._page_looks_like_antibot_challenge(_ChallengePage())
        )


if __name__ == "__main__":
    unittest.main()
