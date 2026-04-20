# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

One unified document system with two ingest paths:

1. **Filesystem ingest** — scans and classifies files using JSON rules.
2. **PST/legal discovery ingest** — extracts Outlook PST email into searchable documents.

Both flows write into the same `DocumentStore` (`unified.db`), which powers web search and evidence export.

## Commands

```bash
# Setup
uv sync
uv run python scripts/init-db.py   # creates runtime dirs + unified.db + data/rules.json

# Run tests
uv run pytest
uv run pytest tests/test_store.py tests/test_extract.py
uv run pytest tests/test_ingest_filesystem.py tests/test_ingest_pst.py

# Run discovery web UI
uv run uvicorn malm.web.app:app --reload --port 8899

# Extract PST (first run builds cache from large PST files, later runs are faster)
uv run python -c "
from malm.pst_extract import extract_pst
print(extract_pst(folder_filter='Innboks', limit=100))
"

# Search the unified DB
uv run python -c "
from malm.pst_extract import search_discovery
for r in search_discovery('konkurs', limit=10):
    print(f'{r[\"uuid\"]} | {(r.get(\"title\") or \"\")[:60]}')
"

# Export evidence package
uv run python -c "
from malm.export import export_from_search
print(export_from_search('konkurs', package_name='konkurs_evidence'))
"
```

## Architecture

### Unified document pipeline

**Pipeline:** source ingest → text extraction → index in `unified.db` → search/export

**Core modules** (`src/malm/`):
- `models.py` — `Document` dataclass for emails/files/attachments.
- `store.py` — `DocumentStore` (SQLite + FTS5 + optional sqlite-vec).
- `ingest/filesystem.py` — filesystem ingest and rules-based routing metadata.
- `ingest/pst.py` — PST/EML ingest on top of `DocumentStore`.
- `extract/text.py` — file text extraction (xlsx/pdf/docx/csv/xml/json/txt).
- `extract/email_parser.py` — robust EML parsing and header decoding.
- `extract/hasher.py` — SHA-256 provenance hashing.
- `rules.py` — rules loading and matching.
- `export.py` — CSV + ZIP evidence export for unified documents.
- `pst_extract.py` — compatibility wrapper around PST extraction/search flows.

**Web UI** (`src/malm/web/`):
- `app.py` — FastAPI + Jinja2 + htmx. Routes: dashboard, search, doc detail, folder, timeline, thread, attachment, export.
- `templates/` — dark-themed responsive UI with live search updates.

**Runtime output** (`~/Documents/Legal-Discovery/`, not in repo):
- `source-doc/` — copied EML files and extracted attachments
- `MD/` — parsed markdown
- `unified.db` — unified SQLite index
- `.eml-cache/` — cached `readpst` output
- `exports/` — evidence ZIP packages

**Migration:** `uv run python scripts/migrate-to-unified.py` migrates legacy `discovery.db` (if present) into `unified.db`.

## Key Details

- Python 3.14+, managed with `uv`
- Rules are Norwegian-language legal/financial categories
- `data/` directory is gitignored; `scripts/rules.json` is the version-controlled default
- Locking helper (`lock.py`) uses atomic `O_CREAT | O_EXCL` with stale PID recovery
- PST cache is per-file (SHA-256 hash of absolute PST path) to avoid cross-case contamination
