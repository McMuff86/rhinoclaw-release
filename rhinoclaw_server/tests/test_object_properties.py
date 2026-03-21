"""
Unit tests for get_object_properties and set_object_properties tools.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestGetObjectProperties:
    """Tests for get_object_properties tool."""

    def test_get_object_properties_requires_object_id(self):
        """Test that either object_id or object_ids is required."""
        from rhinoclaw.tools.get_object_properties import get_object_properties
        
        ctx = MagicMock()
        result = json.loads(get_object_properties(ctx))
        
        assert result["success"] is False
        assert "object_id" in result["message"].lower() or "object_ids" in result["message"].lower()

    def test_get_object_properties_accepts_single_id(self):
        """Test that single object_id is accepted."""
        from rhinoclaw.tools.get_object_properties import get_object_properties
        
        ctx = MagicMock()
        
        with patch("rhinoclaw.tools.get_object_properties.get_rhino_connection") as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "id": "test-guid",
                "bounding_box": {"min": [0, 0, 0], "max": [1, 1, 1]},
                "volume": 1.0
            }
            mock_conn.return_value = mock_rhino
            
            result = json.loads(get_object_properties(ctx, object_id="test-guid"))
            
            assert result["success"] is True
            mock_rhino.send_command.assert_called_once_with(
                "get_object_properties",
                {"object_id": "test-guid"}
            )

    def test_get_object_properties_accepts_batch_ids(self):
        """Test that batch object_ids is accepted."""
        from rhinoclaw.tools.get_object_properties import get_object_properties
        
        ctx = MagicMock()
        
        with patch("rhinoclaw.tools.get_object_properties.get_rhino_connection") as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "objects": [
                    {"id": "id1", "volume": 1.0},
                    {"id": "id2", "volume": 2.0}
                ],
                "count": 2
            }
            mock_conn.return_value = mock_rhino
            
            result = json.loads(get_object_properties(ctx, object_ids=["id1", "id2"]))
            
            assert result["success"] is True
            mock_rhino.send_command.assert_called_once_with(
                "get_object_properties",
                {"object_ids": ["id1", "id2"]}
            )

    def test_get_object_properties_handles_connection_error(self):
        """Test error handling for connection issues."""
        from rhinoclaw.tools.get_object_properties import get_object_properties
        
        ctx = MagicMock()
        
        with patch("rhinoclaw.tools.get_object_properties.get_rhino_connection") as mock_conn:
            mock_conn.side_effect = ConnectionError("Cannot connect to Rhino")
            
            result = json.loads(get_object_properties(ctx, object_id="test-guid"))
            
            assert result["success"] is False
            assert "connect" in result["message"].lower()


class TestSetObjectProperties:
    """Tests for set_object_properties tool."""

    def test_set_object_properties_requires_object_id(self):
        """Test that either object_id or object_ids is required."""
        from rhinoclaw.tools.set_object_properties import set_object_properties
        
        ctx = MagicMock()
        result = json.loads(set_object_properties(ctx, name="test"))
        
        assert result["success"] is False
        assert "object_id" in result["message"].lower() or "object_ids" in result["message"].lower()

    def test_set_object_properties_requires_property(self):
        """Test that at least one property must be specified."""
        from rhinoclaw.tools.set_object_properties import set_object_properties
        
        ctx = MagicMock()
        result = json.loads(set_object_properties(ctx, object_id="test-guid"))
        
        assert result["success"] is False
        assert "property" in result["message"].lower()

    def test_set_object_properties_validates_color_format(self):
        """Test color format validation."""
        from rhinoclaw.tools.set_object_properties import set_object_properties
        
        ctx = MagicMock()
        
        # Wrong length
        result = json.loads(set_object_properties(ctx, object_id="test", color=[255, 0]))
        assert result["success"] is False
        
        # Wrong type
        result = json.loads(set_object_properties(ctx, object_id="test", color="red"))
        assert result["success"] is False
        
        # Out of range
        result = json.loads(set_object_properties(ctx, object_id="test", color=[256, 0, 0]))
        assert result["success"] is False

    def test_set_object_properties_accepts_valid_color(self):
        """Test valid color is accepted."""
        from rhinoclaw.tools.set_object_properties import set_object_properties
        
        ctx = MagicMock()
        
        with patch("rhinoclaw.tools.set_object_properties.get_rhino_connection") as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {"modified_count": 1}
            mock_conn.return_value = mock_rhino
            
            result = json.loads(set_object_properties(ctx, object_id="test", color=[255, 128, 0]))
            
            assert result["success"] is True

    def test_set_object_properties_accepts_name(self):
        """Test setting object name."""
        from rhinoclaw.tools.set_object_properties import set_object_properties
        
        ctx = MagicMock()
        
        with patch("rhinoclaw.tools.set_object_properties.get_rhino_connection") as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {"modified_count": 1}
            mock_conn.return_value = mock_rhino
            
            result = json.loads(set_object_properties(ctx, object_id="test", name="MyObject"))
            
            assert result["success"] is True
            mock_rhino.send_command.assert_called_once()
            call_args = mock_rhino.send_command.call_args[0][1]
            assert call_args["name"] == "MyObject"

    def test_set_object_properties_accepts_layer(self):
        """Test setting object layer."""
        from rhinoclaw.tools.set_object_properties import set_object_properties
        
        ctx = MagicMock()
        
        with patch("rhinoclaw.tools.set_object_properties.get_rhino_connection") as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {"modified_count": 1}
            mock_conn.return_value = mock_rhino
            
            result = json.loads(set_object_properties(ctx, object_id="test", layer="Geometry"))
            
            assert result["success"] is True
            call_args = mock_rhino.send_command.call_args[0][1]
            assert call_args["layer"] == "Geometry"

    def test_set_object_properties_batch(self):
        """Test batch property setting."""
        from rhinoclaw.tools.set_object_properties import set_object_properties
        
        ctx = MagicMock()
        
        with patch("rhinoclaw.tools.set_object_properties.get_rhino_connection") as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {"modified_count": 3}
            mock_conn.return_value = mock_rhino
            
            result = json.loads(set_object_properties(
                ctx, 
                object_ids=["id1", "id2", "id3"], 
                color=[255, 0, 0]
            ))
            
            assert result["success"] is True
            call_args = mock_rhino.send_command.call_args[0][1]
            assert call_args["object_ids"] == ["id1", "id2", "id3"]

    def test_set_object_properties_handles_connection_error(self):
        """Test error handling for connection issues."""
        from rhinoclaw.tools.set_object_properties import set_object_properties
        
        ctx = MagicMock()
        
        with patch("rhinoclaw.tools.set_object_properties.get_rhino_connection") as mock_conn:
            mock_conn.side_effect = ConnectionError("Cannot connect to Rhino")
            
            result = json.loads(set_object_properties(ctx, object_id="test", name="New"))
            
            assert result["success"] is False


class TestObjectPropertiesIntegration:
    """Integration tests (require Rhino connection)."""

    @pytest.mark.skip(reason="Requires live Rhino connection")
    def test_get_properties_of_box(self):
        """Test getting properties of a box."""
        pass

    @pytest.mark.skip(reason="Requires live Rhino connection")
    def test_set_and_verify_properties(self):
        """Test setting and verifying object properties."""
        pass
