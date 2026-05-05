"""Tests for the undo / redo MCP tools."""
import json
from unittest.mock import MagicMock, patch


class TestUndo:
    @patch("rhinoclaw.tools.undo.get_rhino_connection")
    def test_undo_success(self, mock_get_conn):
        from rhinoclaw.tools.undo import undo

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "success": True,
            "did_undo": True,
            "message": "Rolled back the previous action.",
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = undo(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["did_undo"] is True
        assert "Rolled back" in parsed["message"]
        mock_rhino.send_command.assert_called_once_with("undo", {})

    @patch("rhinoclaw.tools.undo.get_rhino_connection")
    def test_undo_empty_stack(self, mock_get_conn):
        from rhinoclaw.tools.undo import undo

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "success": True,
            "did_undo": False,
            "message": "Nothing to undo (stack is empty).",
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = undo(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["did_undo"] is False
        assert "Nothing to undo" in parsed["message"]

    @patch("rhinoclaw.tools.undo.get_rhino_connection")
    def test_undo_error(self, mock_get_conn):
        from rhinoclaw.tools.undo import undo

        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("No active document.")
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = undo(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]


class TestRedo:
    @patch("rhinoclaw.tools.redo.get_rhino_connection")
    def test_redo_success(self, mock_get_conn):
        from rhinoclaw.tools.redo import redo

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "success": True,
            "did_redo": True,
            "message": "Re-applied the previously undone action.",
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = redo(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["did_redo"] is True
        assert "Re-applied" in parsed["message"]
        mock_rhino.send_command.assert_called_once_with("redo", {})

    @patch("rhinoclaw.tools.redo.get_rhino_connection")
    def test_redo_empty_stack(self, mock_get_conn):
        from rhinoclaw.tools.redo import redo

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "success": True,
            "did_redo": False,
            "message": "Nothing to redo (no undone actions on the stack).",
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = redo(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["did_redo"] is False

    @patch("rhinoclaw.tools.redo.get_rhino_connection")
    def test_redo_error(self, mock_get_conn):
        from rhinoclaw.tools.redo import redo

        mock_get_conn.side_effect = Exception("Connection refused")

        ctx = MagicMock()
        result = redo(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is False
