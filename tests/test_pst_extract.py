import sqlite3
import tempfile
from pathlib import Path

import pytest

from janitor.discovery_db import DiscoveryDB
from janitor.pst_extract import (
    _decode_mime_header,
    _decode_payload,
    _sanitize,
)


class TestDecodePayload:
    def test_utf8(self):
        text = "Hei, dette er en test med norske tegn: æøå ÆØÅ"
        assert _decode_payload(text.encode("utf-8"), "utf-8") == text

    def test_windows_1252(self):
        text = "Brev fra konkursboet – påkrav og innsigelse"
        encoded = text.encode("windows-1252")
        result = _decode_payload(encoded, "windows-1252")
        assert "konkursboet" in result
        assert "påkrav" in result

    def test_iso_8859_1(self):
        text = "Oversendelse av brev"
        encoded = text.encode("iso-8859-1")
        assert _decode_payload(encoded, "iso-8859-1") == text

    def test_unknown_charset_falls_back(self):
        text = "Hei på deg"
        encoded = text.encode("windows-1252")
        result = _decode_payload(encoded, "unknown-8bit")
        assert "Hei" in result

    def test_empty_payload(self):
        assert _decode_payload(b"", "utf-8") == ""


class TestDecodeMimeHeader:
    def test_plain_ascii(self):
        assert _decode_mime_header("Hello World") == "Hello World"

    def test_utf8_encoded(self):
        # =?utf-8?B?...?= format
        encoded = "=?utf-8?B?SMOmcg==?="
        result = _decode_mime_header(encoded)
        assert "Hær" in result

    def test_unknown_8bit_charset(self):
        # Should not raise
        encoded = "=?unknown-8bit?Q?Hei?="
        result = _decode_mime_header(encoded)
        assert "Hei" in result

    def test_none_input(self):
        assert _decode_mime_header(None) == ""

    def test_empty_input(self):
        assert _decode_mime_header("") == ""


class TestSanitize:
    def test_basic(self):
        assert _sanitize("Hello World") == "Hello_World"

    def test_special_chars(self):
        result = _sanitize("RE: Brev fra konkursboet!")
        assert "/" not in result
        assert ":" not in result

    def test_max_length(self):
        long = "A" * 200
        assert len(_sanitize(long, max_len=80)) == 80

    def test_empty(self):
        assert _sanitize("") == "untitled"

    def test_norwegian_chars(self):
        result = _sanitize("Årsregnskap_og_økonomi")
        assert "rsregnskap" in result


