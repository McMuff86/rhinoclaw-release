"""Tests for the run_native_command MCP tool."""
import json
from unittest.mock import MagicMock, patch


class TestRunNativeCommand:
    @patch("rhinoclaw.tools.run_native_command.get_rhino_connection")
    def test_basic_call(self, mock_get_conn):
        from rhinoclaw.tools.run_native_command import run_native_command
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "command": "_Loft",
            "script": "_Loft _Pause _Pause _Enter",
            "success": True,
            "message": "Native command '_Loft' executed.",
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = run_native_command(ctx, command="_Loft",
                                     args=["_Pause", "_Pause", "_Enter"])
        parsed = json.loads(result)

        assert parsed["success"] is True
        sent = mock_rhino.send_command.call_args[0][1]
        assert sent["command"] == "_Loft"
        assert sent["args"] == ["_Pause", "_Pause", "_Enter"]
        assert sent["echo"] is False

    @patch("rhinoclaw.tools.run_native_command.get_rhino_connection")
    def test_omits_args_when_not_given(self, mock_get_conn):
        from rhinoclaw.tools.run_native_command import run_native_command
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "command": "_ZoomExtents", "success": True, "message": "ok",
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        run_native_command(ctx, command="_ZoomExtents")

        sent = mock_rhino.send_command.call_args[0][1]
        assert "args" not in sent
        assert sent["echo"] is False

    def test_empty_command_rejected(self):
        from rhinoclaw.tools.run_native_command import run_native_command
        ctx = MagicMock()
        result = run_native_command(ctx, command="")
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    @patch("rhinoclaw.tools.run_native_command.get_rhino_connection")
    def test_rejection_propagates(self, mock_get_conn):
        from rhinoclaw.tools.run_native_command import run_native_command
        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception(
            "Native command '_DangerousThing' is not in the allowlist."
        )
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = run_native_command(ctx, command="_DangerousThing")
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "allowlist" in parsed["message"]
