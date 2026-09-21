from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from ingestion.rpa_self_healing import (
    CDPConnectionError,
    SelfHealingRPA,
    _looks_like_selector,
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

        self.assertIn("Start Windows Chrome", str(raised.exception))

    def test_selector_placeholder_from_ollama_is_rejected(self) -> None:
        self.assertFalse(_looks_like_selector("selerctor"))
        self.assertFalse(_looks_like_selector("selector"))
        self.assertTrue(_looks_like_selector(".retableRow:has(a[href*='/title/'])"))


if __name__ == "__main__":
    unittest.main()
