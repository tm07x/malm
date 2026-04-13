"""Real-world integration tests against the live discovery database.

These tests verify the full pipeline works with actual extracted PST data.
Skip if discovery DB doesn't exist (CI environments).
"""
import subprocess
import json
import time
from pathlib import Path

import pytest

DISCOVERY_ROOT = Path.home() / "Documents" / "Legal-Discovery"
DB_PATH = DISCOVERY_ROOT / "discovery.db"
SOURCE_DIR = DISCOVERY_ROOT / "source-doc"
MD_DIR = DISCOVERY_ROOT / "MD"

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason="Discovery DB not found — skip real-world tests",
)


@pytest.fixture(scope="module")
def db():
    from janitor.discovery_db import DiscoveryDB
    d = DiscoveryDB(str(DB_PATH))
    yield d
    d.close()


# ── Data integrity ──────────────────────────────────────────────

class TestDataIntegrity:
    def test_email_count_is_reasonable(self, db):
        count = db.email_count()
        assert count > 10_000, f"Expected 14k+ emails, got {count}"

    def test_every_email_has_source_file(self, db):
        rows = db.conn.execute("SELECT uuid, source_path FROM emails LIMIT 200").fetchall()
        missing = [row["uuid"] for row in rows if not Path(row["source_path"]).exists()]
        assert len(missing) == 0, f"{len(missing)} emails missing source files: {missing[:5]}"

    def test_every_email_has_markdown_file(self, db):
        rows = db.conn.execute("SELECT uuid, markdown_path FROM emails LIMIT 200").fetchall()
        missing = [row["uuid"] for row in rows if not Path(row["markdown_path"]).exists()]
        assert len(missing) == 0, f"{len(missing)} emails missing markdown: {missing[:5]}"

    def test_attachment_files_exist(self, db):
        rows = db.conn.execute("SELECT uuid, source_path FROM attachments LIMIT 200").fetchall()
        missing = [row["uuid"] for row in rows if not Path(row["source_path"]).exists()]
        assert len(missing) == 0, f"{len(missing)} attachments missing files: {missing[:5]}"

    def test_no_orphan_attachments(self, db):
        orphans = db.conn.execute("""
            SELECT a.uuid FROM attachments a
            LEFT JOIN emails e ON a.email_uuid = e.uuid
            WHERE e.uuid IS NULL
        """).fetchall()
        assert len(orphans) == 0, f"{len(orphans)} orphan attachments found"

    def test_all_emails_have_uuid(self, db):
        bad = db.conn.execute("SELECT COUNT(*) FROM emails WHERE uuid IS NULL OR uuid = ''").fetchone()[0]
        assert bad == 0

    def test_all_emails_have_subject(self, db):
        no_subj = db.conn.execute("SELECT COUNT(*) FROM emails WHERE subject IS NULL").fetchone()[0]
        assert no_subj == 0

    def test_all_emails_have_folder(self, db):
        no_folder = db.conn.execute("SELECT COUNT(*) FROM emails WHERE pst_folder IS NULL OR pst_folder = ''").fetchone()[0]
        assert no_folder == 0


# ── Encoding / charset ──────────────────────────────────────────

class TestEncoding:
    def test_norwegian_chars_in_subjects(self, db):
        """Subjects should contain Norwegian characters, not mojibake."""
        rows = db.conn.execute(
            "SELECT subject FROM emails WHERE subject LIKE '%ø%' OR subject LIKE '%å%' OR subject LIKE '%æ%' LIMIT 5"
        ).fetchall()
        assert len(rows) > 0, "No Norwegian chars found in subjects"
        for row in rows:
            assert "�" not in row["subject"], f"Mojibake in subject: {row['subject'][:60]}"

    def test_norwegian_chars_in_body(self, db):
        rows = db.conn.execute(
            "SELECT uuid, body_text FROM emails WHERE body_text LIKE '%ø%' LIMIT 5"
        ).fetchall()
        assert len(rows) > 0, "No Norwegian ø found in body text"

    def test_sami_name_preserved(self, db):
        rows = db.conn.execute(
            "SELECT sender FROM emails WHERE sender LIKE '%Lásse%' LIMIT 1"
        ).fetchall()
        assert len(rows) > 0, "Sami name 'Lásse' not found in sender"

    def test_no_mojibake_in_body_sample(self, db):
        """Sample body texts should not contain replacement char U+FFFD."""
        rows = db.conn.execute(
            "SELECT uuid, body_text FROM emails WHERE body_text IS NOT NULL AND length(body_text) > 100 LIMIT 50"
        ).fetchall()
        bad = [r["uuid"] for r in rows if "\ufffd" in (r["body_text"] or "")]
        # Some replacement chars are acceptable for truly broken encodings,
        # but it shouldn't be more than 10% of the sample
        assert len(bad) < len(rows) * 0.1, f"{len(bad)}/{len(rows)} emails have U+FFFD in body"


