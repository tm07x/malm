import re
import json
import pytest
from malm.rules import load_rules, _validate_rules


def test_missing_extension_rules():
    with pytest.raises(ValueError, match="missing 'extension_rules'"):
        _validate_rules({"defaults": {"dest": "~/tmp"}})


def test_missing_defaults():
    with pytest.raises(ValueError, match="missing 'defaults.dest'"):
        _validate_rules({"extension_rules": []})


def test_invalid_keyword_regex():
    with pytest.raises(re.error):
        _validate_rules({
            "keyword_rules": [{"id": "bad", "pattern": "(?P<broken", "dest": "~/tmp"}],
            "extension_rules": [],
            "defaults": {"dest": "~/tmp"},
        })


def test_keyword_rule_missing_fields():
    with pytest.raises(ValueError, match="missing required field"):
        _validate_rules({
            "keyword_rules": [{"id": "incomplete"}],
            "extension_rules": [],
            "defaults": {"dest": "~/tmp"},
        })


def test_extension_rule_missing_fields():
    with pytest.raises(ValueError, match="missing required field"):
        _validate_rules({
            "extension_rules": [{"id": "no-match"}],
            "defaults": {"dest": "~/tmp"},
        })


def test_valid_rules_pass():
    _validate_rules({
        "keyword_rules": [{"id": "test", "pattern": "(?i)foo", "dest": "~/tmp"}],
        "extension_rules": [{"id": "txt", "match": ["*.txt"], "dest": "~/tmp"}],
        "defaults": {"dest": "~/tmp"},
    })


def test_load_rules_from_file(tmp_path):
    rules_file = tmp_path / "rules.json"
    rules_file.write_text(json.dumps({
        "source": "~/Downloads",
        "extension_rules": [{"id": "txt", "match": ["*.txt"], "dest": "~/tmp"}],
        "defaults": {"dest": "~/tmp"},
    }))
    rules = load_rules(str(rules_file))
    assert rules["source"] == "~/Downloads"


def test_load_rules_invalid_json(tmp_path):
    rules_file = tmp_path / "rules.json"
    rules_file.write_text("not json{{{")
    with pytest.raises(json.JSONDecodeError):
        load_rules(str(rules_file))
