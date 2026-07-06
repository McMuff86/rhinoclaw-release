"""Tests for rhinoclaw_doctor (NEXT-LEVEL-PLAN 1.5)."""
import json
from unittest.mock import MagicMock, patch

from rhinoclaw import __version__

# Version-agnostic: the healthy mock always matches the current server
# version (plugin reports a 4-segment build number).
HELLO_OK = {"plugin_version": f"{__version__}.0", "auth_required": True,
            "mode": "tcpstart", "gh_available": True}


def _rhino(hello=HELLO_OK, ping_error=None):
    rhino = MagicMock()

    def send_command(command, params=None):
        if command == "hello":
            return dict(hello)
        if command == "ping":
            if ping_error:
                raise ping_error
            return {"timestamp": "now"}
        raise AssertionError(command)

    rhino.send_command.side_effect = send_command
    return rhino


def _statuses(data):
    return {c["check"]: c["status"] for c in data["checks"]}


READY_UI = json.dumps({"success": True, "data": {
    "busy": False, "diagnosis": "ready"}})
BUSY_UI = json.dumps({"success": True, "data": {
    "busy": True, "diagnosis": "A MODAL DIALOG is open"}})


def _patch_ui(payload=READY_UI):
    return patch("rhinoclaw.tools.check_setup.get_ui_state",
                 return_value=payload)


def test_healthy_setup_is_ready():
    from rhinoclaw.tools.check_setup import rhinoclaw_doctor

    with patch("rhinoclaw.tools.check_setup.get_rhino_connection",
               return_value=_rhino()), _patch_ui():
        data = json.loads(rhinoclaw_doctor(MagicMock()))["data"]

    statuses = _statuses(data)
    assert data["ready"] is True
    assert statuses["connection"] == "PASS"
    assert statuses["auth"] == "PASS"
    assert statuses["version"] == "PASS"          # X.Y.Z.0 startswith X.Y.Z
    assert statuses["grasshopper"] == "PASS"
    assert "FAIL" not in statuses.values()


def test_connection_down_fails_fast_with_fix():
    from rhinoclaw.tools.check_setup import rhinoclaw_doctor

    with patch("rhinoclaw.tools.check_setup.get_rhino_connection",
               side_effect=ConnectionError("refused")):
        data = json.loads(rhinoclaw_doctor(MagicMock()))["data"]

    assert data["ready"] is False
    [check] = data["checks"]
    assert check["check"] == "connection"
    assert check["status"] == "FAIL"
    assert "tcpstart" in check["fix"]


def test_auth_rejection_is_a_fail_with_token_fix():
    from rhinoclaw.tools.check_setup import rhinoclaw_doctor

    with patch("rhinoclaw.tools.check_setup.get_rhino_connection",
               return_value=_rhino(ping_error=Exception("Auth token missing"))), \
         _patch_ui():
        data = json.loads(rhinoclaw_doctor(MagicMock()))["data"]

    statuses = _statuses(data)
    assert statuses["auth"] == "FAIL"
    assert data["ready"] is False
    fix = next(c["fix"] for c in data["checks"] if c["check"] == "auth")
    assert "RHINOCLAW_AUTH_TOKEN" in fix


def test_version_mismatch_and_missing_gh_warn_but_stay_ready():
    from rhinoclaw.tools.check_setup import rhinoclaw_doctor

    hello = {"plugin_version": "0.4.0.0", "auth_required": False,
             "mode": "mcpstart", "gh_available": False}
    with patch("rhinoclaw.tools.check_setup.get_rhino_connection",
               return_value=_rhino(hello=hello)), _patch_ui():
        data = json.loads(rhinoclaw_doctor(MagicMock()))["data"]

    statuses = _statuses(data)
    assert statuses["version"] == "WARN"
    assert statuses["grasshopper"] == "WARN"
    assert data["ready"] is True  # warnings don't block readiness


def test_busy_ui_warns_but_stays_ready():
    from rhinoclaw.tools.check_setup import rhinoclaw_doctor

    with patch("rhinoclaw.tools.check_setup.get_rhino_connection",
               return_value=_rhino()), _patch_ui(BUSY_UI):
        data = json.loads(rhinoclaw_doctor(MagicMock()))["data"]

    statuses = _statuses(data)
    assert statuses["ui_state"] == "WARN"
    assert data["ready"] is True  # busy is transient, not broken
    fix = next(c["fix"] for c in data["checks"] if c["check"] == "ui_state")
    assert "Rhino screen" in fix
