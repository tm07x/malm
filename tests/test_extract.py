import textwrap
from pathlib import Path

import pytest

from janitor.extract import extract_text, parse_eml, sha256_file


# --- text.py tests ---

def test_extract_text_txt(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("hello world foo bar")
    result = extract_text(f)
    assert result is not None
    assert "hello" in result["body_text"]
    assert isinstance(result["sheet_names"], list)
    assert isinstance(result["headers"], dict)
    assert isinstance(result["sample_rows"], dict)


def test_extract_text_csv(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("name,age\nAlice,30\nBob,25\n")
    result = extract_text(f)
    assert result is not None
    assert "name" in result["body_text"]
    assert "Alice" in result["body_text"]


def test_extract_text_json(tmp_path):
    f = tmp_path / "data.json"
    f.write_text('{"key": "value", "num": 42}')
    result = extract_text(f)
    assert result is not None
    assert "key" in result["body_text"]
    assert "value" in result["body_text"]


def test_extract_text_unsupported(tmp_path):
    f = tmp_path / "image.png"
    f.write_bytes(b"\x89PNG fake")
    assert extract_text(f) is None


# --- email_parser.py tests ---

def _make_eml(tmp_path, headers: str, body: str = "Hello body") -> Path:
    eml = tmp_path / "test.eml"
    eml.write_text(headers + "\n" + body)
    return eml


def test_parse_eml_simple(tmp_path):
    eml = _make_eml(tmp_path, textwrap.dedent("""\
        From: alice@example.com
        To: bob@example.com
        Subject: Test email
        Date: Mon, 01 Jan 2024 12:00:00 +0000
        Message-ID: <abc123@example.com>
        Content-Type: text/plain; charset="utf-8"
    """), "Hello body")
    result = parse_eml(eml)
    assert result["subject"] == "Test email"
    assert result["sender"] == "alice@example.com"
    assert result["to"] == "bob@example.com"
    assert "Hello body" in result["body"]
    assert result["message_id"] == "<abc123@example.com>"
    assert result["thread_id"] == "abc123@example.com"


def test_parse_eml_folded_header(tmp_path):
    eml = _make_eml(tmp_path, textwrap.dedent("""\
        From: alice@example.com
        To: bob@example.com,
         carol@example.com,
         dave@example.com
        Subject: Folded
        Date: Mon, 01 Jan 2024 12:00:00 +0000
        Content-Type: text/plain; charset="utf-8"
    """), "body text")
    result = parse_eml(eml)
    assert "\n" not in result["to"]
    assert "carol@example.com" in result["to"]


def test_parse_eml_thread_id_from_references(tmp_path):
    eml = _make_eml(tmp_path, textwrap.dedent("""\
        From: alice@example.com
        To: bob@example.com
        Subject: Re: Thread test
        Date: Mon, 01 Jan 2024 12:00:00 +0000
        Message-ID: <msg3@example.com>
        In-Reply-To: <msg2@example.com>
        References: <msg1@example.com> <msg2@example.com>
        Content-Type: text/plain; charset="utf-8"
    """), "reply body")
    result = parse_eml(eml)
    assert result["thread_id"] == "msg1@example.com"


# --- hasher.py tests ---

def test_sha256_same_content(tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("identical content")
    f2.write_text("identical content")
    assert sha256_file(f1) == sha256_file(f2)


def test_sha256_different_content(tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("content one")
    f2.write_text("content two")
    assert sha256_file(f1) != sha256_file(f2)
