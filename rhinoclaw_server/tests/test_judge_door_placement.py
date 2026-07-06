"""Tests for the door domain judge (NEXT-LEVEL-PLAN 2.1 + 2.2).

Golden fixtures are the REAL measured values from the 2026-06-11 live
4-door demo proof (Rahmentuer_UD5.gh, lichtbreite 900/800):
RT01 0°  → bbox [[0, -88.998, 0], [1120, 95.998, 2180]]
RT02 90° → bbox [[3504.002, 0, 0], [3688.998, 1020, 2180]]
"""
import json
from unittest.mock import MagicMock, patch

import pytest

# Real measured bboxes (golden fixtures).
RT01_BBOX = [[0.0, -88.997878, 0.0], [1120.0, 95.997878, 2180.0]]
RT02_BBOX = [[3504.002122, 0.0, 0.0], [3688.997878, 1020.0, 2180.0]]
# Matching ground-truth opening axes: segment length == Lichtbreite.
RT01_OPENING = {"id": "O1", "start": [110, 0, 0], "end": [1010, 0, 0]}     # 900, X
RT02_OPENING = {"id": "O2", "start": [3600, 110, 0], "end": [3600, 910, 0]}  # 800, Y


# --- Pure core ---

def test_correct_door_passes_all_three_signals():
    from rhinoclaw.utils.door_judge import judge_door

    v = judge_door(RT01_BBOX, RT01_OPENING["start"], RT01_OPENING["end"])

    assert v["pass"] is True
    assert v["placed"] is True
    assert v["off_center_mm"] < 5          # measured: ~3.5 mm
    assert v["axis_deg_error"] == 0.0
    assert abs(v["width_error_mm"]) < 1    # 1120 - 900 - 220 = 0
    assert v["hint"] == ""


def test_rotated_door_on_y_opening_passes():
    from rhinoclaw.utils.door_judge import judge_door

    v = judge_door(RT02_BBOX, RT02_OPENING["start"], RT02_OPENING["end"])

    assert v["pass"] is True
    assert v["axis_deg_error"] == 0.0      # door Y-axis ↔ opening Y-axis
    assert abs(v["width_error_mm"]) < 1    # 1020 - 800 - 220 = 0


def test_goodhart_wrong_rotation_fails_despite_correct_claim():
    """THE forced test: geometry says 0°, the (ignored) claim says 90°."""
    from rhinoclaw.utils.door_judge import judge_door

    # RT01's real 0° geometry judged against a Y-axis opening — exactly what
    # a door with a wrong (un-applied) rotation but a "correct" request
    # looks like. The claim never enters the judge.
    y_opening = {"start": [560, -446.5, 0], "end": [560, 453.5, 0]}  # 900, Y
    v = judge_door(RT01_BBOX, y_opening["start"], y_opening["end"])

    assert v["pass"] is False
    assert v["axis_deg_error"] == pytest.approx(90.0)
    assert "rotate" in v["hint"].lower()
    assert v["hint"] != ""


def test_off_center_door_fails_with_shift_hint():
    from rhinoclaw.utils.door_judge import judge_door

    shifted = [[200.0, -89.0, 0.0], [1320.0, 96.0, 2180.0]]  # +200 in X
    v = judge_door(shifted, RT01_OPENING["start"], RT01_OPENING["end"])

    assert v["pass"] is False
    assert v["off_center_mm"] == pytest.approx(200.0, abs=5)
    assert "shift" in v["hint"].lower()


def test_wrong_width_fails_with_width_hint():
    from rhinoclaw.utils.door_judge import judge_door

    # 800-door geometry (extent 1020) on the 900 opening: -100 mm.
    narrow = [[160.0, -89.0, 0.0], [1180.0, 96.0, 2180.0]]
    v = judge_door(narrow, RT01_OPENING["start"], RT01_OPENING["end"])

    assert v["pass"] is False
    assert v["width_error_mm"] == pytest.approx(-100.0, abs=1)
    assert "narrower" in v["hint"]


def test_missing_geometry_is_not_placed():
    from rhinoclaw.utils.door_judge import judge_door

    v = judge_door(None, RT01_OPENING["start"], RT01_OPENING["end"])
    assert v == {
        "placed": False, "off_center_mm": None, "axis_deg_error": None,
        "width_error_mm": None, "pass": False,
        "hint": "No baked geometry found for this door — nothing to judge.",
    }


def test_matching_assigns_nearest_opening_once():
    from rhinoclaw.utils.door_judge import match_doors_to_openings

    assignment = match_doors_to_openings(
        [(560.0, 3.5), (3596.5, 510.0), None],
        [RT02_OPENING, RT01_OPENING],  # deliberately out of order
    )
    assert assignment == [1, 0, None]


# --- MCP tool: re-measures, never trusts claims ---

