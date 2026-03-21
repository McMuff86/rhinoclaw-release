import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok

def get_screenshots_dir() -> Path:
    """Get the screenshots directory path (project root/screenshots)."""
    # Path: tools/capture_viewport.py -> tools -> rhinoclaw -> src -> rhinoclaw_server
    # __file__ = .../src/rhinoclaw/tools/capture_viewport.py
    # parent = .../src/rhinoclaw/tools
    # parent.parent = .../src/rhinoclaw
    # parent.parent.parent = .../src
    # parent.parent.parent.parent = .../rhinoclaw_server
    # parent.parent.parent.parent.parent = .../rhinoclaw (project root)
    server_root = Path(__file__).parent.parent.parent.parent.parent
    screenshots_dir = server_root / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    return screenshots_dir

@mcp.tool()
def capture_viewport(
    ctx: Context,
    viewport_name: str = "Perspective",
    width: int = 1920,
    height: int = 1080,
    filename: Optional[str] = None,
    auto_save: bool = True
) -> str:
    """
    Capture the current viewport as an image.
    
    If filename is not provided and auto_save is True, automatically saves to screenshots/
    directory with timestamp. If filename is provided without a path, saves to screenshots/
    directory. If filename contains a full path, uses that path.

    Parameters:
    - viewport_name: Name of the viewport to capture (default: "Perspective")
    - width: Image width in pixels (default: 1920)
    - height: Image height in pixels (default: 1080)
    - filename: Optional filename to save the image. If None and auto_save=True, auto-generates filename.
                If relative path, saves to screenshots/ directory. If absolute path, uses that path.
    - auto_save: If True and filename is None, automatically saves to screenshots/ with timestamp (default: True)

    Returns:
    Success message with image data or file path

    Examples:
    - capture_viewport() - Auto-save to screenshots/viewport_Perspective_20240101_120000.png
    - capture_viewport(viewport_name="Top", width=1024, height=768) - Auto-save top view
    - capture_viewport(filename="my_screenshot.png") - Save to screenshots/my_screenshot.png
    - capture_viewport(filename="C:/full/path/screenshot.png") - Save to absolute path
    - capture_viewport(auto_save=False) - Return base64 data instead of saving
    """
    try:
        rhino = get_rhino_connection()

        if width <= 0 or height <= 0:
            return json.dumps(from_exception(
                ValueError("Width and height must be positive"),
                code=ErrorCode.INVALID_PARAMS
            ))

        # Handle filename logic
        final_filename = None
        if filename is None and auto_save:
            # Auto-generate filename with timestamp
            screenshots_dir = get_screenshots_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_viewport_name = viewport_name.replace(" ", "_").replace("/", "_")
            final_filename = str(screenshots_dir / f"viewport_{safe_viewport_name}_{timestamp}.png")
        elif filename is not None:
            # Check if filename is absolute path
            file_path = Path(filename)
            if file_path.is_absolute():
                # Use absolute path as-is
                final_filename = str(file_path)
            else:
                # Relative path - save to screenshots directory
                screenshots_dir = get_screenshots_dir()
                final_filename = str(screenshots_dir / filename)

        result = rhino.send_command("capture_viewport", {
            "viewport_name": viewport_name,
            "width": width,
            "height": height,
            "filename": final_filename
        })

        message = f"Viewport '{viewport_name}' captured ({width}x{height})"
        if final_filename:
            message += f" - saved to {final_filename}"

        return json.dumps(ok(
            message=message,
            data=result
        ))
    except Exception as e:
        logger.error(f"Error capturing viewport: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))