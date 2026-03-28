import json
import re
from fnmatch import fnmatch
from pathlib import Path


def load_rules(path: str) -> dict:
    with open(path) as f:
        rules = json.load(f)
    _validate_rules(rules)
    return rules


def _validate_rules(rules: dict) -> None:
    if "extension_rules" not in rules:
        raise ValueError("rules.json missing 'extension_rules'")
    if "defaults" not in rules or "dest" not in rules["defaults"]:
        raise ValueError("rules.json missing 'defaults.dest'")
    for rule in rules.get("keyword_rules", []):
        if "id" not in rule or "pattern" not in rule or "dest" not in rule:
            raise ValueError(f"keyword rule missing required field: {rule}")
        re.compile(rule["pattern"])  # validate regex
    for rule in rules["extension_rules"]:
        if "id" not in rule or "match" not in rule or "dest" not in rule:
            raise ValueError(f"extension rule missing required field: {rule}")


def match_rule(filename: str, rules: dict) -> tuple[str | None, str | None]:
    if filename.startswith("."):
        return None, None

    for rule in rules.get("keyword_rules", []):
        if re.search(rule["pattern"], filename):
            return rule["dest"], rule["id"]

    for rule in rules["extension_rules"]:
        for pattern in rule["match"]:
            if fnmatch(filename.lower(), pattern):
                return rule["dest"], rule["id"]

    return rules["defaults"]["dest"], "default"
