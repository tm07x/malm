#!/usr/bin/env python3
"""Initialize the janitor data directory."""
import json
import shutil
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DEFAULT_RULES = Path(__file__).parent / "rules.json"


def init():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    rules_dest = DATA_DIR / "rules.json"
    if not rules_dest.exists():
        shutil.copy(DEFAULT_RULES, rules_dest)
        print(f"Created {rules_dest}")
    else:
        print(f"Rules already exist at {rules_dest}")

    # Trigger schema creation by importing db
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from janitor.db import JanitorDB
    db = JanitorDB(str(DATA_DIR / "janitor.db"))
    db.close()
    print(f"Database ready at {DATA_DIR / 'janitor.db'}")


if __name__ == "__main__":
    init()
