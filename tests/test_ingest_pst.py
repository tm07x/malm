import tempfile
from email.message import EmailMessage
from pathlib import Path

import pytest

from malm.ingest.pst import PstIngestor, _sanitize
from malm.store import DocumentStore


def _make_eml(
    to="recipient@example.com",
    sender="sender@example.com",
    subject="Test Subject",
    body="Hello, this is the body.",
    attachments=None,
) -> bytes:
    msg = EmailMessage()
    msg["To"] = to
    msg["From"] = sender
    msg["Subject"] = subject
    msg["Date"] = "Mon, 01 Jan 2024 10:00:00 +0000"
    msg["Message-ID"] = "<test-msg-001@example.com>"
    msg.set_content(body)

    for att in (attachments or []):
        msg.add_attachment(
            att["data"],
            maintype=att.get("maintype", "application"),
            subtype=att.get("subtype", "octet-stream"),
            filename=att["filename"],
        )
    return msg.as_bytes()


@pytest.fixture
def workspace(tmp_path):
    source_dir = tmp_path / "source"
    md_dir = tmp_path / "md"
    db_path = str(tmp_path / "test.db")
    store = DocumentStore(db_path)
    ingestor = PstIngestor(store, source_dir, md_dir)
    return {
        "tmp_path": tmp_path,
        "source_dir": source_dir,
        "md_dir": md_dir,
        "store": store,
        "ingestor": ingestor,
    }


class TestPstIngestorBasic:
    def test_ingest_single_eml(self, workspace):
        eml_dir = workspace["tmp_path"] / "emls"
        eml_dir.mkdir()
        (eml_dir / "test.eml").write_bytes(_make_eml())

        result = workspace["ingestor"].ingest_eml_dir(eml_dir, pst_folder="Inbox")

        assert result["docs_processed"] == 1
        assert result["errors"] == 0

        docs = workspace["store"].search(doc_type="email")
        assert len(docs) == 1
        doc = docs[0]
        assert doc["doc_type"] == "email"
        assert doc["source"] == "pst"
        assert doc["sender"] == "sender@example.com"
        assert doc["title"] == "Test Subject"
        assert doc["folder"] == "Inbox"
        assert doc["body_text"] == "Hello, this is the body.\n"

        md_files = list(workspace["md_dir"].glob("*.md"))
        assert len(md_files) == 1
        md_content = md_files[0].read_text()
        assert "# Test Subject" in md_content
        assert "sender@example.com" in md_content

    def test_ingest_eml_with_attachment(self, workspace):
        eml_dir = workspace["tmp_path"] / "emls"
        eml_dir.mkdir()
        att_data = b"PDF content here"
        eml_bytes = _make_eml(
            subject="Email with attachment",
            attachments=[{"filename": "report.pdf", "data": att_data, "maintype": "application", "subtype": "pdf"}],
        )
        (eml_dir / "att.eml").write_bytes(eml_bytes)

        result = workspace["ingestor"].ingest_eml_dir(eml_dir)

        assert result["docs_processed"] == 1
        assert result["errors"] == 0

        emails = workspace["store"].search(doc_type="email")
        assert len(emails) == 1
        email_uuid = emails[0]["uuid"]

        attachments = workspace["store"].get_children(email_uuid)
        assert len(attachments) == 1
        att = attachments[0]
        assert att["doc_type"] == "attachment"
        assert att["filename"] == "report.pdf"
        assert att["parent_uuid"] == email_uuid

        att_files = [f for f in workspace["source_dir"].iterdir() if "report" in f.name]
        assert len(att_files) == 1
        assert att_files[0].read_bytes() == att_data

    def test_ingest_multiple_emls(self, workspace):
        eml_dir = workspace["tmp_path"] / "emls"
        eml_dir.mkdir()
        for i in range(3):
            (eml_dir / f"mail{i}.eml").write_bytes(
                _make_eml(subject=f"Email number {i}", sender=f"user{i}@test.com")
            )

        result = workspace["ingestor"].ingest_eml_dir(eml_dir)

        assert result["docs_processed"] == 3
        assert result["errors"] == 0

        docs = workspace["store"].search(doc_type="email")
        assert len(docs) == 3

    def test_ingest_bad_eml_counts_error(self, workspace):
        eml_dir = workspace["tmp_path"] / "emls"
        eml_dir.mkdir()
        (eml_dir / "good.eml").write_bytes(_make_eml())
        (eml_dir / "bad.eml").write_bytes(b"")  # empty/invalid

        result = workspace["ingestor"].ingest_eml_dir(eml_dir)

        assert result["docs_processed"] + result["errors"] == 2

    def test_markdown_contains_attachment_link(self, workspace):
        eml_dir = workspace["tmp_path"] / "emls"
        eml_dir.mkdir()
        eml_bytes = _make_eml(
            subject="With doc",
            attachments=[{"filename": "notes.txt", "data": b"some notes"}],
        )
        (eml_dir / "withatt.eml").write_bytes(eml_bytes)

        workspace["ingestor"].ingest_eml_dir(eml_dir)

        md_files = list(workspace["md_dir"].glob("*.md"))
        assert len(md_files) == 1
        md = md_files[0].read_text()
        assert "## Attachments" in md
        assert "notes.txt" in md

    def test_source_eml_copied(self, workspace):
        eml_dir = workspace["tmp_path"] / "emls"
        eml_dir.mkdir()
        (eml_dir / "copy.eml").write_bytes(_make_eml())

        workspace["ingestor"].ingest_eml_dir(eml_dir)

        eml_copies = list(workspace["source_dir"].glob("*.eml"))
        assert len(eml_copies) == 1


class TestSanitize:
    def test_basic(self):
        assert _sanitize("Hello World") == "Hello_World"

    def test_special_chars(self):
        result = _sanitize("RE: Brev fra konkursboet!")
        assert "/" not in result
        assert ":" not in result

    def test_max_length(self):
        assert len(_sanitize("A" * 200, max_len=80)) == 80

    def test_empty(self):
        assert _sanitize("") == "untitled"
