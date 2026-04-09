import sqlite3
from datetime import datetime, timezone


class DiscoveryDB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self._migrate()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS emails (
                uuid TEXT PRIMARY KEY,
                pst_folder TEXT,
                subject TEXT,
                sender TEXT,
                recipients TEXT,
                cc TEXT,
                date TEXT,
                date_iso TEXT,
                has_attachments INTEGER DEFAULT 0,
                attachment_names TEXT,
                source_path TEXT NOT NULL,
                markdown_path TEXT NOT NULL,
                original_filename TEXT,
                body_preview TEXT,
                extracted_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_emails_date ON emails(date_iso);
            CREATE INDEX IF NOT EXISTS idx_emails_folder ON emails(pst_folder);
            CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender);
            CREATE INDEX IF NOT EXISTS idx_emails_subject ON emails(subject);

            CREATE TABLE IF NOT EXISTS attachments (
                uuid TEXT PRIMARY KEY,
                email_uuid TEXT NOT NULL REFERENCES emails(uuid),
                original_filename TEXT NOT NULL,
                source_path TEXT NOT NULL,
                markdown_path TEXT,
                size_bytes INTEGER,
                content_type TEXT,
                extracted_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_att_email ON attachments(email_uuid);

            CREATE TABLE IF NOT EXISTS extraction_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                pst_path TEXT NOT NULL,
                folder_filter TEXT,
                emails_extracted INTEGER DEFAULT 0,
                attachments_extracted INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running'
            );
        """)
        self.conn.commit()

    def _migrate(self):
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(emails)").fetchall()}
        new_cols = {
            "body_text": "TEXT",
            "message_id": "TEXT",
            "in_reply_to": "TEXT",
            "references_header": "TEXT",
            "thread_id": "TEXT",
        }
        for col, typ in new_cols.items():
            if col not in cols:
                self.conn.execute(f"ALTER TABLE emails ADD COLUMN {col} {typ}")
        self.conn.commit()

        if "thread_id" in new_cols and "thread_id" not in cols:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(thread_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_message_id ON emails(message_id)")
            self.conn.commit()
        else:
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(thread_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_message_id ON emails(message_id)")
            self.conn.commit()

        fts_exists = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='emails_fts'"
        ).fetchone()
        if not fts_exists:
            self.conn.executescript("""
                CREATE VIRTUAL TABLE emails_fts USING fts5(
                    subject, sender, recipients, body_text,
                    content='emails', content_rowid='rowid'
                );
                INSERT INTO emails_fts(rowid, subject, sender, recipients, body_text)
                    SELECT rowid, COALESCE(subject,''), COALESCE(sender,''), COALESCE(recipients,''), COALESCE(body_text,'')
                    FROM emails;
            """)
            self.conn.commit()

    def _sync_fts(self, uuid: str):
        row = self.conn.execute(
            "SELECT rowid, subject, sender, recipients, body_text FROM emails WHERE uuid = ?",
            (uuid,),
        ).fetchone()
        if row:
            self.conn.execute(
                "INSERT OR REPLACE INTO emails_fts(rowid, subject, sender, recipients, body_text) "
                "VALUES (?, ?, ?, ?, ?)",
                (row[0], row["subject"] or "", row["sender"] or "", row["recipients"] or "", row["body_text"] or ""),
            )

    def insert_email(self, commit: bool = True, **kwargs):
        kwargs.setdefault("body_text", None)
        kwargs.setdefault("message_id", None)
        kwargs.setdefault("in_reply_to", None)
        kwargs.setdefault("references_header", None)
        kwargs.setdefault("thread_id", None)
        self.conn.execute(
            """INSERT OR IGNORE INTO emails
               (uuid, pst_folder, subject, sender, recipients, cc, date, date_iso,
                has_attachments, attachment_names, source_path, markdown_path,
                original_filename, body_preview, extracted_at,
                body_text, message_id, in_reply_to, references_header, thread_id)
               VALUES (:uuid, :pst_folder, :subject, :sender, :recipients, :cc,
                       :date, :date_iso, :has_attachments, :attachment_names,
                       :source_path, :markdown_path, :original_filename,
                       :body_preview, :extracted_at,
                       :body_text, :message_id, :in_reply_to, :references_header, :thread_id)""",
            kwargs,
        )
        self._sync_fts(kwargs["uuid"])
        if commit:
            self.conn.commit()

    def insert_attachment(self, commit: bool = True, **kwargs):
        self.conn.execute(
            """INSERT OR IGNORE INTO attachments
               (uuid, email_uuid, original_filename, source_path, markdown_path,
                size_bytes, content_type, extracted_at)
               VALUES (:uuid, :email_uuid, :original_filename, :source_path,
                       :markdown_path, :size_bytes, :content_type, :extracted_at)""",
            kwargs,
        )
        if commit:
            self.conn.commit()

    def start_run(self, pst_path: str, folder_filter: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO extraction_runs (started_at, pst_path, folder_filter) VALUES (?, ?, ?)",
            (_now(), pst_path, folder_filter),
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, emails: int, attachments: int, errors: int, status: str = "done"):
        self.conn.execute(
            "UPDATE extraction_runs SET finished_at=?, emails_extracted=?, attachments_extracted=?, errors=?, status=? WHERE id=?",
            (_now(), emails, attachments, errors, status, run_id),
        )
        self.conn.commit()

    def search(self, query: str, folder: str | None = None, sender: str | None = None,
               after: str | None = None, before: str | None = None, limit: int = 50) -> list[dict]:
        has_filters = folder or sender or after or before
        if query and not has_filters:
            return self.search_fts(query, limit=limit)

        sql = "SELECT * FROM emails WHERE 1=1"
        params = []
        if query:
            sql += " AND (subject LIKE ? OR sender LIKE ? OR body_preview LIKE ? OR body_text LIKE ?)"
            q = f"%{query}%"
            params.extend([q, q, q, q])
        if folder:
            sql += " AND pst_folder = ?"
            params.append(folder)
        if sender:
            sql += " AND sender LIKE ?"
            params.append(f"%{sender}%")
        if after:
            sql += " AND date_iso >= ?"
            params.append(after)
        if before:
            sql += " AND date_iso <= ?"
            params.append(before)
        sql += " ORDER BY date_iso DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def search_fts(self, query: str, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT e.*, snippet(emails_fts, 3, '>>>', '<<<', '...', 64) AS snippet "
            "FROM emails_fts fts JOIN emails e ON fts.rowid = e.rowid "
            "WHERE emails_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_thread(self, thread_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM emails WHERE thread_id = ? ORDER BY date_iso ASC",
            (thread_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_email(self, uuid: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM emails WHERE uuid = ?", (uuid,)).fetchone()
        return dict(row) if row else None

    def get_attachments(self, email_uuid: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM attachments WHERE email_uuid = ?", (email_uuid,)
        ).fetchall()]

    def get_stats(self) -> dict:
        email_count = self.conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
        att_count = self.conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
        folders = [r[0] for r in self.conn.execute(
            "SELECT DISTINCT pst_folder FROM emails ORDER BY pst_folder"
        ).fetchall()]
        return {"emails": email_count, "attachments": att_count, "folders": folders}

    def folder_counts(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT pst_folder, COUNT(*) as count FROM emails GROUP BY pst_folder ORDER BY count DESC"
        ).fetchall()]

    def email_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]

    def close(self):
        self.conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
