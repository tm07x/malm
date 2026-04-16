---
name: malm
description: Organize ~/Downloads based on strict JSON rules
allowed-tools: ["Bash", "Read", "Glob", "Agent"]
---

Run the downloads malm to organize files.

## Usage

- `/malm` — dry-run, show proposed moves
- `/malm run` — execute moves
- `/malm status` — show file counts by status

## Behavior

1. Check if `~/Projects/scan-files/data/malm.db` exists. If not, run init.
2. Dispatch the downloads-malm agent with the appropriate mode.
