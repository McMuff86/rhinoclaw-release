"""
Tests for render_view tool.
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from rhinoclaw.tools.render_view import render_view


PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


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

    @pytest.mark.parametrize(
        ("width", "height", "message"),
        [
            (16_385, 1, "16384 pixels per dimension"),
            (8192, 4096, "33177600-pixel budget"),
        ],
    )
    @patch("rhinoclaw.tools.render_view.get_rhino_connection")
    def test_excessive_dimensions_fail_before_connecting(
        self,
        mock_get_conn,
        width,
        height,
        message,
    ):
        parsed = json.loads(render_view(None, width=width, height=height))

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"
        assert message in parsed["message"]
        mock_get_conn.assert_not_called()


class TestRenderViewSuccess:
    """Success tests for render_view."""

    @patch("rhinoclaw.tools.render_view.get_rhino_connection")
    def test_render_view_success(self, mock_get_conn, tmp_path):
        mock_conn = Mock()
        mock_conn.send_command.return_value = {
            "status": "success",
            "image_data": PNG_BASE64,
            "viewport": "Perspektive",
        }
        mock_get_conn.return_value = mock_conn

        with patch(
            "rhinoclaw.tools.render_view.get_screenshots_dir",
            return_value=tmp_path,
        ):
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
        assert "saved on MCP server" in parsed["message"]
        saved_to = Path(parsed["data"]["saved_to_file"])
        assert saved_to == tmp_path / "render.png"
        assert saved_to.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert parsed["data"]["save_location"] == "mcp_server"
        assert "image_data" not in parsed["data"]
        mock_conn.send_command.assert_called_once_with("render_view", {
            "viewport_name": "Perspective",
            "display_mode": "rendered",
            "filename": None,
            "width": 800,
            "height": 600
        })

    @patch("rhinoclaw.tools.render_view.get_rhino_connection")
    def test_windows_render_path_is_saved_by_rhino(self, mock_get_conn):
        filename = r"C:\captures\render.jpg"
        mock_conn = Mock()
        mock_conn.send_command.return_value = {
            "status": "success",
            "viewport": "Perspektive",
            "saved_to_file": filename,
            "bytes_written": 1234,
        }
        mock_get_conn.return_value = mock_conn

        parsed = json.loads(render_view(None, filename=filename))

        assert parsed["success"] is True
        assert parsed["data"]["save_location"] == "rhino_host"
        assert parsed["data"]["format"] == "jpeg"
        assert parsed["data"]["bytes_written"] == 1234
        assert "saved on Rhino host" in parsed["message"]
        assert mock_conn.send_command.call_args.args[1]["filename"] == filename

    @pytest.mark.parametrize(
        "filename",
        [
            r"C:\captures\AUX.png",
            r"\\?\C:\captures\render.png",
            r"\\.\C:\captures\render.png",
            r"\\server\share\..\render.png",
        ],
    )
    @patch("rhinoclaw.tools.render_view.get_rhino_connection")
    def test_unsafe_host_render_path_is_rejected(
        self,
        mock_get_conn,
        filename,
    ):
        parsed = json.loads(render_view(None, filename=filename))

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"
        mock_get_conn.assert_not_called()

    @patch("rhinoclaw.tools.render_view.get_rhino_connection")
    def test_render_view_reports_layout_scope_truthfully(self, mock_get_conn):
        mock_conn = Mock()
        mock_conn.send_command.return_value = {
            "status": "success",
            "viewport": "A101::Detail 01",
            "capture_scope": "layout_page",
            "captured_view": "A101",
        }
        mock_get_conn.return_value = mock_conn

        parsed = json.loads(render_view(
            None,
            viewport_name="A101::Detail 01",
        ))

        assert parsed["success"] is True
        assert "layout page 'A101'" in parsed["message"]
        assert "A101::Detail 01" in parsed["message"]


class TestRenderViewError:
    """Error handling tests for render_view."""

    @patch("rhinoclaw.tools.render_view.get_rhino_connection")
    def test_render_view_connection_error(self, mock_get_conn):
        mock_get_conn.side_effect = Exception("Connection failed")

        result = render_view(None, viewport_name="Perspective")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "RHINO_ERROR"
