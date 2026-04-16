import hashlib
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from malm.extract.email_parser import parse_eml
from malm.models import Document
from malm.store import DocumentStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(name: str, max_len: int = 80) -> str:
    clean = re.sub(r'[^\w\s\-.]', '', name).strip()
    clean = re.sub(r'\s+', '_', clean)
    return clean[:max_len] if clean else "untitled"


def _email_to_markdown(parsed: dict, email_uuid: str, att_records: list[dict]) -> str:
    lines = [
        f"# {parsed['subject']}",
        "",
        "## Metadata",
        f"- **UUID:** `{email_uuid}`",
        f"- **From:** {parsed['sender']}",
        f"- **To:** {parsed['to']}",
    ]
    if parsed["cc"]:
        lines.append(f"- **CC:** {parsed['cc']}")
    lines.append(f"- **Date:** {parsed['date_raw']}")
    if parsed.get("message_id"):
        lines.append(f"- **Message-ID:** `{parsed['message_id']}`")
    if parsed.get("thread_id"):
        lines.append(f"- **Thread-ID:** `{parsed['thread_id']}`")
    lines.append("")

    if att_records:
        lines.append("## Attachments")
        for att in att_records:
            lines.append(
                f"- [{att['filename']}]({att['source_path']}) "
                f"({att['content_type']}, {att['size_bytes']} bytes)"
            )
        lines.append("")

    lines.extend([
        "## Body",
        "",
        parsed["body"] or "(empty)",
        "",
    ])
    return "\n".join(lines)


class PstIngestor:
    def __init__(self, store: DocumentStore, source_dir: Path, md_dir: Path):
        self.store = store
        self.source_dir = source_dir
        self.md_dir = md_dir

    def ingest_pst(
        self,
        pst_path: str,
        folder_filter: str | None = None,
        limit: int | None = None,
    ) -> dict:
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.md_dir.mkdir(parents=True, exist_ok=True)

        abs_pst = str(Path(pst_path).resolve())
        pst_hash = hashlib.sha256(abs_pst.encode()).hexdigest()[:12]
        cache_dir = self.source_dir.parent / ".eml-cache" / pst_hash
        cache_dir.mkdir(parents=True, exist_ok=True)

        marker = cache_dir / ".extraction-complete"
        if not marker.exists():
            cmd = ["readpst", "-e", "-8", "-q", "-o", str(cache_dir), pst_path]
            subprocess.run(cmd, check=True, capture_output=True, timeout=3600)
            marker.write_text(_now())

        total_docs = 0
        total_errors = 0

        eml_files = sorted(cache_dir.rglob("*.eml"))
        processed = 0
        for eml_path in eml_files:
            if limit and processed >= limit:
                break

            rel = eml_path.relative_to(cache_dir)
            raw_folder = str(rel.parent)
            pst_folder = re.sub(r'^Outlook Data File/?', '', raw_folder) or "Root"

            if folder_filter and folder_filter not in pst_folder:
                continue

            result = self.ingest_eml_dir(eml_path.parent, pst_folder)
            total_docs += result["docs_processed"]
            total_errors += result["errors"]
            processed += result["docs_processed"]

        return {"docs_processed": total_docs, "errors": total_errors}

    def ingest_eml_dir(self, eml_dir: Path, pst_folder: str = "Root") -> dict:
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.md_dir.mkdir(parents=True, exist_ok=True)

        docs_processed = 0
        errors = 0

        for eml_path in sorted(eml_dir.glob("*.eml")):
            try:
                self._process_eml(eml_path, pst_folder)
                docs_processed += 1
            except Exception as e:
                errors += 1

        return {"docs_processed": docs_processed, "errors": errors}

    def _process_eml(self, eml_path: Path, pst_folder: str) -> None:
        parsed = parse_eml(eml_path)
        eid = uuid.uuid4().hex[:12]
        safe_subj = _sanitize(parsed["subject"], 60)
        email_stem = f"{eid}_{safe_subj}"

        src_dest = self.source_dir / f"{email_stem}.eml"
        shutil.copy2(str(eml_path), str(src_dest))

        att_records = []
        for att in parsed["attachments"]:
            aid = uuid.uuid4().hex[:12]
            safe_att = _sanitize(att["filename"])
            ext = Path(att["filename"]).suffix or ""
            att_dest = self.source_dir / f"{aid}_{safe_att}{ext if ext not in safe_att else ''}"
            if att["payload"]:
                att_dest.write_bytes(att["payload"])

            att_records.append({
                "uuid": aid,
                "email_uuid": eid,
                "filename": att["filename"],
                "source_path": str(att_dest),
                "size_bytes": att["size"],
                "content_type": att["content_type"],
            })

        md_content = _email_to_markdown(parsed, eid, att_records)
        md_dest = self.md_dir / f"{email_stem}.md"
        md_dest.write_text(md_content, encoding="utf-8")

        email_doc = Document(
            uuid=eid,
            doc_type="email",
            source="pst",
            created_at=_now(),
            source_path=str(src_dest),
            markdown_path=str(md_dest),
            filename=eml_path.name,
            title=parsed["subject"],
            body_text=parsed["body"],
            body_preview=parsed["body_preview"],
            sender=parsed["sender"],
            recipients=parsed["to"],
            cc=parsed["cc"],
            date_sent=parsed["date_iso"] or parsed["date_raw"],
            message_id=parsed["message_id"],
            in_reply_to=parsed["in_reply_to"],
            references_header=parsed["references_header"],
            thread_id=parsed["thread_id"],
            folder=pst_folder,
        )
        self.store.insert(email_doc, commit=False)

        for att_rec in att_records:
            att_doc = Document(
                uuid=att_rec["uuid"],
                doc_type="attachment",
                source="pst",
                created_at=_now(),
                parent_uuid=eid,
                source_path=att_rec["source_path"],
                filename=att_rec["filename"],
                size_bytes=att_rec["size_bytes"],
                content_type=att_rec["content_type"],
                folder=pst_folder,
            )
            self.store.insert(att_doc, commit=False)

        self.store.conn.commit()
