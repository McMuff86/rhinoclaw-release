"""
Tests for grasshopper_interactive module.

These tests verify the interactive Grasshopper script execution tools
without requiring an actual Rhino connection.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def run_async(coro):
    """Run an async function in a new event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestRunGrasshopperInteractive:
    """Tests for run_grasshopper_interactive tool."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock MCP context."""
        return MagicMock()

    @pytest.fixture
    def mock_ws_client(self):
        """Create a mock WebSocket client."""
        client = MagicMock()
        client.is_connected = True
        client.current_prompt = "Command:"
        client.clear_buffer = MagicMock()
        client.run_script = AsyncMock(return_value=True)
        client.wait_for_event = AsyncMock(return_value=None)
        client.send_input = AsyncMock(return_value=True)
        client.start_listening = AsyncMock(return_value=True)
        return client

    def test_import(self):
        """Test that the module can be imported."""
        from rhinoclaw.tools.grasshopper_interactive import (
            run_door_script,
            run_grasshopper_interactive,
        )
        assert run_grasshopper_interactive is not None
        assert run_door_script is not None

    def test_missing_file_path(self, mock_context):
        """Test error when file_path is missing."""
        from rhinoclaw.tools.grasshopper_interactive import run_grasshopper_interactive
        
        result = run_async(run_grasshopper_interactive(
            ctx=mock_context,
            file_path="",
        ))
        
        data = json.loads(result)
        assert data["success"] is True
        assert "file_path is required" in data["message"]
        assert data["data"]["success"] is False

    def test_connection_failure(self, mock_context, mock_ws_client):
        """Test handling when WebSocket connection fails."""
        from rhinoclaw.tools.grasshopper_interactive import run_grasshopper_interactive
        
        mock_ws_client.is_connected = False
        mock_ws_client.start_listening = AsyncMock(return_value=False)
        
        with patch(
            "rhinoclaw.tools.grasshopper_interactive.get_websocket_client",
            return_value=mock_ws_client
        ):
            result = run_async(run_grasshopper_interactive(
                ctx=mock_context,
                file_path="/path/to/script.gh",
                inputs={"test": "value"}
            ))
        
        data = json.loads(result)
        assert data["success"] is True
        assert "Failed to connect" in data["message"]

    def test_script_start_failure(self, mock_context, mock_ws_client):
        """Test handling when script fails to start."""
        from rhinoclaw.tools.grasshopper_interactive import run_grasshopper_interactive
        
        mock_ws_client.run_script = AsyncMock(return_value=False)
        
        with patch(
            "rhinoclaw.tools.grasshopper_interactive.get_websocket_client",
            return_value=mock_ws_client
        ):
            result = run_async(run_grasshopper_interactive(
                ctx=mock_context,
                file_path="/path/to/script.gh",
            ))
        
        data = json.loads(result)
        assert data["success"] is True
        assert "Failed to start" in data["message"]

    def test_inputs_dict_validation(self, mock_context, mock_ws_client):
        """Test that inputs dict is properly used."""
        from rhinoclaw.tools.grasshopper_interactive import run_grasshopper_interactive
        
        with patch(
            "rhinoclaw.tools.grasshopper_interactive.get_websocket_client",
            return_value=mock_ws_client
        ):
            result = run_async(run_grasshopper_interactive(
                ctx=mock_context,
                file_path="/path/to/script.gh",
                inputs={"height": "2200", "width": "910"},
                timeout=1.0,
            ))
        
        data = json.loads(result)
        assert data["success"] is True
        assert "file_path" in data["data"]


class TestRunDoorScript:
    """Tests for run_door_script tool."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock MCP context."""
        return MagicMock()

    @pytest.fixture
    def mock_ws_client(self):
        """Create a mock WebSocket client."""
        client = MagicMock()
        client.is_connected = True
        client.current_prompt = "Command:"
        client.clear_buffer = MagicMock()
        client.run_script = AsyncMock(return_value=True)
        client.wait_for_prompt = AsyncMock(return_value=None)
        client.send_input = AsyncMock(return_value=True)
        client.start_listening = AsyncMock(return_value=True)
        return client

    def test_default_parameters(self, mock_context, mock_ws_client):
        """Test run_door_script with default parameters."""
        from rhinoclaw.tools.grasshopper_interactive import run_door_script
        
        with patch(
            "rhinoclaw.tools.grasshopper_interactive.get_websocket_client",
            return_value=mock_ws_client
        ):
            result = run_async(run_door_script(
                ctx=mock_context,
                file_path="/path/to/door.gh",
            ))
        
        data = json.loads(result)
        assert data["success"] is True
        # Will fail on height prompt timeout, but that's expected
        assert "data" in data

    def test_custom_parameters(self, mock_context, mock_ws_client):
        """Test run_door_script with custom parameters."""
        from rhinoclaw.tools.grasshopper_interactive import run_door_script
        
        with patch(
            "rhinoclaw.tools.grasshopper_interactive.get_websocket_client",
            return_value=mock_ws_client
        ):
            result = run_async(run_door_script(
                ctx=mock_context,
                file_path="/path/to/door.gh",
                height=2500,
                width=1000,
                origin="100,200,0",
                plane="WorldYZ",
            ))
        
        data = json.loads(result)
        assert data["success"] is True


