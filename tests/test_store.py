import pytest
from janitor.models import Document
from janitor.store import DocumentStore


@pytest.fixture
def store(tmp_path):
    return DocumentStore(str(tmp_path / "docs.db"))


def _email(uuid="e1", **kw):
    defaults = dict(
        doc_type="email", source="pst", created_at="2025-01-01T00:00:00Z",
        title="Test Subject", sender="alice@example.com",
        recipients="bob@example.com", body_text="Hello world",
        folder="Inbox", date_sent="2025-01-01T10:00:00Z",
    )
    defaults.update(kw)
    return Document(uuid=uuid, **defaults)


def _file(uuid="f1", **kw):
    defaults = dict(
        doc_type="file", source="filesystem", created_at="2025-01-01T00:00:00Z",
        filename="report.pdf", extension=".pdf", size_bytes=2048,
        source_path="/downloads/report.pdf",
    )
    defaults.update(kw)
    return Document(uuid=uuid, **defaults)


def _attachment(uuid="a1", parent_uuid="e1", **kw):
    defaults = dict(
        doc_type="attachment", source="pst", created_at="2025-01-01T00:00:00Z",
        filename="data.xlsx", extension=".xlsx", size_bytes=4096,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    defaults.update(kw)
    return Document(uuid=uuid, parent_uuid=parent_uuid, **defaults)


def test_insert_and_get(store):
    doc = _email()
    store.insert(doc)
    result = store.get("e1")
    assert result is not None
    assert result["uuid"] == "e1"
    assert result["doc_type"] == "email"
    assert result["title"] == "Test Subject"
    assert result["status"] == "indexed"


def test_insert_with_parent(store):
    store.insert(_email())
    store.insert(_attachment())
    children = store.get_children("e1")
    assert len(children) == 1
    assert children[0]["uuid"] == "a1"
    assert children[0]["doc_type"] == "attachment"
    assert children[0]["parent_uuid"] == "e1"


def test_fts_search(store):
    store.insert(_email(uuid="e1", body_text="quarterly budget report"))
    store.insert(_email(uuid="e2", body_text="lunch plans for friday"))
    results = store.search_fts("budget")
    assert len(results) == 1
    assert results[0]["uuid"] == "e1"


def test_search_with_folder_filter(store):
    store.insert(_email(uuid="e1", folder="Inbox"))
    store.insert(_email(uuid="e2", folder="Sent"))
    results = store.search(folder="Inbox")
    assert len(results) == 1
    assert results[0]["folder"] == "Inbox"


def test_search_with_sender_filter(store):
    store.insert(_email(uuid="e1", sender="alice@example.com"))
    store.insert(_email(uuid="e2", sender="bob@example.com"))
    results = store.search(sender="alice")
    assert len(results) == 1
    assert "alice" in results[0]["sender"]


def test_search_with_date_range(store):
    store.insert(_email(uuid="e1", date_sent="2025-01-01T10:00:00Z"))
    store.insert(_email(uuid="e2", date_sent="2025-06-01T10:00:00Z"))
    results = store.search(after="2025-03-01", before="2025-12-31")
    assert len(results) == 1
    assert results[0]["uuid"] == "e2"


def test_search_with_doc_type_filter(store):
    store.insert(_email(uuid="e1"))
    store.insert(_file(uuid="f1"))
    results = store.search(doc_type="file")
    assert len(results) == 1
    assert results[0]["doc_type"] == "file"


def test_dedup_by_sha256(store):
    store.insert(_file(uuid="f1", sha256="abc123"))
    found = store.find_by_sha256("abc123")
    assert found is not None
    assert found["uuid"] == "f1"
    assert store.find_by_sha256("nonexistent") is None


def test_get_thread_ordered(store):
    store.insert(_email(uuid="e1", thread_id="t1", date_sent="2025-01-03T00:00:00Z", title="Re: Hi"))
    store.insert(_email(uuid="e2", thread_id="t1", date_sent="2025-01-01T00:00:00Z", title="Hi"))
    store.insert(_email(uuid="e3", thread_id="t1", date_sent="2025-01-02T00:00:00Z", title="Re: Hi"))
    thread = store.get_thread("t1")
    assert len(thread) == 3
    assert [t["uuid"] for t in thread] == ["e2", "e3", "e1"]


def test_stats(store):
    store.insert(_email(uuid="e1"))
    store.insert(_email(uuid="e2", folder="Sent", source="pst"))
    store.insert(_file(uuid="f1"))
    store.insert(_attachment(uuid="a1"))
    s = store.stats()
    assert s["total"] == 4
    assert s["by_type"]["email"] == 2
    assert s["by_type"]["file"] == 1
    assert s["by_type"]["attachment"] == 1
    assert s["by_source"]["pst"] == 3
    assert s["by_source"]["filesystem"] == 1
    assert "Inbox" in s["folders"]
    assert "Sent" in s["folders"]


def test_ingest_run_tracking(store):
    run_id = store.start_run("pst", "/data/archive.pst")
    assert run_id is not None
    store.finish_run(run_id, docs=42, errors=2, status="done")
    row = store.conn.execute("SELECT * FROM ingest_runs WHERE id = ?", (run_id,)).fetchone()
    assert row["docs_processed"] == 42
    assert row["errors"] == 2
    assert row["status"] == "done"
    assert row["finished_at"] is not None


def test_empty_search_returns_results(store):
    store.insert(_email(uuid="e1"))
    store.insert(_file(uuid="f1"))
    results = store.search()
    assert len(results) == 2


def test_search_limit_respected(store):
    for i in range(10):
        store.insert(_email(uuid=f"e{i}", date_sent=f"2025-01-{i+1:02d}T00:00:00Z"))
    results = store.search(limit=3)
    assert len(results) == 3
