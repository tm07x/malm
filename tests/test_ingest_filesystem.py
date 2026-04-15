import os
import tempfile
from pathlib import Path

import pytest

from janitor.ingest.filesystem import FilesystemIngestor
from janitor.store import DocumentStore


@pytest.fixture
def workspace(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    dest_legal = tmp_path / "Legal"
    dest_pdfs = tmp_path / "PDFs"
    dest_unsorted = tmp_path / "Unsorted"

    rules = {
        "source": str(source),
        "keyword_rules": [
            {"id": "legal", "pattern": "(?i)stevning", "dest": str(dest_legal)},
        ],
        "extension_rules": [
            {"id": "pdf", "match": ["*.pdf"], "dest": str(dest_pdfs)},
        ],
        "defaults": {"dest": str(dest_unsorted)},
    }

    db_path = str(tmp_path / "test.db")
    store = DocumentStore(db_path)

    return {
        "source": source,
        "rules": rules,
        "store": store,
        "dest_legal": dest_legal,
        "dest_pdfs": dest_pdfs,
        "dest_unsorted": dest_unsorted,
    }


def _write(path, content=b"hello"):
    path.write_bytes(content)


def test_discovers_and_indexes(workspace):
    _write(workspace["source"] / "report.txt")
    _write(workspace["source"] / "data.csv", b"a,b,c")

    ingestor = FilesystemIngestor(workspace["store"], workspace["rules"])
    result = ingestor.scan(dry_run=True)

    assert result["discovered"] == 2
    assert result["moved"] == 0
    assert result["skipped"] == 0

    stats = workspace["store"].stats()
    assert stats["total"] == 2
    assert stats["by_type"].get("file") == 2
    assert stats["by_source"].get("filesystem") == 2


def test_keyword_overrides_extension(workspace):
    _write(workspace["source"] / "stevning_dok.pdf")

    ingestor = FilesystemIngestor(workspace["store"], workspace["rules"])
    result = ingestor.scan(dry_run=True)

    assert result["discovered"] == 1
    doc = workspace["store"].search(query="stevning")[0]
    assert doc["rule_matched"] == "legal"
    assert doc["folder"] == str(workspace["dest_legal"])


def test_dry_run_does_not_move(workspace):
    _write(workspace["source"] / "invoice.pdf")

    ingestor = FilesystemIngestor(workspace["store"], workspace["rules"])
    result = ingestor.scan(dry_run=True)

    assert result["moved"] == 0
    assert (workspace["source"] / "invoice.pdf").exists()


def test_sha256_dedup(workspace):
    _write(workspace["source"] / "file_a.txt", b"same content")

    ingestor = FilesystemIngestor(workspace["store"], workspace["rules"])
    result1 = ingestor.scan(dry_run=True)
    assert result1["discovered"] == 1
    assert result1["skipped"] == 0

    result2 = ingestor.scan(dry_run=True)
    assert result2["discovered"] == 1
    assert result2["skipped"] == 1

    assert workspace["store"].stats()["total"] == 1


def test_dotfiles_skipped(workspace):
    _write(workspace["source"] / ".hidden")
    _write(workspace["source"] / "visible.txt")

    ingestor = FilesystemIngestor(workspace["store"], workspace["rules"])
    result = ingestor.scan(dry_run=True)

    assert result["discovered"] == 1
    assert workspace["store"].stats()["total"] == 1


def test_actual_move(workspace):
    _write(workspace["source"] / "contract.pdf", b"pdf content")

    ingestor = FilesystemIngestor(workspace["store"], workspace["rules"])
    result = ingestor.scan(dry_run=False)

    assert result["moved"] == 1
    assert not (workspace["source"] / "contract.pdf").exists()
    assert (workspace["dest_pdfs"] / "contract.pdf").exists()
