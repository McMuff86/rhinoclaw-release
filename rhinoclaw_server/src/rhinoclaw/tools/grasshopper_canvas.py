"""Share the exact agent-loaded graph with the user's Grasshopper canvas."""

import json
from typing import List, Optional
from uuid import UUID

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import error, from_exception, ok


def _node_ids(values, limit=2000):
    if values is None:
        return None
    if not isinstance(values, list) or (limit is not None and len(values) > limit):
        raise ValueError("component_instance_ids must be a list of at most 2000 GUIDs")
    result = []
    for value in values:
        try:
            parsed = UUID(value) if isinstance(value, str) else None
        except ValueError:
            parsed = None
        if parsed is None or not parsed.int or str(parsed) in result:
            raise ValueError("component_instance_ids must contain distinct non-empty GUIDs")
        result.append(str(parsed))
    return result


def _canvas_issues(result):
    if not isinstance(result, dict):
        return ["Canvas response must be an object"]
    issues = []
    for flag in ("editor_visible", "has_document", "agent_registered", "modified", "chat_visible"):
        if not isinstance(result.get(flag), bool):
            issues.append(f"{flag} must be a boolean")
    for rows_key, count_key in (("nodes", "object_count"), ("wires", "wire_count")):
        rows, count = result.get(rows_key), result.get(count_key)
        if not isinstance(rows, list) or not isinstance(count, int) or isinstance(count, bool):
            issues.append(f"{rows_key}/{count_key} inventory is missing or invalid")
        elif len(rows) != count:
            issues.append(f"{count_key} disagrees with the actual inventory")
    nodes = result.get("nodes")
    if isinstance(nodes, list):
        try:
            _node_ids([row.get("instance_id") if isinstance(row, dict) else None for row in nodes], limit=None)
        except ValueError as exc:
            issues.append(str(exc))
    if result.get("agent_registered") is True and not result.get("definition_id"):
        issues.append("Registered canvas has no definition_id")
    if result.get("has_document") is False and (
        result.get("object_count") != 0 or result.get("wire_count") != 0
        or result.get("definition_id") is not None
    ):
        issues.append("Empty canvas reports document contents")
    return issues


@mcp.tool()
def get_grasshopper_canvas(ctx: Context) -> str:
    """Read the user's current GH canvas: document identity, nodes and wires.

    Returns editor visibility, registered definition_id (or null for a graph
    not controlled by RhinoClaw), node instance/type IDs, names, selection and
    positions, named ports, exact wire port/owner IDs and current Slider/Toggle/
    Panel values (Panel text is capped at 2000 characters, with a truncation flag).
    Does not open windows, register/adopt user graphs, inspect script source, solve or bake. A visible canvas is not
    proof of a clean solution. Use before changing or switching GH documents.
    """
    try:
        result = get_rhino_connection().send_command("get_grasshopper_canvas", {})
        issues = _canvas_issues(result)
        if issues:
            return json.dumps(error("Canvas readback is inconsistent",
                                   code=ErrorCode.VERIFICATION_FAILED,
                                   data={"canvas": result, "issues": issues}))
        return json.dumps(ok("Read active Grasshopper canvas", data=result))
    except Exception as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def attach_grasshopper_definition(ctx: Context, document_id: str) -> str:
    """Attach to the user's already-open GH graph without reloading or solving.

    First read get_grasshopper_canvas and pass its exact document_id. Fails if
    the user switched/closed the active graph in the meantime. Returns a stable
    definition_id for set_grasshopper_parameters, solve_grasshopper and show.
    Repeated attachment reuses the same handle. Selection, modified state and
    unsaved edits stay intact. Unload releases the handle and retains the graph.
    Only attach when the user wants this graph edited; a canvas read alone does
    not attach. No solve, bake, new window, file write or BIM claim is made.
    """
    try:
        document_id = _node_ids([document_id])[0]
    except ValueError:
        return json.dumps(from_exception(
            ValueError("document_id must be the non-empty GUID from get_grasshopper_canvas"),
            code=ErrorCode.INVALID_PARAMS))
    try:
        result = get_rhino_connection().send_command(
            "attach_grasshopper_definition", {"document_id": document_id})
        issues = _canvas_issues(result)
        if isinstance(result, dict) and (
            result.get("document_id") != document_id
            or result.get("has_document") is not True
            or result.get("agent_registered") is not True
            or result.get("same_document_instance") is not True
            or result.get("user_owned") is not True
            or result.get("solution_requested") is not False
        ):
            issues.append("Attachment did not confirm the requested user-owned live document")
        if issues:
            return json.dumps(error("Grasshopper attachment could not be verified; read the canvas before retrying",
                                   code=ErrorCode.VERIFICATION_FAILED,
                                   data={"canvas": result, "issues": issues}))
        return json.dumps(ok("Attached to the existing Grasshopper document", data=result))
    except Exception as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def show_grasshopper_definition(
    ctx: Context, definition_id: str,
    component_instance_ids: Optional[List[str]] = None,
    zoom: bool = True, open_chat: bool = False,
) -> str:
    """Show the SAME loaded GH document on the user's canvas, not a disk copy.

    Call after load_grasshopper_definition, then use the same definition_id
    for parameter changes and solving so the user sees the graph you control.
    Exact component_instance_ids select/highlight top-level nodes; None keeps
    selection, [] clears it. zoom frames the supplied nodes (or whole graph).
    open_chat opens the existing agent surface in a modeless GH companion
    window, including activity/stop controls; it does not connect a new agent.

    Existing documents stay open. Previously presented graphs are retained
    when unloaded: only the agent handle is released. User edits are never
    discarded by that cleanup. No explicit solve or bake is requested here;
    normal GH activation callbacks can run. Showing a graph does not verify
    geometry, BIM identity or completion of any solution. This is per-operation
    visibility, not animated per-node execution or external-agent reasoning.
    """
    try:
        if not isinstance(definition_id, str) or not definition_id.strip():
            raise ValueError("definition_id is required")
        if not isinstance(zoom, bool) or not isinstance(open_chat, bool):
            raise ValueError("zoom and open_chat must be booleans")
        ids = _node_ids(component_instance_ids)
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))
    try:
        params = {"definition_id": definition_id, "zoom": zoom, "open_chat": open_chat}
        if ids is not None:
            params["component_instance_ids"] = ids
        result = get_rhino_connection().send_command("show_grasshopper_definition", params)
        issues = _canvas_issues(result)
        if isinstance(result, dict):
            if (result.get("definition_id") != definition_id
                    or result.get("same_document_instance") is not True
                    or result.get("editor_visible") is not True
                    or (result.get("verification") or {}).get("pass") is not True):
                issues.append("The visible canvas is not verified as the requested live definition")
            if result.get("previous_document_retained") is not True:
                issues.append("The previously active document was not confirmed retained")
            if open_chat and result.get("chat_visible") is not True:
                issues.append("The requested chat window is not visible")
            if ids is not None:
                selected = sorted(row.get("instance_id") for row in result.get("nodes", [])
                                  if isinstance(row, dict) and row.get("selected") is True)
                if selected != sorted(ids):
                    issues.append("Selected nodes differ from component_instance_ids")
        if issues:
            return json.dumps(error("Grasshopper presentation could not be verified; inspect the UI before retrying",
                                   code=ErrorCode.VERIFICATION_FAILED,
                                   data={"canvas": result, "issues": issues}))
        return json.dumps(ok("Definition visible on the shared Grasshopper canvas", data=result))
    except Exception as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))
