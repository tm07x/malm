from dataclasses import dataclass


@dataclass
class Document:
    uuid: str
    doc_type: str  # 'email', 'file', 'attachment'
    source: str    # 'pst', 'filesystem', 'filedrop'
    created_at: str

    parent_uuid: str | None = None
    source_path: str | None = None
    stored_path: str | None = None
    markdown_path: str | None = None
    sha256: str | None = None
    filename: str | None = None
    extension: str | None = None
    size_bytes: int | None = None
    content_type: str | None = None

    title: str | None = None
    body_text: str | None = None
    body_preview: str | None = None

    sender: str | None = None
    recipients: str | None = None
    cc: str | None = None
    date_sent: str | None = None
    message_id: str | None = None
    in_reply_to: str | None = None
    references_header: str | None = None
    thread_id: str | None = None
    folder: str | None = None

    rule_matched: str | None = None
    tags: str | None = None
    status: str = "indexed"
    updated_at: str | None = None