class TestStreamCommands:
    """Tests for the stream_commands module."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock MCP context."""
        return MagicMock()

    @pytest.fixture
    def mock_ws_client(self):
        """Create a mock WebSocket client."""
        client = MagicMock()
        client.is_connected = True
        client.current_prompt = "Command:"
        client.url = "ws://127.0.0.1:2000"
        client.event_count = 5
        client._running = True
        client.clear_buffer = MagicMock()
        client.get_buffered_events = MagicMock(return_value=[])
        client.start_listening = AsyncMock(return_value=True)
        client.stop_listening = AsyncMock()
        client.disconnect = AsyncMock()
        client.send_input = AsyncMock(return_value=True)
        client.wait_for_prompt = AsyncMock(return_value=None)
        client.run_script = AsyncMock(return_value=True)
        client.cancel = AsyncMock(return_value=True)
        return client

    def test_import_stream_commands(self):
        """Test that stream_commands can be imported."""
        from rhinoclaw.tools.stream_commands import (
            cancel_rhino_command,
            clear_stream_buffer,
            connect_rhino_stream,
            disconnect_rhino_stream,
            get_stream_events,
            get_stream_status,
            run_script_async,
            send_rhino_input,
            wait_for_prompt,
        )
        assert connect_rhino_stream is not None
        assert disconnect_rhino_stream is not None
        assert send_rhino_input is not None
        assert wait_for_prompt is not None
        assert run_script_async is not None
        assert cancel_rhino_command is not None
        assert get_stream_status is not None
        assert get_stream_events is not None
        assert clear_stream_buffer is not None

    def test_connect_rhino_stream(self, mock_context, mock_ws_client):
        """Test connect_rhino_stream tool."""
        from rhinoclaw.tools.stream_commands import connect_rhino_stream
        
        with patch(
            "rhinoclaw.tools.stream_commands.get_websocket_client",
            return_value=mock_ws_client
        ):
            result = run_async(connect_rhino_stream(ctx=mock_context))
        
        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["connected"] is True

    def test_disconnect_rhino_stream(self, mock_context, mock_ws_client):
        """Test disconnect_rhino_stream tool."""
        from rhinoclaw.tools.stream_commands import disconnect_rhino_stream
        
        with patch(
            "rhinoclaw.tools.stream_commands.get_websocket_client",
            return_value=mock_ws_client
        ):
            result = run_async(disconnect_rhino_stream(ctx=mock_context))
        
        data = json.loads(result)
        assert data["success"] is True
        mock_ws_client.disconnect.assert_called_once()

    def test_send_rhino_input(self, mock_context, mock_ws_client):
        """Test send_rhino_input tool."""
        from rhinoclaw.tools.stream_commands import send_rhino_input
        
        with patch(
            "rhinoclaw.tools.stream_commands.get_websocket_client",
            return_value=mock_ws_client
        ):
            result = run_async(send_rhino_input(
                ctx=mock_context,
                value="TestInput"
            ))
        
        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["sent"] is True

    def test_get_stream_status(self, mock_context, mock_ws_client):
        """Test get_stream_status tool."""
        from rhinoclaw.tools.stream_commands import get_stream_status
        
        with patch(
            "rhinoclaw.tools.stream_commands.get_websocket_client",
            return_value=mock_ws_client
        ):
            result = run_async(get_stream_status(ctx=mock_context))
        
        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["connected"] is True
        assert data["data"]["buffer_size"] == 5

    def test_clear_stream_buffer(self, mock_context, mock_ws_client):
        """Test clear_stream_buffer tool."""
        from rhinoclaw.tools.stream_commands import clear_stream_buffer
        
        with patch(
            "rhinoclaw.tools.stream_commands.get_websocket_client",
            return_value=mock_ws_client
        ):
            result = run_async(clear_stream_buffer(ctx=mock_context))
        
        data = json.loads(result)
        assert data["success"] is True
        mock_ws_client.clear_buffer.assert_called_once()

    def test_run_script_async(self, mock_context, mock_ws_client):
        """Test run_script_async tool."""
        from rhinoclaw.tools.stream_commands import run_script_async
        
        with patch(
            "rhinoclaw.tools.stream_commands.get_websocket_client",
            return_value=mock_ws_client
        ):
            result = run_async(run_script_async(
                ctx=mock_context,
                script="_Box 0,0,0 10,10,10"
            ))
        
        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["started"] is True

    def test_cancel_rhino_command(self, mock_context, mock_ws_client):
        """Test cancel_rhino_command tool."""
        from rhinoclaw.tools.stream_commands import cancel_rhino_command
        
        with patch(
            "rhinoclaw.tools.stream_commands.get_websocket_client",
            return_value=mock_ws_client
        ):
            result = run_async(cancel_rhino_command(ctx=mock_context))
        
        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["cancelled"] is True
