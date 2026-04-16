#!/usr/bin/env python3
"""Migrate discovery.db to unified.db."""

import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from malm.models import Document
from malm.store import DocumentStore

DISCOVERY_DB = os.path.expanduser("~/Documents/Legal-Discovery/discovery.db")
UNIFIED_DB = os.path.expanduser("~/Documents/Legal-Discovery/unified.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate(discovery_path: str = DISCOVERY_DB, unified_path: str = UNIFIED_DB):
    if not os.path.exists(discovery_path):
        print(f"ERROR: {discovery_path} not found")
        sys.exit(1)

    old = sqlite3.connect(discovery_path)
    old.row_factory = sqlite3.Row

    store = DocumentStore(unified_path)
    now = _now()

    email_count = 0
    email_errors = 0
    att_count = 0
    att_errors = 0

    # Migrate emails
    rows = old.execute("SELECT * FROM emails").fetchall()
    for row in rows:
        r = dict(row)
        try:
            doc = Document(
                uuid=r["uuid"],
                doc_type="email",
                source="pst",
                created_at=r.get("extracted_at") or now,
                title=r.get("subject"),
                body_text=r.get("body_text"),
                body_preview=r.get("body_preview"),
                sender=r.get("sender"),
                recipients=r.get("recipients"),
                cc=r.get("cc"),
                date_sent=r.get("date_iso"),
                message_id=r.get("message_id"),
                in_reply_to=r.get("in_reply_to"),
                references_header=r.get("references_header"),
                thread_id=r.get("thread_id"),
                folder=r.get("pst_folder"),
                source_path=r.get("source_path"),
                markdown_path=r.get("markdown_path"),
                filename=r.get("original_filename"),
            )
            store.insert(doc, commit=False)
            email_count += 1
        except Exception as e:
            email_errors += 1
            print(f"  email error {r.get('uuid')}: {e}")

    store.conn.commit()
    print(f"Emails migrated: {email_count} (errors: {email_errors})")

    # Migrate attachments
    rows = old.execute("SELECT * FROM attachments").fetchall()
    for row in rows:
        r = dict(row)
        try:
            doc = Document(
                uuid=r["uuid"],
                doc_type="attachment",
                source="pst",
                created_at=r.get("extracted_at") or now,
                parent_uuid=r.get("email_uuid"),
                filename=r.get("original_filename"),
                title=r.get("original_filename"),
                source_path=r.get("source_path"),
                markdown_path=r.get("markdown_path"),
                content_type=r.get("content_type"),
                size_bytes=r.get("size_bytes"),
            )
            store.insert(doc, commit=False)
            att_count += 1
        except Exception as e:
            att_errors += 1
            print(f"  attachment error {r.get('uuid')}: {e}")

    store.conn.commit()
    print(f"Attachments migrated: {att_count} (errors: {att_errors})")
    print(f"Total: {email_count + att_count} documents in unified.db")

    old.close()
    store.close()


if __name__ == "__main__":
    migrate()
