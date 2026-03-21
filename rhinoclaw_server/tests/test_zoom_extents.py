"""
Tests for the zoom_extents tool.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestZoomExtentsSuccess:
    """Tests for successful zoom_extents operations."""

    @patch("rhinoclaw.tools.zoom_extents.get_rhino_connection")
    def test_zoom_extents_default(self, mock_get_conn):
        from rhinoclaw.tools.zoom_extents import zoom_extents

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {"status": "success"}
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = zoom_extents(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "Perspective" in parsed["message"]
        assert "extents" in parsed["message"]
        mock_conn.send_command.assert_called_once_with("zoom_extents", {
            "viewport_name": "Perspective",
            "include_hidden": True
        })

    @patch("rhinoclaw.tools.zoom_extents.get_rhino_connection")
    def test_zoom_extents_custom_viewport(self, mock_get_conn):
        from rhinoclaw.tools.zoom_extents import zoom_extents

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {"status": "success"}
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = zoom_extents(ctx, viewport_name="Top", include_hidden=False)
        parsed = json.loads(result)

        assert parsed["success"] is True
        mock_conn.send_command.assert_called_once_with("zoom_extents", {
            "viewport_name": "Top",
            "include_hidden": False
        })


class TestZoomExtentsError:
    """Tests for zoom_extents error handling."""

    @patch("rhinoclaw.tools.zoom_extents.get_rhino_connection")
    def test_rhino_connection_error(self, mock_get_conn):
        from rhinoclaw.tools.zoom_extents import zoom_extents

        mock_conn = MagicMock()
        mock_conn.send_command.side_effect = Exception("Connection failed")
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = zoom_extents(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]