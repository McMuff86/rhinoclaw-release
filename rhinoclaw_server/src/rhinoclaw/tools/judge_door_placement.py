import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.door_judge import judge_door, match_doors_to_openings
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.gh_player import union_bbox
from rhinoclaw.utils.interaction_logger import interaction_logger
from rhinoclaw.utils.responses import from_exception, ok

_PRINT_PREFIX = "Script successfully executed! Print output: "


def _read_openings_from_layer(rhino, layer: str) -> List[Dict[str, Any]]:
    """Read opening axis segments (curve start/end) from a document layer.

    The opening axes are GROUND TRUTH: drawn independently in the plan
    (e.g. layer `01_OPENING_AXES`), never created by the placing agent.
    """
    # IronPython 2.7 — keep the embedded script Python-2 compatible.
    code = (
        "import rhinoscriptsyntax as rs\n"
        "import json\n"
        f"layer = {json.dumps(layer)}\n"
        "out = []\n"
        "if rs.IsLayer(layer):\n"
        "    ids = rs.ObjectsByLayer(layer) or []\n"
        "    for oid in ids:\n"
        "        if rs.IsCurve(oid):\n"
        "            s = rs.CurveStartPoint(oid)\n"
        "            e = rs.CurveEndPoint(oid)\n"
        "            out.append({'id': str(oid),\n"
        "                        'start': [s.X, s.Y, s.Z],\n"
        "                        'end': [e.X, e.Y, e.Z]})\n"
        "    print(json.dumps(out))\n"
        "else:\n"
        "    print('LAYER_MISSING')\n"
    )
    raw = rhino.send_command("execute_rhinoscript_python_code", {"code": code})
    text = raw if isinstance(raw, str) else (raw or {}).get("result", "")
    if isinstance(text, str) and text.startswith(_PRINT_PREFIX):
        text = text[len(_PRINT_PREFIX):].strip()
    if text == "LAYER_MISSING":
        raise ValueError(
            f"Opening layer '{layer}' does not exist — pass `openings` "
            "explicitly or draw the opening axes first."
        )
    return json.loads(text)


