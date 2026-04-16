# Unified Document Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge 5 projects (scan-files, fend-search, Teds-Agent, Thinkdoc, docx-2-rag) into one unified pipeline: ingest any document → extract content → index → search → export.

**Architecture:** One SQLite database with one `documents` table, one FTS5 index, one optional vector table. Multiple ingestors (PST emails, filesystem scan, file drop) feed into a shared document store. One web UI, one search API, one export system. Content extraction is pluggable — local parsers for simple formats, Mistral API for complex/OCR cases.

**Tech Stack:** Python 3.14+, uv, SQLite + FTS5 + sqlite-vec, FastAPI + Jinja2 + htmx, Voyage AI embeddings (optional), readpst (PST), python-docx/openpyxl/pymupdf (content extraction)

---

## What We're Merging

| Project | What it does | What we keep |
|---------|-------------|--------------|
| **scan-files/janitor** | Rule-based file organizer with FTS + vector search | Rules engine, content extraction, embeddings, lock |
| **scan-files/discovery** | PST email extraction + web UI | PST ingestor, web UI, export, threading |
| **fend-search** | PST search with SHA-256 provenance, attachment indexing | SHA-256 hashing, attachment text extraction, build_index approach |
| **Teds-Agent** | Email triage with Ollama embeddings, Graph API fetch | Email schema design (conversation_id, categories, classifications) |
| **Thinkdoc/excavator** | AI-powered document pipeline: classify → chunk → enrich → embed | Pipeline stages pattern, AI classification/enrichment, job tracking |
| **docx-2-rag** | DOCX → Markdown + JSON for RAG | DOCX parser, chunker, citation graph, markdown renderer |

## What We're NOT Building

