"""Tests for the busy/modal probe (the invisible-dialog detector)."""
import json
from unittest.mock import MagicMock, patch

PATCH = "rhinoclaw.tools.get_ui_state.get_rhino_connection"
PRINT = "Script successfully executed! Print output: "


def _rhino(state=None, error=None):
    rhino = MagicMock()
    if error:
        rhino.send_command.side_effect = error
    else:
        rhino.send_command.return_value = PRINT + "STATE:" + json.dumps(state)
    return rhino


def test_ready_state():
    from rhinoclaw.tools.get_ui_state import get_ui_state

    state = {"in_command": 0, "command_stack": [], "prompt": "Command",
             "main_window_enabled": True}
    with patch(PATCH, return_value=_rhino(state)):
        data = json.loads(get_ui_state(MagicMock()))["data"]

    assert data["busy"] is False
    assert data["modal_dialog_open"] is False
    assert data["diagnosis"] == "ready"


def test_modal_dialog_detected():
    from rhinoclaw.tools.get_ui_state import get_ui_state

    state = {"in_command": 0, "command_stack": [], "prompt": "Command",
             "main_window_enabled": False}
    with patch(PATCH, return_value=_rhino(state)):
        data = json.loads(get_ui_state(MagicMock()))["data"]

    assert data["busy"] is True
    assert data["modal_dialog_open"] is True
    assert "MODAL DIALOG" in data["diagnosis"]


def test_waiting_prompt_detected():
    from rhinoclaw.tools.get_ui_state import get_ui_state

    state = {"in_command": 1, "command_stack": ["GrasshopperPlayer"],
             "prompt": "Lichtbreite <900>", "main_window_enabled": True}
    with patch(PATCH, return_value=_rhino(state)):
        data = json.loads(get_ui_state(MagicMock()))["data"]

    assert data["busy"] is True
    assert "GrasshopperPlayer" in data["diagnosis"]
    assert "Lichtbreite" in data["diagnosis"]


def test_probe_timeout_is_itself_diagnostic():
    from rhinoclaw.tools.get_ui_state import get_ui_state

    with patch(PATCH, return_value=_rhino(error=Exception("No data received"))):
        result = json.loads(get_ui_state(MagicMock()))

    assert result["success"] is True  # the probe answered the QUESTION
    assert result["data"]["busy"] is True
    assert "blocked" in result["data"]["diagnosis"]


def test_wait_until_ready_returns_when_idle():
    from rhinoclaw.tools import get_ui_state as mod

    states = iter([
        json.dumps({"success": True, "data": {"busy": True}}),
        json.dumps({"success": True, "data": {"busy": True}}),
        json.dumps({"success": True, "data": {"busy": False}}),
    ])
    with patch.object(mod, "get_ui_state", side_effect=lambda ctx: next(states)), \
         patch.object(mod.time, "sleep"):
        data = json.loads(mod.wait_until_ready(MagicMock()))["data"]

    assert data["ready"] is True
    assert data["polls"] == 3


def test_wait_until_ready_timeout_carries_modal_hint():
    from rhinoclaw.tools import get_ui_state as mod

    busy = json.dumps({"success": True, "data": {
        "busy": True, "modal_dialog_open": True}})
    clock = iter([0.0, 0.0, 100.0, 100.0])
    with patch.object(mod, "get_ui_state", return_value=busy), \
         patch.object(mod.time, "sleep"), \
         patch.object(mod.time, "monotonic", side_effect=lambda: next(clock, 100.0)):
        data = json.loads(mod.wait_until_ready(MagicMock(), timeout=60))["data"]

    assert data["ready"] is False
    assert "close it on the Rhino screen" in data["hint"]
    assert data["last_state"]["modal_dialog_open"] is True
