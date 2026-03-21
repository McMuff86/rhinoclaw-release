"""Tests for dimension operation tools."""
import pytest
import json


class TestCreateLinearDimension:
    """Tests for create_linear_dimension tool."""
    
    def test_create_linear_dimension_invalid_start_point(self):
        """Test linear dimension with invalid start_point."""
        from rhinoclaw.tools.create_linear_dimension import create_linear_dimension
        
        result = create_linear_dimension(
            ctx=None,
            start_point=[0, 0],  # Missing Z
            end_point=[10, 0, 0],
            text_point=[5, 2, 0]
        )
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "start_point" in result_data["message"]
        assert "INVALID_PARAMS" in result_data["code"]
    
    def test_create_linear_dimension_invalid_end_point(self):
        """Test linear dimension with invalid end_point."""
        from rhinoclaw.tools.create_linear_dimension import create_linear_dimension
        
        result = create_linear_dimension(
            ctx=None,
            start_point=[0, 0, 0],
            end_point=None,  # Missing
            text_point=[5, 2, 0]
        )
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "end_point" in result_data["message"]
        assert "INVALID_PARAMS" in result_data["code"]
    
    def test_create_linear_dimension_invalid_text_point(self):
        """Test linear dimension with invalid text_point."""
        from rhinoclaw.tools.create_linear_dimension import create_linear_dimension
        
        result = create_linear_dimension(
            ctx=None,
            start_point=[0, 0, 0],
            end_point=[10, 0, 0],
            text_point=[]  # Empty
        )
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "text_point" in result_data["message"]
        assert "INVALID_PARAMS" in result_data["code"]


class TestCreateAngularDimension:
    """Tests for create_angular_dimension tool."""
    
    def test_create_angular_dimension_invalid_vertex(self):
        """Test angular dimension with invalid vertex."""
        from rhinoclaw.tools.create_angular_dimension import create_angular_dimension
        
        result = create_angular_dimension(
            ctx=None,
            vertex=None,
            start_point=[10, 0, 0],
            end_point=[0, 10, 0],
            text_point=[5, 5, 0]
        )
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "vertex" in result_data["message"]
        assert "INVALID_PARAMS" in result_data["code"]
    
    def test_create_angular_dimension_invalid_start_point(self):
        """Test angular dimension with invalid start_point."""
        from rhinoclaw.tools.create_angular_dimension import create_angular_dimension
        
        result = create_angular_dimension(
            ctx=None,
            vertex=[0, 0, 0],
            start_point=[10, 0],  # Missing Z
            end_point=[0, 10, 0],
            text_point=[5, 5, 0]
        )
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "start_point" in result_data["message"]
        assert "INVALID_PARAMS" in result_data["code"]
    
    def test_create_angular_dimension_invalid_end_point(self):
        """Test angular dimension with invalid end_point."""
        from rhinoclaw.tools.create_angular_dimension import create_angular_dimension
        
        result = create_angular_dimension(
            ctx=None,
            vertex=[0, 0, 0],
            start_point=[10, 0, 0],
            end_point=[],  # Empty
            text_point=[5, 5, 0]
        )
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "end_point" in result_data["message"]
        assert "INVALID_PARAMS" in result_data["code"]
    
    def test_create_angular_dimension_invalid_text_point(self):
        """Test angular dimension with invalid text_point."""
        from rhinoclaw.tools.create_angular_dimension import create_angular_dimension
        
        result = create_angular_dimension(
            ctx=None,
            vertex=[0, 0, 0],
            start_point=[10, 0, 0],
            end_point=[0, 10, 0],
            text_point=None
        )
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "text_point" in result_data["message"]
        assert "INVALID_PARAMS" in result_data["code"]


class TestCreateRadialDimension:
    """Tests for create_radial_dimension tool."""
    
    def test_create_radial_dimension_invalid_center(self):
        """Test radial dimension with invalid center."""
        from rhinoclaw.tools.create_radial_dimension import create_radial_dimension
        
        result = create_radial_dimension(
            ctx=None,
            center=[0, 0],  # Missing Z
            radius_point=[10, 0, 0]
        )
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "center" in result_data["message"]
        assert "INVALID_PARAMS" in result_data["code"]
    
    def test_create_radial_dimension_invalid_radius_point(self):
        """Test radial dimension with invalid radius_point."""
        from rhinoclaw.tools.create_radial_dimension import create_radial_dimension
        
        result = create_radial_dimension(
            ctx=None,
            center=[0, 0, 0],
            radius_point=None
        )
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "radius_point" in result_data["message"]
        assert "INVALID_PARAMS" in result_data["code"]
