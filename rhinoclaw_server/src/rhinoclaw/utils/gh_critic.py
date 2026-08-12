"""Graph-authoring critique core — pure Python (NEXT-LEVEL-PLAN 5.3).

Rhino-free and stdlib-only like `door_judge.py`, so every signal is
unit-testable. This is the deterministic half of the `build_gh_interactive`
loop: derive the right bake output from the component catalog instead of
guessing, and judge the BAKED, RE-MEASURED geometry against the caller's
expectations — never the spec's claims.

The semantic half (rewriting the graph when the critique fails) stays with
the agent between calls; everything here must stay deterministic.
"""
import math
from typing import Any, Dict, List, Optional, Sequence

# Output port types that BakeGoo cannot turn into document geometry —
# candidates of these types are tried last, not dropped (catalog `t` values).
_NON_BAKEABLE_TYPES = {
    "number", "integer", "boolean", "text", "domain", "domain²",
    "interval", "colour", "color", "time", "culture", "path", "guid",
}

_SCRIPT_TYPES = {"python3_script", "script"}
_SDK_TYPES = {"sdk_component", "sdk"}

_SEMANTIC_EXPECTATION_KEYS = {
    "geometry_types",
    "object_types",
    "layer",
    "all_valid",
    "all_closed",
    "all_solid",
    "total_volume",
    "total_area",
    "topology",
}
_MEASURABLE_EXPECTATION_KEYS = _SEMANTIC_EXPECTATION_KEYS | {
    "min_count", "dims_mm", "bbox_min", "bbox_max",
}
_TOLERANCE_KEYS = {
    "tolerance_mm", "volume_tolerance", "area_tolerance",
    "relative_tolerance",
}
_EXPECTATION_KEYS = _MEASURABLE_EXPECTATION_KEYS | _TOLERANCE_KEYS
_TOPOLOGY_KEYS = {"face_count", "edge_count", "vertex_count"}


