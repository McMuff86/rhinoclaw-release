"""Tests for the part-placement judge: pure verdict math + the MCP tool."""
import json
from unittest.mock import MagicMock, patch

import pytest

from rhinoclaw.config import reload_settings
from rhinoclaw.utils.part_math import flatten, frames_to_xform

PART_ID = "kauls/aufnahmeelement-band-stumpf-vx"
BLOCK_NAME = "Kauls Aufnahmeelement + Band Stumpf VX"
INSERTION = [0, 0, 0, 1, 0, 0, 0, 1, 0]
HINGE_AXIS = [-3.0, -12.5, 0.0, 1, 0, 0, 0, 1, 0]
BBOX_LOCAL = {"min": [-27.0, -22.5, -90.0], "max": [7.0, 30.0, 90.0]}
# The verified Kauls reference frame: 180-deg about Y at x0+900+4.
TARGET = [904.0, 0.0, 1000.0, -1, 0, 0, 0, 1, 0]

PART = {
    "id": PART_ID,
    "block": {"name": BLOCK_NAME},
    "frames": {"insertion": INSERTION, "hinge_axis": HINGE_AXIS},
    "insertion": {"det_rule": "+1"},
    "verification": {
        "bbox_local": BBOX_LOCAL,
        "expected_det": 1.0,
        "probes": [{
            "name": "axis_on_target",
            "type": "frame_axis_distance",
            "frame": "hinge_axis",
            "tol_mm": 0.5,
        }],
        "tolerances": {"position_mm": 0.5, "axis_deg": 1.0},
    },
}


def _perfect_measurement(target=TARGET):
    """Xform + world bbox of a placement that exactly matches the target."""
    from rhinoclaw.utils.part_judge import transformed_bbox, xform16_to_matrix
    xform = flatten(frames_to_xform(target, INSERTION))
    bbox = transformed_bbox(
        xform16_to_matrix(xform), BBOX_LOCAL["min"], BBOX_LOCAL["max"])
    return xform, bbox


