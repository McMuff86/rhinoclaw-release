"""
Tests for the capture_viewport tool.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


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


class TestCaptureViewportSuccess:
    """Tests for successful capture_viewport operations."""

    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_capture_viewport_base64(self, mock_get_conn):
        from rhinoclaw.tools.capture_viewport import capture_viewport

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {"status": "success", "image_data": "base64data"}
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = capture_viewport(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "Perspective" in parsed["message"]
        assert "1920x1080" in parsed["message"]
        mock_conn.send_command.assert_called_once_with("capture_viewport", {
            "viewport_name": "Perspective",
            "width": 1920,
            "height": 1080,
            "filename": None
        })

    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_capture_viewport_to_file(self, mock_get_conn):
        from rhinoclaw.tools.capture_viewport import capture_viewport

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {"status": "success", "saved_to_file": "screenshot.png"}
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = capture_viewport(ctx, filename="screenshot.png", width=1024, height=768)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "Perspective" in parsed["message"]
        mock_conn.send_command.assert_called_once_with("capture_viewport", {
            "viewport_name": "Perspective",
            "width": 1024,
            "height": 768,
            "filename": "screenshot.png"
        })

    @patch("rhinoclaw.tools.capture_viewport.get_rhino_connection")
    def test_capture_viewport_custom_viewport(self, mock_get_conn):
        from rhinoclaw.tools.capture_viewport import capture_viewport

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {"status": "success", "image_data": "data"}
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = capture_viewport(ctx, viewport_name="Top")
        parsed = json.loads(result)

        assert parsed["success"] is True
        mock_conn.send_command.assert_called_once_with("capture_viewport", {
            "viewport_name": "Top",
            "width": 1920,
            "height": 1080,
            "filename": None
        })


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