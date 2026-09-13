"""Regressions for the September 8 native session's agent-facing failures."""
import json
from unittest.mock import MagicMock, patch

import pytest

from rhinoclaw.tools.create_layer import create_layer
from rhinoclaw.utils.errors import ErrorCode, RhinoCommandError
from rhinoclaw.utils.interaction_logger import InteractionLogger


def test_create_layer_exposes_native_identity_in_json():
    layer = {"id": "test-layer-id", "name": "Live test", "color": [45, 165, 105]}
    with patch("rhinoclaw.tools.create_layer.get_rhino_connection") as connect:
        connect.return_value.send_command.return_value = layer
        response = json.loads(create_layer(MagicMock(), name="Live test", color=[45, 165, 105]))
    assert response["success"] is True
    assert response["data"] == layer


@pytest.mark.parametrize("error, code", [
    (RuntimeError("Layer insertion failed"), ErrorCode.CREATE_LAYER_ERROR),
    (RhinoCommandError("Paused by user", "USER_CANCELLED"), "USER_CANCELLED"),
])
def test_create_layer_failure_is_machine_readable(error, code):
    with patch("rhinoclaw.tools.create_layer.get_rhino_connection") as connect:
        connect.return_value.send_command.side_effect = error
        response = json.loads(create_layer(MagicMock(), name="Live test"))
    assert response["success"] is False
    assert response["code"] == code
    assert str(error) in response["message"]


@pytest.mark.parametrize("explicit_override", [False, True])
def test_interaction_logs_write_to_requested_directory(tmp_path, monkeypatch, explicit_override):
    environment_dir = tmp_path / "environment"
    explicit_dir = tmp_path / "explicit"
    monkeypatch.setenv("RHINOCLAW_LOG_DIR", str(environment_dir))
    writer = InteractionLogger(log_dir=str(explicit_dir) if explicit_override else None)
    writer.log_tool_call("session_probe", {}, True)
    expected = explicit_dir if explicit_override else environment_dir
    files = list(expected.glob("interactions_*.jsonl"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["tool_name"] == "session_probe"
    if explicit_override:
        assert not environment_dir.exists()
