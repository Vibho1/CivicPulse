#!/usr/bin/env python3
"""Seed the local database with the Bengaluru demo scenario.

Usage (from backend/):  python -m scripts.seed_demo [--keep]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.demo import seed_demo  # noqa: E402
from app.store import Store  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="Keep existing data instead of resetting")
    args = ap.parse_args()
    s = get_settings()
    store = Store(s.db_path)
    summary = seed_demo(store, s.uploads_path, reset=not args.keep)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
