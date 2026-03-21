"""
Tests for set_render_settings tool.
"""
import json
from unittest.mock import Mock, patch

from rhinoclaw.tools.set_render_settings import set_render_settings


class TestSetRenderSettingsValidation:
    """Validation tests for set_render_settings."""

    def test_missing_height(self):
        result = set_render_settings(None, width=1920, height=None)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    def test_negative_width(self):
        result = set_render_settings(None, width=-1, height=1080)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    def test_missing_all_params(self):
        result = set_render_settings(None)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    def test_invalid_quality(self):
        result = set_render_settings(None, quality="ultra")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"


class TestSetRenderSettingsSuccess:
    """Success tests for set_render_settings."""

    @patch("rhinoclaw.tools.set_render_settings.get_rhino_connection")
    def test_set_render_settings_success(self, mock_get_conn):
        mock_conn = Mock()
        mock_conn.send_command.return_value = {"status": "success"}
        mock_get_conn.return_value = mock_conn

        result = set_render_settings(None, width=800, height=600, quality="good")
        parsed = json.loads(result)

        assert parsed["success"] is True
        mock_conn.send_command.assert_called_once_with("set_render_settings", {
            "width": 800,
            "height": 600,
            "quality": "good"
        })


class TestSetRenderSettingsError:
    """Error handling tests for set_render_settings."""

    @patch("rhinoclaw.tools.set_render_settings.get_rhino_connection")
    def test_set_render_settings_connection_error(self, mock_get_conn):
        mock_get_conn.side_effect = Exception("Connection failed")

        result = set_render_settings(None, width=800, height=600)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "RHINO_ERROR"
