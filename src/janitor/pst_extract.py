import email
import hashlib
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from email.header import decode_header as _decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path

from janitor.discovery_db import DiscoveryDB

PST_FILE = os.environ.get(
    "DISCOVERY_PST_PATH",
    str(Path.home() / "Documents" / "Tvistesak - Mai " / "Dump" / "Backups" / "lasse@reinconsult.no.pst"),
)
DISCOVERY_ROOT = Path.home() / "Documents" / "Legal-Discovery"
SOURCE_DIR = DISCOVERY_ROOT / "source-doc"
MD_DIR = DISCOVERY_ROOT / "MD"
DB_PATH = DISCOVERY_ROOT / "discovery.db"
# Persistent cache of readpst output so the 6GB PST is only extracted once
EML_CACHE_DIR = DISCOVERY_ROOT / ".eml-cache"


def _ensure_dirs():
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    MD_DIR.mkdir(parents=True, exist_ok=True)
    EML_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_eml_cache(pst_path: str) -> Path:
    """Extract PST to persistent cache if not already done. Returns cache dir."""
    abs_pst = str(Path(pst_path).resolve())
    pst_hash = hashlib.sha256(abs_pst.encode()).hexdigest()[:12]
    cache_dir = EML_CACHE_DIR / pst_hash
    cache_dir.mkdir(parents=True, exist_ok=True)
    marker = cache_dir / ".extraction-complete"
    if marker.exists():
        return cache_dir
    source_file = cache_dir / ".pst-source"
    source_file.write_text(abs_pst)
    print(f"Extracting PST to cache (first run, this takes a while for large files)...")
    cmd = ["readpst", "-e", "-8", "-q", "-o", str(cache_dir), pst_path]
    subprocess.run(cmd, check=True, capture_output=True, timeout=3600)
    marker.write_text(_now())
    return cache_dir


def _sanitize(name: str, max_len: int = 80) -> str:
    clean = re.sub(r'[^\w\s\-.]', '', name).strip()
    clean = re.sub(r'\s+', '_', clean)
    return clean[:max_len] if clean else "untitled"


