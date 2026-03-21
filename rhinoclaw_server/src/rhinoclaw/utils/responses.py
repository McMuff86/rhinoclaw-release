from typing import Any, Dict, Optional

from rhinoclaw.utils.errors import ErrorCode, get_connection_error_code


def ok(message: str = "", data: Optional[Any] = None) -> Dict[str, Any]:
    """Create a success response."""
    return {"success": True, "message": message, "data": data}


def error(
    message: str,
    code: str = ErrorCode.UNKNOWN_ERROR,
    data: Optional[Any] = None
) -> Dict[str, Any]:
    """Create an error response with a structured error code."""
    body: Dict[str, Any] = {"success": False, "message": message, "code": code}
    if data is not None:
        body["data"] = data
    return body


def from_exception(
    exc: Exception,
    code: Optional[str] = None,
    auto_detect: bool = True
) -> Dict[str, Any]:
    """
    Create an error response from an exception.
    
    Args:
        exc: The exception to convert
        code: Explicit error code (takes precedence)
        auto_detect: If True and no code provided, attempt to detect code from exception
    """
    if code is None and auto_detect:
        code = get_connection_error_code(exc)
    elif code is None:
        code = ErrorCode.UNKNOWN_ERROR
    
    return error(str(exc), code=code)


