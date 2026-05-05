"""Tests for the get_auth_status tool."""
import json
import os
from unittest.mock import MagicMock, patch


class TestAuthStatus:
    @patch("rhinoclaw.tools.get_auth_status.get_settings")
    @patch("rhinoclaw.tools.get_auth_status.get_rhino_connection")
    def test_no_token_configured(self, mock_get_conn, mock_get_settings):
        from rhinoclaw.tools.get_auth_status import get_auth_status

        mock_settings = MagicMock()
        mock_settings.auth_token = None
        mock_get_settings.return_value = mock_settings

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"pong": True}
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = get_auth_status(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["client_sends_token"] is False
        assert parsed["data"]["token_fingerprint"] is None
        assert "NOT sending" in parsed["message"]

    @patch("rhinoclaw.tools.get_auth_status.get_settings")
    @patch("rhinoclaw.tools.get_auth_status.get_rhino_connection")
    def test_token_accepted(self, mock_get_conn, mock_get_settings):
        from rhinoclaw.tools.get_auth_status import get_auth_status

        # Realistic 43-char base64-style token.
        token = "abcd" + "x" * 35 + "wxyz"
        mock_settings = MagicMock()
        mock_settings.auth_token = token
        mock_get_settings.return_value = mock_settings

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"pong": True}
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = get_auth_status(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["data"]["client_sends_token"] is True
        assert parsed["data"]["plugin_accepts_token"] is True
        # Fingerprint exposes only first 4 + last 4 chars.
        assert parsed["data"]["token_fingerprint"] == "abcd...wxyz"
        assert "Auth verified" in parsed["message"]

    @patch("rhinoclaw.tools.get_auth_status.get_settings")
    @patch("rhinoclaw.tools.get_auth_status.get_rhino_connection")
    def test_token_rejected_by_plugin(self, mock_get_conn, mock_get_settings):
        from rhinoclaw.tools.get_auth_status import get_auth_status

        mock_settings = MagicMock()
        mock_settings.auth_token = "wrong-token"
        mock_get_settings.return_value = mock_settings

        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception(
            "Auth token missing or invalid"
        )
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = get_auth_status(ctx)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "invalid" in parsed["message"].lower() or "missing" in parsed["message"].lower()

    @patch("rhinoclaw.tools.get_auth_status.get_settings")
    @patch("rhinoclaw.tools.get_auth_status.get_rhino_connection")
    def test_short_token_fingerprint_masked(self, mock_get_conn, mock_get_settings):
        from rhinoclaw.tools.get_auth_status import get_auth_status

        # Short tokens get fully masked instead of partial reveal.
        mock_settings = MagicMock()
        mock_settings.auth_token = "short"
        mock_get_settings.return_value = mock_settings

        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"pong": True}
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = get_auth_status(ctx)
        parsed = json.loads(result)
        assert parsed["data"]["token_fingerprint"] == "*****"
