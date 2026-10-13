"""Typed VisualARQ documentation-object tools.

The connected plugin owns runtime VisualARQ/GH component validation, native
BakeAware execution and independent typed readback.  These wrappers keep the
public MCP contract small and reject cheap invalid input before a Rhino
round-trip. Plan View reads are exact at the object GUID but deliberately
report unresolved Level identity; Plan View creation remains fail-closed.
"""

import json
import math
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import error, from_exception, ok


_PLAN_VIEW_READ_SCRIPT_METHODS = (
    "get_all_building_ids",
    "get_building_level_ids",
    "get_level_name",
    "get_level_elevation",
    "get_level_cut_elevation",
    "is_level",
)

_DOCUMENTATION_POSITIVE_CONTRACTS = {
    ("sections", "list"): (
        "supported", ("is_section",), ("section_read",)),
    ("sections", "read"): (
        "supported", ("is_section",), ("section_read",)),
    ("sections", "create"): (
        "conditional",
        ("is_section", "get_style_name"),
        ("section_read", "section_create"),
    ),
    ("section_views", "list"): (
        "supported", ("is_section",), ("section_view_read",)),
    ("section_views", "read"): (
        "supported", ("is_section",), ("section_view_read",)),
    ("section_views", "create"): (
        "conditional",
        ("is_section", "get_style_name"),
        ("section_read", "section_view_read", "section_view_create"),
    ),
    ("plan_views", "list"): (
        "conditional", _PLAN_VIEW_READ_SCRIPT_METHODS, ("plan_view_read",)),
    ("plan_views", "read"): (
        "conditional", _PLAN_VIEW_READ_SCRIPT_METHODS, ("plan_view_read",)),
}


def _exact_script_method_verified(
    exact_methods: Dict[str, Any],
    name: str,
) -> bool:
    evidence = exact_methods.get(name)
    if not isinstance(evidence, dict):
        return False
    expected_signature = evidence.get("expected_signature")
    exact_matches = evidence.get("exact_matches")
    return (
        evidence.get("available") is True
        and type(evidence.get("exact_match_count")) is int
        and evidence.get("exact_match_count") == 1
        and isinstance(expected_signature, str)
        and bool(expected_signature.strip())
        and isinstance(exact_matches, list)
        and len(exact_matches) == 1
        and isinstance(exact_matches[0], dict)
        and exact_matches[0].get("signature") == expected_signature
    )


def _positive_documentation_mode_is_grounded(
    object_kind: str,
    operation: str,
    capability: Dict[str, Any],
    runtime_versions: Dict[str, Any],
    script_contracts: Dict[str, Any],
    gh_contracts: Dict[str, Any],
) -> bool:
    mode = capability.get("mode")
    if mode == "unsupported":
        return True
    contract = _DOCUMENTATION_POSITIVE_CONTRACTS.get(
        (object_kind, operation))
    if contract is None:
        return False
    expected_mode, required_script_methods, required_gh_contracts = contract
    exact_methods = script_contracts.get("exact_methods")
    return (
        mode == expected_mode
        and runtime_versions.get("version_pair_verified") is True
        and isinstance(exact_methods, dict)
        and all(
            _exact_script_method_verified(exact_methods, name)
            for name in required_script_methods
        )
        and all(
            isinstance(gh_contracts.get(name), dict)
            and gh_contracts[name].get("verified") is True
            for name in required_gh_contracts
        )
    )


