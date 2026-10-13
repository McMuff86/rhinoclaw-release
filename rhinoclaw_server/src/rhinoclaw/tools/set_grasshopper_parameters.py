"""Atomically set loaded Grasshopper inputs by stable instance identity."""

import json
from typing import Any, Dict, List
from uuid import UUID

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import error, from_exception, ok


def _canonical_assignments(
    assignments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not isinstance(assignments, list) or not assignments:
        raise ValueError("assignments must be a non-empty list")
    if len(assignments) > 500:
        raise ValueError("assignments must contain at most 500 items")

    canonical = []
    seen = set()
    for index, item in enumerate(assignments):
        if not isinstance(item, dict) or set(item) != {
            "parameter_instance_id",
            "value",
        }:
            raise ValueError(
                f"assignments[{index}] must contain exactly "
                "parameter_instance_id and value"
            )
        raw_id = item["parameter_instance_id"]
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise ValueError(
                f"assignments[{index}].parameter_instance_id must be a GUID"
            )
        try:
            parameter_id = UUID(raw_id.strip())
        except ValueError as exc:
            raise ValueError(
                f"assignments[{index}].parameter_instance_id must be a GUID"
            ) from exc
        if parameter_id.int == 0:
            raise ValueError(
                f"assignments[{index}].parameter_instance_id must be non-empty"
            )
        canonical_id = str(parameter_id)
        if canonical_id in seen:
            raise ValueError(
                f"assignments[{index}].parameter_instance_id is duplicated"
            )
        if item["value"] is None:
            raise ValueError(f"assignments[{index}].value must not be null")
        seen.add(canonical_id)
        canonical.append({
            "parameter_instance_id": canonical_id,
            "value": item["value"],
        })
    return canonical


@mcp.tool()
def set_grasshopper_parameters(
    ctx: Context,
    definition_id: str,
    assignments: List[Dict[str, Any]],
) -> str:
    """Atomically set multiple loaded-definition inputs by instance GUID.

    Use the ``parameter_instance_id`` values returned by
    ``load_grasshopper_definition``. Every Number Slider, Panel and Boolean
    Toggle assignment is resolved, type-checked and range-checked before the
    first value changes. A successful call independently reads every value
    back. A commit/readback failure triggers reverse rollback and reports
    whether restoration was proven.

    ``assignments`` items contain exactly::

        {"parameter_instance_id": "...", "value": 2400}

    This exact-identity batch is the preferred path for authored graphs.
    The legacy singular tool still supports name matching, which is unsuitable
    when names or nicknames collide.
    """
    if not definition_id:
        return json.dumps(from_exception(
            ValueError("definition_id is required"),
            code=ErrorCode.INVALID_PARAMS,
        ))
    try:
        canonical = _canonical_assignments(assignments)
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))

    try:
        rhino = get_rhino_connection()
        result = rhino.send_command("set_grasshopper_parameters", {
            "definition_id": definition_id,
            "assignments": canonical,
        })
        status = result.get("status")
        if status == "preflight_failed":
            return json.dumps(error(
                "Grasshopper parameter batch failed preflight",
                code=ErrorCode.PRECONDITION_FAILED,
                data=result,
            ))
        if status == "failed_after_mutation":
            rollback = result.get("rollback")
            restored = (
                isinstance(rollback, dict)
                and rollback.get("complete") is True
            )
            return json.dumps(error(
                "Grasshopper parameter batch failed after mutation"
                + ("; baseline restored" if restored else ""),
                code=(
                    ErrorCode.VERIFICATION_FAILED
                    if restored
                    else ErrorCode.PARTIAL_MUTATION
                ),
                data=result,
            ))

        issues = []
        returned = result.get("assignments")
        if result.get("atomic") is not True:
            issues.append("atomic must be true")
        if status != "set":
            issues.append("status must be 'set'")
        if result.get("selector") != "parameter_instance_id":
            issues.append("selector must be parameter_instance_id")
        if result.get("assignment_count") != len(canonical):
            issues.append("assignment_count does not match request")
        if not isinstance(returned, list) or len(returned) != len(canonical):
            issues.append("assignments readback count does not match request")
            returned = []
        else:
            for index, (expected, actual) in enumerate(
                zip(canonical, returned)
            ):
                if not isinstance(actual, dict):
                    issues.append(f"assignments[{index}] readback is not an object")
                    continue
                if actual.get("parameter_instance_id", "").lower() != (
                    expected["parameter_instance_id"].lower()
                ):
                    issues.append(
                        f"assignments[{index}] parameter identity mismatch"
                    )
                if actual.get("readback_match") is not True:
                    issues.append(
                        f"assignments[{index}] readback was not verified"
                    )
                if actual.get("requested_value") != expected["value"]:
                    issues.append(
                        f"assignments[{index}] requested-value echo mismatch"
                    )
        verification = {"pass": not issues, "issues": issues}
        result["verification"] = verification
        if issues:
            return json.dumps(error(
                "Grasshopper parameter batch returned inconsistent evidence",
                code=ErrorCode.VERIFICATION_FAILED,
                data=result,
            ))
        return json.dumps(ok(
            message=f"Atomically set {len(canonical)} Grasshopper parameter(s)",
            data=result,
        ))
    except Exception as exc:
        logger.error(f"Error setting Grasshopper parameter batch: {exc}")
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))
