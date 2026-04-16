import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from malm.store import DocumentStore
from malm.models import Document
from malm.web.app import app, get_db


@pytest.fixture
def test_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    store = DocumentStore(db_path)

    md1 = tmp_path / "email1.md"
    md1.write_text("# Test\n\n## Body\n\nHello from the body", encoding="utf-8")

    source1 = tmp_path / "email1.eml"
    source1.write_text("From: alice@example.com\nSubject: Test\n\nBody")

    att_file = tmp_path / "report.pdf"
    att_file.write_bytes(b"%PDF-fake")

    store.insert(Document(
        uuid="e001",
        doc_type="email",
        source="pst",
        created_at="2024-06-01T00:00:00Z",
        title="Konkursbegjæring mottatt",
        sender="alice@example.com",
        recipients="bob@example.com",
        cc="",
        date_sent="2024-01-01T10:00:00+01:00",
        folder="Innboks",
        source_path=str(source1),
        markdown_path=str(md1),
        filename="1.eml",
        body_preview="Kort forhåndsvisning",
        body_text="Full body text for FTS search testing",
        message_id="<msg001@example.com>",
        thread_id="thread-001",
    ))
    store.insert(Document(
        uuid="e002",
        doc_type="email",
        source="pst",
        created_at="2024-06-01T00:00:00Z",
        title="RE: Konkursbegjæring mottatt",
        sender="bob@example.com",
        recipients="alice@example.com",
        cc="",
        date_sent="2024-01-02T14:00:00+01:00",
        folder="Sendte",
        source_path=str(tmp_path / "email2.eml"),
        markdown_path=str(tmp_path / "email2.md"),
        filename="2.eml",
        body_preview="Svar på konkursbegjæring",
        body_text="Reply body text",
        message_id="<msg002@example.com>",
        in_reply_to="<msg001@example.com>",
        thread_id="thread-001",
    ))
    store.insert(Document(
        uuid="a001",
        doc_type="attachment",
        source="pst",
        created_at="2024-06-01T00:00:00Z",
        parent_uuid="e001",
        filename="report.pdf",
        source_path=str(att_file),
        size_bytes=9,
        content_type="application/pdf",
    ))
    store.close()
    return db_path, tmp_path


@pytest.fixture
def client(test_db):
    db_path, tmp_path = test_db

    db = DocumentStore(db_path)

    def override_get_db():
        return db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    db.close()


class TestDashboard:
    def test_index_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_index_shows_doc_count(self, client):
        resp = client.get("/")
        assert "3" in resp.text

    def test_index_shows_folders(self, client):
        resp = client.get("/")
        assert "Innboks" in resp.text
        assert "Sendte" in resp.text


class TestSearch:
    def test_search_page_loads(self, client):
        resp = client.get("/search")
        assert resp.status_code == 200
        assert "Search" in resp.text

    def test_search_with_query(self, client):
        resp = client.get("/search?q=konkurs")
        assert resp.status_code == 200
        assert "e001" in resp.text

    def test_search_by_folder(self, client):
        resp = client.get("/search?folder=Sendte")
        assert resp.status_code == 200
        assert "bob@example.com" in resp.text

    def test_search_htmx_returns_partial(self, client):
        resp = client.get("/search?q=konkurs", headers={"HX-Request": "true"})
        assert resp.status_code == 200
        assert "e001" in resp.text
        assert "<!DOCTYPE" not in resp.text

    def test_search_no_results(self, client):
        resp = client.get("/search?q=nonexistentxyz")
        assert resp.status_code == 200
        assert "No documents found" in resp.text

    def test_search_by_doc_type(self, client):
        resp = client.get("/search?doc_type=email")
        assert resp.status_code == 200
        assert "e001" in resp.text

    def test_search_by_doc_type_attachment(self, client):
        resp = client.get("/search?doc_type=attachment")
        assert resp.status_code == 200
        assert "a001" in resp.text


class TestDocDetail:
    def test_doc_detail_200(self, client):
        resp = client.get("/doc/e001")
        assert resp.status_code == 200
        assert "Konkursbegjæring" in resp.text

    def test_email_alias_200(self, client):
        resp = client.get("/email/e001")
        assert resp.status_code == 200
        assert "Konkursbegjæring" in resp.text

    def test_doc_detail_shows_metadata(self, client):
        resp = client.get("/doc/e001")
        assert "alice@example.com" in resp.text
        assert "bob@example.com" in resp.text
        assert "Innboks" in resp.text

    def test_doc_detail_shows_body(self, client):
        resp = client.get("/doc/e001")
        assert "Hello from the body" in resp.text

    def test_doc_detail_shows_attachments(self, client):
        resp = client.get("/doc/e001")
        assert "report.pdf" in resp.text

    def test_doc_detail_shows_thread_link(self, client):
        resp = client.get("/doc/e001")
        assert "/thread/thread-001" in resp.text

    def test_doc_detail_not_found(self, client):
        resp = client.get("/doc/nonexistent")
        assert resp.status_code == 404


class TestAttachment:
    def test_serve_attachment(self, client, test_db):
        _, tmp_path = test_db
        import malm.web.app as web_app
        original_root = web_app.DISCOVERY_ROOT
        web_app.DISCOVERY_ROOT = tmp_path
        try:
            resp = client.get("/attachment/a001")
            assert resp.status_code == 200
            assert resp.content == b"%PDF-fake"
        finally:
            web_app.DISCOVERY_ROOT = original_root

    def test_attachment_not_found(self, client):
        resp = client.get("/attachment/nonexistent")
        assert resp.status_code == 404


class TestFolder:
    def test_folder_view(self, client):
        resp = client.get("/folder/Innboks")
        assert resp.status_code == 200
        assert "e001" in resp.text

    def test_folder_empty(self, client):
        resp = client.get("/folder/EmptyFolder")
        assert resp.status_code == 200


class TestTimeline:
    def test_timeline_loads(self, client):
        resp = client.get("/timeline")
        assert resp.status_code == 200

    def test_timeline_shows_dates(self, client):
        resp = client.get("/timeline")
        assert "2024-01-01" in resp.text or "2024-01-02" in resp.text

    def test_timeline_with_date_filter(self, client):
        resp = client.get("/timeline?after=2024-01-02")
        assert resp.status_code == 200


class TestThread:
    def test_thread_view(self, client):
        resp = client.get("/thread/thread-001")
        assert resp.status_code == 200
        assert "2 documents" in resp.text

    def test_thread_shows_both_emails(self, client):
        resp = client.get("/thread/thread-001")
        assert "alice@example.com" in resp.text
        assert "bob@example.com" in resp.text

    def test_empty_thread(self, client):
        resp = client.get("/thread/nonexistent-thread")
        assert resp.status_code == 200
        assert "No documents found" in resp.text


class TestAPIStats:
    def test_stats_json(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert "by_type" in data
        assert data["by_type"]["email"] == 2
        assert data["by_type"]["attachment"] == 1


class TestExportEndpoint:
    def test_export_no_uuids(self, client):
        resp = client.post("/api/export", data={"uuids": ""})
        assert resp.status_code == 400

    def test_download_export_not_found(self, client):
        resp = client.get("/exports/nonexistent.zip")
        assert resp.status_code == 404

    def test_download_export_path_traversal(self, client):
        resp = client.get("/exports/../../../etc/passwd")
        assert resp.status_code in (403, 404)
