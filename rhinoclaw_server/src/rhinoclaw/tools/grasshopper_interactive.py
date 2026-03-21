"""
Interactive Grasshopper script execution with WebSocket-based input handling.

This module provides tools for running Grasshopper scripts that require
user input, using WebSocket for real-time prompt detection and response.

The key advantage over the basic run_grasshopper tool is that this
approach can automatically detect and respond to prompts, making
fully automated Grasshopper workflows possible.
"""

import asyncio
import json
import re
from typing import Dict, List, Optional, Any

from mcp.server.fastmcp import Context

from rhinoclaw.server import logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok
from rhinoclaw.websocket_client import get_websocket_client


@mcp.tool()
async def run_grasshopper_interactive(
    ctx: Context,
    file_path: str,
    inputs: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0,
    input_delay: float = 0.1,
) -> str:
    """
    Run a Grasshopper script with automatic input handling.
    
    Uses WebSocket to detect prompts and send appropriate inputs.
    This is the recommended way to run interactive Grasshopper scripts.
    
    Args:
        file_path: Path to the .gh file
        inputs: Dict mapping prompt patterns to input values, e.g.:
                {"lichthoehe": "2200", "lichtbreite": "910", 
                 "getplane.*worldxy": "WorldXY", "getplane.*parallel": "0,0,0"}
        timeout: Maximum time to wait for script completion (seconds)
        input_delay: Delay between detecting prompt and sending input (seconds)
    
    Returns:
        JSON with execution status and any prompts encountered
    
    Example:
        >>> run_grasshopper_interactive(
        ...     file_path="C:/path/to/door.gh",
        ...     inputs={
        ...         "lichthoehe": "2200",
        ...         "lichtbreite": "910",
        ...         "getplane.*worldxy": "WorldXY",
        ...         "getplane.*parallel": "0,0,0"
        ...     }
        ... )
    
    Notes:
        - Patterns are matched case-insensitively as regex
        - Use ".*" for flexible matching
        - Script starts asynchronously, then inputs are sent based on prompts
        - If a prompt doesn't match any pattern, script will wait for manual input
    """
    if not file_path:
        return json.dumps(ok(
            message="file_path is required",
            data={"success": False, "error": "Missing file_path"}
        ))
    
    inputs = inputs or {}
    
    try:
        ws_client = get_websocket_client()
        
        # Ensure connected
        if not ws_client.is_connected:
            await ws_client.start_listening()
            if not ws_client.is_connected:
                return json.dumps(ok(
                    message="Failed to connect to Rhino WebSocket",
                    data={
                        "success": False,
                        "error": "WebSocket connection failed",
                        "hint": "Make sure Rhino is running with mcpstart"
                    }
                ))
        
        # Clear buffer to get fresh events
        ws_client.clear_buffer()
        
        # Compile input patterns
        patterns = []
        for pattern, value in inputs.items():
            try:
                regex = re.compile(pattern, re.IGNORECASE)
                patterns.append((regex, value))
            except re.error:
                # Treat as literal string
                regex = re.compile(re.escape(pattern), re.IGNORECASE)
                patterns.append((regex, value))
        
        # Start the script
        script = f'_-GrasshopperPlayer "{file_path}"'
        logger.info(f"Starting Grasshopper script: {file_path}")
        
        if not await ws_client.run_script(script, wait_for_completion=False):
            return json.dumps(ok(
                message="Failed to start Grasshopper script",
                data={"success": False, "error": "Script start failed"}
            ))
        
        # Track what happened
        prompts_seen = []
        inputs_sent = []
        script_completed = False
        
        # Wait for prompts and send inputs
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            # Wait for next event
            event = await ws_client.wait_for_event(timeout=2.0)
            
            if event is None:
                # No event, check if we're back at Command prompt
                if "command" in ws_client.current_prompt.lower():
                    if prompts_seen:  # We've been through prompts
                        script_completed = True
                        break
                continue
            
            if event.event_type == "Prompt":
                prompt_text = event.text
                prompts_seen.append(prompt_text)
                
                # Check if this is the Command prompt (script done)
                if prompt_text.lower().strip() == "command":
                    if inputs_sent:  # We've sent inputs
                        script_completed = True
                        break
                    continue
                
                # Try to match against our patterns
                matched = False
                for regex, value in patterns:
                    if regex.search(prompt_text):
                        await asyncio.sleep(input_delay)
                        success = await ws_client.send_input(str(value))
                        inputs_sent.append({
                            "prompt": prompt_text,
                            "input": str(value),
                            "success": success
                        })
                        matched = True
                        break
                
                if not matched:
                    logger.warning(f"Unmatched prompt: {prompt_text}")
                    
            elif event.event_type == "ScriptCompleted":
                script_completed = True
                break
        
        # Determine success
        success = script_completed and len(inputs_sent) > 0
        
        return json.dumps(ok(
            message="Script completed" if success else "Script may require manual input",
            data={
                "success": success,
                "file_path": file_path,
                "prompts_seen": prompts_seen,
                "inputs_sent": inputs_sent,
                "current_prompt": ws_client.current_prompt,
                "timeout_reached": asyncio.get_event_loop().time() - start_time >= timeout,
            }
        ))
        
    except Exception as e:
        logger.error(f"Error running interactive Grasshopper: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
async def run_door_script(
    ctx: Context,
    file_path: str,
    height: int = 2200,
    width: int = 910,
    origin: str = "0,0,0",
    plane: str = "WorldXY",
    timeout: float = 60.0,
) -> str:
    """
    Run the Rahmentuer door script with specified parameters.
    
    This is a convenience wrapper around run_grasshopper_interactive
    specifically configured for the Rahmentuer_UD3.gh door script.
    
    Args:
        file_path: Path to the door .gh file
        height: Door height in mm (default: 2200)
        width: Door width in mm (default: 910)
        origin: Origin point as "x,y,z" string (default: "0,0,0")
        plane: Plane selection - WorldXY, WorldYZ, WorldZX (default: WorldXY)
        timeout: Maximum execution time in seconds
    
    Returns:
        JSON with execution status
    
    Example:
        >>> run_door_script(
        ...     file_path="C:/path/to/Rahmentuer_UD3.gh",
        ...     height=2200,
        ...     width=910,
        ...     origin="0,0,0"
        ... )
    
    Notes:
        - The door script expects: height, width, plane selection, origin
        - Uses the interactive WebSocket approach for automation
    """
    # Build the inputs dict for the door script
    inputs = {
        "lichthoehe": str(height),
        "lichtbreite": str(width),
        "getplane.*worldxy.*worldyz": plane,
        "getplane.*parallelgrid": origin,
        "getplane.*undo": "_Enter",  # Rhino command to confirm plane
    }
    
    try:
        # Use the general interactive runner
        ws_client = get_websocket_client()
        
        if not ws_client.is_connected:
            await ws_client.start_listening()
        
        # Clear and run
        ws_client.clear_buffer()
        
        script = f'_-GrasshopperPlayer "{file_path}"'
        logger.info(f"Starting door script: {file_path}")
        logger.info(f"Parameters: height={height}, width={width}, origin={origin}, plane={plane}")
        
        if not await ws_client.run_script(script, wait_for_completion=False):
            return json.dumps(ok(
                message="Failed to start door script",
                data={"success": False}
            ))
        
        # Respond to prompts
        inputs_sent = []
        prompts_seen = []
        
        # Height
        event = await ws_client.wait_for_prompt("lichthoehe", timeout=10.0)
        if event:
            prompts_seen.append(event.text)
            await asyncio.sleep(0.1)
            await ws_client.send_input(str(height))
            inputs_sent.append({"prompt": "height", "value": height})
        else:
            return json.dumps(ok(
                message="Timeout waiting for height prompt",
                data={"success": False, "prompts_seen": prompts_seen}
            ))
        
        # Width
        event = await ws_client.wait_for_prompt("lichtbreite", timeout=5.0)
        if event:
            prompts_seen.append(event.text)
            await asyncio.sleep(0.1)
            await ws_client.send_input(str(width))
            inputs_sent.append({"prompt": "width", "value": width})
        else:
            return json.dumps(ok(
                message="Timeout waiting for width prompt",
                data={"success": False, "prompts_seen": prompts_seen}
            ))
        
        # GetPlane step 1: Plane type
        event = await ws_client.wait_for_prompt("getplane", timeout=5.0)
        if event:
            prompts_seen.append(event.text)
            await asyncio.sleep(0.1)
            await ws_client.send_input(plane)
            inputs_sent.append({"prompt": "plane_type", "value": plane})
        else:
            return json.dumps(ok(
                message="Timeout waiting for GetPlane prompt",
                data={"success": False, "prompts_seen": prompts_seen}
            ))
        
        # GetPlane step 2: Origin
        event = await ws_client.wait_for_prompt("getplane", timeout=5.0)
        if event:
            prompts_seen.append(event.text)
            await asyncio.sleep(0.1)
            await ws_client.send_input(origin)
            inputs_sent.append({"prompt": "origin", "value": origin})
        
        # GetPlane step 3: Confirmation (if any)
        event = await ws_client.wait_for_prompt("getplane", timeout=3.0)
        if event and "undo" in event.text.lower():
            prompts_seen.append(event.text)
            await asyncio.sleep(0.1)
            await ws_client.send_input("_Enter")  # Rhino command to confirm plane
            inputs_sent.append({"prompt": "confirm", "value": ""})
        
        # Wait for script to complete
        await asyncio.sleep(2.0)
        
        return json.dumps(ok(
            message="Door script inputs sent",
            data={
                "success": True,
                "file_path": file_path,
                "parameters": {
                    "height": height,
                    "width": width,
                    "origin": origin,
                    "plane": plane,
                },
                "prompts_seen": prompts_seen,
                "inputs_sent": inputs_sent,
                "current_prompt": ws_client.current_prompt,
                "note": "Check Rhino to verify door creation"
            }
        ))
        
    except Exception as e:
        logger.error(f"Error running door script: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