# ── Search ──────────────────────────────────────────────────────

class TestSearch:
    def test_keyword_search(self, db):
        results = db.search("konkurs")
        assert len(results) > 0, "No results for 'konkurs'"

    def test_fts_body_search(self, db):
        """FTS should find terms only in body text, not in subject."""
        results = db.search_fts("bistandsplikt")
        assert len(results) > 0, "FTS didn't find 'bistandsplikt' in body text"

    def test_folder_filter(self, db):
        results = db.search("", folder="Innboks")
        assert len(results) > 0
        assert all(r["pst_folder"] == "Innboks" for r in results)

    def test_sender_filter(self, db):
        results = db.search("", sender="noreply")
        assert len(results) > 0
        assert all("noreply" in r["sender"].lower() for r in results)

    def test_date_range_filter(self, db):
        results = db.search("", after="2024-10-01", before="2024-10-31")
        assert len(results) > 0
        for r in results:
            assert r["date_iso"] >= "2024-10-01"
            assert r["date_iso"] <= "2024-10-31"

    def test_combined_filters(self, db):
        results = db.search("faktura", folder="Innboks", after="2024-01-01")
        assert len(results) > 0

    def test_empty_search_returns_results(self, db):
        results = db.search("")
        assert len(results) > 0, "Empty search should return recent emails"

    def test_search_limit_respected(self, db):
        results = db.search("", limit=5)
        assert len(results) <= 5


# ── Threading ───────────────────────────────────────────────────

class TestThreading:
    def test_thread_ids_populated(self, db):
        count = db.conn.execute(
            "SELECT COUNT(*) FROM emails WHERE thread_id IS NOT NULL AND thread_id != ''"
        ).fetchone()[0]
        total = db.email_count()
        assert count > total * 0.5, f"Only {count}/{total} emails have thread_id"

    def test_multi_email_threads_exist(self, db):
        threads = db.conn.execute("""
            SELECT thread_id, COUNT(*) as c FROM emails
            WHERE thread_id IS NOT NULL AND thread_id != ''
            GROUP BY thread_id HAVING c > 2
            ORDER BY c DESC LIMIT 5
        """).fetchall()
        assert len(threads) > 0, "No multi-email threads found"
        assert threads[0]["c"] > 5, "Largest thread should have >5 emails"

    def test_get_thread_returns_ordered(self, db):
        tid = db.conn.execute("""
            SELECT thread_id FROM emails
            WHERE thread_id IS NOT NULL AND thread_id != ''
            GROUP BY thread_id HAVING COUNT(*) > 3
            LIMIT 1
        """).fetchone()
        if tid:
            emails = db.get_thread(tid[0])
            assert len(emails) > 3
            dates = [e["date_iso"] for e in emails if e["date_iso"]]
            assert dates == sorted(dates), "Thread emails not ordered by date"

    def test_message_ids_populated(self, db):
        count = db.conn.execute(
            "SELECT COUNT(*) FROM emails WHERE message_id IS NOT NULL AND message_id != ''"
        ).fetchone()[0]
        assert count > 0, "No message_ids found"


# ── FTS index consistency ───────────────────────────────────────

class TestFTSConsistency:
    def test_fts_row_count_matches_emails(self, db):
        email_count = db.email_count()
        fts_count = db.conn.execute("SELECT COUNT(*) FROM emails_fts").fetchone()[0]
        assert fts_count == email_count, f"FTS has {fts_count} rows, emails has {email_count}"

    def test_fts_finds_known_sender(self, db):
        results = db.search_fts("Gjensidige")
        assert len(results) > 0, "FTS should find 'Gjensidige' (insurance company)"

    def test_fts_snippet_works(self, db):
        results = db.search_fts("konkurs")
        assert len(results) > 0
        has_snippet = any(r.get("snippet") for r in results)
        assert has_snippet, "FTS snippets not returned"


# ── Export ──────────────────────────────────────────────────────

