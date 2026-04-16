import pytest
from malm.rules import match_rule, load_rules

RULES = {
    "source": "~/Downloads",
    "keyword_rules": [
        {"id": "legal", "pattern": "(?i)(stevning|forlik|contract|claim|pant)", "dest": "~/Documents/Legal"},
        {"id": "finance", "pattern": "(?i)(balance|faktura|invoice|hovedbok)", "dest": "~/Documents/Finance"},
        {"id": "microsoft", "pattern": "(?i)(microsoft|azure|csp-auth|msgraph)", "dest": "~/Documents/Work/Microsoft"},
    ],
    "extension_rules": [
        {"id": "installers", "match": ["*.dmg", "*.iso", "*.pkg"], "dest": "~/Downloads/_Installers"},
        {"id": "archives", "match": ["*.zip", "*.tar.gz", "*.xz"], "dest": "~/Downloads/_Archives"},
        {"id": "images", "match": ["*.png", "*.jpg", "*.jpeg", "*.gif"], "dest": "~/Documents/Images"},
        {"id": "documents-pdf", "match": ["*.pdf"], "dest": "~/Documents/PDFs"},
        {"id": "documents-office", "match": ["*.docx", "*.xlsx"], "dest": "~/Documents/Office"},
        {"id": "data", "match": ["*.csv", "*.json", "*.xml"], "dest": "~/Documents/Data"},
    ],
    "defaults": {"dest": "~/Downloads/_Unsorted"},
}


def test_extension_match_dmg():
    dest, rule_id = match_rule("Antigravity.dmg", RULES)
    assert dest == "~/Downloads/_Installers"
    assert rule_id == "installers"


def test_extension_match_png():
    dest, rule_id = match_rule("Gemini_Generated_Image.png", RULES)
    assert dest == "~/Documents/Images"
    assert rule_id == "images"


def test_extension_match_pdf():
    dest, rule_id = match_rule("random-document.pdf", RULES)
    assert dest == "~/Documents/PDFs"
    assert rule_id == "documents-pdf"


def test_keyword_overrides_extension():
    """A PDF with 'stevning' in the name should go to Legal, not PDFs."""
    dest, rule_id = match_rule("01 2025-11-28 - Stevning.pdf", RULES)
    assert dest == "~/Documents/Legal"
    assert rule_id == "legal"


def test_keyword_finance():
    dest, rule_id = match_rule("Balance-2.pdf", RULES)
    assert dest == "~/Documents/Finance"
    assert rule_id == "finance"


def test_keyword_microsoft():
    dest, rule_id = match_rule("CSP-Authorization_2.19.pdf", RULES)
    assert dest == "~/Documents/Work/Microsoft"
    assert rule_id == "microsoft"


def test_keyword_case_insensitive():
    dest, rule_id = match_rule("FAKTURA-2026.pdf", RULES)
    assert dest == "~/Documents/Finance"
    assert rule_id == "finance"


def test_default_for_unknown():
    dest, rule_id = match_rule("FinalizeRemoteSSOut", RULES)
    assert dest == "~/Downloads/_Unsorted"
    assert rule_id == "default"


def test_dotfile_skipped():
    dest, rule_id = match_rule(".DS_Store", RULES)
    assert dest is None
    assert rule_id is None


def test_csv_to_data():
    dest, rule_id = match_rule("projects_rows.csv", RULES)
    assert dest == "~/Documents/Data"
    assert rule_id == "data"


def test_xlsx_to_office():
    dest, rule_id = match_rule("Hovedbok - Periode.xlsx", RULES)
    assert dest == "~/Documents/Finance"
    assert rule_id == "finance"
