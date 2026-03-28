import pytest
from janitor.db import JanitorDB


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "janitor.db"
    return JanitorDB(str(db_path))


def test_init_creates_table(db):
    rows = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = [r[0] for r in rows]
    assert "files" in names


def test_discover_file(db):
    db.discover_file("test.pdf", ".pdf", 1024, "/downloads/test.pdf")
    row = db.get_file_by_source("/downloads/test.pdf")
    assert row is not None
    assert row["filename"] == "test.pdf"
    assert row["status"] == "discovered"


def test_discover_duplicate_ignored(db):
    db.discover_file("test.pdf", ".pdf", 1024, "/downloads/test.pdf")
    db.discover_file("test.pdf", ".pdf", 1024, "/downloads/test.pdf")
    count = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    assert count == 1


def test_get_discovered_files(db):
    db.discover_file("a.pdf", ".pdf", 100, "/downloads/a.pdf")
    db.discover_file("b.png", ".png", 200, "/downloads/b.png")
    files = db.get_discovered_files()
    assert len(files) == 2


def test_mark_moved(db):
    db.discover_file("a.pdf", ".pdf", 100, "/downloads/a.pdf")
    row = db.get_file_by_source("/downloads/a.pdf")
    db.mark_moved(row["id"], "/documents/a.pdf", "documents-pdf")
    updated = db.get_file_by_source("/downloads/a.pdf")
    assert updated["status"] == "moved"
    assert updated["dest_path"] == "/documents/a.pdf"
    assert updated["moved_at"] is not None


def test_mark_error(db):
    db.discover_file("a.pdf", ".pdf", 100, "/downloads/a.pdf")
    row = db.get_file_by_source("/downloads/a.pdf")
    db.mark_error(row["id"], "file not found")
    updated = db.get_file_by_source("/downloads/a.pdf")
    assert updated["status"] == "error"
    assert updated["rule_matched"] == "file not found"


def test_get_status_counts(db):
    db.discover_file("a.pdf", ".pdf", 100, "/downloads/a.pdf")
    db.discover_file("b.png", ".png", 200, "/downloads/b.png")
    row = db.get_file_by_source("/downloads/a.pdf")
    db.mark_moved(row["id"], "/docs/a.pdf", "pdf")
    counts = db.get_status_counts()
    assert counts["discovered"] == 1
    assert counts["moved"] == 1
