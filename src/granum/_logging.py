"""Granum's logger. Configured from the active Config, never at import time."""

from __future__ import annotations

import logging

from granum.core.config import get_config

_LOGGER_NAME = "granum"
_configured = False


def get_logger(name: str | None = None) -> logging.Logger:
    global _configured
    logger = logging.getLogger(_LOGGER_NAME if name is None else f"{_LOGGER_NAME}.{name}")
    if not _configured:
        _configured = True
        config = get_config()
        root = logging.getLogger(_LOGGER_NAME)
        root.setLevel(str(config.get("log-level")).upper())
        formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)
        log_file = str(config.get("log-file") or "")
        if log_file:
            handler = logging.FileHandler(log_file)
            handler.setFormatter(formatter)
            root.addHandler(handler)
    return logger
