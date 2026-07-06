"""Tests for the preflight tool — the deterministic connection/auth entry point."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _settings(token=None, host="127.0.0.1", port=1999):
    return SimpleNamespace(auth_token=token, host=host, port=port)


def _run(send_behavior, token=None, connect_raises=None):
    """send_behavior: a dict (return for any send_command) or a callable side_effect."""
    from rhinoclaw.tools.preflight import preflight

    mock_rhino = MagicMock()
    if callable(send_behavior):
        mock_rhino.send_command.side_effect = send_behavior
    else:
        mock_rhino.send_command.return_value = send_behavior

    grc = (MagicMock(side_effect=connect_raises) if connect_raises
           else MagicMock(return_value=mock_rhino))
    with patch("rhinoclaw.tools.preflight.get_settings", return_value=_settings(token)), \
         patch("rhinoclaw.tools.preflight.get_rhino_connection", grc):
        return json.loads(preflight(MagicMock()))["data"]


def test_ready_no_auth():
    d = _run({"plugin_version": "0.4.1", "mode": "tcpstart",
              "auth_required": False})
    assert d["auth"] == "ready"
    assert d["hello_supported"] is True
    assert d["plugin_version"] == "0.4.1"


def test_missing_client_token():
    d = _run({"auth_required": True,
              "mode": "tcpstart"}, token=None)
    assert d["auth"] == "missing_client_token"
    assert "RHINOCLAW_AUTH_TOKEN" in d["next_action"]


def test_blocked_passes_through_blocked_until():
    d = _run({"blocked": True, "blocked_until": "2026-06-05T10:00:00Z",
              "auth_required": True})
    assert d["auth"] == "blocked"
    assert d["blocked_until"] == "2026-06-05T10:00:00Z"
    assert "do NOT retry" in d["next_action"]


def test_auth_required_token_ok_is_ready():
    def sc(cmd, params):
        if cmd == "hello":
            return {"auth_required": True,
                    "mode": "mcpstart", "plugin_version": "0.4.1"}
        if cmd == "ping":
            return {"pong": True}
        raise AssertionError(cmd)
    d = _run(sc, token="secret")
    assert d["auth"] == "ready"


def test_auth_required_token_mismatch():
    def sc(cmd, params):
        if cmd == "hello":
            return {"auth_required": True,
                    "mode": "mcpstart"}
        if cmd == "ping":
            raise Exception("Auth token missing or invalid")
        raise AssertionError(cmd)
    d = _run(sc, token="wrong")
    assert d["auth"] == "token_mismatch"
    assert "restart Rhino" in d["next_action"]


def test_old_plugin_unknown_command_is_ready():
    def sc(cmd, params):
        raise Exception("Communication error with Rhino: Unknown command type: hello")
    d = _run(sc)
    assert d["auth"] == "ready"
    assert d["hello_supported"] is False


def test_old_plugin_auth_required_no_token():
    def sc(cmd, params):
        raise Exception("Auth token missing or invalid. Set RHINOCLAW_AUTH_TOKEN on the client.")
    d = _run(sc, token=None)
    assert d["auth"] == "missing_client_token"
    assert d["hello_supported"] is False
    assert "sync-skill" in d["next_action"]


def test_not_reachable():
    d = _run({"x": 1}, connect_raises=ConnectionError("Could not connect to Rhino"))
    assert d["connected"] is False
    assert d["auth"] == "unknown"
    assert "tcpstart" in d["next_action"]


class TestHello:
    def test_hello_passes_through(self):
        from rhinoclaw.tools.hello import hello
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "plugin_version": "0.4.1", "auth_required": True,
            "mode": "tcpstart", "gh_available": True,
        }
        with patch("rhinoclaw.tools.hello.get_rhino_connection", return_value=mock_rhino):
            d = json.loads(hello(MagicMock()))
        assert d["success"] is True
        assert d["data"]["plugin_version"] == "0.4.1"
        assert mock_rhino.send_command.call_args[0][0] == "hello"
