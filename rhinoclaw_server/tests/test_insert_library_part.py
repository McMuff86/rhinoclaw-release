"""Tests for the insert_library_part tool (mocked Rhino + mocked library)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from rhinoclaw.config import reload_settings

PART_ID = "glutz-5632c"
BLOCK_NAME = "GLUTZ Topaz 5632C"
IDENTITY_16 = [1.0, 0.0, 0.0, 0.0,
               0.0, 1.0, 0.0, 0.0,
               0.0, 0.0, 1.0, 0.0,
               0.0, 0.0, 0.0, 1.0]


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A minimal on-disk part library + RHINOCLAW_LIBRARY_DIR pointing at it."""
    lib = tmp_path / "part-library"
    part_dir = lib / "parts" / PART_ID
    part_dir.mkdir(parents=True)
    (part_dir / "part.3dm").write_bytes(b"")
    (part_dir / "part.json").write_text(json.dumps({
        "schema": "rhino-part/1",
        "id": PART_ID,
        "block": {"name": BLOCK_NAME},
        "frames": [
            {"name": "insertion", "plane": [0, 0, 0, 1, 0, 0, 0, 1, 0]},
            {"name": "spindle", "plane": [10, 0, 45, 1, 0, 0, 0, 1, 0]},
        ],
        "insertion": {"det_rule": "+1"},
        "verification": {"status": "verified"},
    }), encoding="utf-8")
    (lib / "catalog.json").write_text(json.dumps({
        "meta": {"generated": "2026-08-05"},
        "parts": [{"id": PART_ID, "display_name": "Glutz Topaz 5632C",
                   "block_name": BLOCK_NAME}],
    }), encoding="utf-8")

    monkeypatch.setenv("RHINOCLAW_LIBRARY_DIR", str(lib))
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    reload_settings()
    yield lib
    monkeypatch.undo()
    reload_settings()


def _mock_rhino(result=None):
    rhino = MagicMock()
    rhino.send_command.return_value = result if result is not None else {
        "object_id": "obj-guid-1",
        "block_name": BLOCK_NAME,
        "definition_created": False,
        "det": 1.0,
        "bbox": {"min": [0, 0, 0], "max": [1, 1, 1]},
    }
    return rhino


class TestValidation:
    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_requires_part_id_or_block_name(self, mock_get_conn):
        from rhinoclaw.tools.insert_library_part import insert_library_part

        ctx = MagicMock()
        parsed = json.loads(insert_library_part(
            ctx, target_frame=[0, 0, 0, 1, 0, 0, 0, 1, 0]))

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]
        mock_get_conn.assert_not_called()

    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_target_frame_must_have_9_values(self, mock_get_conn):
        from rhinoclaw.tools.insert_library_part import insert_library_part

        ctx = MagicMock()
        parsed = json.loads(insert_library_part(
            ctx, target_frame=[0, 0, 0], block_name="B"))

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]
        assert "target_frame" in parsed["message"]

    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_source_frame_must_have_9_values(self, mock_get_conn):
        from rhinoclaw.tools.insert_library_part import insert_library_part

        ctx = MagicMock()
        parsed = json.loads(insert_library_part(
            ctx, target_frame=[0, 0, 0, 1, 0, 0, 0, 1, 0],
            source_frame=[1, 2], block_name="B"))

        assert parsed["success"] is False
        assert "source_frame" in parsed["message"]


class TestDirectBlockName:
    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_identity_target_sends_identity_xform(self, mock_get_conn):
        from rhinoclaw.tools.insert_library_part import insert_library_part

        rhino = _mock_rhino()
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(insert_library_part(
            ctx, target_frame=[0, 0, 0, 1, 0, 0, 0, 1, 0], block_name="Chair"))

        assert parsed["success"] is True
        cmd, params = rhino.send_command.call_args[0]
        assert cmd == "insert_library_part"
        assert params["block_name"] == "Chair"
        assert params["xform"] == pytest.approx(IDENTITY_16)
        assert "file_path" not in params

    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_kauls_matrix_target(self, mock_get_conn):
        """Rotated target (X = -world-X): rotation diag(-1,+1,-1) + translation."""
        from rhinoclaw.tools.insert_library_part import insert_library_part

        rhino = _mock_rhino()
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(insert_library_part(
            ctx, target_frame=[120.5, 44.0, 910.0, -1, 0, 0, 0, 1, 0],
            block_name="Part"))

        assert parsed["success"] is True
        x = rhino.send_command.call_args[0][1]["xform"]
        # Row-major: diag(-1, +1, -1), translation in column 3.
        assert x[0] == pytest.approx(-1)
        assert x[5] == pytest.approx(1)
        assert x[10] == pytest.approx(-1)
        assert (x[3], x[7], x[11]) == pytest.approx((120.5, 44.0, 910.0))
        assert (x[12], x[13], x[14], x[15]) == pytest.approx((0, 0, 0, 1))

    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_attributes_forwarded(self, mock_get_conn):
        from rhinoclaw.tools.insert_library_part import insert_library_part

        rhino = _mock_rhino()
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        attrs = {"name": "Beschlag_1", "layer": "Beschlaege",
                 "group": "Tuer_07", "user_strings": {"article_no": "5632C"}}
        insert_library_part(
            ctx, target_frame=[0, 0, 0, 1, 0, 0, 0, 1, 0],
            block_name="Part", attributes=attrs)

        assert rhino.send_command.call_args[0][1]["attributes"] == attrs


