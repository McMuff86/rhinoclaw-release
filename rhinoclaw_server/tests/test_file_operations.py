"""Tests for file operations (open, save, export)."""
import pytest
import json
from unittest.mock import MagicMock, patch


class TestOpenFile:
    """Tests for open_file tool."""

    def test_open_file_success(self):
        """Test successful file open."""
        from rhinoclaw.tools.open_file import open_file
        
        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "C:/test/model.3dm",
            "status": "opened"
        }
        
        with patch("rhinoclaw.tools.open_file.get_rhino_connection", return_value=mock_rhino):
            result = open_file(mock_ctx, "C:/test/model.3dm")
        
        result_data = json.loads(result)
        assert result_data["success"] is True
        assert "file_path" in result_data["data"]
        mock_rhino.send_command.assert_called_once()

    def test_open_file_empty_path(self):
        """Test open with empty path fails."""
        from rhinoclaw.tools.open_file import open_file
        
        mock_ctx = MagicMock()
        
        result = open_file(mock_ctx, "")
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "file_path is required" in result_data["message"]

    def test_open_file_wrong_extension(self):
        """Test open with non-.3dm file fails."""
        from rhinoclaw.tools.open_file import open_file
        
        mock_ctx = MagicMock()
        
        result = open_file(mock_ctx, "C:/test/model.obj")
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert ".3dm" in result_data["message"]


class TestSaveFile:
    """Tests for save_file tool."""

    def test_save_file_success(self):
        """Test successful file save."""
        from rhinoclaw.tools.save_file import save_file
        
        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "C:/test/model.3dm",
            "status": "saved",
            "verification": {"pass": True}
        }
        
        with patch("rhinoclaw.tools.save_file.get_rhino_connection", return_value=mock_rhino):
            result = save_file(mock_ctx, "C:/test/model.3dm")
        
        result_data = json.loads(result)
        assert result_data["success"] is True
        assert "file_path" in result_data["data"]

    def test_save_file_no_path(self):
        """Test save to current location."""
        from rhinoclaw.tools.save_file import save_file
        
        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "C:/existing/document.3dm",
            "status": "saved",
            "verification": {"pass": True}
        }
        
        with patch("rhinoclaw.tools.save_file.get_rhino_connection", return_value=mock_rhino):
            result = save_file(mock_ctx)
        
        result_data = json.loads(result)
        assert result_data["success"] is True
        mock_rhino.send_command.assert_called_once_with("save_file", {}, timeout=120.0)

    @pytest.mark.parametrize("path", ["", "   ", "model.obj"])
    def test_invalid_save_path_never_connects(self, path):
        from rhinoclaw.tools.save_file import save_file

        with patch("rhinoclaw.tools.save_file.get_rhino_connection") as connect:
            result = json.loads(save_file(MagicMock(), path))
        assert result["success"] is False
        connect.assert_not_called()

    @pytest.mark.parametrize("verification", [None, {}, {"pass": False}, {"pass": "true"}])
    def test_unverified_save_preserves_partial_outcome(self, verification):
        from rhinoclaw.tools.save_file import save_file

        raw = {"file_path": "C:/Villa.3dm", "status": "saved_unverified",
               "write_reported_success": True, "verification": verification}
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = raw
        with patch("rhinoclaw.tools.save_file.get_rhino_connection", return_value=mock_rhino):
            result = json.loads(save_file(MagicMock(), "C:/Villa.3dm"))
        assert result["success"] is False
        assert result["data"] == raw

    def test_unicode_and_spaces_are_passed_as_path_data(self):
        from rhinoclaw.tools.save_file import save_file

        path = "C:/Entwürfe/Villa Süd.3dm"
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "status": "saved", "file_path": path, "verification": {"pass": True}
        }
        with patch("rhinoclaw.tools.save_file.get_rhino_connection", return_value=mock_rhino):
            result = json.loads(save_file(MagicMock(), path))
        assert result["success"] is True
        mock_rhino.send_command.assert_called_once_with("save_file", {"file_path": path}, timeout=120.0)

    def test_save_file_wrong_extension(self):
        """Test save with non-.3dm path fails."""
        from rhinoclaw.tools.save_file import save_file
        
        mock_ctx = MagicMock()
        
        result = save_file(mock_ctx, "C:/test/model.obj")
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert ".3dm" in result_data["message"]


