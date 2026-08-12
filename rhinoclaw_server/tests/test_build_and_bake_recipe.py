"""Tests for catalog-grounded primitive and verified composition recipes."""

import json
from unittest.mock import MagicMock, patch


PRIMITIVE_GUIDS = {
    "box": "28061aae-04fb-4cb5-ac45-16f3b66bc0a4",
    "sphere": "dabc854d-f50e-408a-b001-d043c7de151d",
    "cylinder": "0373008a-80ee-45be-887d-ab5a244afc29",
    "cone": "03e331ed-c4d1-4a23-afa2-f57b87d2043c",
}


def _registry(**overrides):
    recipes = {
        name: {
            "component": name.title(),
            "guid": guid,
            "bake_output": "B",
            "params": [],
        }
        for name, guid in PRIMITIVE_GUIDS.items()
    }
    recipes.update(overrides)
    return {"status": "success", "recipes": recipes}


def _catalog_ok(guid):
    return {
        "pass": True,
        "schema_version": 1,
        "global_match": False,
        "scope": "used_components_only",
        "authoring_search_complete": False,
        "warning": "global proxy catalog drifted; used component is exact",
        "issues": [],
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
    }


def _run(recipe, file_path="C:/t/x.gh", *, registry=None,
         run_result=None, **kwargs):
    from rhinoclaw.tools.build_and_bake_recipe import build_and_bake_recipe

    registry = registry if registry is not None else _registry()
    guid = PRIMITIVE_GUIDS.get(recipe, PRIMITIVE_GUIDS["box"])
    run_result = run_result if run_result is not None else {
        "status": "success",
        "layer": kwargs.get("layer", "GH_Bake"),
        "baked_count": 1,
        "baked_ids": ["guid-1"],
        "catalog_verification": _catalog_ok(guid),
    }
    mock_rhino = MagicMock()
    mock_rhino.send_command.side_effect = [registry, run_result]
    with patch(
        "rhinoclaw.tools.build_and_bake_recipe.get_rhino_connection",
        return_value=mock_rhino,
    ):
        result = json.loads(build_and_bake_recipe(
            MagicMock(), recipe, file_path, **kwargs))
    return result, mock_rhino


def test_box_resolves_registry_guid_and_forwards_catalog_contract():
    result, rhino = _run(
        "box", params={"x": 40, "y": 20, "z": 10}, layer="Boxes")

    assert result["success"] is True
    assert rhino.send_command.call_count == 2
    assert rhino.send_command.call_args_list[0].args == (
        "build_and_bake_recipe", {"recipe": "list"})
    cmd, payload = rhino.send_command.call_args_list[1].args
    assert cmd == "build_and_bake_recipe"
    assert payload["recipe"] == "box"
    assert payload["file_path"] == "C:/t/x.gh"
    assert payload["layer"] == "Boxes"
    assert payload["params"] == {"x": 40, "y": 20, "z": 10}
    assert payload["catalog_contract"]["used_components"][0]["guid"] == (
        PRIMITIVE_GUIDS["box"])


def test_params_and_material_forwarding_remain_sparse():
    result, rhino = _run("sphere")
    assert result["success"] is True
    payload = rhino.send_command.call_args_list[1].args[1]
    assert payload["recipe"] == "sphere"
    assert "params" not in payload
    assert "material" not in payload

    result, rhino = _run("box", material="Glass")
    assert result["success"] is True
    assert rhino.send_command.call_args_list[1].args[1]["material"] == "Glass"


def test_list_forwards_without_filepath_or_gate():
    from rhinoclaw.tools.build_and_bake_recipe import build_and_bake_recipe

    mock_rhino = MagicMock()
    mock_rhino.send_command.return_value = _registry()
    with patch(
        "rhinoclaw.tools.build_and_bake_recipe.get_rhino_connection",
        return_value=mock_rhino,
    ):
        result = json.loads(build_and_bake_recipe(MagicMock(), "list"))

    assert result["success"] is True
    assert result["data"]["recipes"]["box"]["guid"] == PRIMITIVE_GUIDS["box"]
    mock_rhino.send_command.assert_called_once_with(
        "build_and_bake_recipe", {"recipe": "list"})


def test_missing_or_stale_registry_guid_fails_before_primitive_run():
    missing = _registry(box={"component": "CenterBox", "params": []})
    result, rhino = _run("box", registry=missing)
    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"
    assert "update/restart" in result["message"]
    assert result["data"]["mutation_scope"] == "read_only_registry_preflight"
    assert rhino.send_command.call_count == 1

    stale = _registry(box={
        "component": "CenterBox",
        "guid": "ffffffff-ffff-4fff-8fff-ffffffffffff",
        "params": [],
    })
    result, rhino = _run("box", registry=stale)
    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"
    assert "not authorable" in result["message"]
    assert rhino.send_command.call_count == 1


def test_valid_but_wrong_registry_guid_is_rejected_by_plugin_gate():
    wrong_guid = PRIMITIVE_GUIDS["sphere"]
    wrong_registry = _registry(box={
        "component": "CenterBox",
        "guid": wrong_guid,
        "params": ["x", "y", "z"],
    })
    mismatch = _catalog_ok(wrong_guid)
    mismatch["pass"] = False
    mismatch["issues"] = ["internally expanded recipe GUID did not match"]
    mismatch["evidence"]["used_components"][0]["contract_match"] = False
    result, rhino = _run(
        "box",
        registry=wrong_registry,
        run_result={
            "status": "verification_failed",
            "catalog_verification": mismatch,
        },
    )

    assert rhino.send_command.call_count == 2
    forwarded = rhino.send_command.call_args_list[1].args[1]
    assert forwarded["catalog_contract"]["used_components"][0][
        "guid"] == wrong_guid
    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"
    assert "expanded recipe GUID" in result["message"]
    assert result["data"]["catalog_verification"]["pass"] is False
    assert result["data"]["mutation_scope"] == "pre_solve_pre_publish_gate"


def test_old_plugin_run_without_catalog_evidence_fails_closed():
    result, rhino = _run("box", run_result={
        "status": "success",
        "baked_count": 1,
        "baked_ids": ["guid-1"],
    })

    assert rhino.send_command.call_count == 2
    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"
    assert result["data"]["mutation_scope"] == "unknown_old_plugin_response"


def test_input_and_unknown_recipe_errors_are_surfaced():
    result, rhino = _run("box", file_path="")
    assert result["success"] is False
    assert "file_path is required" in result["message"]
    rhino.send_command.assert_not_called()

    result, rhino = _run("box", file_path="C:/t/x.3dm")
    assert result["success"] is False
    assert ".gh" in result["message"]
    rhino.send_command.assert_not_called()

    result, rhino = _run("pyramid")
    assert result["success"] is False
    assert "Unknown primitive recipe" in result["message"]
    assert rhino.send_command.call_count == 1