class TestPartIdPath:
    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_loads_block_name_and_translates_path(self, mock_get_conn, library):
        from rhinoclaw.tools.insert_library_part import insert_library_part

        rhino = _mock_rhino()
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(insert_library_part(
            ctx, target_frame=[0, 0, 0, 1, 0, 0, 0, 1, 0], part_id=PART_ID))

        assert parsed["success"] is True
        assert parsed["data"]["part_id"] == PART_ID
        params = rhino.send_command.call_args[0][1]
        assert params["block_name"] == BLOCK_NAME
        # WSL path -> Windows UNC path so Rhino on Windows can open it.
        assert params["file_path"].startswith("\\\\path\to\your\directory")
        assert params["file_path"].endswith("part.3dm")
        assert "/" not in params["file_path"]

    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_named_frame_used_as_source(self, mock_get_conn, library):
        from rhinoclaw.tools.insert_library_part import insert_library_part

        rhino = _mock_rhino()
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        # Source frame "spindle" sits at (10, 0, 45); mapping it onto the
        # world origin means translating by (-10, 0, -45).
        parsed = json.loads(insert_library_part(
            ctx, target_frame=[0, 0, 0, 1, 0, 0, 0, 1, 0],
            part_id=PART_ID, frame_name="spindle"))

        assert parsed["success"] is True
        x = rhino.send_command.call_args[0][1]["xform"]
        assert (x[3], x[7], x[11]) == pytest.approx((-10, 0, -45))

    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_unknown_frame_name_errors(self, mock_get_conn, library):
        from rhinoclaw.tools.insert_library_part import insert_library_part

        ctx = MagicMock()
        parsed = json.loads(insert_library_part(
            ctx, target_frame=[0, 0, 0, 1, 0, 0, 0, 1, 0],
            part_id=PART_ID, frame_name="nope"))

        assert parsed["success"] is False
        assert "nope" in parsed["message"]
        assert "insertion" in parsed["message"]  # lists available frames
        mock_get_conn.assert_not_called()

    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_explicit_block_name_overrides_part_json(self, mock_get_conn, library):
        from rhinoclaw.tools.insert_library_part import insert_library_part

        rhino = _mock_rhino()
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        insert_library_part(
            ctx, target_frame=[0, 0, 0, 1, 0, 0, 0, 1, 0],
            part_id=PART_ID, block_name="Override")

        assert rhino.send_command.call_args[0][1]["block_name"] == "Override"

    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_unknown_part_id_errors_with_hint(self, mock_get_conn, library):
        from rhinoclaw.tools.insert_library_part import insert_library_part

        ctx = MagicMock()
        parsed = json.loads(insert_library_part(
            ctx, target_frame=[0, 0, 0, 1, 0, 0, 0, 1, 0], part_id="does-not-exist"))

        assert parsed["success"] is False
        assert "does-not-exist" in parsed["message"]
        mock_get_conn.assert_not_called()

    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_library_dir_unset_errors_with_hint(self, mock_get_conn, monkeypatch):
        from rhinoclaw.tools.insert_library_part import insert_library_part

        monkeypatch.delenv("RHINOCLAW_LIBRARY_DIR", raising=False)
        reload_settings()
        try:
            ctx = MagicMock()
            parsed = json.loads(insert_library_part(
                ctx, target_frame=[0, 0, 0, 1, 0, 0, 0, 1, 0], part_id=PART_ID))
        finally:
            monkeypatch.undo()
            reload_settings()

        assert parsed["success"] is False
        assert "RHINOCLAW_LIBRARY_DIR" in parsed["message"]


