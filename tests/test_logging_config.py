from __future__ import annotations

import logging
import tempfile
import unittest
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from unittest.mock import patch

from ingestion import logging_config
from ingestion.logging_config import configure_logging, platform_log_context


class LoggingConfigTest(unittest.TestCase):
    def test_type_and_platform_logs_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder) / "logs"
            with patch.object(logging_config, "LOG_DIR", log_dir):
                with patch.object(
                    logging_config, "PLATFORM_LOG_DIR", log_dir / "platforms"
                ):
                    try:
                        configure_logging("ingestion", console=False)
                        file_handlers = [
                            handler
                            for handler in logging.getLogger().handlers
                            if isinstance(handler, TimedRotatingFileHandler)
                        ]
                        self.assertEqual(file_handlers[0].when, "MIDNIGHT")
                        self.assertEqual(file_handlers[0].backupCount, 30)

                        logger = logging.getLogger("test.logging")
                        logger.info("global entry")
                        with platform_log_context("netflix"):
                            logger.info("platform entry")
                    finally:
                        for handler in list(logging.getLogger().handlers):
                            logging.getLogger().removeHandler(handler)
                            handler.close()

                    ingestion_log = log_dir / "ingestion.log"
                    platform_log = log_dir / "platforms" / "netflix.log"
                    self.assertIn("global entry", ingestion_log.read_text())
                    self.assertIn("platform entry", ingestion_log.read_text())
                    self.assertIn("platform entry", platform_log.read_text())


if __name__ == "__main__":
    unittest.main()
