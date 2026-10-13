"""Shared, cross-OS storage mechanics for viewport images."""

import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Optional


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_IMAGE_DIMENSION = 16_384
MAX_IMAGE_PIXELS = 33_177_600
RHINO_HOST_EXTENSIONS = {".png", ".jpg", ".jpeg"}
WINDOWS_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
    "COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³",
}
WINDOWS_DEVICE_PREFIXES = ("\\\\?\\", "\\\\.\\")


def validate_image_dimensions(width: int, height: int) -> None:
    """Validate one bounded image allocation for capture and render."""
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
    ):
        raise ValueError("width and height must be integers")
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise ValueError(
            "width and height must not exceed "
            f"{MAX_IMAGE_DIMENSION} pixels per dimension"
        )
    if width * height > MAX_IMAGE_PIXELS:
        raise ValueError(f"image exceeds the {MAX_IMAGE_PIXELS}-pixel budget")


@dataclass(frozen=True)
class ImageDestination:
    """Exactly one side of the Rhino/MCP storage boundary."""

    server_path: Optional[Path] = None
    rhino_path: Optional[str] = None

    def __post_init__(self) -> None:
        if (self.server_path is None) == (self.rhino_path is None):
            raise ValueError("An image destination must select exactly one storage side")


def get_screenshots_dir() -> Path:
    """Return the repository-local screenshot directory."""
    server_root = Path(__file__).resolve().parents[4]
    return server_root / "screenshots"


def slugify_image_label(label: str) -> str:
    """Return a compact filename component that is valid on Windows too."""
    normalized = unicodedata.normalize("NFKD", label)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_name)
    slug = re.sub(r"_+", "_", slug).strip(" ._-")
    if not slug:
        slug = "ActiveView"
    if slug.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
        slug = f"view_{slug}"
    return slug[:80].rstrip(" .") or "ActiveView"


def auto_png_destination(
    label: str,
    directory: Optional[Path] = None,
    prefix: str = "viewport",
) -> Path:
    """Build a collision-resistant server-local PNG destination."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    slug = slugify_image_label(label)
    target_dir = directory if directory is not None else get_screenshots_dir()
    return target_dir / f"{prefix}_{slug}_{timestamp}.png"


def _with_default_extension(filename: str) -> str:
    if not PureWindowsPath(filename).suffix:
        return f"{filename}.png"
    return filename


def _is_windows_or_unc_absolute(filename: str) -> bool:
    if re.match(r"^[A-Za-z]:[/\\]", filename):
        return True
    return filename.startswith(("\\\\", "//")) and PureWindowsPath(
        filename
    ).is_absolute()


def _validate_windows_component(component: str) -> None:
    if not component or component in {".", ".."}:
        raise ValueError("Windows image paths cannot contain '.', '..', or empty components")
    if WINDOWS_INVALID_CHARS.search(component) or component.endswith((" ", ".")):
        raise ValueError(f"Unsafe Windows image path component: {component!r}")
    if component.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
        raise ValueError(f"Reserved Windows filename in image path: {component!r}")


def validate_rhino_host_image_path(filename: str) -> str:
    """Validate an absolute image path before it crosses to the Rhino host."""
    normalized = filename.replace("/", "\\")
    if normalized.startswith(WINDOWS_DEVICE_PREFIXES):
        raise ValueError("Windows device namespace paths are not allowed")

    path = PureWindowsPath(filename)
    if not path.is_absolute():
        raise ValueError("Rhino-host image paths must be absolute Windows or UNC paths")

    if path.drive.startswith("\\\\"):
        unc_parts = path.drive.lstrip("\\").split("\\")
        if len(unc_parts) != 2:
            raise ValueError("UNC image paths require both a server and share")
        for component in unc_parts:
            _validate_windows_component(component)
    elif not re.fullmatch(r"[A-Za-z]:", path.drive):
        raise ValueError("Rhino-host image paths require a drive root or UNC share")

    anchor = str(path.anchor).replace("/", "\\")
    relative = normalized[len(anchor):]
    file_parts = relative.split("\\")
    if not relative or any(not component for component in file_parts):
        raise ValueError("Rhino-host image path must include a filename")
    for component in file_parts:
        _validate_windows_component(component)

    extension = path.suffix.lower()
    if extension not in RHINO_HOST_EXTENSIONS:
        supported = ", ".join(sorted(RHINO_HOST_EXTENSIONS))
        raise ValueError(f"Rhino-host images require one of: {supported}")
    return filename


def resolve_image_destination(
    filename: str,
    relative_directory: Optional[Path] = None,
) -> ImageDestination:
    """Route an explicit filename to MCP-server or Rhino-host storage."""
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("filename must be a non-empty path")
    if "\x00" in filename:
        raise ValueError("filename cannot contain NUL characters")

    filename = _with_default_extension(filename)
    if _is_windows_or_unc_absolute(filename):
        return ImageDestination(
            rhino_path=validate_rhino_host_image_path(filename),
        )

    local_path = Path(filename)
    if local_path.suffix.lower() != ".png":
        raise ValueError("MCP-server images are PNG; use a .png filename")
    if local_path.is_absolute():
        return ImageDestination(server_path=local_path)

    raw_parts = filename.replace("\\", "/").split("/")
    for component in raw_parts:
        _validate_windows_component(component)

    screenshots_dir = (
        relative_directory if relative_directory is not None else get_screenshots_dir()
    ).resolve()
    destination = screenshots_dir.joinpath(*raw_parts).resolve()
    try:
        destination.relative_to(screenshots_dir)
    except ValueError as exc:
        raise ValueError("Relative image path escapes the screenshots directory") from exc
    return ImageDestination(server_path=destination)


def save_server_png(result: dict, destination: Path) -> dict:
    """Decode a plugin PNG response and return truthful server-save metadata."""
    image_data = result.get("image_data")
    if not isinstance(image_data, str) or not image_data:
        raise RuntimeError("Rhino did not return image_data for the server-local image")
    try:
        image_bytes = base64.b64decode(image_data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("Rhino returned invalid base64 image data") from exc
    if not image_bytes.startswith(PNG_SIGNATURE):
        raise RuntimeError("Rhino returned image data that is not a PNG")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(image_bytes)

    saved_result = dict(result)
    saved_result.pop("image_data", None)
    saved_result.update({
        "saved_to_file": str(destination),
        "save_location": "mcp_server",
        "format": "png",
        "bytes_written": len(image_bytes),
    })
    return saved_result


def confirm_rhino_host_save(result: dict, requested_path: str) -> dict:
    """Verify a host save response and add consistent location metadata."""
    saved_path = result.get("saved_to_file")
    if not isinstance(saved_path, str) or not saved_path:
        raise RuntimeError("Rhino did not confirm the requested host-side image save")
    validate_rhino_host_image_path(saved_path)

    extension = PureWindowsPath(saved_path).suffix.lower()
    saved_result = dict(result)
    saved_result["save_location"] = "rhino_host"
    saved_result["format"] = "png" if extension == ".png" else "jpeg"
    if saved_path != requested_path:
        saved_result["requested_filename"] = requested_path
    return saved_result
