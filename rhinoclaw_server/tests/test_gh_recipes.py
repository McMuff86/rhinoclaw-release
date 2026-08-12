"""Tests for the composition-recipe registry (G4 / Recipe-Registry 2.3).

The registry's contract: every recipe instantiates a spec that (a) lints
clean against the REAL shipped component catalog — GUID/port drift fails
here, offline, before any live run — and (b) carries an expectation
computed from its own params, so live verification measures the recipe's
intent, not just bake success.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from rhinoclaw.tools.find_gh_component import _catalog
from rhinoclaw.utils.gh_lint import lint_definition
from rhinoclaw.utils.gh_recipes import (
    COMPOSITION_RECIPES,
    list_compositions,
)


class TestRegistry:
    def test_expected_recipes_present(self):
        assert set(COMPOSITION_RECIPES) == {
            "rect_extrude", "box_difference", "box_array", "box_orient"}

    @pytest.mark.parametrize("name", sorted(COMPOSITION_RECIPES))
    def test_every_recipe_lints_clean_against_the_real_catalog(self, name):
        spec = COMPOSITION_RECIPES[name].instantiate()
        result = lint_definition(spec["components"], spec["wires"],
                                 catalog=_catalog())
        assert result["valid"], f"{name}: {result['errors']}"
        # SDK-native only — script components would break headless solving.
        assert not any("script" in (c.get("type") or "")
                       for c in spec["components"])

    @pytest.mark.parametrize("name", sorted(COMPOSITION_RECIPES))
    def test_every_recipe_has_a_measurable_expectation(self, name):
        spec = COMPOSITION_RECIPES[name].instantiate()
        expect = spec["expect"]
        assert expect.get("min_count", 0) >= 1
        assert "dims_mm" in expect  # bake success alone is never the verdict

    def test_param_override_flows_into_expectation(self):
        spec = COMPOSITION_RECIPES["rect_extrude"].instantiate(
            {"x": 1000, "height": 50})
        assert spec["params"]["x"] == 1000
        assert spec["expect"]["bbox_max"] == [1000, 200.0, 50]
        assert spec["expect"]["dims_mm"] == [1000, 200.0, 50]

    def test_unknown_param_is_rejected_with_available_names(self):
        with pytest.raises(ValueError, match="radius.*available|no param"):
            COMPOSITION_RECIPES["box_array"].instantiate({"radius": 5})

    def test_array_expectation_scales_with_count(self):
        spec = COMPOSITION_RECIPES["box_array"].instantiate(
            {"x": 50, "step": 200, "count": 3})
        assert spec["expect"]["min_count"] == 3
        # 2*50 extent + 2 steps of 200 along X
        assert spec["expect"]["dims_mm"][0] == 500

    def test_orient_expectation_swaps_y_and_z(self):
        spec = COMPOSITION_RECIPES["box_orient"].instantiate(
            {"x": 200, "y": 100, "z": 50})
        assert spec["expect"]["dims_mm"] == [400, 100, 200]

    def test_list_compositions_shape(self):
        listing = list_compositions()
        assert listing["rect_extrude"]["kind"] == "composition"
        assert "height" in listing["rect_extrude"]["params"]


class TestRecipeToolRouting:
    def test_composition_routes_through_the_verified_loop(self):
        from rhinoclaw.tools.build_and_bake_recipe import build_and_bake_recipe
        loop_result = json.dumps({"success": True, "message": "Iteration 1: PASS",
                                  "data": {"pass": True, "stage_reached": "measure"}})
        with patch("rhinoclaw.tools.build_and_bake_recipe.build_gh_interactive",
                   return_value=loop_result) as loop:
            result = json.loads(build_and_bake_recipe(
                MagicMock(), "rect_extrude", "C:/t/re.gh",
                params={"x": 600}, layer="L1"))
        kwargs = loop.call_args.kwargs
        assert kwargs["label"] == "recipe:rect_extrude"
        assert kwargs["expect"]["dims_mm"] == [600, 200.0, 100.0]
        assert kwargs["layer"] == "L1"
        assert result["data"]["recipe"]["params"]["x"] == 600
        assert result["message"].startswith("Recipe 'rect_extrude':")

    def test_composition_bad_param_fails_without_rhino(self):
        from rhinoclaw.tools.build_and_bake_recipe import build_and_bake_recipe
        result = json.loads(build_and_bake_recipe(
            MagicMock(), "box_orient", "C:/t/o.gh", params={"nope": 1}))
        assert result["success"] is False
        assert result["code"] == "INVALID_PARAMS"

    def test_primitive_still_goes_to_the_plugin(self):
        from rhinoclaw.tools.build_and_bake_recipe import build_and_bake_recipe
        rhino = MagicMock()
        guid = "28061aae-04fb-4cb5-ac45-16f3b66bc0a4"
        rhino.send_command.side_effect = [
            {"recipes": {"box": {"guid": guid}}},
            {
                "baked_count": 1,
                "layer": "GH_Bake",
                "status": "success",
                "catalog_verification": {
                    "pass": True,
                    "schema_version": 1,
                    "global_match": False,
                    "scope": "used_components_only",
                    "authoring_search_complete": False,
                    "warning": "global drift; used component exact",
                    "evidence": {
                        "contract": {
                            "schema_version": 1,
                            "component_count": 2534,
                            "proxy_guid_sha256": "a" * 64,
                            "component_contract_sha256": "b" * 64,
                        },
                        "runtime": {
                            "proxy_count": 2643,
                            "proxy_guid_sha256": "c" * 64,
                        },
                        "used_component_count": 1,
                        "used_components": [{
                            "guid": guid,
                            "requested_instances": 1,
                            "verified_instances": 1,
                            "proxy_present": True,
                            "create_instance_succeeded": True,
                            "contract_match": True,
                        }],
                    },
                },
            },
        ]
        with patch("rhinoclaw.tools.build_and_bake_recipe.get_rhino_connection",
                   return_value=rhino):
            result = json.loads(build_and_bake_recipe(
                MagicMock(), "box", "C:/t/box.gh", params={"x": 40}))
        cmd, params = rhino.send_command.call_args_list[1].args
        assert cmd == "build_and_bake_recipe"
        assert params["recipe"] == "box"
        assert params["catalog_contract"]["used_components"][0]["guid"] == guid
        assert result["success"] is True

    def test_list_merges_both_registries(self):
        from rhinoclaw.tools.build_and_bake_recipe import build_and_bake_recipe
        rhino = MagicMock()
        rhino.send_command.return_value = {
            "recipes": {"box": {"params": ["x", "y", "z"]}}}
        with patch("rhinoclaw.tools.build_and_bake_recipe.get_rhino_connection",
                   return_value=rhino):
            result = json.loads(build_and_bake_recipe(MagicMock(), "list"))
        recipes = result["data"]["recipes"]
        assert "box" in recipes            # plugin primitive
        assert "box_difference" in recipes  # python composition
        assert "4 composition" in result["message"]

    def test_list_degrades_to_compositions_when_plugin_unreachable(self):
        from rhinoclaw.tools.build_and_bake_recipe import build_and_bake_recipe
        with patch("rhinoclaw.tools.build_and_bake_recipe.get_rhino_connection",
                   side_effect=ConnectionError("no rhino")):
            result = json.loads(build_and_bake_recipe(MagicMock(), "list"))
        assert result["success"] is True
        assert set(result["data"]["recipes"]) == set(COMPOSITION_RECIPES)
        assert "plugin_registry_error" in result["data"]
