# Downloads Janitor Plugin — Design Spec (v2)

## Problem

Files pile up in ~/Downloads with no organization.

## Scope

Move files from ~/Downloads to the right folder based on rules. That's it.

---

## Architecture

One agent. One SQLite table. One rules file.

```
downloads-janitor/                    # Claude Code plugin
├── .claude-plugin/
│   └── plugin.json
├── agents/
│   └── janitor.md                    # Single agent: scan, match, move
├── commands/
│   └── janitor.md                    # /janitor command (dry-run default)
└── scripts/
    ├── init-db.py                    # SQLite init
    └── rules.json                    # Default rules (copied to runtime on first run)

~/Projects/scan-files/data/           # Runtime data
├── janitor.db                        # SQLite
├── rules.json                        # Active rules (user-editable)
└── janitor.lock                      # Prevents concurrent runs
```

No ChromaDB. No Voyage AI. No external API dependencies. Works offline.

---

## Rules Format

File: `~/Projects/scan-files/data/rules.json`

Two rule types. Keyword rules evaluated first, then extension rules:

```json
{
  "source": "~/Downloads",
  "keyword_rules": [
    {
      "id": "legal",
      "pattern": "(?i)(stevning|forlik|klage|contract|agreement|settlement|claim|pant|sletting)",
      "dest": "~/Documents/Legal"
    },
    {
      "id": "finance",
      "pattern": "(?i)(balance|faktura|invoice|regnskap|hovedbok|leverandør|avstemming|a-melding|lønn|payroll)",
      "dest": "~/Documents/Finance"
    },
    {
      "id": "microsoft",
      "pattern": "(?i)(microsoft|azure|csp-auth|partner-program|msgraph)",
      "dest": "~/Documents/Work/Microsoft"
    }
  ],
  "extension_rules": [
    {
      "id": "installers",
      "match": ["*.dmg", "*.iso", "*.pkg", "*.app"],
      "dest": "~/Downloads/_Installers"
    },
    {
      "id": "archives",
      "match": ["*.zip", "*.tar", "*.tar.gz", "*.xz", "*.cpgz", "*.rar"],
      "dest": "~/Downloads/_Archives"
    },
    {
      "id": "images",
      "match": ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.svg", "*.webp"],
      "dest": "~/Documents/Images"
    },
    {
      "id": "documents-pdf",
      "match": ["*.pdf"],
      "dest": "~/Documents/PDFs"
    },
    {
      "id": "documents-office",
      "match": ["*.docx", "*.doc", "*.xlsx", "*.xls", "*.pptx"],
      "dest": "~/Documents/Office"
    },
    {
      "id": "data",
      "match": ["*.csv", "*.json", "*.xml", "*.yaml", "*.yml"],
      "dest": "~/Documents/Data"
    },
    {
      "id": "email",
      "match": ["*.eml", "*.msg"],
      "dest": "~/Documents/Email"
    },
    {
      "id": "media",
      "match": ["*.mp4", "*.mov", "*.mp3", "*.m4a", "*.m3u"],
      "dest": "~/Documents/Media"
    }
  ],
  "defaults": {
    "dest": "~/Downloads/_Unsorted"
  }
}
```

### Rule Evaluation

1. Skip dotfiles and directories (v1 ignores directories entirely).
2. Skip files already in SQLite with status `moved`.
3. **Keyword rules** match first — regex against filename. First match wins. A PDF with "stevning" in the name goes to Legal, not generic PDFs.
4. **Extension rules** match second — glob pattern against filename. First match wins.
5. If nothing matches, file goes to `defaults.dest`.

Pure function: `(filename, extension, rules) -> destination`. Testable standalone.

---

## SQLite Schema

Database: `~/Projects/scan-files/data/janitor.db`

```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    extension TEXT,
    size_bytes INTEGER,
    source_path TEXT NOT NULL UNIQUE,
    dest_path TEXT,
    rule_matched TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    discovered_at TEXT NOT NULL,
    moved_at TEXT
);

CREATE INDEX idx_files_status ON files(status);
CREATE INDEX idx_files_source ON files(source_path);
```

One table. Every state in one row.
- `discovered` — seen but not yet moved
- `moved` — successfully moved
- `skipped` — no rule matched, sent to _Unsorted
- `error` — move failed (reason stored in rule_matched)

---

## Agent

One agent. One pass. Scan-decide-move per file.

- **Model:** sonnet
- **Tools:** Bash, Read, Glob

**Behavior:**
1. Acquire lock file. If locked, abort.
2. Initialize if needed: create `data/` dir, run `init-db.py`, copy default `rules.json`.
3. Validate `rules.json`. If invalid, abort.
4. Glob `~/Downloads/*` (top-level only, skip dotfiles).
5. For each file not in SQLite (by `source_path`): insert with status `discovered`.
6. For each file with status `discovered`:
   - Verify file still exists. If not, set status `error`, continue.
   - Match keyword rules (regex on filename).
   - If no keyword match, match extension rules (glob on filename).
   - If no match, use `defaults.dest`.
   - Move file. Create destination dir if needed.
   - On success: update row with dest_path, rule_matched, status `moved`, moved_at.
   - On failure: set status `error`, continue.
7. Release lock.
8. Print summary.

Each file operation is individually try/caught. One failure does not stop the batch.

---

## /janitor Command

Dry-run by default:

```
/janitor           → dry-run: prints proposed moves, no action
/janitor run       → executes moves
/janitor status    → shows counts (discovered, moved, error)
```

Dry-run output example:

```
Proposed moves:
  01 2025-11-28 - Stevning.pdf        → ~/Documents/Legal          (keyword: legal)
  Antigravity.dmg                     → ~/Downloads/_Installers    (ext: installers)
  Balance.pdf                         → ~/Documents/Finance        (keyword: finance)
  Gemini_Generated_Image_4asm.png     → ~/Documents/Images         (ext: images)

65 to move, 3 unmatched → _Unsorted, 12 already processed
Run `/janitor run` to execute.
```

---

## Cron

```
0 */4 * * *  — every 4 hours, auto-execute mode
```

Added after manual runs confirm rules are correct.

---

## Failure Handling

| Scenario | Behavior |
|----------|----------|
| rules.json missing/invalid | Abort with clear error |
| File gone between scan and move | status `error`, continue |
| Destination mkdir fails | status `error`, continue |
| Disk full | status `error`, continue |
| Concurrent runs | Lock file prevents, second run aborts |
| SQLite corrupted | Delete and reinit, history lost but files already moved |

---

## Dependencies

- Python 3.11+ (via uv)
- sqlite3 (stdlib)

Zero external packages. Zero API keys. Zero network required.

---

## Testing

Before writing agent code:

1. Create temp dir with 20 representative files from the actual ~/Downloads scan.
2. Write rules engine as pure function: `match_rule(filename, rules) -> (dest, rule_id)`.
3. Test standalone against the 20 files.
4. Verify destinations. This is the regression suite.

---

## What v1 Does NOT Do

- Does not process directories (files only)
- Does not delete anything (moves only)
- Does not require internet
- Does not read file contents
- Does not use embeddings, vector DBs, or LLM classification
- Does not try to be smart — it follows rules

## Future (only if real usage proves need)

- Content extraction + embeddings for unroutable files
- Directory handling
- Age-based cleanup
- Duplicate detection
