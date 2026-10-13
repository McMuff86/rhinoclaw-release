"""Shared MCP-side helpers for viewport targeting and response labels."""

from typing import Any, Dict, Optional

from rhinoclaw.utils.errors import ErrorCode, RhinoCommandError


def viewport_params(
    params: Dict[str, Any],
    viewport_name: Optional[str],
) -> Dict[str, Any]:
    """Return command params with an explicit viewport only when requested.

    Omitting ``viewport_name`` is meaningful: the Rhino plugin resolves it to
    the active viewport, including an active detail on a layout page.
    """
    result = dict(params)
    if viewport_name is not None and viewport_name.strip():
        result["viewport_name"] = viewport_name.strip()
    return result


def resolved_viewport_label(
    result: Dict[str, Any],
    requested_name: Optional[str],
) -> str:
    """Prefer the plugin's localized/qualified name in user-facing messages."""
    resolved = result.get("viewport") if isinstance(result, dict) else None
    return str(resolved or requested_name or "ActiveView")


def require_verified_viewport_mutation(
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Require native post-commit evidence for a viewport mutation.

    The TCP envelope only proves that the C# handler returned. Viewport
    handlers therefore carry an inner status plus RhinoViewport readback and
    verified rollback evidence. Convert an inner failure to the same
    structured exception used for transport-level Rhino errors.
    """
    if not isinstance(result, dict):
        raise RhinoCommandError(
            "Viewport mutation response was not an object",
            error_code=ErrorCode.VERIFICATION_FAILED,
        )

    if result.get("status") != "success":
        raise RhinoCommandError(
            str(result.get("message") or "Viewport mutation failed"),
            error_code=str(
                result.get("code") or ErrorCode.VERIFICATION_FAILED
            ),
            response=result,
        )

    verification = result.get("verification")
    if not isinstance(verification, dict) or verification.get("pass") is not True:
        raise RhinoCommandError(
            "Viewport mutation lacked passing post-commit verification",
            error_code=ErrorCode.VERIFICATION_FAILED,
            response=result,
        )
    return result
