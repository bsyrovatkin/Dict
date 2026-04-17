"""Thin wrapper around stdlib logging so every module looks the same."""
from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
