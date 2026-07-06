"""Tests for the loop-closing pair: recipe distiller (3.1) + recall (3.2)."""
import json
from unittest.mock import MagicMock, patch


def _write_log(log_dir, day, records):
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"interactions_{day}.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _outcome(door_id, passed, off_center, wall_axis="x", rotation=0,
             width=900, definition="C:/gh/Rahmentuer_UD5.gh",
             timestamp="2026-06-11T10:00:00+00:00"):
    return {
        "timestamp": timestamp,
        "session_id": "s1",
        "tool_name": "judge_door_placement",
        "tool_args": {},
        "success": passed,
        "placement_outcome": {
            "door_id": door_id, "pass": passed, "off_center_mm": off_center,
            "axis_deg_error": 0.0, "width_error_mm": 0.0,
            "wall_axis": wall_axis, "width_requested": width,
            "rotation_applied": rotation, "definition": definition,
        },
    }


def test_distill_keeps_only_passing_and_picks_lowest_off_center(tmp_path):
    from rhinoclaw.utils.recipe_distiller import distill

    _write_log(tmp_path, "20260610", [
        _outcome("RT01", True, 12.0, rotation=0),
        _outcome("RT02", False, 500.0, rotation=180),     # fail → excluded
        {"tool_name": "ping", "success": True},            # no outcome → skip
    ])
    _write_log(tmp_path, "20260611", [
        _outcome("RT05", True, 3.5, rotation=0,
                 timestamp="2026-06-11T12:00:00+00:00"),   # better → wins
    ])

    recipes = distill(tmp_path)

    [(key, entry)] = recipes.items()
    assert key == "rahmentuer_ud5.gh|x"
    assert entry["rotation"] == 0
    assert entry["off_center_mm"] == 3.5          # best, not latest
    assert entry["confidence"] == 2                # passing records only
    assert entry["last_seen"] == "2026-06-11T12:00:00+00:00"
    # registry persisted next to the logs
    on_disk = json.loads((tmp_path / "door_recipes.json").read_text())
    assert on_disk == recipes


def test_distill_separates_axes_and_door_types(tmp_path):
    from rhinoclaw.utils.recipe_distiller import distill, lookup

    _write_log(tmp_path, "20260611", [
        _outcome("A", True, 3.5, wall_axis="x", rotation=0, width=900),
        _outcome("B", True, 3.5, wall_axis="y", rotation=90, width=800),
        _outcome("C", True, 2.0, wall_axis="x", rotation=0,
                 definition="C:/gh/Rahmentuer_UD3.gh"),
    ])

    recipes = distill(tmp_path)

    assert len(recipes) == 3
    assert lookup(recipes, "Rahmentuer_UD5.gh", "y")["rotation"] == 90
    # lookup normalizes paths and case
    assert lookup(recipes, "c:/somewhere/RAHMENTUER_UD3.GH", "x")["off_center_mm"] == 2.0
    assert lookup(recipes, "Rahmentuer_UD5.gh", "z") is None


def test_recall_tool_cold_start_miss(tmp_path):
    from rhinoclaw.tools.recall_placements import recall_placements

    fake_logger = MagicMock()
    fake_logger._log_dir = tmp_path
    with patch("rhinoclaw.tools.recall_placements.interaction_logger",
               fake_logger):
        data = json.loads(recall_placements(
            MagicMock(), "Rahmentuer_UD5.gh", "x"))

    assert data["success"] is True
    assert data["data"]["found"] is False
    assert "defaults" in data["data"]["hint"]


def test_recall_tool_returns_best_after_one_passing_run(tmp_path):
    from rhinoclaw.tools.recall_placements import recall_placements

    _write_log(tmp_path, "20260611", [
        _outcome("RT02", True, 3.5, wall_axis="y", rotation=90, width=800),
    ])
    fake_logger = MagicMock()
    fake_logger._log_dir = tmp_path
    with patch("rhinoclaw.tools.recall_placements.interaction_logger",
               fake_logger):
        data = json.loads(recall_placements(
            MagicMock(), "C:/anywhere/Rahmentuer_UD5.gh", "y"))

    d = data["data"]
    assert d["found"] is True
    assert d["rotation"] == 90
    assert d["width"] == 800
    assert d["confidence"] >= 1
    assert d["last_seen"]


def test_recall_tool_rejects_missing_args():
    from rhinoclaw.tools.recall_placements import recall_placements

    assert json.loads(recall_placements(MagicMock(), "", "x"))["success"] is False
    assert json.loads(recall_placements(MagicMock(), "d.gh", ""))["success"] is False
