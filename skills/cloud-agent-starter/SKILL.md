---
name: cloud-agent-starter
description: Use when starting work in this repository and needing immediate Cloud-agent setup, run, and testing workflows by codebase area.
---

# Cloud Agent Starter (Malm)

## 1) First 2 minutes: auth + environment

- No app login is required for core local workflows.
- Install deps once: `uv sync`
- Initialize local janitor data once: `uv run python scripts/init-db.py`
- Optional external auth only for semantic embeddings:
  - `export VOYAGE_API_KEY=...`
  - If unset, use FTS/non-semantic flows (tests still work).

## 2) Global smoke checks

Run these first to verify the environment before deeper work:

- `uv run pytest tests/test_rules.py tests/test_rules_validation.py`
- `uv run pytest tests/test_store.py tests/test_extract.py`

## 3) Codebase-area workflows

### A) Rules + filesystem ingestion (`src/malm/rules.py`, `src/malm/ingest/filesystem.py`)

Run:

- `uv run pytest tests/test_rules.py tests/test_rules_validation.py tests/test_ingest_filesystem.py`

Practical flags/mocks:

- Safe move behavior: `dry_run=True` in `FilesystemIngestor.scan(...)`
- Real move validation: run the `test_actual_move` case in `tests/test_ingest_filesystem.py`

### B) PST/email ingestion (`src/malm/pst_extract.py`, `src/malm/ingest/pst.py`)

Real extraction (requires `readpst` + PST path):

- `export DISCOVERY_PST_PATH=/absolute/path/to/mailbox.pst`
- `uv run python -c "from malm.pst_extract import extract_pst; print(extract_pst(folder_filter='Innboks', limit=100))"`

Cloud-friendly test workflow (no real PST required):

- `uv run pytest tests/test_pst_extract.py tests/test_ingest_pst.py`

### C) Unified store + export (`src/malm/store.py`, `src/malm/export.py`)

Run:

- `uv run pytest tests/test_store.py tests/test_export.py`

Useful check command:

- `uv run python -c "from malm.store import DocumentStore; from pathlib import Path; s=DocumentStore(str(Path.home()/ 'Documents/Legal-Discovery/unified.db')); print(s.stats()); s.close()"`

### D) Web UI + API (`src/malm/web/app.py`)

Run local UI:

- `uv run uvicorn malm.web.app:app --reload --port 8899`

Use isolated DB (recommended in Cloud sessions):

- `export JANITOR_DB_PATH=/tmp/malm-test.db`

Targeted web tests:

- `uv run pytest tests/test_web.py tests/test_web_unified.py`

Manual checks:

- `GET /`
- `GET /search?q=test`
- `GET /api/stats`

## 4) Feature switches and fallback behavior

- `JANITOR_DB_PATH`: forces web app DB path (use for isolated test DBs).
- `DISCOVERY_PST_PATH`: default PST source path for extraction scripts.
- `VOYAGE_API_KEY`: enables semantic/hybrid embedding flows.
- Search mode fallback: web search auto-falls back to non-semantic DB search when embedding calls fail.

## 5) Updating this skill (keep it short and practical)

Whenever you discover a new reliable runbook trick:

1. Add it under the relevant codebase area above.
2. Include one concrete command and one “when to use” note.
3. Prefer targeted tests over full-suite commands.
4. Remove stale steps immediately when module paths/tests change.
