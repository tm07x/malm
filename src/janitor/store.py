import re
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone

from janitor.models import Document

_COLUMNS = [
    "uuid", "doc_type", "parent_uuid", "source", "source_path", "stored_path",
    "markdown_path", "sha256", "filename", "extension", "size_bytes",
    "content_type", "title", "body_text", "body_preview", "sender",
    "recipients", "cc", "date_sent", "message_id", "in_reply_to",
    "references_header", "thread_id", "folder", "rule_matched", "tags",
    "status", "created_at", "updated_at", "extraction_metadata", "synthetic_text",
]

_FTS_COLUMNS = ["title", "sender", "recipients", "body_text", "filename", "folder", "tags"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DocumentStore:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.row_factory = sqlite3.Row
        self._has_vec = False
        self._init_schema()
        self._migrate()

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
                updated_at TEXT,
                extraction_metadata TEXT,
                synthetic_text TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_doc_type ON documents(doc_type);
            CREATE INDEX IF NOT EXISTS idx_parent_uuid ON documents(parent_uuid);
            CREATE INDEX IF NOT EXISTS idx_source ON documents(source);
            CREATE INDEX IF NOT EXISTS idx_sha256 ON documents(sha256);
            CREATE INDEX IF NOT EXISTS idx_thread_id ON documents(thread_id);
            CREATE INDEX IF NOT EXISTS idx_sender ON documents(sender);
            CREATE INDEX IF NOT EXISTS idx_date_sent ON documents(date_sent);
            CREATE INDEX IF NOT EXISTS idx_status ON documents(status);
            CREATE INDEX IF NOT EXISTS idx_folder ON documents(folder);
            CREATE INDEX IF NOT EXISTS idx_message_id ON documents(message_id);

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
        self.conn.commit()

        fts_exists = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='documents_fts'"
        ).fetchone()
        if not fts_exists:
            cols = ", ".join(_FTS_COLUMNS)
            self.conn.execute(
                f"CREATE VIRTUAL TABLE documents_fts USING fts5({cols})"
            )
            coalesced = ", ".join(f"COALESCE({c},'')" for c in _FTS_COLUMNS)
            self.conn.execute(
                f"INSERT INTO documents_fts(rowid, {cols}) SELECT rowid, {coalesced} FROM documents"
            )
            self.conn.commit()

        try:
            import sqlite_vec
            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
            vec_exists = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='documents_vec'"
            ).fetchone()
            if not vec_exists:
                self.conn.execute(
                    "CREATE VIRTUAL TABLE documents_vec USING vec0(doc_rowid INTEGER PRIMARY KEY, embedding float[1024])"
                )
                self.conn.commit()
            self._has_vec = True
        except (ImportError, Exception):
            self._has_vec = False

    def _migrate(self):
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(documents)").fetchall()}
        new_cols = {"extraction_metadata": "TEXT", "synthetic_text": "TEXT"}
        for col, typ in new_cols.items():
            if col not in cols:
                self.conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {typ}")
        self.conn.commit()

    @property
    def has_vec(self) -> bool:
        return self._has_vec

    def insert(self, doc: Document, commit: bool = True):
        data = asdict(doc)
        cols = ", ".join(_COLUMNS)
        placeholders = ", ".join(f":{c}" for c in _COLUMNS)
        self.conn.execute(
            f"INSERT OR REPLACE INTO documents ({cols}) VALUES ({placeholders})",
            data,
        )
        self._sync_fts(doc.uuid)
        if commit:
            self.conn.commit()

    def _sync_fts(self, uuid: str):
        row = self.conn.execute(
            "SELECT rowid, " + ", ".join(_FTS_COLUMNS) + " FROM documents WHERE uuid = ?",
            (uuid,),
        ).fetchone()
        if not row:
            return
        rowid = row[0]
        fts_cols = ", ".join(_FTS_COLUMNS)
        # Delete old FTS entry to avoid stale tokens
        self.conn.execute("DELETE FROM documents_fts WHERE rowid = ?", (rowid,))
        # Insert new FTS entry
        vals = tuple(row[c] or "" for c in _FTS_COLUMNS)
        placeholders = ", ".join(["?"] * len(_FTS_COLUMNS))
        self.conn.execute(
            f"INSERT INTO documents_fts(rowid, {fts_cols}) VALUES (?, {placeholders})",
            (rowid, *vals),
        )

    def get(self, uuid: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM documents WHERE uuid = ?", (uuid,)).fetchone()
        return dict(row) if row else None

    def get_children(self, parent_uuid: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM documents WHERE parent_uuid = ?", (parent_uuid,)
        ).fetchall()
        return [dict(r) for r in rows]

    def find_by_sha256(self, sha256: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM documents WHERE sha256 = ?", (sha256,)
        ).fetchone()
        return dict(row) if row else None

    def find_duplicate(self, doc: "Document") -> dict | None:
        """Check if a document already exists across any source.
        For emails: match by message_id. For files: match by sha256."""
        if doc.message_id:
            row = self.conn.execute(
                "SELECT * FROM documents WHERE message_id = ? AND doc_type = 'email'",
                (doc.message_id,)
            ).fetchone()
            if row:
                return dict(row)
        if doc.sha256:
            return self.find_by_sha256(doc.sha256)
        return None

    def get_thread(self, thread_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM documents WHERE thread_id = ? ORDER BY date_sent ASC",
            (thread_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def search(self, query: str = "", *, doc_type: str | None = None,
               folder: str | None = None, sender: str | None = None,
               source: str | None = None, after: str | None = None,
               before: str | None = None, limit: int = 50,
               offset: int = 0) -> list[dict]:
        has_filters = doc_type or folder or sender or source or after or before
        if query and not has_filters:
            return self.search_fts(query, limit=limit, offset=offset)

        sql = "SELECT * FROM documents WHERE 1=1"
        params: list = []
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
        sql += " ORDER BY date_sent DESC LIMIT ? OFFSET ?"
        params.append(limit)
        params.append(offset)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    @staticmethod
    def _escape_fts_query(query: str) -> str:
        cleaned = re.sub(r'[^\w\s]', '', query, flags=re.UNICODE)
        tokens = cleaned.split()
        if not tokens:
            return '""'
        return " ".join(t + "*" for t in tokens)

    def search_fts(self, query: str, *, doc_type: str | None = None,
                   limit: int = 50, offset: int = 0) -> list[dict]:
        escaped = self._escape_fts_query(query)
        sql = (
            "SELECT d.*, snippet(documents_fts, 3, '>>>', '<<<', '...', 64) AS snippet "
            "FROM documents_fts fts JOIN documents d ON fts.rowid = d.rowid "
            "WHERE documents_fts MATCH ?"
        )
        params: list = [escaped]
        if doc_type:
            sql += " AND d.doc_type = ?"
            params.append(doc_type)
        sql += " ORDER BY rank LIMIT ? OFFSET ?"
        params.append(limit)
        params.append(offset)
        try:
            rows = self.conn.execute(sql, params).fetchall()
        except Exception:
            return []
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        by_type = {}
        for row in self.conn.execute(
            "SELECT doc_type, COUNT(*) as cnt FROM documents GROUP BY doc_type"
        ).fetchall():
            by_type[row["doc_type"]] = row["cnt"]
        by_source = {}
        for row in self.conn.execute(
            "SELECT source, COUNT(*) as cnt FROM documents GROUP BY source"
        ).fetchall():
            by_source[row["source"]] = row["cnt"]
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
