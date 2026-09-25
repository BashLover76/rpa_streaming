from __future__ import annotations

import contextlib
import json
import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class RuntimePlatform:
    system: str
    is_windows: bool
    is_linux: bool
    is_wsl: bool


def detect_runtime_platform() -> RuntimePlatform:
    system = platform.system().lower()
    release = platform.release().lower()
    version = platform.version().lower()
    is_wsl = system == "linux" and (
        "microsoft" in release
        or "microsoft" in version
        or Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists()
    )
    return RuntimePlatform(
        system=system,
        is_windows=system == "windows",
        is_linux=system == "linux",
        is_wsl=is_wsl,
    )


def chrome_cdp_ready(cdp_url: str) -> bool:
    version_url = urljoin(cdp_url.rstrip("/") + "/", "json/version")
    try:
        request = Request(version_url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    return bool(payload.get("webSocketDebuggerUrl"))


def start_chrome_cdp(
    cdp_url: str = "http://127.0.0.1:9222",
    *,
    extension_path: Path | None = None,
) -> None:
    runtime = detect_runtime_platform()
    port = _cdp_port(cdp_url)
    if runtime.is_wsl:
        _start_windows_chrome_from_wsl(port, extension_path)
    elif runtime.is_windows:
        _start_windows_chrome(port, extension_path)
    elif runtime.is_linux:
        _start_linux_chrome(port, extension_path)
    else:
        raise RuntimeError(f"Unsupported OS for Chrome auto-start: {runtime.system}")


def terminate_chrome_processes() -> None:
    runtime = detect_runtime_platform()
    if runtime.is_wsl or runtime.is_windows:
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Stop-Process -Name chrome -Force -ErrorAction SilentlyContinue",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    if runtime.is_linux:
        for process_name in (
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
            "chrome",
        ):
            subprocess.run(
                ["pkill", "-f", process_name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return
    raise RuntimeError(f"Unsupported OS for Chrome restart: {runtime.system}")


def wait_for_chrome_cdp(cdp_url: str, *, timeout_ms: int) -> bool:
    deadline = time.monotonic() + max(5.0, timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if chrome_cdp_ready(cdp_url):
            return True
        time.sleep(0.5)
    return False


def _cdp_port(cdp_url: str) -> int:
    try:
        return int(cdp_url.rstrip("/").rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return 9222


def _start_windows_chrome_from_wsl(port: int, extension_path: Path | None) -> None:
    command = _windows_chrome_start_command(
        port=port,
        extension_path=_windows_extension_path_from_wsl(extension_path),
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _start_windows_chrome(port: int, extension_path: Path | None) -> None:
    resolved_extension = None
    if extension_path:
        resolved = extension_path.expanduser().resolve()
        if resolved.exists():
            resolved_extension = str(resolved)
    command = _windows_chrome_start_command(
        port=port,
        extension_path=resolved_extension,
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _start_linux_chrome(port: int, extension_path: Path | None) -> None:
    executable = (
        shutil.which("google-chrome")
        or shutil.which("google-chrome-stable")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )
    if executable is None:
        raise RuntimeError("Chrome/Chromium executable not found in PATH")
    profile_dir = Path(os.getenv("RPA_LINUX_CHROME_PROFILE", "~/.config/rpa-streaming-chrome")).expanduser()
    profile_dir.mkdir(parents=True, exist_ok=True)
    args = [
        executable,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
    ]
    args.extend(_linux_extension_args(extension_path))
    subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _extension_args(extension_path: Path | None) -> str:
    if not extension_path:
        return ""
    resolved = extension_path.expanduser().resolve()
    if not resolved.exists():
        return ""
    return f" --disable-extensions-except={resolved} --load-extension={resolved}"


def _linux_extension_args(extension_path: Path | None) -> list[str]:
    if not extension_path:
        return []
    resolved = extension_path.expanduser().resolve()
    if not resolved.exists():
        return []
    return [
        f"--disable-extensions-except={resolved}",
        f"--load-extension={resolved}",
    ]


def _windows_chrome_start_command(
    *,
    port: int,
    extension_path: str | None,
) -> str:
    allow_origins = "*"
    args = [
        f"'--remote-debugging-port={port}'",
        f"'--remote-allow-origins={allow_origins}'",
        '"--user-data-dir=$profileDir"',
    ]
    if extension_path:
        safe_extension_path = extension_path.replace("'", "''")
        args.extend(
            [
                f"'--disable-extensions-except={safe_extension_path}'",
                f"'--load-extension={safe_extension_path}'",
            ]
        )
    return (
        "$profileDir = Join-Path $env:LOCALAPPDATA 'Google\\Chrome\\User Data'; "
        f"$chromeArgs = @({', '.join(args)}); "
        "Start-Process chrome.exe -ArgumentList $chromeArgs"
    )


def _windows_extension_path_from_wsl(extension_path: Path | None) -> str | None:
    if not extension_path:
        return None
    resolved = extension_path.expanduser().resolve()
    if not resolved.exists():
        return None
    try:
        completed = subprocess.run(
            ["wslpath", "-w", str(resolved)],
            check=True,
            capture_output=True,
            text=True,
        )
        windows_path = completed.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        windows_path = str(resolved)
    return windows_path


@contextlib.contextmanager
def portable_file_lock(path: Path, *, disabled: bool = False) -> Iterator[None]:
    if disabled:
        yield
        return
    runtime = detect_runtime_platform()
    if runtime.is_windows:
        with _windows_file_lock(path):
            yield
    else:
        with _posix_file_lock(path):
            yield


@contextlib.contextmanager
def _posix_file_lock(path: Path) -> Iterator[None]:
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit(f"Another ingestion run is already active: {path}") from exc
        handle.write(f"{time.time():.0f}\n")
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def _windows_file_lock(path: Path) -> Iterator[None]:
    import msvcrt

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise SystemExit(f"Another ingestion run is already active: {path}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"{time.time():.0f}\n")
        handle.flush()
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
