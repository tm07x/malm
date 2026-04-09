import mimetypes
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from janitor.discovery_db import DiscoveryDB

DISCOVERY_ROOT = Path.home() / "Documents" / "Legal-Discovery"
DB_PATH = DISCOVERY_ROOT / "discovery.db"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="Legal Discovery")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_db() -> DiscoveryDB:
    return DiscoveryDB(str(DB_PATH))


def _render(request: Request, template: str, **ctx):
    return templates.TemplateResponse(request, template, ctx)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    db = get_db()
    stats = db.get_stats()
    folder_counts = db.folder_counts()
    db.close()
    return _render(request, "index.html", stats=stats, folder_counts=folder_counts)


@app.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = "",
    folder: str | None = None,
    sender: str | None = None,
    after: str | None = None,
    before: str | None = None,
    page: int = 1,
    per_page: int = 50,
):
    db = get_db()
    results = db.search(q, folder, sender, after, before, limit=per_page + 1)
    has_next = len(results) > per_page
    results = results[:per_page]
    folders = [r[0] for r in db.conn.execute(
        "SELECT DISTINCT pst_folder FROM emails ORDER BY pst_folder"
    ).fetchall()]
    db.close()

    ctx = dict(results=results, q=q, folder=folder, sender=sender,
               after=after, before=before, page=page, has_next=has_next)

    if request.headers.get("HX-Request"):
        return _render(request, "partials/email_list.html", **ctx)

    return _render(request, "search.html", folders=folders, **ctx)


@app.get("/email/{uuid}", response_class=HTMLResponse)
def email_detail(request: Request, uuid: str):
    db = get_db()
    email_rec = db.get_email(uuid)
    attachments = db.get_attachments(uuid) if email_rec else []
    db.close()

    if not email_rec:
        return HTMLResponse("<h1>Not found</h1>", status_code=404)

    md_path = Path(email_rec["markdown_path"])
    body_md = md_path.read_text(encoding="utf-8") if md_path.exists() else ""

    body_text = ""
    if "## Body" in body_md:
        body_text = body_md.split("## Body")[-1].strip()

    return _render(request, "email_detail.html",
                   email=email_rec, attachments=attachments, body_text=body_text)


@app.get("/attachment/{uuid}")
def serve_attachment(uuid: str):
    db = get_db()
    atts = db.conn.execute("SELECT * FROM attachments WHERE uuid = ?", (uuid,)).fetchone()
    db.close()
    if not atts:
        return HTMLResponse("Not found", status_code=404)
    path = Path(atts["source_path"])
    if not path.exists():
        return HTMLResponse("File not found on disk", status_code=404)
    ct = atts["content_type"] or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return FileResponse(str(path), media_type=ct, filename=atts["original_filename"])


@app.get("/folder/{folder_name:path}", response_class=HTMLResponse)
def folder_view(request: Request, folder_name: str, page: int = 1, per_page: int = 50):
    db = get_db()
    results = db.search("", folder=folder_name, limit=per_page + 1)
    has_next = len(results) > per_page
    results = results[:per_page]
    db.close()
    return _render(request, "folder.html",
                   folder_name=folder_name, results=results, page=page, has_next=has_next)


@app.get("/timeline", response_class=HTMLResponse)
def timeline(request: Request, after: str | None = None, before: str | None = None):
    db = get_db()
    sql = """
        SELECT date(date_iso) as day, COUNT(*) as count, pst_folder
        FROM emails
        WHERE date_iso IS NOT NULL AND date_iso != ''
    """
    params = []
    if after:
        sql += " AND date_iso >= ?"
        params.append(after)
    if before:
        sql += " AND date_iso <= ?"
        params.append(before)
    sql += " GROUP BY day, pst_folder ORDER BY day DESC LIMIT 500"

    rows = [dict(r) for r in db.conn.execute(sql, params).fetchall()]
    db.close()

    days: dict[str, dict] = {}
    for row in rows:
        day = row["day"]
        if day not in days:
            days[day] = {"day": day, "total": 0, "folders": {}}
        days[day]["total"] += row["count"]
        days[day]["folders"][row["pst_folder"]] = row["count"]

    return _render(request, "timeline.html",
                   days=list(days.values()), after=after, before=before)


@app.get("/thread/{thread_id:path}", response_class=HTMLResponse)
def thread_view(request: Request, thread_id: str):
    db = get_db()
    emails = []
    if hasattr(db, 'get_thread'):
        emails = db.get_thread(thread_id)
    else:
        # Fallback: search by thread_id in message_id/in_reply_to
        emails = [dict(r) for r in db.conn.execute(
            "SELECT * FROM emails WHERE thread_id = ? ORDER BY date_iso ASC",
            (thread_id,)
        ).fetchall()]
    db.close()
    return _render(request, "thread.html", thread_id=thread_id, emails=emails)


@app.post("/api/export", response_class=HTMLResponse)
def api_export(request: Request, uuids: str = ""):
    try:
        from janitor.export import export_evidence_package
    except ImportError:
        return HTMLResponse("Export module not yet available", status_code=501)

    uuid_list = [u.strip() for u in uuids.split(",") if u.strip()]
    if not uuid_list:
        return HTMLResponse("No emails selected", status_code=400)

    zip_path = export_evidence_package(uuid_list, f"export_{len(uuid_list)}_emails")
    return HTMLResponse(f'<a href="/exports/{Path(zip_path).name}" download>Download export ({len(uuid_list)} emails)</a>')


@app.get("/exports/{filename}")
def download_export(filename: str):
    export_dir = DISCOVERY_ROOT / "exports"
    path = export_dir / filename
    if not path.exists() or not path.is_file():
        return HTMLResponse("Export not found", status_code=404)
    return FileResponse(str(path), filename=filename)


@app.get("/api/stats")
def api_stats():
    db = get_db()
    stats = db.get_stats()
    folder_counts = db.folder_counts()
    stats["folder_counts"] = folder_counts
    db.close()
    return stats
