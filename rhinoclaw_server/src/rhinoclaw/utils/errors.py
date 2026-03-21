"""
Structured error codes for RhinoClaw.

Use these constants when returning error responses to enable programmatic error handling.
"""


class ErrorCode:
    """Error code constants for consistent error handling across RhinoClaw."""

    # Connection errors (1xx range conceptually)
    CONNECTION_ERROR = "CONNECTION_ERROR"
    CONNECTION_TIMEOUT = "CONNECTION_TIMEOUT"
    CONNECTION_REFUSED = "CONNECTION_REFUSED"

    # Validation errors (2xx range conceptually)
    INVALID_PARAMS = "INVALID_PARAMS"
    MISSING_PARAMS = "MISSING_PARAMS"
    INVALID_TYPE = "INVALID_TYPE"
    INVALID_ID = "INVALID_ID"

    # Rhino errors (3xx range conceptually)
    RHINO_ERROR = "RHINO_ERROR"
    RHINO_COMMAND_FAILED = "RHINO_COMMAND_FAILED"
    RHINO_OBJECT_NOT_FOUND = "RHINO_OBJECT_NOT_FOUND"
    RHINO_LAYER_NOT_FOUND = "RHINO_LAYER_NOT_FOUND"
    RHINO_MATERIAL_NOT_FOUND = "RHINO_MATERIAL_NOT_FOUND"

    # Document errors (4xx range conceptually)
    DOC_INFO_ERROR = "DOC_INFO_ERROR"
    DOC_NOT_OPEN = "DOC_NOT_OPEN"

    # Script execution errors (5xx range conceptually)
    SCRIPT_ERROR = "SCRIPT_ERROR"
    SCRIPT_TIMEOUT = "SCRIPT_TIMEOUT"

    # Object operation errors (6xx range conceptually)
    CREATE_OBJECT_ERROR = "CREATE_OBJECT_ERROR"
    MODIFY_OBJECT_ERROR = "MODIFY_OBJECT_ERROR"
    DELETE_OBJECT_ERROR = "DELETE_OBJECT_ERROR"
    SELECT_OBJECT_ERROR = "SELECT_OBJECT_ERROR"

    # Layer operation errors (7xx range conceptually)
    CREATE_LAYER_ERROR = "CREATE_LAYER_ERROR"
    DELETE_LAYER_ERROR = "DELETE_LAYER_ERROR"

    # Material operation errors (8xx range conceptually)
    CREATE_MATERIAL_ERROR = "CREATE_MATERIAL_ERROR"
    ASSIGN_MATERIAL_ERROR = "ASSIGN_MATERIAL_ERROR"

    # Generic errors
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def get_connection_error_code(exception: Exception) -> str:
    """Determine the appropriate error code based on exception type."""
    exc_str = str(exception).lower()
    
    if "timeout" in exc_str:
        return ErrorCode.CONNECTION_TIMEOUT
    elif "refused" in exc_str or "connect" in exc_str:
        return ErrorCode.CONNECTION_REFUSED
    elif "connection" in exc_str:
        return ErrorCode.CONNECTION_ERROR
    
    return ErrorCode.UNKNOWN_ERROR
