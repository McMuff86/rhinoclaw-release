import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rhinoclaw.tools.grasshopper_canvas import (
    attach_grasshopper_definition,
    get_grasshopper_canvas,
    show_grasshopper_definition,
)

NODE = "11111111-1111-1111-1111-111111111111"
CANVAS = {
    "editor_visible": True, "has_document": True, "agent_registered": True,
    "modified": False, "chat_visible": False, "definition_id": "loaded",
    "object_count": 1, "wire_count": 0,
    "nodes": [{"instance_id": NODE, "selected": True}], "wires": [],
    "same_document_instance": True, "previous_document_retained": True,
    "verification": {"pass": True},
}


@pytest.mark.parametrize("document_id", [None, "", "bad", "00000000-0000-0000-0000-000000000000", 7])
def test_attach_requires_measured_document_guid_before_connection(document_id):
    with patch("rhinoclaw.tools.grasshopper_canvas.get_rhino_connection") as connect:
        result = json.loads(attach_grasshopper_definition(None, document_id))
    assert result["code"] == "INVALID_PARAMS"
    connect.assert_not_called()


@pytest.mark.parametrize("changed", [
    {}, {"document_id": "another"}, {"same_document_instance": False},
    {"user_owned": False}, {"solution_requested": True}, {"definition_id": None},
    {"agent_registered": False}, {"has_document": False},
])
def test_attach_verifies_document_and_retained_ownership(changed):
    connection = MagicMock()
    connection.send_command.return_value = {
        **CANVAS, "document_id": NODE, "user_owned": True, "solution_requested": False, **changed,
    }
    with patch("rhinoclaw.tools.grasshopper_canvas.get_rhino_connection", return_value=connection):
        result = json.loads(attach_grasshopper_definition(None, NODE))
    assert result["success"] is (not changed)
    connection.send_command.assert_called_once_with("attach_grasshopper_definition", {"document_id": NODE})
    if changed:
        assert result["code"] == "VERIFICATION_FAILED"
        assert "canvas" in result["data"]


def invoke(result, **kwargs):
    connection = MagicMock()
    connection.send_command.return_value = result
    with patch("rhinoclaw.tools.grasshopper_canvas.get_rhino_connection", return_value=connection):
        response = json.loads(show_grasshopper_definition(None, "loaded", **kwargs))
    return response, connection


def test_same_definition_and_exact_selection_verified():
    result, connection = invoke(CANVAS, component_instance_ids=[NODE])
    assert result["success"] is True
    connection.send_command.assert_called_once_with("show_grasshopper_definition", {
        "definition_id": "loaded", "component_instance_ids": [NODE], "zoom": True, "open_chat": False,
    })


@pytest.mark.parametrize("changed", [
    {"definition_id": "other"}, {"same_document_instance": False},
    {"editor_visible": False}, {"verification": {"pass": False}},
    {"previous_document_retained": False}, {"object_count": 2},
    {"object_count": True}, {"nodes": []}, {"wire_count": 1},
    {"modified": "false"}, {"agent_registered": True, "definition_id": None},
])
def test_unproven_presentation_never_succeeds(changed):
    result, _ = invoke({**CANVAS, **changed})
    assert result["success"] is False
    assert result["code"] == "VERIFICATION_FAILED"


def test_chat_and_selection_are_not_assumed_from_request():
    assert invoke(CANVAS, open_chat=True)[0]["success"] is False
    assert invoke(CANVAS, component_instance_ids=[])[0]["success"] is False
    assert invoke({**CANVAS, "chat_visible": True}, open_chat=True)[0]["success"] is True


@pytest.mark.parametrize("kwargs", [
    {"component_instance_ids": ["bad"]}, {"component_instance_ids": [NODE, NODE]},
    {"component_instance_ids": [None]}, {"component_instance_ids": NODE},
    {"component_instance_ids": [NODE] * 2001}, {"zoom": 1}, {"open_chat": "yes"},
])
def test_bad_params_fail_before_connection(kwargs):
    with patch("rhinoclaw.tools.grasshopper_canvas.get_rhino_connection") as connect:
        result = json.loads(show_grasshopper_definition(None, "loaded", **kwargs))
    assert result["code"] == "INVALID_PARAMS"
    connect.assert_not_called()


