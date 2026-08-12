"""Tests for library_doctor (UserDictionary + tight-bbox check, mocked Rhino)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from rhinoclaw.config import reload_settings

PART_ID = "kauls/aufnahmeelement-band-stumpf-vx"
BLOCK_NAME = "Kauls Aufnahmeelement + Band Stumpf VX"
BBOX_LOCAL = {"min": [-27.0, -22.5, -90.0], "max": [7.0, 30.0, 90.0]}

_PRINT_PREFIX = "Script successfully executed! Print output: "


def _script_response(payload):
    return {"result": _PRINT_PREFIX + json.dumps(payload)}


def _inspection(article=None, bompart=None, bbox=None, found=True):
    if not found:
        return {"found": False}
    return {
        "found": True,
        "definition_id": "def-guid-1",
        "object_count": 2,
        "user_dictionary_keys": (
            ([("ARTICLE_JSON")] if article is not None else [])
            + (["BOMPART_JSON"] if bompart is not None else [])),
        "article_json": article,
        "bompart_json": bompart,
        "bbox": bbox if bbox is not None else BBOX_LOCAL,
    }


@pytest.fixture
def library(tmp_path, monkeypatch):
    lib = tmp_path / "part-library"
    part_dir = lib / "parts" / "kauls" / "aufnahmeelement-band-stumpf-vx"
    part_dir.mkdir(parents=True)
    part_dir.joinpath("part.json").write_text(json.dumps({
        "id": PART_ID,
        "block": {"name": BLOCK_NAME},
        "erp": {"embedded": "none"},
        "verification": {"bbox_local": BBOX_LOCAL},
    }), encoding="utf-8")
    monkeypatch.setenv("RHINOCLAW_LIBRARY_DIR", str(lib))
    reload_settings()
    yield lib
    monkeypatch.undo()
    reload_settings()


def _set_embedded(library, declared):
    part_json = (library / "parts" / "kauls"
                 / "aufnahmeelement-band-stumpf-vx" / "part.json")
    data = json.loads(part_json.read_text(encoding="utf-8"))
    data["erp"]["embedded"] = declared
    part_json.write_text(json.dumps(data), encoding="utf-8")


class TestLibraryDoctor:
    @patch("rhinoclaw.tools.library_doctor.get_rhino_connection")
    def test_healthy_part(self, mock_get_conn, library):
        from rhinoclaw.tools.library_doctor import library_doctor

        rhino = MagicMock()
        rhino.send_command.return_value = _script_response(_inspection())
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(library_doctor(ctx, part_id=PART_ID))

        assert parsed["success"] is True
        data = parsed["data"]
        assert data["healthy"] is True
        assert data["definition_in_doc"] is True
        assert data["embedded"]["match"] is True
        assert data["bbox"]["match"] is True
        assert data["bbox"]["max_dev_mm"] == 0
        assert data["issues"] == []

    @patch("rhinoclaw.tools.library_doctor.get_rhino_connection")
    def test_definition_missing_in_doc(self, mock_get_conn, library):
        from rhinoclaw.tools.library_doctor import library_doctor

        rhino = MagicMock()
        rhino.send_command.return_value = _script_response(
            _inspection(found=False))
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(library_doctor(ctx, part_id=PART_ID))

        assert parsed["success"] is True
        assert parsed["data"]["healthy"] is False
        assert parsed["data"]["definition_in_doc"] is False
        assert "insert_library_part" in parsed["data"]["issues"][0]

    @patch("rhinoclaw.tools.library_doctor.get_rhino_connection")
    def test_undeclared_embedding_is_flagged(self, mock_get_conn, library):
        from rhinoclaw.tools.library_doctor import library_doctor

        rhino = MagicMock()
        rhino.send_command.return_value = _script_response(
            _inspection(article='{"article_no": "B2025"}'))
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(library_doctor(ctx, part_id=PART_ID))

        data = parsed["data"]
        assert data["healthy"] is False
        assert data["embedded"]["match"] is False
        assert data["embedded"]["article"]["present"] is True
        assert data["embedded"]["article"]["valid_json"] is True
        assert any("mismatch" in i for i in data["issues"])

    @patch("rhinoclaw.tools.library_doctor.get_rhino_connection")
    def test_declared_embedding_present_is_healthy(self, mock_get_conn, library):
        from rhinoclaw.tools.library_doctor import library_doctor

        _set_embedded(library, "article+bompart")
        rhino = MagicMock()
        rhino.send_command.return_value = _script_response(_inspection(
            article='{"article_no": "B2025"}',
            bompart='{"positions": []}'))
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(library_doctor(ctx, part_id=PART_ID))

        assert parsed["data"]["healthy"] is True
        assert parsed["data"]["embedded"]["match"] is True

    @patch("rhinoclaw.tools.library_doctor.get_rhino_connection")
    def test_declared_but_missing_embedding_is_flagged(self, mock_get_conn,
                                                       library):
        from rhinoclaw.tools.library_doctor import library_doctor

        _set_embedded(library, "article")
        rhino = MagicMock()
        rhino.send_command.return_value = _script_response(_inspection())
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(library_doctor(ctx, part_id=PART_ID))

        assert parsed["data"]["healthy"] is False
        assert parsed["data"]["embedded"]["match"] is False

    @patch("rhinoclaw.tools.library_doctor.get_rhino_connection")
    def test_invalid_embedded_json_is_flagged(self, mock_get_conn, library):
        from rhinoclaw.tools.library_doctor import library_doctor

        _set_embedded(library, "article")
        rhino = MagicMock()
        rhino.send_command.return_value = _script_response(
            _inspection(article="{not json"))
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(library_doctor(ctx, part_id=PART_ID))

        data = parsed["data"]
        assert data["healthy"] is False
        assert data["embedded"]["article"]["valid_json"] is False
        assert any("not valid JSON" in i for i in data["issues"])

    @patch("rhinoclaw.tools.library_doctor.get_rhino_connection")
    def test_bbox_drift_beyond_tenth_mm_fails(self, mock_get_conn, library):
        from rhinoclaw.tools.library_doctor import library_doctor

        drifted = {"min": [-27.0, -26.533, -90.0],   # 4 mm stale value
                   "max": [7.0, 30.0, 90.0]}
        rhino = MagicMock()
        rhino.send_command.return_value = _script_response(
            _inspection(bbox=drifted))
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(library_doctor(ctx, part_id=PART_ID))

        data = parsed["data"]
        assert data["healthy"] is False
        assert data["bbox"]["match"] is False
        assert data["bbox"]["max_dev_mm"] == pytest.approx(4.033)
        assert any("stale" in i for i in data["issues"])

    @patch("rhinoclaw.tools.library_doctor.get_rhino_connection")
    def test_tiny_bbox_deviation_within_tolerance(self, mock_get_conn, library):
        from rhinoclaw.tools.library_doctor import library_doctor

        nearly = {"min": [-27.0, -22.5, -90.05], "max": [7.05, 30.0, 90.0]}
        rhino = MagicMock()
        rhino.send_command.return_value = _script_response(
            _inspection(bbox=nearly))
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(library_doctor(ctx, part_id=PART_ID))

        assert parsed["data"]["bbox"]["match"] is True
        assert parsed["data"]["healthy"] is True

    @patch("rhinoclaw.tools.library_doctor.get_rhino_connection")
    def test_unknown_part_id_errors(self, mock_get_conn, library):
        from rhinoclaw.tools.library_doctor import library_doctor

        ctx = MagicMock()
        parsed = json.loads(library_doctor(ctx, part_id="nope/nope"))

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]
        mock_get_conn.assert_not_called()

    @patch("rhinoclaw.tools.library_doctor.get_rhino_connection")
    def test_library_unset_errors_with_hint(self, mock_get_conn, monkeypatch):
        from rhinoclaw.tools.library_doctor import library_doctor

        monkeypatch.delenv("RHINOCLAW_LIBRARY_DIR", raising=False)
        reload_settings()
        try:
            ctx = MagicMock()
            parsed = json.loads(library_doctor(ctx, part_id=PART_ID))
        finally:
            monkeypatch.undo()
            reload_settings()

        assert parsed["success"] is False
        assert "RHINOCLAW_LIBRARY_DIR" in parsed["message"]
