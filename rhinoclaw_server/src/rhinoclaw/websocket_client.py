"""
WebSocket client for real-time Rhino command line event streaming.

This module provides a WebSocket client that connects to the Rhino plugin's
WebSocket server (port 2000) to receive real-time push notifications about
command line events, prompts, and history changes.

The client now supports both:
- Event monitoring (receiving Prompt/History events)
- Command execution (send_input, run_script, cancel)

Usage:
    from rhinoclaw.websocket_client import get_websocket_client

    # Get the singleton client
    client = get_websocket_client()
    
    # Connect and start listening
    await client.connect()
    
    # Send input to Rhino
    await client.send_input("WorldXY")
    
    # Run a script
    await client.run_script('_-GrasshopperPlayer "path/to/file.gh"')
    
    # Wait for a specific prompt
    prompt = await client.wait_for_prompt("GetPlane", timeout=5.0)
    
    # Disconnect when done
    await client.disconnect()
"""

import asyncio
import json
import logging
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Deque, Dict, List, Optional

logger = logging.getLogger("RhinoWebSocketClient")


@dataclass
class WebSocketEvent:
    """Represents a single event received from the WebSocket server."""
    event_type: str
    text: str
    timestamp: str
    raw: Dict

    @classmethod
    def from_json(cls, data: Dict) -> "WebSocketEvent":
        """Create a WebSocketEvent from a JSON dictionary."""
        return cls(
            event_type=data.get("type", "Unknown"),
            text=data.get("text", data.get("script", "")),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            raw=data
        )


