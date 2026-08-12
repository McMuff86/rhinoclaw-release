"""Tests for the part-library loop closer: part distiller + recall tool
+ the part_outcome split in the interaction logger."""
import json
from unittest.mock import MagicMock, patch

PART_ID = "kauls/aufnahmeelement-band-stumpf-vx"
TARGET = [904.0, 0.0, 1000.0, -1, 0, 0, 0, 1, 0]
XFORM = [-1.0, 0, 0, 904.0, 0, 1.0, 0, 0.0,
         0, 0, -1.0, 1000.0, 0, 0, 0, 1.0]


def _write_log(log_dir, day, records):
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"interactions_{day}.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _outcome(passed, worst_probe, part_id=PART_ID, context="door-right-900",
             timestamp="2026-08-06T10:00:00+00:00", target=TARGET, xform=XFORM):
    return {
        "timestamp": timestamp,
        "session_id": "s1",
        "tool_name": "judge_part_placement",
        "tool_args": {},
        "success": passed,
        "part_outcome": {
            "part_id": part_id, "context": context, "pass": passed,
            "det": 1.0, "worst_probe_mm": worst_probe,
            "target_frame": target, "xform": xform,
        },
    }


class TestPartRecipeDistiller:
    def test_keeps_only_passing_and_picks_lowest_worst_probe(self, tmp_path):
        from rhinoclaw.utils.part_recipe_distiller import distill_part_recipes

        best_target = [905.0, 0.0, 1000.0, -1, 0, 0, 0, 1, 0]
        _write_log(tmp_path, "20260805", [
            _outcome(True, 0.4),
            _outcome(False, 46.0),                       # fail -> excluded
            {"tool_name": "ping", "success": True},      # no outcome -> skip
            # door outcome must NOT contaminate the part corpus:
            {"tool_name": "judge_door_placement", "success": True,
             "placement_outcome": {"pass": True, "off_center_mm": 1.0}},
        ])
        _write_log(tmp_path, "20260806", [
            _outcome(True, 0.02, target=best_target,
                     timestamp="2026-08-06T12:00:00+00:00"),  # better -> wins
        ])

        recipes = distill_part_recipes(tmp_path)

        [(key, entry)] = recipes.items()
        assert key == f"{PART_ID}|door-right-900"
        assert entry["worst_probe_mm"] == 0.02          # best, not latest
        assert entry["target_frame"] == best_target
        assert entry["confidence"] == 2                  # passing records only
        assert entry["last_seen"] == "2026-08-06T12:00:00+00:00"
        # registry persisted next to the logs
        on_disk = json.loads((tmp_path / "part_recipes.json").read_text())
        assert on_disk == recipes

    def test_contexts_are_separate_keys(self, tmp_path):
        from rhinoclaw.utils.part_recipe_distiller import (
            distill_part_recipes,
            lookup_part_recipe,
        )

        _write_log(tmp_path, "20260806", [
            _outcome(True, 0.1, context="door-right-900"),
            _outcome(True, 0.2, context="door-left-900"),
            _outcome(True, 0.3, part_id="glutz/topaz-5632c", context=None),
        ])

        recipes = distill_part_recipes(tmp_path)

        assert len(recipes) == 3
        right = lookup_part_recipe(recipes, PART_ID, "door-right-900")
        left = lookup_part_recipe(recipes, PART_ID, "door-left-900")
        assert right["worst_probe_mm"] == 0.1
        assert left["worst_probe_mm"] == 0.2
        # None context maps to "default"
        assert lookup_part_recipe(
            recipes, "glutz/topaz-5632c", None)["worst_probe_mm"] == 0.3

    def test_empty_corpus_yields_empty_registry(self, tmp_path):
        from rhinoclaw.utils.part_recipe_distiller import distill_part_recipes

        assert distill_part_recipes(tmp_path) == {}

    def test_none_worst_probe_never_wins(self, tmp_path):
        from rhinoclaw.utils.part_recipe_distiller import distill_part_recipes

        _write_log(tmp_path, "20260806", [
            _outcome(True, 0.5),
            _outcome(True, None, timestamp="2026-08-06T13:00:00+00:00"),
        ])
        recipes = distill_part_recipes(tmp_path)
        [entry] = recipes.values()
        assert entry["worst_probe_mm"] == 0.5
        assert entry["confidence"] == 2


class TestLogPartOutcome:
    def test_record_uses_the_part_outcome_split(self, tmp_path):
        from rhinoclaw.utils.interaction_logger import InteractionLogger

        ilog = InteractionLogger(log_dir=str(tmp_path))
        ilog.log_part_outcome({"part_id": PART_ID, "context": "c",
                               "pass": True, "worst_probe_mm": 0.1})

        [log_file] = list(tmp_path.glob("interactions_*.jsonl"))
        record = json.loads(log_file.read_text().strip())
        assert record["tool_name"] == "judge_part_placement"
        assert record["success"] is True
        assert record["part_outcome"]["part_id"] == PART_ID
        # The split keeps the other distillers uncontaminated:
        assert "placement_outcome" not in record
        assert "graph_outcome" not in record


class TestRecallPartPlacementsTool:
    @patch("rhinoclaw.tools.recall_part_placements.interaction_logger")
    def test_found(self, mock_ilog, tmp_path):
        from rhinoclaw.tools.recall_part_placements import recall_part_placements

        mock_ilog._log_dir = tmp_path
        _write_log(tmp_path, "20260806", [_outcome(True, 0.02)])

        ctx = MagicMock()
        parsed = json.loads(recall_part_placements(
            ctx, part_id=PART_ID, context="door-right-900"))

        assert parsed["success"] is True
        assert parsed["data"]["found"] is True
        assert parsed["data"]["target_frame"] == TARGET
        assert len(parsed["data"]["xform"]) == 16
        assert parsed["data"]["confidence"] == 1

    @patch("rhinoclaw.tools.recall_part_placements.interaction_logger")
    def test_cold_start_miss_with_hint(self, mock_ilog, tmp_path):
        from rhinoclaw.tools.recall_part_placements import recall_part_placements

        mock_ilog._log_dir = tmp_path

        ctx = MagicMock()
        parsed = json.loads(recall_part_placements(
            ctx, part_id=PART_ID, context="door-right-900"))

        assert parsed["success"] is True
        assert parsed["data"]["found"] is False
        assert "judge_part_placement" in parsed["data"]["hint"]
        assert parsed["data"]["known_keys"] == []

    @patch("rhinoclaw.tools.recall_part_placements.interaction_logger")
    def test_missing_part_id_is_invalid(self, mock_ilog, tmp_path):
        from rhinoclaw.tools.recall_part_placements import recall_part_placements

        mock_ilog._log_dir = tmp_path

        ctx = MagicMock()
        parsed = json.loads(recall_part_placements(ctx, part_id=""))

        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]
