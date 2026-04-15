"""Tests for the unified web UI using DocumentStore."""
import subprocess
import time
import uuid as uuid_mod
from datetime import datetime, timezone
from pathlib import Path

import pytest

DISCOVERY_ROOT = Path.home() / "Documents" / "Legal-Discovery"


@pytest.fixture(scope="module")
def unified_db(tmp_path_factory):
    from janitor.store import DocumentStore
    from janitor.models import Document

    db_dir = tmp_path_factory.mktemp("webtest")
    db_path = db_dir / "unified.db"
    store = DocumentStore(str(db_path))

    now = datetime.now(timezone.utc).isoformat()
    md_path = db_dir / "test.md"
    md_path.write_text("## Body\nHello world test body", encoding="utf-8")

    store.insert(Document(
        uuid=str(uuid_mod.uuid4()),
        doc_type="email",
        source="pst",
        created_at=now,
        title="Test Email Subject",
        sender="alice@example.com",
        recipients="bob@example.com",
        date_sent="2025-01-15T10:00:00",
        folder="Inbox",
        body_text="This is a test email body",
        body_preview="This is a test email",
        markdown_path=str(md_path),
    ))
    store.insert(Document(
        uuid=str(uuid_mod.uuid4()),
        doc_type="file",
        source="filesystem",
        created_at=now,
        title="Important Document",
        filename="report.pdf",
        date_sent="2025-02-01T08:00:00",
        folder="Documents",
        rule_matched="financial",
        sha256="abc123def456",
        size_bytes=102400,
        body_text="Financial report content",
    ))
    store.insert(Document(
        uuid=str(uuid_mod.uuid4()),
        doc_type="attachment",
        source="pst",
        created_at=now,
        filename="invoice.pdf",
        content_type="application/pdf",
        size_bytes=51200,
        date_sent="2025-01-15T10:00:00",
        folder="Inbox",
    ))

    yield store, db_path
    store.close()


@pytest.fixture(scope="module")
def server(unified_db):
    import httpx
    import os

    store, db_path = unified_db
    env = os.environ.copy()
    env["JANITOR_DB_PATH"] = str(db_path)

    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "janitor.web.app:app", "--host", "127.0.0.1", "--port", "8899"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env,
    )
    timeout = 30
    start = time.time()
    while time.time() - start < timeout:
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            raise RuntimeError(f"Server exited early (rc={proc.returncode}): {stderr}")
        try:
            resp = httpx.get("http://127.0.0.1:8899/", timeout=2)
            if resp.status_code == 200:
                break
        except (httpx.ConnectError, httpx.TimeoutException):
            time.sleep(0.5)
    else:
        proc.terminate()
        proc.wait(timeout=5)
        raise RuntimeError(f"Server failed to start within {timeout}s")
    yield proc
    proc.terminate()
    proc.wait(timeout=5)


def _get(path):
    import httpx
    return httpx.get(f"http://127.0.0.1:8899{path}", timeout=10)


class TestDashboard:
    def test_dashboard_returns_200(self, server):
        r = _get("/")
        assert r.status_code == 200
        assert "Legal Discovery" in r.text

    def test_dashboard_shows_total(self, server):
        r = _get("/")
        assert "Total Documents" in r.text

    def test_dashboard_shows_type_breakdown(self, server):
        r = _get("/")
        assert "Email" in r.text or "email" in r.text


class TestSearch:
    def test_search_empty_query_returns_200(self, server):
        r = _get("/search")
        assert r.status_code == 200

    def test_search_with_query_returns_200(self, server):
        r = _get("/search?q=test")
        assert r.status_code == 200

    def test_search_with_doc_type_filter(self, server):
        r = _get("/search?doc_type=email")
        assert r.status_code == 200

    def test_search_with_doc_type_file(self, server):
        r = _get("/search?doc_type=file")
        assert r.status_code == 200

    def test_search_htmx_partial(self, server):
        import httpx
        r = httpx.get(
            "http://127.0.0.1:8899/search?q=test",
            headers={"HX-Request": "true"},
            timeout=10,
        )
        assert r.status_code == 200
        assert "<!DOCTYPE" not in r.text


class TestAPIStats:
    def test_api_stats_returns_json(self, server):
        r = _get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "by_type" in data
        assert "by_source" in data
        assert "folders" in data

    def test_api_stats_has_correct_total(self, server):
        r = _get("/api/stats")
        data = r.json()
        assert data["total"] == 3

    def test_api_stats_by_type(self, server):
        r = _get("/api/stats")
        data = r.json()
        assert data["by_type"].get("email") == 1
        assert data["by_type"].get("file") == 1
        assert data["by_type"].get("attachment") == 1


class TestTimeline:
    def test_timeline_returns_200(self, server):
        r = _get("/timeline")
        assert r.status_code == 200

    def test_timeline_with_date_filter(self, server):
        r = _get("/timeline?after=2025-01-01&before=2025-12-31")
        assert r.status_code == 200
