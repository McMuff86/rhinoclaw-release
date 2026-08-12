"""Evaluate a measured part placement against part.json verification data.

Pure math on already-measured values — no Rhino, no I/O — so the whole
verdict logic is unit-testable. The measuring itself (instance xform, bbox)
happens in the embedded script of ``tools/judge_part_placement.py``.

Anti-Goodhart contract (same as ``door_judge``): the verdict compares
Rhino-measured values against the caller's INDEPENDENT ground truth
(``expected_frame``, e.g. from a parametric-door computation). Claims made
by the placing agent never enter the evaluation.

Probe semantics (``verification.probes``, type ``frame_axis_distance``):
the named part.json frame (origin + Z direction in block coordinates) is
transformed once by the measured instance xform and once by the expected
xform; the probe passes when the measured point lies on the expected axis
(point-to-line distance <= tol_mm) and the directions agree
(angle <= tol_deg, folded to 0-90).

BBox plausibility: ``verification.bbox_local`` holds Rhino-TIGHT values
(measured live in Rhino — rhino3dm/control-point hulls are ~4 mm looser,
proven during the acceptance test). The measured instance bbox is tight
too, so deviations beyond ``bbox_mm`` (default 5.0, deliberately generous)
indicate a wrong/stale definition, not measurement noise.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from rhinoclaw.utils.part_library import get_det_rule, get_frame
from rhinoclaw.utils.part_math import (
    IDENTITY_FRAME,
    Matrix4,
    det3,
    frames_to_xform,
    plane_to_xform,
)

DEFAULT_TOLERANCES = {
    "position_mm": 0.5,
    "axis_deg": 1.0,
    "bbox_mm": 5.0,
}

_EPS = 1e-9


def xform16_to_matrix(values: Sequence[float]) -> Matrix4:
    """16-double row-major list -> 4x4 nested list."""
    if values is None or len(values) != 16:
        raise ValueError(f"xform must have 16 values, got "
                         f"{0 if values is None else len(values)}")
    v = [float(x) for x in values]
    return [v[0:4], v[4:8], v[8:12], v[12:16]]


def apply_point(m: Matrix4, p: Sequence[float]) -> List[float]:
    """Apply a 4x4 transform to a 3D point (homogeneous, w=1)."""
    return [m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3]
            for i in range(3)]


def apply_vector(m: Matrix4, v: Sequence[float]) -> List[float]:
    """Apply the rotation/scale part of a 4x4 transform to a direction."""
    return [m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2]
            for i in range(3)]


def frame_z_axis(frame9: Sequence[float]) -> List[float]:
    """The frame's Z axis (X cross Y) in the frame's coordinate system."""
    m = plane_to_xform(frame9)
    return [m[0][2], m[1][2], m[2][2]]


def point_line_distance(point: Sequence[float], line_point: Sequence[float],
                        line_dir: Sequence[float]) -> float:
    """Distance from a point to the infinite line (line_point, line_dir)."""
    d = [point[i] - line_point[i] for i in range(3)]
    n = math.sqrt(sum(c * c for c in line_dir))
    if n < _EPS:
        raise ValueError("line direction has zero length")
    u = [c / n for c in line_dir]
    cross = [
        d[1] * u[2] - d[2] * u[1],
        d[2] * u[0] - d[0] * u[2],
        d[0] * u[1] - d[1] * u[0],
    ]
    return math.sqrt(sum(c * c for c in cross))


def axis_angle_deg(a: Sequence[float], b: Sequence[float]) -> float:
    """Angle between two axes in degrees, folded to 0-90 (sign-agnostic)."""
    na = math.sqrt(sum(c * c for c in a))
    nb = math.sqrt(sum(c * c for c in b))
    if na < _EPS or nb < _EPS:
        raise ValueError("axis direction has zero length")
    cos = abs(sum(a[i] * b[i] for i in range(3)) / (na * nb))
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def transformed_bbox(m: Matrix4, bbox_min: Sequence[float],
                     bbox_max: Sequence[float]) -> Dict[str, List[float]]:
    """Axis-aligned hull of a local bbox transformed by ``m``."""
    corners = [
        [x, y, z]
        for x in (bbox_min[0], bbox_max[0])
        for y in (bbox_min[1], bbox_max[1])
        for z in (bbox_min[2], bbox_max[2])
    ]
    world = [apply_point(m, c) for c in corners]
    return {
        "min": [min(p[i] for p in world) for i in range(3)],
        "max": [max(p[i] for p in world) for i in range(3)],
    }


def bbox_max_deviation(a: Dict[str, Sequence[float]],
                       b: Dict[str, Sequence[float]]) -> float:
    """Largest absolute per-face deviation between two axis-aligned boxes."""
    devs = [abs(a["min"][i] - b["min"][i]) for i in range(3)]
    devs += [abs(a["max"][i] - b["max"][i]) for i in range(3)]
    return max(devs)


def evaluate_part_placement(
    part: Dict[str, Any],
    measured_xform: Sequence[float],
    measured_bbox: Optional[Dict[str, Sequence[float]]],
    expected_frame: Sequence[float],
    tolerances: Optional[Dict[str, float]] = None,
    source_frame_name: str = "insertion",
) -> Dict[str, Any]:
    """Full verdict for one measured instance against part.json.

    Parameters:
    - part: parsed part.json dict (frames, insertion.det_rule, verification).
    - measured_xform: the instance's Rhino-measured 4x4 (16 doubles,
      row-major).
    - measured_bbox: Rhino-measured world bbox {"min": [3], "max": [3]}
      or None (bbox check skipped).
    - expected_frame: 9-double target plane in world coordinates —
      independent ground truth from the caller.
    - tolerances: optional override merged over part.json
      verification.tolerances over built-in defaults.
    - source_frame_name: part.json frame the placement maps onto the
      target (default "insertion").
    """
    verification = part.get("verification") or {}

    tol = dict(DEFAULT_TOLERANCES)
    tol.update({k: float(v) for k, v in
                (verification.get("tolerances") or {}).items()})
    if tolerances:
        tol.update({k: float(v) for k, v in tolerances.items()})

    t_meas = xform16_to_matrix(measured_xform)
    det = det3(t_meas)

    failures: List[str] = []

    # --- det rule ---------------------------------------------------------
    det_rule = get_det_rule(part)
    det_pass = True
    if det_rule == "+1" and det <= 0:
        det_pass = False
        failures.append(
            f"det rule '+1' violated: det = {det:.4f} — the instance is "
            "mirrored; handing must be modeled by rotation, never mirroring")
    expected_det = verification.get("expected_det")
    if expected_det is not None and abs(det - float(expected_det)) > 0.05:
        det_pass = False
        failures.append(
            f"det {det:.4f} deviates from expected_det {expected_det} "
            "(scale or shear in the instance transform)")

    # --- expected transform from the ground-truth frame -------------------
    try:
        source_frame = get_frame(part, source_frame_name)
    except Exception:
        source_frame = list(IDENTITY_FRAME)
    t_exp = frames_to_xform(expected_frame, source_frame)

    # --- frame-axis probes -------------------------------------------------
    probes_out: List[Dict[str, Any]] = []
    for probe in verification.get("probes") or []:
        if not isinstance(probe, dict):
            continue
        if probe.get("type") != "frame_axis_distance":
            probes_out.append({
                "name": probe.get("name"),
                "type": probe.get("type"),
                "pass": None,
                "hint": "unsupported probe type — skipped",
            })
            continue
        frame_name = probe.get("frame")
        local = get_frame(part, frame_name)
        p_local = local[0:3]
        z_local = frame_z_axis(local)

        p_meas = apply_point(t_meas, p_local)
        d_meas = apply_vector(t_meas, z_local)
        p_exp = apply_point(t_exp, p_local)
        d_exp = apply_vector(t_exp, z_local)

        distance_mm = point_line_distance(p_meas, p_exp, d_exp)
        angle_deg = axis_angle_deg(d_meas, d_exp)
        tol_mm = float(probe.get("tol_mm", tol["position_mm"]))
        tol_deg = float(probe.get("tol_deg", tol["axis_deg"]))
        probe_pass = distance_mm <= tol_mm and angle_deg <= tol_deg
        if not probe_pass:
            failures.append(
                f"probe '{probe.get('name')}' ({frame_name}): "
                f"axis distance {distance_mm:.3f} mm (tol {tol_mm}), "
                f"angle {angle_deg:.3f} deg (tol {tol_deg})")
        probes_out.append({
            "name": probe.get("name"),
            "type": "frame_axis_distance",
            "frame": frame_name,
            "distance_mm": round(distance_mm, 4),
            "angle_deg": round(angle_deg, 4),
            "tol_mm": tol_mm,
            "tol_deg": tol_deg,
            "point_measured": [round(v, 4) for v in p_meas],
            "point_expected": [round(v, 4) for v in p_exp],
            "pass": probe_pass,
        })

    # --- bbox plausibility --------------------------------------------------
    bbox_verdict: Optional[Dict[str, Any]] = None
    bbox_local = verification.get("bbox_local")
    if bbox_local and measured_bbox:
        expected_bbox = transformed_bbox(
            t_exp, bbox_local["min"], bbox_local["max"])
        max_dev = bbox_max_deviation(measured_bbox, expected_bbox)
        bbox_pass = max_dev <= tol["bbox_mm"]
        if not bbox_pass:
            failures.append(
                f"bbox deviates up to {max_dev:.2f} mm from the library "
                f"master (tol {tol['bbox_mm']}) — in-document definition "
                "may be stale or a different variant")
        bbox_verdict = {
            "measured": {k: [round(v, 3) for v in measured_bbox[k]]
                         for k in ("min", "max")},
            "expected": {k: [round(v, 3) for v in expected_bbox[k]]
                         for k in ("min", "max")},
            "max_dev_mm": round(max_dev, 4),
            "tol_mm": tol["bbox_mm"],
            "pass": bbox_pass,
        }

    checked = [det_pass]
    checked += [p["pass"] for p in probes_out if p["pass"] is not None]
    if bbox_verdict is not None:
        checked.append(bbox_verdict["pass"])
    overall = all(checked)

    worst_probe = max(
        (p["distance_mm"] for p in probes_out if p.get("distance_mm") is not None),
        default=None,
    )

    return {
        "pass": overall,
        "det": round(det, 6),
        "det_rule": det_rule,
        "det_pass": det_pass,
        "probes": probes_out,
        "worst_probe_mm": worst_probe,
        "bbox": bbox_verdict,
        "tolerances_used": tol,
        "hint": "; ".join(failures) if failures else None,
    }
