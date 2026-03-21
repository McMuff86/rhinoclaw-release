"""Tests for WebSocket streaming MCP tools - basic validation tests."""

import json
from unittest.mock import MagicMock

import pytest

from rhinoclaw.websocket_client import WebSocketEvent, reset_websocket_client


@pytest.fixture(autouse=True)
def reset_client():
    """Reset the WebSocket client singleton before/after each test."""
    reset_websocket_client()
    yield
    reset_websocket_client()


class TestWebSocketEventSerialization:
    """Tests for WebSocketEvent serialization."""

    def test_event_to_dict(self):
        """Test converting event to dictionary."""
        event = WebSocketEvent(
            event_type="Prompt",
            text="Pick a point",
            timestamp="2026-01-11 14:30:00.000",
            raw={"type": "Prompt", "text": "Pick a point"}
        )
        
        # Simulate what the tools do
        event_dict = {
            "type": event.event_type,
            "text": event.text,
            "timestamp": event.timestamp,
        }
        
        assert event_dict["type"] == "Prompt"
        assert event_dict["text"] == "Pick a point"
        assert event_dict["timestamp"] == "2026-01-11 14:30:00.000"

    def test_multiple_events_to_list(self):
        """Test converting multiple events to list."""
        events = [
            WebSocketEvent(
                event_type="Prompt",
                text="Pick a point",
                timestamp="2026-01-11 14:30:00.000",
                raw={}
            ),
            WebSocketEvent(
                event_type="History",
                text="Box created",
                timestamp="2026-01-11 14:30:01.000",
                raw={}
            ),
        ]
        
        event_list = [
            {
                "type": e.event_type,
                "text": e.text,
                "timestamp": e.timestamp,
            }
            for e in events
        ]
        
        assert len(event_list) == 2
        assert event_list[0]["type"] == "Prompt"
        assert event_list[1]["type"] == "History"

    def test_event_json_serializable(self):
        """Test that event dict is JSON serializable."""
        event = WebSocketEvent(
            event_type="Connected",
            text="",
            timestamp="2026-01-11 14:30:00.000",
            raw={"type": "Connected", "current_prompt": "Command:"}
        )
        
        event_dict = {
            "type": event.event_type,
            "text": event.text,
            "timestamp": event.timestamp,
        }
        
        # Should not raise
        json_str = json.dumps(event_dict)
        assert "Connected" in json_str


class TestStreamToolsImport:
    """Tests that stream tools can be imported."""

    def test_import_connect_rhino_stream(self):
        """Test connect_rhino_stream can be imported."""
        from rhinoclaw.tools.stream_commands import connect_rhino_stream
        assert callable(connect_rhino_stream)

    def test_import_disconnect_rhino_stream(self):
        """Test disconnect_rhino_stream can be imported."""
        from rhinoclaw.tools.stream_commands import disconnect_rhino_stream
        assert callable(disconnect_rhino_stream)

    def test_import_get_stream_events(self):
        """Test get_stream_events can be imported."""
        from rhinoclaw.tools.stream_commands import get_stream_events
        assert callable(get_stream_events)

    def test_import_wait_for_prompt(self):
        """Test wait_for_prompt can be imported."""
        from rhinoclaw.tools.stream_commands import wait_for_prompt
        assert callable(wait_for_prompt)

    def test_import_get_stream_status(self):
        """Test get_stream_status can be imported."""
        from rhinoclaw.tools.stream_commands import get_stream_status
        assert callable(get_stream_status)

    def test_import_clear_stream_buffer(self):
        """Test clear_stream_buffer can be imported."""
        from rhinoclaw.tools.stream_commands import clear_stream_buffer
        assert callable(clear_stream_buffer)


class TestWebSocketClientInit:
    """Tests for WebSocket client initialization."""

    def test_client_init_from_package(self):
        """Test client can be imported and initialized."""
        from rhinoclaw.websocket_client import RhinoWebSocketClient
        
        client = RhinoWebSocketClient()
        assert client.url == "ws://127.0.0.1:2000"
        assert not client.is_connected

    def test_get_client_singleton(self):
        """Test singleton client access."""
        from rhinoclaw.websocket_client import get_websocket_client
        
        client = get_websocket_client()
        assert client is not None
        assert client.url == "ws://127.0.0.1:2000"
