"""Tests for surface operations (loft, extrude, revolve)."""
import pytest
import json
from unittest.mock import MagicMock, patch


class TestLoftCurves:
    """Tests for loft_curves tool."""

    def test_loft_curves_success(self):
        """Test successful loft between curves."""
        from rhinoclaw.tools.loft_curves import loft_curves
        
        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "source_curve_ids": ["id1", "id2", "id3"],
            "loft_ids": ["loft-id-1"],
            "loft_type": "normal",
            "closed": False
        }
        
        with patch("rhinoclaw.tools.loft_curves.get_rhino_connection", return_value=mock_rhino):
            result = loft_curves(mock_ctx, ["id1", "id2", "id3"])
        
        result_data = json.loads(result)
        assert result_data["success"] is True
        assert "loft_ids" in result_data["data"]
        mock_rhino.send_command.assert_called_once()

    def test_loft_curves_with_options(self):
        """Test loft with closed and loft_type options."""
        from rhinoclaw.tools.loft_curves import loft_curves
        
        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "loft_ids": ["loft-id-1"],
            "closed": True,
            "loft_type": "tight"
        }
        
        with patch("rhinoclaw.tools.loft_curves.get_rhino_connection", return_value=mock_rhino):
            result = loft_curves(mock_ctx, ["id1", "id2", "id3"], closed=True, loft_type="tight")
        
        result_data = json.loads(result)
        assert result_data["success"] is True
        # Verify correct parameters sent
        call_args = mock_rhino.send_command.call_args
        assert call_args[0][1]["closed"] is True
        assert call_args[0][1]["loft_type"] == "TIGHT"

    def test_loft_curves_insufficient_curves(self):
        """Test loft with less than 2 curves fails."""
        from rhinoclaw.tools.loft_curves import loft_curves
        
        mock_ctx = MagicMock()
        
        result = loft_curves(mock_ctx, ["id1"])
        result_data = json.loads(result)
        
        assert result_data["success"] is False
        assert "at least 2" in result_data["message"].lower()

    def test_loft_curves_empty_list(self):
        """Test loft with empty list fails."""
        from rhinoclaw.tools.loft_curves import loft_curves
        
        mock_ctx = MagicMock()
        
        result = loft_curves(mock_ctx, [])
        result_data = json.loads(result)
        
        assert result_data["success"] is False
        assert result_data["code"] == "INVALID_PARAMS"

    def test_loft_curves_invalid_loft_type(self):
        """Test loft with invalid loft_type fails."""
        from rhinoclaw.tools.loft_curves import loft_curves
        
        mock_ctx = MagicMock()
        
        result = loft_curves(mock_ctx, ["id1", "id2"], loft_type="invalid")
        result_data = json.loads(result)
        
        assert result_data["success"] is False
        assert "invalid" in result_data["message"].lower()

    def test_loft_curves_all_loft_types(self):
        """Test all valid loft types."""
        from rhinoclaw.tools.loft_curves import loft_curves
        
        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"loft_ids": ["id"]}
        
        for loft_type in ["normal", "loose", "tight", "straight"]:
            with patch("rhinoclaw.tools.loft_curves.get_rhino_connection", return_value=mock_rhino):
                result = loft_curves(mock_ctx, ["id1", "id2"], loft_type=loft_type)
            
            result_data = json.loads(result)
            assert result_data["success"] is True, f"Failed for loft_type: {loft_type}"


class TestExtrudeCurve:
    """Tests for extrude_curve tool."""

    def test_extrude_curve_success(self):
        """Test successful curve extrusion."""
        from rhinoclaw.tools.extrude_curve import extrude_curve
        
        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "source_curve_id": "curve-id",
            "extrusion_id": "extrusion-id-1",
            "direction": [0, 0, 1],
            "distance": 10.0
        }
        
        with patch("rhinoclaw.tools.extrude_curve.get_rhino_connection", return_value=mock_rhino):
            result = extrude_curve(mock_ctx, "curve-id", [0, 0, 1], distance=10.0)
        
        result_data = json.loads(result)
        assert result_data["success"] is True
        assert "extrusion_id" in result_data["data"]

    def test_extrude_curve_with_cap(self):
        """Test extrusion with cap option."""
        from rhinoclaw.tools.extrude_curve import extrude_curve
        
        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"extrusion_id": "id"}
        
        with patch("rhinoclaw.tools.extrude_curve.get_rhino_connection", return_value=mock_rhino):
            result = extrude_curve(mock_ctx, "curve-id", [0, 0, 1], cap=False)
        
        result_data = json.loads(result)
        assert result_data["success"] is True
        call_args = mock_rhino.send_command.call_args
        assert call_args[0][1]["cap"] is False

    def test_extrude_curve_missing_curve_id(self):
        """Test extrusion without curve_id fails."""
        from rhinoclaw.tools.extrude_curve import extrude_curve
        
        mock_ctx = MagicMock()
        
        result = extrude_curve(mock_ctx, "", [0, 0, 1])
        result_data = json.loads(result)
        
        assert result_data["success"] is False
        assert "curve_id" in result_data["message"].lower()

    def test_extrude_curve_invalid_direction(self):
        """Test extrusion with invalid direction fails."""
        from rhinoclaw.tools.extrude_curve import extrude_curve
        
        mock_ctx = MagicMock()
        
        # Wrong number of components
        result = extrude_curve(mock_ctx, "curve-id", [0, 0])
        result_data = json.loads(result)
        assert result_data["success"] is False
        
        # Empty direction
        result = extrude_curve(mock_ctx, "curve-id", [])
        result_data = json.loads(result)
        assert result_data["success"] is False

    def test_extrude_curve_zero_direction(self):
        """Test extrusion with zero vector fails."""
        from rhinoclaw.tools.extrude_curve import extrude_curve
        
        mock_ctx = MagicMock()
        
        result = extrude_curve(mock_ctx, "curve-id", [0, 0, 0])
        result_data = json.loads(result)
        
        assert result_data["success"] is False
        assert "zero" in result_data["message"].lower()

    def test_extrude_curve_negative_distance(self):
        """Test extrusion with negative distance fails."""
        from rhinoclaw.tools.extrude_curve import extrude_curve
        
        mock_ctx = MagicMock()
        
        result = extrude_curve(mock_ctx, "curve-id", [0, 0, 1], distance=-5)
        result_data = json.loads(result)
        
        assert result_data["success"] is False
        assert "positive" in result_data["message"].lower()


