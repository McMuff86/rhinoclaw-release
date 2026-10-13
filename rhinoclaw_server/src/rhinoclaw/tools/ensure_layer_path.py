import json
from typing import List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import error, from_exception, ok

_PRINT_PREFIX = "Script successfully executed! Print output: "

# IronPython 2.7 body. PARAMS_JSON is prepended as an ASCII-only literal
# (json.dumps with ensure_ascii, then repr), so umlauts in layer names can
# never break the embedded source.
_SCRIPT = """
import json
import System
import System.Drawing
import Rhino
import scriptcontext as sc

params = json.loads(PARAMS_JSON)
segments = [segment.strip() for segment in params["path"].split("::")]
color = params.get("color")
doc = sc.doc
result = {
    "status": "success",
    "layer_path": "::".join(segments),
    "created": [],
}
parent_id = System.Guid.Empty
full_path = None
layer_id = None
for position, segment in enumerate(segments):
    full_path = segment if full_path is None else full_path + "::" + segment
    index = doc.Layers.FindByFullPath(full_path, -1)
    if index >= 0:
        layer_id = doc.Layers.FindIndex(index).Id
        parent_id = layer_id
        continue
    layer = Rhino.DocObjects.Layer()
    layer.Name = segment
    if parent_id != System.Guid.Empty:
        layer.ParentLayerId = parent_id
    if color is not None and position == len(segments) - 1:
        layer.Color = System.Drawing.Color.FromArgb(
            color[0], color[1], color[2])
    added = doc.Layers.Add(layer)
    if added < 0:
        result = {
            "status": "error",
            "code": "RHINO_ERROR",
            "message": "Layers.Add failed for: " + full_path,
        }
        break
    layer_id = doc.Layers.FindIndex(added).Id
    parent_id = layer_id
    result["created"].append(full_path)
if result.get("status") == "success":
    result["layer_id"] = str(layer_id)
    result["created_count"] = len(result["created"])
    result["already_existed"] = len(result["created"]) == 0
print("RESULT:" + json.dumps(result))
"""


@mcp.tool()
def ensure_layer_path(
    ctx: Context,
    path: str,
    color: Optional[List[int]] = None,
) -> str:
    """Ensure a nested layer path exists and return the leaf layer's ID.

    ``path`` is a full ``::``-separated layer path such as
    ``"Plot9::VA::Walls"``. Every missing level is created with a correct
    ``ParentLayerId`` chain — the trap this tool replaces: assigning
    ``layer.Name = "A::B"`` creates ONE layer literally named ``A::B``,
    not a hierarchy. Existing levels are reused, so the call is idempotent
    and safe to repeat before every object placement.

    Parameters:
    - path: Full nested layer path. Segments are trimmed; empty segments
      (``"A::::B"``, leading/trailing ``::``) are rejected.
    - color: Optional [r, g, b] (0-255), applied only when the LEAF layer
      is newly created; an existing leaf keeps its color.

    Returns:
        {"success": true, "data": {"layer_id": "<guid>",
            "layer_path": "Plot9::VA::Walls",
            "created": ["Plot9", "Plot9::VA", "Plot9::VA::Walls"],
            "created_count": 3, "already_existed": false}}
    """
    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path is required")
        if len(path) > 500:
            raise ValueError("path must be at most 500 characters")
        segments = [segment.strip() for segment in path.split("::")]
        if any(not segment for segment in segments):
            raise ValueError(
                f"path contains an empty layer segment: {path!r}"
            )
        if color is not None:
            if (
                not isinstance(color, list)
                or len(color) != 3
                or any(
                    isinstance(channel, bool)
                    or not isinstance(channel, int)
                    or not 0 <= channel <= 255
                    for channel in color
                )
            ):
                raise ValueError("color must be [r, g, b] with 0-255 integers")

        params = {"path": "::".join(segments), "color": color}
        code = "PARAMS_JSON = " + repr(json.dumps(params)) + "\n" + _SCRIPT
        rhino = get_rhino_connection()
        raw = rhino.send_command(
            "execute_rhinoscript_python_code", {"code": code})

        if isinstance(raw, dict) and raw.get("success") is False:
            return json.dumps(error(
                str(raw.get("message") or "ensure_layer_path script failed"),
                code=ErrorCode.RHINO_ERROR,
            ))
        text = raw if isinstance(raw, str) else ""
        if isinstance(raw, dict):
            nested = raw.get("output") or raw.get("result") or raw.get("message", "")
            text = nested if isinstance(nested, str) else str(nested or "")
        if text.startswith(_PRINT_PREFIX):
            text = text[len(_PRINT_PREFIX):]
        if "RESULT:" not in text:
            return json.dumps(error(
                f"No RESULT line in ensure_layer_path output: {text[:200]}",
                code=ErrorCode.RHINO_ERROR,
            ))
        payload = json.loads(
            text.split("RESULT:", 1)[1].strip().splitlines()[0])
        if payload.get("status") != "success":
            return json.dumps(error(
                str(payload.get("message") or "ensure_layer_path failed"),
                code=ErrorCode.RHINO_ERROR,
                data=payload,
            ))
        data = {key: value for key, value in payload.items() if key != "status"}
        created = data.get("created_count", 0)
        return json.dumps(ok(
            message=(
                f"Layer path '{data.get('layer_path')}' ready "
                f"({created} level(s) created)"
            ),
            data=data,
        ))
    except ValueError as e:
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error ensuring layer path: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
