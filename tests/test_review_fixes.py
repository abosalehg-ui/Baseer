"""اختبارات حارسة لإصلاحات المراجعة الشاملة (2026-07-29).

كل اختبار هنا يوثّق سلوكاً **كان خاطئاً** ويمنع النكوص إليه.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.core.analyzer import Detection
from app.core.db import Database
from app.core.detectors.high_beam import HighBeamDetector
from app.core.rules import (
    NoHelmetDetector,
    Track,
    build_tracks,
    consecutive_runs,
    detections_by_frame,
    first_crossing_frame,
)
from app.ui import theme


# ============================================
# 1. المدة تُحسب من فترات متتالية لا من (الأخير − الأول)
# ============================================
def test_consecutive_runs_splits_on_gaps() -> None:
    assert consecutive_runs([1, 2, 3, 50, 51]) == [(1, 3), (50, 51)]
    assert consecutive_runs([]) == []
    assert consecutive_runs([7]) == [(7, 7)]
    # فجوة إطار واحد لا تقطع الفترة (كشف مفقود عابر)
    assert consecutive_runs([1, 2, 4, 5], max_gap=1) == [(1, 5)]
    assert consecutive_runs([1, 2, 4, 5], max_gap=0) == [(1, 2), (4, 5)]
    # المدخلات غير المرتَّبة والمكرَّرة تُعالَج
    assert consecutive_runs([5, 1, 2, 5]) == [(1, 2), (5, 5)]


def _moto_frame(frame: int, *, with_helmet: bool) -> list[Detection]:
    ms = frame * 100
    out = [
        Detection(frame, ms, "motorcycle", 0.9, (100, 200, 150, 280), track_id=1),
        Detection(frame, ms, "person", 0.9, (110, 150, 140, 220), track_id=2),
    ]
    if with_helmet:
        out.append(Detection(frame, ms, "helmet", 0.9, (110, 195, 140, 230), track_id=3))
    return out


def test_no_helmet_does_not_fire_on_scattered_frames() -> None:
    """كشفان بلا خوذة تفصلهما دقائق ليسا مخالفة متواصلة.

    السلوك السابق: `(الأخير − الأول) / fps` = 39 ثانية → مخالفة مؤكَّدة زائفة.
    """
    dets: list[Detection] = []
    dets.extend(_moto_frame(0, with_helmet=False))  # بلا خوذة لحظة واحدة
    for f in range(1, 395):  # خوذة طوال الوقت
        dets.extend(_moto_frame(f, with_helmet=True))
    dets.extend(_moto_frame(395, with_helmet=False))  # وبلا خوذة لحظة أخرى

    violations = NoHelmetDetector(min_duration_sec=2.0).detect(
        build_tracks(dets), detections_by_frame(dets), [], fps=10.0
    )
    assert violations == []


def test_no_helmet_fires_on_a_real_continuous_run() -> None:
    """فترة متواصلة حقيقية تُكتشف، وتُنسب لزمنها لا لزمن الـtrack كله."""
    dets: list[Detection] = []
    for f in range(0, 100):  # 10 ثوانٍ بخوذة
        dets.extend(_moto_frame(f, with_helmet=True))
    for f in range(100, 140):  # 4 ثوانٍ بلا خوذة
        dets.extend(_moto_frame(f, with_helmet=False))
    for f in range(140, 200):
        dets.extend(_moto_frame(f, with_helmet=True))

    violations = NoHelmetDetector(min_duration_sec=2.0).detect(
        build_tracks(dets), detections_by_frame(dets), [], fps=10.0
    )
    assert len(violations) == 1
    v = violations[0]
    assert "متواصلة" in v.notes
    # الفترة تبدأ عند الإطار 100 (=10000ms) لا عند بداية الـtrack (0)
    assert v.start_ms == 10_000
    assert 13_000 <= v.end_ms <= 14_000
    assert all(100 <= f <= 139 for f in v.evidence_frames)


# ============================================
# 2. كاشف الأنوار لا يُحمّل كل الإطارات في الذاكرة
# ============================================
class _CountingProvider:
    """يعدّ قراءات الإطارات ويمنع الاحتفاظ بأكثر من إطار حيّ في وقت واحد."""

    def __init__(self) -> None:
        self.reads: list[int] = []
        self.max_live = 0
        self._live = 0

    def get_frame(self, frame_no: int) -> np.ndarray:
        self.reads.append(frame_no)
        self._live += 1
        self.max_live = max(self.max_live, self._live)
        # نُحرّر «الحيّ» فوراً: الكاشف لا يجب أن يحتفظ بمرجع طويل الأمد
        self._live -= 1
        return np.full((60, 60, 3), 20, dtype=np.uint8)

    def close(self) -> None:
        pass


def test_high_beam_reads_each_frame_once() -> None:
    """كل إطار مسحوب يُقرأ **مرة واحدة** مهما كان عدد المركبات فيه.

    السلوك السابق: قراءة كل الإطارات مقدماً وتخزينها في `frame_cache`
    (≈11 ج.ب لمقطع 5 دقائق 1080p) + إعادة حساب HSV لكل مركبة في الإطار.
    """
    dets: list[Detection] = []
    for frame in range(0, 60, 5):
        for track_id in range(4):  # أربع مركبات في نفس الإطار
            x = track_id * 15
            dets.append(
                Detection(frame, frame * 100, "vehicle", 0.9, (x, 10, x + 12, 40), track_id)
            )
    tracks = build_tracks(dets)

    provider = _CountingProvider()
    HighBeamDetector(frame_provider=provider).detect(tracks, {}, [], fps=10.0)

    assert provider.reads == sorted(set(provider.reads)), "إطار قُرئ أكثر من مرة"
    assert len(provider.reads) == 12  # 60 إطاراً ÷ 5
    assert provider.max_live == 1, "أكثر من إطار محفوظ في الذاكرة في وقت واحد"


# ============================================
# 3. دالة العبور موحّدة بين الكاشفين
# ============================================
def test_first_crossing_frame_shared_helper() -> None:
    from app.core.rules import Zone

    dets = [
        Detection(0, 0, "vehicle", 0.9, (40, 0, 60, 10), track_id=1),
        Detection(1, 100, "vehicle", 0.9, (40, 40, 60, 50), track_id=1),
        Detection(2, 200, "vehicle", 0.9, (40, 80, 60, 90), track_id=1),
    ]
    track = build_tracks(dets)[0]
    line = Zone(zone_type="stop_line", polygon=[(0.0, 60.0), (200.0, 60.0)])
    assert first_crossing_frame(track, [line]) == 2
    assert first_crossing_frame(track, []) is None
    # خط بنقطة واحدة يُتخطّى بلا انهيار
    assert first_crossing_frame(track, [Zone("stop_line", [(0.0, 60.0)])]) is None


def test_first_crossing_frame_empty_track() -> None:
    from app.core.rules import Zone

    empty = Track(track_id=9, class_name="vehicle", detections=[])
    assert first_crossing_frame(empty, [Zone("stop_line", [(0.0, 1.0), (1.0, 1.0)])]) is None


# ============================================
# 4. الترحيلات وسجل التدقيق
# ============================================
def test_migrations_are_recorded_and_idempotent(tmp_db: Database) -> None:
    assert tmp_db.applied_migrations() == [1, 2]
    tmp_db.init_schema()  # إعادة التشغيل لا تُعيد التطبيق
    assert tmp_db.applied_migrations() == [1, 2]
    assert tmp_db.table_exists("audit_log")


def test_audit_log_records_review_changes(tmp_db: Database) -> None:
    from app.core.dashboard import DashboardService

    tmp_db.execute("INSERT INTO videos (filepath, filename) VALUES ('/v/a.mp4', 'a.mp4')")
    vid = int(tmp_db.fetch_one("SELECT id FROM videos")[0])
    tmp_db.execute(
        "INSERT INTO violations (video_id, violation_type, start_ms, end_ms, confidence) "
        "VALUES (?, 'speeding', 0, 100, 0.8)",
        (vid,),
    )
    viol_id = int(tmp_db.fetch_one("SELECT id FROM violations")[0])

    service = DashboardService(db=tmp_db)
    service.update_review_status(viol_id, "confirmed")
    service.delete_violation(viol_id)

    rows = tmp_db.fetch_all(
        "SELECT entity, action, old_value, new_value FROM audit_log ORDER BY id"
    )
    assert [r[1] for r in rows] == ["review_status", "delete"]
    assert rows[0][2] == "pending" and rows[0][3] == "confirmed"


def test_audit_failure_never_breaks_the_operation(tmp_db: Database) -> None:
    """سجل التدقيق مساعد: فشل الكتابة فيه لا يُسقط العملية الأصلية."""
    tmp_db.execute("DROP TABLE audit_log")
    tmp_db.execute("INSERT INTO videos (filepath, filename) VALUES ('/v/b.mp4', 'b.mp4')")
    vid = int(tmp_db.fetch_one("SELECT id FROM videos")[0])
    tmp_db.execute(
        "INSERT INTO violations (video_id, violation_type, start_ms, end_ms, confidence) "
        "VALUES (?, 'speeding', 0, 100, 0.8)",
        (vid,),
    )
    viol_id = int(tmp_db.fetch_one("SELECT id FROM violations")[0])

    from app.core.dashboard import DashboardService

    DashboardService(db=tmp_db).update_review_status(viol_id, "confirmed")  # لا يرفع
    assert tmp_db.fetch_one("SELECT review_status FROM violations WHERE id = ?", (viol_id,))[0] == (
        "confirmed"
    )


def test_transaction_rolls_back_on_error(tmp_db: Database) -> None:
    tmp_db.execute("INSERT INTO videos (filepath, filename) VALUES ('/v/c.mp4', 'c.mp4')")
    before = int(tmp_db.fetch_one("SELECT COUNT(*) FROM videos")[0])

    with pytest.raises(RuntimeError):
        with tmp_db.transaction():
            tmp_db.execute("INSERT INTO videos (filepath, filename) VALUES ('/v/d.mp4', 'd.mp4')")
            raise RuntimeError("فشل محاكى")

    assert int(tmp_db.fetch_one("SELECT COUNT(*) FROM videos")[0]) == before


def test_transaction_commits_on_success(tmp_db: Database) -> None:
    with tmp_db.transaction():
        tmp_db.execute("INSERT INTO videos (filepath, filename) VALUES ('/v/e.mp4', 'e.mp4')")
    assert int(tmp_db.fetch_one("SELECT COUNT(*) FROM videos")[0]) == 1


# ============================================
# 5. الثيم — تباين WCAG AA
# ============================================
def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(fg: str, bg: str) -> float:
    l1, l2 = sorted((_relative_luminance(fg), _relative_luminance(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_theme_pairs_meet_wcag_aa(theme_name: str) -> None:
    """كل تركيبة نص/خلفية في اللوحة تتجاوز 4.5:1.

    التركيبة السابقة (أبيض على #f39c12) كانت ≈2.2:1.
    """
    p = theme.resolve_palette(theme_name)
    pairs = [
        (p.text, p.bg),
        (p.text, p.surface),
        (p.text_muted, p.bg),
        (p.on_primary, p.primary),
        (p.on_danger, p.danger),
        (p.on_warning, p.warning),
        (p.on_success, p.success),
        (p.on_info, p.info),
        (p.plot_fg, p.plot_bg),
    ]
    for fg, bg in pairs:
        ratio = contrast_ratio(fg, bg)
        assert ratio >= 4.5, f"[{theme_name}] {fg} على {bg} = {ratio:.2f}:1 (الحد 4.5)"


def test_theme_falls_back_to_dark_for_unknown_value() -> None:
    assert theme.resolve_palette("neon").name == "dark"
    assert theme.resolve_palette(None).name == "dark"
    assert theme.resolve_palette("LIGHT").name == "light"


def test_apply_theme_sets_stylesheet_and_active_palette() -> None:
    class _FakeApp:
        def __init__(self) -> None:
            self.qss = ""

        def setStyleSheet(self, value: str) -> None:  # noqa: N802
            self.qss = value

    app = _FakeApp()
    palette = theme.apply_theme(app, "light")
    assert palette.name == "light"
    assert theme.active_palette().name == "light"
    assert palette.bg in app.qss and "QPushButton" in app.qss
    theme.set_active_palette(theme.resolve_palette("dark"))  # إعادة للوضع الافتراضي