def _respond(
    result: Dict[str, Any],
    success_message: str,
    *,
    require_create_evidence: bool = False,
    create_entity_key: str = "section",
    require_read_guard: bool = False,
    require_hierarchy_guard: bool = False,
) -> str:
    if not isinstance(result, dict):
        return json.dumps(error(
            "VisualARQ documentation response was not an object",
            code=ErrorCode.VERIFICATION_FAILED,
            data={"response_type": type(result).__name__},
        ))
    status = result.get("status")
    if status != "success":
        code = result.get("code") if status == "error" else None
        return json.dumps(error(
            result.get("message", "VisualARQ documentation operation failed"),
            code=code or ErrorCode.VERIFICATION_FAILED,
            data=result,
        ))
    if require_create_evidence:
        entity = result.get(create_entity_key)
        bake = result.get("bake")
        verification = result.get("verification")
        complete = (
            isinstance(entity, dict)
            and bool(entity.get("id"))
            and isinstance(bake, dict)
            and bake.get("success") is True
            and isinstance(verification, dict)
            and verification.get("pass") is True
        )
        if not complete:
            return json.dumps(error(
                "VisualARQ documentation success response lacked verified "
                "creation evidence",
                code=ErrorCode.VERIFICATION_FAILED,
                data=result,
            ))
    if require_read_guard:
        state_guard = result.get("state_guard")
        style_guard = state_guard.get("visualarq_style_state", {}) \
            if isinstance(state_guard, dict) else {}
        hierarchy_guard = state_guard.get("visualarq_hierarchy_state", {}) \
            if isinstance(state_guard, dict) else {}
        guarded = (
            isinstance(state_guard, dict)
            and state_guard.get("covered_state_unchanged") is True
            and style_guard.get("unchanged") is True
            and (
                not require_hierarchy_guard
                or hierarchy_guard.get("unchanged") is True
            )
        )
        if not guarded:
            return json.dumps(error(
                "VisualARQ read success response lacked a passing state guard",
                code=ErrorCode.VERIFICATION_FAILED,
                data=result,
            ))
    return json.dumps(ok(message=success_message, data=result))


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


