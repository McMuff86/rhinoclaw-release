"""Door-placement domain judge — pure geometry core (NEXT-LEVEL-PLAN 2.1).

Rhino-free and stdlib-only so every signal is unit-testable. The judge
consumes ONLY measured geometry (a door's re-measured bounding box) plus
the independently drawn opening ground truth (an axis segment) — NEVER the
agent's request parameters. Three independent signals:

- ``off_center_mm``   — distance door-footprint center ↔ opening center
- ``axis_deg_error``  — door principal axis ↔ opening axis (folded to 0–90°)
- ``width_error_mm``  — door extent along the opening axis vs opening width
                        (+ a configurable frame allowance)

``pass`` requires all three within tolerance. The Goodhart rule: a door
that *claims* the right rotation but whose baked geometry points the wrong
way MUST fail here — the claim never enters this module.
"""
import math
from typing import Any, Dict, List, Optional, Sequence

# Frozen defaults — the published benchmark treats these like a test oracle;
# changes must be called out (NEXT-LEVEL-PLAN risk table: tolerance gaming).
DEFAULT_TOLERANCES = {
    "center_mm": 25.0,
    "axis_deg": 5.0,
    "width_mm": 30.0,
}

# Door outer extent = Lichtbreite + 2× frame. For the Rahmentuer_UD5 family
# the frame adds 220 mm total (2× 110). Configurable per judge call.
DEFAULT_WIDTH_ALLOWANCE_MM = 220.0


def _fold_angle_deg(angle: float) -> float:
    """Fold any angle difference into [0, 90]."""
    a = abs(angle) % 180.0
    return 180.0 - a if a > 90.0 else a


def opening_metrics(start: Sequence[float], end: Sequence[float]) -> Dict[str, Any]:
    """Center, direction angle (deg, [0,180)) and width of an axis segment."""
    cx = (start[0] + end[0]) / 2.0
    cy = (start[1] + end[1]) / 2.0
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    width = math.hypot(dx, dy)
    angle = math.degrees(math.atan2(dy, dx)) % 180.0
    return {"center": (cx, cy), "angle_deg": angle, "width": width}


def door_footprint(bbox: Sequence[Sequence[float]]) -> Dict[str, Any]:
    """XY footprint of an axis-aligned bbox: center, extents, principal axis.

    The principal axis of an AABB is X (0°) or Y (90°) — sufficient for the
    axis-aligned benchmark scenes this phase is scoped to.
    """
    (xmin, ymin, _), (xmax, ymax, _) = bbox[0], bbox[1]
    ext_x = xmax - xmin
    ext_y = ymax - ymin
    return {
        "center": ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0),
        "ext_x": ext_x,
        "ext_y": ext_y,
        "angle_deg": 0.0 if ext_x >= ext_y else 90.0,
    }


def _extent_along(footprint: Dict[str, Any], angle_deg: float) -> float:
    """AABB extent projected along a direction (exact for axis-aligned)."""
    rad = math.radians(angle_deg)
    return (footprint["ext_x"] * abs(math.cos(rad))
            + footprint["ext_y"] * abs(math.sin(rad)))


def judge_door(
    measured_bbox: Optional[Sequence[Sequence[float]]],
    opening_start: Sequence[float],
    opening_end: Sequence[float],
    tolerances: Optional[Dict[str, float]] = None,
    width_allowance_mm: float = DEFAULT_WIDTH_ALLOWANCE_MM,
) -> Dict[str, Any]:
    """Judge one door's measured bbox against one opening axis segment.

    Returns ``{placed, off_center_mm, axis_deg_error, width_error_mm,
    pass, hint}``. ``width_error_mm`` is signed (negative = too narrow).
    """
    tol = dict(DEFAULT_TOLERANCES)
    tol.update(tolerances or {})

    if not measured_bbox:
        return {
            "placed": False,
            "off_center_mm": None,
            "axis_deg_error": None,
            "width_error_mm": None,
            "pass": False,
            "hint": "No baked geometry found for this door — nothing to judge.",
        }

    opening = opening_metrics(opening_start, opening_end)
    foot = door_footprint(measured_bbox)

    off_center = math.hypot(
        foot["center"][0] - opening["center"][0],
        foot["center"][1] - opening["center"][1],
    )
    axis_error = _fold_angle_deg(foot["angle_deg"] - opening["angle_deg"])
    width_error = (_extent_along(foot, opening["angle_deg"])
                   - opening["width"] - width_allowance_mm)

    hints: List[str] = []
    if axis_error > tol["axis_deg"]:
        hints.append(
            f"Door axis is off by ~{axis_error:.0f}° — rotate by "
            f"~{round(axis_error / 90.0) * 90}° around the placement point."
        )
    if off_center > tol["center_mm"]:
        dx = opening["center"][0] - foot["center"][0]
        dy = opening["center"][1] - foot["center"][1]
        hints.append(
            f"Door center is {off_center:.0f} mm from the opening center — "
            f"shift by ({dx:.0f}, {dy:.0f}) mm."
        )
    if abs(width_error) > tol["width_mm"]:
        direction = "wider" if width_error > 0 else "narrower"
        hints.append(
            f"Door is {abs(width_error):.0f} mm {direction} than the opening "
            f"(+{width_allowance_mm:.0f} mm frame allowance) — check Lichtbreite."
        )

    return {
        "placed": True,
        "off_center_mm": round(off_center, 2),
        "axis_deg_error": round(axis_error, 2),
        "width_error_mm": round(width_error, 2),
        "pass": not hints,
        "hint": " ".join(hints),
    }


def match_doors_to_openings(
    door_centers: List[Optional[Sequence[float]]],
    openings: List[Dict[str, Any]],
) -> List[Optional[int]]:
    """Greedy nearest-center matching: door index → opening index (or None).

    Each opening is used at most once; doors without a measurable center
    get None. Greedy by ascending distance — adequate for benchmark scenes
    where doors sit on their openings.
    """
    candidates = []
    for d_idx, center in enumerate(door_centers):
        if center is None:
            continue
        for o_idx, opening in enumerate(openings):
            m = opening_metrics(opening["start"], opening["end"])
            dist = math.hypot(center[0] - m["center"][0],
                              center[1] - m["center"][1])
            candidates.append((dist, d_idx, o_idx))

    candidates.sort()
    assignment: List[Optional[int]] = [None] * len(door_centers)
    used_openings = set()
    for _, d_idx, o_idx in candidates:
        if assignment[d_idx] is not None or o_idx in used_openings:
            continue
        assignment[d_idx] = o_idx
        used_openings.add(o_idx)
    return assignment
