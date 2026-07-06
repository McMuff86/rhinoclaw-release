"""Tests for build_and_bake_recipe — now a thin forwarder to the C# command.

The recipe registry + expansion lives in the plugin (single source of truth),
so this wrapper just validates and forwards `{recipe, file_path, params, layer,
material}` to the `build_and_bake_recipe` TCP command.
"""
import json
from unittest.mock import MagicMock, patch


def _run(recipe, file_path="C:/t/x.gh", **kw):
    from rhinoclaw.tools.build_and_bake_recipe import build_and_bake_recipe

    mock_rhino = MagicMock()
    mock_rhino.send_command.return_value = kw.pop("_return", {
        "status": "success", "layer": kw.get("layer", "GH_Bake"),
        "baked_count": 1, "baked_ids": ["guid-1"],
    })
    with patch(
        "rhinoclaw.tools.build_and_bake_recipe.get_rhino_connection",
        return_value=mock_rhino,
    ):
        result = json.loads(build_and_bake_recipe(MagicMock(), recipe, file_path, **kw))
    sent = (mock_rhino.send_command.call_args[0]
            if mock_rhino.send_command.called else None)
    return result, sent


def test_box_forwards_command():
    result, sent = _run("box", params={"x": 40, "y": 20, "z": 10}, layer="Boxes")
    assert result["success"] is True
    cmd, payload = sent
    assert cmd == "build_and_bake_recipe"
    assert payload["recipe"] == "box"
    assert payload["file_path"] == "C:/t/x.gh"
    assert payload["layer"] == "Boxes"
    assert payload["params"] == {"x": 40, "y": 20, "z": 10}


def test_params_omitted_when_none():
    result, sent = _run("sphere")
    _, payload = sent
    assert payload["recipe"] == "sphere"
    assert "params" not in payload  # no overrides → key omitted
    assert "material" not in payload


def test_material_forwarded():
    result, sent = _run("box", material="Glass")
    _, payload = sent
    assert payload["material"] == "Glass"


def test_list_forwards_without_filepath():
    from rhinoclaw.tools.build_and_bake_recipe import build_and_bake_recipe

    mock_rhino = MagicMock()
    mock_rhino.send_command.return_value = {
        "status": "success",
        "recipes": {"box": {"component": "CenterBox", "params": ["x", "y", "z"]}},
    }
    with patch(
        "rhinoclaw.tools.build_and_bake_recipe.get_rhino_connection",
        return_value=mock_rhino,
    ):
        # no file_path needed for "list"
        result = json.loads(build_and_bake_recipe(MagicMock(), "list"))

    assert result["success"] is True
    assert "box" in result["data"]["recipes"]
    cmd, payload = mock_rhino.send_command.call_args[0]
    assert cmd == "build_and_bake_recipe"
    assert payload == {"recipe": "list"}


def test_missing_file_path_fails():
    result, sent = _run("box", file_path="")
    assert result["success"] is False
    assert "file_path is required" in result["message"]
    assert sent is None  # never reached the plugin


def test_wrong_extension_fails():
    result, sent = _run("box", file_path="C:/t/x.3dm")
    assert result["success"] is False
    assert ".gh" in result["message"]


def test_unknown_recipe_error_surfaced():
    # The plugin validates the recipe; the wrapper surfaces its error.
    from rhinoclaw.tools.build_and_bake_recipe import build_and_bake_recipe

    mock_rhino = MagicMock()
    mock_rhino.send_command.side_effect = Exception("Unknown recipe 'pyramid'. Available: box, sphere, cylinder, cone")
    with patch(
        "rhinoclaw.tools.build_and_bake_recipe.get_rhino_connection",
        return_value=mock_rhino,
    ):
        result = json.loads(build_and_bake_recipe(MagicMock(), "pyramid", "C:/t/x.gh"))
    assert result["success"] is False
    assert "Unknown recipe" in result["message"]