class TestExportFile:
    """Tests for export_file tool."""

    def test_export_file_success(self):
        """Test successful file export."""
        from rhinoclaw.tools.export_file import export_file
        
        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "C:/test/model.step",
            "format": "STEP",
            "object_count": 5,
            "status": "exported"
        }
        
        with patch("rhinoclaw.tools.export_file.get_rhino_connection", return_value=mock_rhino):
            result = export_file(mock_ctx, "C:/test/model.step")
        
        result_data = json.loads(result)
        assert result_data["success"] is True
        assert result_data["data"]["format"] == "STEP"

    def test_export_file_with_format_override(self):
        """Test export with explicit format."""
        from rhinoclaw.tools.export_file import export_file
        
        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "C:/test/model.stp",
            "format": "IGES",
            "object_count": 3
        }
        
        with patch("rhinoclaw.tools.export_file.get_rhino_connection", return_value=mock_rhino):
            result = export_file(mock_ctx, "C:/test/model.stp", export_format="IGES")
        
        result_data = json.loads(result)
        assert result_data["success"] is True
        # Verify format override was used
        call_args = mock_rhino.send_command.call_args
        assert call_args[0][1]["format"] == "IGES"

    def test_export_file_with_object_ids(self):
        """Test export with specific objects."""
        from rhinoclaw.tools.export_file import export_file
        
        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "file_path": "C:/test/model.obj",
            "format": "OBJ",
            "object_count": 2
        }
        
        with patch("rhinoclaw.tools.export_file.get_rhino_connection", return_value=mock_rhino):
            result = export_file(mock_ctx, "C:/test/model.obj", object_ids=["id1", "id2"])
        
        result_data = json.loads(result)
        assert result_data["success"] is True
        call_args = mock_rhino.send_command.call_args
        assert call_args[0][1]["object_ids"] == ["id1", "id2"]

    def test_export_file_empty_path(self):
        """Test export with empty path fails."""
        from rhinoclaw.tools.export_file import export_file
        
        mock_ctx = MagicMock()
        
        result = export_file(mock_ctx, "")
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "file_path is required" in result_data["message"]

    def test_export_file_unknown_format(self):
        """Test export with unknown extension fails."""
        from rhinoclaw.tools.export_file import export_file
        
        mock_ctx = MagicMock()
        
        result = export_file(mock_ctx, "C:/test/model.xyz")
        result_data = json.loads(result)
        assert result_data["success"] is False
        assert "Cannot determine format" in result_data["message"]

    def test_export_file_all_formats(self):
        """Test that all supported formats are detected from extension."""
        from rhinoclaw.tools.export_file import export_file
        
        mock_ctx = MagicMock()
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {"status": "exported"}
        
        formats = [
            ("model.step", "STEP"),
            ("model.stp", "STEP"),
            ("model.iges", "IGES"),
            ("model.igs", "IGES"),
            ("model.dwg", "DWG"),
            ("model.dxf", "DXF"),
            ("model.obj", "OBJ"),
            ("model.stl", "STL"),
            ("model.3mf", "3MF"),
            ("model.fbx", "FBX"),
            ("model.dae", "DAE"),
        ]
        
        for filename, expected_format in formats:
            with patch("rhinoclaw.tools.export_file.get_rhino_connection", return_value=mock_rhino):
                result = export_file(mock_ctx, f"C:/test/{filename}")
            
            result_data = json.loads(result)
            assert result_data["success"] is True, f"Failed for {filename}"
            call_args = mock_rhino.send_command.call_args
            assert call_args[0][1]["format"] == expected_format, f"Wrong format for {filename}"
