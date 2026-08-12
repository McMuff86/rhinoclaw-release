"""
Tests for the capture_viewport tool.
"""
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rhinoclaw.utils.errors import RhinoCommandError


PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class TestCaptureViewportValidation:
    """Tests for capture_viewport parameter validation."""

    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_invalid_dimensions(self, mock_get_conn):
        from rhinoclaw.tools.capture_viewport import capture_viewport

        ctx = MagicMock()

        # Test zero width
        result = capture_viewport(ctx, width=0, height=100)
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]

        # Test zero height
        result = capture_viewport(ctx, width=100, height=0)
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]

        # Test negative dimensions
        result = capture_viewport(ctx, width=-100, height=100)
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]

        mock_get_conn.assert_not_called()

    @pytest.mark.parametrize(
        ("width", "height", "message"),
        [
            (16_385, 1, "16384 pixels per dimension"),
            (8192, 4096, "33177600-pixel budget"),
        ],
    )
    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_excessive_dimensions_fail_before_connecting(
        self,
        mock_get_conn,
        width,
        height,
        message,
    ):
        from rhinoclaw.tools.capture_viewport import capture_viewport

        parsed = json.loads(capture_viewport(
            MagicMock(),
            width=width,
            height=height,
        ))

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"
        assert message in parsed["message"]
        mock_get_conn.assert_not_called()


class TestCaptureViewportSuccess:
    """Tests for successful capture_viewport operations."""

    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_capture_viewport_base64(self, mock_get_conn):
        """When auto_save=False, filename stays None and base64 is returned."""
        from rhinoclaw.tools.capture_viewport import capture_viewport

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {
            "status": "success",
            "image_data": "base64data",
            "viewport": "Perspektive",
        }
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = capture_viewport(ctx, auto_save=False)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "Perspektive" in parsed["message"]
        assert "1920x1080" in parsed["message"]
        mock_conn.send_command.assert_called_once_with(
            "capture_viewport",
            {"width": 1920, "height": 1080, "filename": None},
        )

    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_capture_viewport_to_file(self, mock_get_conn, tmp_path):
        """Relative filenames are decoded and saved by the MCP server."""
        from rhinoclaw.tools.capture_viewport import capture_viewport

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {
            "status": "success",
            "image_data": PNG_BASE64,
            "format": "png",
            "viewport": "Perspektive",
        }
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        with patch(
            "rhinoclaw.tools.capture_viewport.get_screenshots_dir",
            return_value=tmp_path,
        ):
            result = capture_viewport(
                ctx,
                filename="nested/screenshot.png",
                width=1024,
                height=768,
            )
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "Perspektive" in parsed["message"]
        assert "saved on MCP server" in parsed["message"]
        call_args = mock_conn.send_command.call_args
        assert call_args[0][0] == "capture_viewport"
        sent_params = call_args[0][1]
        assert "viewport_name" not in sent_params
        assert sent_params["width"] == 1024
        assert sent_params["height"] == 768
        assert sent_params["filename"] is None
        saved_to = Path(parsed["data"]["saved_to_file"])
        assert saved_to == tmp_path / "nested" / "screenshot.png"
        assert saved_to.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert parsed["data"]["save_location"] == "mcp_server"
        assert "image_data" not in parsed["data"]

    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_capture_viewport_custom_viewport(self, mock_get_conn, tmp_path):
        """Auto-save slugifies qualified detail names for Windows too."""
        from rhinoclaw.tools.capture_viewport import capture_viewport

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {
            "status": "success",
            "image_data": PNG_BASE64,
            "format": "png",
            "viewport": "Page 01::Detail East",
        }
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        with patch(
            "rhinoclaw.tools.capture_viewport.get_screenshots_dir",
            return_value=tmp_path,
        ):
            result = capture_viewport(ctx, viewport_name="Page 01::Detail East")
        parsed = json.loads(result)

        assert parsed["success"] is True
        call_args = mock_conn.send_command.call_args
        sent_params = call_args[0][1]
        assert sent_params["viewport_name"] == "Page 01::Detail East"
        assert sent_params["width"] == 1920
        assert sent_params["height"] == 1080
        assert sent_params["filename"] is None
        saved_to = Path(parsed["data"]["saved_to_file"])
        assert saved_to.parent == tmp_path
        assert saved_to.name.startswith("viewport_Page_01_Detail_East_")
        assert ":" not in saved_to.name
        assert saved_to.suffix == ".png"

    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_auto_save_names_do_not_collide_within_one_second(self, mock_get_conn, tmp_path):
        from rhinoclaw.tools.capture_viewport import capture_viewport

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {
            "status": "success",
            "image_data": PNG_BASE64,
            "viewport": "Perspektive",
        }
        mock_get_conn.return_value = mock_conn

        with (
            patch(
                "rhinoclaw.tools.capture_viewport.get_screenshots_dir",
                return_value=tmp_path,
            ),
            patch("rhinoclaw.utils.image_storage.datetime") as mock_datetime,
        ):
            mock_datetime.now.side_effect = [
                datetime(2026, 8, 8, 12, 0, 0, 123456),
                datetime(2026, 8, 8, 12, 0, 0, 654321),
            ]
            first = json.loads(capture_viewport(MagicMock()))
            second = json.loads(capture_viewport(MagicMock()))

        first_path = Path(first["data"]["saved_to_file"])
        second_path = Path(second["data"]["saved_to_file"])
        assert first_path != second_path
        assert first_path.name.endswith("_20260808_120000_123456.png")
        assert second_path.name.endswith("_20260808_120000_654321.png")
        assert first_path.exists()
        assert second_path.exists()

    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_capture_viewport_reports_layout_scope_truthfully(self, mock_get_conn):
        from rhinoclaw.tools.capture_viewport import capture_viewport

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {
            "status": "success",
            "viewport": "A101::Detail 01",
            "viewport_kind": "detail",
            "capture_scope": "layout_page",
            "captured_view": "A101",
            "image_data": "data",
        }
        mock_get_conn.return_value = mock_conn

        parsed = json.loads(capture_viewport(
            MagicMock(),
            viewport_name="A101::Detail 01",
            auto_save=False,
        ))

        assert parsed["success"] is True
        assert "Layout page 'A101'" in parsed["message"]
        assert "A101::Detail 01" in parsed["message"]


