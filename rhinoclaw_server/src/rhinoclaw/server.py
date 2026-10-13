# rhinoclaw_server.py
import json
import logging
import socket
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Optional

from mcp.server.fastmcp import FastMCP

from rhinoclaw.config import get_settings
from rhinoclaw.logging_setup import configure_logging
from rhinoclaw.transport import wire
from rhinoclaw.utils.errors import ErrorCode, RhinoCommandError

# Configure logging according to settings (text or JSON format).
_settings = get_settings()
configure_logging(_settings)
logger = logging.getLogger("RhinoClawServer")

# Runtime debug flag — initialised from settings, toggleable via set_debug_mode tool.
_debug_mode = _settings.debug

def set_debug_mode(enable: bool):
    """Enable or disable debug mode"""
    global _debug_mode
    _debug_mode = enable
    logger.info(f"Debug mode {'enabled' if enable else 'disabled'}")

@dataclass
class RhinoConnection:
    host: str
    port: int
    sock: socket.socket | None = None
    max_retries: int = 3
    retry_delay: float = 1.0
    # Serialises send→receive pairs on the shared socket. Without it, two
    # concurrent send_command calls interleave their writes/reads and each
    # may consume the other's response (silent corruption). (W5d)
    _io_lock: threading.RLock = field(default_factory=threading.RLock,
                                     repr=False, compare=False)

    _session_id: Optional[str] = field(default=None, repr=False)
    _framed: bool = field(default=False, repr=False)
    _replay_supported: bool = field(default=False, repr=False)

    def connect(self) -> bool:
        with self._io_lock:
            return self._connect_locked()

    def _connect_locked(self) -> bool:
        """Connect to the Rhino addon socket server"""
        if self.sock:
            return True

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(min(5.0, get_settings().timeout_seconds))
            self.sock.connect((self.host, self.port))
            self._framed = False
            self._session_id = None
            self._replay_supported = False
            hello = self._execute_command("hello", {}, timeout=5.0)
            if not isinstance(hello.get("plugin_version"), str):
                raise ConnectionError("Endpoint did not identify itself as a RhinoClaw plugin")
            session = hello.get("session_id")
            self._session_id = session if isinstance(session, str) and session else None
            self._framed = "length_prefix_v1" in hello.get("framing", [])
            self._replay_supported = hello.get("replay_lookup_only") is True and self._session_id is not None
            logger.info(f"Connected to Rhino at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Rhino: {str(e)}")
            self.disconnect()
            return False

    def is_connected(self) -> bool:
        with self._io_lock:
            return self._is_connected_locked()

    def _is_connected_locked(self) -> bool:
        """Check if the connection to Rhino is active"""
        if self.sock is None:
            return False
        try:
            original_timeout = self.sock.gettimeout()
            self.sock.setblocking(False)
            try:
                data = self.sock.recv(1, socket.MSG_PEEK)
                if data == b'':
                    return False
            except BlockingIOError:
                pass
            except ConnectionError:
                return False
            finally:
                self.sock.settimeout(original_timeout)
            return True
        except Exception:
            return False

    def reconnect(self, max_retries: int | None = None, retry_delay: float | None = None) -> bool:
        """
        Attempt to reconnect to Rhino with configurable retries.

        Args:
            max_retries: Number of retry attempts (default: self.max_retries = 3)
            retry_delay: Delay between retries in seconds (default: self.retry_delay = 1.0)

        Returns:
            True if reconnection successful, False otherwise
        """
        retries = max_retries if max_retries is not None else self.max_retries
        delay = retry_delay if retry_delay is not None else self.retry_delay

        self.disconnect()

        for attempt in range(1, retries + 1):
            logger.info(f"Reconnection attempt {attempt}/{retries}...")
            if self.connect():
                logger.info(f"Reconnected to Rhino on attempt {attempt}")
                return True
            if attempt < retries:
                logger.info(f"Waiting {delay}s before next attempt...")
                import time
                time.sleep(delay)

        logger.error(f"Failed to reconnect after {retries} attempts")
        return False

    def disconnect(self):
        with self._io_lock:
            self._disconnect_locked()

    def _disconnect_locked(self):
        """Disconnect from the Rhino addon"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Rhino: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192, timeout=None):
        """Receive the complete response, potentially in multiple chunks.

        The chunk-until-it-parses framing lives in ``wire.read_json_frame``
        (shared with the rhinoclaw_client CLI, A3); this wrapper adds the
        connection's per-call timeout, logging, and the operator-facing "no
        reply" hint. A silent no-reply surfaces as a plain ``Exception`` (NOT a
        ``socket.timeout``/``ConnectionError``), so ``send_command`` does not
        blindly re-send a command that may already have run. A genuine drop
        (RST) still propagates as a ``ConnectionError`` for the retry path.
        """
        # Honour the caller's per-call timeout (send_command clamps it to
        # [1.0, max_timeout_seconds]); fall back to the configured default.
        # Long-running commands would otherwise be cut off at the default.
        duration = timeout if timeout is not None else get_settings().timeout_seconds
        sock.settimeout(duration)
        try:
            data = wire.read_json_frame(sock, buffer_size=buffer_size, framed=self._framed,
                                        deadline=time.monotonic() + duration)
        except wire.IncompleteFrameError as e:
            # Empty/truncated stream within the timeout — most often a blocked
            # Rhino UI thread. Keep that operator hint (and stay a plain
            # Exception so the auto-retry does not fire).
            logger.warning(f"Incomplete receive: {e}")
            raise Exception(
                "No data received — Rhino did not answer in time. Likely a "
                "MODAL DIALOG or long-running command is blocking the UI "
                "thread (invisible to remote agents): run get_ui_state, and "
                "check the Rhino screen.") from e
        logger.info(f"Received complete response ({len(data)} bytes)")
        return data

    # Extra slack on the socket-recv deadline beyond the command timeout we
    # hand the plugin: the plugin writes a structured TIMEOUT error frame at
    # exactly `timeout`, and without the grace our recv deadline would expire
    # in a race with that frame — turning a diagnosable plugin-side timeout
    # into an anonymous "no data received".
    _PLUGIN_REPLY_GRACE_SECONDS = 5.0

    def _execute_command(self, command_type: str, params: Dict[str, Any], timeout: float = 15.0,
                         idempotency_key: Optional[str] = None, replay_only: bool = False) -> Dict[str, Any]:
        """Internal method to execute a command (no retry logic).

        `idempotency_key` is stable across the reconnect-retry in
        `send_command`, so the plugin can de-duplicate a command that already
        ran server-side before the socket dropped (instead of re-executing it).
        """
        request_id = wire.new_request_id()
        # Auth token is injected only when configured; the plugin enforces it
        # only when it has a token of its own. Frame assembly lives in `wire`
        # (shared with the rhinoclaw_client CLI, A3).
        settings = get_settings()
        command = wire.build_command(
            command_type,
            params,
            request_id=request_id,
            idempotency_key=idempotency_key,
            auth_token=settings.auth_token,
            # Sizes the plugin's UI-thread wait (clamped to [1, 300] there).
            # Without this the plugin always waited its 60 s default, so a
            # tool-level timeout above 60 s was silently unreachable.
            timeout=timeout,
        )

        if self._session_id and command_type != "hello":
            command["expected_session_id"] = self._session_id
        if replay_only:
            command["replay_only"] = True
        log_extra = {"request_id": request_id, "tool": command_type}
        if _debug_mode:
            logger.debug(
                f"Sending command: {command_type} with params: {json.dumps(params, indent=2)}",
                extra=log_extra,
            )
        else:
            logger.info(
                f"Sending command: {command_type}",
                extra=log_extra,
            )

        if self.sock is None:
            raise ConnectionError("Socket is not connected")

        # One send→receive pair at a time on the shared socket (W5d).
        with self._io_lock:
            try:
                command_bytes = wire.encode_command(command, framed=self._framed)
            except (ValueError, TypeError) as exc:
                raise RhinoCommandError("Command is not valid bounded JSON.", error_code=ErrorCode.INVALID_PARAMS,
                                        response={"executed": False}) from exc
            self.sock.sendall(command_bytes)
            if _debug_mode:
                logger.debug("Command sent (%d bytes)", len(command_bytes), extra=log_extra)

            response_data = self.receive_full_response(
                self.sock, timeout=timeout + self._PLUGIN_REPLY_GRACE_SECONDS)
        if _debug_mode:
            logger.debug(f"Received raw response: {response_data.decode('utf-8')}")

        response = json.loads(response_data.decode('utf-8'))
        if _debug_mode:
            logger.debug(f"Response parsed: {json.dumps(response, indent=2)}")
        else:
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")

        # Transport integrity (W5d): the plugin echoes our request_id; a
        # mismatch means we just consumed a response that belongs to a
        # DIFFERENT call (stale frame after a timeout, interleaved client).
        # Fail loudly and discard the socket — the stream is poisoned.
        if wire.is_request_id_mismatch(request_id, response) or (self._framed and response.get("request_id") != request_id):
            echoed = response.get("request_id")
            self.disconnect()
            raise Exception(
                f"Transport integrity error: response request_id '{echoed}' "
                f"does not match sent '{request_id}' (command "
                f"{command_type}). A stale or interleaved frame was on the "
                "socket; the connection has been dropped. Query the operation result before any further mutation.")

        if response.get("status") == "error":
            logger.error(f"Rhino error: {response.get('message')}")
            raise RhinoCommandError(
                response.get("message", "Unknown error from Rhino"),
                error_code=response.get("error_code", ErrorCode.RHINO_ERROR),
                response=response,
            )

        return response.get("result", {})

    def send_command(self, command_type: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        # Connection changes and retry decisions belong to the same transaction
        # as send/receive. A second caller cannot replace the socket mid-retry.
        with self._io_lock:
            return self._send_command_locked(command_type, params, timeout)

    def _send_command_locked(self, command_type: str, params: Optional[Dict[str, Any]], timeout: Optional[float]) -> Dict[str, Any]:
        """
        Send a command to Rhino with automatic reconnection on failure.

        Args:
            command_type: The command to execute
            params: Command parameters
            timeout: Response timeout in seconds. Defaults to settings.timeout_seconds,
                clamped to [1.0, settings.max_timeout_seconds].
        """
        from rhinoclaw.utils.interaction_logger import interaction_logger

        params = params if params is not None else {}
        settings = get_settings()
        if timeout is None:
            timeout = settings.timeout_seconds
        timeout = min(max(timeout, 1.0), settings.max_timeout_seconds)
        # One idempotency key per logical call, REUSED across the reconnect
        # retry below — lets the plugin de-duplicate a command that already ran
        # server-side before the socket dropped, instead of executing it twice
        # (e.g. baking doors twice). See tests/test_transport_loopback.py.
        idempotency_key = wire.new_idempotency_key()
        start_time = time.time()

        if not self.sock and not self.connect():
            # Log connection failure
            interaction_logger.log_tool_call(
                tool_name=command_type,
                tool_args=params or {},
                success=False,
                error_code="CONNECTION_ERROR",
                error_message="Not connected to Rhino",
                duration_ms=(time.time() - start_time) * 1000,
            )
            raise ConnectionError("Not connected to Rhino")

        original_session = self._session_id
        replay_supported = self._replay_supported
        try:
            result = self._execute_command(command_type, params, timeout=timeout,
                                            idempotency_key=idempotency_key)

            # Log successful call
            interaction_logger.log_tool_call(
                tool_name=command_type,
                tool_args=params or {},
                success=True,
                response_summary=self._summarize_response(result),
                duration_ms=(time.time() - start_time) * 1000,
            )

            return result
        except (socket.timeout, ConnectionError, BrokenPipeError, ConnectionResetError, OSError) as e:
            logger.warning(f"Connection error: {str(e)}. Attempting to reconnect...")
            self.disconnect()

            if not replay_supported:
                raise self._unknown_outcome(command_type, idempotency_key, original_session,
                    "Connection dropped; the plugin cannot prove a safe replay.") from e
            if self.reconnect():
                if self._session_id != original_session or not self._replay_supported:
                    raise self._unknown_outcome(command_type, idempotency_key, original_session,
                        "Plugin session changed. The original operation may have executed; replay was refused.") from e
                logger.info("Reconnected successfully, retrying command...")
                try:
                    # Same idempotency_key as the first attempt → the plugin
                    # can recognise this retry as a duplicate and not re-run it.
                    result = self._execute_command(command_type, params, timeout=timeout,
                                                   idempotency_key=idempotency_key, replay_only=True)

                    # Log successful retry
                    interaction_logger.log_tool_call(
                        tool_name=command_type,
                        tool_args=params or {},
                        success=True,
                        response_summary=self._summarize_response(result),
                        duration_ms=(time.time() - start_time) * 1000,
                    )

                    return result
                except RhinoCommandError as retry_error:
                    logger.error(
                        "Rhino rejected command after reconnect: %s",
                        retry_error,
                    )
                    interaction_logger.log_tool_call(
                        tool_name=command_type,
                        tool_args=params or {},
                        success=False,
                        error_code=retry_error.error_code,
                        error_message=str(retry_error),
                        duration_ms=(time.time() - start_time) * 1000,
                    )
                    raise
                except Exception as retry_error:
                    logger.error(f"Command failed after reconnect: {str(retry_error)}")
                    self.disconnect()

                    # Log retry failure
                    interaction_logger.log_tool_call(
                        tool_name=command_type,
                        tool_args=params or {},
                        success=False,
                        error_code="RETRY_FAILED",
                        error_message=str(retry_error),
                        duration_ms=(time.time() - start_time) * 1000,
                    )

                    raise self._unknown_outcome(command_type, idempotency_key, original_session,
                        "Result lookup after reconnect failed; execution outcome remains unknown.") from retry_error
            else:
                # Log reconnect failure
                interaction_logger.log_tool_call(
                    tool_name=command_type,
                    tool_args=params or {},
                    success=False,
                    error_code="CONNECTION_REFUSED",
                    error_message="Failed to reconnect to Rhino",
                    duration_ms=(time.time() - start_time) * 1000,
                )
                raise self._unknown_outcome(command_type, idempotency_key, original_session,
                    "Plugin could not be reached again; execution outcome remains unknown.") from e
        except RhinoCommandError as e:
            logger.error(f"Rhino rejected command: {str(e)}")

            interaction_logger.log_tool_call(
                tool_name=command_type,
                tool_args=params or {},
                success=False,
                error_code=e.error_code,
                error_message=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

            # A domain/validation error is a valid response frame. Keep the
            # healthy socket and preserve the plugin's machine-readable code.
            raise
        except json.JSONDecodeError as e:
            self.disconnect()
            logger.error(f"Invalid JSON response from Rhino: {str(e)}")

            # Log JSON error
            interaction_logger.log_tool_call(
                tool_name=command_type,
                tool_args=params or {},
                success=False,
                error_code="INVALID_RESPONSE",
                error_message=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

            raise self._unknown_outcome(command_type, idempotency_key, original_session,
                "Invalid response from Rhino; the execution outcome is unknown.") from e
        except Exception as e:
            logger.error(f"Error communicating with Rhino: {str(e)}")
            self.disconnect()

            # Log general error
            interaction_logger.log_tool_call(
                tool_name=command_type,
                tool_args=params or {},
                success=False,
                error_code="RHINO_ERROR",
                error_message=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

            raise self._unknown_outcome(command_type, idempotency_key, original_session,
                f"Communication error with Rhino: {str(e)}") from e

    @staticmethod
    def _unknown_outcome(command_type, operation_id, session_id, message):
        return RhinoCommandError(message, error_code="OUTCOME_UNKNOWN", response={
            "status": "error", "error_code": "OUTCOME_UNKNOWN", "message": message,
            "operation_id": operation_id, "session_id": session_id, "command": command_type,
            "executed": None, "next_action": "Inspect UI/document state and query get_operation_result; do not repeat the mutation automatically.",
        })

    def _summarize_response(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Create a compact summary of the response for logging."""
        summary = {}

        # Extract key identifiers
        if "id" in result:
            summary["id"] = result["id"]
        if "ids" in result:
            summary["ids"] = result["ids"][:5] if len(result.get("ids", [])) > 5 else result.get("ids")
            if len(result.get("ids", [])) > 5:
                summary["ids_count"] = len(result["ids"])
        if "name" in result:
            summary["name"] = result["name"]
        if "count" in result:
            summary["count"] = result["count"]
        if "status" in result:
            summary["status"] = result["status"]
        if "type" in result:
            summary["type"] = result["type"]

        return summary if summary else {"raw_keys": list(result.keys())}

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    # We don't need to create a connection here since we're using the global connection
    # for resources and tools

    try:
        # Just log that we're starting up
        logger.info("RhinoClaw server starting up")

        # Try to connect to Rhino on startup to verify it's available
        try:
            # This will initialize the global connection if needed
            get_rhino_connection()
            logger.info("Successfully connected to Rhino on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Rhino on startup: {str(e)}")
            logger.warning("Make sure the Rhino addon is running before using Rhino resources or tools")

        # Return an empty context - we're using the global connection
        yield {}
    finally:
        # Clean up the global connection on shutdown
        global _rhino_connection
        if _rhino_connection:
            logger.info("Disconnecting from Rhino on shutdown")
            _rhino_connection.disconnect()
            _rhino_connection = None
        logger.info("RhinoClaw server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "RhinoClaw",
    lifespan=server_lifespan
)

# Resource endpoints

# Global connection for resources (since resources can't access context)
_rhino_connection = None
_connection_creation_lock = threading.Lock()

def get_rhino_connection():
    """Get or create a persistent Rhino connection"""
    with _connection_creation_lock:
        return _get_rhino_connection_locked()


def _get_rhino_connection_locked():
    global _rhino_connection

    # Create a new connection if needed
    if _rhino_connection is None:
        settings = get_settings()
        _rhino_connection = RhinoConnection(host=settings.host, port=settings.port)
        if not _rhino_connection.connect():
            logger.error("Failed to connect to Rhino")
            _rhino_connection = None
            raise Exception(
                f"Could not connect to Rhino at {settings.host}:{settings.port}. "
                "Make sure the Rhino plugin server is running (ClawStart local, ClawTcpStart remote, or ClawAutoStart)."
            )
        logger.info("Created new persistent connection to Rhino")

    return _rhino_connection

# Main execution
def main():
    """Run the MCP server"""
    mcp.run()


if __name__ == "__main__":
    main()
