import mimetypes
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from janitor.store import DocumentStore

DISCOVERY_ROOT = Path.home() / "Documents" / "Legal-Discovery"
DB_PATH = DISCOVERY_ROOT / "discovery.db"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="Legal Discovery")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _resolve_db_path() -> str:
    override = os.environ.get("JANITOR_DB_PATH")
    if override:
        return override
    unified = DISCOVERY_ROOT / "unified.db"
    if unified.exists():
        return str(unified)
    return str(DB_PATH)


_store: DocumentStore | None = None


def get_db() -> DocumentStore:
    global _store
    if _store is None:
        _store = DocumentStore(_resolve_db_path())
    return _store


def _render(request: Request, template: str, **ctx):
    return templates.TemplateResponse(request, template, ctx)


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: DocumentStore = Depends(get_db)):
    stats = db.stats()
    return _render(request, "index.html", stats=stats)


@app.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = "",
    doc_type: str | None = None,
    folder: str | None = None,
    sender: str | None = None,
    after: str | None = None,
    before: str | None = None,
    page: int = 1,
    per_page: int = 50,
    db: DocumentStore = Depends(get_db),
):
    offset = (page - 1) * per_page
    results = db.search(q, doc_type=doc_type, folder=folder, sender=sender,
                        after=after, before=before, limit=per_page + 1,
                        offset=offset)
    has_next = len(results) > per_page
    results = results[:per_page]
    folders = [r[0] for r in db.conn.execute(
        "SELECT DISTINCT folder FROM documents WHERE folder IS NOT NULL ORDER BY folder"
    ).fetchall()]

    ctx = dict(results=results, q=q, doc_type=doc_type, folder=folder, sender=sender,
               after=after, before=before, page=page, has_next=has_next)

    if request.headers.get("HX-Request"):
        return _render(request, "partials/email_list.html", **ctx)

    return _render(request, "search.html", folders=folders, **ctx)


@app.get("/doc/{uuid}", response_class=HTMLResponse)
def doc_detail(request: Request, uuid: str, db: DocumentStore = Depends(get_db)):
    doc = db.get(uuid)
    if not doc:
        return HTMLResponse("<h1>Not found</h1>", status_code=404)

    attachments = db.get_children(uuid) if doc["doc_type"] == "email" else []

    body_text = ""
    md_path = doc.get("markdown_path")
    if md_path:
        p = Path(md_path)
        if p.exists():
            body_md = p.read_text(encoding="utf-8")
            if "## Body" in body_md:
                body_text = body_md.split("## Body")[-1].strip()
            else:
                body_text = body_md

    return _render(request, "email_detail.html",
                   email=doc, attachments=attachments, body_text=body_text)


@app.get("/email/{uuid}", response_class=HTMLResponse)
def email_detail(request: Request, uuid: str, db: DocumentStore = Depends(get_db)):
    return doc_detail(request, uuid, db)


@app.get("/attachment/{uuid}")
def serve_attachment(uuid: str, db: DocumentStore = Depends(get_db)):
    doc = db.get(uuid)
    if not doc:
        return HTMLResponse("Not found", status_code=404)
    path = Path(doc["source_path"]).resolve()
    if not path.is_relative_to(DISCOVERY_ROOT):
        return HTMLResponse("Forbidden", status_code=403)
    if not path.exists():
        return HTMLResponse("File not found on disk", status_code=404)
    ct = doc.get("content_type") or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    fname = doc.get("filename") or path.name
    return FileResponse(str(path), media_type=ct, filename=fname)


@app.get("/folder/{folder_name:path}", response_class=HTMLResponse)
def folder_view(request: Request, folder_name: str, page: int = 1, per_page: int = 50,
                db: DocumentStore = Depends(get_db)):
    offset = (page - 1) * per_page
    results = db.search("", folder=folder_name, limit=per_page + 1, offset=offset)
    has_next = len(results) > per_page
    results = results[:per_page]
    return _render(request, "folder.html",
                   folder_name=folder_name, results=results, page=page, has_next=has_next)


@app.get("/timeline", response_class=HTMLResponse)
def timeline(request: Request, after: str | None = None, before: str | None = None,
             db: DocumentStore = Depends(get_db)):
    sql = """
        SELECT date(date_sent) as day, COUNT(*) as count, folder
        FROM documents
        WHERE date_sent IS NOT NULL AND date_sent != ''
    """
    params = []
    if after:
        sql += " AND date_sent >= ?"
        params.append(after)
    if before:
        sql += " AND date_sent <= ?"
        params.append(before)
    sql += " GROUP BY day, folder ORDER BY day DESC LIMIT 500"

    rows = [dict(r) for r in db.conn.execute(sql, params).fetchall()]

    days: dict[str, dict] = {}
    for row in rows:
        day = row["day"]
        if day not in days:
            days[day] = {"day": day, "total": 0, "folders": {}}
        days[day]["total"] += row["count"]
        days[day]["folders"][row["folder"] or "unknown"] = row["count"]

    return _render(request, "timeline.html",
                   days=list(days.values()), after=after, before=before)


@app.get("/thread/{thread_id:path}", response_class=HTMLResponse)
def thread_view(request: Request, thread_id: str, db: DocumentStore = Depends(get_db)):
    docs = db.get_thread(thread_id)
    return _render(request, "thread.html", thread_id=thread_id, emails=docs)


@app.post("/api/export", response_class=HTMLResponse)
def api_export(request: Request, uuids: str = ""):
    from janitor.export import export_evidence_package

    uuid_list = [u.strip() for u in uuids.split(",") if u.strip()]
    if not uuid_list:
        return HTMLResponse("No documents selected", status_code=400)

    zip_path = export_evidence_package(uuid_list, f"export_{len(uuid_list)}_docs")
    return HTMLResponse(f'<a href="/exports/{Path(zip_path).name}" download>Download export ({len(uuid_list)} documents)</a>')


@app.get("/exports/{filename}")
def download_export(filename: str):
    export_dir = DISCOVERY_ROOT / "exports"
    path = (export_dir / filename).resolve()
    if not path.is_relative_to(export_dir):
        return HTMLResponse("Forbidden", status_code=403)
    if not path.exists() or not path.is_file():
        return HTMLResponse("Export not found", status_code=404)
    return FileResponse(str(path), filename=filename)


@app.get("/api/stats")
def api_stats(db: DocumentStore = Depends(get_db)):
    return db.stats()
