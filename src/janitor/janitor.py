import shutil
from pathlib import Path

from janitor.db import JanitorDB
from janitor.lock import acquire_lock, release_lock
from janitor.rules import load_rules, match_rule


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