def _mock_rhino(bbox_by_call):
    rhino = MagicMock()
    calls = iter(bbox_by_call)

    def send_command(command, params=None):
        assert command == "get_objects_info"
        box = next(calls)
        if box is None:
            return {"count": 0, "results": []}
        return {"count": len(params["ids"]), "results": [
            {"geometry_details": {"bounding_box": {"min": box[0], "max": box[1]}}},
        ]}

    rhino.send_command.side_effect = send_command
    return rhino


def test_tool_remeasures_and_ignores_lying_baked_bbox():
    from rhinoclaw.tools.judge_door_placement import judge_door_placement

    # The door CLAIMS a perfect Y-oriented bbox, but the document's real
    # geometry (returned by get_objects_info) is X-oriented → must FAIL.
    lying_door = {
        "id": "RT01", "object_ids": ["g1"],
        "baked_bbox": [[3504, 0, 0], [3689, 1020, 2180]],  # the lie
        "rotation_applied": 90,                              # also a lie
        "wall_axis": "y", "width_requested": 900,
    }
    y_opening = {"id": "O1", "start": [560, -446.5, 0], "end": [560, 453.5, 0]}

    with patch("rhinoclaw.tools.judge_door_placement.get_rhino_connection",
               return_value=_mock_rhino([RT01_BBOX])), \
         patch("rhinoclaw.tools.judge_door_placement.interaction_logger") as log:
        data = json.loads(judge_door_placement(
            MagicMock(), [lying_door], openings=[y_opening]))

    [verdict] = data["data"]["verdicts"]
    assert verdict["pass"] is False
    assert verdict["axis_deg_error"] == pytest.approx(90.0)
    assert verdict["measured_bbox"] == RT01_BBOX  # the truth, not the claim
    # 2.2: the outcome was logged with the judge's verdict
    outcome = log.log_outcome.call_args[0][0]
    assert outcome["pass"] is False
    assert outcome["door_id"] == "RT01"
    assert outcome["wall_axis"] == "y"


def test_tool_full_benchmark_passes_and_logs():
    from rhinoclaw.tools.judge_door_placement import judge_door_placement

    doors = [
        {"id": "RT01", "object_ids": ["a"], "wall_axis": "x",
         "width_requested": 900, "rotation_applied": 0},
        {"id": "RT02", "object_ids": ["b"], "wall_axis": "y",
         "width_requested": 800, "rotation_applied": 90},
    ]
    with patch("rhinoclaw.tools.judge_door_placement.get_rhino_connection",
               return_value=_mock_rhino([RT01_BBOX, RT02_BBOX])), \
         patch("rhinoclaw.tools.judge_door_placement.interaction_logger") as log:
        data = json.loads(judge_door_placement(
            MagicMock(), doors, openings=[RT01_OPENING, RT02_OPENING]))

    assert data["data"]["passed"] == 2
    assert data["data"]["failed"] == 0
    assert {v["opening_id"] for v in data["data"]["verdicts"]} == {"O1", "O2"}
    assert log.log_outcome.call_count == 2


def test_tool_door_without_geometry_fails_gracefully():
    from rhinoclaw.tools.judge_door_placement import judge_door_placement

    with patch("rhinoclaw.tools.judge_door_placement.get_rhino_connection",
               return_value=_mock_rhino([None])), \
         patch("rhinoclaw.tools.judge_door_placement.interaction_logger"):
        data = json.loads(judge_door_placement(
            MagicMock(), [{"id": "RT09", "object_ids": ["gone"]}],
            openings=[RT01_OPENING]))

    [verdict] = data["data"]["verdicts"]
    assert verdict["placed"] is False
    assert verdict["pass"] is False
    assert verdict["objects_found"] == 0


def test_tool_rejects_doors_without_object_ids():
    from rhinoclaw.tools.judge_door_placement import judge_door_placement

    data = json.loads(judge_door_placement(
        MagicMock(), [{"id": "RT01", "baked_bbox": RT01_BBOX}],
        openings=[RT01_OPENING]))
    assert data["success"] is False
    assert "object_ids" in data["message"]


def test_outcome_logging_writes_placement_outcome_record(tmp_path):
    from rhinoclaw.utils.interaction_logger import InteractionLogger

    log = InteractionLogger(log_dir=str(tmp_path))
    log.log_outcome({"door_id": "RT01", "pass": True, "off_center_mm": 3.5,
                     "wall_axis": "x", "width_requested": 900})

    [log_file] = list(tmp_path.glob("interactions_*.jsonl"))
    [line] = log_file.read_text(encoding="utf-8").strip().splitlines()
    record = json.loads(line)
    assert record["tool_name"] == "judge_door_placement"
    assert record["success"] is True
    assert record["placement_outcome"]["door_id"] == "RT01"
    assert record["placement_outcome"]["wall_axis"] == "x"
