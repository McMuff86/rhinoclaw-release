import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.interaction_logger import interaction_logger
from rhinoclaw.utils.part_judge import evaluate_part_placement
from rhinoclaw.utils.part_library import PartLibraryError, load_part
from rhinoclaw.utils.responses import from_exception, ok

_PRINT_PREFIX = "Script successfully executed! Print output: "


def _measure_instance(rhino, object_id: Optional[str], name: Optional[str],
                      name_prefix: Optional[str]) -> Dict[str, Any]:
    """Measure one block instance in the live document.

    Embedded IronPython 2.7 script (keep Python-2 compatible). Returns the
    instance's full 4x4 xform, its world bbox and the definition name —
    RHINO-MEASURED values only, never anything the placing agent claimed.
    """
    code = (
        "import rhinoscriptsyntax as rs\n"
        "import scriptcontext as sc\n"
        "import Rhino\n"
        "import json\n"
        f"oid = {json.dumps(object_id)}\n"
        f"name = {json.dumps(name)}\n"
        f"prefix = {json.dumps(name_prefix)}\n"
        "matches = []\n"
        "if oid:\n"
        "    g = rs.coerceguid(oid)\n"
        "    o = sc.doc.Objects.FindId(g) if g else None\n"
        "    if isinstance(o, Rhino.DocObjects.InstanceObject):\n"
        "        matches.append(o)\n"
        "else:\n"
        "    for o in sc.doc.Objects:\n"
        "        if not isinstance(o, Rhino.DocObjects.InstanceObject):\n"
        "            continue\n"
        "        n = o.Attributes.Name or ''\n"
        "        if name is not None and n == name:\n"
        "            matches.append(o)\n"
        "        elif prefix is not None and n.startswith(prefix):\n"
        "            matches.append(o)\n"
        "if len(matches) == 0:\n"
        "    print(json.dumps({'found': False, 'candidates': []}))\n"
        "elif len(matches) > 1:\n"
        "    print(json.dumps({'found': False,\n"
        "                      'candidates': [str(m.Id) for m in matches]}))\n"
        "else:\n"
        "    obj = matches[0]\n"
        "    x = obj.InstanceXform\n"
        "    pts = rs.BoundingBox(obj.Id)\n"
        "    bbox = None\n"
        "    if pts:\n"
        "        bbox = {'min': [pts[0].X, pts[0].Y, pts[0].Z],\n"
        "                'max': [pts[6].X, pts[6].Y, pts[6].Z]}\n"
        "    print(json.dumps({\n"
        "        'found': True,\n"
        "        'object_id': str(obj.Id),\n"
        "        'object_name': obj.Attributes.Name or '',\n"
        "        'block_name': obj.InstanceDefinition.Name,\n"
        "        'xform': [x.M00, x.M01, x.M02, x.M03,\n"
        "                  x.M10, x.M11, x.M12, x.M13,\n"
        "                  x.M20, x.M21, x.M22, x.M23,\n"
        "                  x.M30, x.M31, x.M32, x.M33],\n"
        "        'bbox': bbox}))\n"
    )
    raw = rhino.send_command("execute_rhinoscript_python_code", {"code": code})
    text = raw if isinstance(raw, str) else (raw or {}).get("result", "")
    if isinstance(text, str) and text.startswith(_PRINT_PREFIX):
        text = text[len(_PRINT_PREFIX):].strip()
    return json.loads(text)


