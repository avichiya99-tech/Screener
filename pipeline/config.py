"""Macro assumptions loaded from config/macro.json (never hardcoded in the engine)."""
from __future__ import annotations

import json
import os

DEFAULT_MACRO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "macro.json")
REQUIRED_KEYS = ("rf", "erp", "terminal_g", "mos_pct", "updated_on")


def load_macro(path: str = DEFAULT_MACRO_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"macro config {path} missing keys: {missing}")
    return data
