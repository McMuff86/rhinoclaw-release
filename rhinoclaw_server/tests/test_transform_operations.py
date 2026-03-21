"""Tests for transform operations (copy, mirror, array)."""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestCopyObject:
    """Tests for copy_object tool."""
    
    def test_copy_object_basic(self):
        """Test basic object copy."""
        with patch('rhinoclaw.tools.copy_object.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "source_id": "test-guid-123",
                "copy_ids": ["new-guid-456"],
                "count": 1
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.copy_object import copy_object
            
            result = json.loads(copy_object(None, "test-guid-123"))
            
            assert result["success"] is True
            assert "copy" in result["message"].lower()
            mock_rhino.send_command.assert_called_once_with("copy_object", {
                "object_id": "test-guid-123",
                "translation": [0, 0, 0],
                "count": 1
            })
    
    def test_copy_object_with_translation(self):
        """Test copy with translation vector."""
        with patch('rhinoclaw.tools.copy_object.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "source_id": "test-guid",
                "copy_ids": ["copy1", "copy2"],
                "count": 2
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.copy_object import copy_object
            
            result = json.loads(copy_object(None, "test-guid", [10, 0, 0], 2))
            
            assert result["success"] is True
            mock_rhino.send_command.assert_called_once_with("copy_object", {
                "object_id": "test-guid",
                "translation": [10, 0, 0],
                "count": 2
            })
    
    def test_copy_object_missing_id(self):
        """Test error when object_id is missing."""
        from rhinoclaw.tools.copy_object import copy_object
        
        result = json.loads(copy_object(None, ""))
        
        assert result["success"] is False
        assert "INVALID_PARAMS" in result.get("code", "")
    
    def test_copy_object_invalid_count(self):
        """Test error when count is less than 1."""
        from rhinoclaw.tools.copy_object import copy_object
        
        result = json.loads(copy_object(None, "test-guid", None, 0))
        
        assert result["success"] is False
        assert "count" in result.get("message", "").lower()


class TestMirrorObject:
    """Tests for mirror_object tool."""
    
    def test_mirror_object_xy_plane(self):
        """Test mirror across XY plane."""
        with patch('rhinoclaw.tools.mirror_object.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "source_id": "test-guid",
                "mirror_id": "mirrored-guid",
                "deleted_input": False
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.mirror_object import mirror_object
            
            result = json.loads(mirror_object(
                None, 
                "test-guid",
                [0, 0, 0],  # origin
                [0, 0, 1]   # Z normal = XY plane
            ))
            
            assert result["success"] is True
            assert "mirror" in result["message"].lower()
    
    def test_mirror_object_with_delete(self):
        """Test mirror with delete_input=True."""
        with patch('rhinoclaw.tools.mirror_object.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "source_id": "test-guid",
                "mirror_id": "mirrored-guid",
                "deleted_input": True
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.mirror_object import mirror_object
            
            result = json.loads(mirror_object(
                None,
                "test-guid",
                [0, 0, 0],
                [1, 0, 0],
                True  # delete_input
            ))
            
            assert result["success"] is True
            mock_rhino.send_command.assert_called_once()
            call_args = mock_rhino.send_command.call_args[0]
            assert call_args[1]["delete_input"] is True
    
    def test_mirror_object_invalid_origin(self):
        """Test error with invalid plane_origin."""
        from rhinoclaw.tools.mirror_object import mirror_object
        
        result = json.loads(mirror_object(
            None,
            "test-guid",
            [0, 0],  # Invalid - only 2 elements
            [0, 0, 1]
        ))
        
        assert result["success"] is False
        assert "plane_origin" in result.get("message", "").lower()


class TestArrayLinear:
    """Tests for array_linear tool."""
    
    def test_array_linear_basic(self):
        """Test basic linear array."""
        with patch('rhinoclaw.tools.array_linear.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "source_id": "test-guid",
                "array_ids": ["copy1", "copy2", "copy3", "copy4"],
                "total_count": 5,
                "spacing": 10.0
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.array_linear import array_linear
            
            result = json.loads(array_linear(
                None,
                "test-guid",
                [1, 0, 0],  # X direction
                5,          # count
                10.0        # spacing
            ))
            
            assert result["success"] is True
            assert "array" in result["message"].lower()
    
    def test_array_linear_invalid_count(self):
        """Test error when count < 2."""
        from rhinoclaw.tools.array_linear import array_linear
        
        result = json.loads(array_linear(
            None,
            "test-guid",
            [1, 0, 0],
            1,  # Invalid - must be at least 2
            10.0
        ))
        
        assert result["success"] is False
        assert "count" in result.get("message", "").lower()
    
    def test_array_linear_invalid_spacing(self):
        """Test error when spacing <= 0."""
        from rhinoclaw.tools.array_linear import array_linear
        
        result = json.loads(array_linear(
            None,
            "test-guid",
            [1, 0, 0],
            5,
            -10.0  # Invalid - must be positive
        ))
        
        assert result["success"] is False
        assert "spacing" in result.get("message", "").lower()


class TestArrayPolar:
    """Tests for array_polar tool."""
    
    def test_array_polar_full_circle(self):
        """Test polar array with full 360 degrees."""
        with patch('rhinoclaw.tools.array_polar.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "source_id": "test-guid",
                "array_ids": ["copy1", "copy2", "copy3", "copy4", "copy5"],
                "total_count": 6,
                "angle": 360.0
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.array_polar import array_polar
            
            result = json.loads(array_polar(
                None,
                "test-guid",
                [0, 0, 0],  # center
                [0, 0, 1],  # Z axis
                6           # count
            ))
            
            assert result["success"] is True
            assert "polar" in result["message"].lower()
    
    def test_array_polar_partial_arc(self):
        """Test polar array with partial angle."""
        with patch('rhinoclaw.tools.array_polar.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "source_id": "test-guid",
                "array_ids": ["copy1", "copy2", "copy3"],
                "total_count": 4,
                "angle": 180.0
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.array_polar import array_polar
            
            result = json.loads(array_polar(
                None,
                "test-guid",
                [0, 0, 0],
                [0, 0, 1],
                4,
                180.0  # Half circle
            ))
            
            assert result["success"] is True
            call_args = mock_rhino.send_command.call_args[0]
            assert call_args[1]["angle"] == 180.0
    
    def test_array_polar_invalid_count(self):
        """Test error when count < 2."""
        from rhinoclaw.tools.array_polar import array_polar
        
        result = json.loads(array_polar(
            None,
            "test-guid",
            [0, 0, 0],
            [0, 0, 1],
            1  # Invalid - must be at least 2
        ))
        
        assert result["success"] is False
        assert "count" in result.get("message", "").lower()
    
    def test_array_polar_invalid_axis(self):
        """Test error with invalid axis."""
        from rhinoclaw.tools.array_polar import array_polar
        
        result = json.loads(array_polar(
            None,
            "test-guid",
            [0, 0, 0],
            [0, 0],  # Invalid - only 2 elements
            6
        ))
        
        assert result["success"] is False
        assert "axis" in result.get("message", "").lower()
