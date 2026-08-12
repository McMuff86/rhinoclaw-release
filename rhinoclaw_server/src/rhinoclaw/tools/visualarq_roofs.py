"""Truthful VisualARQ Roof capabilities, inspection and authoring.

The connected C# plugin reflects the exact loaded ``VisualARQ.Script``
assembly and owns document-delta/readback verification.  These wrappers reject
cheap input errors and refuse optimistic success envelopes.  VisualARQ 3.7.2
authoring is intentionally a pre-mutation ``UNSUPPORTED_OPERATION`` with the
externally monitored panel-prime/native-Move workflow; the direct curve API is
admitted only for an exact three-parameter method on VisualARQ >=3.8,<4 and is
Hip-only until ridge-axis control has an authoritative input/readback binding.
"""

import json
import math
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import error, from_exception, ok


RoofType = Literal["shed", "gable", "hip"]
_ROOF_TYPES = {"shed", "gable", "hip"}


def _guid(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty GUID")
    try:
        parsed = UUID(value.strip())
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a non-empty GUID") from exc
    if parsed.int == 0:
        raise ValueError(f"{field} must be a non-empty GUID")
    return str(parsed)


def _optional_slope(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0
        or float(value) >= math.pi / 2
    ):
        raise ValueError("slope_radians must be finite and between 0 and pi/2")
    return float(value)


def _optional_height(
    value: Optional[float],
    roof_type: str,
) -> Optional[float]:
    if value is None:
        return None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise ValueError("gable_height must be a positive finite number")
    if roof_type == "hip":
        raise ValueError("gable_height is only valid for shed or gable roofs")
    return float(value)


def _state_guard_passes(
    result: Dict[str, Any],
    *,
    require_style_guard: bool,
) -> bool:
    state_guard = result.get("state_guard")
    if not isinstance(state_guard, dict):
        return False
    if state_guard.get("covered_state_unchanged") is not True:
        return False
    if not require_style_guard:
        return True
    style_guard = state_guard.get("visualarq_roof_style_state")
    return (
        isinstance(style_guard, dict)
        and style_guard.get("covered") is True
        and style_guard.get("unchanged") is True
    )


def _finite_nonempty_bbox(value: Any) -> bool:
    """Validate a measured axis-aligned ``{min,max}`` bounding box."""
    if not isinstance(value, dict):
        return False
    points = []
    for key in ("min", "max"):
        point = value.get(key)
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            return False
        if any(
            not isinstance(coordinate, (int, float))
            or isinstance(coordinate, bool)
            or not math.isfinite(float(coordinate))
            for coordinate in point
        ):
            return False
        points.append([float(coordinate) for coordinate in point])
    minimum, maximum = points
    if any(low > high for low, high in zip(minimum, maximum)):
        return False
    return any(low < high for low, high in zip(minimum, maximum))


def _nonempty_guid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return UUID(value.strip()).int != 0
    except (TypeError, ValueError, AttributeError):
        return False


def _native_bbox_evidence_complete(entity: Dict[str, Any]) -> bool:
    """Accept only a direct or fully guarded instance-definition bbox."""
    bbox = entity.get("native_bbox")
    source = entity.get("native_bbox_source")
    status = entity.get("native_bbox_status")
    if not (
        _finite_nonempty_bbox(bbox)
        and source in {
            "top_level_geometry",
            "instance_definition_geometry_traversal",
        }
        and isinstance(status, dict)
        and status.get("status") == "resolved"
        and status.get("resolved") is True
        and status.get("source") == source
        and status.get("bbox") == bbox
        and status.get("failure_code") is None
        and status.get("failure") is None
    ):
        return False
    if source == "top_level_geometry":
        return (
            status.get("top_level_bbox_valid") is True
            and status.get("fallback_attempted") is False
            and entity.get("top_level_native_bbox") == bbox
        )
    root_definition_id = status.get("root_instance_definition_id")
    definition_ids = status.get("definition_ids")
    definition_visit_count = status.get("definition_visit_count")
    unique_definition_count = status.get("unique_definition_count")
    member_count = status.get("member_count")
    leaf_geometry_count = status.get("leaf_geometry_count")
    max_depth_observed = status.get("max_depth_observed")
    max_depth_limit = status.get("max_depth_limit")
    max_member_limit = status.get("max_member_limit")
    valid_definition_ids = (
        isinstance(definition_ids, list)
        and all(_nonempty_guid(item) for item in definition_ids)
        and len(set(definition_ids)) == len(definition_ids)
    )
    return (
        status.get("top_level_bbox_valid") is False
        and status.get("fallback_attempted") is True
        and status.get("fallback_eligible") is True
        and status.get("fallback_complete") is True
        and status.get("ownership_verified") is True
        and status.get("transform_chain_verified") is True
        and status.get("cycle_detected") is False
        and _nonempty_guid(root_definition_id)
        and valid_definition_ids
        and root_definition_id in definition_ids
        and type(definition_visit_count) is int
        and definition_visit_count >= 1
        and type(unique_definition_count) is int
        and unique_definition_count == len(definition_ids)
        and 1 <= unique_definition_count <= definition_visit_count
        and type(member_count) is int
        and member_count >= definition_visit_count
        and type(leaf_geometry_count) is int
        and 1 <= leaf_geometry_count <= member_count
        and type(max_depth_observed) is int
        and max_depth_observed >= 0
        and type(max_depth_limit) is int
        and max_depth_observed <= max_depth_limit
        and type(max_member_limit) is int
        and member_count <= max_member_limit
        and entity.get("top_level_native_bbox") is None
    )


def _respond_read(
    result: Dict[str, Any],
    success_message: str,
    *,
    entity_key: Optional[str] = None,
    list_key: Optional[str] = None,
    require_style_guard: bool = True,
) -> str:
    if not isinstance(result, dict):
        return json.dumps(error(
            "VisualARQ Roof response was not an object",
            code=ErrorCode.VERIFICATION_FAILED,
            data={"response_type": type(result).__name__},
        ))
    if result.get("status") != "success":
        return json.dumps(error(
            result.get("message", "VisualARQ Roof operation failed"),
            code=result.get("code") or ErrorCode.VERIFICATION_FAILED,
            data=result,
        ))
    if not _state_guard_passes(
        result, require_style_guard=require_style_guard,
    ):
        return json.dumps(error(
            "VisualARQ Roof read lacked a passing covered-state guard",
            code=ErrorCode.VERIFICATION_FAILED,
            data=result,
        ))
    if entity_key is not None:
        entity = result.get(entity_key)
        if not (
            isinstance(entity, dict)
            and bool(entity.get("id"))
            and entity.get("identity_verified") is True
            and entity.get("readback_complete") is True
            and isinstance(entity.get("style_id"), str)
            and _finite_nonempty_bbox(entity.get("contour_bbox"))
            and _native_bbox_evidence_complete(entity)
            and isinstance(entity.get("slopes_radians"), list)
            and isinstance(entity.get("slopes_applicable"), bool)
            and (
                entity.get("slopes_applicable") is False
                or len(entity["slopes_radians"]) > 0
            )
            and isinstance(entity.get("axis"), dict)
            and entity["axis"].get("status") == "unresolved"
        ):
            return json.dumps(error(
                "VisualARQ Roof success lacked complete measured readback",
                code=ErrorCode.VERIFICATION_FAILED,
                data=result,
            ))
    if list_key is not None:
        items = result.get(list_key)
        if not (
            isinstance(items, list)
            and type(result.get("count")) is int
            and result["count"] == len(items)
            and result.get("read_complete") is True
        ):
            return json.dumps(error(
                "VisualARQ Roof inventory success was incomplete",
                code=ErrorCode.VERIFICATION_FAILED,
                data=result,
            ))
    return json.dumps(ok(message=success_message, data=result))


def _respond_capabilities(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return json.dumps(error(
            "VisualARQ Roof capability response was not an object",
            code=ErrorCode.VERIFICATION_FAILED,
        ))
    if result.get("status") != "success":
        return json.dumps(error(
            result.get("message", "VisualARQ Roof capability check failed"),
            code=result.get("code") or ErrorCode.VERIFICATION_FAILED,
            data=result,
        ))
    authoring = result.get("authoring")
    execution = result.get("execution")
    valid = (
        result.get("schema_version") == "1.0"
        and result.get("read_only") is True
        and isinstance(result.get("available"), bool)
        and isinstance(authoring, dict)
        and authoring.get("mode") in {
            "direct_api", "external_interactive_required", "unsupported",
        }
        and isinstance(authoring.get("direct_curve_api_supported"), bool)
        and isinstance(authoring.get("legacy_fallback"), dict)
        and authoring["legacy_fallback"].get("executed_by_this_tool") is False
        and isinstance(execution, dict)
        and execution.get("document_mutation_attempted") is False
        and execution.get("native_command_attempted") is False
        and execution.get("ui_automation_attempted") is False
        and _state_guard_passes(result, require_style_guard=False)
    )
    runtime = result.get("runtime")
    if result.get("available") is True:
        valid = valid and (
            isinstance(runtime, dict)
            and runtime.get("loaded") is True
            and isinstance(result.get("method_contracts"), dict)
        )
    if authoring.get("mode") == "direct_api":
        valid = valid and (
            authoring.get("direct_curve_api_supported") is True
            and authoring.get("direct_supported_roof_types") == ["hip"]
            and authoring.get("axis_dependent_roof_types") == ["shed", "gable"]
            and authoring.get("axis_control_authoritatively_bound") is False
            and isinstance(runtime, dict)
            and runtime.get("direct_version_approved") is True
            and runtime.get("direct_create_contract_complete") is True
        )
    if not valid:
        return json.dumps(error(
            "VisualARQ Roof capability response lacked the complete semantic contract",
            code=ErrorCode.VERIFICATION_FAILED,
            data=result,
        ))
    return json.dumps(ok(
        message="VisualARQ Roof capabilities reflected and guarded",
        data=result,
    ))


def _respond_create(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return json.dumps(error(
            "VisualARQ Roof authoring response was not an object",
            code=ErrorCode.VERIFICATION_FAILED,
        ))
    if result.get("status") == "error":
        if result.get("code") == "UNSUPPORTED_OPERATION":
            fallback = result.get("legacy_fallback")
            fallback_steps = result.get("fallback_steps")
            evidence_complete = (
                result.get("phase", "").startswith("pre_mutation_")
                and result.get("mutation_phase_started") is False
                and isinstance(fallback, dict)
                and fallback.get("executed_by_this_tool") is False
                and isinstance(fallback_steps, list)
                and len(fallback_steps) >= 5
            )
            if not evidence_complete:
                return json.dumps(error(
                    "Unsupported Roof authoring response lacked complete "
                    "pre-mutation fallback evidence",
                    code=ErrorCode.VERIFICATION_FAILED,
                    data=result,
                ))
        return json.dumps(error(
            result.get("message", "VisualARQ Roof authoring failed"),
            code=result.get("code") or ErrorCode.VERIFICATION_FAILED,
            data=result,
        ))
    if result.get("status") != "success":
        return json.dumps(error(
            "VisualARQ Roof authoring returned an unknown status",
            code=ErrorCode.VERIFICATION_FAILED,
            data=result,
        ))
    roof = result.get("roof")
    verification = result.get("verification")
    mutation = result.get("mutation_evidence")
    persistence = result.get("persistence")
    contour_topology = verification.get("contour_topology") \
        if isinstance(verification, dict) else None
    boundary_match = verification.get("boundary_match") \
        if isinstance(verification, dict) else None
    complete = (
        result.get("authoring_route") == "direct_api_visualarq_3_8_plus"
        and isinstance(roof, dict)
        and roof.get("roof_type") == "hip"
        and roof.get("identity_verified") is True
        and roof.get("readback_complete") is True
        and isinstance(roof.get("style_id"), str)
        and _finite_nonempty_bbox(roof.get("contour_bbox"))
        and _native_bbox_evidence_complete(roof)
        and isinstance(roof.get("slopes_radians"), list)
        and isinstance(verification, dict)
        and verification.get("pass") is True
        and verification.get("axis_control_applicable") is False
        and verification.get("axis_control_verified") is False
        and isinstance(contour_topology, dict)
        and contour_topology.get("pass") is True
        and contour_topology.get("valid") is True
        and contour_topology.get("manifold") is True
        and contour_topology.get("face_count") == 1
        and contour_topology.get("outer_loop_count") == 1
        and contour_topology.get("inner_loop_count") == 0
        and isinstance(boundary_match, dict)
        and boundary_match.get("pass") is True
        and boundary_match.get("same_bbox_alone_is_accepted") is False
        and boundary_match.get("perimeter_matches") is True
        and boundary_match.get("area_matches") is True
        and boundary_match.get("sampling_matches") is True
        and boundary_match.get("max_bidirectional_deviation") is not None
        and isinstance(mutation, dict)
        and mutation.get("success") is True
        and mutation.get("ownership_proven") is True
        and isinstance(persistence, dict)
        and persistence.get("live_document_verified") is True
        and persistence.get("save_reopen_required") is True
        and persistence.get("save_reopen_verified") is False
    )
    if not complete:
        return json.dumps(error(
            "VisualARQ Roof success lacked independent creation/readback evidence",
            code=ErrorCode.VERIFICATION_FAILED,
            data=result,
        ))
    return json.dumps(ok(
        message=(
            "VisualARQ Roof created and live-readback verified; Save-New-Open "
            "persistence remains a required follow-up"
        ),
        data=result,
    ))


@mcp.tool()
def va_roof_capabilities(ctx: Context) -> str:
    """Report exact VisualARQ Roof read/style/authoring capabilities.

    This read-only tool reflects the loaded ``VisualARQ.Script`` method shapes
    and product version. It distinguishes direct API authoring (VisualARQ
    >=3.8,<4 with the exact three-parameter method, Hip only) from the
    externally monitored Shed/Gable/VisualARQ-3.7.2 fallback.
    """
    try:
        result = get_rhino_connection().send_command(
            "va_roof_capabilities", {})
        return _respond_capabilities(result)
    except Exception as exc:
        logger.error("Error reading VisualARQ Roof capabilities: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_list_roof_styles(ctx: Context) -> str:
    """List document Roof Styles with exact slope-style linkage/thickness."""
    try:
        result = get_rhino_connection().send_command(
            "va_list_roof_styles", {})
        response = _respond_read(
            result,
            f"Listed {result.get('count', 0)} VisualARQ Roof Style(s)",
            list_key="styles",
        )
        parsed = json.loads(response)
        if parsed.get("success") is True:
            styles = parsed["data"]["styles"]
            if not all(
                isinstance(item, dict)
                and bool(item.get("id"))
                and bool(item.get("name"))
                and bool(item.get("slope_style_id"))
                and item.get("readback_complete") is True
                and isinstance(item.get("thickness"), (int, float))
                for item in styles
            ):
                return json.dumps(error(
                    "VisualARQ Roof Style inventory lacked complete readback",
                    code=ErrorCode.VERIFICATION_FAILED,
                    data=result,
                ))
        return response
    except Exception as exc:
        logger.error("Error listing VisualARQ Roof Styles: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_list_roofs(ctx: Context) -> str:
    """List every active top-level VisualARQ Roof with measured readback."""
    try:
        result = get_rhino_connection().send_command("va_list_roofs", {})
        response = _respond_read(
            result,
            f"Listed {result.get('count', 0)} VisualARQ Roof(s)",
            list_key="roofs",
        )
        parsed = json.loads(response)
        if parsed.get("success") is True:
            roofs = parsed["data"]["roofs"]
            if not all(
                isinstance(item, dict)
                and item.get("identity_verified") is True
                and item.get("readback_complete") is True
                and _finite_nonempty_bbox(item.get("contour_bbox"))
                and _native_bbox_evidence_complete(item)
                and isinstance(item.get("slopes_radians"), list)
                and isinstance(item.get("slopes_applicable"), bool)
                and (
                    item.get("slopes_applicable") is False
                    or len(item["slopes_radians"]) > 0
                )
                and item.get("axis", {}).get("status") == "unresolved"
                for item in roofs
            ):
                return json.dumps(error(
                    "VisualARQ Roof inventory contained incomplete readback",
                    code=ErrorCode.VERIFICATION_FAILED,
                    data=result,
                ))
        return response
    except Exception as exc:
        logger.error("Error listing VisualARQ Roofs: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_get_roof(ctx: Context, roof_id: str) -> str:
    """Read one VisualARQ Roof by exact Rhino object GUID.

    Returns measured ProductStyle GUID/name, type, contour/native bounding
    boxes, slope slots and Gable/Shed height. Ridge-axis identity remains
    explicitly unresolved because no approved public binding exists.
    """
    try:
        canonical_id = _guid(roof_id, "roof_id")
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))
    try:
        result = get_rhino_connection().send_command(
            "va_get_roof", {"roof_id": canonical_id})
        return _respond_read(
            result,
            "VisualARQ Roof read and independently verified",
            entity_key="roof",
        )
    except Exception as exc:
        logger.error("Error reading VisualARQ Roof: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_create_roof_from_curve(
    ctx: Context,
    style_id: str,
    boundary_curve_id: str,
    roof_type: RoofType,
    slope_radians: Optional[float] = None,
    gable_height: Optional[float] = None,
) -> str:
    """Create or route one verified Shed/Gable/Hip Roof request.

    The boundary must be one active valid, closed, horizontal planar curve.
    ``slope_radians`` is optional and, when present, is applied to every slope
    slot. ``gable_height`` is optional for Shed/Gable only. Direct mutation is
    Hip-only and admitted only for the exact VisualARQ >=3.8,<4 API. Shed and
    Gable fail before create-command send until ridge-axis control has an
    authoritative input/readback contract. Direct Hip is accepted only after
    single-object delta, ProductStyle, type, Brep topology, bidirectional
    contour-form comparison, slope, native geometry and instance-definition
    ownership readback.

    On VisualARQ 3.7.2 this tool deterministically returns
    ``UNSUPPORTED_OPERATION`` before mutation plus ``fallback_steps`` for the
    externally monitored panel-prime/FromCurves/native-Move workflow. A direct
    success still requires later Save-New-Open plus ``va_get_roof`` before
    claiming artifact persistence.
    """
    try:
        canonical_style_id = _guid(style_id, "style_id")
        canonical_curve_id = _guid(boundary_curve_id, "boundary_curve_id")
        if roof_type not in _ROOF_TYPES:
            raise ValueError("roof_type must be shed, gable, or hip")
        normalized_slope = _optional_slope(slope_radians)
        normalized_height = _optional_height(gable_height, roof_type)
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))

    params: Dict[str, Any] = {
        "style_id": canonical_style_id,
        "boundary_curve_id": canonical_curve_id,
        "roof_type": roof_type,
    }
    if normalized_slope is not None:
        params["slope_radians"] = normalized_slope
    if normalized_height is not None:
        params["gable_height"] = normalized_height
    try:
        rhino = get_rhino_connection()
        capability = rhino.send_command("va_roof_capabilities", {})
        capability_response = json.loads(_respond_capabilities(capability))
        if capability_response.get("success") is not True:
            return json.dumps(capability_response)
        authoring = capability_response["data"]["authoring"]
        if authoring.get("mode") != "direct_api":
            fallback = authoring.get("legacy_fallback")
            fallback_steps = fallback.get("required_steps", []) \
                if isinstance(fallback, dict) else []
            return _respond_create({
                "status": "error",
                "code": "UNSUPPORTED_OPERATION",
                "message": (
                    "Direct VisualARQ Roof authoring is unavailable in the "
                    "loaded runtime; the create command was not sent"
                ),
                "phase": "pre_mutation_python_capability_gate",
                "mutation_phase_started": False,
                "create_command_sent": False,
                "authoring": authoring,
                "legacy_fallback": fallback,
                "fallback_steps": fallback_steps,
                "runtime": capability_response["data"].get("runtime"),
            })
        supported_types = authoring.get("direct_supported_roof_types", [])
        if roof_type not in supported_types:
            fallback = authoring.get("legacy_fallback")
            fallback_steps = fallback.get("required_steps", []) \
                if isinstance(fallback, dict) else []
            return _respond_create({
                "status": "error",
                "code": "UNSUPPORTED_OPERATION",
                "message": (
                    "Direct Shed/Gable Roof authoring is unavailable because "
                    "ridge-axis control cannot be authoritatively verified; "
                    "the create command was not sent"
                ),
                "phase": "pre_mutation_python_axis_capability_gate",
                "mutation_phase_started": False,
                "create_command_sent": False,
                "blocker": "axis_control_unavailable",
                "axis_control_verified": False,
                "direct_supported_roof_types": supported_types,
                "authoring": authoring,
                "legacy_fallback": fallback,
                "fallback_steps": fallback_steps,
                "runtime": capability_response["data"].get("runtime"),
            })
        result = rhino.send_command("va_create_roof_from_curve", params)
        return _respond_create(result)
    except Exception as exc:
        logger.error("Error creating VisualARQ Roof from curve: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))