@mcp.tool()
def judge_door_placement(
    ctx: Context,
    doors: List[Dict[str, Any]],
    openings: Optional[List[Dict[str, Any]]] = None,
    opening_layer: str = "01_OPENING_AXES",
    tolerance_center_mm: float = 25.0,
    tolerance_axis_deg: float = 5.0,
    tolerance_width_mm: float = 30.0,
    width_allowance_mm: float = 220.0,
    log_outcomes: bool = True,
    definition: Optional[str] = None,
) -> str:
    """Judge placed doors against opening ground truth — geometry only.

    The domain judge of the verified door vertical. For every door it
    **re-measures** the baked geometry via `get_objects_info(object_ids)`
    and compares it against the independently drawn opening axis. Any
    `baked_bbox`, `rotation`, or other *claims* in the input are
    deliberately ignored — a door that claims the right rotation but whose
    geometry points the wrong way fails.

    Three independent signals per door:
    - `off_center_mm`: door footprint center ↔ opening center distance
    - `axis_deg_error`: door principal axis ↔ opening axis (0–90°)
    - `width_error_mm`: extent along the opening axis minus opening width
      minus `width_allowance_mm` (signed; Rahmentuer_UD5 frame = 220 mm)

    Parameters:
    - doors: One dict per door with `id` and `object_ids` (the GUID list a
      `place_doors` result reports). Feed `result.data.doors` directly.
    - openings: Optional explicit ground truth:
      `[{"id": "O1", "start": [x,y,z], "end": [x,y,z]}, ...]` — the segment
      length IS the opening width (Lichtbreite). When omitted, axis curves
      are read from `opening_layer` in the document.
    - opening_layer: Layer holding the opening axis curves (default
      `01_OPENING_AXES`).
    - tolerance_*: Pass thresholds. The published benchmark freezes these
      like a test oracle — change only with a callout.
    - width_allowance_mm: Expected door-extent overhang beyond the opening
      width (frame construction; 220 for the UD5 family).
    - log_outcomes: Write one `placement_outcome` JSONL record per door
      (the corpus the self-improving loop distills from).
    - definition: The `.gh` the doors came from (e.g. the `definition` field
      of the place_doors result) — stamped into each outcome record so the
      recall loop can key on (door_type, wall_axis).

    Returns:
        {"success": true, "data": {
            "total": N, "passed": n, "failed": m,
            "verdicts": [{"id", "placed", "off_center_mm", "axis_deg_error",
                          "width_error_mm", "pass", "hint", "opening_id",
                          "measured_bbox", "objects_found"}, ...]}}

    Example (the full place → judge loop):
        result = place_doors(definition=..., items=[...])
        judge_door_placement(
            doors=result["data"]["doors"],
            openings=[{"id": "O1", "start": [110, 0, 0], "end": [1010, 0, 0]}],
        )
    """
    try:
        if not isinstance(doors, list) or not doors:
            raise ValueError("doors must be a non-empty list of door dicts")
        for door in doors:
            if not isinstance(door, dict) or not door.get("object_ids"):
                raise ValueError(
                    "every door needs an `object_ids` list — the judge "
                    "re-measures real geometry, it cannot work from claims"
                )

        rhino = get_rhino_connection()

        if openings is None:
            openings = _read_openings_from_layer(rhino, opening_layer)
        if not openings:
            raise ValueError("no openings available as ground truth")
        for opening in openings:
            if "start" not in opening or "end" not in opening:
                raise ValueError("every opening needs `start` and `end` points")

        tolerances = {
            "center_mm": tolerance_center_mm,
            "axis_deg": tolerance_axis_deg,
            "width_mm": tolerance_width_mm,
        }

        # Re-measure every door from the document — the only trusted input.
        measured: List[Optional[list]] = []
        objects_found: List[int] = []
        for door in doors:
            info = rhino.send_command("get_objects_info",
                                      {"ids": list(door["object_ids"])})
            measured.append(union_bbox(info))
            objects_found.append((info or {}).get("count", 0))

        centers = [
            ((b[0][0] + b[1][0]) / 2.0, (b[0][1] + b[1][1]) / 2.0) if b else None
            for b in measured
        ]
        assignment = match_doors_to_openings(centers, openings)

        verdicts = []
        for i, door in enumerate(doors):
            door_id = str(door.get("id", f"door_{i + 1}"))
            o_idx = assignment[i]
            if measured[i] is None or o_idx is None:
                verdict = {
                    "placed": measured[i] is not None,
                    "off_center_mm": None,
                    "axis_deg_error": None,
                    "width_error_mm": None,
                    "pass": False,
                    "hint": ("No baked geometry found for this door."
                             if measured[i] is None
                             else "No opening left to match this door against."),
                }
            else:
                opening = openings[o_idx]
                verdict = judge_door(
                    measured[i], opening["start"], opening["end"],
                    tolerances=tolerances,
                    width_allowance_mm=width_allowance_mm,
                )

            verdict.update({
                "id": door_id,
                "opening_id": (openings[o_idx].get("id", o_idx)
                               if o_idx is not None else None),
                "measured_bbox": measured[i],
                "objects_found": objects_found[i],
            })
            verdicts.append(verdict)

            if log_outcomes:
                # The outcome corpus: judge-measured verdict + the request
                # metadata needed for recall keys — never the claim itself.
                interaction_logger.log_outcome({
                    "door_id": door_id,
                    "pass": verdict["pass"],
                    "off_center_mm": verdict["off_center_mm"],
                    "axis_deg_error": verdict["axis_deg_error"],
                    "width_error_mm": verdict["width_error_mm"],
                    "wall_axis": door.get("wall_axis"),
                    "width_requested": door.get("width_requested"),
                    "rotation_applied": door.get("rotation_applied"),
                    "opening_id": verdict["opening_id"],
                    "definition": definition,
                })

        passed = sum(1 for v in verdicts if v["pass"])
        return json.dumps(ok(
            message=f"Judged {len(verdicts)} door(s): {passed} pass, "
                    f"{len(verdicts) - passed} fail",
            data={
                "total": len(verdicts),
                "passed": passed,
                "failed": len(verdicts) - passed,
                "tolerances": tolerances,
                "width_allowance_mm": width_allowance_mm,
                "verdicts": verdicts,
            },
        ))
    except Exception as e:
        logger.error(f"Error judging door placement: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
