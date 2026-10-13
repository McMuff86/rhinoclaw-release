import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.part_library import PartLibraryError, load_part
from rhinoclaw.utils.responses import from_exception, ok

_PRINT_PREFIX = "Script successfully executed! Print output: "

# UserDictionary keys the ERP embedding contract uses on block definitions.
_ARTICLE_KEY = "ARTICLE_JSON"
_BOMPART_KEY = "BOMPART_JSON"


def _inspect_definition(rhino, block_name: str) -> Dict[str, Any]:
    """Read a block definition's UserDictionary + tight bbox in live Rhino.

    Embedded IronPython 2.7 script (keep Python-2 compatible). This is the
    check CI cannot do: rhino3dm neither reads InstanceDefinition
    UserDictionary nor produces tight Brep bboxes (control-point hulls are
    ~4 mm looser — proven during the acceptance test).
    """
    code = (
        "import scriptcontext as sc\n"
        "import Rhino\n"
        "import json\n"
        f"target = {json.dumps(block_name)}\n"
        "idef = None\n"
        "for d in sc.doc.InstanceDefinitions:\n"
        "    if not d.IsDeleted and d.Name == target:\n"
        "        idef = d\n"
        "        break\n"
        "if idef is None:\n"
        "    print(json.dumps({'found': False}))\n"
        "else:\n"
        "    def getstr(ud, key):\n"
        "        try:\n"
        "            if ud is not None and ud.ContainsKey(key):\n"
        "                return str(ud[key])\n"
        "        except:\n"
        "            pass\n"
        "        return None\n"
        "    ud = idef.UserDictionary\n"
        "    keys = []\n"
        "    try:\n"
        "        keys = [str(k) for k in ud.Keys]\n"
        "    except:\n"
        "        pass\n"
        "    bb = None\n"
        "    for o in idef.GetObjects():\n"
        "        if o is None or o.Geometry is None:\n"
        "            continue\n"
        "        b = o.Geometry.GetBoundingBox(True)\n"
        "        if not b.IsValid:\n"
        "            continue\n"
        "        bb = b if bb is None else Rhino.Geometry.BoundingBox.Union(bb, b)\n"
        "    bbox = None\n"
        "    if bb is not None:\n"
        "        bbox = {'min': [bb.Min.X, bb.Min.Y, bb.Min.Z],\n"
        "                'max': [bb.Max.X, bb.Max.Y, bb.Max.Z]}\n"
        "    print(json.dumps({\n"
        "        'found': True,\n"
        "        'definition_id': str(idef.Id),\n"
        "        'object_count': idef.ObjectCount,\n"
        "        'user_dictionary_keys': keys,\n"
        f"        'article_json': getstr(ud, {json.dumps(_ARTICLE_KEY)}),\n"
        f"        'bompart_json': getstr(ud, {json.dumps(_BOMPART_KEY)}),\n"
        "        'bbox': bbox}))\n"
    )
    raw = rhino.send_command("execute_rhinoscript_python_code", {"code": code})
    text = raw if isinstance(raw, str) else (raw or {}).get("result", "")
    if isinstance(text, str) and text.startswith(_PRINT_PREFIX):
        text = text[len(_PRINT_PREFIX):].strip()
    return json.loads(text)


def _payload_status(value: Optional[str]) -> Dict[str, Any]:
    """Presence + parseability of an embedded JSON payload (no content dump)."""
    if value is None:
        return {"present": False}
    status: Dict[str, Any] = {"present": True, "length": len(value)}
    try:
        json.loads(value)
        status["valid_json"] = True
    except (ValueError, TypeError):
        status["valid_json"] = False
    return status


