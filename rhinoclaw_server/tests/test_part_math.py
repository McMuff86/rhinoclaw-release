"""Unit tests for rhinoclaw.utils.part_math — pure math, no Rhino, no mocks."""
import math

import pytest

from rhinoclaw.utils.part_math import (
    IDENTITY_FRAME,
    det3,
    flatten,
    frames_to_xform,
    invert_rigid,
    matmul,
    plane_to_xform,
)

WORLD_XY = [0, 0, 0, 1, 0, 0, 0, 1, 0]


def assert_matrix_close(a, b, tol=1e-9):
    for i in range(4):
        for j in range(4):
            assert abs(a[i][j] - b[i][j]) < tol, f"[{i}][{j}]: {a[i][j]} != {b[i][j]}"


IDENTITY4 = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


class TestPlaneToXform:
    def test_world_xy_is_identity(self):
        assert_matrix_close(plane_to_xform(WORLD_XY), IDENTITY4)

    def test_translation_only(self):
        m = plane_to_xform([10, 20, 30, 1, 0, 0, 0, 1, 0])
        assert m[0][3] == 10 and m[1][3] == 20 and m[2][3] == 30
        assert det3(m) == pytest.approx(1.0)

    def test_axes_are_normalized(self):
        # Axes given with length 2 must still yield an orthonormal basis.
        m = plane_to_xform([0, 0, 0, 2, 0, 0, 0, 2, 0])
        assert_matrix_close(m, IDENTITY4)

    def test_gram_schmidt_reorthogonalizes_y(self):
        # Y has a component along X; it must be projected out.
        m = plane_to_xform([0, 0, 0, 1, 0, 0, 0.5, 1, 0])
        assert_matrix_close(m, IDENTITY4, tol=1e-12)

    def test_z_is_right_handed_cross_product(self):
        # X = world Y, Y = world Z -> Z must be world X.
        m = plane_to_xform([0, 0, 0, 0, 1, 0, 0, 0, 1])
        assert (m[0][2], m[1][2], m[2][2]) == pytest.approx((1, 0, 0))
        assert det3(m) == pytest.approx(1.0)

    def test_rotation_is_always_proper(self):
        # 9-double frames cannot express a mirror: det is always +1.
        m = plane_to_xform([5, -3, 2, 0, -1, 0, 1, 0, 0])
        assert det3(m) == pytest.approx(1.0)

    def test_wrong_length_raises(self):
        with pytest.raises(ValueError, match="9 values"):
            plane_to_xform([0, 0, 0, 1, 0, 0])

    def test_zero_axis_raises(self):
        with pytest.raises(ValueError, match="zero length"):
            plane_to_xform([0, 0, 0, 0, 0, 0, 0, 1, 0])

    def test_parallel_axes_raise(self):
        with pytest.raises(ValueError, match="zero length"):
            plane_to_xform([0, 0, 0, 1, 0, 0, 2, 0, 0])


class TestInvertRigid:
    def test_inverse_times_forward_is_identity(self):
        m = plane_to_xform([7, -2, 3, 0, 1, 0, -1, 0, 0])
        assert_matrix_close(matmul(invert_rigid(m), m), IDENTITY4)
        assert_matrix_close(matmul(m, invert_rigid(m)), IDENTITY4)

    def test_non_rigid_raises(self):
        scaled = [
            [2.0, 0.0, 0.0, 0.0],
            [0.0, 2.0, 0.0, 0.0],
            [0.0, 0.0, 2.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        with pytest.raises(ValueError, match="not rigid"):
            invert_rigid(scaled)


class TestFramesToXform:
    def test_identity_pair(self):
        assert_matrix_close(frames_to_xform(WORLD_XY, WORLD_XY), IDENTITY4)

    def test_default_source_is_identity(self):
        target = [1, 2, 3, 1, 0, 0, 0, 1, 0]
        assert_matrix_close(frames_to_xform(target), plane_to_xform(target))

    def test_kauls_matrix_diag_minus1_plus1_minus1(self):
        # The verified Kauls placement: rotation diag(-1,+1,-1) + translation.
        # Expressed as a frame: X = (-1,0,0), Y = (0,1,0) -> Z = (0,0,-1).
        target = [120.5, 44.0, 910.0, -1, 0, 0, 0, 1, 0]
        m = frames_to_xform(target, IDENTITY_FRAME)
        assert m[0][0] == pytest.approx(-1)
        assert m[1][1] == pytest.approx(1)
        assert m[2][2] == pytest.approx(-1)
        assert (m[0][3], m[1][3], m[2][3]) == pytest.approx((120.5, 44.0, 910.0))
        # 180-degree rotation about Y is proper: det +1, no mirror.
        assert det3(m) == pytest.approx(1.0)

    def test_maps_source_origin_onto_target_origin(self):
        source = [5, 5, 0, 0, 1, 0, -1, 0, 0]
        target = [100, 200, 300, 1, 0, 0, 0, 0, 1]
        m = frames_to_xform(target, source)
        # Apply m to the source origin (homogeneous).
        p = [
            m[i][0] * 5 + m[i][1] * 5 + m[i][2] * 0 + m[i][3]
            for i in range(3)
        ]
        assert p == pytest.approx([100, 200, 300])

    def test_maps_source_x_axis_onto_target_x_axis(self):
        source = [0, 0, 0, 0, 1, 0, -1, 0, 0]
        target = [0, 0, 0, 0, 0, 1, 0, 1, 0]
        m = frames_to_xform(target, source)
        # Direction vector: source X axis (0,1,0) -> target X axis (0,0,1).
        v = [m[i][0] * 0 + m[i][1] * 1 + m[i][2] * 0 for i in range(3)]
        assert v == pytest.approx([0, 0, 1])


class TestDetAndFlatten:
    def test_det3_of_identity(self):
        assert det3(IDENTITY4) == pytest.approx(1.0)

    def test_det3_of_mirror(self):
        mirror = [
            [-1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        assert det3(mirror) == pytest.approx(-1.0)

    def test_det3_rotation_arbitrary(self):
        angle = math.radians(33)
        c, s = math.cos(angle), math.sin(angle)
        rot = [
            [c, -s, 0.0, 0.0],
            [s, c, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        assert det3(rot) == pytest.approx(1.0)

    def test_flatten_is_row_major(self):
        m = [[float(i * 4 + j) for j in range(4)] for i in range(4)]
        assert flatten(m) == [float(v) for v in range(16)]
