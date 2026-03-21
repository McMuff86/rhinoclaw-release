"""
Tests for add_light tool.
"""
import json
from unittest.mock import Mock, patch

from rhinoclaw.tools.add_light import add_light


class TestAddLightValidation:
    """Validation tests for add_light."""

    def test_missing_light_type(self):
        result = add_light(None, light_type=None)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    def test_point_requires_location(self):
        result = add_light(None, light_type="point", location=None)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    def test_directional_requires_direction(self):
        result = add_light(None, light_type="directional", direction=None)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    def test_spot_requires_target(self):
        result = add_light(None, light_type="spot", location=[0, 0, 0], target=None)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"


class TestAddLightSuccess:
    """Success tests for add_light."""

    @patch("rhinoclaw.tools.add_light.get_rhino_connection")
    def test_add_light_point_success(self, mock_get_conn):
        mock_conn = Mock()
        mock_conn.send_command.return_value = {"status": "success"}
        mock_get_conn.return_value = mock_conn

        result = add_light(None, light_type="point", location=[1.0, 2.0, 3.0])
        parsed = json.loads(result)

        assert parsed["success"] is True
        mock_conn.send_command.assert_called_once_with("add_light", {
            "light_type": "point",
            "color": [255, 255, 255],
            "intensity": 1.0,
            "location": [1.0, 2.0, 3.0]
        })


class TestAddLightError:
    """Error handling tests for add_light."""

    @patch("rhinoclaw.tools.add_light.get_rhino_connection")
    def test_add_light_connection_error(self, mock_get_conn):
        mock_get_conn.side_effect = Exception("Connection failed")

        result = add_light(None, light_type="point", location=[0, 0, 0])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "RHINO_ERROR"
