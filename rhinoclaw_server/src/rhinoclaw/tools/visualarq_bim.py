"""Closed VisualARQ BIM snapshots, deltas, and semantic critique."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.tools.visualarq import (
    _HIERARCHY_SCRIPT_HELPERS,
    _OBJECT_SCRIPT_HELPERS,
    _STYLE_SCRIPT_HELPERS,
    _UNAVAILABLE_HINT,
)
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import error, from_exception, ok
from rhinoclaw.utils.visualarq import run_va, va_unavailable, warm_va


_SNAPSHOT_SCHEMA = "rhinoclaw.visualarq.bim-snapshot.v1"
_CATEGORIES = ("buildings", "levels", "styles", "visualarq_objects")
_MAX_ENTITIES = 5000


_SNAPSHOT_BODY = (
    _STYLE_SCRIPT_HELPERS
    + _OBJECT_SCRIPT_HELPERS
    + _HIERARCHY_SCRIPT_HELPERS
    + r"""
import scriptcontext as sc
from System.Diagnostics import FileVersionInfo, Process

styles = va_global_style_inventory()
hierarchy = va_hierarchy_snapshot()
objects = []
scan_errors = []
scan_error_count = 0
matched_count = 0
style_cache = {}

for obj in sc.doc.Objects:
    identity_probe = va_visualarq_identity_probe(obj.Id)
    if identity_probe["match"] is None:
        scan_error_count += 1
        if len(scan_errors) < 100:
            scan_errors.append({
                "object_id": str(obj.Id), "stage": "identity",
                "errors": identity_probe["errors"],
            })
        continue
    if identity_probe["match"] is False:
        continue
    matched_count += 1
    classification_probe = va_object_classification_probe(obj.Id)
    snapshot = va_product_snapshot(
        obj, classification_probe, True, True, style_cache)
    if snapshot is None:
        scan_error_count += 1
        if len(scan_errors) < 100:
            scan_errors.append({
                "object_id": str(obj.Id), "stage": "product_snapshot",
                "errors": classification_probe["errors"],
            })
        continue
    if snapshot.get("readback_complete") is not True:
        scan_error_count += 1
        if len(scan_errors) < 100:
            scan_errors.append({
                "object_id": str(obj.Id), "stage": "product_readback",
                "errors": snapshot.get("readback_errors", []),
            })
    if len(objects) < params["max_entities"]:
        objects.append(snapshot)

version = None
file_version = None
product_version = None
assembly_version = None
try:
    assembly_version = str(va_assembly.GetName().Version)
    version_info = FileVersionInfo.GetVersionInfo(va_assembly.Location)
    file_version = str(version_info.FileVersion or "") or None
    product_version = str(version_info.ProductVersion or "") or None
    version = product_version or file_version or assembly_version
except Exception:
    version = assembly_version