class RhinoWebSocketClient:
    """
    WebSocket client for receiving real-time command line events from Rhino.
    
    This client connects to the C# WebSocket server running on port 2000 and
    receives push notifications whenever the command line state changes.
    
    Features:
    - Automatic reconnection with exponential backoff
    - Event buffering with configurable max size
    - Callback support for event handlers
    - Command execution (send_input, run_script, cancel)
    - Async and sync access patterns
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 2000,
        max_buffer_size: int = 500,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 30.0,
    ):
        """
        Initialize the WebSocket client.
        
        Args:
            host: WebSocket server host
            port: WebSocket server port
            max_buffer_size: Maximum number of events to buffer
            reconnect_delay: Initial delay before reconnection attempts
            max_reconnect_delay: Maximum delay between reconnection attempts
        """
        self.host = host
        self.port = port
        self.url = f"ws://{host}:{port}"
        self.max_buffer_size = max_buffer_size
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay

        # Connection state
        self._websocket = None
        self._connected = False
        self._running = False
        self._listen_task: Optional[asyncio.Task] = None

        # Event buffer (thread-safe deque)
        self._event_buffer: Deque[WebSocketEvent] = deque(maxlen=max_buffer_size)
        self._buffer_lock = threading.Lock()

        # Callbacks
        self._callbacks: List[Callable[[WebSocketEvent], None]] = []
        self._callbacks_lock = threading.Lock()

        # Current prompt (for quick access)
        self._current_prompt: str = ""
        self._prompt_lock = threading.Lock()

        # Pending responses for request-response pattern
        self._pending_requests: Dict[str, asyncio.Event] = {}
        self._pending_responses: Dict[str, Dict] = {}
        self._requests_lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        """Check if the WebSocket is currently connected."""
        return self._connected and self._websocket is not None

    @property
    def current_prompt(self) -> str:
        """Get the current Rhino command prompt."""
        with self._prompt_lock:
            return self._current_prompt

    @property
    def event_count(self) -> int:
        """Get the number of buffered events."""
        with self._buffer_lock:
            return len(self._event_buffer)

    async def connect(self) -> bool:
        """
        Connect to the WebSocket server.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            import websockets

            logger.info(f"Connecting to WebSocket at {self.url}")
            self._websocket = await websockets.connect(
                self.url,
                ping_interval=30,
                ping_timeout=10,
            )
            self._connected = True
            logger.info(f"Connected to Rhino WebSocket at {self.url}")
            return True

        except ImportError:
            logger.error("websockets package not installed. Run: pip install websockets")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            self._connected = False
            self._websocket = None
            return False

    async def disconnect(self):
        """Disconnect from the WebSocket server."""
        self._running = False

        # Cancel the listen task
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        # Close the WebSocket
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception as e:
                logger.debug(f"Error closing WebSocket: {e}")
            self._websocket = None

        self._connected = False
        logger.info("Disconnected from WebSocket")

    async def start_listening(self) -> bool:
        """
        Start listening for events in the background.
        
        Returns:
            True if listening started successfully
        """
        if not self.is_connected:
            if not await self.connect():
                return False

        if self._running:
            logger.debug("Already listening for events")
            return True

        self._running = True
        self._listen_task = asyncio.create_task(self._listen_loop())
        logger.info("Started listening for WebSocket events")
        return True

    async def stop_listening(self):
        """Stop listening for events."""
        self._running = False
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        self._listen_task = None
        logger.info("Stopped listening for WebSocket events")

    async def _listen_loop(self):
        """Main event listening loop with automatic reconnection."""
        import websockets

        reconnect_delay = self.reconnect_delay

        while self._running:
            try:
                if not self.is_connected:
                    if not await self.connect():
                        # Exponential backoff for reconnection
                        logger.warning(f"Reconnection failed, waiting {reconnect_delay}s")
                        await asyncio.sleep(reconnect_delay)
                        reconnect_delay = min(reconnect_delay * 2, self.max_reconnect_delay)
                        continue
                    reconnect_delay = self.reconnect_delay  # Reset on successful connect

                # Receive message with timeout
                try:
                    message = await asyncio.wait_for(
                        self._websocket.recv(),
                        timeout=35.0  # Slightly longer than heartbeat interval
                    )

                    # Parse and handle the event
                    event_data = json.loads(message)
                    event = WebSocketEvent.from_json(event_data)
                    self._handle_event(event)

                except asyncio.TimeoutError:
                    # No message received, but connection might still be alive
                    logger.debug("No message received in timeout period")
                    continue

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e}")
                self._connected = False
                self._websocket = None
                # Will reconnect on next loop iteration

            except Exception as e:
                logger.error(f"Error in WebSocket listen loop: {e}")
                self._connected = False
                self._websocket = None
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, self.max_reconnect_delay)

        logger.debug("Listen loop exited")

    def _handle_event(self, event: WebSocketEvent):
        """Process a received event."""
        # Update current prompt if this is a Prompt event
        if event.event_type == "Prompt":
            with self._prompt_lock:
                self._current_prompt = event.text

        # Check for pending request responses
        request_id = event.raw.get("request_id")
        if request_id:
            with self._requests_lock:
                if request_id in self._pending_requests:
                    self._pending_responses[request_id] = event.raw
                    self._pending_requests[request_id].set()

        # Add to buffer (skip heartbeats and internal responses)
        if event.event_type not in ["Heartbeat", "Pong", "InputResult", "CancelResult"]:
            with self._buffer_lock:
                self._event_buffer.append(event)

        # Notify callbacks
        with self._callbacks_lock:
            for callback in self._callbacks:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"Error in event callback: {e}")

    def add_callback(self, callback: Callable[[WebSocketEvent], None]):
        """Add a callback function to be called for each event."""
        with self._callbacks_lock:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[WebSocketEvent], None]):
        """Remove a callback function."""
        with self._callbacks_lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def get_buffered_events(self, count: Optional[int] = None, clear: bool = False) -> List[WebSocketEvent]:
        """
        Get events from the buffer.
        
        Args:
            count: Maximum number of events to return (None = all)
            clear: Whether to clear the returned events from the buffer
        
        Returns:
            List of WebSocketEvent objects
        """
        with self._buffer_lock:
            if count is None:
                events = list(self._event_buffer)
            else:
                events = list(self._event_buffer)[-count:]

            if clear:
                self._event_buffer.clear()

            return events

    def clear_buffer(self):
        """Clear all buffered events."""
        with self._buffer_lock:
            self._event_buffer.clear()

    async def send_input(self, value: str, timeout: float = 5.0) -> bool:
        """
        Send input to the Rhino command line.
        
        Args:
            value: The input value to send
            timeout: Timeout in seconds
        
        Returns:
            True if input was sent successfully
        """
        if not self.is_connected:
            logger.warning("Cannot send input: not connected")
            return False

        request_id = str(uuid.uuid4())
        
        # Register pending request
        event = asyncio.Event()
        with self._requests_lock:
            self._pending_requests[request_id] = event

        try:
            # Send the command
            message = json.dumps({
                "command": "send_input",
                "input": value,
                "request_id": request_id
            })
            await self._websocket.send(message)
            
            # Wait for response
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
                with self._requests_lock:
                    response = self._pending_responses.get(request_id, {})
                return response.get("success", False)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for input response")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send input: {e}")
            return False
        finally:
            # Cleanup
            with self._requests_lock:
                self._pending_requests.pop(request_id, None)
                self._pending_responses.pop(request_id, None)

    async def run_script(self, script: str, wait_for_completion: bool = False, timeout: float = 60.0) -> bool:
        """
        Run a Rhino script.
        
        Args:
            script: The script to run
            wait_for_completion: Whether to wait for script to complete
            timeout: Timeout in seconds (only used if wait_for_completion=True)
        
        Returns:
            True if script was started (and completed if wait_for_completion=True)
        """
        if not self.is_connected:
            logger.warning("Cannot run script: not connected")
            return False

        request_id = str(uuid.uuid4())

        try:
            # Send the command
            message = json.dumps({
                "command": "run_script",
                "script": script,
                "request_id": request_id
            })
            await self._websocket.send(message)
            
            if not wait_for_completion:
                return True
            
            # Wait for ScriptCompleted event
            completion_event = asyncio.Event()
            result = {"success": False}
            
            def on_event(event: WebSocketEvent):
                if event.event_type in ["ScriptCompleted", "ScriptError"]:
                    if event.raw.get("request_id") == request_id:
                        result["success"] = event.raw.get("success", False)
                        completion_event.set()
            
            self.add_callback(on_event)
            try:
                await asyncio.wait_for(completion_event.wait(), timeout=timeout)
                return result["success"]
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for script completion")
                return False
            finally:
                self.remove_callback(on_event)
                
        except Exception as e:
            logger.error(f"Failed to run script: {e}")
            return False

    async def cancel(self) -> bool:
        """
        Cancel the current Rhino command.
        
        Returns:
            True if cancel was sent successfully
        """
        if not self.is_connected:
            logger.warning("Cannot cancel: not connected")
            return False

        try:
            message = json.dumps({"command": "cancel"})
            await self._websocket.send(message)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel: {e}")
            return False

    async def wait_for_prompt(
        self,
        pattern: str,
        timeout: float = 10.0,
        case_sensitive: bool = False
    ) -> Optional[WebSocketEvent]:
        """
        Wait for a prompt matching the given pattern.
        
        Args:
            pattern: Regex pattern or substring to match
            timeout: Maximum time to wait in seconds
            case_sensitive: Whether the match is case-sensitive
        
        Returns:
            The matching event, or None if timeout
        """
        # Compile regex pattern
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error:
            # If not a valid regex, treat as literal substring
            escaped = re.escape(pattern)
            regex = re.compile(escaped, flags)

        # Check if current prompt already matches
        with self._prompt_lock:
            if regex.search(self._current_prompt):
                return WebSocketEvent(
                    event_type="Prompt",
                    text=self._current_prompt,
                    timestamp=datetime.now().isoformat(),
                    raw={"type": "Prompt", "text": self._current_prompt}
                )

        # Set up a future to wait for matching event
        match_event = asyncio.Event()
        matched_event: List[WebSocketEvent] = []

        def on_event(event: WebSocketEvent):
            if event.event_type == "Prompt" and regex.search(event.text):
                matched_event.append(event)
                match_event.set()

        self.add_callback(on_event)

        try:
            # Wait for matching event or timeout
            await asyncio.wait_for(match_event.wait(), timeout=timeout)
            return matched_event[0] if matched_event else None
        except asyncio.TimeoutError:
            logger.debug(f"Timeout waiting for prompt matching '{pattern}'")
            return None
        finally:
            self.remove_callback(on_event)

    async def wait_for_event(
        self,
        event_type: str = None,
        text_pattern: str = None,
        timeout: float = 10.0
    ) -> Optional[WebSocketEvent]:
        """
        Wait for any event matching the criteria.
        
        Args:
            event_type: Event type to match (Prompt, History, etc.)
            text_pattern: Regex pattern for text content
            timeout: Maximum time to wait
        
        Returns:
            Matching event or None if timeout
        """
        # Compile text pattern if provided
        text_regex = None
        if text_pattern:
            try:
                text_regex = re.compile(text_pattern, re.IGNORECASE)
            except re.error:
                text_regex = re.compile(re.escape(text_pattern), re.IGNORECASE)

        match_event = asyncio.Event()
        matched: List[WebSocketEvent] = []

        def on_event(event: WebSocketEvent):
            # Check type match
            if event_type and event.event_type != event_type:
                return
            # Check text match
            if text_regex and not text_regex.search(event.text):
                return
            matched.append(event)
            match_event.set()

        self.add_callback(on_event)

        try:
            await asyncio.wait_for(match_event.wait(), timeout=timeout)
            return matched[0] if matched else None
        except asyncio.TimeoutError:
            return None
        finally:
            self.remove_callback(on_event)

    async def send_command(self, command: str, data: Dict = None) -> bool:
        """
        Send a command to the WebSocket server.
        
        Args:
            command: Command name (e.g., "ping", "get_state")
            data: Additional data to send
        
        Returns:
            True if sent successfully
        """
        if not self.is_connected:
            logger.warning("Cannot send command: not connected")
            return False

        try:
            message = {"command": command}
            if data:
                message.update(data)
            await self._websocket.send(json.dumps(message))
            return True
        except Exception as e:
            logger.error(f"Failed to send command: {e}")
            return False


# Singleton instance
_ws_client: Optional[RhinoWebSocketClient] = None
_ws_client_lock = threading.Lock()


def get_websocket_client(
    host: str = "127.0.0.1",
    port: int = 2000
) -> RhinoWebSocketClient:
    """
    Get or create the singleton WebSocket client.
    
    Args:
        host: WebSocket server host
        port: WebSocket server port
    
    Returns:
        The WebSocket client instance
    """
    global _ws_client

    with _ws_client_lock:
        if _ws_client is None:
            _ws_client = RhinoWebSocketClient(host=host, port=port)
        return _ws_client


def reset_websocket_client():
    """Reset the singleton WebSocket client (for testing)."""
    global _ws_client

    with _ws_client_lock:
        if _ws_client:
            # Note: This is sync, so we can't await disconnect
            # The client should be disconnected before calling this
            _ws_client._running = False
            _ws_client._connected = False
            _ws_client._websocket = None
        _ws_client = None
