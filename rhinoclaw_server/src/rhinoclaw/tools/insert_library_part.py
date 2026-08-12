import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.part_library import (
    PartLibraryError,
    get_det_rule,
    get_frame,
    load_part,
    wsl_to_windows_path,
)
from rhinoclaw.utils.part_math import (
    IDENTITY_FRAME,
    det3,
    flatten,
    frames_to_xform,
)
from rhinoclaw.utils.responses import from_exception, ok


@mcp.tool()
def insert_library_part(
    ctx: Context,
    target_frame: List[float],
    part_id: Optional[str] = None,
    block_name: Optional[str] = None,
    file_path: Optional[str] = None,
    source_frame: Optional[List[float]] = None,
    frame_name: str = "insertion",
    attributes: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Insert a block instance with a FULL rigid transform — frame onto frame.

    Unlike insert_block (position/scale/Euler only), this maps a part's
    source frame (block coordinates) onto a target frame (world
    coordinates) via a full 4x4 matrix, so verified placements like the
    Kauls matrix (rotation diag(-1,+1,-1) + translation) are expressible.
    If the block definition is missing in the document, it is imported from
    the part's .3dm file first.

    Frames are 9 doubles [Ox,Oy,Oz, Xx,Xy,Xz, Yx,Yy,Yz]; Z = X cross Y
    (right-handed). The transform is
    plane_to_xform(target) @ inverse(plane_to_xform(source)).

    Parameters:
    - target_frame: Target plane in WORLD coordinates (9 doubles). Required.
    - part_id: Part folder in <RHINOCLAW_LIBRARY_DIR>/parts/, may nest
      (e.g. "kauls/aufnahmeelement-band-stumpf-vx"). When given, block
      name, .3dm path (part.json block.file) and the named source frame
      are read from the part's part.json (and its insertion.det_rule is
      enforced).
    - block_name: Block definition name. Required if no part_id; overrides
      the part.json name when both are given.
    - file_path: Path to a .3dm to import the definition from if missing.
      WSL paths are translated for Rhino on Windows automatically.
    - source_frame: Source plane in BLOCK coordinates (9 doubles, default:
      identity / part.json frame `frame_name`).
    - frame_name: Which part.json frame to use as source (default
      "insertion").
    - attributes: Optional {"name", "layer", "group", "user_strings": {...}}
      applied to the new instance (layer/group are created if missing).

    Returns:
        {"success": true, "data": {"object_id", "det", "bbox",
                                   "definition_created", ...}}

    Examples:
    - insert_library_part(part_id="glutz-5632c",
                          target_frame=[120,45,910, -1,0,0, 0,1,0])
    - insert_library_part(block_name="GLUTZ Topaz 5632C",
                          target_frame=[0,0,0, 1,0,0, 0,1,0],
                          attributes={"layer": "Beschlaege"})
    """
    try:
        if target_frame is None or len(target_frame) != 9:
            raise ValueError(
                "target_frame must be 9 doubles [Ox,Oy,Oz, Xx,Xy,Xz, Yx,Yy,Yz]")
        if source_frame is not None and len(source_frame) != 9:
            raise ValueError(
                "source_frame must be 9 doubles [Ox,Oy,Oz, Xx,Xy,Xz, Yx,Yy,Yz]")
        if not part_id and not block_name:
            raise ValueError("Either part_id or block_name is required")

        det_rule: Optional[str] = None
        if part_id:
            part = load_part(part_id)
            block = part.get("block") or {}
            part_block_name = block.get("name") if isinstance(block, dict) else None
            if not block_name:
                block_name = part_block_name
            if not block_name:
                raise PartLibraryError(
                    f"part.json of '{part_id}' has no block.name — pass block_name explicitly")
            if not file_path:
                file_path = str(part["_part_3dm"])
            if source_frame is None:
                source_frame = get_frame(part, frame_name)
            det_rule = get_det_rule(part)

        if source_frame is None:
            source_frame = list(IDENTITY_FRAME)

        xform = frames_to_xform(target_frame, source_frame)
        det = det3(xform)
        if det_rule == "+1" and det < 0:
            raise ValueError(
                f"Transform violates the part's det_rule '+1': det = {det:.6f} < 0. "
                "The resulting placement would MIRROR the part, which is not "
                "allowed for this part (handing is modeled explicitly). "
                "Fix the target_frame axes instead of mirroring."
            )

        # Rhino runs on Windows — translate WSL paths to UNC/drive paths.
        if file_path:
            file_path = wsl_to_windows_path(file_path)

        rhino = get_rhino_connection()
        params: Dict[str, Any] = {
            "block_name": block_name,
            "xform": flatten(xform),
        }
        if file_path:
            params["file_path"] = file_path
        if attributes:
            params["attributes"] = attributes
        result = rhino.send_command("insert_library_part", params)

        if isinstance(result, dict):
            result.setdefault("det", det)
            if part_id:
                result["part_id"] = part_id
        return json.dumps(ok(
            message=f"Inserted library part '{block_name}' (det = {det:+.3f})",
            data=result,
        ))
    except (ValueError, PartLibraryError) as e:
        logger.error(f"Error inserting library part: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error inserting library part: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
