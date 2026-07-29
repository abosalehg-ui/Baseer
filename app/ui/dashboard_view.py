"""تبويب الداشبورد — KPIs، رسوم، مستعرض مخالفات، تصدير."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
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
from app.core.dashboard import DashboardKPIs, DashboardService
from app.core.exporter import (
    anonymize_violation_rows,
    build_study,
    export_csv,
    export_excel,
    export_json,
    export_pdf,
)
from app.ui import theme
from app.ui.widgets.stats_charts import make_bar_chart, make_heatmap, make_line_chart

logger = logging.getLogger(__name__)

ARABIC_WEEKDAYS = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

# سقف صفوف الجدول — يُعرض مع الإجمالي بدل بتر صامت
VIOLATIONS_PAGE_SIZE = 500

# عدد بطاقات KPI في الصف — يُعاد حسابه حسب عرض النافذة
KPI_CARD_MIN_WIDTH = 190


class DashboardView(QWidget):
    """تبويب الداشبورد كاملاً."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = get_settings()
        self._service = DashboardService()
        self._kpi_cards: list[QFrame] = []
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
        json_btn.setAccessibleName("تصدير الدراسة بصيغة JSON")
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

        # تجهيل اللوحات عند التصدير — الدراسة الإحصائية لا تحتاج أرقام لوحات،
        # وتصديرها يجعل الملف سجلاً شخصياً يربط مركبات محدَّدة بأوقات ومواقع.
        self._anon_check = QCheckBox("تصدير مجهّل (إخفاء أرقام اللوحات)", self)
        self._anon_check.setChecked(True)
        self._anon_check.setToolTip(
            "يستبدل كل رقم لوحة برمز مستعار ثابت (PLATE-XXXXXXXXXX):\n"
            "تبقى إحصاءات «مخالفات نفس المركبة» ممكنة بلا كشف الهوية.\n"
            "أزل التحديد فقط عند الحاجة الفعلية للأرقام."
        )
        self._anon_check.setAccessibleName("تفعيل تجهيل اللوحات عند التصدير")
        bar.addWidget(self._anon_check)

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
            self._filter_review.addItem(_review_status_label(rs.value), rs.value)
        self._filter_review.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self._filter_review)
        filters.addStretch()
        layout.addLayout(filters)

        # الجدول
        self._table_caption = QLabel("", panel)
        self._table_caption.setProperty("role", "muted")
        layout.addWidget(self._table_caption)

        self._table = QTableWidget(panel)
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["المعرّف", "الملف", "النوع", "الثقة", "اللوحة", "الحالة", "أفعال"]
        )
        self._table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._table.setAlternatingRowColors(True)
        self._table.setAccessibleName("جدول المخالفات للمراجعة")
        header = self._table.horizontalHeader()
        if header is not None:
            for col in range(self._table.columnCount()):
                header.setSectionResizeMode(
                    col,
                    (
                        QHeaderView.ResizeMode.Stretch
                        if col in (1, 2)
                        else QHeaderView.ResizeMode.ResizeToContents
                    ),
                )
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

    def _refresh_kpis(self, kpis: DashboardKPIs) -> None:
        # امسح القديم
        while self._kpi_grid.count():
            item = self._kpi_grid.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._kpi_cards.clear()

        # الألوان من لوحة الثيم لا كـhex مكتوبة هنا، وكل تركيبة (نص/خلفية)
        # مضبوطة لتتجاوز حد WCAG AA — أبيض على البرتقالي كان 2.2:1.
        p = theme.active_palette()
        cards = [
            ("إجمالي المقاطع", str(kpis.total_videos), p.primary, p.on_primary),
            ("إجمالي المخالفات", str(kpis.total_violations), p.danger, p.on_danger),
            (
                "متوسط مخالفات/مقطع",
                f"{kpis.avg_violations_per_video:.2f}",
                p.warning,
                p.on_warning,
            ),
            ("أنواع المصادر", str(len(kpis.sources_breakdown)), p.success, p.on_success),
        ]
        for title, value, bg, fg in cards:
            self._kpi_cards.append(self._kpi_card(title, value, bg, fg))
        self._layout_kpi_cards()

    def _layout_kpi_cards(self) -> None:
        """يوزّع بطاقات KPI على صفوف حسب العرض المتاح.

        كانت أربع بطاقات في صف واحد **دائماً** (`addWidget(card, 0, col)`)،
        فتنضغط على الشاشات الضيقة حتى يُقصّ نص «متوسط مخالفات/مقطع».
        """
        if not self._kpi_cards:
            return
        available = max(self.width(), KPI_CARD_MIN_WIDTH)
        per_row = max(1, min(len(self._kpi_cards), available // KPI_CARD_MIN_WIDTH))
        for index, card in enumerate(self._kpi_cards):
            self._kpi_grid.addWidget(card, index // per_row, index % per_row)

    def resizeEvent(self, event: QResizeEvent | None) -> None:  # noqa: N802
        """يعيد توزيع بطاقات KPI عند تغيّر عرض النافذة."""
        super().resizeEvent(event)
        if self._kpi_cards:
            self._layout_kpi_cards()

    def _kpi_card(self, title: str, value: str, background: str, foreground: str) -> QFrame:
        card = QFrame(self)
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setMinimumWidth(KPI_CARD_MIN_WIDTH - 20)
        card.setStyleSheet(theme.kpi_card_style(background, foreground))
        # قارئ الشاشة يقرأ البطاقة كوحدة واحدة ذات معنى
        card.setAccessibleName(f"{title}: {value}")
        layout = QVBoxLayout(card)
        title_lbl = QLabel(title, card)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(f"font-size: 12px; color: {foreground};")
        value_lbl = QLabel(value, card)
        value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_lbl.setStyleSheet(f"font-size: 26px; font-weight: bold; color: {foreground};")
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
            violation_type=vtype, review_status=rstatus, limit=VIOLATIONS_PAGE_SIZE
        )
        total = self._service.count_violations(violation_type=vtype, review_status=rstatus)
        self._table.setRowCount(len(violations))
        for r, v in enumerate(violations):
            self._table.setItem(r, 0, QTableWidgetItem(str(v.id)))
            self._table.setItem(r, 1, QTableWidgetItem(v.video_filename))
            self._table.setItem(r, 2, QTableWidgetItem(v.violation_type_ar))
            self._table.setItem(r, 3, QTableWidgetItem(f"{v.confidence:.2f}"))
            self._table.setItem(r, 4, QTableWidgetItem(v.license_plate or "—"))
            # الحالة تُعرض بنص + رمز: الاعتماد على اللون وحده يُقصي مستخدمي
            # عمى الألوان (≈8% من الذكور) عن التمييز بين مؤكَّدة وكاذبة.
            self._table.setItem(r, 5, QTableWidgetItem(_review_status_label(v.review_status)))
            self._table.setCellWidget(r, 6, self._action_buttons(v.id))

        # البتر عند 500 كان صامتاً — المستخدم يظن أن هذا كل ما لديه
        if total > len(violations):
            self._table_caption.setText(f"عرض {len(violations)} من {total} مخالفة (الأحدث أولاً)")
        else:
            self._table_caption.setText(f"{total} مخالفة")

    def _action_buttons(self, violation_id: int) -> QWidget:
        """أزرار مراجعة المخالفة.

        كل زر يحمل اسم وصول ووصف tooltip: أزرار برمز واحد («✓»/«✗»/«؟») بلا
        تسمية تُقرأ لدى قارئ الشاشة كـ«علامة صح» بلا سياق. الألوان من لوحة
        الثيم بتباين مضبوط، والهدف بعرض مريح للنقر بدل 32px.
        """
        p = theme.active_palette()
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING_XS)
        for label, name, status, bg, fg in (
            ("✓", "تأكيد المخالفة", ReviewStatus.CONFIRMED, p.success, p.on_success),
            ("✗", "وسمها إيجابية كاذبة", ReviewStatus.FALSE_POSITIVE, p.danger, p.on_danger),
            ("؟", "وسمها غير مؤكدة", ReviewStatus.UNCERTAIN, p.warning, p.on_warning),
        ):
            btn = QPushButton(label, container)
            btn.setStyleSheet(theme.action_button_style(bg, fg))
            btn.setMinimumWidth(theme.MIN_TOUCH_TARGET)
            btn.setMinimumHeight(theme.MIN_TOUCH_TARGET - 6)
            btn.setAccessibleName(f"{name} رقم {violation_id}")
            btn.setToolTip(name)
            btn.clicked.connect(
                lambda _checked=False, vid=violation_id, st=status: self._mark_review(vid, st)
            )
            layout.addWidget(btn)

        evidence_btn = QPushButton("🎬", container)
        evidence_btn.setToolTip("عرض الأدلة (إطارات + مشغّل عند وقت المخالفة)")
        evidence_btn.setAccessibleName(f"عرض أدلة المخالفة رقم {violation_id}")
        evidence_btn.setMinimumWidth(theme.MIN_TOUCH_TARGET)
        evidence_btn.setMinimumHeight(theme.MIN_TOUCH_TARGET - 6)
        evidence_btn.clicked.connect(
            lambda _checked=False, vid=violation_id: self._show_evidence(vid)
        )
        layout.addWidget(evidence_btn)
        return container

    def _show_evidence(self, violation_id: int) -> None:
        from app.ui.dialogs.evidence_dialog import EvidenceDialog

        dlg = EvidenceDialog(violation_id, parent=self)
        dlg.exec()

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

        anonymize = self._anon_check.isChecked()
        try:
            study = build_study(self._service, anonymize=anonymize)
            violations = self._service.list_violations()
            if anonymize:
                violations = anonymize_violation_rows(violations)
            if fmt == "json":
                export_json(study, out_path)
            elif fmt == "csv":
                export_csv(violations, out_path)
            elif fmt == "xlsx":
                export_excel(study, violations, out_path)
            elif fmt == "pdf":
                export_pdf(study, violations, out_path)
            self._service.record_export_entry(
                study_name=out_path.stem, fmt=fmt, output_path=out_path
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


_REVIEW_STATUS_LABELS: dict[str, str] = {
    ReviewStatus.PENDING.value: "⏳ بانتظار المراجعة",
    ReviewStatus.CONFIRMED.value: "✓ مؤكَّدة",
    ReviewStatus.FALSE_POSITIVE.value: "✗ إيجابية كاذبة",
    ReviewStatus.UNCERTAIN.value: "؟ غير مؤكدة",
}


def _review_status_label(status: str) -> str:
    """تسمية عربية + رمز لحالة المراجعة — معلومة لا تعتمد على اللون وحده."""
    return _REVIEW_STATUS_LABELS.get(status, status)