def test_empty_canvas_is_valid_and_does_not_open_ui():
    connection = MagicMock()
    connection.send_command.return_value = {
        "editor_visible": False, "has_document": False, "agent_registered": False,
        "modified": False, "chat_visible": False, "definition_id": None,
        "object_count": 0, "wire_count": 0, "nodes": [], "wires": [],
    }
    with patch("rhinoclaw.tools.grasshopper_canvas.get_rhino_connection", return_value=connection):
        result = json.loads(get_grasshopper_canvas(None))
    assert result["success"] is True
    connection.send_command.assert_called_once_with("get_grasshopper_canvas", {})


@pytest.mark.parametrize("visible", [True, False])
def test_load_preserves_definition_id_if_show_fails(visible):
    from rhinoclaw.tools.load_grasshopper_definition import load_grasshopper_definition
    connection = MagicMock()
    connection.send_command.return_value = {
        "definition_id": "loaded", "parameters": [],
        "parameter_identity": "parameter_instance_id", "settable_parameter_count": 0,
    }
    with patch("rhinoclaw.tools.load_grasshopper_definition.get_rhino_connection", return_value=connection), \
         patch("rhinoclaw.tools.load_grasshopper_definition.show_grasshopper_definition",
               return_value=json.dumps({"success": visible, "data": CANVAS})) as show:
        result = json.loads(load_grasshopper_definition(None, "C:/fixture.gh", show_in_grasshopper=True))
    assert result["success"] is visible
    assert result["data"]["definition_id"] == "loaded"
    show.assert_called_once_with(None, "loaded")


@pytest.mark.parametrize("shown,clean", [(True, True), (False, True), (False, False)])
def test_build_shows_only_clean_graph_and_keeps_presentation_evidence(shown, clean):
    from rhinoclaw.tools.build_gh_definition import build_gh_definition
    slider = {"type": "slider", "name": "Width", "default": 200, "min": 10, "max": 1000}

    connection = MagicMock()
    connection.send_command.return_value = {
        "status": "success" if clean else "success_with_errors",
        "errors": [] if clean else ["bad wire"], "object_count": 1,
        "catalog_verification": {},
    }
    with patch("rhinoclaw.tools.build_gh_definition.get_rhino_connection", return_value=connection), \
         patch("rhinoclaw.tools.build_gh_definition.require_catalog_verification"), \
         patch("rhinoclaw.tools.build_gh_definition.load_grasshopper_definition",
               return_value=json.dumps({"success": shown, "data": {"definition_id": "loaded"}})) as load:
        result = json.loads(build_gh_definition(None, "C:/fixture.gh", [slider], show_in_grasshopper=True))
    assert result["success"] is (shown and clean)
    if clean:
        load.assert_called_once_with(None, "C:/fixture.gh", show_in_grasshopper=True)
        assert result["data"]["presentation"]["data"]["definition_id"] == "loaded"
    else:
        load.assert_not_called()


def test_presented_unload_releases_handle_without_disposal():
    root = Path(__file__).resolve().parents[2]
    source = (root / "rhinoclaw_plugin/Functions/GrasshopperApiOperations.cs").read_text(encoding="utf-8")
    unload = source[source.index("public JObject UnloadGrasshopperDefinition"):]
    retained = unload[unload.index("if (_presentedDefinitions.Contains"):unload.index("Instances.DocumentServer?.RemoveDocument")]
    assert '["status"] = "released"' in retained
    assert "Dispose" not in retained
    assert "_loadedDefinitions.Remove" in retained
    assert source.index("RequireGrasshopperPathNotOpen(filePath)") < source.index("archive.ReadFromFile")
    builder = (root / "rhinoclaw_plugin/Functions/GrasshopperDefinitionBuilder.cs").read_text(encoding="utf-8")
    assert "RequireGrasshopperPathNotOpen(filePath);" in builder


def test_companion_reuses_panel_without_stealing_current_panel_and_cleans_up():
    root = Path(__file__).resolve().parents[2]
    source = (root / "rhinoclaw_plugin/UI/GrasshopperWorkspace.cs").read_text(encoding="utf-8")
    assert "new ClawChatPanel(registerAsCurrent: false)" in source
    assert "panel.StartFloatingFeeds()" in source
    assert "timer.Stop(); timer.Dispose(); panel.Dispose();" in source
    assert "RhinoApp.Idle +=" not in source
