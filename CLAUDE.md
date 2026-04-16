# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Two systems in one repo:

1. **Downloads janitor** — Claude Code plugin that organizes `~/Downloads` by moving files to categorized folders based on JSON rules.
2. **Legal discovery** — PST email extraction, indexing, search, and web UI for litigation review. Extracts emails from Outlook PST files into a structured discovery system with SQLite, FTS5, and a FastAPI web interface.

## Commands

```bash
# Setup
uv sync
uv run python scripts/init-db.py   # creates data/janitor.db + copies default rules

# Run tests
uv run pytest
uv run pytest tests/test_rules.py           # single file
uv run pytest -k test_match_rule            # single test

# Run janitor
uv run python -c "
from malm.janitor import run_janitor
print(run_janitor('data/rules.json', 'data/janitor.db', 'data/janitor.lock', dry_run=True))
"

# Run discovery web UI
uv run uvicorn malm.web.app:app --reload --port 8899

# Extract PST (first run builds cache from 6GB file, subsequent runs are fast)
uv run python -c "
from malm.pst_extract import extract_pst
print(extract_pst(folder_filter='Innboks', limit=100))
"

# Search discovery DB
uv run python -c "
from malm.pst_extract import search_discovery
for r in search_discovery('konkurs', limit=10):
    print(f'{r[\"uuid\"]} | {r[\"subject\"][:60]}')
"

# Export evidence package
uv run python -c "
from malm.export import export_from_search
print(export_from_search('konkurs', package_name='konkurs_evidence'))
"
```

## Architecture

### Janitor (Downloads Organizer)

**Rule matching pipeline** (priority order):
1. **Keyword rules** — regex on filename (`data/rules.json` → `keyword_rules`)
2. **Content rules** — regex on extracted file content, scoped to specific extensions (`content_rules`)
3. **Extension rules** — glob on filename (`extension_rules`)
4. **Default** — `~/Downloads/_Unsorted`

**Core modules** (`src/malm/`):
- `janitor.py` — orchestrator: discover → match → move (or dry-run). Atomic file-level lock via `lock.py`.
- `rules.py` — loads `data/rules.json`, validates schema, runs match cascade.
- `db.py` — SQLite + sqlite-vec + FTS5. Schema auto-migrates on open. FTS uses delete-before-insert for correct index maintenance.
- `content.py` — reads file content for classification. Supports xlsx, pdf, docx, csv, xml, json, txt.
- `embeddings.py` — Voyage AI (`voyage-3-large`, 1024d). Requires `VOYAGE_API_KEY`.

### Legal Discovery (Unified Document Pipeline)

**Pipeline:** Sources → ingest → extract content → index in unified.db → search/export

**Sources:**
- PST emails: `pst_extract.py` → readpst (cached) → parse .eml → UUID-named files + markdown
- Filesystem: rule-matched files from janitor
- Filedrop: uploaded files via web UI

**Core modules** (`src/malm/`):
- `models.py` — `Document` dataclass: unified schema for emails, files, and attachments.
- `store.py` — `DocumentStore`: SQLite with FTS5 + optional sqlite-vec (1024d embeddings). Unified `documents` table replaces separate `emails`/`attachments` tables.
- `discovery_db.py` — Legacy SQLite store (emails + attachments tables). Use `scripts/migrate-to-unified.py` to migrate to unified.db.
- `pst_extract.py` — Extracts emails from PST files via `readpst`. Per-PST hash-based caching. Extracts threading headers (Message-ID, In-Reply-To, References). Handles Windows-1252/ISO-8859-1 encoding.
- `export.py` — Evidence package export: CSV, ZIP with manifest. Supports both DiscoveryDB and DocumentStore via `export_from_store()`.

**Web UI** (`src/malm/web/`):
- `app.py` — FastAPI + Jinja2 + htmx. Routes: dashboard, search, email detail, folder browser, timeline, thread view, attachment serving, evidence export.
- `templates/` — Dark-themed responsive UI with real-time search via htmx.

**Output** (`~/Documents/Legal-Discovery/`, not in repo):
- `source-doc/` — UUID-prefixed .eml files and attachments
- `MD/` — UUID-prefixed parsed markdown
- `discovery.db` — Legacy SQLite index (emails + attachments)
- `unified.db` — Unified SQLite index (documents table, FTS5, optional vec)
- `.eml-cache/` — Per-PST readpst cache (hash-isolated)
- `exports/` — Evidence package ZIPs

**Migration:** `uv run python scripts/migrate-to-unified.py` reads discovery.db and populates unified.db. Idempotent (INSERT OR REPLACE).

**Claude Code plugin** (`.claude-plugin/`):
- `agents/malm.md` — downloads organizer agent
- `agents/pst-search.md` — PST search/extraction agent (legacy, uses discovery.db)
- `agents/search.md` — unified search agent (uses unified.db)
- `commands/malm.md` — `/malm` slash command

## Key Details

- Python 3.14+, managed with `uv`
- Rules are Norwegian-language legal/financial categories
- `data/` directory is gitignored; `scripts/rules.json` is the version-controlled default
- Lock uses `O_CREAT | O_EXCL` for atomic acquisition with stale PID detection
- PST cache is per-file (SHA256 hash of path) to prevent cross-case contamination
- Discovery DB enables foreign keys; email + attachments are inserted atomically
