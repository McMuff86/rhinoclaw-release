"""Tests for the list_capabilities MCP tool."""
import json
from unittest.mock import MagicMock, patch


class TestListCapabilities:
    @patch("rhinoclaw.tools.list_capabilities.get_rhino_connection")
    def test_returns_categorised_inventory(self, mock_get_conn):
        from rhinoclaw.tools.list_capabilities import list_capabilities

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "plugin_version": "0.2.8",
            "rhino_version": "8.17",
            "categories": {
                "geometry": ["create_object", "delete_object"],
                "scene_analysis": ["find_nearby", "is_inside"],
                "batch": ["batch_operations"],
            },
            "native_command_allowlist": ["_Loft", "_Sweep1"],
            "scripting_paths": {
                "rhinoscriptsyntax": {"tool": "execute_rhinoscript_python_code"},
                "rhinocommon": {"tool": "execute_python3_code"},
            },
            "preferences": ["1. Typed command...", "2. batch..."],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = list_capabilities(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "0.2.8" in parsed["message"]
        assert "3 command categories" in parsed["message"]
        assert parsed["data"]["categories"]["geometry"] == ["create_object", "delete_object"]
        assert "_Loft" in parsed["data"]["native_command_allowlist"]
        mock_rhino.send_command.assert_called_once_with("list_capabilities", {})

    @patch("rhinoclaw.tools.list_capabilities.get_rhino_connection")
    def test_error_propagates(self, mock_get_conn):
        from rhinoclaw.tools.list_capabilities import list_capabilities

        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("Connection refused")
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = list_capabilities(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]
