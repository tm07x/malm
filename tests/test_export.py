import csv
import json
import os
import zipfile

import pytest

from janitor.models import Document
from janitor.store import DocumentStore
from janitor.export import export_csv, export_evidence_package, export_from_search


@pytest.fixture
def test_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    store = DocumentStore(db_path)

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

    store.insert(Document(
        uuid="uuid-001", doc_type="email", source="pst",
        title="Test Email", sender="alice@example.com",
        recipients="bob@example.com", date_sent="2024-01-15T10:00:00Z",
        folder="Inbox", source_path=str(source1), markdown_path=str(md1),
        filename="email1.eml", body_preview="Body here",
        created_at="2024-06-01T00:00:00Z",
    ))
    store.insert(Document(
        uuid="uuid-002", doc_type="email", source="pst",
        title="Contract Review", sender="bob@example.com",
        recipients="alice@example.com", date_sent="2024-02-20T14:30:00Z",
        folder="Sent Items", source_path=str(source2), markdown_path=str(md2),
        filename="email2.eml", body_preview="Details",
        created_at="2024-06-01T00:00:00Z",
    ))
    store.insert(Document(
        uuid="att-001", doc_type="attachment", source="pst",
        parent_uuid="uuid-002", title="contract.pdf",
        filename="contract.pdf", source_path=str(att_path),
        size_bytes=17, content_type="application/pdf",
        created_at="2024-06-01T00:00:00Z",
    ))
    store.close()
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


def test_export_from_search(test_db):
    db_path, tmp_path = test_db
    out_dir = str(tmp_path / "search_exports")
    result = export_from_search(
        "Contract", package_name="search-contract",
        output_dir=out_dir, db_path=db_path,
    )
    assert result.endswith("search-contract.zip")
    assert os.path.isfile(result)
