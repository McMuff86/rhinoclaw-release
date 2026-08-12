"""Tests for the find_library_part tool (offline catalog search)."""
import json
from unittest.mock import MagicMock

import pytest

from rhinoclaw.config import reload_settings

CATALOG = {
    "meta": {"generated": "2026-08-05", "schema": "rhino-part-catalog/1"},
    "parts": [
        {
            "id": "glutz-topaz-5632c",
            "display_name": "Glutz Topaz 5632C Drueckergarnitur",
            "vendor": "Glutz",
            "article_no": "5632C",
            "block_name": "GLUTZ Topaz 5632C",
            "frames": ["insertion", "spindle"],
            "keywords": ["drücker", "garnitur", "topaz"],
        },
        {
            "id": "glutz-treplane-1834",
            "display_name": "Glutz Treplane 1834 Schloss",
            "vendor": "Glutz",
            "article_no": "1834",
            "block_name": "Glutz Treplane 1834",
            "keywords": ["schloss", "schliessblech"],
        },
        # Deliberately sparse entry — the tool must tolerate missing fields.
        {"id": "sfs-he18"},
    ],
}


@pytest.fixture
def library(tmp_path, monkeypatch):
    lib = tmp_path / "part-library"
    lib.mkdir()
    (lib / "catalog.json").write_text(json.dumps(CATALOG), encoding="utf-8")
    monkeypatch.setenv("RHINOCLAW_LIBRARY_DIR", str(lib))
    reload_settings()
    yield lib
    monkeypatch.undo()
    reload_settings()


class TestSearch:
    def test_exact_article_no_wins(self, library):
        from rhinoclaw.tools.find_library_part import find_library_part

        parsed = json.loads(find_library_part(MagicMock(), query="5632C"))

        assert parsed["success"] is True
        assert parsed["data"]["matches"][0]["id"] == "glutz-topaz-5632c"
        assert "glutz-topaz-5632c" in parsed["message"]

    def test_keyword_match(self, library):
        from rhinoclaw.tools.find_library_part import find_library_part

        parsed = json.loads(find_library_part(MagicMock(), query="schliessblech"))

        assert parsed["success"] is True
        assert parsed["data"]["matches"][0]["id"] == "glutz-treplane-1834"

    def test_multiword_query(self, library):
        from rhinoclaw.tools.find_library_part import find_library_part

        parsed = json.loads(find_library_part(MagicMock(), query="glutz topaz"))

        assert parsed["success"] is True
        assert parsed["data"]["matches"][0]["id"] == "glutz-topaz-5632c"

    def test_limit(self, library):
        from rhinoclaw.tools.find_library_part import find_library_part

        parsed = json.loads(find_library_part(MagicMock(), query="glutz", limit=1))

        assert len(parsed["data"]["matches"]) == 1

    def test_sparse_entry_findable(self, library):
        from rhinoclaw.tools.find_library_part import find_library_part

        parsed = json.loads(find_library_part(MagicMock(), query="sfs-he18"))

        assert parsed["success"] is True
        assert parsed["data"]["matches"][0]["id"] == "sfs-he18"

    def test_no_match_returns_hint(self, library):
        from rhinoclaw.tools.find_library_part import find_library_part

        parsed = json.loads(find_library_part(MagicMock(), query="zzz-does-not-exist"))

        assert parsed["success"] is True
        assert parsed["data"]["matches"] == []
        assert "hint" in parsed["data"]
        assert parsed["data"]["catalog"]["part_count"] == 3

    def test_empty_query_is_invalid(self, library):
        from rhinoclaw.tools.find_library_part import find_library_part

        parsed = json.loads(find_library_part(MagicMock(), query="  "))

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]


class TestLibraryConfig:
    def test_env_unset_errors_with_hint(self, monkeypatch):
        from rhinoclaw.tools.find_library_part import find_library_part

        monkeypatch.delenv("RHINOCLAW_LIBRARY_DIR", raising=False)
        reload_settings()
        try:
            parsed = json.loads(find_library_part(MagicMock(), query="glutz"))
        finally:
            monkeypatch.undo()
            reload_settings()

        assert parsed["success"] is False
        assert "RHINOCLAW_LIBRARY_DIR" in parsed["message"]

    def test_missing_dir_errors_with_hint(self, monkeypatch, tmp_path):
        from rhinoclaw.tools.find_library_part import find_library_part

        monkeypatch.setenv("RHINOCLAW_LIBRARY_DIR", str(tmp_path / "nope"))
        reload_settings()
        try:
            parsed = json.loads(find_library_part(MagicMock(), query="glutz"))
        finally:
            monkeypatch.undo()
            reload_settings()

        assert parsed["success"] is False
        assert "does not exist" in parsed["message"]

    def test_missing_catalog_errors(self, monkeypatch, tmp_path):
        from rhinoclaw.tools.find_library_part import find_library_part

        lib = tmp_path / "empty-lib"
        lib.mkdir()
        monkeypatch.setenv("RHINOCLAW_LIBRARY_DIR", str(lib))
        reload_settings()
        try:
            parsed = json.loads(find_library_part(MagicMock(), query="glutz"))
        finally:
            monkeypatch.undo()
            reload_settings()

        assert parsed["success"] is False
        assert "catalog.json" in parsed["message"]
