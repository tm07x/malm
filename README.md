## malm

Unified document ingestion, extraction, indexing, search, and evidence export.

### Setup

```bash
uv sync
uv run python scripts/init-db.py
```

### Core commands

```bash
# Run tests
uv run pytest

# Run web UI
uv run uvicorn malm.web.app:app --reload --port 8899

# PST extraction (requires readpst + DISCOVERY_PST_PATH)
export DISCOVERY_PST_PATH=/absolute/path/to/mailbox.pst
uv run python -c "
from malm.pst_extract import extract_pst
print(extract_pst(folder_filter='Innboks', limit=100))
"

# Search unified store
uv run python -c "
from malm.pst_extract import search_discovery
for r in search_discovery('konkurs', limit=10):
    print(f'{r[\"uuid\"]} | {r.get(\"title\", \"\")[:60]}')
"

# Export evidence package
uv run python -c "
from malm.export import export_from_search
print(export_from_search('konkurs', package_name='konkurs_evidence'))
"
```

### Optional semantic search

Set `VOYAGE_API_KEY` to enable semantic/hybrid search paths and embedding jobs.

```bash
export VOYAGE_API_KEY=...
```
