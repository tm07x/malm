import sqlite3
from datetime import datetime, timezone


class JanitorDB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

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
