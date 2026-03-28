import json
import pytest
from pathlib import Path
from janitor.janitor import run_janitor


RULES = {
    "source": "REPLACED_AT_RUNTIME",
    "keyword_rules": [
        {"id": "legal", "pattern": "(?i)(stevning|contract)", "dest": "REPLACED"},
    ],
    "extension_rules": [
        {"id": "installers", "match": ["*.dmg"], "dest": "REPLACED"},
        {"id": "images", "match": ["*.png"], "dest": "REPLACED"},
        {"id": "documents-pdf", "match": ["*.pdf"], "dest": "REPLACED"},
    ],
    "defaults": {"dest": "REPLACED"},
}


@pytest.fixture
def workspace(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    docs_legal = tmp_path / "Documents" / "Legal"
    docs_images = tmp_path / "Documents" / "Images"
    docs_pdfs = tmp_path / "Documents" / "PDFs"
    installers = tmp_path / "Downloads" / "_Installers"
    unsorted = tmp_path / "Downloads" / "_Unsorted"

    rules = RULES.copy()
    rules["source"] = str(downloads)
    rules["keyword_rules"] = [
        {"id": "legal", "pattern": "(?i)(stevning|contract)", "dest": str(docs_legal)},
    ]
    rules["extension_rules"] = [
        {"id": "installers", "match": ["*.dmg"], "dest": str(installers)},
        {"id": "images", "match": ["*.png"], "dest": str(docs_images)},
        {"id": "documents-pdf", "match": ["*.pdf"], "dest": str(docs_pdfs)},
    ]
    rules["defaults"] = {"dest": str(unsorted)}

    rules_file = data_dir / "rules.json"
    rules_file.write_text(json.dumps(rules))

    return {
        "downloads": downloads,
        "data_dir": data_dir,
        "rules_file": rules_file,
        "db_path": str(data_dir / "janitor.db"),
        "lock_path": str(data_dir / "janitor.lock"),
    }


def _create_file(directory: Path, name: str, size: int = 100):
    f = directory / name
    f.write_bytes(b"x" * size)
    return f


def test_moves_dmg_to_installers(workspace):
    _create_file(workspace["downloads"], "App.dmg")
    result = run_janitor(
        rules_path=str(workspace["rules_file"]),
        db_path=workspace["db_path"],
        lock_path=workspace["lock_path"],
        dry_run=False,
    )
    assert not (workspace["downloads"] / "App.dmg").exists()
    assert result["moved"] == 1


def test_keyword_overrides_extension(workspace):
    _create_file(workspace["downloads"], "Stevning-2025.pdf")
    result = run_janitor(
        rules_path=str(workspace["rules_file"]),
        db_path=workspace["db_path"],
        lock_path=workspace["lock_path"],
        dry_run=False,
    )
    assert not (workspace["downloads"] / "Stevning-2025.pdf").exists()
    assert result["moved"] == 1


def test_dry_run_does_not_move(workspace):
    _create_file(workspace["downloads"], "photo.png")
    result = run_janitor(
        rules_path=str(workspace["rules_file"]),
        db_path=workspace["db_path"],
        lock_path=workspace["lock_path"],
        dry_run=True,
    )
    assert (workspace["downloads"] / "photo.png").exists()
    assert result["proposed"] == 1


def test_skips_dotfiles(workspace):
    _create_file(workspace["downloads"], ".DS_Store")
    result = run_janitor(
        rules_path=str(workspace["rules_file"]),
        db_path=workspace["db_path"],
        lock_path=workspace["lock_path"],
        dry_run=False,
    )
    assert result["moved"] == 0


def test_unknown_goes_to_unsorted(workspace):
    _create_file(workspace["downloads"], "mystery_binary")
    result = run_janitor(
        rules_path=str(workspace["rules_file"]),
        db_path=workspace["db_path"],
        lock_path=workspace["lock_path"],
        dry_run=False,
    )
    unsorted = Path(str(workspace["rules_file"])).parent.parent / "Downloads" / "_Unsorted"
    assert (unsorted / "mystery_binary").exists()
    assert result["moved"] == 1


def test_idempotent_second_run(workspace):
    _create_file(workspace["downloads"], "App.dmg")
    run_janitor(
        rules_path=str(workspace["rules_file"]),
        db_path=workspace["db_path"],
        lock_path=workspace["lock_path"],
        dry_run=False,
    )
    result = run_janitor(
        rules_path=str(workspace["rules_file"]),
        db_path=workspace["db_path"],
        lock_path=workspace["lock_path"],
        dry_run=False,
    )
    assert result["moved"] == 0


def test_file_deleted_between_runs(workspace):
    _create_file(workspace["downloads"], "gone.pdf")
    from janitor.db import JanitorDB
    db = JanitorDB(workspace["db_path"])
    db.discover_file("gone.pdf", ".pdf", 100, str(workspace["downloads"] / "gone.pdf"))
    db.close()
    (workspace["downloads"] / "gone.pdf").unlink()
    result = run_janitor(
        rules_path=str(workspace["rules_file"]),
        db_path=workspace["db_path"],
        lock_path=workspace["lock_path"],
        dry_run=False,
    )
    assert result["errors"] == 1


def test_multiple_files(workspace):
    _create_file(workspace["downloads"], "App.dmg")
    _create_file(workspace["downloads"], "photo.png")
    _create_file(workspace["downloads"], "Stevning.pdf")
    _create_file(workspace["downloads"], "unknown.bin")
    result = run_janitor(
        rules_path=str(workspace["rules_file"]),
        db_path=workspace["db_path"],
        lock_path=workspace["lock_path"],
        dry_run=False,
    )
    assert result["moved"] == 4
    assert result["errors"] == 0
