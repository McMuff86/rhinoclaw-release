"""
Real-time Rhino command stream tools.

These tools enable AI agents to interact with Rhino in real-time via WebSocket.
The WebSocket connection provides:
- Push-based event notifications (prompts, history changes)
- Direct input sending to command line
- Script execution with completion tracking

Usage Flow:
    1. connect_rhino_stream() - Establish WebSocket connection
    2. send_rhino_input() - Send input to Rhino when prompted
    3. wait_for_prompt() - Wait for specific prompt patterns
    4. disconnect_rhino_stream() - Cleanup when done
"""

import asyncio
import json
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok
from rhinoclaw.websocket_client import get_websocket_client


@mcp.tool()
async def connect_rhino_stream(ctx: Context) -> str:
    """
    Connect to Rhino's real-time event stream via WebSocket.
    
    Establishes a WebSocket connection to the Rhino plugin (port 2000)
    for receiving real-time events and sending commands.
    
    Returns:
        JSON with connection status and current Rhino state
    
    Example:
        >>> connect_rhino_stream()
        {"ok": true, "data": {"connected": true, "current_prompt": "Command:"}}
    
    Notes:
        - Requires Rhino plugin running with mcpstart command
        - Connection auto-reconnects on failure
        - Call disconnect_rhino_stream() when done
    """
    try:
        ws_client = get_websocket_client()
        
        success = await ws_client.start_listening()
        
        if success:
            logger.info("Connected to Rhino stream")
            return json.dumps(ok(
                message="Connected to Rhino real-time stream",
                data={
                    "connected": True,
                    "url": ws_client.url,
                    "current_prompt": ws_client.current_prompt,
                }
            ))
        else:
            return json.dumps(ok(
                message="Failed to connect to Rhino stream",
                data={
                    "connected": False,
                    "url": ws_client.url,
                    "hint": "Make sure Rhino plugin is running (mcpstart)"
                }
            ))
        
    except Exception as e:
        logger.error(f"Failed to connect to stream: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.CONNECTION_ERROR))


@mcp.tool()
async def disconnect_rhino_stream(ctx: Context) -> str:
    """
    Disconnect from Rhino's real-time event stream.
    
    Closes the WebSocket connection and stops event listening.
    
    Returns:
        JSON with disconnection status
    
    Example:
        >>> disconnect_rhino_stream()
        {"ok": true, "message": "Disconnected from Rhino stream"}
    """
    try:
        ws_client = get_websocket_client()
        
        await ws_client.stop_listening()
        await ws_client.disconnect()
        
        logger.info("Disconnected from Rhino stream")
        return json.dumps(ok(
            message="Disconnected from Rhino stream",
            data={"connected": False}
        ))
        
    except Exception as e:
        logger.error(f"Failed to disconnect: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.CONNECTION_ERROR))


@mcp.tool()
async def send_rhino_input(
    ctx: Context,
    value: str,
    timeout: float = 5.0,
) -> str:
    """
    Send input to the Rhino command line.
    
    Use this to respond to Rhino prompts detected via the stream.
    For example, when Rhino prompts for a point, send coordinates.
    
    Args:
        value: The input to send (e.g., "0,0,0", "WorldXY", "2200")
        timeout: Timeout in seconds for response
    
    Returns:
        JSON with send status
    
    Example:
        >>> # Rhino prompts: "Lichthoehe:"
        >>> send_rhino_input("2200")
        {"ok": true, "data": {"sent": true, "value": "2200"}}
        
        >>> # Rhino prompts: "GetPlane ( WorldXY  WorldYZ  WorldZX )"
        >>> send_rhino_input("WorldXY")
    
    Notes:
        - Requires active stream connection
        - Input is sent via WebSocket for faster response
        - Use empty string "" to simulate pressing Enter
    """
    try:
        ws_client = get_websocket_client()
        
        if not ws_client.is_connected:
            # Auto-connect if not connected
            await ws_client.start_listening()
        
        success = await ws_client.send_input(value, timeout=timeout)
        
        if success:
            logger.info(f"Sent input: {value}")
            return json.dumps(ok(
                message=f"Input sent successfully",
                data={
                    "sent": True,
                    "value": value,
                    "current_prompt": ws_client.current_prompt,
                }
            ))
        else:
            return json.dumps(ok(
                message="Failed to send input",
                data={
                    "sent": False,
                    "value": value,
                    "hint": "Rhino may not be waiting for input"
                }
            ))
        
    except Exception as e:
        logger.error(f"Failed to send input: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
async def wait_for_prompt(
    ctx: Context,
    pattern: str,
    timeout: float = 10.0,
) -> str:
    """
    Wait for a specific prompt pattern from Rhino.
    
    Blocks until Rhino displays a prompt matching the given pattern,
    or until timeout expires.
    
    Args:
        pattern: Regex pattern or substring to match (case-insensitive)
        timeout: Maximum time to wait in seconds
    
    Returns:
        JSON with matched prompt or timeout status
    
    Example:
        >>> # Wait for GetPlane prompt
        >>> wait_for_prompt("GetPlane")
        {"ok": true, "data": {"matched": true, "prompt": "GetPlane ( WorldXY  WorldYZ  WorldZX )"}}
        
        >>> # Pattern examples:
        >>> wait_for_prompt("lichthoehe|height")  # Match either term
        >>> wait_for_prompt("pick.*point")        # Regex pattern
    
    Notes:
        - Auto-connects to stream if not connected
        - Current prompt is checked immediately
        - Pattern matching is case-insensitive
    """
    if not pattern:
        return json.dumps(ok(
            message="Pattern is required",
            data={"matched": False, "error": "Empty pattern"}
        ))
    
    try:
        ws_client = get_websocket_client()
        
        if not ws_client.is_connected:
            await ws_client.start_listening()
        
        event = await ws_client.wait_for_prompt(
            pattern=pattern,
            timeout=timeout,
            case_sensitive=False
        )
        
        if event:
            return json.dumps(ok(
                message=f"Found prompt matching '{pattern}'",
                data={
                    "matched": True,
                    "prompt": event.text,
                    "timestamp": event.timestamp,
                }
            ))
        else:
            return json.dumps(ok(
                message=f"Timeout waiting for prompt",
                data={
                    "matched": False,
                    "timeout": True,
                    "pattern": pattern,
                    "current_prompt": ws_client.current_prompt,
                }
            ))
        
    except Exception as e:
        logger.error(f"Error waiting for prompt: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
async def run_script_async(
    ctx: Context,
    script: str,
    wait_for_completion: bool = False,
    timeout: float = 60.0,
) -> str:
    """
    Run a Rhino script asynchronously via WebSocket.
    
    Starts a script and optionally waits for completion.
    Use this for scripts that require user input - you can monitor
    prompts and send inputs while the script runs.
    
    Args:
        script: The Rhino script to run (e.g., '_-GrasshopperPlayer "path/to/file.gh"')
        wait_for_completion: Whether to wait for script to finish
        timeout: Timeout in seconds (only if wait_for_completion=True)
    
    Returns:
        JSON with script status
    
    Example:
        >>> # Start GrasshopperPlayer (don't wait - we need to send inputs)
        >>> run_script_async('_-GrasshopperPlayer "C:/path/to/door.gh"')
        {"ok": true, "data": {"started": true}}
        
        >>> # Run simple script and wait
        >>> run_script_async("_Box 0,0,0 10,10,10", wait_for_completion=True)
    
    Notes:
        - Script runs on Rhino UI thread
        - Use wait_for_prompt() to detect when input is needed
        - Use send_rhino_input() to provide input
    """
    if not script:
        return json.dumps(ok(
            message="Script is required",
            data={"started": False, "error": "Empty script"}
        ))
    
    try:
        ws_client = get_websocket_client()
        
        if not ws_client.is_connected:
            await ws_client.start_listening()
        
        success = await ws_client.run_script(
            script=script,
            wait_for_completion=wait_for_completion,
            timeout=timeout
        )
        
        if wait_for_completion:
            return json.dumps(ok(
                message="Script completed" if success else "Script failed",
                data={
                    "completed": True,
                    "success": success,
                    "script": script,
                }
            ))
        else:
            return json.dumps(ok(
                message="Script started",
                data={
                    "started": True,
                    "script": script,
                    "current_prompt": ws_client.current_prompt,
                }
            ))
        
    except Exception as e:
        logger.error(f"Failed to run script: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
async def cancel_rhino_command(ctx: Context) -> str:
    """
    Cancel the current Rhino command (emergency escape).
    
    Sends Escape key to Rhino to cancel any hanging command.
    This is like pressing Esc in Rhino - it cancels the current operation
    and returns to Command prompt.
    
    Use this when:
    - Rhino is waiting for input you don't recognize
    - A command is hanging/timed out
    - You need to abort the current operation
    
    Returns:
        JSON with cancel status and current prompt
    
    Example:
        >>> cancel_rhino_command()
        {"ok": true, "message": "Cancel sent", "cancelled": true, "current_prompt": "Command"}
    
    See also:
        docs/learnings/getting-unstuck.md - Complete guide for handling stuck situations
    """
    try:
        ws_client = get_websocket_client()
        
        if not ws_client.is_connected:
            await ws_client.start_listening()
        
        success = await ws_client.cancel()
        
        return json.dumps(ok(
            message="Cancel sent" if success else "Failed to send cancel",
            data={
                "cancelled": success,
                "current_prompt": ws_client.current_prompt,
            }
        ))
        
    except Exception as e:
        logger.error(f"Failed to cancel: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
async def get_stream_status(ctx: Context) -> str:
    """
    Get the current status of the Rhino stream connection.
    
    Returns information about the WebSocket connection and current state.
    
    Returns:
        JSON with stream status
    
    Example:
        >>> get_stream_status()
        {
            "ok": true,
            "data": {
                "connected": true,
                "current_prompt": "Command:",
                "buffer_size": 5
            }
        }
    """
    try:
        ws_client = get_websocket_client()
        
        return json.dumps(ok(
            message="Stream status",
            data={
                "connected": ws_client.is_connected,
                "url": ws_client.url,
                "current_prompt": ws_client.current_prompt,
                "buffer_size": ws_client.event_count,
                "listening": ws_client._running,
            }
        ))
        
    except Exception as e:
        logger.error(f"Error getting stream status: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
async def get_stream_events(
    ctx: Context,
    count: Optional[int] = None,
    clear: bool = True,
) -> str:
    """
    Get buffered events from the stream.
    
    Retrieves events that have been received since the last call.
    
    Args:
        count: Maximum number of events (None = all)
        clear: Whether to clear buffer after retrieval
    
    Returns:
        JSON with events list
    
    Example:
        >>> get_stream_events()
        {
            "ok": true,
            "data": {
                "events": [
                    {"type": "Prompt", "text": "Command:", "timestamp": "..."}
                ],
                "count": 1
            }
        }
    """
    try:
        ws_client = get_websocket_client()
        
        events = ws_client.get_buffered_events(count=count, clear=clear)
        
        event_list = [
            {
                "type": event.event_type,
                "text": event.text,
                "timestamp": event.timestamp,
            }
            for event in events
        ]
        
        return json.dumps(ok(
            message=f"Retrieved {len(event_list)} events",
            data={
                "events": event_list,
                "count": len(event_list),
                "current_prompt": ws_client.current_prompt,
            }
        ))
        
    except Exception as e:
        logger.error(f"Failed to get events: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
async def clear_stream_buffer(ctx: Context) -> str:
    """
    Clear all buffered events from the stream.
    
    Use before starting a new operation to get clean event state.
    
    Returns:
        JSON confirmation
    
    Example:
        >>> clear_stream_buffer()
        >>> run_script_async("...")
        >>> get_stream_events()  # Only events from this operation
    """
    try:
        ws_client = get_websocket_client()
        ws_client.clear_buffer()
        
        return json.dumps(ok(
            message="Stream buffer cleared",
            data={"buffer_size": 0}
        ))
        
    except Exception as e:
        logger.error(f"Error clearing buffer: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
