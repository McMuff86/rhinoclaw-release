"""Tests for run_grasshopper tool."""
import pytest
import json
from unittest.mock import MagicMock, patch


class TestRunGrasshopper:
    """Tests for run_grasshopper tool."""

    def test_run_grasshopper_success(self):
        """Test successful Grasshopper execution."""
        from rhinoclaw.tools.run_grasshopper import run_grasshopper

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "C:/test/script.gh",
            "status": "executed"
        }

        with patch("rhinoclaw.tools.run_grasshopper.get_rhino_connection", return_value=mock_rhino):
            result = run_grasshopper(mock_ctx, "C:/test/script.gh")

        result_data = json.loads(result)
        assert result_data["success"] is True
        assert "file_path" in result_data["data"]
        mock_rhino.send_command.assert_called_once()

    def test_run_grasshopper_empty_path(self):
        """Test run with empty path fails."""
        from rhinoclaw.tools.run_grasshopper import run_grasshopper

        mock_ctx = MagicMock()

        result = run_grasshopper(mock_ctx, "")
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "file_path is required" in result_data["message"]

    def test_run_grasshopper_wrong_extension(self):
        """Test run with non-.gh file fails."""
        from rhinoclaw.tools.run_grasshopper import run_grasshopper

        mock_ctx = MagicMock()

        result = run_grasshopper(mock_ctx, "C:/test/script.py")
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert ".gh" in result_data["message"]

    def test_run_grasshopper_with_spaces(self):
        """Test run with path containing spaces."""
        from rhinoclaw.tools.run_grasshopper import run_grasshopper

        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "C:/test folder/script.gh",
            "status": "executed"
        }

        with patch("rhinoclaw.tools.run_grasshopper.get_rhino_connection", return_value=mock_rhino):
            result = run_grasshopper(mock_ctx, "C:/test folder/script.gh")

        result_data = json.loads(result)
        assert result_data["success"] is True
        # Verify the path was passed correctly
        call_args = mock_rhino.send_command.call_args
        assert call_args[0][1]["file_path"] == "C:/test folder/script.gh"


# Note: Tests for run_grasshopper_with_params and run_grasshopper_automated
# have been removed as these functions were deprecated in favor of the
# WebSocket-based grasshopper_interactive module.
# See tests/test_grasshopper_interactive.py for the new tests.
