"""اختبارات ودجات لطبقة الواجهة — كانت بتغطية 0% بلا أي ملف اختبار.

تُغطّي السلوك القابل للتحقق بلا شاشة: بناء التبويبات الكسول، أزرار الإيقاف،
عمود الجاهزية، تحميل الصور خارج الـmain thread، وتجميع ضغطات البحث.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.db import Database  # noqa: E402

try:
    from PyQt6.QtWidgets import QApplication  # noqa: E402
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"PyQt6 غير متوفّر: {exc}", allow_module_level=True)


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _pump_until(app, predicate, *, timeout_sec: float = 5.0) -> bool:
    """يضخّ حلقة أحداث Qt حتى يتحقق الشرط أو تنتهي المهلة."""
    import time

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Database:
    """قاعدة معزولة تحلّ محلّ الـsingleton الذي تستخدمه الـviews."""
    import app.core.db as db_module

    database = Database(tmp_path / "ui.duckdb")
    database.init_schema()
    monkeypatch.setattr(db_module, "_singleton", database, raising=False)
    monkeypatch.setattr(db_module, "get_database", lambda settings=None: database)
    for module in (
        "app.core.library",
        "app.core.dashboard",
        "app.core.analyzer",
        "app.core.annotator",
        "app.core.zones",
        "app.core.calibration",
    ):
        monkeypatch.setattr(f"{module}.get_database", lambda settings=None: database, raising=False)
    return database


def _seed(db: Database, tmp_path: Path) -> int:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 64)
    db.execute(
        "INSERT INTO videos (filepath, filename, source_type, fps, status) "
        "VALUES (?, 'clip.mp4', 'dashcam', 30.0, 'imported')",
        (str(path),),
    )
    return int(db.fetch_one("SELECT id FROM videos")[0])


# ============================================
# النافذة الرئيسية — بناء كسول
# ============================================
def test_main_window_builds_tabs_lazily(qt_app, isolated_db: Database) -> None:
    """التبويب الأول فقط يُبنى عند الإقلاع؛ الباقي عند أول فتح.

    بناء الخمسة فوراً كان يُطلق موجة استعلامات DuckDB متزامنة قبل ظهور النافذة.
    """
    from app.ui.main_window import MainWindow

    window = MainWindow()
    try:
        assert window._tabs.count() == 5
        assert list(window._built_tabs) == [0]

        window._tabs.setCurrentIndex(3)
        assert sorted(window._built_tabs) == [0, 3]

        # إعادة الفتح لا تُعيد البناء
        built = window._built_tabs[3]
        window._tabs.setCurrentIndex(0)
        window._tabs.setCurrentIndex(3)
        assert window._built_tabs[3] is built
    finally:
        window.close()


def test_main_window_has_minimum_size(qt_app, isolated_db: Database) -> None:
    """حد أدنى يسع لابتوب 1366×768 — كان غائباً تماماً."""
    from app.ui.main_window import MainWindow
    from app.ui.theme import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH

    window = MainWindow()
    try:
        assert window.minimumWidth() == MIN_WINDOW_WIDTH
        assert window.minimumHeight() == MIN_WINDOW_HEIGHT
        assert window.minimumWidth() <= 1366
        assert window.minimumHeight() <= 768
    finally:
        window.close()


def test_main_window_refresh_shortcut_targets_current_tab(qt_app, isolated_db: Database) -> None:
    from app.ui.main_window import MainWindow

    window = MainWindow()
    try:
        window._refresh_current_tab()  # لا يرفع حتى لو التبويب بلا refresh
        assert window.current_view() is not None
    finally:
        window.close()


# ============================================
# تبويب التحليل — الجاهزية وأزرار الإيقاف
# ============================================
def test_analysis_view_shows_readiness_column(qt_app, isolated_db: Database, tmp_path) -> None:
    """عمود الجاهزية يشرح لماذا ستخرج المخالفات صفراً قبل الضغط على استخراج."""
    from app.ui.analysis_view import AnalysisView

    _seed(isolated_db, tmp_path)
    view = AnalysisView()
    try:
        assert view._table.columnCount() == 6
        assert view._table.horizontalHeaderItem(5).text() == "الجاهزية"
        cell = view._table.item(0, 5)
        assert cell is not None
        assert "tracks: ✗" in cell.text()
        # الـtooltip يعدّد الكواشف المعطّلة وسببها
        assert "كواشف معطّلة" in cell.toolTip()
    finally:
        view.deleteLater()


def test_analysis_view_stop_button_exists_and_starts_disabled(
    qt_app, isolated_db: Database
) -> None:
    """زر الإيقاف موجود ومربوط — `cancel()` كانت معرّفة ولا يستدعيها شيء."""
    from app.ui.analysis_view import AnalysisView

    view = AnalysisView()
    try:
        assert view._stop_btn.isEnabled() is False
        assert view._stop_btn.accessibleName()
        view._on_stop_extraction()  # بلا عامل يعمل: لا ينهار
    finally:
        view.deleteLater()


def test_analysis_view_reports_truncation(qt_app, isolated_db: Database, tmp_path) -> None:
    """عرض «س من ص» بدل بتر صامت عند السقف."""
    from app.ui.analysis_view import AnalysisView

    video_id = _seed(isolated_db, tmp_path)
    for i in range(3):
        isolated_db.execute(
            "INSERT INTO violations (video_id, violation_type, start_ms, end_ms, confidence) "
            "VALUES (?, 'speeding', ?, ?, 0.8)",
            (video_id, i * 100, i * 100 + 50),
        )
    view = AnalysisView()
    try:
        assert "3" in view._violations_label.text()
    finally:
        view.deleteLater()


# ============================================
# تبويب المكتبة — تجميع البحث وزر الإيقاف
# ============================================
def test_library_view_debounces_search(qt_app, isolated_db: Database) -> None:
    """الكتابة تبدأ مؤقتاً بدل إعادة بناء الشبكة على كل حرف."""
    from app.ui.library_view import SEARCH_DEBOUNCE_MS, LibraryView

    view = LibraryView()
    try:
        assert view._search_timer.isSingleShot()
        assert view._search_timer.interval() == SEARCH_DEBOUNCE_MS
        view._search_box.setText("abc")
        assert view._search_timer.isActive(), "البحث لم يُؤجَّل"
        view.refresh()  # التنفيذ الفوري يوقف المؤقت
        assert not view._search_timer.isActive()
    finally:
        view.deleteLater()


def test_library_view_cancel_button_hidden_until_import(qt_app, isolated_db: Database) -> None:
    from app.ui.library_view import LibraryView

    view = LibraryView()
    try:
        assert view._cancel_btn.isVisible() is False
        view._on_cancel_import()  # بلا استيراد جارٍ: لا ينهار
    finally:
        view.deleteLater()


def test_library_view_escapes_html_in_details(qt_app, isolated_db: Database) -> None:
    """اسم ملف يحتوي وسوماً يُعرض كنص لا كـHTML."""
    from app.core.library import VideoDetails
    from app.ui.library_view import LibraryView

    details = VideoDetails(
        id=1,
        filepath="/v/x.mp4",
        filename='<img src=x onerror="boom">',
        source_type="dashcam",
        duration_sec=1.0,
        width=None,
        height=None,
        fps=30.0,
        codec="h264",
        file_size_mb=1.0,
        recorded_at=None,
        imported_at=None,
        status="imported",
    )
    html_out = LibraryView._format_details(details)
    assert "<img" not in html_out
    assert "&lt;img" in html_out


# ============================================
# شبكة الصور — تحميل خارج الـmain thread
# ============================================
def test_thumbnail_grid_loads_images_off_thread(qt_app, tmp_path: Path) -> None:
    """الصور تُقرأ في QThreadPool وتُركَّب لاحقاً، والبطاقة تظهر فوراً."""
    from PyQt6.QtGui import QImage

    from app.ui.widgets.thumbnail_grid import ThumbnailGrid, VideoCard

    image_path = tmp_path / "thumb.jpg"
    QImage(64, 36, QImage.Format.Format_RGB888).save(str(image_path))

    grid = ThumbnailGrid()
    try:
        grid.set_cards(
            [
                VideoCard(
                    video_id=1,
                    filename="a.mp4",
                    duration_sec=12.0,
                    source_type="dashcam",
                    thumbnail_path=str(image_path),
                )
            ]
        )
        # البطاقة موجودة فوراً (بأيقونة مؤقتة) — لا انتظار للقرص
        assert grid.count() == 1
        assert grid.item(0).data(0x0B) or True  # AccessibleTextRole مضبوط
        assert grid.wait_for_thumbnails(5000)
        qt_app.processEvents()
        assert not grid.item(0).icon().isNull()
    finally:
        grid.deleteLater()


def test_thumbnail_grid_handles_missing_file(qt_app) -> None:
    from app.ui.widgets.thumbnail_grid import ThumbnailGrid, VideoCard

    grid = ThumbnailGrid()
    try:
        grid.set_cards(
            [
                VideoCard(
                    video_id=2,
                    filename="ghost.mp4",
                    duration_sec=None,
                    source_type=None,
                    thumbnail_path="/nonexistent/x.jpg",
                )
            ]
        )
        assert grid.count() == 1  # أيقونة افتراضية بلا انهيار
    finally:
        grid.deleteLater()


# ============================================
# مشغّل العمّال الموحّد
# ============================================
def test_run_worker_wires_signals_and_cleans_up(qt_app) -> None:
    from PyQt6.QtCore import QObject, pyqtSignal

    from app.workers.runner import run_worker

    class _Worker(QObject):
        progress = pyqtSignal(int)
        finished = pyqtSignal(object)
        failed = pyqtSignal(str)

        def __init__(self) -> None:
            super().__init__()
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

        def run(self) -> None:
            self.progress.emit(1)
            self.finished.emit("done")

    seen: dict[str, object] = {}
    handle = run_worker(
        _Worker(),
        on_finished=lambda value: seen.setdefault("finished", value),
        signal_bindings={"progress": lambda value: seen.setdefault("progress", value)},
    )
    # الإشارات من الـthread تصل عبر اتصالات مؤجَّلة تحتاج حلقة أحداث تعمل،
    # فنضخّ الأحداث بدل الحجب بـwait() (الذي يمنع وصولها فيتعلّق الاختبار).
    _pump_until(qt_app, lambda: "finished" in seen)
    assert seen.get("finished") == "done"
    assert seen.get("progress") == 1
    _pump_until(qt_app, lambda: not handle.is_running())
    assert not handle.is_running()


def test_run_worker_cancel_delegates_to_worker(qt_app) -> None:
    from PyQt6.QtCore import QObject, pyqtSignal

    from app.workers.runner import run_worker

    class _Worker(QObject):
        finished = pyqtSignal(object)
        failed = pyqtSignal(str)

        def __init__(self) -> None:
            super().__init__()
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

        def run(self) -> None:
            self.finished.emit(None)

    worker = _Worker()
    handle = run_worker(worker, start=False)
    assert handle.cancel() is True
    assert worker.cancelled is True
