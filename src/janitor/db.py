import json
import sqlite3
from datetime import datetime, timezone

import sqlite_vec


class JanitorDB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self._migrate()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS files (
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
            CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
            CREATE INDEX IF NOT EXISTS idx_files_source ON files(source_path);
        """)
        self.conn.commit()

    def _migrate(self):
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(files)").fetchall()}
        new_cols = {
            "sheet_names": "TEXT",
            "headers_json": "TEXT",
            "content_text": "TEXT",
        }
        for col, typ in new_cols.items():
            if col not in cols:
                self.conn.execute(f"ALTER TABLE files ADD COLUMN {col} {typ}")
        self.conn.commit()

        # FTS index for content search
        fts_exists = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='files_fts'"
        ).fetchone()
        if not fts_exists:
            self.conn.executescript("""
                CREATE VIRTUAL TABLE files_fts USING fts5(
                    filename, sheet_names, headers_json, content_text,
                    content='files', content_rowid='id'
                );
                INSERT INTO files_fts(rowid, filename, sheet_names, headers_json, content_text)
                    SELECT id, filename, COALESCE(sheet_names,''), COALESCE(headers_json,''), COALESCE(content_text,'')
                    FROM files;
            """)
            self.conn.commit()

        # Vector table for semantic search
        vec_exists = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='files_vec'"
        ).fetchone()
        if not vec_exists:
            self.conn.execute("CREATE VIRTUAL TABLE files_vec USING vec0(file_id INTEGER PRIMARY KEY, embedding float[1024])")
            self.conn.commit()

    def execute(self, sql, params=()):
        return self.conn.execute(sql, params)

    def discover_file(self, filename: str, extension: str, size_bytes: int, source_path: str):
        try:
            self.conn.execute(
                "INSERT INTO files (filename, extension, size_bytes, source_path, discovered_at) VALUES (?, ?, ?, ?, ?)",
                (filename, extension, size_bytes, source_path, _now()),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass  # already discovered

    def get_file_by_source(self, source_path: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM files WHERE source_path = ?", (source_path,)
        ).fetchone()

    def get_discovered_files(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM files WHERE status = 'discovered'"
        ).fetchall()

    def store_content(self, file_id: int, content: dict):
        sheet_names = ", ".join(content.get("sheet_names", []))
        headers_json = json.dumps(content.get("headers", {}), ensure_ascii=False)
        content_text = "\n".join(content.get("cell_values", []))
        self.conn.execute(
            "UPDATE files SET sheet_names = ?, headers_json = ?, content_text = ? WHERE id = ?",
            (sheet_names, headers_json, content_text, file_id),
        )
        # Keep FTS in sync
        self.conn.execute(
            "INSERT INTO files_fts(rowid, filename, sheet_names, headers_json, content_text) "
            "SELECT id, filename, COALESCE(sheet_names,''), COALESCE(headers_json,''), COALESCE(content_text,'') "
            "FROM files WHERE id = ?",
            (file_id,),
        )
        self.conn.commit()

    def store_embedding(self, file_id: int, embedding: bytes):
        # Upsert: delete then insert since vec0 doesn't support ON CONFLICT
        self.conn.execute("DELETE FROM files_vec WHERE file_id = ?", (file_id,))
        self.conn.execute(
            "INSERT INTO files_vec (file_id, embedding) VALUES (?, ?)",
            (file_id, embedding),
        )
        self.conn.commit()

    def search_fts(self, query: str, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT f.id, f.filename, f.extension, f.dest_path, f.rule_matched, f.sheet_names, "
            "snippet(files_fts, 3, '>>>', '<<<', '...', 32) AS snippet "
            "FROM files_fts fts JOIN files f ON fts.rowid = f.id "
            "WHERE files_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()

    def search_vec(self, query_embedding: bytes, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT f.id, f.filename, f.extension, f.dest_path, f.rule_matched, f.sheet_names, "
            "v.distance "
            "FROM files_vec v JOIN files f ON v.file_id = f.id "
            "WHERE v.embedding MATCH ? AND k = ? "
            "ORDER BY v.distance",
            (query_embedding, limit),
        ).fetchall()

    def search(self, query: str, limit: int = 20) -> list[sqlite3.Row]:
        """FTS-only search (no embedding needed)."""
        return self.search_fts(query, limit)

    def hybrid_search(self, query: str, query_embedding: bytes, limit: int = 20, fts_weight: float = 0.3, vec_weight: float = 0.7) -> list[dict]:
        fts_results = self.search_fts(query, limit=limit * 2)
        vec_results = self.search_vec(query_embedding, limit=limit * 2)

        # Reciprocal rank fusion
        scores: dict[int, dict] = {}
        k = 60  # RRF constant

        for rank, row in enumerate(fts_results):
            fid = row["id"]
            scores[fid] = {
                "id": fid, "filename": row["filename"], "extension": row["extension"],
                "dest_path": row["dest_path"], "rule_matched": row["rule_matched"],
                "sheet_names": row["sheet_names"], "snippet": row["snippet"],
                "score": fts_weight / (k + rank + 1),
            }

        for rank, row in enumerate(vec_results):
            fid = row["id"]
            rrf = vec_weight / (k + rank + 1)
            if fid in scores:
                scores[fid]["score"] += rrf
            else:
                scores[fid] = {
                    "id": fid, "filename": row["filename"], "extension": row["extension"],
                    "dest_path": row["dest_path"], "rule_matched": row["rule_matched"],
                    "sheet_names": row["sheet_names"], "snippet": None,
                    "score": rrf,
                }

        ranked = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
        return ranked[:limit]

    def mark_moved(self, file_id: int, dest_path: str, rule_matched: str):
        self.conn.execute(
            "UPDATE files SET status = 'moved', dest_path = ?, rule_matched = ?, moved_at = ? WHERE id = ?",
            (dest_path, rule_matched, _now(), file_id),
        )
        self.conn.commit()

    def mark_error(self, file_id: int, reason: str):
        self.conn.execute(
            "UPDATE files SET status = 'error', rule_matched = ? WHERE id = ?",
            (reason, file_id),
        )
        self.conn.commit()

    def get_status_counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM files GROUP BY status"
        ).fetchall()
        return {row["status"]: row["cnt"] for row in rows}

    def close(self):
        self.conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
