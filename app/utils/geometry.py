"""دوال هندسية مساعدة — bbox، polygon، IoU، تقاطع الخطوط."""

from __future__ import annotations

from collections.abc import Iterable

Point = tuple[float, float]
BBox = tuple[float, float, float, float]  # x1, y1, x2, y2
Polygon = list[Point]


# ============================================
# bbox
# ============================================
def bbox_center(bbox: BBox) -> Point:
    """مركز الـ bbox."""
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def bbox_area(bbox: BBox) -> float:
    """مساحة الـ bbox."""
    w = max(0.0, bbox[2] - bbox[0])
    h = max(0.0, bbox[3] - bbox[1])
    return w * h


def iou(a: BBox, b: BBox) -> float:
    """تقاطع/اتحاد بين bbox-ين (Intersection over Union)."""
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter == 0.0:
        return 0.0
    union = bbox_area(a) + bbox_area(b) - inter
    return inter / union if union > 0 else 0.0


def bbox_contains_point(bbox: BBox, point: Point) -> bool:
    """هل النقطة داخل الـ bbox؟"""
    return bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3]


# ============================================
# point-in-polygon (ray casting)
# ============================================
def point_in_polygon(point: Point, polygon: Polygon) -> bool:
    """يحدد إن كانت النقطة داخل polygon (خوارزمية ray casting)."""
    if len(polygon) < 3:
        return False
    x, y = point
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        crosses = (yi > y) != (yj > y)
        if crosses:
            denom = yj - yi
            if denom != 0:
                x_intersect = xi + (y - yi) * (xj - xi) / denom
                if x < x_intersect:
                    inside = not inside
        j = i
    return inside


def polygon_centroid(polygon: Polygon) -> Point:
    """مركز polygon (متوسط الرؤوس — تقريبي للأشكال المحدبة)."""
    if not polygon:
        return (0.0, 0.0)
    n = len(polygon)
    return (
        sum(p[0] for p in polygon) / n,
        sum(p[1] for p in polygon) / n,
    )


# ============================================
# تقاطع الخطوط
# ============================================
def _ccw(a: Point, b: Point, c: Point) -> float:
    """علامة المنتج المتجه — مفيدة لاكتشاف التقاطع."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_intersect(a1: Point, a2: Point, b1: Point, b2: Point) -> bool:
    """هل قطعتا الخط a و b تتقاطعان؟"""
    d1 = _ccw(b1, b2, a1)
    d2 = _ccw(b1, b2, a2)
    d3 = _ccw(a1, a2, b1)
    d4 = _ccw(a1, a2, b2)
    return ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
        (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
    )


# ============================================
# حركة وإزاحة
# ============================================
def euclidean_distance(a: Point, b: Point) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def total_path_length(points: Iterable[Point]) -> float:
    """مجموع طول المسار عبر النقاط."""
    pts = list(points)
    if len(pts) < 2:
        return 0.0
    return sum(euclidean_distance(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def displacement(start: Point, end: Point) -> Point:
    """متجه الإزاحة (Δx, Δy)."""
    return (end[0] - start[0], end[1] - start[1])


def heading_angle(start: Point, end: Point) -> float:
    """زاوية اتجاه الحركة بالراديان (atan2)."""
    import math

    dx, dy = displacement(start, end)
    return math.atan2(dy, dx)


def angle_diff(a: float, b: float) -> float:
    """فرق زاويتين (بالراديان)، مُطبَّع إلى [0, π]."""
    import math

    diff = abs(a - b) % (2 * math.pi)
    return diff if diff <= math.pi else 2 * math.pi - diff


def is_stationary(points: list[Point], threshold_px: float = 5.0) -> bool:
    """هل كل النقاط ضمن دائرة نصف قطرها threshold_px من مركزها؟"""
    if len(points) < 2:
        return True
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    return all(euclidean_distance((cx, cy), p) <= threshold_px for p in points)


def speed_from_centers_kmh(centers: list[Point], fps: float, meters_per_px: float) -> float:
    """يقدّر متوسط السرعة بالكم/ساعة من مسار مراكز bbox عبر فريمات متعاقبة.

    مختلف عن `calibration.estimate_speed_kmh` الذي يأخذ إزاحة ومدّة جاهزتين.
    """
    if fps <= 0 or meters_per_px <= 0 or len(centers) < 2:
        return 0.0
    total_px = sum(euclidean_distance(centers[i], centers[i + 1]) for i in range(len(centers) - 1))
    n_intervals = len(centers) - 1
    dt_s = n_intervals / fps
    if dt_s <= 0:
        return 0.0
    return (total_px * meters_per_px / dt_s) * 3.6


def clip_segment_to_bbox(p1: Point, p2: Point, bbox: BBox) -> float:
    """يعيد طول جزء القطعة (p1→p2) الواقع داخل bbox (Liang-Barsky).

    يعود بـ 0.0 إذا كانت القطعة خارج الـ bbox تماماً.
    يُستخدم لاكتشاف "التطفل" — هل خط المسار يمر فعلياً داخل صندوق المركبة؟
    """
    x1, y1 = p1
    x2, y2 = p2
    xmin, ymin, xmax, ymax = bbox
    dx = x2 - x1
    dy = y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - xmin), (dx, xmax - x1), (-dy, y1 - ymin), (dy, ymax - y1)):
        if p == 0:
            if q < 0:
                return 0.0
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return 0.0
            if t > t0:
                t0 = t
        else:
            if t < t0:
                return 0.0
            if t < t1:
                t1 = t
    clipped_len = ((dx * (t1 - t0)) ** 2 + (dy * (t1 - t0)) ** 2) ** 0.5
    return clipped_len
