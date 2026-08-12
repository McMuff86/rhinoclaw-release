"""File-based part library access (door hardware etc.) — shared plumbing.

Library layout (see the reference implementation in
``~/projects/rhino-part-library``):

    <RHINOCLAW_LIBRARY_DIR>/
        catalog.json                  {"meta": {...}, "parts": [{...}]}
        parts/<part_id>/<block.file>  manufacturer block .3dm (part_id may
                                      nest, e.g. kauls/aufnahmeelement-...)
        parts/<part_id>/part.json     insertion semantics:
            {"block": {"name": ...},
             "frames": [{"name": "insertion", "plane": [9 doubles]}] or
                       {"insertion": [9 doubles], ...},
             "insertion": {"det_rule": "+1"},
             "verification": {...}}

Frames are 9-double planes [Ox,Oy,Oz, Xx,Xy,Xz, Yx,Yy,Yz] in block
coordinates. This module is I/O + path plumbing only; the matrix math lives
in :mod:`rhinoclaw.utils.part_math`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from rhinoclaw.config import get_settings

LIBRARY_HINT = (
    "Set RHINOCLAW_LIBRARY_DIR to the part-library root "
    "(the folder containing catalog.json and parts/<part_id>/), "
    "e.g. RHINOCLAW_LIBRARY_DIR=~/projects/rhino-part-library."
)


class PartLibraryError(Exception):
    """Part library not configured / not found / malformed."""


def get_library_dir() -> Path:
    """Resolve the configured library root or raise with a setup hint."""
    lib = get_settings().library_dir
    if lib is None:
        raise PartLibraryError(f"RHINOCLAW_LIBRARY_DIR is not set. {LIBRARY_HINT}")
    if not lib.is_dir():
        raise PartLibraryError(
            f"RHINOCLAW_LIBRARY_DIR points to '{lib}', which does not exist. {LIBRARY_HINT}"
        )
    return lib


def load_catalog() -> Dict[str, Any]:
    """Load ``catalog.json``. Tolerant: guarantees a ``parts`` list."""
    path = get_library_dir() / "catalog.json"
    if not path.is_file():
        raise PartLibraryError(f"catalog.json not found in library: {path}. {LIBRARY_HINT}")
    with open(path, encoding="utf-8") as f:
        catalog = json.load(f)
    if not isinstance(catalog, dict):
        raise PartLibraryError(f"catalog.json must be a JSON object: {path}")
    parts = catalog.get("parts")
    catalog["parts"] = parts if isinstance(parts, list) else []
    return catalog


def load_part(part_id: str) -> Dict[str, Any]:
    """Load ``parts/<part_id>/part.json`` and resolve the block's .3dm path.

    ``part_id`` may contain forward slashes for vendor subfolders
    (e.g. ``kauls/aufnahmeelement-band-stumpf-vx``); each segment is
    validated so the id cannot escape the parts/ tree. The .3dm filename
    comes from ``block.file`` in part.json (reference schema), with
    ``part.3dm`` as the fallback.

    Returns the parsed part.json with two extra keys:
    ``_part_dir`` (Path) and ``_part_3dm`` (Path, may not exist yet).
    """
    segments = [s for s in (part_id or "").split("/")]
    if (not part_id or "\\" in part_id
            or any(s in ("", ".", "..") for s in segments)):
        raise PartLibraryError(f"Invalid part_id: '{part_id}'")
    part_dir = get_library_dir() / "parts"
    for segment in segments:
        part_dir = part_dir / segment
    part_json = part_dir / "part.json"
    if not part_json.is_file():
        raise PartLibraryError(
            f"Part '{part_id}' not found: no {part_json}. "
            "Use find_library_part to list available parts."
        )
    with open(part_json, encoding="utf-8") as f:
        part = json.load(f)
    if not isinstance(part, dict):
        raise PartLibraryError(f"part.json must be a JSON object: {part_json}")
    block = part.get("block")
    block_file = None
    if isinstance(block, dict):
        block_file = block.get("file")
    if block_file and ("/" in block_file or "\\" in block_file or ".." in block_file):
        raise PartLibraryError(
            f"block.file must be a plain filename inside the part folder, got: '{block_file}'")
    part["_part_dir"] = part_dir
    part["_part_3dm"] = part_dir / (block_file or "part.3dm")
    return part


def get_frame(part: Dict[str, Any], frame_name: str) -> List[float]:
    """Extract a named 9-double frame from part.json.

    Tolerates both shapes: ``frames`` as a list of
    ``{"name": ..., "plane": [9]}`` objects, or as a dict
    ``{name: [9 doubles]}``.
    """
    frames = part.get("frames")
    plane: Optional[Any] = None
    available: List[str] = []
    if isinstance(frames, dict):
        available = sorted(frames.keys())
        plane = frames.get(frame_name)
    elif isinstance(frames, list):
        for entry in frames:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if name:
                available.append(name)
            if name == frame_name:
                plane = entry.get("plane") or entry.get("frame")
    if plane is None:
        raise PartLibraryError(
            f"Frame '{frame_name}' not found in part.json "
            f"(available: {available or 'none'})"
        )
    if not isinstance(plane, list) or len(plane) != 9:
        raise PartLibraryError(
            f"Frame '{frame_name}' must be 9 doubles [Ox,Oy,Oz, Xx,Xy,Xz, Yx,Yy,Yz], "
            f"got: {plane!r}"
        )
    return [float(v) for v in plane]


def get_det_rule(part: Dict[str, Any]) -> Optional[str]:
    """``insertion.det_rule`` from part.json (e.g. "+1"), or None."""
    insertion = part.get("insertion")
    if isinstance(insertion, dict):
        rule = insertion.get("det_rule")
        if rule is not None:
            return str(rule)
    return None


def wsl_to_windows_path(path: str) -> str:
    """Translate a WSL path to something Rhino on Windows can open.

    - ``/mnt/c/foo/bar``      -> ``C:\\foo\\bar``
    - ``/home/user/x.3dm``    -> ``\\\\path\to\your\directory
    - ``C:\\...`` / ``\\\\server\\...`` -> unchanged (already a Windows path)

    The distro name comes from ``$WSL_DISTRO_NAME`` (fallback "Ubuntu").
    On native Windows (``os.name == "nt"``) paths pass through unchanged.
    """
    if not path:
        return path
    # Already Windows-shaped? (drive letter or UNC)
    if re.match(r"^[A-Za-z]:[\\/]", path) or path.startswith("\\\\"):
        return path
    if os.name == "nt" or not path.startswith("/"):
        return path
    m = re.match(r"^/mnt/([a-zA-Z])(/.*)?$", path)
    if m:
        drive = m.group(1).upper()
        rest = (m.group(2) or "").replace("/", "\\")
        return f"{drive}:{rest}" if rest else f"{drive}:\\"
    distro = os.environ.get("WSL_DISTRO_NAME") or "Ubuntu"
    return f"\\\\path\to\your\directory" + path.replace("/", "\\")