class TestEvaluatePartPlacement:
    def test_perfect_placement_passes(self):
        from rhinoclaw.utils.part_judge import evaluate_part_placement

        xform, bbox = _perfect_measurement()
        verdict = evaluate_part_placement(PART, xform, bbox, TARGET)

        assert verdict["pass"] is True
        assert verdict["det"] == pytest.approx(1.0)
        assert verdict["det_pass"] is True
        assert verdict["probes"][0]["pass"] is True
        assert verdict["probes"][0]["distance_mm"] == pytest.approx(0.0)
        assert verdict["probes"][0]["angle_deg"] == pytest.approx(0.0)
        assert verdict["bbox"]["pass"] is True
        assert verdict["hint"] is None

    def test_mirrored_instance_fails_det_rule(self):
        from rhinoclaw.utils.part_judge import evaluate_part_placement

        mirror = [-1.0, 0, 0, 904.0, 0, 1.0, 0, 0.0,
                  0, 0, 1.0, 1000.0, 0, 0, 0, 1.0]  # det = -1
        verdict = evaluate_part_placement(PART, mirror, None, TARGET)

        assert verdict["pass"] is False
        assert verdict["det_pass"] is False
        assert verdict["det"] == pytest.approx(-1.0)
        assert "mirror" in verdict["hint"]

    def test_shifted_placement_fails_probe_with_distance(self):
        from rhinoclaw.utils.part_judge import evaluate_part_placement

        # Shift the instance 2 mm along world X: hinge axis (dir Z) moves
        # 2 mm off the expected axis — beyond tol_mm 0.5.
        shifted_target = [906.0, 0.0, 1000.0, -1, 0, 0, 0, 1, 0]
        xform, bbox = _perfect_measurement(shifted_target)
        verdict = evaluate_part_placement(PART, xform, bbox, TARGET)

        assert verdict["pass"] is False
        probe = verdict["probes"][0]
        assert probe["pass"] is False
        assert probe["distance_mm"] == pytest.approx(2.0)
        assert "axis_on_target" in verdict["hint"]

    def test_shift_along_probe_axis_still_passes(self):
        from rhinoclaw.utils.part_judge import evaluate_part_placement

        # Shift along world Z = along the hinge axis direction: the probe
        # point stays ON the expected axis (point-to-line distance), so
        # the axis probe passes — only the bbox moves.
        shifted_target = [904.0, 0.0, 1002.0, -1, 0, 0, 0, 1, 0]
        xform, _ = _perfect_measurement(shifted_target)
        verdict = evaluate_part_placement(PART, xform, None, TARGET)

        assert verdict["probes"][0]["distance_mm"] == pytest.approx(0.0)
        assert verdict["probes"][0]["pass"] is True

    def test_rotated_instance_fails_angle(self):
        from rhinoclaw.utils.part_judge import evaluate_part_placement

        # Rotate the placement 5 degrees about the world X axis: the hinge
        # direction (Z) tilts by 5 deg > tol 1 deg.
        import math
        c, s = math.cos(math.radians(5)), math.sin(math.radians(5))
        tilted_target = [904.0, 0.0, 1000.0, -1, 0, 0, 0, c, s]
        xform, _ = _perfect_measurement(tilted_target)
        verdict = evaluate_part_placement(PART, xform, None, TARGET)

        probe = verdict["probes"][0]
        assert probe["angle_deg"] == pytest.approx(5.0, abs=1e-6)
        assert probe["pass"] is False
        assert verdict["pass"] is False

    def test_bbox_drift_fails_generously(self):
        from rhinoclaw.utils.part_judge import evaluate_part_placement

        xform, bbox = _perfect_measurement()
        bbox["min"][0] -= 6.0  # 6 mm drift > default bbox_mm 5.0
        verdict = evaluate_part_placement(PART, xform, bbox, TARGET)

        assert verdict["bbox"]["pass"] is False
        assert verdict["bbox"]["max_dev_mm"] == pytest.approx(6.0)
        assert verdict["pass"] is False
        assert "stale" in verdict["hint"]

    def test_small_bbox_deviation_tolerated(self):
        from rhinoclaw.utils.part_judge import evaluate_part_placement

        xform, bbox = _perfect_measurement()
        bbox["max"][1] += 3.0  # within the generous 5 mm default
        verdict = evaluate_part_placement(PART, xform, bbox, TARGET)

        assert verdict["bbox"]["pass"] is True
        assert verdict["pass"] is True

    def test_tolerances_override(self):
        from rhinoclaw.utils.part_judge import evaluate_part_placement

        shifted_target = [906.0, 0.0, 1000.0, -1, 0, 0, 0, 1, 0]
        xform, _ = _perfect_measurement(shifted_target)
        verdict = evaluate_part_placement(
            PART, xform, None, TARGET,
            tolerances={"position_mm": 5.0})

        # probe tol_mm from part.json (0.5) still wins for the probe; the
        # override only moves the fallback: prove precedence explicitly.
        assert verdict["probes"][0]["tol_mm"] == 0.5
        assert verdict["probes"][0]["pass"] is False

    def test_probe_tol_fallback_uses_position_mm(self):
        from rhinoclaw.utils.part_judge import evaluate_part_placement

        part = json.loads(json.dumps(PART))
        del part["verification"]["probes"][0]["tol_mm"]
        shifted_target = [906.0, 0.0, 1000.0, -1, 0, 0, 0, 1, 0]
        xform, _ = _perfect_measurement(shifted_target)

        verdict = evaluate_part_placement(
            part, xform, None, TARGET, tolerances={"position_mm": 5.0})
        assert verdict["probes"][0]["tol_mm"] == 5.0
        assert verdict["probes"][0]["pass"] is True

    def test_unsupported_probe_type_skipped(self):
        from rhinoclaw.utils.part_judge import evaluate_part_placement

        part = json.loads(json.dumps(PART))
        part["verification"]["probes"].append(
            {"name": "future", "type": "volume_check"})
        xform, bbox = _perfect_measurement()
        verdict = evaluate_part_placement(part, xform, bbox, TARGET)

        assert verdict["pass"] is True  # skipped probe does not fail
        assert verdict["probes"][1]["pass"] is None


_PRINT_PREFIX = "Script successfully executed! Print output: "


def _script_response(payload):
    return {"result": _PRINT_PREFIX + json.dumps(payload)}


@pytest.fixture
def library(tmp_path, monkeypatch):
    lib = tmp_path / "part-library"
    part_dir = lib / "parts" / "kauls" / "aufnahmeelement-band-stumpf-vx"
    part_dir.mkdir(parents=True)
    (part_dir / "part.json").write_text(json.dumps(PART), encoding="utf-8")
    monkeypatch.setenv("RHINOCLAW_LIBRARY_DIR", str(lib))
    reload_settings()
    yield lib
    monkeypatch.undo()
    reload_settings()


