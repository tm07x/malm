#!/usr/bin/env python3
"""Initialize local runtime directories and the unified document store."""

import shutil
from pathlib import Path

from malm.store import DocumentStore

DATA_DIR = Path(__file__).parent.parent / "data"
DEFAULT_RULES = Path(__file__).parent / "rules.json"

DISCOVERY_ROOT = Path.home() / "Documents" / "Legal-Discovery"
UNIFIED_DB = DISCOVERY_ROOT / "unified.db"
SOURCE_DIR = DISCOVERY_ROOT / "source-doc"
MD_DIR = DISCOVERY_ROOT / "MD"
EXPORTS_DIR = DISCOVERY_ROOT / "exports"


def init() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DISCOVERY_ROOT.mkdir(parents=True, exist_ok=True)
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    MD_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    rules_dest = DATA_DIR / "rules.json"
    if not rules_dest.exists():
        shutil.copy(DEFAULT_RULES, rules_dest)
        print(f"Created rules file: {rules_dest}")
    else:
        print(f"Rules already exist: {rules_dest}")

    store = DocumentStore(str(UNIFIED_DB))
    store.close()
    print(f"Unified store ready: {UNIFIED_DB}")
    print(f"Source docs dir: {SOURCE_DIR}")
    print(f"Markdown dir: {MD_DIR}")
    print(f"Exports dir: {EXPORTS_DIR}")


if __name__ == "__main__":
    init()
