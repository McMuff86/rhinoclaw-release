"""Behavior regressions for domain failures and the new GH artifact contract."""
import importlib
import json
from unittest.mock import patch

import pytest

from rhinoclaw.tools.boolean_operation import boolean_operation
from rhinoclaw.tools.grasshopper_artifacts import capture_grasshopper_canvas, save_grasshopper_definition
from rhinoclaw.utils.gh_lint import lint_definition


@pytest.mark.parametrize("module,arguments,native", [
    ("open_file", {"file_path": "C:/scratch/new.3dm"}, {"success": False, "active_document_changed": True}),
    ("undo", {}, {"success": False, "did_undo": False, "outcome": "recording_active", "recording_state_before": {"current_record_serial": 39}}),
    ("redo", {}, {"success": False, "did_redo": False, "outcome": "no_change"}),
    ("delete_object", {"id": "exact"}, {"success": False, "deleted": False, "id": "exact"}),
    ("get_object_info", {"id": "exact"}, {"success": False, "id": "exact"}),
])
def test_domain_failure_retains_native_evidence(module, arguments, native):
    tool = importlib.import_module("rhinoclaw.tools." + module)
    with patch.object(tool, "get_rhino_connection") as connect:
        connect.return_value.send_command.return_value = native
        result = json.loads(getattr(tool, module)(None, **arguments))
    assert result["success"] is False
    assert result["data"] == native


@pytest.mark.parametrize("module,native", [
    ("delete_object", {"id": "exact", "name": "own", "deleted": True}),
    ("get_object_info", {"id": "exact", "name": "own", "geometry": {"volume": 27000000}}),
])
def test_normalized_envelope_keeps_exact_identity(module, native):
    tool = importlib.import_module("rhinoclaw.tools." + module)
    with patch.object(tool, "get_rhino_connection") as connect:
        connect.return_value.send_command.return_value = native
        result = json.loads(getattr(tool, module)(None, id="exact"))
    assert result["success"] is True
    assert result["data"] == native


def test_boolean_partial_result_ids_survive_transport_success():
    native = {"success": False, "error_code": "PARTIAL_MUTATION", "result_ids": ["fragment"],
              "deleted_input_ids": [], "retained_input_ids": ["base", "cut"]}
    with patch("rhinoclaw.tools.boolean_operation.get_rhino_connection") as connect:
        connect.return_value.send_command.return_value = native
        result = json.loads(boolean_operation(None, "difference", ["base", "cut"]))
    assert result["success"] is False
    assert result["code"] == "PARTIAL_MUTATION"
    assert result["data"] == native


@pytest.mark.parametrize("spec", [
    {"min": 2, "max": 2}, {"min": 3, "max": 2}, {"min": float("nan"), "max": 3},
    {"min": 0, "max": float("inf")}, {"min": True, "max": 3}, {"default": float("nan")},
    {"decimals": -1}, {"decimals": 13}, {"decimals": True},
])
def test_invalid_slider_never_reaches_rhino(spec):
    verdict = lint_definition([{"type": "slider", "name": "Divisor", **spec}], [], {})
    assert not verdict["valid"]
    assert any("slider" in issue for issue in verdict["errors"])


def test_constant_panel_is_supported():
    assert lint_definition([{"type": "panel", "name": "Divisor", "value": "2"}], [], {})["valid"]


@pytest.mark.parametrize("function,arguments", [
    (save_grasshopper_definition, {"definition_id": "graph", "file_path": "new.gh", "mode": "copy"}),
    (save_grasshopper_definition, {"definition_id": "graph", "file_path": "new.ghx", "mode": "save_as"}),
    (capture_grasshopper_canvas, {"definition_id": "graph", "file_path": "new.png"}),
])
@pytest.mark.parametrize("verification_pass", [True, False])
def test_artifact_verification_and_partial_file_evidence(function, arguments, verification_pass):
    native = {"success": verification_pass, "external_file_written": True, "written_file_path": "retained-file",
              "verification": {"pass": verification_pass}}
    with patch("rhinoclaw.tools.grasshopper_artifacts.get_rhino_connection") as connect:
        connect.return_value.send_command.return_value = native
        result = json.loads(function(None, **arguments))
        connect.return_value.send_command.assert_called_once_with(function.__name__, arguments)
    assert result["success"] is verification_pass
    assert result["data"] == native


def test_bad_artifact_request_does_not_connect():
    with patch("rhinoclaw.tools.grasshopper_artifacts.get_rhino_connection") as connect:
        assert not json.loads(save_grasshopper_definition(None, "", "new.gh"))["success"]
        assert not json.loads(save_grasshopper_definition(None, "graph", "new.gh", "overwrite"))["success"]
        assert not json.loads(capture_grasshopper_canvas(None, "graph", "new.jpg"))["success"]
        connect.assert_not_called()
