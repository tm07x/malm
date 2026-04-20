---
name: malm
description: Organize ~/Downloads based on strict JSON rules
allowed-tools: ["Bash", "Read", "Glob", "Agent"]
---

Run the downloads ingestion workflow to classify and organize files.

## Usage

- `/malm` — dry-run, show proposed moves
- `/malm run` — execute moves
- `/malm status` — show file counts by status

## Behavior

1. Check if local runtime data is initialized; if not, run `uv run python scripts/init-db.py`.
2. Dispatch the downloads-malm agent with the appropriate mode.
