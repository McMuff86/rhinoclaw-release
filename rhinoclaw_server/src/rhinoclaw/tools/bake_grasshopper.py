"""
Bake output geometry from a solved Grasshopper definition to Rhino.

This tool creates actual Rhino geometry objects from the computed
Grasshopper outputs.
"""

import json
from typing import Dict, List, Literal, Optional
from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.gh_bake_verification import (
    canonical_nonempty_guids,
    verify_active_object_readback,
)
from rhinoclaw.utils.gh_output_targets import validate_output_targets
from rhinoclaw.utils.gh_bim_verification import (
    validate_bim_expectation,
    verify_bim_bake,
)
from rhinoclaw.tools.visualarq import va_get_object
from rhinoclaw.utils.responses import error, from_exception, ok


def _canonical_baked_ids(result):
    baked_count = result.get("baked_count")
    baked_objects = result.get("baked_objects")
    issues = []
    if (
        not isinstance(baked_count, int)
        or isinstance(baked_count, bool)
        or baked_count < 0
    ):
        issues.append("baked_count must be a non-negative integer")
    if not isinstance(baked_objects, list):
        issues.append("baked_objects must be a list")
        baked_objects = []

    raw_ids = []
    for index, item in enumerate(baked_objects):
        if not isinstance(item, dict):
            issues.append(f"baked_objects[{index}] must be an object")
            continue
        raw_ids.append(item.get("id"))

    ids, id_issues = canonical_nonempty_guids(
        raw_ids,
        field_name="baked_objects[].id",
    )
    issues.extend(id_issues)

    if isinstance(baked_count, int) and not isinstance(baked_count, bool):
        if baked_count != len(baked_objects):
            issues.append(
                "baked_count does not equal len(baked_objects)")
    return ids, issues


