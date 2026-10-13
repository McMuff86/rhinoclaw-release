"""
Solve a loaded Grasshopper definition.

This tool triggers the Grasshopper solver to compute all outputs
based on the current parameter values.
"""

import json

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import error, from_exception, ok


def _verify_solve_evidence(result, expected_expire_all):
    issues = []
    solution = result.get("solution")
    runtime_messages = result.get("runtime_messages")
    if not isinstance(solution, dict):
        issues.append("solution evidence must be an object")
        solution = {}
    expected = {
        "requested": True,
        "solve_count": 1,
        "solution_start_count": 1,
        "solution_end_count": 1,
        "runtime_messages_collected": True,
    }
    for key, value in expected.items():
        if solution.get(key) != value:
            issues.append(f"solution.{key} must equal {value!r}")
    if solution.get("mode") != "Silent":
        issues.append("solution.mode must be 'Silent'")
    if solution.get("expire_all_objects") is not expected_expire_all:
        issues.append(
            "solution.expire_all_objects does not match the request"
        )
    if not isinstance(runtime_messages, list):
        issues.append("runtime_messages must be a list")
        runtime_messages = []

    actual_counts = {"remark": 0, "warning": 0, "error": 0}
    for index, item in enumerate(runtime_messages):
        if not isinstance(item, dict):
            issues.append(f"runtime_messages[{index}] must be an object")
            continue
        level = item.get("level")
        if level not in actual_counts:
            issues.append(f"runtime_messages[{index}].level is invalid")
            continue
        if not isinstance(item.get("component_id"), str):
            issues.append(
                f"runtime_messages[{index}].component_id must be a string"
            )
        if not isinstance(item.get("message"), str):
            issues.append(f"runtime_messages[{index}].message must be a string")
        actual_counts[level] += 1

    reported_counts = solution.get("runtime_message_counts")
    if not isinstance(reported_counts, dict):
        issues.append("solution.runtime_message_counts must be an object")
    else:
        for level, count in actual_counts.items():
            if reported_counts.get(level) != count:
                issues.append(
                    f"solution.runtime_message_counts.{level} does not "
                    "match runtime_messages"
                )
    if solution.get("runtime_message_count") != len(runtime_messages):
        issues.append(
            "solution.runtime_message_count does not match runtime_messages"
        )
    for field, level in (
        ("remarks", "remark"),
        ("warnings", "warning"),
        ("errors", "error"),
    ):
        messages = result.get(field)
        if not isinstance(messages, list):
            issues.append(f"{field} must be a list")
        elif len(messages) != actual_counts[level]:
            issues.append(f"{field} count does not match runtime_messages")
    return {"pass": not issues, "issues": issues}


@mcp.tool()
def solve_grasshopper(
    ctx: Context,
    definition_id: str,
    expire_all: bool = True,
) -> str:
    """
    Solve a loaded Grasshopper definition.
    
    Triggers the Grasshopper solver to compute all outputs based on
    the current parameter values. Call this after setting parameters
    and before baking or retrieving outputs.
    
    Parameters:
        definition_id: ID returned from load_grasshopper_definition
        expire_all: If True, forces full recalculation of all components.
                   If False, only recalculates components with expired inputs.
                   Default: True
    
    Returns:
        JSON object containing:
        - definition_id: The definition ID
        - status: "solved" or "solved_with_errors"
        - errors: Array of error messages (if any)
        - warnings: Array of warning messages (if any)
        - remarks: Array of remark messages (if any)
        - runtime_messages: Complete structured message inventory
        - solution: Exactly-one-cycle SolutionStart/SolutionEnd evidence,
          solve mode, duration and message counts
    
    Example:
        >>> # Load and configure
        >>> result = load_grasshopper_definition(file_path="C:/path/to/door.gh")
        >>> definition_id = result["data"]["definition_id"]
        >>> set_grasshopper_parameter(definition_id=definition_id, parameter_name="Height", value=2400)
        >>> 
        >>> # Solve
        >>> solve_result = solve_grasshopper(definition_id=definition_id)
        >>> if solve_result["data"]["status"] == "solved":
        ...     # Now we can bake or get outputs
        ...     bake_grasshopper(definition_id=definition_id)
    
    Notes:
        - Must be called before bake_grasshopper or get_grasshopper_outputs
        - Errors from components are reported but don't stop execution
        - Some components may produce warnings that are informational
        - Use expire_all=False for faster incremental updates
    
    See Also:
        - set_grasshopper_parameter: Set inputs before solving
        - bake_grasshopper: Bake geometry after solving
        - get_grasshopper_outputs: Retrieve values after solving
    """
    if not definition_id:
        return json.dumps(from_exception(
            ValueError("definition_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))

    try:
        rhino = get_rhino_connection()

        result = rhino.send_command("solve_grasshopper", {
            "definition_id": definition_id,
            "expire_all": expire_all
        })

        verification = _verify_solve_evidence(result, expire_all)
        result["verification"] = verification
        if not verification["pass"]:
            return json.dumps(error(
                "Grasshopper solve returned incomplete or inconsistent evidence",
                code=ErrorCode.VERIFICATION_FAILED,
                data=result,
            ))

        # Format message based on status
        status = result.get("status", "unknown")
        errors = result.get("errors", [])
        warnings = result.get("warnings", [])
        
        if status == "solved":
            message = "Definition solved successfully"
        else:
            message = f"Definition solved with {len(errors)} error(s) and {len(warnings)} warning(s)"

        return json.dumps(ok(
            message=message,
            data=result
        ))
    except Exception as e:
        logger.error(f"Error solving Grasshopper definition: {str(e)}")
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