class TestDiscoveryDB:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = str(Path(self.tmpdir) / "test.db")
        self.db = DiscoveryDB(self.db_path)

    def teardown_method(self):
        self.db.close()

    def test_insert_and_search(self):
        self.db.insert_email(
            uuid="abc123",
            pst_folder="Innboks",
            subject="Test email om konkurs",
            sender="test@example.com",
            recipients="lasse@reinconsult.no",
            cc="",
            date="Mon, 01 Jan 2024 10:00:00 +0000",
            date_iso="2024-01-01T10:00:00+00:00",
            has_attachments=0,
            attachment_names=None,
            source_path="/tmp/abc123.eml",
            markdown_path="/tmp/abc123.md",
            original_filename="1.eml",
            body_preview="Dette handler om konkurs",
            extracted_at="2024-01-01T10:00:00+00:00",
        )
        results = self.db.search("konkurs")
        assert len(results) == 1
        assert results[0]["uuid"] == "abc123"

    def test_search_by_folder(self):
        self.db.insert_email(
            uuid="f1", pst_folder="Innboks", subject="Inbox email",
            sender="a@b.com", recipients="c@d.com", cc="", date="", date_iso="2024-01-01",
            has_attachments=0, attachment_names=None, source_path="/tmp/f1.eml",
            markdown_path="/tmp/f1.md", original_filename="1.eml",
            body_preview="", extracted_at="2024-01-01",
        )
        self.db.insert_email(
            uuid="f2", pst_folder="Sendte", subject="Sent email",
            sender="a@b.com", recipients="c@d.com", cc="", date="", date_iso="2024-01-02",
            has_attachments=0, attachment_names=None, source_path="/tmp/f2.eml",
            markdown_path="/tmp/f2.md", original_filename="2.eml",
            body_preview="", extracted_at="2024-01-01",
        )
        results = self.db.search("", folder="Innboks")
        assert len(results) == 1
        assert results[0]["uuid"] == "f1"

    def test_search_by_date_range(self):
        self.db.insert_email(
            uuid="d1", pst_folder="Innboks", subject="Old",
            sender="a@b.com", recipients="c@d.com", cc="", date="", date_iso="2023-06-01",
            has_attachments=0, attachment_names=None, source_path="/tmp/d1.eml",
            markdown_path="/tmp/d1.md", original_filename="1.eml",
            body_preview="", extracted_at="2024-01-01",
        )
        self.db.insert_email(
            uuid="d2", pst_folder="Innboks", subject="New",
            sender="a@b.com", recipients="c@d.com", cc="", date="", date_iso="2024-06-01",
            has_attachments=0, attachment_names=None, source_path="/tmp/d2.eml",
            markdown_path="/tmp/d2.md", original_filename="2.eml",
            body_preview="", extracted_at="2024-01-01",
        )
        results = self.db.search("", after="2024-01-01")
        assert len(results) == 1
        assert results[0]["uuid"] == "d2"

    def test_insert_attachment(self):
        self.db.insert_email(
            uuid="e1", pst_folder="Innboks", subject="With att",
            sender="a@b.com", recipients="c@d.com", cc="", date="", date_iso="2024-01-01",
            has_attachments=1, attachment_names="doc.pdf", source_path="/tmp/e1.eml",
            markdown_path="/tmp/e1.md", original_filename="1.eml",
            body_preview="", extracted_at="2024-01-01",
        )
        self.db.insert_attachment(
            uuid="a1", email_uuid="e1", original_filename="doc.pdf",
            source_path="/tmp/a1_doc.pdf", markdown_path=None,
            size_bytes=1024, content_type="application/pdf",
            extracted_at="2024-01-01",
        )
        atts = self.db.get_attachments("e1")
        assert len(atts) == 1
        assert atts[0]["original_filename"] == "doc.pdf"

    def test_stats(self):
        self.db.insert_email(
            uuid="s1", pst_folder="Innboks", subject="Test",
            sender="a@b.com", recipients="c@d.com", cc="", date="", date_iso="2024-01-01",
            has_attachments=0, attachment_names=None, source_path="/tmp/s1.eml",
            markdown_path="/tmp/s1.md", original_filename="1.eml",
            body_preview="", extracted_at="2024-01-01",
        )
        stats = self.db.get_stats()
        assert stats["emails"] == 1
        assert "Innboks" in stats["folders"]

    def test_extraction_run_tracking(self):
        run_id = self.db.start_run("/test.pst", "Innboks")
        self.db.finish_run(run_id, emails=5, attachments=3, errors=1)
        row = self.db.conn.execute("SELECT * FROM extraction_runs WHERE id = ?", (run_id,)).fetchone()
        assert row["emails_extracted"] == 5
        assert row["status"] == "done"

    def test_insert_email_with_new_fields(self):
        self.db.insert_email(
            uuid="new1",
            pst_folder="Innboks",
            subject="Threaded email",
            sender="alice@example.com",
            recipients="bob@example.com",
            cc="",
            date="",
            date_iso="2024-03-01",
            has_attachments=0,
            attachment_names=None,
            source_path="/tmp/new1.eml",
            markdown_path="/tmp/new1.md",
            original_filename="1.eml",
            body_preview="Short preview",
            extracted_at="2024-03-01",
            body_text="This is the full body text of the email with more detail",
            message_id="<msg001@example.com>",
            in_reply_to=None,
            references_header=None,
            thread_id="thread-001",
        )
        email = self.db.get_email("new1")
        assert email["body_text"] == "This is the full body text of the email with more detail"
        assert email["message_id"] == "<msg001@example.com>"
        assert email["thread_id"] == "thread-001"

    def test_insert_email_backward_compat(self):
        self.db.insert_email(
            uuid="compat1",
            pst_folder="Innboks",
            subject="Old style insert",
            sender="a@b.com",
            recipients="c@d.com",
            cc="",
            date="",
            date_iso="2024-01-01",
            has_attachments=0,
            attachment_names=None,
            source_path="/tmp/compat1.eml",
            markdown_path="/tmp/compat1.md",
            original_filename="1.eml",
            body_preview="preview",
            extracted_at="2024-01-01",
        )
        email = self.db.get_email("compat1")
        assert email["uuid"] == "compat1"
        assert email["body_text"] is None
        assert email["thread_id"] is None

    def test_fts_search(self):
        self.db.insert_email(
            uuid="fts1",
            pst_folder="Innboks",
            subject="Quarterly financial report",
            sender="cfo@company.com",
            recipients="board@company.com",
            cc="",
            date="",
            date_iso="2024-02-01",
            has_attachments=0,
            attachment_names=None,
            source_path="/tmp/fts1.eml",
            markdown_path="/tmp/fts1.md",
            original_filename="1.eml",
            body_preview="Q4 numbers",
            extracted_at="2024-02-01",
            body_text="The quarterly financial results show a 15% increase in revenue",
        )
        self.db.insert_email(
            uuid="fts2",
            pst_folder="Innboks",
            subject="Lunch plans",
            sender="friend@example.com",
            recipients="me@example.com",
            cc="",
            date="",
            date_iso="2024-02-02",
            has_attachments=0,
            attachment_names=None,
            source_path="/tmp/fts2.eml",
            markdown_path="/tmp/fts2.md",
            original_filename="2.eml",
            body_preview="Lunch?",
            extracted_at="2024-02-02",
            body_text="Want to grab lunch tomorrow at the usual place?",
        )
        results = self.db.search_fts("financial")
        assert len(results) == 1
        assert results[0]["uuid"] == "fts1"
        assert "snippet" in results[0]

    def test_fts_snippet_contains_markers(self):
        self.db.insert_email(
            uuid="snip1",
            pst_folder="Sendte",
            subject="Contract review",
            sender="legal@co.com",
            recipients="me@co.com",
            cc="",
            date="",
            date_iso="2024-04-01",
            has_attachments=0,
            attachment_names=None,
            source_path="/tmp/snip1.eml",
            markdown_path="/tmp/snip1.md",
            original_filename="1.eml",
            body_preview="",
            extracted_at="2024-04-01",
            body_text="Please review the attached contract for the new vendor agreement",
        )
        results = self.db.search_fts("contract")
        assert len(results) == 1
        assert ">>>" in results[0]["snippet"] or "contract" in results[0]["snippet"].lower()

    def test_search_uses_fts_for_plain_query(self):
        self.db.insert_email(
            uuid="sq1",
            pst_folder="Innboks",
            subject="Budget proposal",
            sender="finance@co.com",
            recipients="ceo@co.com",
            cc="",
            date="",
            date_iso="2024-05-01",
            has_attachments=0,
            attachment_names=None,
            source_path="/tmp/sq1.eml",
            markdown_path="/tmp/sq1.md",
            original_filename="1.eml",
            body_preview="Budget",
            extracted_at="2024-05-01",
            body_text="The proposed budget for next fiscal year",
        )
        results = self.db.search("budget")
        assert len(results) >= 1
        assert results[0]["uuid"] == "sq1"

    def test_search_with_filters_uses_like(self):
        self.db.insert_email(
            uuid="sf1",
            pst_folder="Innboks",
            subject="Meeting notes",
            sender="boss@co.com",
            recipients="team@co.com",
            cc="",
            date="",
            date_iso="2024-06-01",
            has_attachments=0,
            attachment_names=None,
            source_path="/tmp/sf1.eml",
            markdown_path="/tmp/sf1.md",
            original_filename="1.eml",
            body_preview="Notes from meeting",
            extracted_at="2024-06-01",
            body_text="Meeting notes from Monday standup",
        )
        results = self.db.search("meeting", folder="Innboks")
        assert len(results) >= 1
        assert results[0]["uuid"] == "sf1"

    def test_get_thread(self):
        for i, date in enumerate(["2024-01-01", "2024-01-02", "2024-01-03"]):
            self.db.insert_email(
                uuid=f"t{i}",
                pst_folder="Innboks",
                subject="RE: Project discussion",
                sender=f"user{i}@co.com",
                recipients="team@co.com",
                cc="",
                date="",
                date_iso=date,
                has_attachments=0,
                attachment_names=None,
                source_path=f"/tmp/t{i}.eml",
                markdown_path=f"/tmp/t{i}.md",
                original_filename=f"{i}.eml",
                body_preview="",
                extracted_at="2024-01-01",
                thread_id="thread-proj",
                message_id=f"<msg{i}@co.com>",
            )
        self.db.insert_email(
            uuid="other",
            pst_folder="Innboks",
            subject="Unrelated",
            sender="x@co.com",
            recipients="y@co.com",
            cc="",
            date="",
            date_iso="2024-01-02",
            has_attachments=0,
            attachment_names=None,
            source_path="/tmp/other.eml",
            markdown_path="/tmp/other.md",
            original_filename="other.eml",
            body_preview="",
            extracted_at="2024-01-01",
            thread_id="thread-other",
        )
        thread = self.db.get_thread("thread-proj")
        assert len(thread) == 3
        assert thread[0]["uuid"] == "t0"
        assert thread[2]["uuid"] == "t2"

    def test_migration_idempotent(self):
        db2 = DiscoveryDB(self.db_path)
        db2.insert_email(
            uuid="mig1",
            pst_folder="Innboks",
            subject="After re-open",
            sender="a@b.com",
            recipients="c@d.com",
            cc="",
            date="",
            date_iso="2024-01-01",
            has_attachments=0,
            attachment_names=None,
            source_path="/tmp/mig1.eml",
            markdown_path="/tmp/mig1.md",
            original_filename="1.eml",
            body_preview="",
            extracted_at="2024-01-01",
            body_text="Full text here",
        )
        results = db2.search_fts("text")
        assert len(results) >= 1
        db2.close()
