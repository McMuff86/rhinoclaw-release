import json
from typing import Any, Dict, List, Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

FilterType = Literal["and", "or"]

@mcp.tool()
def select_objects(
    ctx: Context,
    filters: Optional[Dict[str, List[Any]]] = None,
    filters_type: FilterType = "and",
) -> str:
    """
    Select objects in the Rhino document.
    
    Parameters:
    - filters: A dictionary containing the filters. The filters parameter is necessary, unless it's empty, in which case all objects will be selected.
    - filters_type: The type of the filters, it's "and" or "or", default is "and"

    Note:
    The filter value is always a list, even if it's a single value. The reason is that a filter can contain multiple values, for example when we query by a attribute that has EITHER value1 OR value2.

    The filters dictionary can contain the following keys:
    - name: The name of the object
    - color: The color of the object, for example [255, 0, 0]

    Additionaly, rhino allows to have user custom attributes, which can be used to filters the objects.
    For example, if the object has a user custom attribute called "category", the filters dictionary can contain:
    - category: custom_attribute_value

    Example:
    filters = {
        "name": ["object_name1", "object_name2"],
        "category": ["custom_attribute_value"]
    },
    filters_type = "or"
    

    Returns:
        {"success": true, "message": "Selected N objects", "data": {"count": N}}
    """
    try:
        # Get the global connection
        rhino = get_rhino_connection()
        command_params = {
            "filters": filters if filters is not None else {},
            "filters_type": filters_type
        }

        result = rhino.send_command("select_objects", command_params)
          
        return json.dumps(ok(
            message=f"Selected {result['count']} objects",
            data={"count": result['count']}
        ))
    except Exception as e:
        logger.error(f"Error selecting objects: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))

