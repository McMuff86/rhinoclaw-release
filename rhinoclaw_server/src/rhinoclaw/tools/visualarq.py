"""VisualARQ BIM tools (NEXT-LEVEL-PLAN 4.1) — walls, doors, levels, IFC.

Every tool degrades gracefully when VisualARQ is not installed: the
response carries `available: false` plus a hint instead of crashing.
Check `va_status` first.
"""
import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import error, from_exception, ok
from rhinoclaw.utils.visualarq import run_va, va_unavailable

_UNAVAILABLE_HINT = (
    "VisualARQ is not loaded in the connected Rhino. Install/enable the "
    "VisualARQ plugin (visualarq.com), restart Rhino, then re-run va_status."
)


def _respond(result: Dict[str, Any], success_message: str) -> str:
    if va_unavailable(result):
        return json.dumps(error(
            _UNAVAILABLE_HINT, code=ErrorCode.RHINO_ERROR,
            data={"available": False},
        ))
    if result.get("status") == "error":
        return json.dumps(error(
            result.get("message", "VisualARQ operation failed"),
            code=ErrorCode.RHINO_ERROR, data=result,
        ))
    return json.dumps(ok(message=success_message, data=result))


@mcp.tool()
def va_status(ctx: Context) -> str:
    """Check VisualARQ availability and document BIM inventory.

    Run this BEFORE other `va_*` tools. Reports whether the VisualARQ
    plugin is loaded plus style/level counts of the active document.

    Returns:
        {"success": true, "data": {"available": true,
            "wall_styles": 4, "door_styles": 6, "window_styles": 5,
            "levels": 2}}
        or {"success": true, "data": {"available": false, "hint": "..."}}.
    """
    try:
        rhino = get_rhino_connection()
        result = run_va(rhino, """
def safe(fn):
    try:
        return fn()
    except Exception:
        return None
def count_levels():
    if hasattr(va, "GetAllLevelIds"):
        return len(va.GetAllLevelIds() or [])
    n = 0
    for bid in (va.GetAllBuildingIds() or []):
        n += len(va.GetBuildingLevelIds(bid) or [])
    return n
result = {
    "available": True,
    "wall_styles": safe(lambda: len(va.GetAllWallStyleIds() or [])),
    "door_styles": safe(lambda: len(va.GetAllDoorStyleIds() or [])),
    "window_styles": safe(lambda: len(va.GetAllWindowStyleIds() or [])),
    "levels": safe(count_levels),
    "buildings": safe(lambda: len(va.GetAllBuildingIds() or [])),
}
""")
        if va_unavailable(result):
            # Status is a *query*: not-installed is an answer, not an error.
            return json.dumps(ok(
                message="VisualARQ not available",
                data={"available": False, "hint": _UNAVAILABLE_HINT},
            ))
        return json.dumps(ok(
            message=f"VisualARQ available — {result.get('wall_styles')} wall / "
                    f"{result.get('door_styles')} door styles, "
                    f"{result.get('levels')} levels",
            data=result,
        ))
    except Exception as e:
        logger.error(f"Error checking VisualARQ status: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_list_styles(ctx: Context, kind: str = "wall") -> str:
    """List VisualARQ styles of a kind: "wall", "door", or "window".

    Returns:
        {"success": true, "data": {"kind": "door",
            "styles": [{"id": "...", "name": "Door 80x210"}, ...]}}
    """
    if kind not in ("wall", "door", "window"):
        return json.dumps(from_exception(
            ValueError("kind must be 'wall', 'door' or 'window'"),
            code=ErrorCode.INVALID_PARAMS))
    try:
        rhino = get_rhino_connection()
        result = run_va(rhino, """
kind = params["kind"]
if kind == "wall":
    ids = va.GetAllWallStyleIds()
elif kind == "door":
    ids = va.GetAllDoorStyleIds()
else:
    ids = va.GetAllWindowStyleIds()
# VA API drift: newer builds expose the generic GetStyleName, older ones
# per-type Get<Kind>StyleName.
def style_name(sid):
    if hasattr(va, "GetStyleName"):
        return va.GetStyleName(sid)
    return getattr(va, "Get" + kind.capitalize() + "StyleName")(sid)
styles = []
for sid in (ids or []):
    styles.append({"id": str(sid), "name": style_name(sid)})
result = {"status": "success", "kind": kind, "styles": styles}
""", {"kind": kind})
        return _respond(
            result,
            f"{len(result.get('styles', []))} {kind} style(s)",
        )
    except Exception as e:
        logger.error(f"Error listing VisualARQ styles: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_create_wall(
    ctx: Context,
    style: str,
    start: List[float],
    end: List[float],
    height: float,
) -> str:
    """Create a VisualARQ wall (a real BIM element, not a box).

    Parameters:
    - style: Wall style name (see `va_list_styles(kind="wall")`).
    - start / end: [x, y, z] of the wall axis at its base.
    - height: Wall height in document units.

    Returns:
        {"success": true, "data": {"wall_id": "...", "style": "...",
            "height": 2400}}

    Doors/windows are inserted into the wall afterwards via
    `va_create_door` with this `wall_id`.
    """
    try:
        if not (isinstance(start, list) and isinstance(end, list)
                and len(start) == 3 and len(end) == 3):
            raise ValueError("start and end must be [x, y, z]")
        rhino = get_rhino_connection()
        result = run_va(rhino, """
def style_name(sid):
    if hasattr(va, "GetStyleName"):
        return va.GetStyleName(sid)
    return va.GetWallStyleName(sid)
style_id = None
for ws_id in (va.GetAllWallStyleIds() or []):
    if style_name(ws_id) == params["style"]:
        style_id = ws_id
        break
if style_id is None:
    result = {"status": "error",
              "message": "Wall style not found: " + params["style"]}
else:
    s = params["start"]; e = params["end"]
    sp = rg.Point3d(s[0], s[1], s[2])
    ep = rg.Point3d(e[0], e[1], e[2])
    # API drift: newer VA = AddWall(styleId, start, end) + SetWallHeight;
    # older VA = AddWall(start, end, height, styleId).
    if "styleId" in str(va.AddWall.__doc__ or "").split(",")[0]:
        wall_id = va.AddWall(style_id, sp, ep)
        if wall_id != Guid.Empty and params.get("height") and hasattr(va, "SetWallHeight"):
            va.SetWallHeight(wall_id, params["height"])
    else:
        wall_id = va.AddWall(sp, ep, params["height"], style_id)
    if wall_id != Guid.Empty:
        result = {"status": "success", "wall_id": str(wall_id),
                  "style": params["style"], "height": params["height"]}
    else:
        result = {"status": "error", "message": "AddWall returned empty Guid"}
""", {"style": style, "start": start, "end": end, "height": height})
        return _respond(result, f"Wall created: {result.get('wall_id')}")
    except Exception as e:
        logger.error(f"Error creating VisualARQ wall: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_create_door(
    ctx: Context,
    style: str,
    point: Optional[List[float]] = None,
    rotation: float = 0.0,
    wall_id: Optional[str] = None,
    position: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
) -> str:
    """Insert a VisualARQ door (real BIM door, IFC-exportable).

    Two placement modes — pass whichever the situation gives you:
    - `point` [x, y, z] **on a wall axis** (+ optional `rotation` in
      degrees): VisualARQ hosts the door into that wall automatically.
      This is the native mode of current VA versions.
    - `wall_id` + `position` (distance along the wall axis): legacy VA
      API; on current versions the tool converts is not possible — prefer
      `point`.

    Parameters:
    - style: Door style name (see `va_list_styles(kind="door")`).
    - width / height: Optional overrides; omit to keep the style's values.

    Returns:
        {"success": true, "data": {"door_id": "...", "style": "...", ...}}
    """
    try:
        if point is None and (wall_id is None or position is None):
            raise ValueError(
                "pass either point=[x,y,z] (on a wall axis) or "
                "wall_id + position")
        rhino = get_rhino_connection()
        result = run_va(rhino, """
import math
def style_name(sid):
    if hasattr(va, "GetStyleName"):
        return va.GetStyleName(sid)
    return va.GetDoorStyleName(sid)
style_id = None
for ds_id in (va.GetAllDoorStyleIds() or []):
    if style_name(ds_id) == params["style"]:
        style_id = ds_id
        break
if style_id is None:
    result = {"status": "error",
              "message": "Door style not found: " + params["style"]}
else:
    modern = "doorStyleId" in str(va.AddDoor.__doc__ or "")
    if modern:
        p = params.get("point")
        if not p:
            result = {"status": "error", "message":
                      "This VisualARQ version places doors by 3D point - "
                      "pass point=[x,y,z] on the wall axis"}
            door_id = Guid.Empty
        else:
            door_id = va.AddDoor(style_id,
                                 rg.Point3d(p[0], p[1], p[2]),
                                 math.radians(params.get("rotation") or 0.0))
    else:
        door_id = va.AddDoor(Guid(params["wall_id"]),
                             params["position"], style_id)
    if door_id != Guid.Empty:
        try:
            if params.get("width") and hasattr(va, "SetDoorWidth"):
                va.SetDoorWidth(door_id, params["width"])
            if params.get("height") and hasattr(va, "SetDoorHeight"):
                va.SetDoorHeight(door_id, params["height"])
        except Exception:
            pass  # sizing is best-effort; the door exists
        result = {"status": "success", "door_id": str(door_id),
                  "style": params["style"], "point": params.get("point"),
                  "wall_id": params.get("wall_id"),
                  "width": params.get("width"),
                  "height": params.get("height")}
    elif result is None:
        result = {"status": "error", "message": "AddDoor returned empty Guid"}
""", {"style": style, "point": point, "rotation": rotation,
            "wall_id": wall_id, "position": position,
            "width": width, "height": height})
        return _respond(result, f"Door created: {result.get('door_id')}")
    except Exception as e:
        logger.error(f"Error creating VisualARQ door: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_list_levels(ctx: Context) -> str:
    """List VisualARQ levels (name + elevation).

    Returns:
        {"success": true, "data": {"levels":
            [{"id": "...", "name": "EG", "elevation": 0.0}, ...]}}
    """
    try:
        rhino = get_rhino_connection()
        result = run_va(rhino, """
levels = []
if hasattr(va, "GetAllLevelIds"):
    for lid in (va.GetAllLevelIds() or []):
        levels.append({"id": str(lid), "name": va.GetLevelName(lid),
                       "elevation": va.GetLevelElevation(lid)})
else:
    for bid in (va.GetAllBuildingIds() or []):
        bname = va.GetBuildingName(bid)
        for lid in (va.GetBuildingLevelIds(bid) or []):
            levels.append({"id": str(lid), "name": va.GetLevelName(lid),
                           "elevation": va.GetLevelElevation(lid),
                           "building": bname})
result = {"status": "success", "levels": levels}
""")
        return _respond(result, f"{len(result.get('levels', []))} level(s)")
    except Exception as e:
        logger.error(f"Error listing VisualARQ levels: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_add_level(ctx: Context, name: str, elevation: float) -> str:
    """Add a VisualARQ level (storey) at the given elevation.

    Returns:
        {"success": true, "data": {"level_id": "...", "name": "OG1",
            "elevation": 2800.0}}
    """
    try:
        if not name:
            raise ValueError("name is required")
        rhino = get_rhino_connection()
        result = run_va(rhino, """
# Newer VA: AddLevel(buildingId, name, elevation) — use/create a building.
if "buildingId" in str(va.AddLevel.__doc__ or ""):
    bids = va.GetAllBuildingIds() or []
    bid = bids[0] if len(bids) else va.AddBuilding("Building 1", 0.0)
    level_id = va.AddLevel(bid, params["name"], params["elevation"])
else:
    level_id = va.AddLevel(params["name"], params["elevation"])
if level_id != Guid.Empty:
    result = {"status": "success", "level_id": str(level_id),
              "name": params["name"], "elevation": params["elevation"]}
else:
    result = {"status": "error", "message": "AddLevel returned empty Guid"}
""", {"name": name, "elevation": elevation})
        return _respond(result, f"Level '{name}' at {elevation}")
    except Exception as e:
        logger.error(f"Error adding VisualARQ level: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_ifc_export(ctx: Context, path: str, version: str = "IFC4") -> str:
    """Export the document to IFC via VisualARQ — the BIM deliverable.

    Parameters:
    - path: Output `.ifc` path, visible to the WINDOWS Rhino process
      (e.g. `C:/Users/<you>/Desktop/model.ifc`).
    - version: "IFC4" (default) or "IFC2x3". Only honored by the legacy
      `va.ExportIFC` API; on current VisualARQ the schema comes from the
      saved exporter settings (the V3 engine writes IFC2x3).

    Returns:
        {"success": true, "data": {"path": "...", "version": "IFC4"}}

    VisualARQ elements (walls, doors, windows, slabs, levels) export as
    typed IFC entities (IfcWall, IfcDoor, ...); plain Rhino geometry
    exports as proxies.

    FIRST-RUN GOTCHA: the VisualARQ IFC exporter pops a **modal options
    dialog** on its first use in an installation — it blocks this tool
    (timeout) AND every later save until someone clicks it away in the
    Rhino UI. Have the user tick *"Always use these settings. Do not show
    this dialog again"* once (settings adjustable any time via the
    `IfcExportOptionsDialog` command); afterwards exports run headless.
    """
    try:
        if not path or not path.lower().endswith(".ifc"):
            raise ValueError("path must end with .ifc")
        rhino = get_rhino_connection()
        result = run_va(rhino, """
# Newer VA has no ExportIFC in VisualARQ.Script — write through the
# registered IFC export plugin via RhinoDoc.WriteFile with
# SuppressDialogBoxes (doc.Export would pop the modal options dialog
# and block the UI thread — verified live).
if hasattr(va, "ExportIFC"):
    success = va.ExportIFC(params["path"], params["version"])
    exporter = "va.ExportIFC"
else:
    import scriptcontext as sc
    import Rhino
    opts = Rhino.FileIO.FileWriteOptions()
    opts.SuppressDialogBoxes = True
    opts.WriteSelectedObjectsOnly = False
    success = sc.doc.WriteFile(params["path"], opts)
    exporter = "doc.WriteFile (VisualARQ IFC plugin, dialogs suppressed)"
if success:
    result = {"status": "success", "path": params["path"],
              "version": params["version"], "exporter": exporter}
else:
    result = {"status": "error", "message": "IFC export returned false"}
""", {"path": path, "version": version})
        return _respond(result, f"IFC exported: {path}")
    except Exception as e:
        logger.error(f"Error exporting IFC: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_ifc_import(ctx: Context, path: str) -> str:
    """Import an IFC file into the document via VisualARQ.

    Parameters:
    - path: `.ifc` path visible to the WINDOWS Rhino process.

    Returns:
        {"success": true, "data": {"path": "..."}}
    """
    try:
        if not path or not path.lower().endswith(".ifc"):
            raise ValueError("path must end with .ifc")
        rhino = get_rhino_connection()
        result = run_va(rhino, """
if hasattr(va, "ImportIFC"):
    success = va.ImportIFC(params["path"])
else:
    import scriptcontext as sc
    success = sc.doc.Import(params["path"])
if success:
    result = {"status": "success", "path": params["path"]}
else:
    result = {"status": "error", "message": "IFC import returned false"}
""", {"path": path})
        return _respond(result, f"IFC imported: {path}")
    except Exception as e:
        logger.error(f"Error importing IFC: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
