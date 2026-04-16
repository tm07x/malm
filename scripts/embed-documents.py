#!/usr/bin/env python3
"""Embed all documents in unified.db that don't have embeddings yet."""
import sys
import time
from pathlib import Path

from malm.embeddings import get_embeddings, serialize_f32
from malm.store import DocumentStore

DB_PATH = Path.home() / "Documents" / "Legal-Discovery" / "unified.db"
BATCH_SIZE = 32


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else str(DB_PATH)
    store = DocumentStore(db_path)

    if not store.has_vec:
        print("sqlite-vec not available, exiting.")
        return

    rows = store.conn.execute(
        "SELECT uuid, title, sender, body_preview, filename "
        "FROM documents WHERE rowid NOT IN (SELECT doc_rowid FROM documents_vec)"
    ).fetchall()

    total = len(rows)
    if total == 0:
        print("All documents already embedded.")
        return

    print(f"Embedding {total} documents...")
    embedded = 0

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        texts = []
        for r in batch:
            parts = [r["title"] or "", r["sender"] or "", r["body_preview"] or ""]
            texts.append("\n".join(parts))

        try:
            vectors = get_embeddings(texts, input_type="document")
        except Exception as e:
            if "429" in str(e):
                print("Rate limited, sleeping 10s...")
                time.sleep(10)
                vectors = get_embeddings(texts, input_type="document")
            else:
                raise

        for r, vec in zip(batch, vectors):
            store.store_embedding(r["uuid"], serialize_f32(vec))

        embedded += len(batch)
        if embedded % 100 < BATCH_SIZE:
            print(f"  {embedded}/{total}")

    print(f"Done. Embedded {embedded} documents.")
    store.close()


if __name__ == "__main__":
    main()
