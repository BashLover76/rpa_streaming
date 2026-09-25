from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from main_ingestion import _chrome_cdp_ready, ensure_chrome_cdp


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class ChromeCDPStartupTests(unittest.TestCase):
    def test_ready_endpoint_requires_websocket_url(self) -> None:
        with patch(
            "main_ingestion.urlopen",
            return_value=_Response(b'{"Browser":"Chrome/154"}'),
        ):
            self.assertFalse(_chrome_cdp_ready("http://127.0.0.1:9222"))

        with patch(
            "main_ingestion.urlopen",
            return_value=_Response(
                b'{"Browser":"Chrome/154","webSocketDebuggerUrl":"ws://127.0.0.1"}'
            ),
        ):
            self.assertTrue(_chrome_cdp_ready("http://127.0.0.1:9222"))

    def test_auto_start_launches_chrome_when_endpoint_is_down(self) -> None:
        states = iter([False, True])
        subprocess_run = Mock()

        with (
            patch("main_ingestion._chrome_cdp_ready", side_effect=lambda _url: next(states)),
            patch("main_ingestion.subprocess.run", subprocess_run),
            patch("main_ingestion.time.sleep"),
        ):
            ensure_chrome_cdp("http://127.0.0.1:9222", timeout_ms=30_000)

        subprocess_run.assert_called_once()
        command = subprocess_run.call_args.args[0]
        self.assertEqual(command[:3], ["powershell.exe", "-NoProfile", "-Command"])
        self.assertIn("--remote-debugging-port=9222", command[3])


if __name__ == "__main__":
    unittest.main()
