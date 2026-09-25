from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from ingestion.runtime_platform import chrome_cdp_ready, detect_runtime_platform
from main_ingestion import ensure_chrome_cdp


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
            "ingestion.runtime_platform.urlopen",
            return_value=_Response(b'{"Browser":"Chrome/154"}'),
        ):
            self.assertFalse(chrome_cdp_ready("http://127.0.0.1:9222"))

        with patch(
            "ingestion.runtime_platform.urlopen",
            return_value=_Response(
                b'{"Browser":"Chrome/154","webSocketDebuggerUrl":"ws://127.0.0.1"}'
            ),
        ):
            self.assertTrue(chrome_cdp_ready("http://127.0.0.1:9222"))

    def test_auto_start_launches_chrome_when_endpoint_is_down(self) -> None:
        with (
            patch("main_ingestion.chrome_cdp_ready", return_value=False),
            patch("main_ingestion.start_chrome_cdp") as start_chrome,
            patch("main_ingestion.wait_for_chrome_cdp", return_value=True),
        ):
            ensure_chrome_cdp("http://127.0.0.1:9222", timeout_ms=30_000)

        start_chrome.assert_called_once_with("http://127.0.0.1:9222")

    def test_detects_windows_linux_and_wsl(self) -> None:
        with (
            patch("ingestion.runtime_platform.platform.system", return_value="Windows"),
            patch("ingestion.runtime_platform.platform.release", return_value=""),
            patch("ingestion.runtime_platform.platform.version", return_value=""),
            patch("ingestion.runtime_platform.Path.exists", return_value=False),
        ):
            runtime = detect_runtime_platform()
            self.assertTrue(runtime.is_windows)
            self.assertFalse(runtime.is_wsl)

        with (
            patch("ingestion.runtime_platform.platform.system", return_value="Linux"),
            patch("ingestion.runtime_platform.platform.release", return_value="microsoft-standard-WSL2"),
            patch("ingestion.runtime_platform.platform.version", return_value=""),
            patch("ingestion.runtime_platform.Path.exists", return_value=False),
        ):
            self.assertTrue(detect_runtime_platform().is_wsl)


if __name__ == "__main__":
    unittest.main()
