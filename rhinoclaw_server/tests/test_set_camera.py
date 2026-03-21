"""
Tests for set_camera tool.
"""
import json
from unittest.mock import Mock, patch

from rhinoclaw.tools.set_camera import set_camera


class TestSetCameraValidation:
    """Validation tests for set_camera."""

    def test_missing_camera_location(self):
        result = set_camera(None, camera_location=None)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    def test_invalid_target(self):
        result = set_camera(None, camera_location=[0, 0, 0], target_location=[0, 1])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"


class TestSetCameraSuccess:
    """Success tests for set_camera."""

    @patch("rhinoclaw.tools.set_camera.get_rhino_connection")
    def test_set_camera_success(self, mock_get_conn):
        mock_conn = Mock()
        mock_conn.send_command.return_value = {"status": "success"}
        mock_get_conn.return_value = mock_conn

        result = set_camera(
            None,
            camera_location=[1.0, 2.0, 3.0],
            target_location=[0.0, 0.0, 0.0],
            lens_length=50.0,
            viewport_name="Perspective"
        )
        parsed = json.loads(result)

        assert parsed["success"] is True
        mock_conn.send_command.assert_called_once_with("set_camera", {
            "viewport_name": "Perspective",
            "camera_location": [1.0, 2.0, 3.0],
            "target_location": [0.0, 0.0, 0.0],
            "lens_length": 50.0
        })


class TestSetCameraError:
    """Error handling tests for set_camera."""

    @patch("rhinoclaw.tools.set_camera.get_rhino_connection")
    def test_set_camera_connection_error(self, mock_get_conn):
        mock_get_conn.side_effect = Exception("Connection failed")

        result = set_camera(None, camera_location=[1, 2, 3])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "RHINO_ERROR"
