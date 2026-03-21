"""
Tests for the modify_object tool.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestModifyObjectSuccess:
    """Tests for successful object modification."""

    @patch("rhinoclaw.tools.modify_object.get_rhino_connection")
    def test_modify_by_id(self, mock_get_conn):
        from rhinoclaw.tools.modify_object import modify_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"name": "TestObject", "id": "test-guid"}
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = modify_object(
            ctx,
            id="test-guid-123",
            new_color=[255, 0, 0]
        )
        
        assert "Modified" in result
        assert "TestObject" in result

    @patch("rhinoclaw.tools.modify_object.get_rhino_connection")
    def test_modify_by_name(self, mock_get_conn):
        from rhinoclaw.tools.modify_object import modify_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"name": "MyBox", "id": "box-guid"}
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = modify_object(
            ctx,
            name="MyBox",
            new_color=[0, 255, 0]
        )
        
        assert "MyBox" in result
        assert "Modified" in result

    @patch("rhinoclaw.tools.modify_object.get_rhino_connection")
    def test_translate_object(self, mock_get_conn):
        from rhinoclaw.tools.modify_object import modify_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"name": "translated", "id": "trans-guid"}
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = modify_object(
            ctx,
            id="test-guid",
            translation=[10, 20, 30]
        )
        
        call_args = mock_rhino.send_command.call_args
        assert call_args[0][1]["translation"] == [10, 20, 30]

    @patch("rhinoclaw.tools.modify_object.get_rhino_connection")
    def test_rotate_object(self, mock_get_conn):
        from rhinoclaw.tools.modify_object import modify_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"name": "rotated", "id": "rot-guid"}
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = modify_object(
            ctx,
            id="test-guid",
            rotation=[0, 0, 1.57]  # 90 degrees in radians
        )
        
        call_args = mock_rhino.send_command.call_args
        assert call_args[0][1]["rotation"] == [0, 0, 1.57]

    @patch("rhinoclaw.tools.modify_object.get_rhino_connection")
    def test_scale_object(self, mock_get_conn):
        from rhinoclaw.tools.modify_object import modify_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"name": "scaled", "id": "scale-guid"}
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = modify_object(
            ctx,
            id="test-guid",
            scale=[2, 2, 2]
        )
        
        call_args = mock_rhino.send_command.call_args
        assert call_args[0][1]["scale"] == [2, 2, 2]

    @patch("rhinoclaw.tools.modify_object.get_rhino_connection")
    def test_rename_object(self, mock_get_conn):
        from rhinoclaw.tools.modify_object import modify_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"name": "NewName", "id": "rename-guid"}
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = modify_object(
            ctx,
            name="OldName",
            new_name="NewName"
        )
        
        call_args = mock_rhino.send_command.call_args
        assert call_args[0][1]["new_name"] == "NewName"


class TestModifyObjectErrors:
    """Tests for error handling.
    
    Note: modify_object returns plain error strings, not JSON.
    """

    @patch("rhinoclaw.tools.modify_object.get_rhino_connection")
    def test_object_not_found(self, mock_get_conn):
        from rhinoclaw.tools.modify_object import modify_object
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("Object not found")
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = modify_object(
            ctx,
            id="nonexistent-guid"
        )
        
        # modify_object returns JSON error response
        response = json.loads(result)
        assert response["success"] is False
        assert "Object not found" in response["message"]

    @patch("rhinoclaw.tools.modify_object.get_rhino_connection")
    def test_connection_error(self, mock_get_conn):
        from rhinoclaw.tools.modify_object import modify_object
        
        mock_get_conn.side_effect = Exception("Connection refused")
        
        ctx = MagicMock()
        result = modify_object(
            ctx,
            id="test-guid"
        )
        
        # modify_object returns JSON error response
        response = json.loads(result)
        assert response["success"] is False
        assert "Connection refused" in response["message"]
