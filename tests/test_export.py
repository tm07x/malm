import csv
import json
import os
import tempfile
import zipfile

import pytest

from janitor.discovery_db import DiscoveryDB
from janitor.export import export_csv, export_evidence_package, export_from_search


@pytest.fixture
def test_db(tmp_path):
    db_path = str(tmp_path / "test_discovery.db")
    db = DiscoveryDB(db_path)

    source1 = tmp_path / "email1.eml"
    source1.write_text("From: alice@example.com\nSubject: Test\n\nBody here")
    md1 = tmp_path / "email1.md"
    md1.write_text("# Test Email\n\nBody here")

    source2 = tmp_path / "email2.eml"
    source2.write_text("From: bob@example.com\nSubject: Contract\n\nDetails")
    md2 = tmp_path / "email2.md"
    md2.write_text("# Contract\n\nDetails")

    att_path = tmp_path / "contract.pdf"
    att_path.write_bytes(b"%PDF-fake-content")

    db.insert_email(
        uuid="uuid-001", pst_folder="Inbox", subject="Test Email",
        sender="alice@example.com", recipients="bob@example.com", cc="",
        date="2024-01-15", date_iso="2024-01-15T10:00:00Z",
        has_attachments=0, attachment_names="",
        source_path=str(source1), markdown_path=str(md1),
        original_filename="email1.eml", body_preview="Body here",
        extracted_at="2024-06-01T00:00:00Z",
    )
    db.insert_email(
        uuid="uuid-002", pst_folder="Sent Items", subject="Contract Review",
        sender="bob@example.com", recipients="alice@example.com", cc="",
        date="2024-02-20", date_iso="2024-02-20T14:30:00Z",
        has_attachments=1, attachment_names="contract.pdf",
        source_path=str(source2), markdown_path=str(md2),
        original_filename="email2.eml", body_preview="Details",
        extracted_at="2024-06-01T00:00:00Z",
    )
    db.insert_attachment(
        uuid="att-001", email_uuid="uuid-002",
        original_filename="contract.pdf",
        source_path=str(att_path), markdown_path=None,
        size_bytes=17, content_type="application/pdf",
        extracted_at="2024-06-01T00:00:00Z",
    )
    db.close()
    return db_path, tmp_path


def test_export_csv_format(test_db):
    db_path, tmp_path = test_db
    out = str(tmp_path / "export.csv")
    result = export_csv(["uuid-001", "uuid-002"], out, db_path=db_path)

    assert result == out
    assert os.path.isfile(out)

    with open(out) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 2
    assert rows[0]["uuid"] == "uuid-001"
    assert rows[0]["sender"] == "alice@example.com"
    assert rows[0]["attachment_count"] == "0"
    assert rows[1]["uuid"] == "uuid-002"
    assert rows[1]["attachment_count"] == "1"

    expected_fields = {"uuid", "date", "sender", "recipients", "subject",
                       "folder", "attachment_count", "source_path", "markdown_path"}
    assert set(rows[0].keys()) == expected_fields


def test_export_csv_skips_missing_uuids(test_db):
    db_path, tmp_path = test_db
    out = str(tmp_path / "partial.csv")
    export_csv(["uuid-001", "nonexistent"], out, db_path=db_path)

    with open(out) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1


def test_evidence_package_structure(test_db):
    db_path, tmp_path = test_db
    out_dir = str(tmp_path / "exports")
    result = export_evidence_package(
        ["uuid-001", "uuid-002"], "test-package",
        output_dir=out_dir, db_path=db_path,
    )

    assert result.endswith("test-package.zip")
    assert os.path.isfile(result)

    with zipfile.ZipFile(result) as zf:
        names = zf.namelist()
        assert "manifest.csv" in names
        assert "manifest.json" in names
        assert "emails/uuid-001.eml" in names
        assert "emails/uuid-002.eml" in names
        assert "markdown/uuid-001.md" in names
        assert "markdown/uuid-002.md" in names
        assert "attachments/uuid-002/contract.pdf" in names

        manifest_csv = zf.read("manifest.csv").decode()
        reader = csv.DictReader(manifest_csv.splitlines())
        csv_rows = list(reader)
        assert len(csv_rows) == 2
        assert csv_rows[0]["sha256"] != ""

        manifest_data = json.loads(zf.read("manifest.json"))
        assert len(manifest_data) == 2
        assert manifest_data[1]["attachments"][0]["original_filename"] == "contract.pdf"


def test_export_from_search(test_db):
    db_path, tmp_path = test_db
    out_dir = str(tmp_path / "search_exports")
    result = export_from_search(
        "Contract", package_name="search-contract",
        db_path=db_path,
    )
    assert result.endswith("search-contract.zip")
