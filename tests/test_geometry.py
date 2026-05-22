"""اختبارات أدوات الهندسة."""

from __future__ import annotations

import math

import pytest

from app.utils.geometry import (
    bbox_area,
    bbox_center,
    bbox_contains_point,
    displacement,
    euclidean_distance,
    heading_angle,
    iou,
    is_stationary,
    point_in_polygon,
    polygon_centroid,
    segments_intersect,
    total_path_length,
)


# ============================================
# bbox
# ============================================
def test_bbox_center() -> None:
    assert bbox_center((0, 0, 10, 10)) == (5, 5)


def test_bbox_area() -> None:
    assert bbox_area((0, 0, 10, 5)) == 50


def test_bbox_area_zero_for_negative_dims() -> None:
    assert bbox_area((10, 10, 0, 0)) == 0


def test_bbox_contains_point_inside() -> None:
    assert bbox_contains_point((0, 0, 10, 10), (5, 5))


def test_bbox_contains_point_outside() -> None:
    assert not bbox_contains_point((0, 0, 10, 10), (15, 5))


# ============================================
# IoU
# ============================================
def test_iou_identical_bboxes() -> None:
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0


def test_iou_no_overlap() -> None:
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0


def test_iou_partial_overlap() -> None:
    # نصف تداخل
    result = iou((0, 0, 10, 10), (5, 0, 15, 10))
    assert 0.3 < result < 0.4  # 50/150 ≈ 0.333


# ============================================
# point in polygon
# ============================================
def test_point_in_polygon_square() -> None:
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert point_in_polygon((5, 5), sq)
    assert not point_in_polygon((15, 5), sq)
    assert not point_in_polygon((-1, 5), sq)


def test_point_in_polygon_triangle() -> None:
    tri = [(0, 0), (10, 0), (5, 10)]
    assert point_in_polygon((5, 3), tri)
    assert not point_in_polygon((5, 12), tri)


def test_point_in_polygon_rejects_degenerate() -> None:
    assert not point_in_polygon((5, 5), [(0, 0), (1, 1)])


def test_polygon_centroid() -> None:
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert polygon_centroid(sq) == (5, 5)


# ============================================
# segments
# ============================================
def test_segments_intersect_x() -> None:
    assert segments_intersect((0, 0), (10, 10), (0, 10), (10, 0))


def test_segments_dont_intersect_parallel() -> None:
    assert not segments_intersect((0, 0), (10, 0), (0, 5), (10, 5))


def test_segments_dont_intersect_separated() -> None:
    assert not segments_intersect((0, 0), (1, 1), (10, 10), (11, 11))


# ============================================
# distance + heading
# ============================================
def test_euclidean_distance_pythagorean() -> None:
    assert euclidean_distance((0, 0), (3, 4)) == 5


def test_total_path_length() -> None:
    pts = [(0, 0), (3, 0), (3, 4)]
    assert total_path_length(pts) == 7


def test_displacement() -> None:
    assert displacement((1, 2), (4, 6)) == (3, 4)


def test_heading_angle_east_is_zero() -> None:
    assert heading_angle((0, 0), (10, 0)) == pytest.approx(0.0)


def test_heading_angle_north_is_half_pi() -> None:
    assert heading_angle((0, 0), (0, 10)) == pytest.approx(math.pi / 2)


# ============================================
# stationary
# ============================================
def test_is_stationary_within_threshold() -> None:
    points = [(100, 100), (101, 99), (99, 101), (100, 100)]
    assert is_stationary(points, threshold_px=5.0)


def test_is_not_stationary_for_moving_points() -> None:
    points = [(0, 0), (10, 10), (20, 20), (30, 30)]
    assert not is_stationary(points, threshold_px=5.0)


def test_is_stationary_single_point() -> None:
    assert is_stationary([(5, 5)])
