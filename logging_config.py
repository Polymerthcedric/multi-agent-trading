from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from config.settings import Settings


def setup_logging(settings: Settings) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")

    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    if not any(isinstance(h, (logging.FileHandler, RotatingFileHandler)) for h in root_logger.handlers):
        file_handler = RotatingFileHandler(
            settings.log_file, mode="a", encoding="utf-8",
            maxBytes=10 * 1024 * 1024, backupCount=5,
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    logging.getLogger(__name__).info("Logging initialized to %s", settings.log_file)
