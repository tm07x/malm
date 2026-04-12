import csv
import hashlib
import io
import json
import os
import shutil
import zipfile
from pathlib import Path

from janitor.discovery_db import DiscoveryDB

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


def _build_rows(db: DiscoveryDB, email_uuids: list[str]) -> list[dict]:
    rows = []
    for uid in email_uuids:
        email = db.get_email(uid)
        if not email:
            continue
        atts = db.get_attachments(uid)
        rows.append({
            "uuid": email["uuid"],
            "date": email["date"],
            "sender": email["sender"],
            "recipients": email["recipients"],
            "subject": email["subject"],
            "folder": email["pst_folder"],
            "attachment_count": len(atts),
            "source_path": email["source_path"],
            "markdown_path": email["markdown_path"],
        })
    return rows


def export_csv(email_uuids: list[str], output_path: str, db_path: str = DEFAULT_DB) -> str:
    db = DiscoveryDB(db_path)
    try:
        rows = _build_rows(db, email_uuids)
        fieldnames = ["uuid", "date", "sender", "recipients", "subject", "folder",
                       "attachment_count", "source_path", "markdown_path"]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return output_path
    finally:
        db.close()


def export_evidence_package(email_uuids: list[str], package_name: str,
                            output_dir: str | None = None, db_path: str = DEFAULT_DB) -> str:
    db = DiscoveryDB(db_path)
    try:
        if output_dir is None:
            output_dir = DEFAULT_EXPORT_DIR
        os.makedirs(output_dir, exist_ok=True)
        zip_path = os.path.join(output_dir, f"{package_name}.zip")

        manifest_rows = []
        manifest_json = []

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for uid in email_uuids:
                email = db.get_email(uid)
                if not email:
                    continue
                atts = db.get_attachments(uid)

                source_hash = _sha256(email["source_path"])
                row = {
                    "uuid": email["uuid"],
                    "date": email["date"],
                    "sender": email["sender"],
                    "recipients": email["recipients"],
                    "subject": email["subject"],
                    "folder": email["pst_folder"],
                    "attachment_count": len(atts),
                    "source_path": email["source_path"],
                    "markdown_path": email["markdown_path"],
                    "sha256": source_hash,
                }
                manifest_rows.append(row)
                manifest_json.append({**dict(email), "attachments": atts, "sha256": source_hash})

                if os.path.isfile(email["source_path"]):
                    ext = Path(email["source_path"]).suffix or ".eml"
                    zf.write(email["source_path"], f"emails/{uid}{ext}")

                if email["markdown_path"] and os.path.isfile(email["markdown_path"]):
                    zf.write(email["markdown_path"], f"markdown/{uid}.md")

                for att in atts:
                    if os.path.isfile(att["source_path"]):
                        zf.write(att["source_path"],
                                 f"attachments/{uid}/{att['original_filename']}")

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
        db.close()


def export_from_search(query: str, folder: str | None = None, sender: str | None = None,
                       after: str | None = None, before: str | None = None,
                       package_name: str | None = None, output_dir: str | None = None,
                       db_path: str = DEFAULT_DB) -> str:
    db = DiscoveryDB(db_path)
    try:
        results = db.search(query, folder=folder, sender=sender, after=after, before=before)
        uuids = [r["uuid"] for r in results]
    finally:
        db.close()

    if not package_name:
        package_name = f"search-{query[:30].replace(' ', '_')}"

    return export_evidence_package(uuids, package_name, output_dir=output_dir, db_path=db_path)
