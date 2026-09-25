from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ingestion.runtime_platform import (
    chrome_cdp_ready,
    detect_runtime_platform,
    start_chrome_cdp,
)
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

        start_chrome.assert_called_once_with(
            "http://127.0.0.1:9222", extension_path=None
        )

    def test_auto_start_does_not_restart_chrome_without_confirmation(self) -> None:
        with (
            patch("main_ingestion.chrome_cdp_ready", return_value=False),
            patch("main_ingestion.start_chrome_cdp"),
            patch("main_ingestion.wait_for_chrome_cdp", return_value=False),
            patch("main_ingestion.sys.stdin.isatty", return_value=False),
            patch("main_ingestion.terminate_chrome_processes") as terminate_chrome,
        ):
            ensure_chrome_cdp("http://127.0.0.1:9222", timeout_ms=30_000)

        terminate_chrome.assert_not_called()

    def test_force_restart_closes_chrome_and_relaunches_cdp(self) -> None:
        with (
            patch("main_ingestion.chrome_cdp_ready", return_value=False),
            patch("main_ingestion.start_chrome_cdp") as start_chrome,
            patch(
                "main_ingestion.wait_for_chrome_cdp",
                side_effect=[False, True],
            ),
            patch("main_ingestion.terminate_chrome_processes") as terminate_chrome,
            patch("main_ingestion.time.sleep"),
        ):
            ensure_chrome_cdp(
                "http://127.0.0.1:9222",
                timeout_ms=30_000,
                force_restart=True,
            )

        terminate_chrome.assert_called_once_with()
        self.assertEqual(start_chrome.call_count, 2)

    def test_linux_chrome_autostart_loads_extension_when_available(self) -> None:
        extension_path = Path("browser_extension/streaming-rpa-helper")
        runtime = Mock(is_wsl=False, is_windows=False, is_linux=True, system="linux")
        with (
            patch("ingestion.runtime_platform.detect_runtime_platform", return_value=runtime),
            patch("ingestion.runtime_platform.shutil.which", return_value="/usr/bin/google-chrome"),
            patch("ingestion.runtime_platform.subprocess.Popen") as popen,
        ):
            start_chrome_cdp(
                "http://127.0.0.1:9222", extension_path=extension_path
            )

        launch_args = popen.call_args.args[0]
        resolved = str(extension_path.resolve())
        self.assertIn(f"--disable-extensions-except={resolved}", launch_args)
        self.assertIn(f"--load-extension={resolved}", launch_args)

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