def _decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for chunk, charset in _decode_header(value):
        if isinstance(chunk, bytes):
            enc = charset or "utf-8"
            try:
                parts.append(chunk.decode(enc, errors="replace"))
            except (LookupError, UnicodeDecodeError):
                parts.append(chunk.decode("utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return " ".join(parts)


def _decode_payload(payload: bytes, charset: str) -> str:
    for enc in (charset, "windows-1252", "iso-8859-1", "utf-8"):
        try:
            return payload.decode(enc, errors="replace")
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def _parse_eml(eml_path: Path) -> dict:
    raw = eml_path.read_bytes()
    msg = email.message_from_bytes(raw)

    subject = _decode_mime_header(msg.get("Subject")) or "(no subject)"
    sender = _decode_mime_header(msg.get("From"))
    to = _decode_mime_header(msg.get("To"))
    cc = _decode_mime_header(msg.get("Cc"))
    date_raw = msg.get("Date", "")

    date_iso = ""
    if date_raw:
        try:
            dt = parsedate_to_datetime(date_raw)
            date_iso = dt.isoformat()
        except Exception:
            date_iso = ""

    # Extract body
    body_parts = []
    attachments = []
    for part in msg.walk():
        ct = part.get_content_type()
        disp = str(part.get("Content-Disposition", ""))
        filename = part.get_filename()

        try:
            payload = part.get_payload(decode=True)
        except Exception:
            # Handle unknown encodings (e.g. "unknown-8bit" from Outlook)
            raw_payload = part.get_payload(decode=False)
            payload = raw_payload.encode("utf-8", errors="replace") if isinstance(raw_payload, str) else raw_payload

        if filename or "attachment" in disp:
            attachments.append({
                "filename": _decode_mime_header(filename) if filename else "unnamed",
                "content_type": ct,
                "size": len(payload) if payload else 0,
                "payload": payload,
            })
        elif ct == "text/plain":
            if payload:
                charset = part.get_content_charset() or "utf-8"
                body_parts.append(_decode_payload(payload, charset))
        elif ct == "text/html" and not body_parts:
            if payload:
                charset = part.get_content_charset() or "utf-8"
                html = _decode_payload(payload, charset)
                text = re.sub(r'<[^>]+>', ' ', html)
                text = re.sub(r'&nbsp;', ' ', text)
                text = re.sub(r'&[a-z]+;', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                body_parts.append(text)

    body = "\n\n".join(body_parts)

    message_id = _decode_mime_header(msg.get("Message-ID"))
    in_reply_to = _decode_mime_header(msg.get("In-Reply-To"))
    references_header = _decode_mime_header(msg.get("References"))

    def _strip_angles(val: str) -> str:
        return val.strip().strip("<>").strip()

    if references_header:
        first_ref = references_header.split()[0]
        thread_id = _strip_angles(first_ref)
    elif in_reply_to:
        thread_id = _strip_angles(in_reply_to)
    elif message_id:
        thread_id = _strip_angles(message_id)
    else:
        thread_id = ""

    return {
        "subject": subject,
        "sender": sender,
        "to": to,
        "cc": cc,
        "date_raw": date_raw,
        "date_iso": date_iso,
        "body": body,
        "body_preview": body[:500] if body else "",
        "attachments": attachments,
        "message_id": message_id,
        "in_reply_to": in_reply_to,
        "references_header": references_header,
        "thread_id": thread_id,
    }


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
    if parsed.get("in_reply_to"):
        lines.append(f"- **In-Reply-To:** `{parsed['in_reply_to']}`")
    if parsed.get("thread_id"):
        lines.append(f"- **Thread-ID:** `{parsed['thread_id']}`")
    lines.append("")

    if att_records:
        lines.append("## Attachments")
        for att in att_records:
            lines.append(f"- [{att['original_filename']}]({att['source_path']}) ({att['content_type']}, {att['size_bytes']} bytes)")
        lines.append("")

    lines.extend([
        "## Body",
        "",
        parsed["body"] or "(empty)",
        "",
    ])
    return "\n".join(lines)


def extract_pst(
    folder_filter: str | None = None,
    limit: int | None = None,
    pst_path: str = PST_FILE,
) -> dict:
    _ensure_dirs()
    db = DiscoveryDB(str(DB_PATH))
    run_id = db.start_run(pst_path, folder_filter)

    email_count = 0
    att_count = 0
    error_count = 0
    run_status = "error"

    try:
        cache_dir = _ensure_eml_cache(pst_path)
        eml_files = sorted(cache_dir.rglob("*.eml"))

        for eml_path in eml_files:
            if limit and email_count >= limit:
                break

            # Determine PST folder from directory structure
            # readpst nests under "Outlook Data File/<folder>" — strip the prefix
            rel = eml_path.relative_to(cache_dir)
            raw_folder = str(rel.parent)
            pst_folder = re.sub(r'^Outlook Data File/?', '', raw_folder) or "Root"

            if folder_filter and folder_filter not in pst_folder:
                continue

            try:
                parsed = _parse_eml(eml_path)
                eid = uuid.uuid4().hex[:12]
                safe_subj = _sanitize(parsed["subject"], 60)
                email_stem = f"{eid}_{safe_subj}"

                # Copy source .eml
                src_dest = SOURCE_DIR / f"{email_stem}.eml"
                shutil.copy2(str(eml_path), str(src_dest))

                # Prepare attachment records (write files but defer DB inserts)
                att_records = []
                for att in parsed["attachments"]:
                    aid = uuid.uuid4().hex[:12]
                    safe_att = _sanitize(att["filename"])
                    ext = Path(att["filename"]).suffix or ""
                    att_dest = SOURCE_DIR / f"{aid}_{safe_att}{ext if ext not in safe_att else ''}"
                    if att["payload"]:
                        att_dest.write_bytes(att["payload"])

                    att_records.append({
                        "uuid": aid,
                        "email_uuid": eid,
                        "original_filename": att["filename"],
                        "source_path": str(att_dest),
                        "markdown_path": None,
                        "size_bytes": att["size"],
                        "content_type": att["content_type"],
                        "extracted_at": _now(),
                    })

                # Write markdown
                md_content = _email_to_markdown(parsed, eid, att_records)
                md_dest = MD_DIR / f"{email_stem}.md"
                md_dest.write_text(md_content, encoding="utf-8")

                # Insert email + attachments in a single transaction
                try:
                    db.insert_email(
                        commit=False,
                        uuid=eid,
                        pst_folder=pst_folder,
                        subject=parsed["subject"],
                        sender=parsed["sender"],
                        recipients=parsed["to"],
                        cc=parsed["cc"],
                        date=parsed["date_raw"],
                        date_iso=parsed["date_iso"],
                        has_attachments=1 if parsed["attachments"] else 0,
                        attachment_names=", ".join(a["filename"] for a in parsed["attachments"]) or None,
                        source_path=str(src_dest),
                        markdown_path=str(md_dest),
                        original_filename=eml_path.name,
                        body_preview=parsed["body_preview"],
                        body_text=parsed["body"],
                        message_id=parsed["message_id"],
                        in_reply_to=parsed["in_reply_to"],
                        references_header=parsed["references_header"],
                        thread_id=parsed["thread_id"],
                        extracted_at=_now(),
                    )
                    for att_rec in att_records:
                        db.insert_attachment(commit=False, **att_rec)
                    db.conn.commit()
                except Exception:
                    db.conn.rollback()
                    raise
                email_count += 1
                att_count += len(att_records)

            except Exception as e:
                error_count += 1
                print(f"Error processing {eml_path.name}: {e}")

    except subprocess.TimeoutExpired:
        error_count += 1
        run_status = "error"
        print("readpst timed out")
    except subprocess.CalledProcessError as e:
        error_count += 1
        run_status = "error"
        print(f"readpst failed: {e.stderr.decode() if e.stderr else e}")
    else:
        run_status = "partial" if error_count > 0 else "done"
    finally:
        db.finish_run(run_id, email_count, att_count, error_count, status=run_status)
        db.close()

    return {
        "emails_extracted": email_count,
        "attachments_extracted": att_count,
        "errors": error_count,
        "source_dir": str(SOURCE_DIR),
        "markdown_dir": str(MD_DIR),
        "db_path": str(DB_PATH),
    }


def search_discovery(query: str = "", folder: str | None = None, sender: str | None = None,
                     after: str | None = None, before: str | None = None, limit: int = 50) -> list[dict]:
    db = DiscoveryDB(str(DB_PATH))
    results = db.search(query, folder, sender, after, before, limit)
    db.close()
    return results


def get_email_detail(email_uuid: str) -> dict | None:
    db = DiscoveryDB(str(DB_PATH))
    email_rec = db.get_email(email_uuid)
    if email_rec:
        email_rec["attachments"] = db.get_attachments(email_uuid)
    db.close()
    return email_rec


def get_discovery_stats() -> dict:
    db = DiscoveryDB(str(DB_PATH))
    stats = db.get_stats()
    folder_counts = db.folder_counts()
    stats["folder_counts"] = folder_counts
    db.close()
    return stats


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
