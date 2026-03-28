---
name: janitor
description: Organize ~/Downloads based on strict JSON rules
allowed-tools: ["Bash", "Read", "Glob", "Agent"]
---

Run the downloads janitor to organize files.

## Usage

- `/janitor` — dry-run, show proposed moves
- `/janitor run` — execute moves
- `/janitor status` — show file counts by status

## Behavior

1. Check if `~/Projects/scan-files/data/janitor.db` exists. If not, run init.
2. Dispatch the downloads-janitor agent with the appropriate mode.
