"""Centralized logging configuration for the platform."""
from __future__ import annotations

import logging
import sys

from app.config import get_settings


def configure_logging() -> None:
    """Configure root logger with a consistent, readable format."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    if root.handlers:
        # Avoid duplicate handlers on reload
        root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
