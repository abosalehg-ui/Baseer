"""كاشف عدم ترك مسافة آمنة — TTC + قاعدة نصف السرعة."""

from __future__ import annotations

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.core.violations import BaseViolationDetector, Track, ViolationCandidate, Zone
from app.utils.geometry import speed_from_centers_kmh

VEHICLE_CLASSES = ("vehicle", "motorcycle")


class FollowingDistanceDetector(BaseViolationDetector):
    """يكشف عدم ترك مسافة آمنة بين مركبتين في نفس المسار.

    يتطلب معايرة `meters_per_px`. يتجاهل السرعات المنخفضة (توقف الإشارات).
    """

    def __init__(
        self,
        *,
        meters_per_px: float | None = None,
        fps_override: float | None = None,
        ttc_threshold_sec: float = 2.0,
        min_violation_sec: float = 2.0,
        same_lane_x_tolerance_px: float = 60.0,
        min_speed_kmh: float = 15.0,
    ) -> None:
        self._meters_per_px = meters_per_px
        self._fps_override = fps_override
        self._ttc_threshold_sec = ttc_threshold_sec
        self._min_violation_sec = min_violation_sec
        self._same_lane_x_tolerance_px = same_lane_x_tolerance_px
        self._min_speed_kmh = min_speed_kmh

    def detect(
        self,
        tracks: list[Track],
        frame_detections: dict[int, list[Detection]],
        zones: list[Zone],
        fps: float,
    ) -> list[ViolationCandidate]:
        if self._meters_per_px is None or self._meters_per_px <= 0:
            return []
        effective_fps = self._fps_override or fps
        if effective_fps <= 0:
            return []

        vehicle_tracks = [
            t for t in tracks if t.class_name in VEHICLE_CLASSES and len(t.detections) >= 2
        ]
        if len(vehicle_tracks) < 2:
            return []

        # فهرسة مكانية: المقارنة الكاملة (كل زوج) كانت O(n²) — 200 track = 40,000
        # فحص، كلٌّ يبني قاموسين ويفرز ثلاث قوائم. المركبتان لا تكونان في نفس
        # المسار إلا إذا تقارب مركزاهما أفقياً، فنُوزّع الـtracks على «سلال x»
        # بعرض عتبة المسار ونقارن داخل السلة وجارتيها فقط.
        buckets = self._bucket_by_x(vehicle_tracks)

        violations: list[ViolationCandidate] = []
        seen_followers: set[int] = set()

        for follower in vehicle_tracks:
            if follower.track_id in seen_followers:
                continue
            for leader in self._candidate_leaders(follower, buckets):
                if leader.track_id == follower.track_id:
                    continue
                pair_violation = self._check_pair(
                    leader=leader, follower=follower, fps=effective_fps
                )
                if pair_violation is not None:
                    violations.append(pair_violation)
                    seen_followers.add(follower.track_id)
                    break
        return violations

    def _bucket_key(self, track: Track) -> int:
        """رقم السلة الأفقية للـtrack (متوسط مركز x ÷ عرض العتبة)."""
        xs = [(d.bbox[0] + d.bbox[2]) / 2 for d in track.detections]
        mean_x = sum(xs) / len(xs)
        return int(mean_x // self._same_lane_x_tolerance_px)

    def _bucket_by_x(self, tracks: list[Track]) -> dict[int, list[Track]]:
        buckets: dict[int, list[Track]] = {}
        for t in tracks:
            buckets.setdefault(self._bucket_key(t), []).append(t)
        return buckets

    def _candidate_leaders(self, follower: Track, buckets: dict[int, list[Track]]) -> list[Track]:
        """المركبات التي قد تكون في نفس مسار `follower` — سلته وجارتاها.

        الجارتان ضروريتان لأن مركبتين متقاربتين فعلاً قد تقعان على حدّي سلتين.
        """
        key = self._bucket_key(follower)
        out: list[Track] = []
        for k in (key - 1, key, key + 1):
            out.extend(buckets.get(k, ()))
        return out

    def _check_pair(
        self, *, leader: Track, follower: Track, fps: float
    ) -> ViolationCandidate | None:
        """يفحص زوج (leader, follower) — يعيد candidate إن كانت المسافة غير آمنة لمدة كافية."""
        # نبني خريطة (frame_no → detection) لكل track
        leader_by_frame = {d.frame_no: d for d in leader.detections}
        follower_by_frame = {d.frame_no: d for d in follower.detections}

        shared_frames = sorted(set(leader_by_frame) & set(follower_by_frame))
        if len(shared_frames) < 2:
            return None

        # فحص "نفس المسار": متوسط الفرق في x بين مراكز bbox السفلية
        x_diffs: list[float] = []
        for f in shared_frames:
            lb = leader_by_frame[f].bbox
            fb = follower_by_frame[f].bbox
            l_cx = (lb[0] + lb[2]) / 2
            f_cx = (fb[0] + fb[2]) / 2
            x_diffs.append(abs(f_cx - l_cx))
        median_x_diff = sorted(x_diffs)[len(x_diffs) // 2]
        if median_x_diff > self._same_lane_x_tolerance_px:
            return None

        # follower يجب أن يكون "خلف" leader من منظور الكاميرا (أقرب → bottom_y أكبر)
        l_bottom_median = sorted(leader_by_frame[f].bbox[3] for f in shared_frames)[
            len(shared_frames) // 2
        ]
        f_bottom_median = sorted(follower_by_frame[f].bbox[3] for f in shared_frames)[
            len(shared_frames) // 2
        ]
        if f_bottom_median <= l_bottom_median:
            return None  # follower أمام leader، نُلغي

        # حساب السرعات (km/h)
        assert self._meters_per_px is not None
        v_follower_kmh = speed_from_centers_kmh(follower.centers, fps, self._meters_per_px)
        v_leader_kmh = speed_from_centers_kmh(leader.centers, fps, self._meters_per_px)
        if v_follower_kmh < self._min_speed_kmh:
            return None

        v_follower_mps = v_follower_kmh / 3.6
        v_leader_mps = v_leader_kmh / 3.6
        rel_speed_mps = max(0.5, v_follower_mps - v_leader_mps)

        # لكل فريم مشترك: المسافة وعلامة الخطر
        unsafe_frames: list[int] = []
        for f in shared_frames:
            lb = leader_by_frame[f].bbox
            fb = follower_by_frame[f].bbox
            # gap_px = أعلى follower - أسفل leader (الـ y يزداد للأسفل في إحداثيات الصورة)
            gap_px = max(0.0, fb[1] - lb[3])
            gap_m = gap_px * self._meters_per_px
            ttc = gap_m / rel_speed_mps if rel_speed_mps > 0 else float("inf")
            half_speed_rule_m = 0.5 * v_follower_kmh
            if ttc < self._ttc_threshold_sec or gap_m < half_speed_rule_m:
                unsafe_frames.append(f)

        if not unsafe_frames:
            return None

        # تحقق من تتابع زمني كافٍ
        duration_s = (unsafe_frames[-1] - unsafe_frames[0] + 1) / fps
        if duration_s < self._min_violation_sec:
            return None

        # نوتس بالأرقام الأخيرة المُحسبة
        last_f = unsafe_frames[-1]
        last_gap_m = (
            max(0.0, follower_by_frame[last_f].bbox[1] - leader_by_frame[last_f].bbox[3])
            * self._meters_per_px
        )
        last_ttc = last_gap_m / rel_speed_mps if rel_speed_mps > 0 else float("inf")

        return ViolationCandidate(
            violation_type=ViolationType.UNSAFE_FOLLOWING,
            track_id=follower.track_id,
            start_ms=int(unsafe_frames[0] * 1000 / fps),
            end_ms=int(unsafe_frames[-1] * 1000 / fps),
            confidence=min(0.90, 0.55 + duration_s / 10.0),
            evidence_frames=[
                unsafe_frames[0],
                unsafe_frames[len(unsafe_frames) // 2],
                unsafe_frames[-1],
            ],
            notes=(
                f"سرعة المتبوع≈{v_follower_kmh:.0f} كم/س، "
                f"المسافة≈{last_gap_m:.1f} م، "
                f"TTC≈{last_ttc:.1f} ث (الأمان ≥ {self._ttc_threshold_sec:.1f} ث)"
            ),
        )
