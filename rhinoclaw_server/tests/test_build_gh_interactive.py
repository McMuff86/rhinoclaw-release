"""Tests for build_gh_interactive — the verified GH authoring loop (5.3).

The critique core (gh_critic) is tested pure; the tool tests mock the Rhino
connection and assert the loop semantics: lint fails offline without a
round-trip, bake_output derives from the catalog and auto-retries, measured
geometry (never claims) drives the verdict, every iteration logs an outcome.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from rhinoclaw.tools.find_gh_component import _catalog
from rhinoclaw.utils.gh_critic import (
    bbox_dims,
    check_expectations,
    derive_bake_outputs,
    terminal_components,
)

CENTER_BOX_GUID = "28061aae-04fb-4cb5-ac45-16f3b66bc0a4"   # out: B (Box)
EXTRUDE_GUID = "962034e9-cc27-4394-afc4-5c16e3447cf9"      # out: E (Geometry)
RECTANGLE_GUID = "d93100b6-d50b-40b2-831a-814659dc38e3"    # out: R, L (Number)

SLIDERS = [
    {"type": "slider", "name": "X", "default": 40, "min": 0, "max": 100},
    {"type": "slider", "name": "Y", "default": 20, "min": 0, "max": 100},
    {"type": "slider", "name": "Z", "default": 10, "min": 0, "max": 100},
]
BOX = {"type": "sdk_component", "name": "Box", "guid": CENTER_BOX_GUID}
BOX_WIRES = [
    {"from": "X", "to": "Box", "to_input": "X"},
    {"from": "Y", "to": "Box", "to_input": "Y"},
    {"from": "Z", "to": "Box", "to_input": "Z"},
]
BOX_SPEC = SLIDERS + [BOX]


def _mock_rhino(build_results, inspect_result=None, objects_info=None):
    """send_command router; build_results is a list consumed per bake call."""
    rhino = MagicMock()
    build_calls = []

    def route(cmd, params, **kwargs):
        if cmd == "build_and_bake_gh":
            build_calls.append(params)
            return build_results[min(len(build_calls) - 1,
                                     len(build_results) - 1)]
        if cmd == "inspect_grasshopper_definition":
            return inspect_result or {
                "headless_solvable": True,
                "script_component_count": 0,
                "object_count": 4,
            }
        if cmd == "get_objects_info":
            return objects_info or {
                "count": 1,
                "results": [{"geometry_details": {"bounding_box": {
                    "min": [-20.0, -10.0, -5.0], "max": [20.0, 10.0, 5.0]}}}],
            }
        raise AssertionError(f"unexpected command {cmd}")

    rhino.send_command.side_effect = route
    rhino._build_calls = build_calls
    return rhino


BUILD_OK = {
    "file_path": "C:/t/box.gh", "layer": "GH_Bake", "baked_count": 1,
    "baked_ids": ["g1"], "status": "success",
    "diagnostics": {"bake_output": "B", "components_total": 1,
                    "matched_outputs": 1, "items_in_output": 1,
                    "first_item_type": "Rhino.Geometry.Box"},
}


class TestGhCritic:
    def test_terminal_is_the_unconsumed_sdk_component(self):
        terms = terminal_components(BOX_SPEC, BOX_WIRES)
        assert [c["name"] for c in terms] == ["Box"]

    def test_chained_graph_terminal_is_the_sink(self):
        extrude = {"type": "sdk_component", "name": "Ext", "guid": EXTRUDE_GUID}
        wires = BOX_WIRES + [{"from": "Box", "to": "Ext", "to_input": "Base"}]
        terms = terminal_components(BOX_SPEC + [extrude], wires)
        assert [c["name"] for c in terms] == ["Ext"]

    def test_derive_bake_output_from_catalog(self):
        assert derive_bake_outputs(BOX_SPEC, BOX_WIRES,
                                   catalog=_catalog()) == ["B"]

    def test_derive_orders_geometry_before_numbers(self):
        rect = {"type": "sdk_component", "name": "Rect",
                "guid": RECTANGLE_GUID}
        # Rectangle outputs R (Generic Data) and L (Number) — L must come last.
        assert derive_bake_outputs([rect], [], catalog=_catalog()) == ["R", "L"]

    def test_derive_script_defaults_to_a(self):
        script = {"type": "python3_script", "name": "S", "code": "a=1"}
        assert derive_bake_outputs([script], [], catalog=_catalog()) == ["a"]

    def test_bbox_dims(self):
        assert bbox_dims([[-20, -10, -5], [20, 10, 5]]) == [40.0, 20.0, 10.0]
        assert bbox_dims(None) is None

    def test_expectations_pass_within_tolerance(self):
        res = check_expectations([[-20, -10, -5], [20, 10, 5]], 1,
                                 {"min_count": 1, "dims_mm": [40, 20, 10],
                                  "bbox_min": [-20, -10, -5]})
        assert res["ok"] is True
        assert res["checked"] == 3
        assert res["hints"] == []

    def test_expectations_fail_names_the_worst_axis(self):
        res = check_expectations([[-20, -10, -5], [20, 10, 5]], 1,
                                 {"dims_mm": [40, 20, 30]})
        assert res["ok"] is False
        assert any("z off by -20" in h for h in res["hints"])

    def test_expectations_with_nothing_baked(self):
        res = check_expectations(None, 0, {"min_count": 1, "dims_mm": [1, 1, 1]})
        assert res["ok"] is False
        assert len(res["hints"]) == 2


@pytest.fixture(autouse=True)
def _no_corpus_writes():
    """Tests must never pollute the real logs/ outcome corpus."""
    with patch("rhinoclaw.tools.build_gh_interactive.interaction_logger"):
        yield


class TestBuildGhInteractive:
    def _call(self, rhino, **kwargs):
        from rhinoclaw.tools.build_gh_interactive import build_gh_interactive
        defaults = dict(file_path="C:/t/box.gh", components=BOX_SPEC,
                        wires=BOX_WIRES)
        defaults.update(kwargs)
        with patch("rhinoclaw.tools.build_gh_interactive.get_rhino_connection",
                   return_value=rhino):
            return json.loads(build_gh_interactive(MagicMock(), **defaults))

    def test_lint_failure_costs_no_round_trip(self):
        rhino = MagicMock()
        bad = [{"type": "sdk_component", "name": "Box",
                "guid": "deadbeef-0000-0000-0000-000000000000"}]
        result = self._call(rhino, components=bad, wires=[])
        assert result["success"] is True  # transport ok, verdict in data
        assert result["data"]["pass"] is False
        assert result["data"]["stage_reached"] == "lint"
        assert any("find_gh_component" in h for h in result["data"]["hints"])
        rhino.send_command.assert_not_called()

    def test_happy_path_derives_bake_output_and_measures(self):
        rhino = _mock_rhino([BUILD_OK])
        result = self._call(rhino, expect={"min_count": 1,
                                           "dims_mm": [40, 20, 10]})
        data = result["data"]
        assert data["pass"] is True
        assert data["stage_reached"] == "measure"
        assert data["build"]["bake_output_used"] == "B"  # catalog-derived
        assert rhino._build_calls[0]["bake_output"] == "B"
        assert data["measured"]["dims_mm"] == [40.0, 20.0, 10.0]
        assert data["expect_check"]["ok"] is True
        assert "PASS" in result["message"]

    def test_wrong_bake_output_auto_retries_with_derived(self):
        no_match = {**BUILD_OK, "status": "no_geometry", "baked_count": 0,
                    "baked_ids": [],
                    "diagnostics": {"matched_outputs": 0, "items_in_output": 0}}
        rhino = _mock_rhino([no_match, BUILD_OK])
        result = self._call(rhino, bake_output="a")  # wrong, pinned by agent
        data = result["data"]
        assert data["pass"] is True
        assert [a["bake_output"] for a in data["build"]["attempts"]] == ["a", "B"]
        assert data["build"]["bake_output_used"] == "B"
        assert any("auto-retried" in h for h in data["hints"])

    def test_empty_solve_does_not_retry_other_outputs(self):
        empty = {**BUILD_OK, "status": "no_geometry", "baked_count": 0,
                 "baked_ids": [],
                 "diagnostics": {"matched_outputs": 1, "items_in_output": 0}}
        rhino = _mock_rhino([empty])
        result = self._call(rhino, bake_output="B")
        data = result["data"]
        assert data["pass"] is False
        assert data["stage_reached"] == "build"
        assert len(data["build"]["attempts"]) == 1
        assert any("headless" in h for h in data["hints"])

    def test_expectation_mismatch_fails_with_hint(self):
        rhino = _mock_rhino([BUILD_OK])
        result = self._call(rhino, expect={"dims_mm": [40, 20, 30]})
        data = result["data"]
        assert data["pass"] is False
        assert data["stage_reached"] == "measure"
        assert data["expect_check"]["ok"] is False
        assert "FAIL" in result["message"]

    def test_script_definition_fails_headless_verdict(self):
        rhino = _mock_rhino(
            [BUILD_OK],
            inspect_result={"headless_solvable": False,
                            "script_component_count": 1, "object_count": 2},
        )
        result = self._call(rhino)
        data = result["data"]
        assert data["pass"] is False
        assert any("SDK-native" in h for h in data["hints"])

    def test_every_iteration_logs_a_graph_outcome(self):
        rhino = _mock_rhino([BUILD_OK])
        with patch("rhinoclaw.tools.build_gh_interactive.interaction_logger"
                   ) as logger_mock:
            result = self._call(rhino, label="param_box", iteration=2,
                                expect={"min_count": 1})
        assert result["data"]["pass"] is True
        outcome = logger_mock.log_graph_outcome.call_args[0][0]
        assert outcome["label"] == "param_box"
        assert outcome["iteration"] == 2
        assert outcome["pass"] is True
        assert outcome["stage_reached"] == "measure"
        assert outcome["bake_output_used"] == "B"
        assert outcome["definition"] == "C:/t/box.gh"

    def test_log_outcomes_false_stays_silent(self):
        rhino = _mock_rhino([BUILD_OK])
        with patch("rhinoclaw.tools.build_gh_interactive.interaction_logger"
                   ) as logger_mock:
            self._call(rhino, log_outcomes=False)
        logger_mock.log_graph_outcome.assert_not_called()

    def test_invalid_file_path_is_rejected(self):
        from rhinoclaw.tools.build_gh_interactive import build_gh_interactive
        result = json.loads(build_gh_interactive(
            MagicMock(), file_path="C:/t/box.txt", components=BOX_SPEC))
        assert result["success"] is False


class TestGraphOutcomeLogging:
    def test_log_graph_outcome_writes_jsonl_record(self, tmp_path):
        from rhinoclaw.utils.interaction_logger import InteractionLogger
        il = InteractionLogger(log_dir=str(tmp_path))
        il.log_graph_outcome({"label": "param_box", "iteration": 1,
                              "pass": True, "stage_reached": "measure"})
        files = list(tmp_path.glob("interactions_*.jsonl"))
        assert len(files) == 1
        record = json.loads(files[0].read_text().strip())
        assert record["tool_name"] == "build_gh_interactive"
        assert record["success"] is True
        assert record["graph_outcome"]["label"] == "param_box"
        assert "placement_outcome" not in record  # door corpus untouched
