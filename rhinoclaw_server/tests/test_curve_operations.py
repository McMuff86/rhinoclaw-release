"""Tests for curve operations (offset, fillet, chamfer)."""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestOffsetCurve:
    """Tests for offset_curve tool."""
    
    def test_offset_curve_basic(self):
        """Test basic curve offset."""
        with patch('rhinoclaw.tools.offset_curve.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "source_id": "test-curve-123",
                "offset_ids": ["offset-curve-456"],
                "distance": 5.0,
                "corner_style": "sharp"
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.offset_curve import offset_curve
            
            result = json.loads(offset_curve(None, "test-curve-123", 5.0))
            
            assert result["success"] is True
            assert "offset" in result["message"].lower()
            mock_rhino.send_command.assert_called_once_with("offset_curve", {
                "curve_id": "test-curve-123",
                "distance": 5.0,
                "plane_origin": None,
                "plane_normal": [0, 0, 1],
                "corner_style": "sharp"
            })
    
    def test_offset_curve_negative_distance(self):
        """Test offset with negative distance (left side)."""
        with patch('rhinoclaw.tools.offset_curve.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "source_id": "test-curve",
                "offset_ids": ["offset-1"],
                "distance": -5.0,
                "corner_style": "sharp"
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.offset_curve import offset_curve
            
            result = json.loads(offset_curve(None, "test-curve", -5.0))
            
            assert result["success"] is True
    
    def test_offset_curve_with_corner_style(self):
        """Test offset with different corner styles."""
        with patch('rhinoclaw.tools.offset_curve.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "source_id": "test-curve",
                "offset_ids": ["offset-1"],
                "distance": 5.0,
                "corner_style": "round"
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.offset_curve import offset_curve
            
            result = json.loads(offset_curve(
                None, "test-curve", 5.0, None, None, "round"
            ))
            
            assert result["success"] is True
            call_args = mock_rhino.send_command.call_args[0]
            assert call_args[1]["corner_style"] == "round"
    
    def test_offset_curve_missing_id(self):
        """Test error when curve_id is missing."""
        from rhinoclaw.tools.offset_curve import offset_curve
        
        result = json.loads(offset_curve(None, "", 5.0))
        
        assert result["success"] is False
        assert "INVALID_PARAMS" in result.get("code", "")
    
    def test_offset_curve_zero_distance(self):
        """Test error when distance is zero."""
        from rhinoclaw.tools.offset_curve import offset_curve
        
        result = json.loads(offset_curve(None, "test-curve", 0))
        
        assert result["success"] is False
        assert "distance" in result.get("message", "").lower()
    
    def test_offset_curve_invalid_corner_style(self):
        """Test error with invalid corner style."""
        from rhinoclaw.tools.offset_curve import offset_curve
        
        result = json.loads(offset_curve(
            None, "test-curve", 5.0, None, None, "invalid"
        ))
        
        assert result["success"] is False
        assert "corner_style" in result.get("message", "").lower()


class TestFilletCurves:
    """Tests for fillet_curves tool."""
    
    def test_fillet_curves_basic(self):
        """Test basic curve fillet."""
        with patch('rhinoclaw.tools.fillet_curves.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "curve_id_1": "curve-1",
                "curve_id_2": "curve-2",
                "fillet_ids": ["fillet-arc"],
                "radius": 2.0,
                "joined": False
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.fillet_curves import fillet_curves
            
            result = json.loads(fillet_curves(None, "curve-1", "curve-2", 2.0))
            
            assert result["success"] is True
            assert "fillet" in result["message"].lower()
            mock_rhino.send_command.assert_called_once()
    
    def test_fillet_curves_with_join(self):
        """Test fillet with join=True."""
        with patch('rhinoclaw.tools.fillet_curves.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "curve_id_1": "curve-1",
                "curve_id_2": "curve-2",
                "fillet_ids": ["joined-curve"],
                "radius": 2.0,
                "joined": True
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.fillet_curves import fillet_curves
            
            result = json.loads(fillet_curves(
                None, "curve-1", "curve-2", 2.0, None, None, True
            ))
            
            assert result["success"] is True
            call_args = mock_rhino.send_command.call_args[0]
            assert call_args[1]["join"] is True
    
    def test_fillet_curves_missing_curve_1(self):
        """Test error when curve_id_1 is missing."""
        from rhinoclaw.tools.fillet_curves import fillet_curves
        
        result = json.loads(fillet_curves(None, "", "curve-2", 2.0))
        
        assert result["success"] is False
        assert "curve_id_1" in result.get("message", "").lower()
    
    def test_fillet_curves_missing_curve_2(self):
        """Test error when curve_id_2 is missing."""
        from rhinoclaw.tools.fillet_curves import fillet_curves
        
        result = json.loads(fillet_curves(None, "curve-1", "", 2.0))
        
        assert result["success"] is False
        assert "curve_id_2" in result.get("message", "").lower()
    
    def test_fillet_curves_invalid_radius(self):
        """Test error when radius is not positive."""
        from rhinoclaw.tools.fillet_curves import fillet_curves
        
        result = json.loads(fillet_curves(None, "curve-1", "curve-2", 0))
        
        assert result["success"] is False
        assert "radius" in result.get("message", "").lower()
    
    def test_fillet_curves_negative_radius(self):
        """Test error when radius is negative."""
        from rhinoclaw.tools.fillet_curves import fillet_curves
        
        result = json.loads(fillet_curves(None, "curve-1", "curve-2", -5.0))
        
        assert result["success"] is False
        assert "radius" in result.get("message", "").lower()


class TestChamferCurves:
    """Tests for chamfer_curves tool."""
    
    def test_chamfer_curves_basic(self):
        """Test basic curve chamfer."""
        with patch('rhinoclaw.tools.chamfer_curves.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "curve_id_1": "curve-1",
                "curve_id_2": "curve-2",
                "chamfer_ids": ["chamfer-line"],
                "distance_1": 3.0,
                "distance_2": 3.0,
                "joined": False
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.chamfer_curves import chamfer_curves
            
            result = json.loads(chamfer_curves(None, "curve-1", "curve-2", 3.0))
            
            assert result["success"] is True
            assert "chamfer" in result["message"].lower()
            mock_rhino.send_command.assert_called_once()
    
    def test_chamfer_curves_asymmetric(self):
        """Test chamfer with different distances."""
        with patch('rhinoclaw.tools.chamfer_curves.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "curve_id_1": "curve-1",
                "curve_id_2": "curve-2",
                "chamfer_ids": ["chamfer-line"],
                "distance_1": 2.0,
                "distance_2": 4.0,
                "joined": False
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.chamfer_curves import chamfer_curves
            
            result = json.loads(chamfer_curves(
                None, "curve-1", "curve-2", 2.0, 4.0
            ))
            
            assert result["success"] is True
            call_args = mock_rhino.send_command.call_args[0]
            assert call_args[1]["distance_1"] == 2.0
            assert call_args[1]["distance_2"] == 4.0
    
    def test_chamfer_curves_with_join(self):
        """Test chamfer with join=True."""
        with patch('rhinoclaw.tools.chamfer_curves.get_rhino_connection') as mock_conn:
            mock_rhino = MagicMock()
            mock_rhino.send_command.return_value = {
                "curve_id_1": "curve-1",
                "curve_id_2": "curve-2",
                "chamfer_ids": ["joined-curve"],
                "distance_1": 3.0,
                "distance_2": 3.0,
                "joined": True
            }
            mock_conn.return_value = mock_rhino
            
            from rhinoclaw.tools.chamfer_curves import chamfer_curves
            
            result = json.loads(chamfer_curves(
                None, "curve-1", "curve-2", 3.0, None, None, None, True
            ))
            
            assert result["success"] is True
            call_args = mock_rhino.send_command.call_args[0]
            assert call_args[1]["join"] is True
    
    def test_chamfer_curves_missing_curve_1(self):
        """Test error when curve_id_1 is missing."""
        from rhinoclaw.tools.chamfer_curves import chamfer_curves
        
        result = json.loads(chamfer_curves(None, "", "curve-2", 3.0))
        
        assert result["success"] is False
        assert "curve_id_1" in result.get("message", "").lower()
    
    def test_chamfer_curves_missing_curve_2(self):
        """Test error when curve_id_2 is missing."""
        from rhinoclaw.tools.chamfer_curves import chamfer_curves
        
        result = json.loads(chamfer_curves(None, "curve-1", "", 3.0))
        
        assert result["success"] is False
        assert "curve_id_2" in result.get("message", "").lower()
    
    def test_chamfer_curves_invalid_distance_1(self):
        """Test error when distance_1 is not positive."""
        from rhinoclaw.tools.chamfer_curves import chamfer_curves
        
        result = json.loads(chamfer_curves(None, "curve-1", "curve-2", 0))
        
        assert result["success"] is False
        assert "distance_1" in result.get("message", "").lower()
    
    def test_chamfer_curves_invalid_distance_2(self):
        """Test error when distance_2 is negative."""
        from rhinoclaw.tools.chamfer_curves import chamfer_curves
        
        result = json.loads(chamfer_curves(None, "curve-1", "curve-2", 3.0, -1.0))
        
        assert result["success"] is False
        assert "distance_2" in result.get("message", "").lower()
