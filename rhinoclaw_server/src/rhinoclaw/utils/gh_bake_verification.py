"""Shared verification helpers for Grasshopper bake mutation reports.

This module owns reusable *mechanics*: GUID/readback contracts, semantic
measurement assembly and exact-ID cleanup.  Individual tools still decide
when a failed domain verdict should trigger cleanup and how to classify the
failure.
"""

import math
from typing import Any
from uuid import UUID


def canonical_nonempty_guids(
    raw_ids: Any,
    *,
    field_name: str = "ids",
) -> tuple[list[str], list[str]]:
    """Canonicalize a GUID list and report every structural defect."""
    if not isinstance(raw_ids, list):
        return [], [f"{field_name} must be a list"]

    canonical: list[str] = []
    issues: list[str] = []
    for index, raw_id in enumerate(raw_ids):
        try:
            parsed = UUID(str(raw_id))
        except (TypeError, ValueError, AttributeError):
            issues.append(f"{field_name}[{index}] is not a GUID")
            continue
        if parsed.int == 0:
            issues.append(f"{field_name}[{index}] is the empty GUID")
            continue
        canonical.append(str(parsed))

    if len(canonical) != len(set(canonical)):
        issues.append(f"{field_name} contains duplicate GUIDs")
    return canonical, issues


def verify_active_object_readback(
    readback: Any,
    expected_ids: list[str],
) -> tuple[list[str], list[str]]:
    """Verify that ``get_objects_info`` resolves exactly the expected IDs."""
    if not isinstance(readback, dict):
        return [], ["get_objects_info response must be an object"]

    issues: list[str] = []
    count = readback.get("count")
    missing_count = readback.get("missing_count")
    results = readback.get("results")
    missing = readback.get("missing")

    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        issues.append("get_objects_info count must be a non-negative integer")
    elif count != len(expected_ids):
        issues.append("get_objects_info count does not match baked GUID count")

    if (
        not isinstance(missing_count, int)
        or isinstance(missing_count, bool)
        or missing_count < 0
    ):
        issues.append(
            "get_objects_info missing_count must be a non-negative integer"
        )
    elif missing_count != 0:
        issues.append("one or more baked GUIDs are not active")

    if not isinstance(results, list):
        issues.append("get_objects_info results must be a list")
        results = []
    elif len(results) != len(expected_ids):
        issues.append("get_objects_info result length does not match baked GUID count")

    if not isinstance(missing, list):
        issues.append("get_objects_info missing must be a list")
    elif missing:
        issues.append("get_objects_info returned missing-object evidence")

    raw_result_ids = [
        item.get("id") if isinstance(item, dict) else None
        for item in results
    ]
    result_ids, result_id_issues = canonical_nonempty_guids(
        raw_result_ids,
        field_name="get_objects_info.results[].id",
    )
    issues.extend(result_id_issues)
    if (
        len(result_ids) != len(expected_ids)
        or set(result_ids) != set(expected_ids)
    ):
        issues.append(
            "active Rhino GUID readback does not match the bake report"
        )
    return result_ids, issues