- Weaviate integration (Thinkdoc's store.py) — SQLite is sufficient
- Telegram notifications (Thinkdoc's notify.py) — not needed
- Graph API email fetch (Teds-Agent) — we have PST and can add Graph later
- AI classification/enrichment (Thinkdoc's classify.py, enrich.py) — deferred, can add as pipeline stage later
- RAG export format (docx-2-rag's rag_export.py) — evidence export is the priority

## File Structure (Target)

```
src/malm/
  # Core document store
  store.py              ← NEW: unified SQLite DB (replaces db.py + discovery_db.py)
  models.py             ← NEW: dataclasses for Document, Email, Attachment, SearchResult

  # Ingestors (one per source type)
  ingest/
    __init__.py
    pst.py              ← MOVE: from pst_extract.py (PST → documents)
    filesystem.py       ← MOVE: from malm.py (~/Downloads scan → documents)
    filedrop.py         ← NEW: watch a directory, ingest new files on arrival

  # Content extraction
  extract/
    __init__.py
    text.py             ← MERGE: content.py + docx-2-rag/docx_parser + excavator/extract
    email_parser.py     ← MOVE: _parse_eml + _decode_mime_header from pst_extract.py
    hasher.py           ← NEW: SHA-256 for provenance (from fend-search)

  # Search
  search.py             ← MERGE: search methods from db.py + discovery_db.py

  # Rules (janitor-specific, but applies to any file)
  rules.py              ← KEEP as-is

  # Embeddings
  embeddings.py         ← KEEP as-is (Voyage AI)

  # Export
  export.py             ← KEEP + extend

  # Process lock
  lock.py               ← KEEP as-is

  # Web UI
  web/
    app.py              ← EXTEND: unified routes for all document types
    templates/          ← EXTEND: add file browser, unified search
```

## Unified Schema

```sql
-- One table for everything: emails, files, attachments
CREATE TABLE documents (
    uuid TEXT PRIMARY KEY,
    doc_type TEXT NOT NULL,        -- 'email', 'file', 'attachment'
    parent_uuid TEXT,              -- attachment → parent email/file
    source TEXT NOT NULL,          -- 'pst', 'filesystem', 'filedrop'
    source_path TEXT,              -- original location
    stored_path TEXT,              -- where we saved it (source-doc/)
    markdown_path TEXT,            -- parsed markdown (MD/)
    sha256 TEXT,                   -- content hash for dedup + provenance
    filename TEXT,
    extension TEXT,
    size_bytes INTEGER,
    content_type TEXT,             -- MIME type

    -- Metadata (all types)
    title TEXT,                    -- subject for email, filename for file
    body_text TEXT,                -- full extracted text
    body_preview TEXT,             -- first 500 chars

    -- Email-specific
    sender TEXT,
    recipients TEXT,
    cc TEXT,
    date_sent TEXT,               -- ISO format
    message_id TEXT,
    in_reply_to TEXT,
    references_header TEXT,
    thread_id TEXT,
    folder TEXT,                   -- PST folder or filesystem path

    -- Classification
    rule_matched TEXT,             -- janitor rule that matched
    tags TEXT,                     -- comma-separated: responsive, privileged, etc.
    status TEXT DEFAULT 'indexed', -- indexed, moved, exported, error

    -- Timestamps
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE INDEX idx_doc_type ON documents(doc_type);
CREATE INDEX idx_doc_parent ON documents(parent_uuid);
CREATE INDEX idx_doc_source ON documents(source);
CREATE INDEX idx_doc_sha256 ON documents(sha256);
CREATE INDEX idx_doc_thread ON documents(thread_id);
CREATE INDEX idx_doc_sender ON documents(sender);
CREATE INDEX idx_doc_date ON documents(date_sent);
CREATE INDEX idx_doc_status ON documents(status);
CREATE INDEX idx_doc_folder ON documents(folder);

CREATE VIRTUAL TABLE documents_fts USING fts5(
    title, sender, recipients, body_text, filename, folder, tags,
    content='documents', content_rowid='rowid'
);

-- Optional vector search (requires sqlite-vec)
CREATE VIRTUAL TABLE IF NOT EXISTS documents_vec USING vec0(
    doc_id INTEGER PRIMARY KEY, embedding float[1024]
);

-- Ingest run tracking
CREATE TABLE ingest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_path TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    docs_processed INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running'
);
```

---

### Task 1: Unified Document Store

**Files:**
- Create: `src/malm/models.py`
- Create: `src/malm/store.py`
- Create: `tests/test_store.py`
- Reference: `src/malm/db.py` (existing JanitorDB pattern)
- Reference: `src/malm/discovery_db.py` (existing DiscoveryDB pattern)

- [ ] **Step 1: Write failing tests for the document store**

```python
# tests/test_store.py
import tempfile
from pathlib import Path
import pytest
from malm.store import DocumentStore
from malm.models import Document


@pytest.fixture
def store():
    tmp = tempfile.mkdtemp()
    s = DocumentStore(str(Path(tmp) / "test.db"))
    yield s
    s.close()


class TestDocumentStore:
    def test_insert_and_get(self, store):
        doc = Document(
            uuid="abc123", doc_type="email", source="pst",
            title="Test email", filename="1.eml",
            body_text="Hello world", created_at="2024-01-01T00:00:00Z",
        )
        store.insert(doc)
        result = store.get("abc123")
        assert result["uuid"] == "abc123"
        assert result["title"] == "Test email"

    def test_insert_with_parent(self, store):
        store.insert(Document(
            uuid="email1", doc_type="email", source="pst",
            title="Parent", filename="1.eml", created_at="2024-01-01T00:00:00Z",
        ))
        store.insert(Document(
            uuid="att1", doc_type="attachment", source="pst",
            parent_uuid="email1", title="doc.pdf", filename="doc.pdf",
            created_at="2024-01-01T00:00:00Z",
        ))
        children = store.get_children("email1")
        assert len(children) == 1
        assert children[0]["uuid"] == "att1"

    def test_fts_search(self, store):
        store.insert(Document(
            uuid="d1", doc_type="file", source="filesystem",
            title="Financial report", filename="report.xlsx",
            body_text="Q4 revenue increased by 15 percent",
            created_at="2024-01-01T00:00:00Z",
        ))
        store.insert(Document(
            uuid="d2", doc_type="email", source="pst",
            title="Lunch plans", filename="2.eml",
            body_text="Want to grab lunch?",
            created_at="2024-01-01T00:00:00Z",
        ))
        results = store.search("revenue")
        assert len(results) == 1
        assert results[0]["uuid"] == "d1"

    def test_search_with_filters(self, store):
        store.insert(Document(
            uuid="e1", doc_type="email", source="pst",
            title="Invoice", sender="vendor@co.com",
            date_sent="2024-06-01", folder="Innboks",
            created_at="2024-01-01T00:00:00Z",
        ))
        store.insert(Document(
            uuid="e2", doc_type="email", source="pst",
            title="Invoice", sender="other@co.com",
            date_sent="2024-03-01", folder="Sendte",
            created_at="2024-01-01T00:00:00Z",
        ))
        results = store.search("invoice", folder="Innboks")
        assert len(results) == 1
        assert results[0]["uuid"] == "e1"

    def test_dedup_by_sha256(self, store):
        store.insert(Document(
            uuid="f1", doc_type="file", source="filesystem",
            sha256="deadbeef", filename="a.pdf",
            created_at="2024-01-01T00:00:00Z",
        ))
        dup = store.find_by_sha256("deadbeef")
        assert dup is not None
        assert dup["uuid"] == "f1"

    def test_get_thread(self, store):
        for i in range(3):
            store.insert(Document(
                uuid=f"t{i}", doc_type="email", source="pst",
                title=f"RE: Discussion", thread_id="thread-1",
                date_sent=f"2024-01-0{i+1}", created_at="2024-01-01T00:00:00Z",
            ))
        thread = store.get_thread("thread-1")
        assert len(thread) == 3
        assert thread[0]["date_sent"] <= thread[1]["date_sent"]

    def test_stats(self, store):
        store.insert(Document(
            uuid="s1", doc_type="email", source="pst",
            title="Test", created_at="2024-01-01T00:00:00Z",
        ))
        store.insert(Document(
            uuid="s2", doc_type="file", source="filesystem",
            title="Test", created_at="2024-01-01T00:00:00Z",
        ))
        stats = store.stats()
        assert stats["total"] == 2
        assert stats["by_type"]["email"] == 1
        assert stats["by_type"]["file"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'janitor.store'`

- [ ] **Step 3: Create models.py**

```python
# src/malm/models.py
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Document:
    uuid: str
    doc_type: str  # 'email', 'file', 'attachment'
    source: str    # 'pst', 'filesystem', 'filedrop'
    created_at: str

    parent_uuid: str | None = None
    source_path: str | None = None
    stored_path: str | None = None
    markdown_path: str | None = None
    sha256: str | None = None
    filename: str | None = None
    extension: str | None = None
    size_bytes: int | None = None
    content_type: str | None = None

    title: str | None = None
    body_text: str | None = None
    body_preview: str | None = None

    # Email-specific
    sender: str | None = None
    recipients: str | None = None
    cc: str | None = None
    date_sent: str | None = None
    message_id: str | None = None
    in_reply_to: str | None = None
    references_header: str | None = None
    thread_id: str | None = None
    folder: str | None = None

    # Classification
    rule_matched: str | None = None
    tags: str | None = None
    status: str = "indexed"
    updated_at: str | None = None
```

- [ ] **Step 4: Create store.py**

```python
# src/malm/store.py
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone

from malm.models import Document

try:
    import sqlite_vec
    HAS_VEC = True
except ImportError:
    HAS_VEC = False


class DocumentStore:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.row_factory = sqlite3.Row
        if HAS_VEC:
            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                uuid TEXT PRIMARY KEY,
                doc_type TEXT NOT NULL,
                parent_uuid TEXT,
                source TEXT NOT NULL,
                source_path TEXT,
                stored_path TEXT,
                markdown_path TEXT,
                sha256 TEXT,
                filename TEXT,
                extension TEXT,
                size_bytes INTEGER,
                content_type TEXT,
                title TEXT,
                body_text TEXT,
                body_preview TEXT,
                sender TEXT,
                recipients TEXT,
                cc TEXT,
                date_sent TEXT,
                message_id TEXT,
                in_reply_to TEXT,
                references_header TEXT,
                thread_id TEXT,
                folder TEXT,
                rule_matched TEXT,
                tags TEXT,
                status TEXT DEFAULT 'indexed',
                created_at TEXT NOT NULL,
                updated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_doc_type ON documents(doc_type);
            CREATE INDEX IF NOT EXISTS idx_doc_parent ON documents(parent_uuid);
            CREATE INDEX IF NOT EXISTS idx_doc_source ON documents(source);
            CREATE INDEX IF NOT EXISTS idx_doc_sha256 ON documents(sha256);
            CREATE INDEX IF NOT EXISTS idx_doc_thread ON documents(thread_id);
            CREATE INDEX IF NOT EXISTS idx_doc_sender ON documents(sender);
            CREATE INDEX IF NOT EXISTS idx_doc_date ON documents(date_sent);
            CREATE INDEX IF NOT EXISTS idx_doc_status ON documents(status);
            CREATE INDEX IF NOT EXISTS idx_doc_folder ON documents(folder);

            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                title, sender, recipients, body_text, filename, folder, tags,
                content='documents', content_rowid='rowid'
            );

            CREATE TABLE IF NOT EXISTS ingest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_path TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                docs_processed INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running'
            );
        """)
        if HAS_VEC:
            vec_exists = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='documents_vec'"
            ).fetchone()
            if not vec_exists:
                self.conn.execute(
                    "CREATE VIRTUAL TABLE documents_vec USING vec0(doc_id INTEGER PRIMARY KEY, embedding float[1024])"
                )
        self.conn.commit()

    def insert(self, doc: Document, commit: bool = True):
        d = {k: v for k, v in asdict(doc).items() if v is not None}
        cols = ", ".join(d.keys())
        placeholders = ", ".join(f":{k}" for k in d.keys())
        self.conn.execute(
            f"INSERT OR IGNORE INTO documents ({cols}) VALUES ({placeholders})", d
        )
        self._sync_fts(doc.uuid)
        if commit:
            self.conn.commit()

    def _sync_fts(self, uuid: str):
        row = self.conn.execute(
            "SELECT rowid, title, sender, recipients, body_text, filename, folder, tags "
            "FROM documents WHERE uuid = ?", (uuid,)
        ).fetchone()
        if row:
            self.conn.execute(
                "INSERT OR REPLACE INTO documents_fts(rowid, title, sender, recipients, body_text, filename, folder, tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(row[k] or "" for k in ["rowid", "title", "sender", "recipients", "body_text", "filename", "folder", "tags"]),
            )

    def get(self, uuid: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM documents WHERE uuid = ?", (uuid,)).fetchone()
        return dict(row) if row else None

    def get_children(self, parent_uuid: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM documents WHERE parent_uuid = ?", (parent_uuid,)
        ).fetchall()]

    def find_by_sha256(self, sha256: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM documents WHERE sha256 = ? LIMIT 1", (sha256,)).fetchone()
        return dict(row) if row else None

    def get_thread(self, thread_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM documents WHERE thread_id = ? ORDER BY date_sent ASC", (thread_id,)
        ).fetchall()]

    def search(self, query: str = "", doc_type: str | None = None,
               folder: str | None = None, sender: str | None = None,
               source: str | None = None,
               after: str | None = None, before: str | None = None,
               limit: int = 50) -> list[dict]:
        if query and not any([folder, sender, source, after, before]):
            return self.search_fts(query, doc_type=doc_type, limit=limit)

        sql = "SELECT * FROM documents WHERE 1=1"
        params = []
        if query:
            sql += " AND (title LIKE ? OR sender LIKE ? OR body_text LIKE ? OR filename LIKE ?)"
            q = f"%{query}%"
            params.extend([q, q, q, q])
        if doc_type:
            sql += " AND doc_type = ?"
            params.append(doc_type)
        if folder:
            sql += " AND folder = ?"
            params.append(folder)
        if sender:
            sql += " AND sender LIKE ?"
            params.append(f"%{sender}%")
        if source:
            sql += " AND source = ?"
            params.append(source)
        if after:
            sql += " AND date_sent >= ?"
            params.append(after)
        if before:
            sql += " AND date_sent <= ?"
            params.append(before)
        sql += " ORDER BY COALESCE(date_sent, created_at) DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def search_fts(self, query: str, doc_type: str | None = None, limit: int = 50) -> list[dict]:
        sql = (
            "SELECT d.*, snippet(documents_fts, 3, '>>>', '<<<', '...', 32) AS snippet "
            "FROM documents_fts fts JOIN documents d ON fts.rowid = d.rowid "
            "WHERE documents_fts MATCH ?"
        )
        params = [query]
        if doc_type:
            sql += " AND d.doc_type = ?"
            params.append(doc_type)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        by_type = {}
        for row in self.conn.execute("SELECT doc_type, COUNT(*) as c FROM documents GROUP BY doc_type"):
            by_type[row["doc_type"]] = row["c"]
        by_source = {}
        for row in self.conn.execute("SELECT source, COUNT(*) as c FROM documents GROUP BY source"):
            by_source[row["source"]] = row["c"]
        folders = [r[0] for r in self.conn.execute(
            "SELECT DISTINCT folder FROM documents WHERE folder IS NOT NULL ORDER BY folder"
        ).fetchall()]
        return {"total": total, "by_type": by_type, "by_source": by_source, "folders": folders}

    def start_run(self, source: str, source_path: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO ingest_runs (source, source_path, started_at) VALUES (?, ?, ?)",
            (source, source_path, _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, docs: int, errors: int, status: str = "done"):
        self.conn.execute(
            "UPDATE ingest_runs SET finished_at=?, docs_processed=?, errors=?, status=? WHERE id=?",
            (_now(), docs, errors, status, run_id),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_store.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/malm/models.py src/malm/store.py tests/test_store.py
git commit -m "feat: unified document store with FTS5 search"
```

---

### Task 2: Content Extraction Module

**Files:**
- Create: `src/malm/extract/__init__.py`
- Create: `src/malm/extract/text.py`
- Create: `src/malm/extract/email_parser.py`
- Create: `src/malm/extract/hasher.py`
- Create: `tests/test_extract.py`
- Reference: `src/malm/content.py` (existing file readers)
- Reference: `src/malm/pst_extract.py` (_parse_eml, _decode_mime_header)
- Reference: `/Users/tm07x/Projects/fend-search/build_index.py` (SHA-256 hashing)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_extract.py
import tempfile
from pathlib import Path
import pytest

from malm.extract.text import extract_text
from malm.extract.email_parser import parse_eml
from malm.extract.hasher import sha256_file


class TestTextExtraction:
    def test_txt_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello world æøå")
        result = extract_text(f)
        assert result is not None
        assert "Hello world" in result["body_text"]
        assert "æøå" in result["body_text"]

    def test_csv_file(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("name,value\nalice,100\nbob,200")
        result = extract_text(f)
        assert "alice" in result["body_text"]

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "binary.xyz"
        f.write_bytes(b"\x00\x01\x02")
        result = extract_text(f)
        assert result is None

    def test_json_file(self, tmp_path):
        f = tmp_path / "config.json"
        f.write_text('{"key": "value", "nested": {"a": 1}}')
        result = extract_text(f)
        assert "key" in result["body_text"]


class TestEmailParser:
    def test_parse_simple_eml(self, tmp_path):
        eml = tmp_path / "test.eml"
        eml.write_text(
            "From: alice@example.com\r\n"
            "To: bob@example.com\r\n"
            "Subject: Test\r\n"
            "Date: Mon, 01 Jan 2024 10:00:00 +0000\r\n"
            "Message-ID: <msg001@example.com>\r\n"
            "\r\n"
            "Hello Bob\r\n"
        )
        result = parse_eml(eml)
        assert result["subject"] == "Test"
        assert result["sender"] == "alice@example.com"
        assert result["to"] == "bob@example.com"
        assert "Hello Bob" in result["body"]
        assert result["message_id"] == "<msg001@example.com>"
        assert result["thread_id"] != ""

    def test_parse_folded_headers(self, tmp_path):
        eml = tmp_path / "folded.eml"
        eml.write_text(
            "From: alice@example.com\r\n"
            "To: bob@example.com,\r\n"
            "\tcharlie@example.com\r\n"
            "Subject: Test\r\n"
            "\r\n"
            "Body\r\n"
        )
        result = parse_eml(eml)
        assert "\n" not in result["to"]
        assert "charlie" in result["to"]


class TestHasher:
    def test_sha256(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        h = sha256_file(f)
        assert len(h) == 64  # hex digest length
        # Same content = same hash
        f2 = tmp_path / "test2.txt"
        f2.write_text("hello")
        assert sha256_file(f2) == h

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f1.write_text("hello")
        f2 = tmp_path / "b.txt"
        f2.write_text("world")
        assert sha256_file(f1) != sha256_file(f2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_extract.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create hasher.py**

```python
# src/malm/extract/hasher.py
import hashlib
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
```

- [ ] **Step 4: Create email_parser.py**

Move `_parse_eml`, `_decode_mime_header`, `_decode_payload`, `_unfold_header` from `pst_extract.py` into this standalone module. The function signature becomes `parse_eml(path: Path) -> dict` (same return shape as current `_parse_eml`). Copy the exact implementations from `src/malm/pst_extract.py` lines 57-163.

- [ ] **Step 5: Create text.py**

Merge content extraction from `src/malm/content.py` (the `CONTENT_READERS` dict and all `read_*` functions) into `extract_text(path) -> dict | None`. Same return shape: `{"body_text": str, "sheet_names": list, "headers": dict, "sample_rows": dict}`. The key difference: `body_text` replaces `cell_values` as the primary field — it's a single string, not a list.

- [ ] **Step 6: Create `src/malm/extract/__init__.py`**

```python
from malm.extract.text import extract_text
from malm.extract.email_parser import parse_eml
from malm.extract.hasher import sha256_file
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_extract.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add src/malm/extract/ tests/test_extract.py
git commit -m "feat: unified content extraction module"
```

---

### Task 3: PST Ingestor (Rewrite on Unified Store)

**Files:**
- Create: `src/malm/ingest/__init__.py`
- Create: `src/malm/ingest/pst.py`
- Create: `tests/test_ingest_pst.py`
- Reference: `src/malm/pst_extract.py` (existing implementation)
- Reference: `src/malm/extract/email_parser.py` (from Task 2)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ingest_pst.py
import tempfile
from pathlib import Path
import pytest
from malm.store import DocumentStore
from malm.ingest.pst import PstIngestor


@pytest.fixture
def store():
    tmp = tempfile.mkdtemp()
    s = DocumentStore(str(Path(tmp) / "test.db"))
    yield s
    s.close()


class TestPstIngestor:
    def test_ingest_creates_documents(self, store, tmp_path):
        """Create a fake .eml in a cache dir and ingest it."""
        cache = tmp_path / "cache"
        cache.mkdir()
        eml = cache / "1.eml"
        eml.write_text(
            "From: alice@example.com\r\n"
            "To: bob@example.com\r\n"
            "Subject: Test email\r\n"
            "Date: Mon, 01 Jan 2024 10:00:00 +0000\r\n"
            "Message-ID: <msg001@example.com>\r\n"
            "\r\n"
            "Body text here\r\n"
        )
        output = tmp_path / "output"
        output.mkdir()

        ingestor = PstIngestor(store, source_dir=output, md_dir=output / "md")
        result = ingestor.ingest_eml_dir(cache, pst_folder="Innboks")

        assert result["docs_processed"] >= 1
        assert result["errors"] == 0

        docs = store.search("Test email")
        assert len(docs) >= 1
        assert docs[0]["doc_type"] == "email"
        assert docs[0]["sender"] == "alice@example.com"
        assert docs[0]["thread_id"] is not None
```

- [ ] **Step 2: Implement PstIngestor**

`PstIngestor` wraps the existing `readpst` + EML parsing logic but writes to the unified `DocumentStore` instead of `DiscoveryDB`. It uses `extract.email_parser.parse_eml` and `extract.hasher.sha256_file`.

Key method: `ingest_pst(pst_path: str, folder_filter: str | None = None, limit: int | None = None) -> dict`
— calls `readpst`, walks the cache, parses each .eml, inserts `Document` records.

Secondary method: `ingest_eml_dir(eml_dir: Path, pst_folder: str = "Root") -> dict`
— for testing and for cases where readpst was already run.

- [ ] **Step 3: Run tests and commit**

Run: `uv run pytest tests/test_ingest_pst.py -v`

```bash
git add src/malm/ingest/ tests/test_ingest_pst.py
git commit -m "feat: PST ingestor on unified document store"
```

---

### Task 4: Filesystem Ingestor (Rewrite Janitor on Unified Store)

**Files:**
- Create: `src/malm/ingest/filesystem.py`
- Create: `tests/test_ingest_filesystem.py`
- Reference: `src/malm/janitor.py` (existing run_janitor)
- Reference: `src/malm/rules.py` (rule matching — kept as-is)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ingest_filesystem.py
import tempfile
from pathlib import Path
import pytest
from malm.store import DocumentStore
from malm.ingest.filesystem import FilesystemIngestor

RULES = {
    "source": "PLACEHOLDER",
    "keyword_rules": [
        {"id": "legal", "pattern": "(?i)stevning", "dest": "~/Documents/Legal"},
    ],
    "extension_rules": [
        {"id": "pdf", "match": ["*.pdf"], "dest": "~/Documents/PDFs"},
    ],
    "defaults": {"dest": "~/Downloads/_Unsorted"},
}


@pytest.fixture
def env(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    db_path = str(tmp_path / "test.db")
    store = DocumentStore(db_path)
    rules = {**RULES, "source": str(source)}
    return source, store, rules


class TestFilesystemIngestor:
    def test_discovers_and_indexes(self, env):
        source, store, rules = env
        (source / "report.pdf").write_bytes(b"%PDF-fake")
        ingestor = FilesystemIngestor(store, rules)
        result = ingestor.scan(dry_run=True)
        assert result["discovered"] >= 1

        docs = store.search("report.pdf")
        assert len(docs) >= 1
        assert docs[0]["doc_type"] == "file"
        assert docs[0]["rule_matched"] == "pdf"

    def test_keyword_rule_overrides_extension(self, env):
        source, store, rules = env
        (source / "Stevning-2024.pdf").write_bytes(b"%PDF-fake")
        ingestor = FilesystemIngestor(store, rules)
        ingestor.scan(dry_run=True)
        docs = store.search("Stevning")
        assert docs[0]["rule_matched"] == "legal"

    def test_dry_run_does_not_move(self, env):
        source, store, rules = env
        f = source / "test.pdf"
        f.write_bytes(b"%PDF-fake")
        ingestor = FilesystemIngestor(store, rules)
        ingestor.scan(dry_run=True)
        assert f.exists()  # still in source
```

- [ ] **Step 2: Implement FilesystemIngestor**

`FilesystemIngestor` scans a directory, applies rules, optionally extracts content, indexes into `DocumentStore`, and moves files. Reuses `rules.py` for matching, `extract.text.extract_text` for content, `extract.hasher.sha256_file` for dedup.

- [ ] **Step 3: Run tests and commit**

Run: `uv run pytest tests/test_ingest_filesystem.py -v`

```bash
git add src/malm/ingest/filesystem.py tests/test_ingest_filesystem.py
git commit -m "feat: filesystem ingestor on unified document store"
```

---

### Task 5: Unified Web UI

**Files:**
- Modify: `src/malm/web/app.py`
- Modify: `src/malm/web/templates/index.html`
- Modify: `src/malm/web/templates/search.html`
- Modify: `src/malm/web/templates/partials/email_list.html`
- Modify: `src/malm/web/templates/email_detail.html`
- Create: `tests/test_web_unified.py`
- Reference: `src/malm/store.py` (from Task 1)

- [ ] **Step 1: Update app.py to use DocumentStore**

Replace all `DiscoveryDB` imports and calls with `DocumentStore`. The route signatures stay the same but the queries use the unified schema. Add a `doc_type` filter to the search page. The dashboard shows totals by type (emails, files, attachments) and by source (pst, filesystem).

- [ ] **Step 2: Update templates**

`search.html` — add doc_type dropdown (All / Emails / Files / Attachments).
`partials/email_list.html` — rename to `partials/doc_list.html`, add a type icon column.
`index.html` — show stats by type and source, not just folders.
`email_detail.html` — rename to `doc_detail.html`, conditionally show email fields vs file fields.

- [ ] **Step 3: Write web tests**

```python
# tests/test_web_unified.py
import subprocess, time
import pytest
import httpx

@pytest.fixture(scope="module")
def server():
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "malm.web.app:app", "--host", "127.0.0.1", "--port", "8877"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    time.sleep(3)
    yield proc
    proc.terminate()
    proc.wait(timeout=5)

def test_dashboard(server):
    r = httpx.get("http://127.0.0.1:8877/", timeout=10)
    assert r.status_code == 200
    assert "Legal Discovery" in r.text

def test_search_with_type_filter(server):
    r = httpx.get("http://127.0.0.1:8877/search?q=test&doc_type=email", timeout=10)
    assert r.status_code == 200

def test_api_stats(server):
    r = httpx.get("http://127.0.0.1:8877/api/stats", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "by_type" in data
```

- [ ] **Step 4: Run tests and commit**

Run: `uv run pytest tests/test_web_unified.py -v`

```bash
git add src/malm/web/ tests/test_web_unified.py
git commit -m "feat: unified web UI for all document types"
```

---

### Task 6: Migration Script + Wire Up

**Files:**
- Create: `scripts/migrate-to-unified.py`
- Modify: `src/malm/export.py` (use DocumentStore)
- Modify: `CLAUDE.md`
- Modify: `agents/pst-search.md`

- [ ] **Step 1: Create migration script**

`scripts/migrate-to-unified.py` reads the existing `discovery.db` and inserts all records into a new unified DB. Maps: `emails` → `documents` (doc_type='email'), `attachments` → `documents` (doc_type='attachment', parent_uuid set).

- [ ] **Step 2: Update export.py**

Replace `DiscoveryDB` with `DocumentStore`. The `export_csv` and `export_evidence_package` functions should work on any document type, not just emails.

- [ ] **Step 3: Update CLAUDE.md**

Document the new unified architecture, commands, and module structure.

- [ ] **Step 4: Update agent definition**

`agents/pst-search.md` → `agents/search.md` — works with all document types, not just PST.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/migrate-to-unified.py src/malm/export.py CLAUDE.md agents/
git commit -m "feat: migration script, export on unified store, updated docs"
```

---

### Task 7: Delete Old Code

**Files:**
- Delete: `src/malm/db.py` (replaced by store.py)
- Delete: `src/malm/discovery_db.py` (replaced by store.py)
- Delete: `src/malm/pst_extract.py` (replaced by ingest/pst.py + extract/)
- Delete: `src/malm/janitor.py` (replaced by ingest/filesystem.py)
- Delete: `src/malm/content.py` (replaced by extract/text.py)
- Update: tests that imported old modules
- Keep: `rules.py`, `embeddings.py`, `lock.py`, `export.py`, `web/`

- [ ] **Step 1: Delete old modules, update imports**
- [ ] **Step 2: Run full test suite to catch broken imports**
- [ ] **Step 3: Fix any remaining references**
- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "refactor: remove old duplicated modules"
```

---

## Execution Order

Tasks 1-4 are independent (store, extract, PST ingestor, filesystem ingestor) and can be built in sequence. Task 5 (web UI) depends on Task 1. Task 6 (migration + wiring) depends on all. Task 7 (cleanup) is last.

## Success Criteria

- [ ] One SQLite database for all document types
- [ ] `uv run pytest tests/` — all pass
- [ ] PST emails searchable alongside filesystem files
- [ ] Web UI shows emails and files in one search
- [ ] Evidence export works on any document type
- [ ] Old code deleted, no duplicate pipelines
