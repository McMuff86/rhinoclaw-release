"""Tests for the batch_operations MCP tool."""
import json
from unittest.mock import MagicMock, patch


class TestBatchValidation:
    def test_empty_steps_rejected(self):
        from rhinoclaw.tools.batch_operations import batch_operations
        ctx = MagicMock()
        result = batch_operations(ctx, steps=[])
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"

    def test_step_without_tool_rejected(self):
        from rhinoclaw.tools.batch_operations import batch_operations
        ctx = MagicMock()
        result = batch_operations(ctx, steps=[{"args": {}}])
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["code"] == "INVALID_PARAMS"


class TestBatchHappyPath:
    @patch("rhinoclaw.tools.batch_operations.get_rhino_connection")
    def test_all_steps_succeed(self, mock_get_conn):
        from rhinoclaw.tools.batch_operations import batch_operations
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "success": True,
            "policy": "rollback",
            "counts": {"total": 2, "completed": 2, "failed": 0, "skipped": 0},
            "rolled_back": False,
            "batch_label": "test",
            "results": [
                {"step": 0, "tool": "ping", "success": True, "result": {"pong": True}},
                {"step": 1, "tool": "ping", "success": True, "result": {"pong": True}},
            ],
            "message": "Batch OK — 2/2 step(s) completed.",
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = batch_operations(ctx, steps=[
            {"tool": "ping", "args": {}},
            {"tool": "ping", "args": {}},
        ], name="test")
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "2/2" in parsed["message"]
        # Verify the wire payload included the name
        mock_rhino.send_command.assert_called_once()
        sent = mock_rhino.send_command.call_args[0][1]
        assert sent["name"] == "test"
        assert sent["on_error"] == "rollback"
        assert len(sent["steps"]) == 2


class TestBatchFailureWithRollback:
    @patch("rhinoclaw.tools.batch_operations.get_rhino_connection")
    def test_rollback_surfaces_as_failure(self, mock_get_conn):
        """Plugin reports success=false + rolled_back=true; tool wraps it as
        a structured BATCH_FAILED error."""
        from rhinoclaw.tools.batch_operations import batch_operations
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "success": False,
            "policy": "rollback",
            "counts": {"total": 3, "completed": 2, "failed": 1, "skipped": 0},
            "rolled_back": True,
            "failed_step": 2,
            "failed_tool": "modify_object",
            "error": "Object not found",
            "results": [
                {"step": 0, "tool": "create_object", "success": True, "result": {"id": "g1"}},
                {"step": 1, "tool": "create_object", "success": True, "result": {"id": "g2"}},
                {"step": 2, "tool": "modify_object", "success": False, "error": "Object not found"},
            ],
            "message": "Step 2 (modify_object) failed: Object not found. "
                       "Rolled back 2 previously-completed step(s).",
            "batch_label": "test",
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = batch_operations(ctx, steps=[
            {"tool": "create_object", "args": {"type": "BOX"}},
            {"tool": "create_object", "args": {"type": "BOX"}},
            {"tool": "modify_object", "args": {"id": "missing"}},
        ])
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["code"] == "BATCH_FAILED"
        assert parsed["data"]["rolled_back"] is True
        assert parsed["data"]["failed_step"] == 2
        assert "Rolled back" in parsed["message"]


class TestBatchBestEffort:
    @patch("rhinoclaw.tools.batch_operations.get_rhino_connection")
    def test_best_effort_keeps_success_flag(self, mock_get_conn):
        """best_effort policy: even with a failed step the outer success flag
        stays true so the caller can introspect partial results."""
        from rhinoclaw.tools.batch_operations import batch_operations
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "success": True,  # plugin already applies best_effort flag
            "policy": "best_effort",
            "counts": {"total": 3, "completed": 2, "failed": 1, "skipped": 0},
            "rolled_back": False,
            "failed_step": 1,
            "failed_tool": "modify_object",
            "error": "Bad params",
            "results": [
                {"step": 0, "tool": "ping", "success": True, "result": {"pong": True}},
                {"step": 1, "tool": "modify_object", "success": False, "error": "Bad params"},
                {"step": 2, "tool": "ping", "success": True, "result": {"pong": True}},
            ],
            "message": "Step 1 (modify_object) failed: Bad params. "
                       "Continued past failure; 2/3 step(s) completed.",
            "batch_label": "best",
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        result = batch_operations(ctx, steps=[
            {"tool": "ping", "args": {}},
            {"tool": "modify_object", "args": {"id": "missing"}},
            {"tool": "ping", "args": {}},
        ], on_error="best_effort")
        parsed = json.loads(result)

        # Outer success stays true (best_effort), but per-step failure visible
        # in data.results.
        assert parsed["success"] is True
        assert parsed["data"]["counts"]["failed"] == 1
        assert parsed["data"]["counts"]["completed"] == 2

        sent = mock_rhino.send_command.call_args[0][1]
        assert sent["on_error"] == "best_effort"


class TestBatchTransport:
    @patch("rhinoclaw.tools.batch_operations.get_rhino_connection")
    def test_omits_name_when_not_given(self, mock_get_conn):
        from rhinoclaw.tools.batch_operations import batch_operations
        mock_rhino = MagicMock()
        mock_rhino.send_command.return_value = {
            "success": True, "policy": "rollback",
            "counts": {"total": 1, "completed": 1, "failed": 0, "skipped": 0},
            "rolled_back": False, "results": [], "message": "ok", "batch_label": "x",
        }
        mock_get_conn.return_value = mock_rhino

        ctx = MagicMock()
        batch_operations(ctx, steps=[{"tool": "ping", "args": {}}])

        sent = mock_rhino.send_command.call_args[0][1]
        assert "name" not in sent

    @patch("rhinoclaw.tools.batch_operations.get_rhino_connection")
    def test_connection_error_propagates(self, mock_get_conn):
        from rhinoclaw.tools.batch_operations import batch_operations
        mock_get_conn.side_effect = Exception("Connection refused")

        ctx = MagicMock()
        result = batch_operations(ctx, steps=[{"tool": "ping", "args": {}}])
        parsed = json.loads(result)
        assert parsed["success"] is False