def _catalog_index(catalog: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if not catalog:
        return {}
    return {c["guid"].lower(): c for c in catalog.get("components", [])
            if c.get("guid")}


def terminal_components(
    components: List[Dict[str, Any]],
    wires: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Components with outputs that feed no other component (the graph's end).

    Returned in REVERSE spec order — graphs are authored source→sink, so the
    last terminal component is the most likely bake target.
    """
    source_names = {w.get("from") for w in (wires or [])}
    terminals = []
    for comp in components:
        ctype = (comp.get("type") or "").lower()
        if ctype not in _SCRIPT_TYPES | _SDK_TYPES:
            continue  # sliders/panels/toggles produce values, not geometry
        if comp.get("name") in source_names:
            continue
        terminals.append(comp)
    return list(reversed(terminals))


def derive_bake_outputs(
    components: List[Dict[str, Any]],
    wires: Optional[List[Dict[str, Any]]] = None,
    catalog: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Ordered `bake_output` candidates derived from the catalog ground truth.

    The C# engine matches `bake_output` case-insensitively against output
    NICKNAMES across all components (GrasshopperDefinitionBuilder.cs:798).
    Hallucinated bake outputs are the same failure class as hallucinated
    GUIDs — so derive them: terminal components first, geometry-typed ports
    before numeric ones. Returns e.g. ["B"] for a Center Box sink, ["a"]
    for a script sink. Empty list when nothing has outputs.
    """
    guid_index = _catalog_index(catalog)
    bakeable: List[str] = []
    fallback: List[str] = []

    for comp in terminal_components(components, wires):
        ctype = (comp.get("type") or "").lower()
        if ctype in _SCRIPT_TYPES:
            for nick in ["a"] + list(comp.get("extra_outputs") or []):
                bakeable.append(str(nick))
            continue
        entry = guid_index.get(str(comp.get("guid", "")).lower())
        for port in (entry or {}).get("out") or []:
            nick = port.get("nn") or port.get("n")
            if not nick:
                continue
            port_type = (port.get("t") or "").lower()
            (fallback if port_type in _NON_BAKEABLE_TYPES else bakeable).append(nick)

    seen = set()
    ordered = []
    for nick in bakeable + fallback:
        key = nick.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(nick)
    return ordered


def bbox_dims(bbox: Optional[Sequence[Sequence[float]]]) -> Optional[List[float]]:
    """[dx, dy, dz] extents of a [[min],[max]] axis-aligned bbox."""
    if not bbox:
        return None
    return [round(bbox[1][i] - bbox[0][i], 3) for i in range(3)]


def _is_finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def validate_expectations(expect: Any) -> List[str]:
    """Validate the critic contract before any Rhino mutation is attempted."""
    if expect is None:
        return []
    if not isinstance(expect, dict):
        return ["expect must be an object"]

    errors: List[str] = []
    unknown = sorted(set(expect) - _EXPECTATION_KEYS)
    if unknown:
        errors.append(
            "Unknown expect key(s): " + ", ".join(unknown)
            + ". Unchecked expectations are rejected."
        )

    if expect and not any(key in expect for key in _MEASURABLE_EXPECTATION_KEYS):
        errors.append(
            "expect must contain at least one measurable expectation; "
            "tolerances alone do not verify geometry"
        )

    min_count = expect.get("min_count")
    if min_count is not None and (
        isinstance(min_count, bool)
        or not isinstance(min_count, int)
        or min_count < 0
    ):
        errors.append("expect.min_count must be a non-negative integer")

    for key in ("dims_mm", "bbox_min", "bbox_max"):
        vector = expect.get(key)
        if vector is None:
            continue
        if not isinstance(vector, (list, tuple)) or len(vector) != 3 \
                or any(not _is_finite_number(value) for value in vector):
            errors.append(f"expect.{key} must contain three finite numbers")

    for key in _TOLERANCE_KEYS:
        value = expect.get(key)
        if value is not None and (
            not _is_finite_number(value) or float(value) < 0
        ):
            errors.append(f"expect.{key} must be a finite non-negative number")

    for key in ("geometry_types", "object_types"):
        value = expect.get(key)
        if value is None:
            continue
        values = [value] if isinstance(value, str) else value
        if not isinstance(values, (list, tuple)) or not values or any(
            not isinstance(item, str) or not item.strip() for item in values
        ):
            errors.append(
                f"expect.{key} must be a non-empty string or string list"
            )

    layer = expect.get("layer")
    if layer is not None and (
        not isinstance(layer, str) or not layer.strip()
    ):
        errors.append("expect.layer must be a non-empty string")

    for key in ("all_valid", "all_closed", "all_solid"):
        value = expect.get(key)
        if value is not None and not isinstance(value, bool):
            errors.append(f"expect.{key} must be a boolean")

    for key in ("total_volume", "total_area"):
        value = expect.get(key)
        if value is not None and (
            not _is_finite_number(value) or float(value) < 0
        ):
            errors.append(f"expect.{key} must be a finite non-negative number")

    topology = expect.get("topology")
    if topology is not None:
        if not isinstance(topology, dict) or not topology:
            errors.append("expect.topology must be a non-empty object")
        else:
            unknown_topology = sorted(set(topology) - _TOPOLOGY_KEYS)
            if unknown_topology:
                errors.append(
                    "Unknown topology key(s): " + ", ".join(unknown_topology)
                )
            for key, value in topology.items():
                if key in _TOPOLOGY_KEYS and (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < 0
                ):
                    errors.append(
                        f"expect.topology.{key} must be a non-negative integer"
                    )
    return errors


def semantic_expectations_requested(expect: Any) -> bool:
    return isinstance(expect, dict) and any(
        key in expect for key in _SEMANTIC_EXPECTATION_KEYS
    )


def mass_properties_requested(expect: Any) -> bool:
    return isinstance(expect, dict) and any(
        key in expect
        for key in ("all_closed", "all_solid", "total_volume", "total_area")
    )


def check_expectations(
    measured_bbox: Optional[Sequence[Sequence[float]]],
    baked_count: int,
    expect: Optional[Dict[str, Any]],
    measured_semantics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Judge measured geometry against caller expectations.

    `expect` keys (all optional):
    - ``min_count``: at least N baked objects.
    - ``dims_mm``: [dx, dy, dz] expected bbox extents (world axes).
    - ``bbox_min`` / ``bbox_max``: expected bbox corners.
    - ``tolerance_mm``: allowed deviation for dims/corners (default 1.0).
    - ``geometry_types`` / ``object_types``: allowed measured Rhino types.
    - ``layer``: every baked object must read back on this layer.
    - ``all_valid`` / ``all_closed`` / ``all_solid``: exact boolean intent.
    - ``total_volume`` / ``total_area``: complete mass-property totals.
    - ``topology``: exact aggregate face/edge/vertex counts.
    - ``volume_tolerance`` / ``area_tolerance``: absolute tolerances.  When
      omitted, ``relative_tolerance`` (default 1e-6) is used.

    Only MEASURED inputs reach this function (`get_objects_info` bboxes) —
    the Goodhart rule from the door judge applies unchanged: a graph that
    claims a 40×20×10 box but bakes a 10×10×10 one must fail here.
    """
    expect = expect or {}
    tol = float(expect.get("tolerance_mm", 1.0))
    checks: List[Dict[str, Any]] = []
    hints: List[str] = []
    semantic = measured_semantics or {}
    aggregate = semantic.get("aggregate") \
        if isinstance(semantic, dict) else {}
    aggregate = aggregate if isinstance(aggregate, dict) else {}

    min_count = expect.get("min_count")
    if min_count is not None:
        ok = baked_count >= int(min_count)
        checks.append({"check": "min_count", "ok": ok,
                       "expected": int(min_count), "measured": baked_count})
        if not ok:
            hints.append(
                f"Expected ≥{min_count} baked object(s), measured "
                f"{baked_count} — the graph solves but bakes too little."
            )

    dims = bbox_dims(measured_bbox)

    expected_dims = expect.get("dims_mm")
    if expected_dims is not None:
        if dims is None:
            checks.append({"check": "dims_mm", "ok": False,
                           "expected": expected_dims, "measured": None})
            hints.append("Expected bbox dims but nothing measurable was baked.")
        else:
            errors = [round(dims[i] - float(expected_dims[i]), 3)
                      for i in range(3)]
            ok = all(abs(e) <= tol for e in errors)
            checks.append({"check": "dims_mm", "ok": ok,
                           "expected": expected_dims, "measured": dims,
                           "error_mm": errors})
            if not ok:
                axes = "xyz"
                worst = max(range(3), key=lambda i: abs(errors[i]))
                hints.append(
                    f"Bbox dims {dims} vs expected {list(expected_dims)} "
                    f"(tol {tol} mm) — worst axis {axes[worst]} off by "
                    f"{errors[worst]:+.1f} mm; check the slider value or "
                    f"wire feeding that dimension."
                )

    for key, corner_idx in (("bbox_min", 0), ("bbox_max", 1)):
        expected_corner = expect.get(key)
        if expected_corner is None:
            continue
        if measured_bbox is None:
            checks.append({"check": key, "ok": False,
                           "expected": expected_corner, "measured": None})
            hints.append(f"Expected {key} but nothing measurable was baked.")
            continue
        corner = measured_bbox[corner_idx]
        errors = [round(corner[i] - float(expected_corner[i]), 3)
                  for i in range(3)]
        ok = all(abs(e) <= tol for e in errors)
        checks.append({"check": key, "ok": ok, "expected": expected_corner,
                       "measured": list(corner), "error_mm": errors})
        if not ok:
            hints.append(
                f"{key} {list(corner)} vs expected {list(expected_corner)} "
                f"(tol {tol} mm) — the geometry is misplaced; check the base "
                f"plane / origin inputs."
            )

    def allowed_types(key: str, measured_key: str) -> None:
        expected = expect.get(key)
        if expected is None:
            return
        expected_values = [expected] if isinstance(expected, str) else list(expected)
        allowed = {str(item).casefold() for item in expected_values}
        measured = aggregate.get(measured_key)
        complete = (
            isinstance(measured, list)
            and bool(measured)
            and all(isinstance(item, str) and item for item in measured)
        )
        is_ok = complete and all(item.casefold() in allowed for item in measured)
        checks.append({
            "check": key,
            "ok": is_ok,
            "expected": expected_values,
            "measured": measured if complete else None,
        })
        if not is_ok:
            hints.append(
                f"Expected every {key} value in {expected_values}, measured "
                f"{measured if complete else 'incomplete type evidence'} — "
                "check the terminal output and bake target."
            )

    allowed_types("geometry_types", "geometry_types")
    allowed_types("object_types", "object_types")

    expected_layer = expect.get("layer")
    if expected_layer is not None:
        layers = aggregate.get("layers")
        complete = (
            isinstance(layers, list)
            and bool(layers)
            and all(isinstance(item, str) and item for item in layers)
        )
        layer_ok = complete and all(
            item.casefold() == expected_layer.casefold() for item in layers
        )
        checks.append({
            "check": "layer",
            "ok": layer_ok,
            "expected": expected_layer,
            "measured": layers if complete else None,
        })
        if not layer_ok:
            hints.append(
                f"Expected every baked object on layer '{expected_layer}', "
                f"measured {layers if complete else 'incomplete layer evidence'}."
            )

    for key in ("all_valid", "all_closed", "all_solid"):
        expected_value = expect.get(key)
        if expected_value is None:
            continue
        measured_value = aggregate.get(key)
        check_ok = isinstance(measured_value, bool) \
            and measured_value is expected_value
        checks.append({
            "check": key,
            "ok": check_ok,
            "expected": expected_value,
            "measured": measured_value
            if isinstance(measured_value, bool) else None,
        })
        if not check_ok:
            label = key.replace("all_", "")
            hints.append(
                f"Expected all baked geometry {label}={expected_value}, "
                f"measured {measured_value!r}; unknown evidence is a failure."
            )

    relative_tolerance = float(expect.get("relative_tolerance", 1e-6))
    for key, complete_key, tolerance_key in (
        ("total_volume", "volume_complete", "volume_tolerance"),
        ("total_area", "area_complete", "area_tolerance"),
    ):
        expected_value = expect.get(key)
        if expected_value is None:
            continue
        expected_float = float(expected_value)
        measured_value = aggregate.get(key)
        complete = aggregate.get(complete_key) is True \
            and _is_finite_number(measured_value)
        absolute_tolerance = float(expect.get(
            tolerance_key,
            max(1e-6, abs(expected_float) * relative_tolerance),
        ))
        error_value = float(measured_value) - expected_float if complete else None
        check_ok = complete and abs(error_value) <= absolute_tolerance
        checks.append({
            "check": key,
            "ok": check_ok,
            "expected": expected_float,
            "measured": float(measured_value) if complete else None,
            "error": error_value,
            "tolerance": absolute_tolerance,
            "complete": complete,
        })
        if not check_ok:
            if not complete:
                hints.append(
                    f"Expected {key}={expected_float}, but complete independent "
                    "mass-property evidence is unavailable."
                )
            else:
                hints.append(
                    f"Measured {key}={float(measured_value)} vs expected "
                    f"{expected_float} (tol {absolute_tolerance}); bbox equality "
                    "does not override this semantic mismatch."
                )

    expected_topology = expect.get("topology")
    if expected_topology is not None:
        measured_topology = aggregate.get("topology")
        measured_topology = measured_topology \
            if isinstance(measured_topology, dict) else {}
        topology_complete = aggregate.get("topology_complete")
        topology_complete = topology_complete \
            if isinstance(topology_complete, dict) else {}
        for field, expected_value in expected_topology.items():
            complete = topology_complete.get(field) is True
            measured_value = measured_topology.get(field) if complete else None
            check_ok = complete and measured_value == expected_value
            checks.append({
                "check": f"topology.{field}",
                "ok": check_ok,
                "expected": expected_value,
                "measured": measured_value,
                "complete": complete,
            })
            if not check_ok:
                hints.append(
                    f"Expected topology {field}={expected_value}, measured "
                    f"{measured_value if complete else 'incomplete evidence'} — "
                    "inspect the Boolean/cap/join result, not only its bbox."
                )

    return {
        "ok": all(c["ok"] for c in checks),
        "checked": len(checks),
        "semantic_checked": sum(
            1 for check in checks
            if check["check"].split(".", 1)[0] in _SEMANTIC_EXPECTATION_KEYS
        ),
        "contract_supplied": bool(checks),
        "checks": checks,
        "hints": hints,
        "measured_dims_mm": dims,
        "measured_semantics": semantic if semantic else None,
    }
