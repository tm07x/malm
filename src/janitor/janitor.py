import shutil
from pathlib import Path

from janitor.content import read_file_content
from janitor.db import JanitorDB
from janitor.embeddings import get_embedding, serialize_f32
from janitor.lock import acquire_lock, release_lock
from janitor.rules import load_rules, match_content_rule, match_rule


def run_janitor(
    rules_path: str,
    db_path: str,
    lock_path: str,
    dry_run: bool = True,
) -> dict:
    acquire_lock(lock_path)
    try:
        return _run(rules_path, db_path, dry_run)
    finally:
        release_lock(lock_path)


def _run(rules_path: str, db_path: str, dry_run: bool) -> dict:
    rules = load_rules(rules_path)
    db = JanitorDB(db_path)
    source = Path(rules["source"]).expanduser()

    # Discover new files
    for entry in sorted(source.iterdir()):
        if entry.name.startswith(".") or entry.is_dir():
            continue
        ext = entry.suffix.lower() if entry.suffix else None
        db.discover_file(entry.name, ext, entry.stat().st_size, str(entry))

    # Process discovered files
    discovered = db.get_discovered_files()
    moved = 0
    errors = 0
    proposed = 0
    moves = []

    for row in discovered:
        src = Path(row["source_path"])

        if not src.exists():
            db.mark_error(row["id"], "file not found")
            errors += 1
            continue

        dest_dir, rule_id = match_rule(row["filename"], rules)
        if dest_dir is None:
            continue  # dotfile somehow got in, skip

        # Content-based reclassification for supported file types
        ext = row["extension"]
        if ext and any(ext in r.get("extensions", []) for r in rules.get("content_rules", [])):
            try:
                content = read_file_content(src)
                if content and content.get("cell_values"):
                    db.store_content(row["id"], content)
                    # Generate and store embedding
                    embed_text = f"{row['filename']}\n{' '.join(content.get('sheet_names', []))}\n{' '.join(content['cell_values'][:200])}"
                    try:
                        vec = get_embedding(embed_text)
                        db.store_embedding(row["id"], serialize_f32(vec))
                    except Exception:
                        pass  # embedding is best-effort
                    content_dest, content_rule = match_content_rule(ext, content["cell_values"], rules)
                    if content_dest:
                        dest_dir, rule_id = content_dest, content_rule
            except Exception:
                pass  # fall back to filename-based rule

        dest_path = Path(dest_dir).expanduser() / row["filename"]

        if dry_run:
            moves.append((row["filename"], str(dest_dir), rule_id))
            proposed += 1
            continue

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest_path))
            db.mark_moved(row["id"], str(dest_path), rule_id)
            moved += 1
        except Exception as e:
            db.mark_error(row["id"], str(e))
            errors += 1

    db.close()
    return {"moved": moved, "errors": errors, "proposed": proposed, "moves": moves}
