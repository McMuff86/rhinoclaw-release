import json
from typing import Any, Dict, List

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp


@mcp.tool()
def delete_object(ctx: Context, id: str = None, name: str = None, all: bool = None) -> str:
    """
    Delete an object from the Rhino document.
    
    Parameters:
    - id: The id of the object to delete
    - name: The name of the object to delete
    """
    try:
        # Get the global connection
        rhino = get_rhino_connection()

        commandParams = {}
        if id is not None:
            commandParams["id"] = id
        if name is not None:
            commandParams["name"] = name
        if all:
            commandParams["all"] = all
        
        result = rhino.send_command("delete_object", commandParams)

        return f"Deleted object: {result['name']}"
    except Exception as e:
        logger.error(f"Error deleting object: {str(e)}")
        return f"Error deleting object: {str(e)}"