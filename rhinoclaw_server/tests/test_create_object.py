"""
Tests for the create_object tool.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestCreateObjectValidation:
    """Tests for create_object parameter validation."""

    @patch("rhinoclaw.tools.create_object.get_rhino_connection")
    def test_invalid_object_type(self, mock_get_conn):
        from rhinoclaw.tools.create_object import create_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("Unknown object type: INVALID")
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = create_object(ctx, type="INVALID", params={"x": 0, "y": 0, "z": 0})
        parsed = json.loads(result)
        
        assert parsed["success"] is False
        assert "INVALID" in parsed["message"] or "Unknown" in parsed["message"]

    @patch("rhinoclaw.tools.create_object.get_rhino_connection")
    def test_valid_box_params(self, mock_get_conn):
        from rhinoclaw.tools.create_object import create_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"name": "TestBox", "id": "test-guid"}
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = create_object(
            ctx, 
            type="BOX", 
            name="TestBox",
            params={"width": 10, "length": 10, "height": 10}
        )
        parsed = json.loads(result)
        
        assert parsed["success"] is True
        assert "BOX" in parsed["message"]


class TestCreateObjectSuccess:
    """Tests for successful object creation."""

    @patch("rhinoclaw.tools.create_object.get_rhino_connection")
    def test_create_box(self, mock_get_conn):
        from rhinoclaw.tools.create_object import create_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"name": "MyBox", "id": "box-guid-123"}
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = create_object(
            ctx,
            type="BOX",
            name="MyBox",
            params={"width": 5, "length": 5, "height": 5}
        )
        parsed = json.loads(result)
        
        assert parsed["success"] is True
        assert "MyBox" in parsed["message"]
        assert parsed["data"]["name"] == "MyBox"
        
        mock_rhino.send_command.assert_called_once()
        call_args = mock_rhino.send_command.call_args
        assert call_args[0][0] == "create_object"
        assert call_args[0][1]["type"] == "BOX"

    @patch("rhinoclaw.tools.create_object.get_rhino_connection")
    def test_create_sphere(self, mock_get_conn):
        from rhinoclaw.tools.create_object import create_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"name": "MySphere", "id": "sphere-guid"}
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = create_object(
            ctx,
            type="SPHERE",
            name="MySphere",
            params={"radius": 10}
        )
        parsed = json.loads(result)
        
        assert parsed["success"] is True
        assert "SPHERE" in parsed["message"]

    @patch("rhinoclaw.tools.create_object.get_rhino_connection")
    def test_create_with_color(self, mock_get_conn):
        from rhinoclaw.tools.create_object import create_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"name": "ColoredBox", "id": "color-guid"}
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = create_object(
            ctx,
            type="BOX",
            name="ColoredBox",
            color=[255, 0, 0],
            params={"width": 5, "length": 5, "height": 5}
        )
        
        call_args = mock_rhino.send_command.call_args
        assert call_args[0][1]["color"] == [255, 0, 0]

    @patch("rhinoclaw.tools.create_object.get_rhino_connection")
    def test_create_with_translation(self, mock_get_conn):
        from rhinoclaw.tools.create_object import create_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"name": "TranslatedBox", "id": "trans-guid"}
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = create_object(
            ctx,
            type="BOX",
            name="TranslatedBox",
            translation=[10, 20, 30],
            params={"width": 5, "length": 5, "height": 5}
        )
        
        call_args = mock_rhino.send_command.call_args
        assert call_args[0][1]["translation"] == [10, 20, 30]


class TestCreateObjectCurves:
    """Tests for curve object creation."""

    @patch("rhinoclaw.tools.create_object.get_rhino_connection")
    def test_create_line(self, mock_get_conn):
        from rhinoclaw.tools.create_object import create_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"name": "MyLine", "id": "line-guid"}
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = create_object(
            ctx,
            type="LINE",
            name="MyLine",
            params={"start": [0, 0, 0], "end": [10, 10, 10]}
        )
        parsed = json.loads(result)
        
        assert parsed["success"] is True
        assert "LINE" in parsed["message"]

    @patch("rhinoclaw.tools.create_object.get_rhino_connection")
    def test_create_circle(self, mock_get_conn):
        from rhinoclaw.tools.create_object import create_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"name": "MyCircle", "id": "circle-guid"}
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = create_object(
            ctx,
            type="CIRCLE",
            name="MyCircle",
            params={"center": [0, 0, 0], "radius": 5}
        )
        parsed = json.loads(result)
        
        assert parsed["success"] is True
        assert "CIRCLE" in parsed["message"]


class TestCreateObjectErrors:
    """Tests for error handling."""

    @patch("rhinoclaw.tools.create_object.get_rhino_connection")
    def test_connection_error(self, mock_get_conn):
        from rhinoclaw.tools.create_object import create_object
        
        mock_get_conn.side_effect = Exception("Connection refused")
        
        ctx = MagicMock()
        result = create_object(
            ctx,
            type="BOX",
            params={"width": 5, "length": 5, "height": 5}
        )
        
        parsed = json.loads(result)
        assert parsed["success"] is False

    @patch("rhinoclaw.tools.create_object.get_rhino_connection")
    def test_rhino_error(self, mock_get_conn):
        from rhinoclaw.tools.create_object import create_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("Invalid geometry")
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = create_object(
            ctx,
            type="BOX",
            params={"width": 5, "length": 5, "height": 5}
        )
        
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "Invalid geometry" in parsed["message"]
