"""CLI / library logging helpers."""

from __future__ import annotations

import logging
import sys


def configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=level,
            format="%(levelname)s: %(message)s",
            stream=sys.stderr,
        )
    else:
        logging.getLogger().setLevel(level)
