import pytest

from janitor.pst_extract import (
    _decode_mime_header,
    _decode_payload,
    _sanitize,
)


class TestDecodePayload:
    def test_utf8(self):
        text = "Hei, dette er en test med norske tegn: æøå ÆØÅ"
        assert _decode_payload(text.encode("utf-8"), "utf-8") == text

    def test_windows_1252(self):
        text = "Brev fra konkursboet – påkrav og innsigelse"
        encoded = text.encode("windows-1252")
        result = _decode_payload(encoded, "windows-1252")
        assert "konkursboet" in result
        assert "påkrav" in result

    def test_iso_8859_1(self):
        text = "Oversendelse av brev"
        encoded = text.encode("iso-8859-1")
        assert _decode_payload(encoded, "iso-8859-1") == text

    def test_unknown_charset_falls_back(self):
        text = "Hei på deg"
        encoded = text.encode("windows-1252")
        result = _decode_payload(encoded, "unknown-8bit")
        assert "Hei" in result

    def test_empty_payload(self):
        assert _decode_payload(b"", "utf-8") == ""


class TestDecodeMimeHeader:
    def test_plain_ascii(self):
        assert _decode_mime_header("Hello World") == "Hello World"

    def test_utf8_encoded(self):
        # =?utf-8?B?...?= format
        encoded = "=?utf-8?B?SMOmcg==?="
        result = _decode_mime_header(encoded)
        assert "Hær" in result

    def test_unknown_8bit_charset(self):
        # Should not raise
        encoded = "=?unknown-8bit?Q?Hei?="
        result = _decode_mime_header(encoded)
        assert "Hei" in result

    def test_none_input(self):
        assert _decode_mime_header(None) == ""

    def test_empty_input(self):
        assert _decode_mime_header("") == ""


class TestSanitize:
    def test_basic(self):
        assert _sanitize("Hello World") == "Hello_World"

    def test_special_chars(self):
        result = _sanitize("RE: Brev fra konkursboet!")
        assert "/" not in result
        assert ":" not in result

    def test_max_length(self):
        long = "A" * 200
        assert len(_sanitize(long, max_len=80)) == 80

    def test_empty(self):
        assert _sanitize("") == "untitled"

    def test_norwegian_chars(self):
        result = _sanitize("Årsregnskap_og_økonomi")
        assert "rsregnskap" in result
