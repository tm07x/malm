import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from janitor.extract.hasher import sha256_file
from janitor.extract.text import extract_text
from janitor.models import Document
from janitor.rules import match_rule
from janitor.store import DocumentStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FilesystemIngestor:
    def __init__(self, store: DocumentStore, rules: dict):
        self.store = store
        self.rules = rules

    def scan(self, dry_run: bool = True) -> dict:
        source = Path(self.rules["source"]).expanduser()
        discovered = 0
        moved = 0
        skipped = 0
        errors = 0

        run_id = self.store.start_run("filesystem", str(source))

        for entry in sorted(source.iterdir()):
            if entry.name.startswith(".") or entry.is_dir():
                continue

            discovered += 1

            try:
                file_hash = sha256_file(entry)
            except Exception:
                errors += 1
                continue

            if self.store.find_by_sha256(file_hash):
                skipped += 1
                continue

            dest_dir, rule_id = match_rule(entry.name, self.rules)
            if dest_dir is None:
                skipped += 1
                continue

            body_text = None
            try:
                result = extract_text(entry)
                if result and result.get("body_text"):
                    body_text = result["body_text"]
            except Exception:
                pass

            ext = entry.suffix.lower() if entry.suffix else None
            stat = entry.stat()

            doc = Document(
                uuid=str(uuid.uuid4()),
                doc_type="file",
                source="filesystem",
                created_at=_now(),
                source_path=str(entry),
                sha256=file_hash,
                filename=entry.name,
                extension=ext,
                size_bytes=stat.st_size,
                folder=dest_dir,
                rule_matched=rule_id,
                body_text=body_text,
            )

            self.store.insert(doc)

            if not dry_run:
                try:
                    dest_path = Path(dest_dir).expanduser() / entry.name
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(entry), str(dest_path))
                    moved += 1
                except Exception:
                    errors += 1

        self.store.finish_run(run_id, discovered, errors)
        return {"discovered": discovered, "moved": moved, "skipped": skipped, "errors": errors}
