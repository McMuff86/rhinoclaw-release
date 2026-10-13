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
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Deque, Dict, List, Optional

from rhinoclaw.config import get_settings

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
        self._auth_failed = False
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
        self._auth_failed = False
        try:
            import websockets

            logger.info(f"Connecting to WebSocket at {self.url}")
            self._websocket = await websockets.connect(
                self.url,
                ping_interval=30,
                ping_timeout=10,
            )
            # Subscribe before starting the receive loop, including on reconnect.
            # Older plugins send Connected without auth_protocol and stream
            # immediately; their welcome remains supported.
            welcome = json.loads(await asyncio.wait_for(self._websocket.recv(), timeout=5.0))
            if welcome.get("type") != "Connected":
                raise ConnectionError("Missing Rhino WebSocket welcome")
            if welcome.get("auth_protocol") == 1:
                request_id = str(uuid.uuid4())
                await self._websocket.send(self._encode_message({
                    "command": "subscribe", "request_id": request_id,
                }))
                response = json.loads(await asyncio.wait_for(self._websocket.recv(), timeout=5.0))
                if response.get("type") != "Subscribed" or response.get("request_id") != request_id:
                    self._auth_failed = response.get("error_code") in {"AUTH_REQUIRED", "AUTH_BLOCKED"}
                    raise ConnectionError("WebSocket subscription rejected: " + str(response.get("error_code", "INVALID_RESPONSE")))
            self._handle_event(WebSocketEvent.from_json(welcome))
            self._connected = True
            logger.info(f"Connected to Rhino WebSocket at {self.url}")

            # A connected transport without a receive loop cannot deliver
            # request-correlated acknowledgements.  Public usage has always
            # documented ``connect()`` as sufficient before ``get_state()``,
            # ``send_input()`` or ``run_script()``; make that contract true.
            # During an automatic reconnect ``_running`` is already true, so
            # the existing listener reconnects its own transport instead of
            # spawning a second consumer for the same socket.
            if not self._running:
                self._running = True
                self._listen_task = asyncio.create_task(self._listen_loop())
                logger.info("Started listening for WebSocket events")
            return True

        except ImportError:
            logger.error("websockets package not installed. Run: pip install websockets")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            self._connected = False
            if self._websocket is not None:
                await self._websocket.close()
            self._websocket = None
            return False

    @staticmethod
    def _encode_message(message: Dict[str, Any]) -> str:
        """Attach configured credentials to every request without logging them."""
        payload = dict(message)
        token = get_settings().auth_token
        if token:
            payload["auth"] = token
        return json.dumps(payload)

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
                        if self._auth_failed:
                            self._running = False
                            break  # A configuration error must not trigger a brute-force lockout.
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

    async def get_state(
        self,
        timeout: float = 5.0,
    ) -> Optional[Dict[str, Any]]:
        """Request a correlated, typed Rhino command state.

        The response callback is installed before sending the command so an
        immediate ``State`` event cannot be lost.

        Args:
            timeout: Maximum time to wait for the State response.

        Returns:
            Prompt, command depth, idle flag and stack, or None on failure.
        """
        if not self.is_connected:
            logger.warning("Cannot get state: not connected")
            return None

        response_event = asyncio.Event()
        request_id = str(uuid.uuid4())
        responses: List[Optional[Dict[str, Any]]] = []

        def on_event(event: WebSocketEvent):
            if (
                event.event_type not in {"State", "Error"}
                or event.raw.get("request_id") != request_id
                or responses
            ):
                return
            if event.event_type == "Error":
                responses.append(None)
                response_event.set()
                return
            current_prompt = event.raw.get("current_prompt")
            in_command = event.raw.get("in_command")
            command_idle = event.raw.get("command_idle")
            command_stack = event.raw.get("command_stack")
            valid = (
                isinstance(current_prompt, str)
                and isinstance(in_command, int)
                and not isinstance(in_command, bool)
                and in_command >= 0
                and isinstance(command_idle, bool)
                and command_idle is (in_command == 0)
                and isinstance(command_stack, list)
                and all(isinstance(item, str) for item in command_stack)
            )
            responses.append({
                "current_prompt": current_prompt,
                "in_command": in_command,
                "command_idle": command_idle,
                "command_stack": command_stack,
            } if valid else None)
            response_event.set()

        callback_registered = False
        try:
            self.add_callback(on_event)
            callback_registered = True
            await self._websocket.send(self._encode_message({
                "command": "get_state",
                "request_id": request_id,
            }))
            await asyncio.wait_for(response_event.wait(), timeout=timeout)
            return responses[0]
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for state response")
            return None
        except Exception as e:
            logger.error(f"Failed to get state: {e}")
            return None
        finally:
            if callback_registered:
                self.remove_callback(on_event)

    async def wait_for_command_idle(
        self,
        timeout: float = 10.0,
        poll_interval: float = 0.05,
        require_observed_active: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Wait until a correlated state proves ``in_command == 0``.

        When ``require_observed_active`` is true, an initial idle state is
        ignored until at least one positive command depth was observed. This
        closes the delayed-command-start race after an asynchronous request.
        """
        if timeout <= 0 or poll_interval <= 0:
            raise ValueError("timeout and poll_interval must be positive")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        observed_active = not require_observed_active
        while loop.time() < deadline:
            remaining = deadline - loop.time()
            state = await self.get_state(timeout=min(2.0, remaining))
            if state is not None:
                if state["in_command"] > 0:
                    observed_active = True
                elif observed_active and state["command_idle"] is True:
                    return state
            remaining = deadline - loop.time()
            if remaining > 0:
                await asyncio.sleep(min(poll_interval, remaining))
        return None

    async def send_input(self, value: str, timeout: float = 5.0) -> bool:
        """
        Send input to the Rhino command line.

        Returns True only when Rhino confirmed that the script completed
        successfully. See ``send_input_detailed`` for the three distinct
        outcomes (delivered+ok, delivered+declined, unconfirmed).
        """
        outcome = await self.send_input_detailed(value, timeout=timeout)
        return outcome["rhino_success"] is True

    async def send_input_detailed(self, value: str, timeout: float = 5.0) -> Dict[str, Any]:
        """
        Send input to the Rhino command line and report what actually happened.

        The plugin runs the input through ``RhinoApp.RunScript``, which blocks
        until the script finishes. An interactive command (``_vaSection``,
        ``_Line``, ...) therefore only reports back after the user finished or
        cancelled it, and a macro starting with ``!`` may report ``false`` even
        though the command it launched is running. Callers must not read a
        missing confirmation as "nothing was sent".

        Returns:
            {"delivered": bool,            # Rhino sent a reply for this request
             "rhino_success": bool | None, # RunScript result; None when unconfirmed
             "timed_out": bool,            # no reply within ``timeout``
             "error": str | None}          # plugin or transport error text
        """
        outcome: Dict[str, Any] = {
            "delivered": False, "rhino_success": None, "timed_out": False, "error": None,
        }
        if not self.is_connected:
            logger.warning("Cannot send input: not connected")
            outcome["error"] = "not connected to the Rhino WebSocket stream"
            return outcome

        request_id = str(uuid.uuid4())

        # Register pending request
        event = asyncio.Event()
        with self._requests_lock:
            self._pending_requests[request_id] = event

        try:
            # Send the command
            message = self._encode_message({
                "command": "send_input",
                "input": value,
                "request_id": request_id
            })
            await self._websocket.send(message)

            # Wait for response
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for input response")
                outcome["timed_out"] = True
                return outcome
            with self._requests_lock:
                response = self._pending_responses.get(request_id, {})
            if response.get("type") == "Error":
                outcome["error"] = str(response.get("message") or "plugin reported an error")
                return outcome
            outcome["delivered"] = True
            outcome["rhino_success"] = bool(response.get("success", False))
            return outcome

        except Exception as e:
            logger.error(f"Failed to send input: {e}")
            outcome["error"] = str(e)
            return outcome
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
        completion_event = asyncio.Event()
        result = {"success": False}

        expected_events = (
            {"ScriptCompleted", "ScriptError", "Error"}
            if wait_for_completion
            else {"ScriptStarted", "ScriptError", "Error"}
        )

        def on_event(event: WebSocketEvent):
            if (
                event.event_type in expected_events
                and event.raw.get("request_id") == request_id
            ):
                result["success"] = (
                    event.event_type not in {"ScriptError", "Error"}
                    and event.raw.get("success", True) is True
                )
                completion_event.set()

        callback_registered = False

        try:
            # Register before send: Rhino can acknowledge or complete while
            # the send coroutine is still yielding control.
            self.add_callback(on_event)
            callback_registered = True

            # Send the command
            message = self._encode_message({
                "command": "run_script",
                "script": script,
                "request_id": request_id
            })
            await self._websocket.send(message)

            try:
                await asyncio.wait_for(completion_event.wait(), timeout=timeout)
                return result["success"]
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for script completion")
                return False

        except Exception as e:
            logger.error(f"Failed to run script: {e}")
            return False
        finally:
            if callback_registered:
                self.remove_callback(on_event)

    async def cancel(self, timeout: float = 5.0) -> bool:
        """
        Cancel the current Rhino command.

        Returns:
            True if cancel was sent successfully
        """
        if not self.is_connected:
            logger.warning("Cannot cancel: not connected")
            return False

        request_id = str(uuid.uuid4())
        event = asyncio.Event()
        with self._requests_lock:
            self._pending_requests[request_id] = event

        try:
            message = self._encode_message({
                "command": "cancel",
                "request_id": request_id,
            })
            await self._websocket.send(message)
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
                with self._requests_lock:
                    response = self._pending_responses.get(request_id, {})
                return (
                    response.get("type") == "CancelResult"
                    and response.get("success") is True
                )
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for cancel acknowledgment")
                return False
        except Exception as e:
            logger.error(f"Failed to cancel: {e}")
            return False
        finally:
            with self._requests_lock:
                self._pending_requests.pop(request_id, None)
                self._pending_responses.pop(request_id, None)

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
            await self._websocket.send(self._encode_message(message))
            return True
        except Exception as e:
            logger.error(f"Failed to send command: {e}")
            return False


# Singleton instance
_ws_client: Optional[RhinoWebSocketClient] = None
_ws_client_lock = threading.Lock()


def get_websocket_client(
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> RhinoWebSocketClient:
    """
    Get or create the singleton WebSocket client.

    Args:
        host: Optional explicit WebSocket server host. On first creation this
            defaults to the shared ``RHINOCLAW_HOST`` setting used by TCP.
        port: Optional explicit WebSocket server port. On first creation this
            defaults to ``RHINOCLAW_WS_PORT``.

    Returns:
        The WebSocket client instance
    """
    global _ws_client

    with _ws_client_lock:
        if _ws_client is None:
            settings = get_settings()
            resolved_host = host if host is not None else settings.host
            resolved_port = port if port is not None else settings.ws_port
            _ws_client = RhinoWebSocketClient(
                host=resolved_host,
                port=resolved_port,
            )
        elif host is not None or port is not None:
            # Default callers stay attached to the endpoint selected at first
            # creation. That lets disconnect/status recover an active client
            # even if tests or embedding code reload process settings later.
            resolved_host = host if host is not None else _ws_client.host
            resolved_port = port if port is not None else _ws_client.port
            if (
                _ws_client.host != resolved_host
                or _ws_client.port != resolved_port
            ):
                if _ws_client.is_connected or _ws_client._running:
                    raise RuntimeError(
                        "WebSocket endpoint changed while the singleton "
                        "client is active; disconnect and reset it before "
                        "reconnecting"
                    )
                _ws_client = RhinoWebSocketClient(
                    host=resolved_host,
                    port=resolved_port,
                )
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