@mcp.tool()
def library_doctor(
    ctx: Context,
    part_id: str,
    bbox_tol_mm: float = 0.1,
) -> str:
    """Health-check a library part against the live Rhino document.

    Closes the CI gap: rhino3dm can neither read a block definition's
    UserDictionary nor measure tight Brep bboxes, so this check needs a
    running Rhino. For the part's block definition it verifies:

    1. **Definition present?** Does the document contain a definition
       named part.json `block.name`?
    2. **ERP embedding**: reads the definition's UserDictionary keys
       `ARTICLE_JSON` / `BOMPART_JSON` and diffs presence against the
       `erp.embedded` declaration in part.json ("none", "article",
       "bompart", "article+bompart").
    3. **Geometry drift**: the definition's tight bbox must match
       part.json `verification.bbox_local` within `bbox_tol_mm`
       (default 0.1 mm) — a deviation means the in-document definition is
       stale or a different variant than the library master.

    Parameters:
    - part_id: Library part id (e.g. "kauls/aufnahmeelement-band-stumpf-vx").
    - bbox_tol_mm: Per-face tolerance for the bbox comparison (0.1 mm).

    Returns:
        {"success": true, "data": {"healthy": bool, "definition_in_doc":
            bool, "embedded": {"declared", "article": {...}, "bompart":
            {...}, "match": bool}, "bbox": {"measured", "expected",
            "max_dev_mm", "match"}, "issues": [...]}}
    """
    try:
        if not part_id:
            raise ValueError("part_id is required")

        part = load_part(part_id)
        block_name = (part.get("block") or {}).get("name")
        if not block_name:
            raise PartLibraryError(
                f"part.json of '{part_id}' has no block.name")

        rhino = get_rhino_connection()
        inspected = _inspect_definition(rhino, block_name)

        issues: List[str] = []
        if not inspected.get("found"):
            issues.append(
                f"definition '{block_name}' not found in the active "
                "document — open a document containing it or insert the "
                "part first (insert_library_part)")
            return json.dumps(ok(
                message=f"Part '{part_id}': definition not in document",
                data={
                    "healthy": False,
                    "part_id": part_id,
                    "block_name": block_name,
                    "definition_in_doc": False,
                    "issues": issues,
                },
            ))

        # --- ERP embedding vs. part.json declaration ----------------------
        declared = str(((part.get("erp") or {}).get("embedded")) or "none").lower()
        article = _payload_status(inspected.get("article_json"))
        bompart = _payload_status(inspected.get("bompart_json"))
        expect_article = "article" in declared
        expect_bompart = "bompart" in declared
        embedded_match = (article["present"] == expect_article
                          and bompart["present"] == expect_bompart)
        if not embedded_match:
            issues.append(
                f"ERP embedding mismatch: part.json declares "
                f"'{declared}', document has ARTICLE_JSON="
                f"{article['present']}, BOMPART_JSON={bompart['present']}")
        if article.get("valid_json") is False:
            issues.append("ARTICLE_JSON present but not valid JSON")
            embedded_match = False
        if bompart.get("valid_json") is False:
            issues.append("BOMPART_JSON present but not valid JSON")
            embedded_match = False

        # --- tight bbox vs. verification.bbox_local ------------------------
        bbox_verdict: Optional[Dict[str, Any]] = None
        expected_bbox = (part.get("verification") or {}).get("bbox_local")
        measured_bbox = inspected.get("bbox")
        if expected_bbox and measured_bbox:
            devs = [abs(measured_bbox["min"][i] - expected_bbox["min"][i])
                    for i in range(3)]
            devs += [abs(measured_bbox["max"][i] - expected_bbox["max"][i])
                     for i in range(3)]
            max_dev = max(devs)
            bbox_match = max_dev <= bbox_tol_mm
            if not bbox_match:
                issues.append(
                    f"definition bbox deviates up to {max_dev:.3f} mm from "
                    f"verification.bbox_local (tol {bbox_tol_mm}) — "
                    "in-document definition is stale or a different variant")
            bbox_verdict = {
                "measured": {k: [round(v, 4) for v in measured_bbox[k]]
                             for k in ("min", "max")},
                "expected": expected_bbox,
                "max_dev_mm": round(max_dev, 4),
                "tol_mm": bbox_tol_mm,
                "match": bbox_match,
            }
        else:
            issues.append(
                "bbox comparison skipped — "
                + ("part.json has no verification.bbox_local"
                   if not expected_bbox else
                   "definition has no measurable geometry"))

        healthy = (embedded_match
                   and bbox_verdict is not None and bbox_verdict["match"])
        status = "healthy" if healthy else "issues found"
        return json.dumps(ok(
            message=f"Part '{part_id}': {status}"
                    + (f" — {'; '.join(issues)}" if issues else ""),
            data={
                "healthy": healthy,
                "part_id": part_id,
                "block_name": block_name,
                "definition_in_doc": True,
                "definition_id": inspected.get("definition_id"),
                "object_count": inspected.get("object_count"),
                "embedded": {
                    "declared": declared,
                    "article": article,
                    "bompart": bompart,
                    "match": embedded_match,
                },
                "user_dictionary_keys": inspected.get("user_dictionary_keys"),
                "bbox": bbox_verdict,
                "issues": issues,
            },
        ))
    except (ValueError, PartLibraryError) as e:
        logger.error(f"Error running library doctor: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.INVALID_PARAMS))
    except Exception as e:
        logger.error(f"Error running library doctor: {e}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
