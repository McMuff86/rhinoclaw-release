"""
Tests for the boolean_operation tool.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestBooleanOperationValidation:
    """Tests for boolean_operation parameter validation."""

    @patch("rhinoclaw.tools.boolean_operation.get_rhino_connection")
    def test_invalid_operation_type(self, mock_get_conn):
        from rhinoclaw.tools.boolean_operation import boolean_operation
        
        ctx = MagicMock()
        result = boolean_operation(ctx, operation="invalid", object_ids=["id1", "id2"])
        parsed = json.loads(result)
        
        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]
        assert "invalid" in parsed["message"].lower()

    @patch("rhinoclaw.tools.boolean_operation.get_rhino_connection")
    def test_insufficient_objects(self, mock_get_conn):
        from rhinoclaw.tools.boolean_operation import boolean_operation
        
        ctx = MagicMock()
        result = boolean_operation(ctx, operation="union", object_ids=["id1"])
        parsed = json.loads(result)
        
        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]
        assert "2" in parsed["message"]

    @patch("rhinoclaw.tools.boolean_operation.get_rhino_connection")
    def test_empty_object_ids(self, mock_get_conn):
        from rhinoclaw.tools.boolean_operation import boolean_operation
        
        ctx = MagicMock()
        result = boolean_operation(ctx, operation="union", object_ids=[])
        parsed = json.loads(result)
        
        assert parsed["success"] is False
        assert "INVALID_PARAMS" in parsed["code"]


class TestBooleanOperationSuccess:
    """Tests for successful boolean operations."""

    @patch("rhinoclaw.tools.boolean_operation.get_rhino_connection")
    def test_union_success(self, mock_get_conn):
        from rhinoclaw.tools.boolean_operation import boolean_operation
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "operation": "UNION",
            "input_count": 2,
            "result_ids": ["new-guid-123"],
            "deleted_input": True
        }
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = boolean_operation(ctx, operation="union", object_ids=["id1", "id2"])
        parsed = json.loads(result)
        
        assert parsed["success"] is True
        assert "UNION" in parsed["message"]
        assert parsed["data"]["result_ids"] == ["new-guid-123"]
        
        mock_rhino.send_command.assert_called_once_with("boolean_operation", {
            "operation": "UNION",
            "object_ids": ["id1", "id2"],
            "delete_input": True
        })

    @patch("rhinoclaw.tools.boolean_operation.get_rhino_connection")
    def test_difference_success(self, mock_get_conn):
        from rhinoclaw.tools.boolean_operation import boolean_operation
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "operation": "DIFFERENCE",
            "input_count": 2,
            "result_ids": ["new-guid-456"],
            "deleted_input": True
        }
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = boolean_operation(ctx, operation="difference", object_ids=["base", "cutter"])
        parsed = json.loads(result)
        
        assert parsed["success"] is True
        assert "DIFFERENCE" in parsed["message"]

    @patch("rhinoclaw.tools.boolean_operation.get_rhino_connection")
    def test_intersection_success(self, mock_get_conn):
        from rhinoclaw.tools.boolean_operation import boolean_operation
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "operation": "INTERSECTION",
            "input_count": 2,
            "result_ids": ["new-guid-789"],
            "deleted_input": False
        }
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = boolean_operation(
            ctx, 
            operation="INTERSECTION", 
            object_ids=["id1", "id2"],
            delete_input=False
        )
        parsed = json.loads(result)
        
        assert parsed["success"] is True
        assert parsed["data"]["result_ids"] is not None  # New structure includes result_ids

    @patch("rhinoclaw.tools.boolean_operation.get_rhino_connection")
    def test_case_insensitive_operation(self, mock_get_conn):
        from rhinoclaw.tools.boolean_operation import boolean_operation
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "operation": "UNION",
            "input_count": 2,
            "result_ids": ["new-id"],
            "deleted_input": True
        }
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        
        for op in ["union", "UNION", "Union", "uNiOn"]:
            result = boolean_operation(ctx, operation=op, object_ids=["a", "b"])
            parsed = json.loads(result)
            assert parsed["success"] is True


class TestBooleanOperationErrors:
    """Tests for boolean operation error handling."""

    @patch("rhinoclaw.tools.boolean_operation.get_rhino_connection")
    def test_rhino_error_handling(self, mock_get_conn):
        from rhinoclaw.tools.boolean_operation import boolean_operation
        
        mock_rhino = MagicMock()
        mock_rhino.send_command.side_effect = Exception("Objects are disjoint")
        mock_get_conn.return_value = mock_rhino
        
        ctx = MagicMock()
        result = boolean_operation(ctx, operation="union", object_ids=["id1", "id2"])
        parsed = json.loads(result)
        
        assert parsed["success"] is False
        assert "RHINO_ERROR" in parsed["code"]
        assert "disjoint" in parsed["message"]

    @patch("rhinoclaw.tools.boolean_operation.get_rhino_connection")
    def test_connection_error_handling(self, mock_get_conn):
        from rhinoclaw.tools.boolean_operation import boolean_operation
        
        mock_get_conn.side_effect = Exception("Connection refused")
        
        ctx = MagicMock()
        result = boolean_operation(ctx, operation="union", object_ids=["id1", "id2"])
        parsed = json.loads(result)
        
        assert parsed["success"] is False
        assert "refused" in parsed["message"].lower()
