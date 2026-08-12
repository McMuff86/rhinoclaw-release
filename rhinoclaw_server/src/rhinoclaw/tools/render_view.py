import json
from typing import Literal, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.image_storage import (
    confirm_rhino_host_save,
    get_screenshots_dir,
    resolve_image_destination,
    save_server_png,
    validate_image_dimensions,
)
from rhinoclaw.utils.responses import from_exception, ok
from rhinoclaw.utils.viewports import resolved_viewport_label, viewport_params

RenderDisplayMode = Literal["rendered", "raytraced"]


@mcp.tool()
def render_view(
    ctx: Context,
    viewport_name: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    filename: Optional[str] = None,
    display_mode: RenderDisplayMode = "rendered"
) -> str:
    """
    Render the current viewport to an image.

    Relative filenames and POSIX absolute paths are saved as PNG files by the
    MCP server from Rhino's base64 response. Absolute Windows and UNC paths are
    saved directly by the Rhino host and may use PNG, JPG, or JPEG.

    Parameters:
    - viewport_name: Optional localized name, GUID, or `Layout::Detail`.
      Omit it to render Rhino's active view. A detail target captures its
      complete owning layout page; `capture_scope` reports that explicitly.
    - width: Render width in pixels (requires height)
    - height: Render height in pixels (requires width)
    - filename: Optional output path (if omitted, returns base64 data).
      Relative paths stay below screenshots/. Server-local output must be PNG.
    - display_mode: Display mode to render ("rendered", "raytraced")

    Returns:
    Success message with image data or file path
    """
    if (width is None) != (height is None):
        return json.dumps(from_exception(
            ValueError("width and height must be provided together"),
            code=ErrorCode.INVALID_PARAMS
        ))

    if width is not None and height is not None:
        try:
            validate_image_dimensions(width, height)
        except ValueError as exc:
            return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))

    display_mode = display_mode.lower()
    if display_mode not in ("rendered", "raytraced"):
        return json.dumps(from_exception(
            ValueError("display_mode must be one of: rendered, raytraced"),
            code=ErrorCode.INVALID_PARAMS
        ))

    destination = None
    if filename is not None:
        try:
            destination = resolve_image_destination(filename, get_screenshots_dir())
        except ValueError as exc:
            return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))

    try:
        rhino = get_rhino_connection()
        params = viewport_params({
            "display_mode": display_mode,
            # Only fully-qualified Windows/UNC paths are meaningful to Rhino.
            # Local and relative targets deliberately request a base64 PNG.
            "filename": destination.rhino_path if destination else None,
        }, viewport_name)

        if width is not None:
            params["width"] = width
            params["height"] = height

        result = rhino.send_command("render_view", params)
        resolved = resolved_viewport_label(result, viewport_name)
        if destination is not None and destination.server_path is not None:
            result = save_server_png(result, destination.server_path)
        elif destination is not None and destination.rhino_path is not None:
            result = confirm_rhino_host_save(result, destination.rhino_path)

        if result.get("capture_scope") == "layout_page":
            captured_view = result.get("captured_view", resolved)
            message = (
                f"Rendered layout page '{captured_view}' "
                f"for target '{resolved}'"
            )
        else:
            message = f"Rendered viewport '{resolved}'"
        if result.get("saved_to_file"):
            save_location = result.get("save_location")
            location_label = (
                "MCP server" if save_location == "mcp_server" else "Rhino host"
            )
            message += f" - saved on {location_label} to {result['saved_to_file']}"

        return json.dumps(ok(message=message, data=result))
    except Exception as e:
        logger.error(f"Error rendering viewport: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
