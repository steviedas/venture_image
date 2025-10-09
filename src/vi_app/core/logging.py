# src/vi_app/core/logging.py
from __future__ import annotations

import logging
import sys


def configure_logging(level: int | str = logging.INFO, json: bool = False) -> None:
    """
    Configure root + uvicorn loggers. Keep it minimal and production-safe.
    """
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())

    handlers = [logging.StreamHandler(sys.stdout)]

    fmt = (
        '{"level":"%(levelname)s","time":"%(asctime)s","name":"%(name)s",'
        '"message":"%(message)s","module":"%(module)s","line":%(lineno)d}'
        if json
        else "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    logging.basicConfig(level=level, handlers=handlers, format=fmt)

    # Uvicorn noisy loggers normalization
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).setLevel(level)


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(name or "vi_app")
