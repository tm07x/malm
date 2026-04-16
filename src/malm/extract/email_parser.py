import email
import re
from email.header import decode_header as _decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path


def _unfold_header(value: str) -> str:
    """Remove RFC 2822 header folding (newline + whitespace)."""
    return re.sub(r'\r?\n[\t ]+', ' ', value).strip()


def _decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    value = _unfold_header(value)
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


def parse_eml(eml_path: Path) -> dict:
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

    body_parts = []
    attachments = []
    for part in msg.walk():
        ct = part.get_content_type()
        disp = str(part.get("Content-Disposition", ""))
        filename = part.get_filename()

        try:
            payload = part.get_payload(decode=True)
        except Exception:
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
