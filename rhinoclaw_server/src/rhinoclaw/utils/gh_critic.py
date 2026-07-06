"""Graph-authoring critique core — pure Python (NEXT-LEVEL-PLAN 5.3).

Rhino-free and stdlib-only like `door_judge.py`, so every signal is
unit-testable. This is the deterministic half of the `build_gh_interactive`
loop: derive the right bake output from the component catalog instead of
guessing, and judge the BAKED, RE-MEASURED geometry against the caller's
expectations — never the spec's claims.

The semantic half (rewriting the graph when the critique fails) stays with
the agent between calls; everything here must stay deterministic.
"""
from typing import Any, Dict, List, Optional, Sequence

# Output port types that BakeGoo cannot turn into document geometry —
# candidates of these types are tried last, not dropped (catalog `t` values).
_NON_BAKEABLE_TYPES = {
    "number", "integer", "boolean", "text", "domain", "domain²",
    "interval", "colour", "color", "time", "culture", "path", "guid",
}

_SCRIPT_TYPES = {"python3_script", "script"}
_SDK_TYPES = {"sdk_component", "sdk"}


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


def check_expectations(
    measured_bbox: Optional[Sequence[Sequence[float]]],
    baked_count: int,
    expect: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Judge measured geometry against caller expectations.

    `expect` keys (all optional):
    - ``min_count``: at least N baked objects.
    - ``dims_mm``: [dx, dy, dz] expected bbox extents (world axes).
    - ``bbox_min`` / ``bbox_max``: expected bbox corners.
    - ``tolerance_mm``: allowed deviation for dims/corners (default 1.0).

    Only MEASURED inputs reach this function (`get_objects_info` bboxes) —
    the Goodhart rule from the door judge applies unchanged: a graph that
    claims a 40×20×10 box but bakes a 10×10×10 one must fail here.
    """
    expect = expect or {}
    tol = float(expect.get("tolerance_mm", 1.0))
    checks: List[Dict[str, Any]] = []
    hints: List[str] = []

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

    return {
        "ok": all(c["ok"] for c in checks),
        "checked": len(checks),
        "checks": checks,
        "hints": hints,
        "measured_dims_mm": dims,
    }
