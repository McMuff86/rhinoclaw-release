"""Pure matrix/plane math for the part library — no Rhino, no I/O.

The part-library schema describes insertion frames as 9-double planes
``[Ox, Oy, Oz, Xx, Xy, Xz, Yx, Yy, Yz]`` (origin, X axis, Y axis). A frame
becomes a 4x4 rigid transform whose columns are the orthonormalized X/Y and
the right-handed Z = X cross Y; placing a part means mapping its source
frame (in block coordinates) onto a target frame (in world coordinates):

    T = plane_to_xform(target) @ inverse(plane_to_xform(source))

All matrices are 4x4 nested lists, row-major. ``flatten(m)`` yields the
16-double row-major list the ``insert_library_part`` plugin command expects.

Deliberately dependency-free (no numpy) so it can be unit-tested without a
Rhino connection and reused by thin clients.
"""

from __future__ import annotations

from typing import List, Sequence

Matrix4 = List[List[float]]

IDENTITY_FRAME: List[float] = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0]

_EPS = 1e-9


def _norm(v: Sequence[float]) -> float:
    return (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5


def _normalize(v: Sequence[float]) -> List[float]:
    n = _norm(v)
    if n < _EPS:
        raise ValueError(f"frame axis has (near-)zero length: {list(v)}")
    return [v[0] / n, v[1] / n, v[2] / n]


def _cross(a: Sequence[float], b: Sequence[float]) -> List[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def plane_to_xform(frame: Sequence[float]) -> Matrix4:
    """9-double plane [Ox,Oy,Oz, Xx,Xy,Xz, Yx,Yy,Yz] -> 4x4 transform.

    X and Y are normalized, Y is re-orthogonalized against X (Gram-Schmidt)
    and Z = X cross Y, so the rotation part is always a right-handed
    orthonormal basis (det = +1). Mirroring must be expressed by the frame
    *pair* (target vs. source), not by a degenerate single frame.
    """
    frame = [float(v) for v in frame]
    if len(frame) != 9:
        raise ValueError(f"frame must have 9 values, got {len(frame)}")
    origin = frame[0:3]
    x_axis = _normalize(frame[3:6])
    y_raw = frame[6:9]
    # Remove any X component from Y, then normalize (tolerates slightly
    # non-perpendicular hand-measured frames).
    proj = _dot(y_raw, x_axis)
    y_ortho = [y_raw[i] - proj * x_axis[i] for i in range(3)]
    y_axis = _normalize(y_ortho)
    z_axis = _cross(x_axis, y_axis)
    return [
        [x_axis[0], y_axis[0], z_axis[0], origin[0]],
        [x_axis[1], y_axis[1], z_axis[1], origin[1]],
        [x_axis[2], y_axis[2], z_axis[2], origin[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def matmul(a: Matrix4, b: Matrix4) -> Matrix4:
    """4x4 matrix product a @ b."""
    return [
        [sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)]
        for i in range(4)
    ]


def det3(m: Matrix4) -> float:
    """Determinant of the upper-left 3x3 (rotation/scale) part."""
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def invert_rigid(m: Matrix4) -> Matrix4:
    """Invert a rigid transform (orthonormal rotation + translation).

    Uses R^-1 = R^T; exact and stable for the frame transforms produced by
    :func:`plane_to_xform`. Raises for matrices with scale/shear.
    """
    r = [[m[i][j] for j in range(3)] for i in range(3)]
    # Rigid check: R @ R^T must be the identity.
    for i in range(3):
        for j in range(3):
            expect = 1.0 if i == j else 0.0
            got = sum(r[i][k] * r[j][k] for k in range(3))
            if abs(got - expect) > 1e-6:
                raise ValueError("matrix is not rigid (rotation part not orthonormal)")
    t = [m[0][3], m[1][3], m[2][3]]
    rt = [[r[j][i] for j in range(3)] for i in range(3)]  # transpose
    new_t = [-sum(rt[i][k] * t[k] for k in range(3)) for i in range(3)]
    return [
        [rt[0][0], rt[0][1], rt[0][2], new_t[0]],
        [rt[1][0], rt[1][1], rt[1][2], new_t[1]],
        [rt[2][0], rt[2][1], rt[2][2], new_t[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def frames_to_xform(target_frame: Sequence[float],
                    source_frame: Sequence[float] = IDENTITY_FRAME) -> Matrix4:
    """Transform mapping the source frame (block coords) onto the target
    frame (world coords): ``plane_to_xform(target) @ inverse(plane_to_xform(source))``.
    """
    target = plane_to_xform(target_frame)
    source = plane_to_xform(source_frame)
    return matmul(target, invert_rigid(source))


def flatten(m: Matrix4) -> List[float]:
    """4x4 nested list -> 16-double row-major list (plugin wire format)."""
    return [m[i][j] for i in range(4) for j in range(4)]
