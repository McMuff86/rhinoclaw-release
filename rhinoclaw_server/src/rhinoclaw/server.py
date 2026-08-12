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
    _io_lock: threading.Lock = field(default_factory=threading.Lock,
                                     repr=False, compare=False)
    
    def connect(self) -> bool:
        """Connect to the Rhino addon socket server"""
        if self.sock:
            return True
            
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Rhino at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Rhino: {str(e)}")
            self.sock = None
            return False
    
    def is_connected(self) -> bool:
        """Check if the connection to Rhino is active"""
        if self.sock is None:
            return False
        try:
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
                self.sock.setblocking(True)
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
        sock.settimeout(timeout if timeout is not None else get_settings().timeout_seconds)
        try:
            data = wire.read_json_frame(sock, buffer_size=buffer_size)
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

    def _execute_command(self, command_type: str, params: Dict[str, Any], timeout: float = 15.0,
                         idempotency_key: Optional[str] = None) -> Dict[str, Any]:
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
        )

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
            command_bytes = wire.encode_command(command)
            self.sock.sendall(command_bytes)
            if _debug_mode:
                logger.debug(f"Command JSON sent: {command_bytes.decode('utf-8')}")

            response_data = self.receive_full_response(self.sock, timeout=timeout)
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
        if wire.is_request_id_mismatch(request_id, response):
            echoed = response.get("request_id")
            self.disconnect()
            raise Exception(
                f"Transport integrity error: response request_id '{echoed}' "
                f"does not match sent '{request_id}' (command "
                f"{command_type}). A stale or interleaved frame was on the "
                "socket; the connection has been dropped — retry the call.")

        if response.get("status") == "error":
            logger.error(f"Rhino error: {response.get('message')}")
            raise RhinoCommandError(
                response.get("message", "Unknown error from Rhino"),
                error_code=response.get("error_code", ErrorCode.RHINO_ERROR),
                response=response,
            )

        return response.get("result", {})

    def send_command(self, command_type: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
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
            self.sock = None
            
            if self.reconnect():
                logger.info("Reconnected successfully, retrying command...")
                try:
                    # Same idempotency_key as the first attempt → the plugin
                    # can recognise this retry as a duplicate and not re-run it.
                    result = self._execute_command(command_type, params, timeout=timeout,
                                                   idempotency_key=idempotency_key)

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
                    self.sock = None
                    
                    # Log retry failure
                    interaction_logger.log_tool_call(
                        tool_name=command_type,
                        tool_args=params or {},
                        success=False,
                        error_code="RETRY_FAILED",
                        error_message=str(retry_error),
                        duration_ms=(time.time() - start_time) * 1000,
                    )
                    
                    raise Exception(f"Command failed after reconnect: {str(retry_error)}")
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
                raise ConnectionError("Failed to reconnect to Rhino. Make sure the Rhino plugin is running.")
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
            
            raise Exception(f"Invalid response from Rhino: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Rhino: {str(e)}")
            self.sock = None
            
            # Log general error
            interaction_logger.log_tool_call(
                tool_name=command_type,
                tool_args=params or {},
                success=False,
                error_code="RHINO_ERROR",
                error_message=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )
            
            raise Exception(f"Communication error with Rhino: {str(e)}")
    
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

def get_rhino_connection():
    """Get or create a persistent Rhino connection"""
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
                "Make sure the Rhino addon is running (mcpstart or tcpstart)."
            )
        logger.info("Created new persistent connection to Rhino")

    return _rhino_connection

# Main execution
def main():
    """Run the MCP server"""
    mcp.run()


if __name__ == "__main__":
    main()