class TestJudgePartPlacementTool:
    @patch("rhinoclaw.tools.judge_part_placement.interaction_logger")
    @patch("rhinoclaw.tools.judge_part_placement.get_rhino_connection")
    def test_pass_and_outcome_logged(self, mock_get_conn, mock_ilog, library):
        from rhinoclaw.tools.judge_part_placement import judge_part_placement

        xform, bbox = _perfect_measurement()
        rhino = MagicMock()
        rhino.send_command.return_value = _script_response({
            "found": True, "object_id": "inst-1", "object_name": "Band_1",
            "block_name": BLOCK_NAME, "xform": xform, "bbox": bbox,
        })
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(judge_part_placement(
            ctx, part_id=PART_ID, expected_frame=TARGET,
            object_id="inst-1", context="door-right-900"))

        assert parsed["success"] is True
        assert parsed["data"]["pass"] is True
        assert parsed["data"]["block_name_matches"] is True
        assert "PASS" in parsed["message"]

        outcome = mock_ilog.log_part_outcome.call_args[0][0]
        assert outcome["part_id"] == PART_ID
        assert outcome["context"] == "door-right-900"
        assert outcome["pass"] is True
        assert outcome["target_frame"] == TARGET
        assert len(outcome["xform"]) == 16
        # Anti-Goodhart: only measured values + ground truth in the record.
        assert "claimed" not in json.dumps(outcome)

    @patch("rhinoclaw.tools.judge_part_placement.interaction_logger")
    @patch("rhinoclaw.tools.judge_part_placement.get_rhino_connection")
    def test_instance_not_found_fails_gracefully(self, mock_get_conn,
                                                 mock_ilog, library):
        from rhinoclaw.tools.judge_part_placement import judge_part_placement

        rhino = MagicMock()
        rhino.send_command.return_value = _script_response(
            {"found": False, "candidates": []})
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(judge_part_placement(
            ctx, part_id=PART_ID, expected_frame=TARGET, name="missing"))

        assert parsed["success"] is True
        assert parsed["data"]["pass"] is False
        assert parsed["data"]["found"] is False
        assert mock_ilog.log_part_outcome.call_args[0][0]["pass"] is False

    @patch("rhinoclaw.tools.judge_part_placement.get_rhino_connection")
    def test_ambiguous_matches_error(self, mock_get_conn, library):
        from rhinoclaw.tools.judge_part_placement import judge_part_placement

        rhino = MagicMock()
        rhino.send_command.return_value = _script_response(
            {"found": False, "candidates": ["id-a", "id-b"]})
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(judge_part_placement(
            ctx, part_id=PART_ID, expected_frame=TARGET, name_prefix="Band"))

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]
        assert "id-a" in parsed["message"]

    @patch("rhinoclaw.tools.judge_part_placement.get_rhino_connection")
    def test_requires_lookup_parameter(self, mock_get_conn, library):
        from rhinoclaw.tools.judge_part_placement import judge_part_placement

        ctx = MagicMock()
        parsed = json.loads(judge_part_placement(
            ctx, part_id=PART_ID, expected_frame=TARGET))

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]
        mock_get_conn.assert_not_called()

    @patch("rhinoclaw.tools.judge_part_placement.get_rhino_connection")
    def test_invalid_expected_frame(self, mock_get_conn, library):
        from rhinoclaw.tools.judge_part_placement import judge_part_placement

        ctx = MagicMock()
        parsed = json.loads(judge_part_placement(
            ctx, part_id=PART_ID, expected_frame=[0, 0, 0], object_id="x"))

        assert parsed["success"] is False
        assert "expected_frame" in parsed["message"]

    @patch("rhinoclaw.tools.judge_part_placement.interaction_logger")
    @patch("rhinoclaw.tools.judge_part_placement.get_rhino_connection")
    def test_goodhart_wrong_placement_fails_despite_agent_claim(
            self, mock_get_conn, mock_ilog, library):
        """A 'perfect' claim cannot help — the measured xform decides."""
        from rhinoclaw.tools.judge_part_placement import judge_part_placement

        wrong_target = [950.0, 0.0, 1000.0, -1, 0, 0, 0, 1, 0]  # 46 mm off
        xform, bbox = _perfect_measurement(wrong_target)
        rhino = MagicMock()
        rhino.send_command.return_value = _script_response({
            "found": True, "object_id": "inst-2", "object_name": "Band_2",
            "block_name": BLOCK_NAME, "xform": xform, "bbox": bbox,
        })
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        parsed = json.loads(judge_part_placement(
            ctx, part_id=PART_ID, expected_frame=TARGET, object_id="inst-2"))

        assert parsed["data"]["pass"] is False
        assert parsed["data"]["probes"][0]["distance_mm"] == pytest.approx(46.0)

    @patch("rhinoclaw.tools.judge_part_placement.interaction_logger")
    @patch("rhinoclaw.tools.judge_part_placement.get_rhino_connection")
    def test_log_outcomes_false_writes_nothing(self, mock_get_conn,
                                               mock_ilog, library):
        from rhinoclaw.tools.judge_part_placement import judge_part_placement

        xform, bbox = _perfect_measurement()
        rhino = MagicMock()
        rhino.send_command.return_value = _script_response({
            "found": True, "object_id": "inst-1", "object_name": "b",
            "block_name": BLOCK_NAME, "xform": xform, "bbox": bbox,
        })
        mock_get_conn.return_value = rhino

        ctx = MagicMock()
        judge_part_placement(ctx, part_id=PART_ID, expected_frame=TARGET,
                             object_id="inst-1", log_outcomes=False)

        mock_ilog.log_part_outcome.assert_not_called()
