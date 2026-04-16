---
name: search
description: Search the malm document store
allowed-tools: ["Bash", "Read", "Glob", "Agent"]
---

Search the malm document store for emails, files, and attachments.

## Usage

- `/search <query>` — hybrid search (keyword + semantic)
- `/search <query> --emails` — search emails only
- `/search <query> --export` — search and export as evidence package

## Behavior

1. Dispatch the malm-search agent with the query and options.