class TestCaptureViewportError:
    """Tests for capture_viewport error handling."""

    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_rhino_connection_error(self, mock_get_conn):
        from rhinoclaw.tools.capture_viewport import capture_viewport

        mock_conn = MagicMock()
        mock_conn.send_command.side_effect = Exception("Connection failed")
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = capture_viewport(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]

    @pytest.mark.parametrize(
        "error_code",
        ["INVALID_PARAMS", "AMBIGUOUS_REFERENCE"],
    )
    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_structured_plugin_error_reaches_mcp_response(
        self,
        mock_get_conn,
        error_code,
    ):
        from rhinoclaw.tools.capture_viewport import capture_viewport

        mock_conn = MagicMock()
        mock_conn.send_command.side_effect = RhinoCommandError(
            "Plugin rejected viewport request",
            error_code=error_code,
        )
        mock_get_conn.return_value = mock_conn

        parsed = json.loads(capture_viewport(MagicMock(), auto_save=False))

        assert parsed["success"] is False
        assert parsed["code"] == error_code


class TestCaptureViewportStorageRouting:
    """Tests for the WSL/POSIX versus Windows save boundary."""

    @pytest.mark.parametrize(
        "filename",
        [
            r"C:\captures\perspective.jpg",
            r"\\fileserver\rhino\perspective.png",
            "//fileserver/rhino/perspective.jpeg",
        ],
    )
    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_windows_and_unc_paths_are_saved_by_rhino(self, mock_get_conn, filename):
        from rhinoclaw.tools.capture_viewport import capture_viewport

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {
            "status": "success",
            "viewport": "Perspektive",
            "saved_to_file": filename,
        }
        mock_get_conn.return_value = mock_conn

        parsed = json.loads(capture_viewport(MagicMock(), filename=filename))

        assert parsed["success"] is True
        assert parsed["data"]["save_location"] == "rhino_host"
        assert parsed["data"]["format"] in {"png", "jpeg"}
        assert "saved on Rhino host" in parsed["message"]
        sent_params = mock_conn.send_command.call_args.args[1]
        assert sent_params["filename"] == filename

    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_posix_absolute_path_is_never_sent_to_rhino(self, mock_get_conn, tmp_path):
        from rhinoclaw.tools.capture_viewport import capture_viewport

        destination = tmp_path / "capture.png"
        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {
            "status": "success",
            "viewport": "Perspektive",
            "image_data": PNG_BASE64,
        }
        mock_get_conn.return_value = mock_conn

        parsed = json.loads(capture_viewport(MagicMock(), filename=str(destination)))

        assert parsed["success"] is True
        assert destination.exists()
        assert parsed["data"]["saved_to_file"] == str(destination)
        assert mock_conn.send_command.call_args.args[1]["filename"] is None

    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_relative_path_cannot_escape_screenshots(self, mock_get_conn, tmp_path):
        from rhinoclaw.tools.capture_viewport import capture_viewport

        with patch(
            "rhinoclaw.tools.capture_viewport.get_screenshots_dir",
            return_value=tmp_path,
        ):
            parsed = json.loads(capture_viewport(MagicMock(), filename=r"..\escape.png"))

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"
        mock_get_conn.assert_not_called()

    @pytest.mark.parametrize(
        "filename",
        [
            "capture.jpg",
            "capture.gif",
            "nested/NUL.png",
            r"C:\captures\NUL.png",
            "C:\\captures\\COM¹.png",
            r"C:\captures\CONOUT$.png",
            r"\\?\C:\captures\view.png",
            r"\\.\C:\captures\view.png",
            r"\\fileserver\share\..\view.png",
        ],
    )
    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_unsafe_server_local_filename_is_rejected(self, mock_get_conn, filename):
        from rhinoclaw.tools.capture_viewport import capture_viewport

        parsed = json.loads(capture_viewport(MagicMock(), filename=filename))

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"
        mock_get_conn.assert_not_called()

    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_invalid_plugin_base64_is_not_reported_as_saved(self, mock_get_conn, tmp_path):
        from rhinoclaw.tools.capture_viewport import capture_viewport

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {
            "status": "success",
            "viewport": "Perspektive",
            "image_data": "not base64!",
        }
        mock_get_conn.return_value = mock_conn

        destination = tmp_path / "capture.png"
        parsed = json.loads(capture_viewport(MagicMock(), filename=str(destination)))

        assert parsed["success"] is False
        assert parsed["code"] == "RHINO_ERROR"
        assert "invalid base64" in parsed["message"]
        assert not destination.exists()