@mcp.tool()
def bake_grasshopper(
    ctx: Context,
    definition_id: str,
    component_names: Optional[List[str]] = None,
    output_targets: Optional[List[Dict[str, str]]] = None,
    layer: Optional[str] = None,
    expected_visualarq_kind: Optional[Literal["wall", "slab", "space", "door", "window"]] = None,
    expected_count: Optional[int] = None,
    expected_style_id: Optional[str] = None,
    expected_host_id: Optional[str] = None,
) -> str:
    """
    Bake output geometry from a solved Grasshopper definition to Rhino.
    
    Creates actual Rhino geometry objects from the computed Grasshopper outputs.
    The definition must be solved first using solve_grasshopper.
    
    Parameters:
        definition_id: ID returned from load_grasshopper_definition
        component_names: Optional list of component nicknames to bake.
                        If not specified, bakes all output geometry.
        output_targets: Exact output identities returned by
                        load/get_grasshopper_outputs. Each item contains
                        component_instance_id and output_instance_id. This is
                        mutually exclusive with component_names and is the
                        recommended selector when nicknames may collide.
        layer: Optional layer name for the baked geometry.
               Creates the layer if it doesn't exist.
        expected_visualarq_kind: Require actual VisualARQ products of this kind,
               not lookalike Breps. Requires exact output_targets and native
               BakeAware output items; prepare the target layer first.
               Independently reads each product, its style and domain data.
               Doors/windows also require a readable active VisualARQ wall host.
        expected_count: Optional exact product count for the BIM batch.
        expected_style_id: Optional required BIM style GUID for all products.
        expected_host_id: Optional required host wall GUID for doors/windows.
               Count/style/host expectations require expected_visualarq_kind.
    
    Returns:
        JSON object containing:
        - definition_id: The definition ID
        - baked_count: Number of objects baked
        - baked_objects: Array of baked objects with:
            - id: Rhino object GUID
            - component: Source component nickname
            - output: Source output nickname
        - layer: Target layer name (if specified)
    
    Example:
        >>> # Complete workflow
        >>> result = load_grasshopper_definition(file_path="C:/path/to/door.gh")
        >>> definition_id = result["data"]["definition_id"]
        >>> 
        >>> # Configure
        >>> set_grasshopper_parameter(definition_id=definition_id, parameter_name="Height", value=2400)
        >>> set_grasshopper_parameter(definition_id=definition_id, parameter_name="Width", value=1000)
        >>> 
        >>> # Solve
        >>> solve_grasshopper(definition_id=definition_id)
        >>> 
        >>> # Bake to specific layer
        >>> bake_result = bake_grasshopper(
        ...     definition_id=definition_id,
        ...     layer="Doors"
        ... )
        >>> print(f"Baked {bake_result['data']['baked_count']} objects")
        >>> 
        >>> # Optionally bake only specific components
        >>> bake_grasshopper(
        ...     definition_id=definition_id,
        ...     component_names=["Frame", "Panel"],
        ...     layer="Door_Parts"
        ... )
    
    Notes:
        - Definition must be solved first (solve_grasshopper)
        - Supports Brep, Surface, Mesh, Curve, Point, Line geometry
        - Exact ``output_targets`` whose items implement IGH_BakeAwareData
          use the guarded document-baseline/ownership path. Every item is
          invoked exactly once; mixed BakeAware/geometry batches fail before
          mutation and must be submitted separately.
        - Guarded BakeAware calls may target only an existing layer. Their
          evidence covers active objects, layers, instance definitions and
          the current layer; VisualARQ-private state remains explicitly
          unmeasured and a post-mutation failure is always PARTIAL_MUTATION.
        - Created layer inherits default layer properties
        - Returns GUIDs of all created Rhino objects
        - BIM mismatch/readback failure returns PARTIAL_MUTATION with retained
          IDs; never automatically retries or deletes potentially related BIM
          objects. Inspect the evidence before modifying or baking again.
        - BIM verification does not prove a host cut, level membership, IFC
          round-trip or rollback of VisualARQ-private state. Use va_create_door
          / va_create_window when verified host cutting is required.
    
    See Also:
        - solve_grasshopper: Must be called first
        - get_grasshopper_outputs: Get values without baking
        - unload_grasshopper_definition: Clean up when done
    """
    if not definition_id:
        return json.dumps(from_exception(
            ValueError("definition_id is required"),
            code=ErrorCode.INVALID_PARAMS
        ))
    if component_names is not None and output_targets is not None:
        return json.dumps(from_exception(
            ValueError(
                "component_names and output_targets are mutually exclusive"),
            code=ErrorCode.INVALID_PARAMS,
        ))
    try:
        canonical_targets = validate_output_targets(output_targets) \
            if output_targets is not None else None
        bim_expectation = validate_bim_expectation(
            expected_visualarq_kind, expected_count, expected_style_id,
            expected_host_id, canonical_targets,
        )
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))

    bake_sent = False
    result = None
    try:
        rhino = get_rhino_connection()

        params = {
            "definition_id": definition_id
        }
        
        if component_names is not None:
            params["component_names"] = component_names
        if canonical_targets is not None:
            params["output_targets"] = canonical_targets
        if layer is not None:
            params["layer"] = layer
        if bim_expectation is not None:
            params["require_bake_aware"] = True

        bake_sent = True
        result = rhino.send_command("bake_grasshopper", params)

        bake_status = result.get("bake_status")
        if bake_status == "preflight_failed":
            return json.dumps(error(
                result.get("failure", "Guarded BakeAware preflight failed"),
                code=ErrorCode.PRECONDITION_FAILED,
                data=result,
            ))
        if bake_status == "failed_after_mutation":
            return json.dumps(error(
                result.get("failure", "Guarded BakeAware bake failed"),
                code=ErrorCode.PARTIAL_MUTATION,
                data=result,
            ))

        baked_ids, contract_issues = _canonical_baked_ids(result)
        baked_count = result.get("baked_count", 0)
        if baked_count == 0 and not contract_issues:
            return json.dumps(error(
                "Grasshopper bake produced no Rhino objects",
                code=ErrorCode.VERIFICATION_FAILED,
                data={**result, "verification": {
                    "pass": False,
                    "issues": ["no objects were baked"],
                }},
            ))
        if contract_issues:
            return json.dumps(error(
                "Grasshopper bake returned an inconsistent mutation report",
                code=ErrorCode.PARTIAL_MUTATION,
                data={**result, "verification": {
                    "pass": False,
                    "issues": contract_issues,
                    "canonical_baked_ids": baked_ids,
                }},
            ))

        readback = rhino.send_command("get_objects_info", {"ids": baked_ids})
        readback_ids, readback_issues = verify_active_object_readback(
            readback, baked_ids)
        verification = {
            "pass": not readback_issues,
            "issues": readback_issues,
            "canonical_baked_ids": baked_ids,
            "active_readback": readback,
        }
        result["verification"] = verification
        if readback_issues:
            return json.dumps(error(
                "Baked Rhino objects could not be independently verified",
                code=ErrorCode.PARTIAL_MUTATION,
                data=result,
            ))

        if bim_expectation is not None:
            bim = verify_bim_bake(
                baked_ids, bim_expectation,
                lambda object_id, kind: va_get_object(
                    ctx, object_id=object_id, expected_kind=kind),
            )
            if (result.get("guarded_bake_aware") is not True
                    or result.get("bake_mode") != "guarded_bake_aware"
                    or result.get("bake_status") != "success"):
                bim["issues"].append("Plugin did not confirm the guarded native BakeAware route")
                bim["pass"] = False
            result["bim_verification"] = bim
            verification["pass"] = bim["pass"]
            verification["issues"].extend(bim["issues"])
            if not bim["pass"]:
                return json.dumps(error(
                    "Baked objects did not pass the VisualARQ BIM contract; "
                    "objects retained, inspect before retrying",
                    code=ErrorCode.PARTIAL_MUTATION, data=result,
                ))

        layer_name = result.get("layer", "Default")
        
        return json.dumps(ok(
            message=f"Baked {baked_count} object(s) to layer '{layer_name}'",
            data=result
        ))
    except Exception as e:
        logger.error(f"Error baking Grasshopper geometry: {str(e)}")
        if bake_sent:
            return json.dumps(error(
                "Grasshopper bake may have mutated Rhino, but its final "
                "state could not be verified",
                code=ErrorCode.PARTIAL_MUTATION,
                data={
                    "bake_response": result,
                    "verification_error": str(e),
                },
            ))
        return json.dumps(from_exception(e, code=ErrorCode.RHINO_ERROR))
