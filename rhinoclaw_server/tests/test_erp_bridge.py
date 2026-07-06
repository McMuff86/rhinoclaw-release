"""Tests for the erp_list_tools / erp_invoke MCP tools (RhinoERPBridge coupling)."""
import json
from unittest.mock import MagicMock, patch


class TestErpListTools:
    @patch("rhinoclaw.tools.erp_bridge.get_rhino_connection")
    def test_returns_manifest(self, mock_get_conn):
        from rhinoclaw.tools.erp_bridge import erp_list_tools
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "tools": [
                {"name": "erp_info", "description": "…", "inputSchema": {"type": "object"}},
                {"name": "erp_search_article", "description": "…", "inputSchema": {"type": "object"}},
            ],
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = erp_list_tools(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is True
        names = [t["name"] for t in parsed["data"]["tools"]]
        assert "erp_search_article" in names
        mock_rhino.send_command.assert_called_once_with("erp_list_tools")

    @patch("rhinoclaw.tools.erp_bridge.get_rhino_connection")
    def test_bridge_missing_maps_to_error(self, mock_get_conn):
        from rhinoclaw.tools.erp_bridge import erp_list_tools
        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception(
            "Plugin 'RhinoERPBridge' is not installed or not loaded")
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        parsed = json.loads(erp_list_tools(ctx))

        assert parsed["success"] is False
        assert "RhinoERPBridge" in parsed["message"]


class TestErpInvoke:
    @patch("rhinoclaw.tools.erp_bridge.get_rhino_connection")
    def test_passes_tool_and_parsed_args(self, mock_get_conn):
        from rhinoclaw.tools.erp_bridge import erp_invoke
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"ok": True, "result": [{"sku": "be-100"}]}
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = erp_invoke(ctx, tool="erp_search_article",
                            args='{"query": "scharnier", "maxResults": 5}')
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["ok"] is True
        mock_rhino.send_command.assert_called_once_with(
            "erp_invoke",
            {"tool": "erp_search_article", "args": {"query": "scharnier", "maxResults": 5}},
        )

    def test_invalid_args_json_rejected_before_wire(self):
        from rhinoclaw.tools.erp_bridge import erp_invoke
        ctx = MagicMock()
        parsed = json.loads(erp_invoke(ctx, tool="erp_info", args="{kaputt"))

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    @patch("rhinoclaw.tools.erp_bridge.get_rhino_connection")
    def test_default_args_is_empty_object(self, mock_get_conn):
        from rhinoclaw.tools.erp_bridge import erp_invoke
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"ok": True, "result": {}}
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        erp_invoke(ctx, tool="erp_info")

        sent = mock_rhino.send_command.call_args[0][1]
        assert sent == {"tool": "erp_info", "args": {}}
