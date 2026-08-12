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
from rhinoclaw.utils.gh_bake_verification import summarize_baked_geometry
from rhinoclaw.utils.gh_critic import (
    bbox_dims,
    check_expectations,
    derive_bake_outputs,
    terminal_components,
    validate_expectations,
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
BAKED_ID = "11111111-1111-4111-8111-111111111111"


def _mock_rhino(
    build_results,
    inspect_result=None,
    objects_info=None,
    object_properties=None,
    inspect_error=None,
    cleanup_sticks=False,
):
    """send_command router; build_results is a list consumed per bake call."""
    rhino = MagicMock()
    build_calls = []
    deleted_ids = set()

    default_info = {
        "count": 1,
        "missing_count": 0,
        "missing": [],
        "results": [{
            "id": BAKED_ID,
            "type": "Brep",
            "layer": "GH_Bake",
            "geometry_details": {
                "type": "Brep",
                "object_type": "Brep",
                "is_valid": True,
                "bounding_box": {
                    "min": [-20.0, -10.0, -5.0],
                    "max": [20.0, 10.0, 5.0],
                },
            },
            "brep_details": {
                "face_count": 6,
                "edge_count": 12,
                "vertex_count": 8,
                "is_solid": True,
            },
        }],
    }
    default_properties = {
        "id": BAKED_ID,
        "type": "Brep",
        "is_solid": True,
        "area": 2800.0,
        "volume": 8000.0,
    }

    def route(cmd, params, **kwargs):
        if cmd == "build_and_bake_gh":
            build_calls.append(params)
            return build_results[min(len(build_calls) - 1,
                                     len(build_results) - 1)]
        if cmd == "inspect_grasshopper_definition":
            if inspect_error is not None:
                raise inspect_error
            return inspect_result or {
                "headless_solvable": True,
                "script_component_count": 0,
                "object_count": 4,
            }
        if cmd == "get_objects_info":
            requested = params["ids"]
            if not cleanup_sticks and requested \
                    and all(object_id in deleted_ids for object_id in requested):
                return {
                    "count": 0,
                    "missing_count": len(requested),
                    "results": [],
                    "missing": [
                        {"id": object_id, "reason": "not_found"}
                        for object_id in requested
                    ],
                }
            return objects_info or default_info
        if cmd == "get_object_properties":
            return object_properties or default_properties
        if cmd == "delete_object":
            object_id = params["id"]
            if not cleanup_sticks:
                deleted_ids.add(object_id)
            return {
                "id": object_id,
                "name": "",
                "deleted": not cleanup_sticks,
            }
        raise AssertionError(f"unexpected command {cmd}")

    rhino.send_command.side_effect = route
    rhino._build_calls = build_calls
    rhino._deleted_ids = deleted_ids
    return rhino


BUILD_OK = {
    "file_path": "C:/t/box.gh", "layer": "GH_Bake", "baked_count": 1,
    "baked_ids": [BAKED_ID], "status": "success",
    "diagnostics": {"bake_output": "B", "components_total": 1,
                    "matched_outputs": 1, "items_in_output": 1,
                    "first_item_type": "Rhino.Geometry.Box"},
    "catalog_verification": {
        "pass": True,
        "schema_version": 1,
        "global_match": False,
        "scope": "used_components_only",
        "authoring_search_complete": False,
        "warning": "global proxy drift; used component contract is exact",
        "evidence": {
            "contract": {
                "schema_version": 1,
                "component_count": 2534,
                "proxy_guid_sha256": "b" * 64,
                "component_contract_sha256": "c" * 64,
            },
            "runtime": {
                "proxy_count": 2643,
                "proxy_guid_sha256": "a" * 64,
            },
            "used_component_count": 1,
            "used_components": [{
                "guid": CENTER_BOX_GUID,
                "requested_instances": 1,
                "verified_instances": 1,
                "proxy_present": True,
                "create_instance_succeeded": True,
                "contract_match": True,
            }],
        },
    },
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

    def test_expectation_schema_rejects_unchecked_or_nonfinite_claims(self):
        assert "Unknown expect key" in validate_expectations(
            {"totl_volume": 8000})[0]
        assert any("finite" in issue for issue in validate_expectations(
            {"total_volume": float("nan")}))
        assert any("tolerances alone" in issue for issue in validate_expectations(
            {"tolerance_mm": 1.0}))

    def test_semantic_expectations_use_independent_summary(self):
        semantics = {
            "aggregate": {
                "geometry_types": ["Brep"],
                "object_types": ["Brep"],
                "layers": ["GH_Bake"],
                "all_valid": True,
                "all_closed": True,
                "all_solid": True,
                "total_volume": 8000.0,
                "volume_complete": True,
                "total_area": 2800.0,
                "area_complete": True,
                "topology": {
                    "face_count": 6,
                    "edge_count": 12,
                    "vertex_count": 8,
                },
                "topology_complete": {
                    "face_count": True,
                    "edge_count": True,
                    "vertex_count": True,
                },
            },
        }
        res = check_expectations(
            [[-20, -10, -5], [20, 10, 5]],
            1,
            {
                "geometry_types": ["Brep"],
                "object_types": "Brep",
                "layer": "gh_bake",
                "all_valid": True,
                "all_closed": True,
                "all_solid": True,
                "total_volume": 8000,
                "total_area": 2800,
                "topology": {"face_count": 6, "edge_count": 12},
            },
            semantics,
        )
        assert res["ok"] is True
        assert res["semantic_checked"] == 10

    @pytest.mark.parametrize(
        ("expect", "aggregate_update", "failed_check"),
        [
            ({"geometry_types": ["Mesh"]}, {}, "geometry_types"),
            ({"object_types": ["Mesh"]}, {}, "object_types"),
            ({"layer": "Wrong"}, {}, "layer"),
            ({"all_valid": True}, {"all_valid": False}, "all_valid"),
            ({"all_closed": True}, {"all_closed": False}, "all_closed"),
            ({"total_area": 3000}, {}, "total_area"),
        ],
    )
    def test_each_semantic_family_fails_on_measured_mismatch(
        self, expect, aggregate_update, failed_check,
    ):
        aggregate = {
            "geometry_types": ["Brep"],
            "object_types": ["Brep"],
            "layers": ["GH_Bake"],
            "all_valid": True,
            "all_closed": True,
            "all_solid": True,
            "total_area": 2800.0,
            "area_complete": True,
            "total_volume": 8000.0,
            "volume_complete": True,
            "topology": {},
            "topology_complete": {},
        }
        aggregate.update(aggregate_update)

        result = check_expectations(
            [[-20, -10, -5], [20, 10, 5]],
            1,
            expect,
            {"aggregate": aggregate},
        )

        assert result["ok"] is False
        assert result["checks"][0]["check"] == failed_check

    def test_partial_multi_object_volume_is_never_promoted_to_total(self):
        second_id = "22222222-2222-4222-8222-222222222222"
        info = {
            "results": [
                {
                    "id": BAKED_ID,
                    "layer": "GH_Bake",
                    "geometry_details": {
                        "type": "Brep", "is_valid": True},
                    "brep_details": {"is_solid": True},
                },
                {
                    "id": second_id,
                    "layer": "GH_Bake",
                    "geometry_details": {
                        "type": "Brep", "is_valid": True},
                    "brep_details": {"is_solid": True},
                },
            ],
        }
        semantics = summarize_baked_geometry(info, [
            {"id": BAKED_ID, "is_solid": True, "volume": 8000.0},
            {"id": second_id, "is_solid": True},
        ])

        assert semantics["aggregate"]["volume_complete"] is False
        assert semantics["aggregate"]["total_volume"] is None
        result = check_expectations(
            None, 2, {"total_volume": 8000}, semantics)
        assert result["ok"] is False
        assert result["checks"][0]["measured"] is None


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

    def test_old_plugin_success_without_catalog_evidence_fails_closed(self):
        old_plugin = {
            key: value for key, value in BUILD_OK.items()
            if key != "catalog_verification"
        }
        rhino = _mock_rhino([old_plugin])

        result = self._call(rhino)

        assert result["success"] is False
        assert result["code"] == "VERIFICATION_FAILED"
        assert result["data"]["stage_reached"] == "build"
        assert result["data"]["catalog_verification"] is None
        assert result["data"]["mutation_scope"] == "unknown_old_plugin_response"
        assert not any(
            call.args[0] == "inspect_grasshopper_definition"
            for call in rhino.send_command.call_args_list
        )

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
        assert data["states"]["solved"]["pass"] is True
        assert data["states"]["baked"]["pass"] is True
        assert data["states"]["verified"]["pass"] is True
        assert "PASS" in result["message"]

    def test_surfaces_authoring_solution_runtime_and_catalog_evidence(self):
        build_result = {
            "status": "success",
            "errors": [],
            "solution": {
                "requested": True,
                "solve_count": 1,
                "solution_start_count": 1,
                "solution_end_count": 1,
                "runtime_messages_collected": True,
            },
            "runtime_messages": [{
                "level": "warning",
                "component_name": "Box",
                "message": "diagnostic survives",
            }],
            "publication": {
                "published": True,
                "atomic": True,
            },
            "session_cleanup": {
                "complete": True,
                "document_absent_from_server": True,
            },
            "catalog_verification": BUILD_OK["catalog_verification"],
        }
        plugin_result = {**BUILD_OK, "build_result": build_result}
        rhino = _mock_rhino([plugin_result])

        result = self._call(rhino)

        build = result["data"]["build"]
        assert build["build_result"] == build_result
        assert build["solution"] == build_result["solution"]
        assert build["runtime_messages"] == build_result["runtime_messages"]
        assert build["publication"] == build_result["publication"]
        assert build["session_cleanup"] == build_result["session_cleanup"]
        assert build["catalog_verification"] == BUILD_OK[
            "catalog_verification"]
        attempt = build["attempts"][0]
        assert attempt["build_result"] == build_result
        assert attempt["solution"]["solve_count"] == 1
        assert attempt["runtime_messages"][0]["message"] == (
            "diagnostic survives"
        )
        assert attempt["catalog_verification"]["pass"] is True
        assert result["data"]["states"]["solved"][
            "clean_runtime_messages_verified"] is False

    def test_clean_runtime_inventory_is_verified_from_solve_evidence(self):
        build_result = {
            "solution": {
                "requested": True,
                "solve_count": 1,
                "runtime_messages_collected": True,
                "runtime_message_count": 0,
                "runtime_message_counts": {
                    "remark": 0, "warning": 0, "error": 0,
                },
            },
            "runtime_messages": [],
        }
        rhino = _mock_rhino([{**BUILD_OK, "build_result": build_result}])

        result = self._call(rhino, expect={"min_count": 1})

        assert result["data"]["states"]["solved"][
            "clean_runtime_messages_verified"] is True

    def test_each_retry_keeps_its_own_authoring_diagnostics(self):
        first_build = {
            "solution": {"requested": True, "solve_count": 1},
            "runtime_messages": [{"message": "first attempt"}],
        }
        second_build = {
            "solution": {"requested": True, "solve_count": 1},
            "runtime_messages": [{"message": "second attempt"}],
        }
        no_match = {
            **BUILD_OK,
            "status": "no_geometry",
            "baked_count": 0,
            "baked_ids": [],
            "diagnostics": {"matched_outputs": 0, "items_in_output": 0},
            "build_result": first_build,
        }
        success = {**BUILD_OK, "build_result": second_build}
        rhino = _mock_rhino([no_match, success])

        result = self._call(rhino, bake_output="a")

        attempts = result["data"]["build"]["attempts"]
        assert [
            attempt["runtime_messages"][0]["message"]
            for attempt in attempts
        ] == ["first attempt", "second attempt"]
        assert result["data"]["build"]["build_result"] == second_build

    def test_no_expect_contract_is_conformance_pass_not_verified(self):
        rhino = _mock_rhino([BUILD_OK])
        result = self._call(rhino)
        data = result["data"]

        assert data["pass"] is True
        assert data["states"]["solved"]["pass"] is True
        assert data["states"]["baked"]["pass"] is True
        assert data["states"]["verified"] == {
            "pass": False,
            "status": "no_contract",
            "active_readback_pass": True,
            "contract_supplied": False,
            "check_count": 0,
            "semantic_check_count": 0,
            "scope": [],
        }
        assert "verified=false" in result["message"]

    def test_unknown_expectation_fails_before_rhino_round_trip(self):
        rhino = MagicMock()
        result = self._call(rhino, expect={"totl_volume": 8000})

        assert result["data"]["pass"] is False
        assert result["data"]["stage_reached"] == "lint"
        assert any("Unknown expect key" in issue
                   for issue in result["data"]["lint"]["errors"])
        rhino.send_command.assert_not_called()

    def test_full_semantic_contract_passes_from_two_readbacks(self):
        rhino = _mock_rhino([BUILD_OK])
        result = self._call(rhino, expect={
            "min_count": 1,
            "geometry_types": ["Brep"],
            "object_types": ["Brep"],
            "layer": "GH_Bake",
            "all_valid": True,
            "all_closed": True,
            "all_solid": True,
            "total_volume": 8000,
            "total_area": 2800,
            "topology": {
                "face_count": 6,
                "edge_count": 12,
                "vertex_count": 8,
            },
        })
        data = result["data"]

        assert data["pass"] is True
        assert data["states"]["verified"]["pass"] is True
        assert data["states"]["verified"]["semantic_check_count"] == 11
        assert data["measured"]["semantics"]["aggregate"][
            "total_volume"] == 8000.0
        assert any(
            call.args[0] == "get_object_properties"
            for call in rhino.send_command.call_args_list
        )

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
        assert data["cleanup"]["pass"] is True
        assert data["cleanup"]["absence_verified"] is True
        assert BAKED_ID in rhino._deleted_ids
        assert "FAIL" in result["message"]

    def test_same_bbox_wrong_volume_fails_and_cleans_geometry(self):
        rhino = _mock_rhino(
            [BUILD_OK],
            object_properties={
                "id": BAKED_ID,
                "type": "Brep",
                "is_solid": True,
                "area": 2800.0,
                "volume": 7000.0,
            },
        )
        result = self._call(rhino, expect={
            "dims_mm": [40, 20, 10],
            "total_volume": 8000,
            "volume_tolerance": 0.01,
        })
        data = result["data"]

        assert result["success"] is True
        assert data["pass"] is False
        assert next(check for check in data["expect_check"]["checks"]
                    if check["check"] == "dims_mm")["ok"] is True
        volume = next(check for check in data["expect_check"]["checks"]
                      if check["check"] == "total_volume")
        assert volume["ok"] is False
        assert volume["measured"] == 7000.0
        assert data["cleanup"]["pass"] is True

    def test_open_extrusion_fails_solid_contract_and_is_cleaned(self):
        info = {
            "count": 1,
            "missing_count": 0,
            "missing": [],
            "results": [{
                "id": BAKED_ID,
                "type": "EXTRUSION",
                "layer": "GH_Bake",
                "geometry_details": {
                    "type": "Extrusion",
                    "object_type": "Extrusion",
                    "is_valid": True,
                    "bounding_box": {
                        "min": [-20, -10, -5],
                        "max": [20, 10, 5],
                    },
                },
            }],
        }
        properties = {
            "id": BAKED_ID,
            "type": "Extrusion",
            "is_solid": False,
            "area": 1200.0,
        }
        rhino = _mock_rhino(
            [BUILD_OK], objects_info=info, object_properties=properties)
        result = self._call(rhino, expect={"all_solid": True})
        data = result["data"]

        assert data["pass"] is False
        solid = data["expect_check"]["checks"][0]
        assert solid == {
            "check": "all_solid",
            "ok": False,
            "expected": True,
            "measured": False,
        }
        assert data["cleanup"]["pass"] is True

    def test_topology_mismatch_fails_without_mass_property_call(self):
        rhino = _mock_rhino([BUILD_OK])
        result = self._call(
            rhino, expect={"topology": {"face_count": 5}})
        data = result["data"]

        assert data["pass"] is False
        assert data["expect_check"]["checks"][0]["measured"] == 6
        assert data["cleanup"]["pass"] is True
        assert not any(
            call.args[0] == "get_object_properties"
            for call in rhino.send_command.call_args_list
        )

    def test_incomplete_property_guid_readback_fails_closed_and_cleans(self):
        rhino = _mock_rhino(
            [BUILD_OK],
            object_properties={
                "id": "22222222-2222-4222-8222-222222222222",
                "is_solid": True,
                "volume": 8000.0,
            },
        )
        result = self._call(rhino, expect={"total_volume": 8000})
        data = result["data"]

        assert data["pass"] is False
        assert data["measured"]["verification"]["pass"] is False
        assert any("does not match" in issue
                   for issue in data["measured"]["verification"]["issues"])
        assert data["cleanup"]["pass"] is True

    def test_cleanup_residual_is_partial_mutation(self):
        rhino = _mock_rhino([BUILD_OK], cleanup_sticks=True)
        result = self._call(rhino, expect={"all_solid": False})
        data = result["data"]

        assert result["success"] is False
        assert result["code"] == "PARTIAL_MUTATION"
        assert data["pass"] is False
        assert data["cleanup"]["pass"] is False
        assert data["cleanup"]["absence_verified"] is False

    def test_cleanup_opt_out_reports_retained_partial_mutation(self):
        rhino = _mock_rhino([BUILD_OK])
        result = self._call(
            rhino,
            expect={"all_solid": False},
            cleanup_on_failure=False,
        )
        data = result["data"]

        assert result["success"] is False
        assert result["code"] == "PARTIAL_MUTATION"
        assert data["cleanup"]["requested"] is False
        assert data["cleanup"]["retained_ids"] == [BAKED_ID]
        assert rhino._deleted_ids == set()

    def test_missing_baked_id_fails_closed_and_uses_measured_count(self):
        rhino = _mock_rhino(
            [BUILD_OK],
            objects_info={
                "count": 0,
                "missing_count": 1,
                "results": [],
                "missing": [{"id": BAKED_ID, "reason": "not_found"}],
            },
        )
        result = self._call(rhino, expect={"min_count": 1})
        data = result["data"]

        assert data["pass"] is False
        assert data["stage_reached"] == "measure"
        assert data["measured"]["count"] == 0
        assert data["measured"]["verification"]["pass"] is False
        assert data["expect_check"]["checks"][0]["measured"] == 0
        assert data["expect_check"]["ok"] is False
        assert any("not active" in hint for hint in data["hints"])

    @pytest.mark.parametrize(
        ("baked_count", "baked_ids", "issue"),
        [
            (2, [BAKED_ID], "does not equal"),
            (1, ["not-a-guid"], "not a GUID"),
            (0, [], "reported no Rhino objects"),
        ],
    )
    def test_inconsistent_build_report_fails_before_semantic_readback(
        self, baked_count, baked_ids, issue,
    ):
        build = {**BUILD_OK, "baked_count": baked_count,
                 "baked_ids": baked_ids}
        rhino = _mock_rhino([build])

        result = self._call(rhino)
        data = result["data"]

        assert data["pass"] is False
        assert data["stage_reached"] == "build"
        assert data["build"]["verification"]["pass"] is False
        assert any(issue in value
                   for value in data["build"]["verification"]["issues"])
        assert not any(
            call.args[0] in {
                "inspect_grasshopper_definition",
                "get_object_properties",
            }
            for call in rhino.send_command.call_args_list
        )

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

    def test_failed_inspection_fails_closed(self):
        rhino = _mock_rhino(
            [BUILD_OK], inspect_error=RuntimeError("archive unreadable"))
        result = self._call(rhino)
        data = result["data"]
        assert data["pass"] is False
        assert data["stage_reached"] == "measure"
        assert data["inspect"] is None
        assert any("headless-solvable" in h for h in data["hints"])

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