@mcp.tool()
def judge_part_placement(
    ctx: Context,
    part_id: str,
    expected_frame: List[float],
    object_id: Optional[str] = None,
    name: Optional[str] = None,
    name_prefix: Optional[str] = None,
    context: Optional[str] = None,
    tolerances: Optional[Dict[str, float]] = None,
    log_outcomes: bool = True,
) -> str:
    """Judge a placed library part against part.json verification data.

    The domain judge of the part-library loop (insert -> judge -> log ->
    recall). It RE-MEASURES the instance in the live document (full 4x4
    xform, det, world bbox) and evaluates it against the part's
    verification section: det rule, frame_axis_distance probes (e.g. the
    hinge_axis must land on the target axis) and bbox plausibility against
    the transformed tight bbox_local. Claims by the placing agent are
    never trusted — only Rhino-measured values enter the verdict.

    Parameters:
    - part_id: Library part (e.g. "kauls/aufnahmeelement-band-stumpf-vx");
      verification, frames and det_rule come from its part.json.
    - expected_frame: 9-double target plane in WORLD coordinates — the
      INDEPENDENT ground truth (e.g. computed from door parameters by the
      caller). Never pass the placing agent's own claim here.
    - object_id: Instance GUID to judge (from insert_library_part).
    - name / name_prefix: Alternative instance lookup by object name
      (exactly one match required — multiple matches error with the
      candidate ids).
    - context: Free-form recall context (e.g. "door-right-900") stamped
      into the outcome record; the part distiller keys on part_id|context.
    - tolerances: Optional override, e.g. {"position_mm": 0.5,
      "axis_deg": 1.0, "bbox_mm": 5.0} — merged over part.json values.
    - log_outcomes: Write one `part_outcome` JSONL record (the corpus
      recall_part_placements distills from).

    Returns:
        {"success": true, "data": {"pass": bool, "det": ..., "probes":
            [{"name", "distance_mm", "angle_deg", "pass"}, ...],
            "bbox": {...}, "object_id", "block_name", "hint"}}

    Example (the full insert -> judge loop):
        r = insert_library_part(part_id=..., target_frame=frame)
        judge_part_placement(part_id=..., expected_frame=frame,
                             object_id=r["data"]["object_id"],
                             context="door-right-900")
    """
    try:
        if not part_id:
            raise ValueError("part_id is required")
        if expected_frame is None or len(expected_frame) != 9:
            raise ValueError(
                "expected_frame must be 9 doubles [Ox,Oy,Oz, Xx,Xy,Xz, "
                "Yx,Yy,Yz] — the independent ground-truth target plane")
        if not (object_id or name or name_prefix):
            raise ValueError(
                "one of object_id, name or name_prefix is required to "
                "find the instance to judge")

        part = load_part(part_id)

        rhino = get_rhino_connection()
        measured = _measure_instance(rhino, object_id, name, name_prefix)

        if not measured.get("found"):
            candidates = measured.get("candidates") or []
            if len(candidates) > 1:
                raise ValueError(
                    f"instance lookup is ambiguous — {len(candidates)} "
                    f"matches: {candidates}. Judge exactly one instance "
                    "(pass its object_id).")
            verdict = {
                "pass": False,
                "found": False,
                "hint": "no matching block instance found in the document",
            }
            if log_outcomes:
                interaction_logger.log_part_outcome({
                    "part_id": part_id,
                    "context": context,
                    "pass": False,
                    "found": False,
                    "target_frame": list(expected_frame),
                })
            return json.dumps(ok(
                message=f"Part '{part_id}': FAIL — instance not found",
                data=verdict,
            ))

        verdict = evaluate_part_placement(
            part=part,
            measured_xform=measured["xform"],
            measured_bbox=measured.get("bbox"),
            expected_frame=expected_frame,
            tolerances=tolerances,
        )
        verdict.update({
            "found": True,
            "object_id": measured.get("object_id"),
            "object_name": measured.get("object_name"),
            "block_name": measured.get("block_name"),
            "block_name_matches": (
                measured.get("block_name") == ((part.get("block") or {}).get("name"))
            ),
        })

        if log_outcomes:
            # Outcome corpus: judge-measured values + the caller's
            # independent ground truth — never the placing agent's claims.
            interaction_logger.log_part_outcome({
                "part_id": part_id,
                "context": context,
                "pass": verdict["pass"],
                "det": verdict["det"],
                "worst_probe_mm": verdict["worst_probe_mm"],
                "bbox_max_dev_mm": (verdict.get("bbox") or {}).get("max_dev_mm"),
                "probes": [
                    {"name": p.get("name"),
                     "distance_mm": p.get("distance_mm"),
                     "angle_deg": p.get("angle_deg"),
                     "pass": p.get("pass")}
                    for p in verdict["probes"]
                ],
                "target_frame": list(expected_frame),
                "xform": list(measured["xform"]),
                "object_id": measured.get("object_id"),
                "block_name": measured.get("block_name"),
            })

        status = "PASS" if verdict["pass"] else "FAIL"
        return json.dumps(ok(
            message=f"Part '{part_id}': {status}"
                    + (f" — {verdict['hint']}" if verdict.get("hint") else ""),
            data=verdict,
        ))
    except (ValueError, PartLibraryError) as e:
        logger.error(f"Error judging part placement: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error judging part placement: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