class TestRevolveCurve:
    """Tests for revolve_curve tool."""

    def test_revolve_curve_success(self):
        """Test successful curve revolution."""
        from rhinoclaw.tools.revolve_curve import revolve_curve
        
        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "source_curve_id": "curve-id",
            "revolve_id": "revolve-id-1",
            "angle": 360.0
        }
        
        with patch("rhinoclaw.tools.revolve_curve.get_rhino_connection", return_value=mock_rhino):
            result = revolve_curve(mock_ctx, "curve-id", [0, 0, 0], [0, 0, 1])
        
        result_data = json.loads(result)
        assert result_data["success"] is True
        assert "revolve_id" in result_data["data"]

    def test_revolve_curve_partial_angle(self):
        """Test revolution with partial angle."""
        from rhinoclaw.tools.revolve_curve import revolve_curve
        
        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"revolve_id": "id"}
        
        with patch("rhinoclaw.tools.revolve_curve.get_rhino_connection", return_value=mock_rhino):
            result = revolve_curve(mock_ctx, "curve-id", [0, 0, 0], [0, 0, 1], angle=180.0)
        
        result_data = json.loads(result)
        assert result_data["success"] is True
        call_args = mock_rhino.send_command.call_args
        assert call_args[0][1]["angle"] == 180.0

    def test_revolve_curve_missing_curve_id(self):
        """Test revolution without curve_id fails."""
        from rhinoclaw.tools.revolve_curve import revolve_curve
        
        mock_ctx = MagicMock()
        
        result = revolve_curve(mock_ctx, "", [0, 0, 0], [0, 0, 1])
        result_data = json.loads(result)
        
        assert result_data["success"] is False
        assert "curve_id" in result_data["message"].lower()

    def test_revolve_curve_invalid_axis_start(self):
        """Test revolution with invalid axis_start fails."""
        from rhinoclaw.tools.revolve_curve import revolve_curve
        
        mock_ctx = MagicMock()
        
        result = revolve_curve(mock_ctx, "curve-id", [0, 0], [0, 0, 1])
        result_data = json.loads(result)
        
        assert result_data["success"] is False
        assert "axis_start" in result_data["message"].lower()

    def test_revolve_curve_invalid_axis_end(self):
        """Test revolution with invalid axis_end fails."""
        from rhinoclaw.tools.revolve_curve import revolve_curve
        
        mock_ctx = MagicMock()
        
        result = revolve_curve(mock_ctx, "curve-id", [0, 0, 0], [0, 0])
        result_data = json.loads(result)
        
        assert result_data["success"] is False
        assert "axis_end" in result_data["message"].lower()

    def test_revolve_curve_same_axis_points(self):
        """Test revolution with same axis start and end fails."""
        from rhinoclaw.tools.revolve_curve import revolve_curve
        
        mock_ctx = MagicMock()
        
        result = revolve_curve(mock_ctx, "curve-id", [0, 0, 0], [0, 0, 0])
        result_data = json.loads(result)
        
        assert result_data["success"] is False
        assert "same point" in result_data["message"].lower()

    def test_revolve_curve_zero_angle(self):
        """Test revolution with zero angle fails."""
        from rhinoclaw.tools.revolve_curve import revolve_curve
        
        mock_ctx = MagicMock()
        
        result = revolve_curve(mock_ctx, "curve-id", [0, 0, 0], [0, 0, 1], angle=0)
        result_data = json.loads(result)
        
        assert result_data["success"] is False
        assert "zero" in result_data["message"].lower()


class TestSurfaceOperationsIntegration:
    """Integration tests for surface operations (require Rhino connection)."""

    @pytest.mark.skip(reason="Requires live Rhino connection")
    def test_loft_integration(self):
        """Integration test for loft with real Rhino."""
        pass

    @pytest.mark.skip(reason="Requires live Rhino connection")
    def test_extrude_integration(self):
        """Integration test for extrude with real Rhino."""
        pass

    @pytest.mark.skip(reason="Requires live Rhino connection")
    def test_revolve_integration(self):
        """Integration test for revolve with real Rhino."""
        pass
