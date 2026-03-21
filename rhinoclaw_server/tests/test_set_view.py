"""
Tests for the set_view tool.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestSetViewValidation:
    """Tests for set_view parameter validation."""

    @patch("rhinoclaw.tools.set_view.get_rhino_connection")
    def test_missing_view_type(self, mock_get_conn):
        from rhinoclaw.tools.set_view import set_view

        ctx = MagicMock()
        result = set_view(ctx, view_type=None)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]


class TestSetViewSuccess:
    """Tests for successful set_view operations."""

    @patch("rhinoclaw.tools.set_view.get_rhino_connection")
    def test_set_view_top(self, mock_get_conn):
        from rhinoclaw.tools.set_view import set_view

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {"status": "success"}
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = set_view(ctx, view_type="Top")
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["message"] == "Viewport 'Perspective' set to Top view"
        mock_conn.send_command.assert_called_once_with("set_view", {
            "view_type": "Top",
            "viewport_name": "Perspective"
        })

    @patch("rhinoclaw.tools.set_view.get_rhino_connection")
    def test_set_view_custom_viewport(self, mock_get_conn):
        from rhinoclaw.tools.set_view import set_view

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {"status": "success"}
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = set_view(ctx, view_type="Front", viewport_name="Top")
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "Top" in parsed["message"]
        assert "Front" in parsed["message"]
        mock_conn.send_command.assert_called_once_with("set_view", {
            "view_type": "Front",
            "viewport_name": "Top"
        })

    @patch("rhinoclaw.tools.set_view.get_rhino_connection")
    def test_set_view_perspective(self, mock_get_conn):
        from rhinoclaw.tools.set_view import set_view

        mock_conn = MagicMock()
        mock_conn.send_command.return_value = {"status": "success"}
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = set_view(ctx, view_type="Perspective")
        parsed = json.loads(result)

        assert parsed["success"] is True
        mock_conn.send_command.assert_called_once_with("set_view", {
            "view_type": "Perspective",
            "viewport_name": "Perspective"
        })


class TestSetViewError:
    """Tests for set_view error handling."""

    @patch("rhinoclaw.tools.set_view.get_rhino_connection")
    def test_rhino_connection_error(self, mock_get_conn):
        from rhinoclaw.tools.set_view import set_view

        mock_conn = MagicMock()
        mock_conn.send_command.side_effect = Exception("Connection failed")
        mock_get_conn.return_value = mock_conn

        ctx = MagicMock()
        result = set_view(ctx, view_type="Top")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]