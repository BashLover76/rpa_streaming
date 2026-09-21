from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Iterator

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_DIR = Path("logs")
PLATFORM_LOG_DIR = LOG_DIR / "platforms"


def configure_logging(
    log_type: str,
    *,
    platform: str | None = None,
    level: int = logging.INFO,
    console: bool = True,
) -> None:
    """Configure console, type-level and optional platform-level logs."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PLATFORM_LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT)
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        root.addHandler(console_handler)

    root.addHandler(_file_handler(LOG_DIR / f"{_slug(log_type)}.log", level))
    if platform:
        root.addHandler(_file_handler(_platform_log_path(platform), level))

    logging.getLogger("httpx").setLevel(logging.WARNING)


@contextmanager
def platform_log_context(platform: str, *, level: int = logging.INFO) -> Iterator[None]:
    """Mirror logs emitted in this block to logs/platforms/<platform>.log."""
    root = logging.getLogger()
    path = _platform_log_path(platform)
    if any(
        getattr(handler, "_streaming_log_path", None) == path
        for handler in root.handlers
    ):
        yield
        return

    handler = _file_handler(path, level)
    root.addHandler(handler)
    try:
        yield
    finally:
        root.removeHandler(handler)
        handler.close()


def _file_handler(path: Path, level: int) -> TimedRotatingFileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        path,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        utc=False,
    )
    handler.suffix = "%Y-%m-%d"
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.setLevel(level)
    handler._streaming_log_path = path  # type: ignore[attr-defined]
    return handler


def _platform_log_path(platform: str) -> Path:
    return PLATFORM_LOG_DIR / f"{_slug(platform)}.log"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip().lower())
    return slug.strip("._-") or "script"
