import json
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.image_storage import (
    ImageDestination,
    auto_png_destination,
    confirm_rhino_host_save,
    get_screenshots_dir,
    resolve_image_destination,
    save_server_png,
    validate_image_dimensions,
)
from rhinoclaw.utils.responses import from_exception, ok
from rhinoclaw.utils.viewports import resolved_viewport_label, viewport_params


@mcp.tool()
def capture_viewport(
    ctx: Context,
    viewport_name: Optional[str] = None,
    width: int = 1920,
    height: int = 1080,
    filename: Optional[str] = None,
    auto_save: bool = True
) -> str:
    """
    Capture the current viewport as an image.
    
    If filename is not provided and auto_save is True, automatically saves to the MCP
    server's screenshots/ directory with a timestamp. Relative filenames and POSIX
    absolute paths are also written by the MCP server from Rhino's base64 PNG response.
    Absolute Windows and UNC paths are written directly by the Rhino host.

    Parameters:
    - viewport_name: Optional localized name, GUID, or `Layout::Detail`.
      Omit it to capture Rhino's active view. A detail target captures its
      owning layout view, with the detail identified in the response.
    - width: Image width in pixels (default: 1920)
    - height: Image height in pixels (default: 1080)
    - filename: Optional filename to save the image. If None and auto_save=True, auto-generates a PNG filename.
                Relative paths stay below screenshots/. Server-local captures must use PNG;
                Windows/UNC host paths may use PNG, JPG, or JPEG.
    - auto_save: If True and filename is None, automatically saves to screenshots/ with timestamp (default: True)

    Returns:
    Success message with image data or file path

    Examples:
    - capture_viewport() - Auto-save the active view with a timestamp
    - capture_viewport(viewport_name="Top", width=1024, height=768) - Auto-save top view
    - capture_viewport(filename="my_screenshot.png") - Save to screenshots/my_screenshot.png
    - capture_viewport(filename="C:/full/path/screenshot.png") - Save to absolute path
    - capture_viewport(auto_save=False) - Return base64 data instead of saving
    """
    try:
        validate_image_dimensions(width, height)
    except ValueError as exc:
        return json.dumps(from_exception(
            exc,
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

        result = rhino.send_command(
            "capture_viewport",
            viewport_params({
                "width": width,
                "height": height,
                # Only paths meaningful to the Windows Rhino process cross TCP.
                # Server-local destinations deliberately request base64 instead.
                "filename": destination.rhino_path if destination else None,
            }, viewport_name),
        )
        resolved = resolved_viewport_label(result, viewport_name)

        if filename is None and auto_save:
            destination = ImageDestination(
                server_path=auto_png_destination(
                    resolved,
                    get_screenshots_dir(),
                ),
            )
        if destination is not None and destination.server_path is not None:
            result = save_server_png(result, destination.server_path)
        elif destination is not None and destination.rhino_path is not None:
            result = confirm_rhino_host_save(result, destination.rhino_path)

        if result.get("capture_scope") == "layout_page":
            captured_view = result.get("captured_view", resolved)
            message = (
                f"Layout page '{captured_view}' captured for target "
                f"'{resolved}' ({width}x{height})"
            )
        else:
            message = f"Viewport '{resolved}' captured ({width}x{height})"
        if result.get("saved_to_file"):
            save_location = result.get("save_location")
            location_label = "MCP server" if save_location == "mcp_server" else "Rhino host"
            message += f" - saved on {location_label} to {result['saved_to_file']}"

        return json.dumps(ok(
            message=message,
            data=result
        ))
    except Exception as e:
        logger.error(f"Error capturing viewport: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
