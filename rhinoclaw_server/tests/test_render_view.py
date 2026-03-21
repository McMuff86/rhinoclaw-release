"""
Tests for render_view tool.
"""
import json
from unittest.mock import Mock, patch

from rhinoclaw.tools.render_view import render_view


class TestRenderViewValidation:
    """Validation tests for render_view."""

    def test_missing_height(self):
        result = render_view(None, width=800, height=None)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    def test_negative_width(self):
        result = render_view(None, width=-1, height=600)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    def test_invalid_display_mode(self):
        result = render_view(None, display_mode="preview")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"


class TestRenderViewSuccess:
    """Success tests for render_view."""

    @patch("rhinoclaw.tools.render_view.get_rhino_connection")
    def test_render_view_success(self, mock_get_conn):
        mock_conn = Mock()
        mock_conn.send_command.return_value = {"status": "success"}
        mock_get_conn.return_value = mock_conn

        result = render_view(
            None,
            viewport_name="Perspective",
            width=800,
            height=600,
            filename="render.png",
            display_mode="rendered"
        )
        parsed = json.loads(result)

        assert parsed["success"] is True
        mock_conn.send_command.assert_called_once_with("render_view", {
            "viewport_name": "Perspective",
            "display_mode": "rendered",
            "filename": "render.png",
            "width": 800,
            "height": 600
        })


class TestRenderViewError:
    """Error handling tests for render_view."""

    @patch("rhinoclaw.tools.render_view.get_rhino_connection")
    def test_render_view_connection_error(self, mock_get_conn):
        mock_get_conn.side_effect = Exception("Connection failed")

        result = render_view(None, viewport_name="Perspective")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "RHINO_ERROR"
