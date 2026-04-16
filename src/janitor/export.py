import csv
import hashlib
import io
import json
import os
import shutil
import zipfile
from pathlib import Path

from janitor.store import DocumentStore

DEFAULT_DB = os.path.expanduser("~/Documents/Legal-Discovery/discovery.db")
DEFAULT_EXPORT_DIR = os.path.expanduser("~/Documents/Legal-Discovery/exports")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (FileNotFoundError, PermissionError):
        return ""


def _build_rows(store: DocumentStore, email_uuids: list[str]) -> list[dict]:
    rows = []
    for uid in email_uuids:
        email = store.get(uid)
        if not email:
            continue
        atts = store.get_children(uid)
        rows.append({
            "uuid": email["uuid"],
            "date": email.get("date_sent"),
            "sender": email.get("sender"),
            "recipients": email.get("recipients"),
            "subject": email.get("title"),
            "folder": email.get("folder"),
            "attachment_count": len(atts),
            "source_path": email.get("source_path"),
            "markdown_path": email.get("markdown_path"),
        })
    return rows


def export_csv(email_uuids: list[str], output_path: str, db_path: str = DEFAULT_DB) -> str:
    store = DocumentStore(db_path)
    try:
        rows = _build_rows(store, email_uuids)
        fieldnames = ["uuid", "date", "sender", "recipients", "subject", "folder",
                       "attachment_count", "source_path", "markdown_path"]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return output_path
    finally:
        store.close()


def export_evidence_package(email_uuids: list[str], package_name: str,
                            output_dir: str | None = None, db_path: str = DEFAULT_DB) -> str:
    store = DocumentStore(db_path)
    try:
        if output_dir is None:
            output_dir = DEFAULT_EXPORT_DIR
        os.makedirs(output_dir, exist_ok=True)
        zip_path = os.path.join(output_dir, f"{package_name}.zip")

        manifest_rows = []
        manifest_json = []

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for uid in email_uuids:
                doc = store.get(uid)
                if not doc:
                    continue
                children = store.get_children(uid)

                source_path = doc.get("source_path") or ""
                source_hash = _sha256(source_path)
                row = {
                    "uuid": doc["uuid"],
                    "date": doc.get("date_sent"),
                    "sender": doc.get("sender"),
                    "recipients": doc.get("recipients"),
                    "subject": doc.get("title"),
                    "folder": doc.get("folder"),
                    "attachment_count": len(children),
                    "source_path": source_path,
                    "markdown_path": doc.get("markdown_path"),
                    "sha256": source_hash,
                }
                manifest_rows.append(row)
                manifest_json.append({**doc, "attachments": [dict(c) for c in children], "sha256": source_hash})

                if source_path and os.path.isfile(source_path):
                    ext = Path(source_path).suffix or ".eml"
                    zf.write(source_path, f"emails/{uid}{ext}")

                md_path = doc.get("markdown_path") or ""
                if md_path and os.path.isfile(md_path):
                    zf.write(md_path, f"markdown/{uid}.md")

                for child in children:
                    cp = child.get("source_path") or ""
                    if cp and os.path.isfile(cp):
                        zf.write(cp,
                                 f"attachments/{uid}/{child.get('filename', 'unknown')}")

            fieldnames = ["uuid", "date", "sender", "recipients", "subject", "folder",
                          "attachment_count", "source_path", "markdown_path", "sha256"]
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(manifest_rows)
            zf.writestr("manifest.csv", buf.getvalue())

            zf.writestr("manifest.json", json.dumps(manifest_json, indent=2, default=str))

        return zip_path
    finally:
        store.close()


def export_from_search(query: str, folder: str | None = None, sender: str | None = None,
                       after: str | None = None, before: str | None = None,
                       package_name: str | None = None, output_dir: str | None = None,
                       db_path: str = DEFAULT_DB) -> str:
    store = DocumentStore(db_path)
    try:
        results = store.search(query, folder=folder, sender=sender, after=after, before=before)
        uuids = [r["uuid"] for r in results]
    finally:
        store.close()

    if not package_name:
        package_name = f"search-{query[:30].replace(' ', '_')}"

    return export_evidence_package(uuids, package_name, output_dir=output_dir, db_path=db_path)


def export_from_store(store: "DocumentStore", uuids: list[str], package_name: str,
                      output_dir: str | None = None) -> str:
    if output_dir is None:
        output_dir = DEFAULT_EXPORT_DIR
    os.makedirs(output_dir, exist_ok=True)
    zip_path = os.path.join(output_dir, f"{package_name}.zip")

    manifest_rows = []
    manifest_json = []

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for uid in uuids:
            doc = store.get(uid)
            if not doc:
                continue
            children = store.get_children(uid)

            source_hash = _sha256(doc.get("source_path") or "")
            row = {
                "uuid": doc["uuid"],
                "date": doc.get("date_sent"),
                "sender": doc.get("sender"),
                "recipients": doc.get("recipients"),
                "subject": doc.get("title"),
                "folder": doc.get("folder"),
                "attachment_count": len(children),
                "source_path": doc.get("source_path"),
                "markdown_path": doc.get("markdown_path"),
                "sha256": source_hash,
            }
            manifest_rows.append(row)
            manifest_json.append({**doc, "children": children, "sha256": source_hash})

            sp = doc.get("source_path") or ""
            if sp and os.path.isfile(sp):
                ext = Path(sp).suffix or ".eml"
                zf.write(sp, f"emails/{uid}{ext}")

            mp = doc.get("markdown_path") or ""
            if mp and os.path.isfile(mp):
                zf.write(mp, f"markdown/{uid}.md")

            for child in children:
                cp = child.get("source_path") or ""
                if cp and os.path.isfile(cp):
                    zf.write(cp, f"attachments/{uid}/{child.get('filename', 'unknown')}")

        fieldnames = ["uuid", "date", "sender", "recipients", "subject", "folder",
                      "attachment_count", "source_path", "markdown_path", "sha256"]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest_rows)
        zf.writestr("manifest.csv", buf.getvalue())

        zf.writestr("manifest.json", json.dumps(manifest_json, indent=2, default=str))

    return zip_path