process = Process.GetCurrentProcess()
result = {
    "status": "success",
    "document": {
        "runtime_serial_number": int(sc.doc.RuntimeSerialNumber),
        "path": str(sc.doc.Path or "") or None,
        "modified": bool(sc.doc.Modified),
        "units": str(sc.doc.ModelUnitSystem),
        "absolute_tolerance": float(sc.doc.ModelAbsoluteTolerance),
        "relative_tolerance": float(sc.doc.ModelRelativeTolerance),
        "angle_tolerance_radians": float(
            sc.doc.ModelAngleToleranceRadians),
        "process_id": int(process.Id),
        "process_start_ticks": int(process.StartTime.Ticks),
    },
    "visualarq": {
        "version": version,
        "product_version": product_version,
        "file_version": file_version,
        "assembly_version": assembly_version,
    },
    "buildings": hierarchy["buildings"],
    "levels": hierarchy["levels"],
    "styles": styles["styles"],
    "visualarq_objects": objects,
    "source_verification": {
        "hierarchy": hierarchy["verification"],
        "styles": {
            "read_complete": styles["read_complete"],
            "readback_errors": styles["readback_errors"],
            "inventory_methods": styles["inventory_methods"],
            "inventory_counts": styles["inventory_counts"],
            "coverage": styles["coverage"],
        },
        "objects": {
            "matched_count": matched_count,
            "returned_count": len(objects),
            "truncated": matched_count > len(objects),
            "scan_complete": scan_error_count == 0,
            "scan_error_count": scan_error_count,
            "scan_errors": scan_errors,
            "scan_errors_truncated": scan_error_count > len(scan_errors),
        },
        "product_level_contract": {
            "authoritative_link_available": False,
            "source": "loaded VisualARQ.Script public static reflection",
            "reason": (
                "VisualARQ 3.11 exposes Building/Level hierarchy getters "
                "but no public Product-to-Level getter"),
        },
    },
}
"""
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _style_kind(inventory_method: Any) -> Optional[str]:
    if not isinstance(inventory_method, str):
        return None
    if inventory_method == "GetAllBeamStyle":
        return "beam"
    match = re.fullmatch(r"GetAll(.+)StyleIds", inventory_method)
    if match is None:
        return None
    name = match.group(1)
    words = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return words


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    return normalized if math.isfinite(normalized) else None


def _object_datum(item: Dict[str, Any]) -> Optional[float]:
    kind = item.get("kind")
    if kind == "wall":
        path = item.get("path")
        if isinstance(path, dict):
            start = path.get("start")
            end = path.get("end")
            if (
                isinstance(start, list)
                and isinstance(end, list)
                and len(start) == 3
                and len(end) == 3
            ):
                start_z = _finite(start[2])
                end_z = _finite(end[2])
                if start_z is not None and end_z is not None:
                    return (start_z + end_z) / 2.0
    if kind == "slab":
        contour = item.get("contour")
        bbox = contour.get("bbox") if isinstance(contour, dict) else None
        if isinstance(bbox, dict):
            minimum = bbox.get("min")
            maximum = bbox.get("max")
            if (
                isinstance(minimum, list)
                and isinstance(maximum, list)
                and len(minimum) == 3
                and len(maximum) == 3
            ):
                low = _finite(minimum[2])
                high = _finite(maximum[2])
                if low is not None and high is not None:
                    return (low + high) / 2.0
    if kind == "space":
        return _finite(item.get("elevation"))
    geometry = item.get("geometry")
    bbox_min = geometry.get("bbox_min") if isinstance(geometry, dict) else None
    if isinstance(bbox_min, list) and len(bbox_min) == 3:
        return _finite(bbox_min[2])
    return None


def _object_metrics(item: Dict[str, Any]) -> Dict[str, Any]:
    kind = item.get("kind")
    metrics: Dict[str, Any] = {
        "area": None,
        "gross_area": None,
        "volume": None,
        "gross_volume": None,
        "volume_source": None,
        "volume_verified": False,
    }
    if kind == "wall":
        path = item.get("path")
        height = _finite(item.get("height"))
        thickness = _finite(item.get("thickness"))
        length = _finite(path.get("length")) if isinstance(path, dict) else None
        if length is not None and height is not None:
            metrics["gross_area"] = length * height
        quantity = item.get("quantity")
        if isinstance(quantity, dict) and quantity.get("volume_verified") is True:
            volume = _finite(quantity.get("volume"))
            if volume is not None:
                metrics["volume"] = volume
                metrics["volume_source"] = quantity.get("source")
                metrics["volume_verified"] = True
        if all(
            value is not None for value in (length, height, thickness)
        ):
            metrics["gross_volume"] = length * height * thickness
    elif kind == "slab":
        contour = item.get("contour")
        area = _finite(contour.get("area")) if isinstance(contour, dict) else None
        thickness = _finite(item.get("thickness"))
        metrics["area"] = area
        if area is not None and thickness is not None:
            metrics["gross_volume"] = area * thickness
    elif kind == "space":
        metrics["area"] = _finite(item.get("area"))
        metrics["volume"] = _finite(item.get("volume"))
        if metrics["volume"] is not None:
            metrics["volume_source"] = "GetSpaceVolume"
            metrics["volume_verified"] = True
    return metrics


def _augment_entities(raw: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    entities: Dict[str, List[Dict[str, Any]]] = {}
    levels = raw.get("levels") if isinstance(raw.get("levels"), list) else []
    tolerance = _finite((raw.get("document") or {}).get("absolute_tolerance"))
    tolerance = tolerance if tolerance is not None and tolerance > 0 else 0.01

    for category in _CATEGORIES:
        values = raw.get(category)
        if not isinstance(values, list):
            values = []
        entities[category] = [dict(value) for value in values if isinstance(value, dict)]

    for style in entities["styles"]:
        style["kind"] = _style_kind(style.get("inventory_method"))
        components = style.get("component_ids")
        style["component_count"] = len(components) if isinstance(components, list) else None

    for item in entities["visualarq_objects"]:
        datum = _object_datum(item)
        matches = []
        if datum is not None:
            for level in levels:
                elevation = _finite(level.get("elevation"))
                if elevation is not None and abs(elevation - datum) <= tolerance:
                    matches.append(level)
        item["datum_elevation"] = datum
        item["datum_level"] = {
            "match_count": len(matches),
            "level_id": matches[0].get("id") if len(matches) == 1 else None,
            "level_name": matches[0].get("name") if len(matches) == 1 else None,
            "level_elevation": matches[0].get("elevation")
            if len(matches) == 1
            else None,
            "source": "semantic_geometry_datum",
            "authoritative_object_link": False,
        }
        item["metrics"] = _object_metrics(item)

    for category in _CATEGORIES:
        entities[category].sort(key=lambda item: str(item.get("id") or ""))
    return entities


def _build_inventory(
    entities: Dict[str, List[Dict[str, Any]]],
) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, str], str]:
    inventories: Dict[str, List[Dict[str, str]]] = {}
    for category in _CATEGORIES:
        entries = []
        seen = set()
        for entity in entities[category]:
            identity = entity.get("id")
            if not isinstance(identity, str) or not identity or identity in seen:
                raise ValueError(f"{category} contains an invalid or duplicate identity")
            seen.add(identity)
            entries.append({
                "identity": identity,
                "state_sha256": _canonical_sha256(entity),
            })
        entries.sort(key=lambda item: item["identity"])
        inventories[category] = entries
    hashes = {
        category: _canonical_sha256(inventories[category])
        for category in _CATEGORIES
    }
    return inventories, hashes, _canonical_sha256(hashes)


def _derive_verification(
    source: Any,
    entities: Dict[str, List[Dict[str, Any]]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    hierarchy = source.get("hierarchy") if isinstance(source, dict) else None
    styles = source.get("styles") if isinstance(source, dict) else None
    objects = source.get("objects") if isinstance(source, dict) else None
    issues = []
    if not isinstance(hierarchy, dict) or hierarchy.get("pass") is not True:
        issues.append("Building/Level hierarchy inventory is incomplete")
    if not isinstance(styles, dict) or styles.get("read_complete") is not True:
        issues.append("global VisualARQ style inventory is incomplete")
    if not isinstance(objects, dict) or objects.get("scan_complete") is not True:
        issues.append("VisualARQ object inventory is incomplete")
    if isinstance(objects, dict) and objects.get("truncated") is True:
        issues.append("VisualARQ object inventory is truncated")
    for category in _CATEGORIES:
        incomplete = [
            entity.get("id")
            for entity in entities[category]
            if entity.get("readback_complete") is not True
        ]
        if incomplete:
            issues.append(
                f"{category} contains incomplete readbacks: "
                + ", ".join(str(value) for value in incomplete[:10])
            )
    hierarchy_scope = (
        hierarchy.get("inventory_scope") if isinstance(hierarchy, dict) else None
    )
    mutation_baseline_complete = bool(
        isinstance(hierarchy, dict)
        and hierarchy.get("mutation_baseline_complete") is True
    )
    promotion_blockers = list(issues)
    if not mutation_baseline_complete:
        promotion_blockers.append(
            "global Level inventory/orphan check is unavailable in the loaded "
            "VisualARQ.Script API"
        )
    verification = {
        "pass": not issues,
        "issues": issues,
        "source": source,
    }
    eligibility = {
        "measured_state_comparison": not issues,
        "gh02_promotion": not promotion_blockers,
        "hierarchy_inventory_scope": hierarchy_scope,
        "global_level_inventory_available": bool(
            isinstance(hierarchy, dict)
            and hierarchy.get("global_level_inventory_available") is True
        ),
        "mutation_baseline_complete": mutation_baseline_complete,
        "blockers": promotion_blockers,
    }
    return verification, eligibility


def _evidence_hashes(
    document: Any,
    visualarq: Any,
    source: Any,
    fingerprint: str,
    verification: Dict[str, Any],
    eligibility: Dict[str, Any],
) -> Dict[str, str]:
    document_hash = _canonical_sha256(document)
    visualarq_hash = _canonical_sha256(visualarq)
    source_hash = _canonical_sha256(source)
    evidence_fingerprint = _canonical_sha256({
        "document_sha256": document_hash,
        "visualarq_sha256": visualarq_hash,
        "source_verification_sha256": source_hash,
        "inventory_fingerprint": fingerprint,
        "verification": verification,
        "baseline_eligibility": eligibility,
    })
    return {
        "document_sha256": document_hash,
        "visualarq_sha256": visualarq_hash,
        "source_verification_sha256": source_hash,
        "evidence_fingerprint": evidence_fingerprint,
    }


def _finalize_snapshot(raw: Dict[str, Any]) -> Dict[str, Any]:
    entities = _augment_entities(raw)
    inventories, hashes, fingerprint = _build_inventory(entities)
    source = raw.get("source_verification")
    verification, eligibility = _derive_verification(source, entities)
    document = raw.get("document")
    visualarq = raw.get("visualarq")
    evidence_hashes = _evidence_hashes(
        document,
        visualarq,
        source,
        fingerprint,
        verification,
        eligibility,
    )
    snapshot = {
        "schema_version": _SNAPSHOT_SCHEMA,
        "complete": verification["pass"],
        "document": document,
        "visualarq": visualarq,
        "entities": entities,
        "inventories": inventories,
        "inventory_hashes": hashes,
        "fingerprint": fingerprint,
        "verification": verification,
        "baseline_eligibility": eligibility,
    }
    snapshot.update(evidence_hashes)
    return snapshot


def _validate_snapshot(snapshot: Any, label: str) -> Dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise ValueError(f"{label} must be a BIM snapshot object")
    if snapshot.get("schema_version") != _SNAPSHOT_SCHEMA:
        raise ValueError(f"{label}.schema_version is unsupported")
    entities = snapshot.get("entities")
    if not isinstance(entities, dict) or set(entities) != set(_CATEGORIES):
        raise ValueError(f"{label}.entities does not have the closed category set")
    normalized: Dict[str, List[Dict[str, Any]]] = {}
    for category in _CATEGORIES:
        values = entities.get(category)
        if not isinstance(values, list) or not all(isinstance(v, dict) for v in values):
            raise ValueError(f"{label}.entities.{category} must be an object array")
        normalized[category] = values
    inventories, hashes, fingerprint = _build_inventory(normalized)
    if snapshot.get("inventories") != inventories:
        raise ValueError(f"{label}.inventories is not entity-derived")
    if snapshot.get("inventory_hashes") != hashes:
        raise ValueError(f"{label}.inventory_hashes is not inventory-derived")
    if snapshot.get("fingerprint") != fingerprint:
        raise ValueError(f"{label}.fingerprint is not hash-derived")
    verification = snapshot.get("verification")
    source = verification.get("source") if isinstance(verification, dict) else None
    for field, value in (
        ("document_sha256", snapshot.get("document")),
        ("visualarq_sha256", snapshot.get("visualarq")),
        ("source_verification_sha256", source),
    ):
        if snapshot.get(field) != _canonical_sha256(value):
            raise ValueError(f"{label}.{field} is not evidence-derived")
    expected_verification, expected_eligibility = _derive_verification(
        source, normalized
    )
    if verification != expected_verification:
        raise ValueError(f"{label}.verification is not source-derived")
    if snapshot.get("baseline_eligibility") != expected_eligibility:
        raise ValueError(f"{label}.baseline_eligibility is not evidence-derived")
    if snapshot.get("complete") is not expected_verification["pass"]:
        raise ValueError(f"{label}.complete is not verification-derived")
    if snapshot.get("complete") is not True:
        raise ValueError(f"{label} is not complete")
    expected_evidence_hashes = _evidence_hashes(
        snapshot.get("document"),
        snapshot.get("visualarq"),
        source,
        fingerprint,
        expected_verification,
        expected_eligibility,
    )
    for field, expected in expected_evidence_hashes.items():
        if snapshot.get(field) != expected:
            raise ValueError(f"{label}.{field} is not evidence-derived")
    return snapshot


def _snapshot_delta(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    before_document = before.get("document") or {}
    after_document = after.get("document") or {}
    if before_document.get("runtime_serial_number") != after_document.get(
        "runtime_serial_number"
    ):
        raise ValueError("baseline and current snapshot belong to different documents")
    categories = {}
    for category in _CATEGORIES:
        before_entities = {
            item["id"]: item for item in before["entities"][category]
        }
        after_entities = {
            item["id"]: item for item in after["entities"][category]
        }
        before_hashes = {
            item["identity"]: item["state_sha256"]
            for item in before["inventories"][category]
        }
        after_hashes = {
            item["identity"]: item["state_sha256"]
            for item in after["inventories"][category]
        }
        before_ids = set(before_entities)
        after_ids = set(after_entities)
        added_ids = sorted(after_ids - before_ids)
        removed_ids = sorted(before_ids - after_ids)
        changed_ids = sorted(
            identity
            for identity in before_ids & after_ids
            if before_hashes[identity] != after_hashes[identity]
        )
        categories[category] = {
            "added_ids": added_ids,
            "removed_ids": removed_ids,
            "changed_ids": changed_ids,
            "added": [after_entities[identity] for identity in added_ids],
            "removed": [before_entities[identity] for identity in removed_ids],
            "changed_before": [before_entities[identity] for identity in changed_ids],
            "changed_after": [after_entities[identity] for identity in changed_ids],
            "unchanged_baseline": not removed_ids and not changed_ids,
        }
    return {
        "baseline_fingerprint": before["fingerprint"],
        "current_fingerprint": after["fingerprint"],
        "categories": categories,
        "baseline_unchanged": all(
            value["unchanged_baseline"] for value in categories.values()
        ),
    }


def _capture_snapshot(rhino: Any, max_entities: int) -> Dict[str, Any]:
    warm_va(rhino)
    raw = run_va(rhino, _SNAPSHOT_BODY, {"max_entities": max_entities})
    if va_unavailable(raw) or raw.get("status") == "error":
        return raw
    return _finalize_snapshot(raw)


def _normalize_alignment(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = value.strip().casefold()
    if normalized in {"center", "centre", "centered", "centred", "middle"}:
        return "centered"
    return normalized


def _near(actual: Any, expected: Any, tolerance: float) -> bool:
    actual_number = _finite(actual)
    expected_number = _finite(expected)
    return (
        actual_number is not None
        and expected_number is not None
        and abs(actual_number - expected_number) <= tolerance
    )


def _point_near(actual: Any, expected: Any, tolerance: float) -> bool:
    return (
        isinstance(actual, list)
        and isinstance(expected, list)
        and len(actual) == 3
        and len(expected) == 3
        and all(_near(left, right, tolerance) for left, right in zip(actual, expected))
    )


def _entity_match(
    category: str,
    actual: Dict[str, Any],
    expected: Dict[str, Any],
    tolerance: float,
    level_names_by_id: Dict[str, str],
) -> Tuple[bool, List[str]]:
    reasons = []
    count = expected.get("count", 1)
    fields = {key: value for key, value in expected.items() if key != "count"}
    if category == "buildings":
        actual_level_names = sorted(
            level_names_by_id.get(identity)
            for identity in actual.get("level_ids", [])
            if level_names_by_id.get(identity) is not None
        )
        lookups = {
            "name": actual.get("name"),
            "elevation": actual.get("elevation"),
            "level_names": actual_level_names,
        }
    elif category == "levels":
        lookups = {
            "name": actual.get("name"),
            "elevation": actual.get("elevation"),
            "building_name": actual.get("owner_building_name"),
        }
    elif category == "styles":
        lookups = {
            "name": actual.get("name"),
            "kind": actual.get("kind"),
            "component_count": actual.get("component_count"),
        }
    else:
        geometry = actual.get("geometry") or {}
        path = actual.get("path") or {}
        metrics = actual.get("metrics") or {}
        datum_level = actual.get("datum_level") or {}
        alignment = actual.get("alignment") or {}
        lookups = {
            "kind": actual.get("kind"),
            "name": actual.get("name"),
            "style_name": actual.get("style_name"),
            "height": actual.get("height"),
            "thickness": actual.get("thickness"),
            "area": metrics.get("area"),
            "gross_area": metrics.get("gross_area"),
            "volume": metrics.get("volume"),
            "gross_volume": metrics.get("gross_volume"),
            "volume_verified": metrics.get("volume_verified"),
            "elevation": actual.get("elevation", actual.get("datum_elevation")),
            "alignment": alignment.get("name"),
            "datum_level_name": datum_level.get("level_name"),
            "authoritative_level_id": None,
            "path_start": path.get("start"),
            "path_end": path.get("end"),
            "bbox_min": geometry.get("bbox_min"),
            "bbox_max": geometry.get("bbox_max"),
        }

    numeric = {
        "elevation",
        "height",
        "thickness",
        "area",
        "gross_area",
        "volume",
        "gross_volume",
    }
    points = {"path_start", "path_end", "bbox_min", "bbox_max"}
    for field, requested in fields.items():
        observed = lookups.get(field)
        if field in numeric:
            matches = _near(observed, requested, tolerance)
        elif field in points:
            matches = _point_near(observed, requested, tolerance)
        elif field == "alignment":
            matches = _normalize_alignment(observed) == _normalize_alignment(requested)
        elif field == "level_names":
            matches = isinstance(requested, list) and actual_level_names == sorted(requested)
        else:
            matches = observed == requested
        if not matches:
            reasons.append(
                f"{field}: expected {requested!r}, observed {observed!r}"
            )
    if count < 1:
        reasons.append("count must be positive")
    return not reasons, reasons


_EXPECTATION_FIELDS = {
    "buildings": {"name", "elevation", "level_names", "count"},
    "levels": {"name", "elevation", "building_name", "count"},
    "styles": {"name", "kind", "component_count", "count"},
    "visualarq_objects": {
        "kind",
        "name",
        "style_name",
        "height",
        "thickness",
        "area",
        "gross_area",
        "volume",
        "gross_volume",
        "volume_verified",
        "elevation",
        "alignment",
        "datum_level_name",
        "authoritative_level_id",
        "path_start",
        "path_end",
        "bbox_min",
        "bbox_max",
        "count",
    },
}


def _validate_expectations(expectations: Any, baseline_present: bool) -> Dict[str, Any]:
    if not isinstance(expectations, dict) or not expectations:
        raise ValueError("expectations must be a non-empty object")
    allowed = {
        "scope",
        "tolerance",
        "unchanged_baseline",
        "require_promotion_baseline",
        "exact_counts",
        "buildings",
        "levels",
        "styles",
        "visualarq_objects",
    }
    unknown = set(expectations) - allowed
    if unknown:
        raise ValueError("unknown expectation key(s): " + ", ".join(sorted(unknown)))
    result = dict(expectations)
    scope = result.get("scope", "added" if baseline_present else "document")
    if scope not in {"added", "document"}:
        raise ValueError("expectations.scope must be 'added' or 'document'")
    if scope == "added" and not baseline_present:
        raise ValueError("expectations.scope='added' requires baseline")
    result["scope"] = scope
    tolerance = result.get("tolerance", 0.01)
    tolerance_number = _finite(tolerance)
    if tolerance_number is None or tolerance_number <= 0:
        raise ValueError("expectations.tolerance must be finite and positive")
    result["tolerance"] = tolerance_number
    unchanged = result.get("unchanged_baseline", baseline_present)
    if not isinstance(unchanged, bool):
        raise ValueError("expectations.unchanged_baseline must be boolean")
    result["unchanged_baseline"] = unchanged
    require_promotion = result.get("require_promotion_baseline", False)
    if not isinstance(require_promotion, bool):
        raise ValueError(
            "expectations.require_promotion_baseline must be boolean"
        )
    result["require_promotion_baseline"] = require_promotion

    counts = result.get("exact_counts", {})
    if not isinstance(counts, dict):
        raise ValueError("expectations.exact_counts must be an object")
    allowed_counts = set(_CATEGORIES) | {"objects_by_kind"}
    if set(counts) - allowed_counts:
        raise ValueError("expectations.exact_counts contains an unknown category")
    for key, value in counts.items():
        if key == "objects_by_kind":
            if not isinstance(value, dict) or not all(
                isinstance(kind, str)
                and kind
                and isinstance(count, int)
                and not isinstance(count, bool)
                and count >= 0
                for kind, count in value.items()
            ):
                raise ValueError("exact_counts.objects_by_kind must map kinds to non-negative integers")
        elif not (
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
        ):
            raise ValueError(f"exact_counts.{key} must be a non-negative integer")

    has_assertion = bool(counts)
    for category in _CATEGORIES:
        values = result.get(category, [])
        if not isinstance(values, list):
            raise ValueError(f"expectations.{category} must be an array")
        normalized = []
        for index, item in enumerate(values):
            if not isinstance(item, dict) or not item:
                raise ValueError(f"expectations.{category}[{index}] must be a non-empty object")
            unknown_fields = set(item) - _EXPECTATION_FIELDS[category]
            if unknown_fields:
                raise ValueError(
                    f"expectations.{category}[{index}] has unknown field(s): "
                    + ", ".join(sorted(unknown_fields))
                )
            count = item.get("count", 1)
            if not (
                isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= _MAX_ENTITIES
            ):
                raise ValueError(f"expectations.{category}[{index}].count must be 1..{_MAX_ENTITIES}")
            normalized.append(dict(item))
        result[category] = normalized
        has_assertion = has_assertion or bool(normalized)
    if not has_assertion:
        raise ValueError("expectations must contain at least one measurable assertion")
    result["exact_counts"] = counts
    return result


def _match_collection(
    category: str,
    actual: List[Dict[str, Any]],
    expected: List[Dict[str, Any]],
    tolerance: float,
    level_names_by_id: Dict[str, str],
) -> Dict[str, Any]:
    expanded = []
    for expectation_index, item in enumerate(expected):
        for copy_index in range(item.get("count", 1)):
            expanded.append((expectation_index, copy_index, item))
    adjacency = []
    mismatch_evidence = []
    for expectation_index, copy_index, item in expanded:
        candidates = []
        candidate_mismatches = []
        for actual_index, entity in enumerate(actual):
            matches, reasons = _entity_match(
                category, entity, item, tolerance, level_names_by_id
            )
            if matches:
                candidates.append(actual_index)
            elif len(candidate_mismatches) < 10:
                candidate_mismatches.append({
                    "id": entity.get("id"), "reasons": reasons,
                })
        adjacency.append(candidates)
        mismatch_evidence.append({
            "expectation_index": expectation_index,
            "copy_index": copy_index,
            "candidate_mismatches": candidate_mismatches,
        })

    matched_actual: Dict[int, int] = {}

    def assign(expectation_slot: int, visited: set[int]) -> bool:
        for actual_index in adjacency[expectation_slot]:
            if actual_index in visited:
                continue
            visited.add(actual_index)
            previous = matched_actual.get(actual_index)
            if previous is None or assign(previous, visited):
                matched_actual[actual_index] = expectation_slot
                return True
        return False

    unmatched_slots = []
    for expectation_slot in range(len(expanded)):
        if not assign(expectation_slot, set()):
            unmatched_slots.append(expectation_slot)
    matched = []
    for actual_index, expectation_slot in sorted(
        matched_actual.items(), key=lambda item: item[1]
    ):
        expectation_index, copy_index, _item = expanded[expectation_slot]
        matched.append({
            "expectation_index": expectation_index,
            "copy_index": copy_index,
            "id": actual[actual_index].get("id"),
        })
    return {
        "pass": not unmatched_slots,
        "expected_count": len(expanded),
        "matched_count": len(matched),
        "matches": matched,
        "unmatched": [mismatch_evidence[index] for index in unmatched_slots],
    }


def _critique(
    current: Dict[str, Any],
    expectations: Dict[str, Any],
    baseline: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    delta = _snapshot_delta(baseline, current) if baseline is not None else None
    if expectations["scope"] == "added":
        selected = {
            category: delta["categories"][category]["added"]
            for category in _CATEGORIES
        }
    else:
        selected = current["entities"]

    checks = []

    def add_check(name: str, passed: bool, expected: Any, actual: Any) -> None:
        checks.append({
            "name": name,
            "pass": bool(passed),
            "expected": expected,
            "actual": actual,
        })

    if baseline is not None and expectations["unchanged_baseline"]:
        add_check(
            "unchanged_baseline",
            delta["baseline_unchanged"],
            True,
            delta["baseline_unchanged"],
        )
    if expectations["require_promotion_baseline"]:
        baseline_eligible = baseline is None or (
            (baseline.get("baseline_eligibility") or {}).get(
                "gh02_promotion"
            )
            is True
        )
        current_eligible = (
            (current.get("baseline_eligibility") or {}).get("gh02_promotion")
            is True
        )
        add_check(
            "gh02_promotion_baseline",
            baseline_eligible and current_eligible,
            True,
            {
                "baseline": baseline_eligible,
                "current": current_eligible,
            },
        )

    counts = expectations["exact_counts"]
    for category in _CATEGORIES:
        if category in counts:
            add_check(
                f"exact_count.{category}",
                len(selected[category]) == counts[category],
                counts[category],
                len(selected[category]),
            )
    if "objects_by_kind" in counts:
        actual_kind_counts: Dict[str, int] = {}
        for item in selected["visualarq_objects"]:
            kind = item.get("kind")
            actual_kind_counts[kind] = actual_kind_counts.get(kind, 0) + 1
        for kind, expected_count in sorted(counts["objects_by_kind"].items()):
            add_check(
                f"exact_count.visualarq_objects.{kind}",
                actual_kind_counts.get(kind, 0) == expected_count,
                expected_count,
                actual_kind_counts.get(kind, 0),
            )

    level_names_by_id = {
        item["id"]: item.get("name")
        for item in current["entities"]["levels"]
    }
    collection_matches = {}
    for category in _CATEGORIES:
        match = _match_collection(
            category,
            selected[category],
            expectations[category],
            expectations["tolerance"],
            level_names_by_id,
        )
        collection_matches[category] = match
        if expectations[category]:
            add_check(
                f"semantic_match.{category}",
                match["pass"],
                match["expected_count"],
                match["matched_count"],
            )

    passed = all(check["pass"] for check in checks)
    return {
        "pass": passed,
        "scope": expectations["scope"],
        "tolerance": expectations["tolerance"],
        "checks": checks,
        "failed_checks": [check["name"] for check in checks if not check["pass"]],
        "matches": collection_matches,
        "selected_counts": {
            category: len(selected[category]) for category in _CATEGORIES
        },
        "delta": delta,
        "level_semantics": {
            "datum_matching_available": True,
            "datum_source": "semantic_geometry_datum",
            "authoritative_object_link_available": False,
            "reason": (
                "Loaded VisualARQ 3.11 public Script reflection exposes no "
                "Product-to-Level getter"),
        },
    }


@mcp.tool()
def va_bim_snapshot(
    ctx: Context,
    max_entities: int = _MAX_ENTITIES,
) -> str:
    """Capture one hash-derived VisualARQ BIM state snapshot.

    The closed inventory contains rich Building, Level, style and VisualARQ
    object arrays plus sorted ``identity/state_sha256`` rows, per-category
    hashes and an aggregate fingerprint. A truncated or partially readable
    category fails verification. ``baseline_eligibility`` separately reports
    whether the loaded API covers only Building-reachable Levels or also has
    the global Level/orphan inventory required for GH02 promotion.

    Object ``datum_level`` is an independently measured elevation match. Its
    ``authoritative_object_link`` is deliberately false because VisualARQ
    3.11 exposes no public Product-to-Level getter.
    """
    try:
        if (
            isinstance(max_entities, bool)
            or not isinstance(max_entities, int)
            or not 1 <= max_entities <= _MAX_ENTITIES
        ):
            raise ValueError(f"max_entities must be an integer between 1 and {_MAX_ENTITIES}")
        snapshot = _capture_snapshot(get_rhino_connection(), max_entities)
        if va_unavailable(snapshot):
            return json.dumps(error(
                _UNAVAILABLE_HINT,
                code=ErrorCode.RHINO_ERROR,
                data={"available": False},
            ))
        if snapshot.get("status") == "error":
            return json.dumps(error(
                snapshot.get("message", "VisualARQ snapshot failed"),
                code=snapshot.get("code", ErrorCode.RHINO_ERROR),
                data=snapshot,
            ))
        if snapshot.get("complete") is not True:
            return json.dumps(error(
                "VisualARQ BIM snapshot is incomplete",
                code=ErrorCode.VERIFICATION_FAILED,
                data=snapshot,
            ))
        counts = {
            category: len(snapshot["entities"][category])
            for category in _CATEGORIES
        }
        return json.dumps(ok(
            message=(
                "Captured complete VisualARQ BIM snapshot: "
                f"{counts['buildings']} building(s), {counts['levels']} level(s), "
                f"{counts['styles']} style(s), "
                f"{counts['visualarq_objects']} object(s)"
            ),
            data=snapshot,
        ))
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))
    except Exception as exc:
        logger.error("VisualARQ BIM snapshot failed: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))


@mcp.tool()
def va_critique_bim(
    ctx: Context,
    expectations: Dict[str, Any],
    baseline: Optional[Dict[str, Any]] = None,
    max_entities: int = _MAX_ENTITIES,
) -> str:
    """Judge current VisualARQ BIM state against a closed semantic contract.

    Pass a prior ``va_bim_snapshot.data`` as ``baseline`` to judge only added
    entities and prove that no baseline Building, Level, style or VisualARQ
    object was removed or changed. Expectations can assert exact category and
    object-kind counts and uniquely match Building/Level/style/product fields,
    including style, height, thickness, area, volume, alignment, path, BBox
    and geometrically proven datum-Level name.
    """
    try:
        if (
            isinstance(max_entities, bool)
            or not isinstance(max_entities, int)
            or not 1 <= max_entities <= _MAX_ENTITIES
        ):
            raise ValueError(f"max_entities must be an integer between 1 and {_MAX_ENTITIES}")
        baseline_snapshot = (
            _validate_snapshot(baseline, "baseline") if baseline is not None else None
        )
        normalized_expectations = _validate_expectations(
            expectations, baseline_snapshot is not None
        )
        current = _capture_snapshot(get_rhino_connection(), max_entities)
        if va_unavailable(current):
            return json.dumps(error(
                _UNAVAILABLE_HINT,
                code=ErrorCode.RHINO_ERROR,
                data={"available": False},
            ))
        if current.get("status") == "error":
            return json.dumps(error(
                current.get("message", "VisualARQ snapshot failed"),
                code=current.get("code", ErrorCode.RHINO_ERROR),
                data=current,
            ))
        _validate_snapshot(current, "current")
        verdict = _critique(current, normalized_expectations, baseline_snapshot)
        payload = {
            "snapshot": current,
            "expectations": normalized_expectations,
            "verdict": verdict,
        }
        if not verdict["pass"]:
            return json.dumps(error(
                "VisualARQ BIM semantic critique failed",
                code=ErrorCode.VERIFICATION_FAILED,
                data=payload,
            ))
        return json.dumps(ok(
            message="VisualARQ BIM semantic critique passed",
            data=payload,
        ))
    except ValueError as exc:
        return json.dumps(from_exception(exc, code=ErrorCode.INVALID_PARAMS))
    except Exception as exc:
        logger.error("VisualARQ BIM critique failed: %s", exc)
        return json.dumps(from_exception(exc, code=ErrorCode.RHINO_ERROR))