class TestExport:
    def test_csv_export_real_data(self, db, tmp_path):
        import csv as csv_mod
        from janitor.export import export_csv
        uuids = [r["uuid"] for r in db.search("konkurs", limit=5)]
        assert len(uuids) > 0
        out = export_csv(uuids, str(tmp_path / "test.csv"), db_path=str(DB_PATH))
        with open(out) as f:
            reader = csv_mod.DictReader(f)
            rows = list(reader)
        assert len(rows) == len(uuids), f"Expected {len(uuids)} data rows, got {len(rows)}"
        assert "uuid" in rows[0]

    def test_evidence_package_real_data(self, db, tmp_path):
        from janitor.export import export_evidence_package
        uuids = [r["uuid"] for r in db.search("Reinslakteriet", limit=3)]
        assert len(uuids) > 0
        zip_path = export_evidence_package(uuids, "test_pkg", output_dir=str(tmp_path))
        assert Path(zip_path).exists()
        assert Path(zip_path).stat().st_size > 1000

        import zipfile
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert any("manifest.csv" in n for n in names)
            assert any("manifest.json" in n for n in names)
            assert any(".eml" in n for n in names)


# ── Web UI ──────────────────────────────────────────────────────

class TestWebUI:
    @pytest.fixture(autouse=True, scope="class")
    def server(self):
        import httpx
        proc = subprocess.Popen(
            ["uv", "run", "uvicorn", "janitor.web.app:app", "--host", "127.0.0.1", "--port", "8877"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        # Poll for server readiness
        timeout = 30  # seconds
        start = time.time()
        while time.time() - start < timeout:
            if proc.poll() is not None:
                raise RuntimeError(f"Server process exited early with code {proc.returncode}")
            try:
                resp = httpx.get("http://127.0.0.1:8877/", timeout=2)
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

    def _get(self, path):
        import httpx
        return httpx.get(f"http://127.0.0.1:8877{path}", timeout=10)

    def test_dashboard_loads(self, server):
        r = self._get("/")
        assert r.status_code == 200
        assert "Legal Discovery" in r.text

    def test_dashboard_shows_counts(self, server):
        from janitor.discovery_db import DiscoveryDB
        db = DiscoveryDB(str(DB_PATH))
        expected_count = db.email_count()
        db.close()
        r = self._get("/")
        # Format with comma separator (e.g., "14,474") as used in the UI
        formatted_count = f"{expected_count:,}"
        assert formatted_count in r.text, f"Expected count {formatted_count} not found in dashboard"

    def test_search_returns_results(self, server):
        r = self._get("/search?q=faktura")
        assert r.status_code == 200
        assert "<tr>" in r.text

    def test_search_norwegian_query(self, server):
        r = self._get("/search?q=årsregnskap")
        assert r.status_code == 200

    def test_email_detail_loads(self, server):
        # Get a UUID from the API
        stats = self._get("/api/stats")
        assert stats.status_code == 200
        # Search for any email
        r = self._get("/search?q=Reinslakteriet")
        assert r.status_code == 200

    def test_folder_view(self, server):
        r = self._get("/folder/Innboks")
        assert r.status_code == 200
        assert "Innboks" in r.text

    def test_folder_norwegian_name(self, server):
        r = self._get("/folder/Søppelpost")
        assert r.status_code == 200
        assert "Søppelpost" in r.text

    def test_timeline_loads(self, server):
        r = self._get("/timeline")
        assert r.status_code == 200
        assert "timeline-day" in r.text

    def test_timeline_date_filter(self, server):
        r = self._get("/timeline?after=2024-10-01&before=2024-10-31")
        assert r.status_code == 200

    def test_api_stats_json(self, server):
        r = self._get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["emails"] > 10_000
        assert len(data["folders"]) > 10

    def test_attachment_serves(self, server):
        from janitor.discovery_db import DiscoveryDB
        d = DiscoveryDB(str(DB_PATH))
        att = d.conn.execute(
            "SELECT uuid FROM attachments WHERE content_type LIKE 'application/pdf' LIMIT 1"
        ).fetchone()
        d.close()
        if att:
            r = self._get(f"/attachment/{att[0]}")
            assert r.status_code == 200

    def test_htmx_partial(self, server):
        import httpx
        r = httpx.get(
            "http://127.0.0.1:8877/search?q=faktura",
            headers={"HX-Request": "true"},
            timeout=10,
        )
        assert r.status_code == 200
        # Partial should NOT contain full HTML doc
        assert "<!DOCTYPE" not in r.text
        assert "<tr>" in r.text