class TestDetRule:
    @patch("rhinoclaw.tools.insert_library_part.frames_to_xform")
    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_mirror_transform_is_rejected(self, mock_get_conn, mock_frames, library):
        """det_rule '+1' + det < 0 must refuse to insert, clearly worded.

        Frame pairs always produce det +1 (Z = X x Y), so the guard is
        defense in depth; force a mirror matrix to prove it trips.
        """
        from rhinoclaw.tools.insert_library_part import insert_library_part

        mock_frames.return_value = [
            [-1.0, 0.0, 0.0, 5.0],
            [0.0, 1.0, 0.0, 6.0],
            [0.0, 0.0, 1.0, 7.0],
            [0.0, 0.0, 0.0, 1.0],
        ]

        ctx = MagicMock()
        parsed = json.loads(insert_library_part(
            ctx, target_frame=[0, 0, 0, 1, 0, 0, 0, 1, 0], part_id=PART_ID))

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]
        assert "det_rule" in parsed["message"]
        assert "MIRROR" in parsed["message"]
        mock_get_conn.assert_not_called()


class TestNestedPartIdAndBlockFile:
    """Real library layout: parts/<vendor>/<part>/ + block.file naming."""

    NESTED_ID = "kauls/aufnahmeelement-band-stumpf-vx"
    NESTED_BLOCK = "Kauls Aufnahmeelement + Band Stumpf VX"

    @pytest.fixture
    def nested_library(self, library):
        part_dir = library / "parts" / "kauls" / "aufnahmeelement-band-stumpf-vx"
        part_dir.mkdir(parents=True)
        (part_dir / f"{self.NESTED_BLOCK}.3dm").write_bytes(b"")
        (part_dir / "part.json").write_text(json.dumps({
            "schema_version": "1.0",
            "id": self.NESTED_ID,
            "block": {"name": self.NESTED_BLOCK,
                      "file": f"{self.NESTED_BLOCK}.3dm"},
            "frames": {
                "insertion": [0, 0, 0, 1, 0, 0, 0, 1, 0],
                "hinge_axis": [-3.0, -12.5, 0.0, 1, 0, 0, 0, 1, 0],
            },
            "insertion": {"det_rule": "+1"},
        }), encoding="utf-8")
        return library

    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_vendor_subfolder_id_resolves(self, mock_get_conn, nested_library):
        from rhinoclaw.tools.insert_library_part import insert_library_part

        rhino = _mock_rhino()
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(insert_library_part(
            ctx, target_frame=[0, 0, 0, 1, 0, 0, 0, 1, 0], part_id=self.NESTED_ID))

        assert parsed["success"] is True
        params = rhino.send_command.call_args[0][1]
        assert params["block_name"] == self.NESTED_BLOCK
        # .3dm filename comes from block.file, not a hardcoded part.3dm.
        assert params["file_path"].endswith(f"{self.NESTED_BLOCK}.3dm")
        assert params["file_path"].startswith("\\\\path\to\your\directory")

    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_traversal_part_id_rejected(self, mock_get_conn, nested_library):
        from rhinoclaw.tools.insert_library_part import insert_library_part

        ctx = MagicMock()
        parsed = json.loads(insert_library_part(
            ctx, target_frame=[0, 0, 0, 1, 0, 0, 0, 1, 0],
            part_id="kauls/../../../etc"))

        assert parsed["success"] is False
        assert "Invalid part_id" in parsed["message"]
        mock_get_conn.assert_not_called()


class TestFrameShapeTolerance:
    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_frames_as_dict(self, mock_get_conn, library):
        """part.json may store frames as {name: [9 doubles]} instead of a list."""
        from rhinoclaw.tools.insert_library_part import insert_library_part

        part_json = library / "parts" / PART_ID / "part.json"
        data = json.loads(part_json.read_text(encoding="utf-8"))
        data["frames"] = {"insertion": [1, 2, 3, 1, 0, 0, 0, 1, 0]}
        part_json.write_text(json.dumps(data), encoding="utf-8")

        rhino = _mock_rhino()
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(insert_library_part(
            ctx, target_frame=[1, 2, 3, 1, 0, 0, 0, 1, 0], part_id=PART_ID))

        assert parsed["success"] is True
        # Source == target -> identity transform.
        assert rhino.send_command.call_args[0][1]["xform"] == pytest.approx(IDENTITY_16)


class TestErrors:
    @patch("rhinoclaw.tools.insert_library_part.get_rhino_connection")
    def test_rhino_error(self, mock_get_conn):
        from rhinoclaw.tools.insert_library_part import insert_library_part

        rhino = MagicMock()
        rhino.send_command.side_effect = Exception("Failed to insert file")
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(insert_library_part(
            ctx, target_frame=[0, 0, 0, 1, 0, 0, 0, 1, 0], block_name="B"))

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]
