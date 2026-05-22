"""تبويب الداشبورد — KPIs، رسوم، مستعرض مخالفات، تصدير."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import get_settings
from app.constants import VIOLATION_ARABIC_NAMES, ReviewStatus, ViolationType
from app.core.dashboard import DashboardService
from app.core.exporter import (
    build_study,
    export_csv,
    export_excel,
    export_json,
    export_pdf,
    record_export,
)
from app.ui.widgets.stats_charts import make_bar_chart, make_heatmap, make_line_chart

logger = logging.getLogger(__name__)

ARABIC_WEEKDAYS = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


class DashboardView(QWidget):
    """تبويب الداشبورد كاملاً."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = get_settings()
        self._service = DashboardService()
        self._build_ui()
        self.refresh()

    # ============================================
    # بناء الواجهة
    # ============================================
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # بطاقات KPI
        self._kpi_grid = QGridLayout()
        root.addLayout(self._kpi_grid)

        # شريط التصدير
        root.addLayout(self._build_export_bar())

        # القسم السفلي: رسوم + جدول المخالفات
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        splitter.addWidget(self._build_charts_panel())
        splitter.addWidget(self._build_violations_panel())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, stretch=1)

    def _build_export_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.addWidget(QLabel("تصدير الدراسة:", self))

        json_btn = QPushButton("JSON", self)
        json_btn.clicked.connect(lambda: self._on_export("json"))
        bar.addWidget(json_btn)

        csv_btn = QPushButton("CSV", self)
        csv_btn.clicked.connect(lambda: self._on_export("csv"))
        bar.addWidget(csv_btn)

        xlsx_btn = QPushButton("Excel", self)
        xlsx_btn.clicked.connect(lambda: self._on_export("xlsx"))
        bar.addWidget(xlsx_btn)

        pdf_btn = QPushButton("PDF عربي", self)
        pdf_btn.clicked.connect(lambda: self._on_export("pdf"))
        bar.addWidget(pdf_btn)

        bar.addStretch()

        refresh_btn = QPushButton("تحديث", self)
        refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(refresh_btn)

        return bar

    def _build_charts_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QGridLayout(panel)
        self._charts_container = panel
        self._charts_layout = layout
        return panel

    def _build_violations_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)

        # فلاتر
        filters = QHBoxLayout()
        filters.addWidget(QLabel("النوع:", panel))
        self._filter_type = QComboBox(panel)
        self._filter_type.addItem("الكل", None)
        for vt in ViolationType:
            self._filter_type.addItem(VIOLATION_ARABIC_NAMES[vt], vt.value)
        self._filter_type.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self._filter_type)

        filters.addWidget(QLabel("الحالة:", panel))
        self._filter_review = QComboBox(panel)
        self._filter_review.addItem("الكل", None)
        for rs in ReviewStatus:
            self._filter_review.addItem(rs.value, rs.value)
        self._filter_review.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self._filter_review)
        filters.addStretch()
        layout.addLayout(filters)

        # الجدول
        self._table = QTableWidget(panel)
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["المعرّف", "الملف", "النوع", "الثقة", "اللوحة", "الحالة", "أفعال"]
        )
        self._table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout.addWidget(self._table, stretch=1)

        return panel

    # ============================================
    # تحديث العرض
    # ============================================
    def refresh(self) -> None:
        kpis = self._service.get_kpis()
        self._refresh_kpis(kpis)
        self._refresh_charts()
        self._refresh_violations()

    def _refresh_kpis(self, kpis) -> None:
        # امسح القديم
        while self._kpi_grid.count():
            item = self._kpi_grid.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        cards = [
            ("إجمالي المقاطع", str(kpis.total_videos), "#3498db"),
            ("إجمالي المخالفات", str(kpis.total_violations), "#e74c3c"),
            ("متوسط مخالفات/مقطع", f"{kpis.avg_violations_per_video:.2f}", "#f39c12"),
            ("أنواع المصادر", str(len(kpis.sources_breakdown)), "#2ecc71"),
        ]
        for col, (title, value, color) in enumerate(cards):
            self._kpi_grid.addWidget(self._kpi_card(title, value, color), 0, col)

    def _kpi_card(self, title: str, value: str, color: str) -> QFrame:
        card = QFrame(self)
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setStyleSheet(
            f"QFrame {{ background-color: {color}; color: white; border-radius: 8px; padding: 8px; }}"
        )
        layout = QVBoxLayout(card)
        title_lbl = QLabel(title, card)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setStyleSheet("font-size: 12px; color: rgba(255,255,255,0.9);")
        value_lbl = QLabel(value, card)
        value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_lbl.setStyleSheet("font-size: 26px; font-weight: bold;")
        layout.addWidget(title_lbl)
        layout.addWidget(value_lbl)
        return card

    def _refresh_charts(self) -> None:
        # امسح القديم
        while self._charts_layout.count():
            item = self._charts_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        by_type = self._service.violations_by_type()
        type_data = [
            (VIOLATION_ARABIC_NAMES.get(ViolationType(t), t) if _safe_vt(t) else t, c)
            for t, c in by_type
        ]
        self._charts_layout.addWidget(
            make_bar_chart("المخالفات حسب النوع", type_data, self._charts_container), 0, 0
        )

        by_hour = self._service.violations_by_hour()
        line_points = [(float(h), float(c)) for h, c in by_hour]
        self._charts_layout.addWidget(
            make_line_chart("المخالفات حسب ساعة اليوم", line_points, self._charts_container), 0, 1
        )

        heatmap_data = self._service.violations_heatmap()
        if heatmap_data:
            matrix = [[heatmap_data.get((wd, h), 0) for h in range(24)] for wd in range(7)]
            self._charts_layout.addWidget(
                make_heatmap(
                    "خريطة حرارية (أيام × ساعات)",
                    matrix,
                    row_labels=ARABIC_WEEKDAYS,
                    col_labels=[str(h) for h in range(24)],
                    parent=self._charts_container,
                ),
                1,
                0,
                1,
                2,
            )

    def _refresh_violations(self) -> None:
        vtype = self._filter_type.currentData()
        rstatus = self._filter_review.currentData()
        violations = self._service.list_violations(
            violation_type=vtype, review_status=rstatus, limit=500
        )
        self._table.setRowCount(len(violations))
        for r, v in enumerate(violations):
            self._table.setItem(r, 0, QTableWidgetItem(str(v.id)))
            self._table.setItem(r, 1, QTableWidgetItem(v.video_filename))
            self._table.setItem(r, 2, QTableWidgetItem(v.violation_type_ar))
            self._table.setItem(r, 3, QTableWidgetItem(f"{v.confidence:.2f}"))
            self._table.setItem(r, 4, QTableWidgetItem(v.license_plate or "—"))
            self._table.setItem(r, 5, QTableWidgetItem(v.review_status))
            self._table.setCellWidget(r, 6, self._action_buttons(v.id))
        self._table.resizeColumnsToContents()

    def _action_buttons(self, violation_id: int) -> QWidget:
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        for label, status, color in (
            ("✓", ReviewStatus.CONFIRMED, "#27ae60"),
            ("✗", ReviewStatus.FALSE_POSITIVE, "#c0392b"),
            ("؟", ReviewStatus.UNCERTAIN, "#f39c12"),
        ):
            btn = QPushButton(label, container)
            btn.setStyleSheet(f"background-color: {color}; color: white; padding: 2px 6px;")
            btn.setFixedWidth(32)
            btn.clicked.connect(
                lambda _checked=False, vid=violation_id, st=status: self._mark_review(vid, st)
            )
            layout.addWidget(btn)
        return container

    def _mark_review(self, violation_id: int, status: ReviewStatus) -> None:
        try:
            self._service.update_review_status(violation_id, status)
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل تحديث المراجعة")
            QMessageBox.critical(self, "فشل التحديث", str(exc))
            return
        self._refresh_violations()

    # ============================================
    # التصدير
    # ============================================
    def _on_export(self, fmt: str) -> None:
        export_dir = self._settings.data_dir / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        filters_map = {
            "json": ("JSON (*.json)", "study.json"),
            "csv": ("CSV (*.csv)", "violations.csv"),
            "xlsx": ("Excel (*.xlsx)", "study.xlsx"),
            "pdf": ("PDF (*.pdf)", "study.pdf"),
        }
        filt, default = filters_map[fmt]
        path_str, _ = QFileDialog.getSaveFileName(
            self, "حفظ التصدير", str(export_dir / default), filt
        )
        if not path_str:
            return
        out_path = Path(path_str)

        try:
            study = build_study(self._service)
            violations = self._service.list_violations()
            if fmt == "json":
                export_json(study, out_path)
            elif fmt == "csv":
                export_csv(violations, out_path)
            elif fmt == "xlsx":
                export_excel(study, violations, out_path)
            elif fmt == "pdf":
                export_pdf(study, violations, out_path)
            record_export(
                self._service._db,  # noqa: SLF001
                study_name=out_path.stem,
                fmt=fmt,
                output_path=out_path,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل التصدير")
            QMessageBox.critical(self, "فشل التصدير", str(exc))
            return

        QMessageBox.information(self, "تم التصدير", f"حُفظ في:\n{out_path}")


def _safe_vt(value: str) -> bool:
    try:
        ViolationType(value)
        return True
    except ValueError:
        return False