def verify_object_properties_readback(
    readback: Any,
    expected_ids: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalize and verify the legacy single/batch mass-property response.

    ``get_object_properties`` returns one object directly for a one-ID call,
    but ``{objects, count}`` for a batch.  Callers must not infer a missing
    item from that shape difference, so normalize it once here and require an
    exact GUID set in both cases.
    """
    if not isinstance(readback, dict):
        return [], ["get_object_properties response must be an object"]

    issues: list[str] = []
    if "objects" in readback:
        results = readback.get("objects")
        count = readback.get("count")
        if not isinstance(results, list):
            issues.append("get_object_properties objects must be a list")
            results = []
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            issues.append(
                "get_object_properties count must be a non-negative integer"
            )
        elif count != len(results):
            issues.append(
                "get_object_properties count does not match result length"
            )
    else:
        results = [readback]

    if len(results) != len(expected_ids):
        issues.append(
            "get_object_properties result length does not match baked GUID count"
        )

    raw_ids = [
        item.get("id") if isinstance(item, dict) else None
        for item in results
    ]
    result_ids, id_issues = canonical_nonempty_guids(
        raw_ids,
        field_name="get_object_properties.results[].id",
    )
    issues.extend(id_issues)
    if len(result_ids) != len(expected_ids) or set(result_ids) != set(expected_ids):
        issues.append(
            "mass-property GUID readback does not match the bake report"
        )

    normalized = [item for item in results if isinstance(item, dict)]
    return normalized, issues


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def summarize_baked_geometry(
    object_info: Any,
    object_properties: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build semantic measurements from authoritative Rhino readbacks.

    No requested value enters this summary.  Unknown or unsupported fields
    remain ``None`` and completeness flags stay false; partial sums are never
    promoted to verified totals.
    """
    info_results = object_info.get("results", []) \
        if isinstance(object_info, dict) else []

    properties_by_id: dict[str, dict[str, Any]] = {}
    for item in object_properties or []:
        if not isinstance(item, dict):
            continue
        canonical, issues = canonical_nonempty_guids(
            [item.get("id")], field_name="object_properties.id")
        if canonical and not issues:
            properties_by_id[canonical[0]] = item

    objects: list[dict[str, Any]] = []
    for info in info_results:
        if not isinstance(info, dict):
            continue
        canonical, issues = canonical_nonempty_guids(
            [info.get("id")], field_name="object_info.id")
        object_id = canonical[0] if canonical and not issues else None
        properties = properties_by_id.get(object_id or "", {})

        geometry = info.get("geometry_details")
        geometry = geometry if isinstance(geometry, dict) else {}
        brep = info.get("brep_details")
        brep = brep if isinstance(brep, dict) else {}
        mesh = info.get("mesh_details")
        mesh = mesh if isinstance(mesh, dict) else {}
        curve = info.get("curve_details")
        curve = curve if isinstance(curve, dict) else {}

        geometry_type = geometry.get("type") \
            if isinstance(geometry.get("type"), str) else None
        object_type = geometry.get("object_type") \
            if isinstance(geometry.get("object_type"), str) \
            else (info.get("type") if isinstance(info.get("type"), str) else None)

        is_valid = geometry.get("is_valid")
        is_valid = is_valid if isinstance(is_valid, bool) else None

        property_solid = properties.get("is_solid")
        property_solid = property_solid \
            if isinstance(property_solid, bool) else None
        brep_solid = brep.get("is_solid")
        brep_solid = brep_solid if isinstance(brep_solid, bool) else None
        mesh_closed = mesh.get("is_closed")
        mesh_closed = mesh_closed if isinstance(mesh_closed, bool) else None
        curve_closed = curve.get("is_closed")
        curve_closed = curve_closed if isinstance(curve_closed, bool) else None

        is_solid = property_solid
        if is_solid is None:
            is_solid = brep_solid if brep_solid is not None else mesh_closed

        is_closed = curve_closed
        if is_closed is None:
            is_closed = mesh_closed
        if is_closed is None:
            is_closed = brep_solid
        if is_closed is None:
            is_closed = property_solid

        topology: dict[str, int | None] = {
            "face_count": _nonnegative_int(
                brep.get("face_count", mesh.get("face_count"))
            ),
            "edge_count": _nonnegative_int(brep.get("edge_count")),
            "vertex_count": _nonnegative_int(
                brep.get("vertex_count", mesh.get("vertex_count"))
            ),
        }

        objects.append({
            "id": object_id,
            "geometry_type": geometry_type,
            "object_type": object_type,
            "layer": info.get("layer")
            if isinstance(info.get("layer"), str) else None,
            "is_valid": is_valid,
            "is_closed": is_closed,
            "is_solid": is_solid,
            "area": _finite_number(properties.get("area")),
            "volume": _finite_number(properties.get("volume")),
            "topology": topology,
        })

    def complete_all(field: str) -> bool | None:
        values = [item.get(field) for item in objects]
        if not values or any(not isinstance(value, bool) for value in values):
            return None
        return all(values)

    def complete_total(field: str) -> tuple[float | None, bool]:
        values = [item.get(field) for item in objects]
        complete = bool(values) and all(value is not None for value in values)
        return (sum(values) if complete else None, complete)

    total_area, area_complete = complete_total("area")
    total_volume, volume_complete = complete_total("volume")

    topology_totals: dict[str, int | None] = {}
    topology_complete: dict[str, bool] = {}
    for field in ("face_count", "edge_count", "vertex_count"):
        values = [item["topology"].get(field) for item in objects]
        complete = bool(values) and all(value is not None for value in values)
        topology_complete[field] = complete
        topology_totals[field] = sum(values) if complete else None

    return {
        "objects": objects,
        "aggregate": {
            "all_valid": complete_all("is_valid"),
            "all_closed": complete_all("is_closed"),
            "all_solid": complete_all("is_solid"),
            "geometry_types": [item["geometry_type"] for item in objects],
            "object_types": [item["object_type"] for item in objects],
            "layers": [item["layer"] for item in objects],
            "total_area": total_area,
            "area_complete": area_complete,
            "total_volume": total_volume,
            "volume_complete": volume_complete,
            "topology": topology_totals,
            "topology_complete": topology_complete,
        },
    }


def verify_objects_absent(
    readback: Any,
    expected_ids: list[str],
) -> list[str]:
    """Require exact ``not_found`` evidence for every cleanup target."""
    if not isinstance(readback, dict):
        return ["cleanup get_objects_info response must be an object"]

    issues: list[str] = []
    if readback.get("count") != 0:
        issues.append("one or more cleanup targets are still active")
    if readback.get("results") != []:
        issues.append("cleanup readback returned active object payloads")

    missing_count = readback.get("missing_count")
    if missing_count != len(expected_ids):
        issues.append("cleanup missing_count does not match target count")
    missing = readback.get("missing")
    if not isinstance(missing, list):
        issues.append("cleanup missing evidence must be a list")
        return issues

    raw_ids = [
        item.get("id") if isinstance(item, dict) else None
        for item in missing
    ]
    missing_ids, id_issues = canonical_nonempty_guids(
        raw_ids, field_name="cleanup.missing[].id")
    issues.extend(id_issues)
    if len(missing_ids) != len(expected_ids) \
            or set(missing_ids) != set(expected_ids):
        issues.append("cleanup absence GUIDs do not match target GUIDs")
    if any(
        not isinstance(item, dict) or item.get("reason") != "not_found"
        for item in missing
    ):
        issues.append("cleanup absence reason must be not_found for every GUID")
    return issues


def cleanup_reported_baked_objects(
    rhino: Any,
    raw_ids: Any,
    *,
    scope_complete: bool,
) -> dict[str, Any]:
    """Delete only reported bake GUIDs, then prove their exact absence.

    ``scope_complete`` must be true only after a consistent mutation report.
    A malformed report can still be cleaned best-effort, but can never be
    represented as a complete rollback because unreported geometry is outside
    the known ownership set.
    """
    canonical, contract_issues = canonical_nonempty_guids(
        raw_ids, field_name="cleanup_ids")
    targets = list(dict.fromkeys(canonical))
    operation_issues: list[str] = []
    deleted_ids: list[str] = []

    for object_id in targets:
        try:
            result = rhino.send_command("delete_object", {"id": object_id})
            if not isinstance(result, dict) or result.get("deleted") is not True:
                operation_issues.append(
                    f"delete_object did not confirm deletion for {object_id}"
                )
                continue
            returned, returned_issues = canonical_nonempty_guids(
                [result.get("id")], field_name="delete_object.id")
            if returned_issues or returned != [object_id]:
                operation_issues.append(
                    f"delete_object returned the wrong GUID for {object_id}"
                )
                continue
            deleted_ids.append(object_id)
        except Exception as exc:  # final absence, not the exception, is truth
            operation_issues.append(f"delete_object failed for {object_id}: {exc}")

    absence_issues: list[str] = []
    absence_readback: Any = None
    if targets:
        try:
            absence_readback = rhino.send_command(
                "get_objects_info", {"ids": targets})
            absence_issues = verify_objects_absent(absence_readback, targets)
        except Exception as exc:
            absence_issues = [f"cleanup absence readback failed: {exc}"]

    absence_verified = not absence_issues
    cleanup_pass = (
        absence_verified
        and scope_complete
        and not contract_issues
    )
    unmeasured_or_retained = [
        "bake layer and material table changes",
        "written Grasshopper definition file",
    ]
    if not scope_complete or contract_issues:
        unmeasured_or_retained.append(
            "objects omitted by an inconsistent mutation report"
        )
    return {
        "requested": True,
        "attempted": bool(targets),
        "scope": "reported_baked_objects_only",
        "scope_complete": scope_complete and not contract_issues,
        "target_ids": targets,
        "deleted_ids": deleted_ids,
        "operation_issues": operation_issues,
        "absence_readback": absence_readback,
        "absence_verified": absence_verified,
        "verification_issues": contract_issues + absence_issues,
        "pass": cleanup_pass,
        "unmeasured_or_retained": unmeasured_or_retained,
    }