def _point(value: List[float], field: str) -> List[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{field} must be [x, y, z]")
    normalized = []
    for coordinate in value:
        if (
            not isinstance(coordinate, (int, float))
            or isinstance(coordinate, bool)
            or not math.isfinite(float(coordinate))
        ):
            raise ValueError(f"{field} coordinates must be finite numbers")
        normalized.append(float(coordinate))
    return normalized


def _positive_finite(value: float, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise ValueError(f"{field} must be a positive finite number")
    return float(value)


def _plan_view_boundary(value: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(value, dict) or set(value) not in (
        {"curve_id"}, {"points"},
    ):
        raise ValueError(
            "boundary must contain exactly one of curve_id or points")
    if "curve_id" in value:
        return {"curve_id": _guid(value["curve_id"], "boundary.curve_id")}

    points = value["points"]
    if not isinstance(points, list) or len(points) < 3:
        raise ValueError("boundary.points must contain at least three points")
    return {
        "points": [
            _point(point, f"boundary.points[{index}]")
            for index, point in enumerate(points)
        ],
    }


def _plan_view_depth(value: Any) -> Any:
    if isinstance(value, str):
        normalized = value.strip()
        if normalized == "no_projection":
            raise NotImplementedError(
                "Plan View no_projection encoding is not verified for "
                "VisualARQ 3.7.2")
        if normalized not in {"level", "level_below", "unlimited"}:
            raise ValueError(
                "depth must be level, level_below, unlimited, or "
                "{'custom': positive number}")
        return normalized
    if not isinstance(value, dict) or set(value) != {"custom"}:
        raise ValueError(
            "depth must be level, level_below, unlimited, or "
            "{'custom': positive number}")
    return {"custom": _positive_finite(value["custom"], "depth.custom")}


def _respond_plan_view_read(
    result: Dict[str, Any],
    success_message: str,
    expected_plan_view_id: Optional[str] = None,
) -> str:
    if isinstance(result, dict) and result.get("status") == "success":
        if "plan_views" in result:
            entities = result.get("plan_views")
        else:
            entity = result.get("plan_view")
            entities = [entity] if isinstance(entity, dict) else None
        honest_entities = (
            isinstance(entities, list)
            and all(
                isinstance(entity, dict)
                and bool(entity.get("id"))
                and (
                    expected_plan_view_id is None
                    or entity.get("id") == expected_plan_view_id
                )
                and entity.get("identity_verified") is True
                and entity.get("readback_complete") is True
                and isinstance(entity.get("level"), dict)
                and entity["level"].get("id") is None
                and entity["level"].get("identity_status") == "unresolved"
                and entity["level"].get("identity_verified") is False
                for entity in entities
            )
        )
        if not (
            result.get("read_complete") is True
            and result.get("identity_complete") is False
            and result.get("level_identity_verified") is False
            and honest_entities
        ):
            return json.dumps(error(
                "VisualARQ Plan View read response blurred unresolved Level "
                "identity or lacked exact Plan View identity evidence",
                code=ErrorCode.VERIFICATION_FAILED,
                data=result,
            ))
    return _respond(
        result,
        success_message,
        require_read_guard=True,
        require_hierarchy_guard=True,
    )


def _respond_plan_view_create_gate(result: Dict[str, Any]) -> str:
    if isinstance(result, dict) and result.get("status") == "success":
        return json.dumps(error(
            "VisualARQ Plan View creation cannot report success before the "
            "exact Level identity bridge is released",
            code=ErrorCode.VERIFICATION_FAILED,
            data=result,
        ))
    if (
        isinstance(result, dict)
        and result.get("status") == "error"
        and result.get("code") == "UNSUPPORTED_OPERATION"
    ):
        state_guard = result.get("state_guard")
        style_guard = state_guard.get("visualarq_style_state", {}) \
            if isinstance(state_guard, dict) else {}
        hierarchy_guard = state_guard.get("visualarq_hierarchy_state", {}) \
            if isinstance(state_guard, dict) else {}
        evidence_complete = (
            result.get("phase") == "pre_solve_pre_bake"
            and result.get("mutation_phase_started") is False
            and result.get("graph_constructed") is False
            and result.get("solve_attempted") is False
            and result.get("bake_attempted") is False
            and result.get("level_identity_verified") is False
            and isinstance(state_guard, dict)
            and state_guard.get("covered_state_unchanged") is True
            and style_guard.get("unchanged") is True
            and hierarchy_guard.get("unchanged") is True
        )
        if not evidence_complete:
            return json.dumps(error(
                "VisualARQ Plan View unsupported response lacked complete "
                "pre-solve/pre-bake state evidence",
                code=ErrorCode.VERIFICATION_FAILED,
                data=result,
            ))
    return _respond(result, "VisualARQ Plan View create capability checked")


def _respond_section_style_create_gate(result: Dict[str, Any]) -> str:
    """Accept only the guarded VA 3.7.2 pre-mutation capability result."""
    if isinstance(result, dict) and result.get("status") == "success":
        return json.dumps(error(
            "VisualARQ Section Style creation cannot report success without "
            "a complete document-wide Section Style inventory",
            code=ErrorCode.VERIFICATION_FAILED,
            data=result,
        ))
    if (
        isinstance(result, dict)
        and result.get("status") == "error"
        and result.get("code") == "UNSUPPORTED_OPERATION"
    ):
        state_guard = result.get("state_guard")
        style_guard = state_guard.get("visualarq_style_state", {}) \
            if isinstance(state_guard, dict) else {}
        collision_guard = result.get("collision_guard")
        runtime_contract = result.get("runtime_contract")
        creator = runtime_contract.get("creator", {}) \
            if isinstance(runtime_contract, dict) else {}
        evidence_complete = (
            result.get("phase") == "pre_proxy_pre_solve_pre_bake"
            and result.get("mutation_phase_started") is False
            and result.get("proxy_instantiation_attempted") is False
            and result.get("graph_constructed") is False
            and result.get("solve_attempted") is False
            and result.get("solve_count") == 0
            and result.get("bake_attempted") is False
            and result.get("bake_count") == 0
            and isinstance(collision_guard, dict)
            and collision_guard.get("required_inventory_method")
            == "GetAllSectionStyleIds"
            and collision_guard.get("inventory_complete") is False
            and collision_guard.get("name_absence_proven") is False
            and isinstance(runtime_contract, dict)
            and runtime_contract.get("script_version_verified") is True
            and creator.get("guid")
            == "1450aecb-482e-4691-bba5-00572baf2c35"
            and isinstance(state_guard, dict)
            and state_guard.get("covered_state_unchanged") is True
            and style_guard.get("unchanged") is True
        )
        if not evidence_complete:
            return json.dumps(error(
                "VisualARQ Section Style unsupported response lacked complete "
                "pre-proxy/pre-solve/pre-bake evidence",
                code=ErrorCode.VERIFICATION_FAILED,
                data=result,
            ))
    return _respond(result, "VisualARQ Section Style create capability checked")


def _respond_documentation_capabilities(result: Dict[str, Any]) -> str:
    """Accept only the complete, read-only documentation capability schema."""
    if isinstance(result, dict) and result.get("status") == "success":
        objects = result.get("documentation_objects")
        execution = result.get("execution")
        approved_version = result.get("approved_visualarq_version")
        runtime_versions = result.get("runtime_versions")
        script_contracts = result.get("script_contracts")
        gh_contracts = result.get("gh_contracts")
        required_gh_contracts = {
            "section_read",
            "section_create",
            "section_style_creator",
            "section_view_read",
            "section_view_create",
            "plan_view_read",
        }
        valid = (
            result.get("schema_version") == "1.0"
            and result.get("read_only") is True
            and isinstance(approved_version, str)
            and bool(approved_version.strip())
            and isinstance(runtime_versions, dict)
            and runtime_versions.get("approved") == approved_version
            and isinstance(
                runtime_versions.get("script_version_verified"), bool)
            and isinstance(
                runtime_versions.get("gh_version_verified"), bool)
            and isinstance(
                runtime_versions.get("all_gh_contracts_verified"), bool)
            and isinstance(
                runtime_versions.get("version_pair_verified"), bool)
            and isinstance(script_contracts, dict)
            and isinstance(script_contracts.get("assembly"), list)
            and isinstance(script_contracts.get("exact_methods"), dict)
            and isinstance(script_contracts.get("method_families"), dict)
            and isinstance(gh_contracts, dict)
            and required_gh_contracts <= set(gh_contracts)
            and all(
                isinstance(gh_contracts.get(name), dict)
                and isinstance(
                    gh_contracts[name].get("verified"), bool)
                for name in required_gh_contracts
            )
            and runtime_versions.get("version_pair_verified")
            == (
                runtime_versions.get("script_version_verified") is True
                and runtime_versions.get("gh_version_verified") is True
            )
            and runtime_versions.get("all_gh_contracts_verified")
            == all(
                gh_contracts[name].get("verified") is True
                for name in required_gh_contracts
            )
            and isinstance(objects, dict)
            and isinstance(execution, dict)
            and execution.get("document_mutation_attempted") is False
            and execution.get("gh_document_constructed") is False
            and execution.get("gh_solve_attempted") is False
            and type(execution.get("gh_solve_count")) is int
            and execution.get("gh_solve_count") == 0
            and execution.get("bake_attempted") is False
            and type(execution.get("bake_count")) is int
            and execution.get("bake_count") == 0
        )
        for object_kind in ("sections", "section_views", "plan_views"):
            operations = objects.get(object_kind) \
                if isinstance(objects, dict) else None
            if not isinstance(operations, dict):
                valid = False
                continue
            for operation in ("list", "read", "create", "style_create"):
                capability = operations.get(operation)
                valid = valid and (
                    isinstance(capability, dict)
                    and capability.get("mode") in {
                        "supported", "conditional", "unsupported",
                    }
                    and isinstance(capability.get("requirements"), list)
                    and all(
                        isinstance(value, str) and bool(value.strip())
                        for value in capability.get("requirements", [])
                    )
                    and isinstance(capability.get("blockers"), list)
                    and all(
                        isinstance(value, str) and bool(value.strip())
                        for value in capability.get("blockers", [])
                    )
                    and (
                        capability.get("mode") != "unsupported"
                        or bool(capability.get("blockers"))
                    )
                    and _positive_documentation_mode_is_grounded(
                        object_kind,
                        operation,
                        capability,
                        runtime_versions,
                        script_contracts,
                        gh_contracts,
                    )
                )
        if (
            isinstance(runtime_versions, dict)
            and runtime_versions.get("version_pair_verified") is False
            and isinstance(objects, dict)
        ):
            valid = valid and all(
                capability.get("mode") == "unsupported"
                for operations in objects.values()
                if isinstance(operations, dict)
                for capability in operations.values()
                if isinstance(capability, dict)
            )
        if not valid:
            return json.dumps(error(
                "VisualARQ documentation capability response lacked the "
                "complete read-only semantic contract",
                code=ErrorCode.VERIFICATION_FAILED,
                data=result,
            ))
    return _respond(
        result,
        "VisualARQ documentation capabilities reflected and verified",
        require_read_guard=True,
        require_hierarchy_guard=True,
    )


@mcp.tool()
def va_documentation_capabilities(ctx: Context) -> str:
    """Report truthful runtime capabilities for VA documentation objects.

    The plugin reflects exact public VisualARQ Script signatures and validates
    the installed, version-pinned Grasshopper proxies without constructing a
    GH document, solving, baking, or mutating Rhino. For Sections, Section
    Views, and Plan Views it distinguishes ``supported``, ``conditional``,
    and ``unsupported`` list/read/create/style-create modes with concrete
    requirements and blockers.
    """
    try:
        result = get_rhino_connection().send_command(
            "va_documentation_capabilities", {})
        return _respond_documentation_capabilities(result)
    except Exception as exc:
        logger.error(
            "Error reading VisualARQ documentation capabilities: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_list_sections(ctx: Context) -> str:
    """List every active VisualARQ Section with typed GH deconstruction.

    The plugin scans active Rhino objects through ``VisualARQ.Script.IsSection``
    and then independently reloads each match as ``GhVaSection``. A partial
    scan is an error and includes per-object readback evidence.
    """
    try:
        result = get_rhino_connection().send_command("va_list_sections", {})
        return _respond(
            result,
            f"Listed {result.get('count', 0)} VisualARQ section(s)",
            require_read_guard=True,
        )
    except Exception as exc:
        logger.error("Error listing VisualARQ sections: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_get_section(ctx: Context, section_id: str) -> str:
    """Read one VisualARQ Section by GUID and independently deconstruct it."""
    try:
        canonical_id = _guid(section_id, "section_id")
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))

    try:
        result = get_rhino_connection().send_command(
            "va_get_section", {"section_id": canonical_id})
        return _respond(
            result,
            "VisualARQ Section read and verified",
            require_read_guard=True,
        )
    except Exception as exc:
        logger.error("Error reading VisualARQ Section: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_create_section(
    ctx: Context,
    start: List[float],
    end: List[float],
    depth: float,
    reference: str,
    style_id: str,
) -> str:
    """Create one straight VisualARQ Section from an existing Section Style.

    Parameters:
        start: Section-line start point ``[x, y, z]`` in document units.
        end: Section-line end point at the same World-Z elevation.
        depth: Positive section depth in document units.
        reference: Non-empty reference text shown by the Section mark.
        style_id: Existing document-resident VisualARQ Section Style GUID.

    The plugin validates the installed VA component GUIDs and exact ports,
    solves one transient native GH graph once, invokes one native BakeAware
    strategy, and succeeds only after typed document-resident readback. This
    first contract does not create styles and does not claim a visually tested
    viewer/target side.
    """
    try:
        normalized_start = _point(start, "start")
        normalized_end = _point(end, "end")
        if (
            not isinstance(depth, (int, float))
            or isinstance(depth, bool)
            or not math.isfinite(float(depth))
            or float(depth) <= 0
        ):
            raise ValueError("depth must be a positive finite number")
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("reference is required")
        canonical_style_id = _guid(style_id, "style_id")
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))

    try:
        result = get_rhino_connection().send_command(
            "va_create_section",
            {
                "start": normalized_start,
                "end": normalized_end,
                "depth": float(depth),
                "reference": reference.strip(),
                "style_id": canonical_style_id,
            },
        )
        return _respond(
            result,
            "VisualARQ Section created and verified",
            require_create_evidence=True,
        )
    except Exception as exc:
        logger.error("Error creating VisualARQ Section: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_create_section_style(ctx: Context, name: str) -> str:
    """Validate a Section Style name, then fail closed before mutation.

    The installed VisualARQ 3.7.2 GH component can produce a valid native
    ``GhVaSectionStyle`` with version-pinned defaults. However, its public API
    exposes neither a complete document-wide Section Style enumerator nor a
    name-to-GUID lookup. The plugin therefore cannot prove name uniqueness or
    ownership of a +1 style delta and returns ``UNSUPPORTED_OPERATION`` before
    proxy construction, solve, or bake, together with complete state evidence.
    """
    if not isinstance(name, str) or not name.strip():
        return json.dumps(from_exception(
            ValueError("name must be a non-empty string"),
            code=ErrorCode.INVALID_PARAMS,
        ))

    try:
        result = get_rhino_connection().send_command(
            "va_create_section_style", {"name": name.strip()})
        return _respond_section_style_create_gate(result)
    except Exception as exc:
        logger.error("Error checking VisualARQ Section Style creation: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_list_section_views(ctx: Context) -> str:
    """List every active VisualARQ Section View with exact typed readback.

    VisualARQ Script 3.7.2 has no ``IsSectionView`` method. The plugin instead
    attempts the version-pinned ``GhVaSectionView(Guid).LoadObject`` contract,
    then deconstructs every match into insertion point, exact source Section
    GUID, title, projection, auto-update and style identity. Any incomplete
    match or failed covered-state/style guard fails the complete inventory.
    """
    try:
        result = get_rhino_connection().send_command(
            "va_list_section_views", {})
        return _respond(
            result,
            f"Listed {result.get('count', 0)} VisualARQ Section View(s)",
            require_read_guard=True,
        )
    except Exception as exc:
        logger.error("Error listing VisualARQ Section Views: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_get_section_view(ctx: Context, section_view_id: str) -> str:
    """Read one VisualARQ Section View by exact document object GUID."""
    try:
        canonical_id = _guid(section_view_id, "section_view_id")
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))

    try:
        result = get_rhino_connection().send_command(
            "va_get_section_view", {"section_view_id": canonical_id})
        return _respond(
            result,
            "VisualARQ Section View read and verified",
            require_read_guard=True,
        )
    except Exception as exc:
        logger.error("Error reading VisualARQ Section View: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_create_section_view(
    ctx: Context,
    section_id: str,
    insertion_point: List[float],
    title: str,
    style_id: str,
    projection: bool = True,
    auto_update: bool = True,
) -> str:
    """Create one VisualARQ Section View linked to an existing Section.

    Parameters:
        section_id: Exact GUID of an active document-resident VA Section.
        insertion_point: View insertion point ``[x, y, z]`` in document units.
        title: Non-empty Section View title.
        style_id: Existing document-resident VA Section View Style GUID.
        projection: Include geometry behind the source Section plane.
        auto_update: Keep the view associated with source-model changes.

    The VA 3.7.2 handler uses one exact native Grasshopper graph and one
    ``IGH_BakeAwareData`` strategy. Success requires one owned Rhino object,
    non-empty instance geometry and independent typed readback of the source
    Section GUID, insertion point, all options and style identity. Dynamic
    update and delete-cascade behavior remain explicit live scratch gates.
    """
    try:
        canonical_section_id = _guid(section_id, "section_id")
        canonical_style_id = _guid(style_id, "style_id")
        normalized_point = _point(insertion_point, "insertion_point")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title is required")
        if not isinstance(projection, bool):
            raise ValueError("projection must be a boolean")
        if not isinstance(auto_update, bool):
            raise ValueError("auto_update must be a boolean")
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))

    try:
        result = get_rhino_connection().send_command(
            "va_create_section_view",
            {
                "section_id": canonical_section_id,
                "insertion_point": normalized_point,
                "title": title.strip(),
                "style_id": canonical_style_id,
                "projection": projection,
                "auto_update": auto_update,
            },
        )
        return _respond(
            result,
            "VisualARQ Section View created and verified",
            require_create_evidence=True,
            create_entity_key="section_view",
        )
    except Exception as exc:
        logger.error("Error creating VisualARQ Section View: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_list_plan_views(ctx: Context) -> str:
    """List document-resident VisualARQ Plan Views without guessing Levels.

    Every match must load as the exact version-pinned ``GhVaPlanView`` type
    and roundtrip the scanned Rhino GUID through ``ReferenceID``. The plugin
    deconstructs boundary, options and Level semantics with one transient
    solve per object. Because VA 3.7.2 exposes no authoritative Level GUID
    bridge, every result intentionally carries ``level.id=null`` and
    ``level.identity_verified=false``.
    """
    try:
        result = get_rhino_connection().send_command(
            "va_list_plan_views", {})
        return _respond_plan_view_read(
            result,
            f"Listed {result.get('count', 0)} VisualARQ Plan View(s)",
        )
    except Exception as exc:
        logger.error("Error listing VisualARQ Plan Views: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_get_plan_view(ctx: Context, plan_view_id: str) -> str:
    """Read one VisualARQ Plan View by its exact Rhino object GUID.

    Plan View identity is verified exactly. Level identity remains explicitly
    unresolved even when its name and elevations happen to match one Level.
    """
    try:
        canonical_id = _guid(plan_view_id, "plan_view_id")
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))

    try:
        result = get_rhino_connection().send_command(
            "va_get_plan_view", {"plan_view_id": canonical_id})
        return _respond_plan_view_read(
            result,
            "VisualARQ Plan View read with unresolved Level identity",
            expected_plan_view_id=canonical_id,
        )
    except Exception as exc:
        logger.error("Error reading VisualARQ Plan View: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_create_plan_view(
    ctx: Context,
    level_id: str,
    style_id: str,
    insertion_point: List[float],
    boundary: Dict[str, Any],
    title: str = "%<level.name>%",
    depth: Any = "unlimited",
    scale: float = 1.0,
    auto_update: bool = False,
    show_boundary: bool = False,
    plan_type: Literal["floor", "reflected_ceiling"] = "floor",
) -> str:
    """Validate a future Plan View request, then fail closed before mutation.

    VisualARQ 3.7.2 does not expose a public, authoritative conversion from a
    document Level GUID to ``GhVaLevel``. The plugin therefore proves that no
    graph, solve or bake began and returns ``UNSUPPORTED_OPERATION``. This
    tool must not be treated as a partial creator or semantic Level fallback.

    ``boundary`` contains exactly one of ``{"curve_id": GUID}`` or
    ``{"points": [[x, y, z], ...]}``. ``depth`` is ``level``,
    ``level_below``, ``unlimited`` or ``{"custom": positive_number}``.
    """
    try:
        canonical_level_id = _guid(level_id, "level_id")
        canonical_style_id = _guid(style_id, "style_id")
        normalized_point = _point(insertion_point, "insertion_point")
        normalized_boundary = _plan_view_boundary(boundary)
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")
        normalized_depth = _plan_view_depth(depth)
        normalized_scale = _positive_finite(scale, "scale")
        if not isinstance(auto_update, bool):
            raise ValueError("auto_update must be a boolean")
        if not isinstance(show_boundary, bool):
            raise ValueError("show_boundary must be a boolean")
        if plan_type not in {"floor", "reflected_ceiling"}:
            raise ValueError(
                "plan_type must be floor or reflected_ceiling")
    except NotImplementedError as exc:
        return json.dumps(error(
            str(exc),
            code=ErrorCode.UNSUPPORTED_OPERATION,
            data={
                "phase": "python_preflight",
                "roundtrip_attempted": False,
            },
        ))
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))

    try:
        result = get_rhino_connection().send_command(
            "va_create_plan_view",
            {
                "level_id": canonical_level_id,
                "style_id": canonical_style_id,
                "insertion_point": normalized_point,
                "boundary": normalized_boundary,
                "title": title.strip(),
                "depth": normalized_depth,
                "scale": normalized_scale,
                "auto_update": auto_update,
                "show_boundary": show_boundary,
                "plan_type": plan_type,
            },
        )
        return _respond_plan_view_create_gate(result)
    except Exception as exc:
        logger.error("Error checking VisualARQ Plan View creation: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))
