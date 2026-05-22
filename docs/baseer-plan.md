# مشروع بَصير | Baseer
## نظام تحليل المخالفات المرورية من الفيديوهات
### خطة شاملة لتنفيذ تطبيق سطح مكتب محلي بالكامل

---

## جدول المحتويات

1. [نظرة عامة](#1-نظرة-عامة)
2. [السياق والقيود](#2-السياق-والقيود)
3. [القرارات التقنية](#3-القرارات-التقنية-مع-التبرير)
4. [المعمارية العامة](#4-المعمارية-العامة)
5. [هيكل الملفات](#5-هيكل-الملفات)
6. [مخطط قاعدة البيانات](#6-مخطط-قاعدة-البيانات)
7. [مواصفات الوحدات](#7-مواصفات-الوحدات)
8. [محرك المخالفات (Rules Engine)](#8-محرك-المخالفات-rules-engine)
9. [خارطة الطريق (8 أسابيع)](#9-خارطة-الطريق-8-أسابيع)
10. [منهجية العمل](#10-منهجية-العمل)
11. [المخاطر والتخفيف](#11-المخاطر-والتخفيف)
12. [التبعيات والتثبيت](#12-التبعيات-والتثبيت)
13. [إرشادات Claude Code](#13-إرشادات-claude-code)

---

## 1. نظرة عامة

### 1.1 المشكلة
عندي مئات المقاطع المرورية المجمَّعة من سنوات، من مصادر مختلفة (داش كام، CCTV، سوشل ميديا). أحتاج تحويلها لبيانات منظمة قابلة للتحليل لإنتاج دراسات حول أنماط المخالفات المرورية.

### 1.2 الحل
تطبيق سطح مكتب محلي بالكامل (بدون أي اعتماد على السحابة) يقوم بـ:
- استيراد وفهرسة المقاطع
- تصنيف يدوي مدعوم بـ pseudo-labeling
- تدريب موديل YOLO على البيانات
- تحليل شامل لكل المقاطع
- توليد إحصاءات ودراسات قابلة للنشر

### 1.3 اسم المنتج
**بَصير | Baseer** — اسم عربي يدل على الإدراك والملاحظة الدقيقة.

### 1.4 ما هو خارج النطاق (Non-Goals)
- ❌ التشغيل real-time على كاميرات حية (المشروع للتحليل العَكسي)
- ❌ ربط مع أي API حكومي أو خارجي
- ❌ تحرير المخالفات الفعلية (هذا تحليل بحثي/إحصائي فقط)
- ❌ دعم الجوال أو الويب (سطح مكتب فقط)
- ❌ تخزين سحابي

---

## 2. السياق والقيود

### 2.1 المستخدم
مطور واحد (المالك)، خبرة عالية في Python و PyQt، يفضّل الواجهات العربية الاحترافية، يعمل بمنهجية gstack.

### 2.2 البيئة
- **نظام التشغيل**: Windows 11
- **العتاد**:
  - CPU: AMD Ryzen 7 9800X3D
  - GPU: NVIDIA RTX 4070 SUPER (12GB VRAM)
  - RAM: 32GB DDR5
  - Storage: SSD سريع (مطلوب لمعالجة الفيديو)

### 2.3 خصائص البيانات
- مئات المقاطع متراكمة من سنوات
- مصادر مختلطة: داش كام شخصي + CCTV + تنزيلات من السوشل ميديا
- جودات متفاوتة (480p إلى 4K محتمل)
- صيغ مختلفة (mp4, mkv, mov, avi)
- بدون تصنيف مسبق (نبدأ من الصفر)

### 2.4 الإخراج المتوقع
- جدول مخالفات منظم في قاعدة بيانات
- إحصاءات كمية لكل نوع مخالفة
- تحليل زمني (متى تكثر، أي أيام، أي أوقات)
- خرائط حرارية (لو توفرت إحداثيات)
- تقارير قابلة للتصدير: Excel، PDF، JSON
- dataset عربي محلي قابل للنشر العلمي

---

## 3. القرارات التقنية (مع التبرير)

| القرار | الخيار المختار | البديل المرفوض | السبب |
|--------|----------------|-----------------|-------|
| اللغة | Python 3.11 | C++/Rust | سرعة التطوير، نظام بيئي غني لـ ML |
| الواجهة | PyQt6 | Tkinter / Electron | احترافية، RTL ممتاز، أداء عالي |
| قاعدة البيانات | DuckDB | SQLite / PostgreSQL | تحليلي سريع، لا يحتاج سيرفر، يقرأ Parquet مباشرة |
| موديل الكشف | YOLOv8/v11 (Ultralytics) | Detectron2 / MMDetection | سهولة الـ fine-tuning، أداء ممتاز على 4070 |
| التتبع | ByteTrack | DeepSORT | أسرع، أدق، مدمج في Ultralytics |
| التصنيف | CVAT (Docker) | Label Studio / Roboflow | الأقوى للفيديو، محلي 100% |
| OCR | PaddleOCR | Tesseract / EasyOCR | الأفضل للعربية، يدعم لوحات السيارات |
| معالجة الفيديو | FFmpeg + PySceneDetect | OpenCV فقط | أسرع، أكثر مرونة |
| الرسوم البيانية | PyQtGraph | matplotlib | تفاعلي وسريع داخل PyQt |
| التصدير | openpyxl + reportlab | python-docx فقط | تقارير PDF عربية احترافية |

---

## 4. المعمارية العامة

```
┌──────────────────────────────────────────────────────────────┐
│                  بَصير - PyQt6 Desktop App                   │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│   ┌─────────┐ ┌──────────┐ ┌────────┐ ┌────────┐ ┌────────┐ │
│   │ المكتبة │ │ التصنيف  │ │ التدريب │ │ التحليل │ │الداشبورد│ │
│   └────┬────┘ └────┬─────┘ └───┬────┘ └────┬───┘ └────┬───┘ │
│        │           │           │           │          │      │
│   ┌────▼───────────▼───────────▼───────────▼──────────▼───┐ │
│   │                    Core Services                       │ │
│   │  library.py | annotator.py | trainer.py | analyzer.py  │ │
│   │  rules.py   | ocr.py       | exporter.py| db.py        │ │
│   └────┬────────────────────────────────────────────────┬───┘ │
│        │                                                │     │
│   ┌────▼─────┐  ┌──────────┐  ┌──────────┐  ┌─────────▼───┐ │
│   │ DuckDB   │  │ FFmpeg   │  │ YOLOv8   │  │ CVAT Bridge │ │
│   │ (data/)  │  │ Pipeline │  │ ByteTrack│  │ (REST API)  │ │
│   └──────────┘  └──────────┘  └──────────┘  └─────────────┘ │
└──────────────────────────────────────────────────────────────┘
                              │
                ┌─────────────┴──────────────┐
                │                            │
        ┌───────▼────────┐          ┌────────▼────────┐
        │ Docker         │          │ NVIDIA CUDA 12  │
        │  └─ CVAT       │          │  └─ PyTorch     │
        └────────────────┘          └─────────────────┘
```

### 4.1 طبقات التطبيق
1. **UI Layer** (PyQt6): الواجهات والـ widgets
2. **Core Services**: المنطق التطبيقي
3. **Workers**: عمليات طويلة في threads منفصلة (QThread)
4. **Storage**: DuckDB + filesystem
5. **External**: CVAT, YOLO models

### 4.2 مبدأ الفصل
- الـ UI لا يحتوي على أي منطق تجاري
- الـ Core Services لا تعرف عن Qt
- كل عملية ثقيلة تجري في Worker مع signals/slots

---

## 5. هيكل الملفات

```
baseer/
├── README.md
├── requirements.txt
├── pyproject.toml
├── .gitignore
├── .env.example
│
├── docs/
│   ├── architecture.md
│   ├── violation_rules.md
│   ├── annotation_guide.md
│   └── api_reference.md
│
├── app/
│   ├── __init__.py
│   ├── main.py                    # نقطة الدخول
│   ├── config.py                  # الإعدادات (مسارات، thresholds)
│   ├── constants.py               # ثوابت (أنواع المخالفات، classes)
│   │
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── main_window.py         # النافذة الرئيسية + التبويبات
│   │   ├── library_view.py        # وحدة المكتبة
│   │   ├── annotator_view.py      # وحدة التصنيف
│   │   ├── trainer_view.py        # وحدة التدريب
│   │   ├── analyzer_view.py       # وحدة التحليل
│   │   ├── dashboard_view.py      # الداشبورد
│   │   │
│   │   ├── widgets/
│   │   │   ├── __init__.py
│   │   │   ├── video_player.py    # مشغل فيديو مع bbox overlay
│   │   │   ├── thumbnail_grid.py  # عرض شبكي للمقاطع
│   │   │   ├── timeline.py        # شريط زمني للأحداث
│   │   │   ├── stats_charts.py    # رسوم PyQtGraph
│   │   │   └── violation_card.py  # بطاقة عرض مخالفة
│   │   │
│   │   └── resources/
│   │       ├── icons/
│   │       ├── fonts/             # خطوط عربية (Cairo, IBM Plex Sans Arabic)
│   │       └── styles.qss         # ستايل قلوبال
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── db.py                  # DuckDB connection + queries
│   │   ├── library.py             # استيراد، metadata، hashing
│   │   ├── annotator.py           # CVAT REST API bridge
│   │   ├── trainer.py             # Ultralytics wrapper
│   │   ├── analyzer.py            # inference + ByteTrack
│   │   ├── rules.py               # محرك المخالفات
│   │   ├── ocr.py                 # PaddleOCR للوحات
│   │   ├── calibration.py         # معايرة الكاميرا للسرعة
│   │   └── exporter.py            # Excel, PDF, JSON
│   │
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── import_worker.py       # استيراد ثقيل
│   │   ├── inference_worker.py    # تحليل المقاطع
│   │   ├── training_worker.py     # تدريب الموديل
│   │   └── export_worker.py
│   │
│   └── utils/
│       ├── __init__.py
│       ├── video_utils.py         # FFmpeg wrappers
│       ├── hash_utils.py          # perceptual + file hashing
│       ├── arabic_utils.py        # تطبيع نص عربي
│       └── geometry.py            # bbox math, IoU, line crossing
│
├── models/
│   ├── pretrained/
│   │   ├── yolov8x.pt             # موديل عام
│   │   ├── yolov8m-plate.pt       # كاشف لوحات
│   │   └── README.md
│   └── finetuned/
│       └── baseer-v1/
│           ├── best.pt
│           ├── last.pt
│           └── results.csv
│
├── data/
│   ├── videos/                    # المقاطع (أو symlinks)
│   ├── thumbnails/                # صور مصغرة
│   ├── annotations/
│   │   ├── raw/                   # pseudo-labels من YOLOv8x
│   │   └── reviewed/              # بعد المراجعة (YOLO format)
│   ├── frames/                    # evidence frames للمخالفات
│   ├── results.duckdb             # قاعدة البيانات الرئيسية
│   └── exports/
│
├── scripts/
│   ├── setup_cvat.ps1             # تثبيت CVAT على ويندوز
│   ├── download_models.py         # تنزيل الموديلات
│   ├── benchmark.py               # قياس أداء الـ inference
│   └── seed_demo_data.py          # بيانات تجريبية
│
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_db.py
    ├── test_library.py
    ├── test_rules.py
    ├── test_geometry.py
    └── fixtures/
        └── sample_videos/
```

**قاعدة صارمة**: لا يوجد ملف يتجاوز **500 سطر**. لو زاد، يُقسَّم.

---

## 6. مخطط قاعدة البيانات

```sql
-- ============================================
-- جدول المقاطع
-- ============================================
CREATE TABLE IF NOT EXISTS videos (
    id              INTEGER PRIMARY KEY,
    filepath        VARCHAR NOT NULL UNIQUE,
    filename        VARCHAR NOT NULL,
    source_type     VARCHAR CHECK (source_type IN ('dashcam','cctv','social','other')),
    duration_sec    DOUBLE,
    width           INTEGER,
    height          INTEGER,
    fps             DOUBLE,
    codec           VARCHAR,
    file_size_mb    DOUBLE,
    file_hash       VARCHAR,                  -- SHA256 جزئي للملف
    phash           VARCHAR,                  -- perceptual hash للتعرف على المكرر
    recorded_at     TIMESTAMP,                -- من EXIF أو يدوي
    imported_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    thumbnail_path  VARCHAR,
    location_lat    DOUBLE,                   -- اختياري
    location_lon    DOUBLE,
    notes           VARCHAR,
    status          VARCHAR DEFAULT 'imported' -- imported|prelabeled|reviewed|analyzed
);

-- ============================================
-- المشاهد (المقاطع المجزأة)
-- ============================================
CREATE TABLE IF NOT EXISTS scenes (
    id              INTEGER PRIMARY KEY,
    video_id        INTEGER REFERENCES videos(id) ON DELETE CASCADE,
    scene_index     INTEGER,
    start_ms        INTEGER,
    end_ms          INTEGER
);

-- ============================================
-- الكشوفات (كل bbox من YOLO)
-- ============================================
CREATE TABLE IF NOT EXISTS detections (
    id              INTEGER PRIMARY KEY,
    video_id        INTEGER REFERENCES videos(id) ON DELETE CASCADE,
    frame_no        INTEGER,
    timestamp_ms    INTEGER,
    class_name      VARCHAR,
    confidence      DOUBLE,
    bbox_x1         DOUBLE,
    bbox_y1         DOUBLE,
    bbox_x2         DOUBLE,
    bbox_y2         DOUBLE,
    track_id        INTEGER                   -- ByteTrack ID
);
CREATE INDEX idx_det_video ON detections(video_id);
CREATE INDEX idx_det_track ON detections(video_id, track_id);

-- ============================================
-- المخالفات
-- ============================================
CREATE TABLE IF NOT EXISTS violations (
    id              INTEGER PRIMARY KEY,
    video_id        INTEGER REFERENCES videos(id) ON DELETE CASCADE,
    violation_type  VARCHAR,                  -- انظر CONSTANTS
    start_ms        INTEGER,
    end_ms          INTEGER,
    confidence      DOUBLE,
    track_id        INTEGER,
    evidence_frames VARCHAR,                  -- JSON: [12,45,78]
    license_plate   VARCHAR,                  -- لو انقرئت
    plate_conf      DOUBLE,
    review_status   VARCHAR DEFAULT 'pending', -- pending|confirmed|false_positive|uncertain
    notes           VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at     TIMESTAMP
);
CREATE INDEX idx_viol_type ON violations(violation_type);
CREATE INDEX idx_viol_video ON violations(video_id);

-- ============================================
-- المعايرات (للسرعة، اختياري لكل فيديو CCTV)
-- ============================================
CREATE TABLE IF NOT EXISTS calibrations (
    id              INTEGER PRIMARY KEY,
    video_id        INTEGER REFERENCES videos(id) ON DELETE CASCADE,
    reference_pts   VARCHAR,                  -- JSON: 4 نقاط مع مسافات حقيقية
    meters_per_px   DOUBLE,
    calibrated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- المناطق (zones): مناطق ممنوع الوقوف، إشارات، إلخ
-- ============================================
CREATE TABLE IF NOT EXISTS zones (
    id              INTEGER PRIMARY KEY,
    video_id        INTEGER REFERENCES videos(id) ON DELETE CASCADE,
    zone_type       VARCHAR,                  -- no_parking | stop_line | direction_lane
    polygon         VARCHAR,                  -- JSON: [[x,y],[x,y]...]
    metadata        VARCHAR                   -- JSON
);

-- ============================================
-- الدراسات المُصدَّرة
-- ============================================
CREATE TABLE IF NOT EXISTS exports (
    id              INTEGER PRIMARY KEY,
    study_name      VARCHAR,
    filter_json     VARCHAR,
    format          VARCHAR,                  -- xlsx|pdf|json|csv
    output_path     VARCHAR,
    exported_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 7. مواصفات الوحدات

### 7.1 وحدة المكتبة (Library)

**الغرض**: استيراد المقاطع وفهرستها.

**الواجهة (UI)**:
- شريط أدوات: استيراد مجلد | استيراد ملفات | بحث | فلاتر
- شبكة thumbnails مع معلومات (المدة، التاريخ، المصدر)
- panel جانبي: تفاصيل المقطع المختار + معاينة فيديو
- شريط حالة: عدد المقاطع، مجموع المدة، مساحة التخزين

**المنطق الأساسي** (`core/library.py`):
```python
class LibraryService:
    def import_path(self, path: Path, source_type: str) -> ImportReport: ...
    def extract_metadata(self, video_path: Path) -> VideoMetadata: ...
    def compute_hashes(self, video_path: Path) -> tuple[str, str]: ...
    def detect_duplicates(self) -> list[DuplicateGroup]: ...
    def generate_thumbnail(self, video_path: Path) -> Path: ...
    def split_long_video(self, video_id: int, max_duration: int = 600): ...
```

**معايير القبول**:
- استيراد 100 مقطع في < 3 دقائق (بدون thumbnails)
- استيراد 100 مقطع في < 10 دقائق (مع thumbnails)
- لا تكرارات بفضل phash + file_hash
- يحفظ recorded_at تلقائياً من EXIF لو متوفر

---

### 7.2 وحدة التصنيف (Annotator)

**الغرض**: تصنيف عينة من المقاطع لتدريب الموديل.

**الاستراتيجية**:
1. تشغيل YOLOv8x جاهز على كل المقاطع → pseudo-labels
2. اختيار ~300-500 مقطع للمراجعة اليدوية
3. تصدير الـ pseudo-labels إلى CVAT
4. مراجعة وتصحيح في CVAT
5. سحب النتائج النهائية لـ `data/annotations/reviewed/`

**الواجهة (UI)**:
- زر "تشغيل Pre-labeling" → batch inference
- لائحة المقاطع مع نسبة الثقة المتوسطة
- زر "فتح في CVAT" يفتح localhost:8080 مع المهمة محملة
- مؤشر التقدم: مراجَع/الإجمالي

**المنطق الأساسي** (`core/annotator.py`):
```python
class AnnotatorService:
    def run_pseudo_labeling(self, video_ids: list[int]): ...
    def export_to_cvat(self, video_ids: list[int]) -> str: ...     # task_id
    def import_from_cvat(self, task_id: str): ...
    def export_yolo_format(self, output_dir: Path): ...
```

**Classes للكشف (Detection Classes)**:
```python
DETECTION_CLASSES = {
    0:  "vehicle",            # سيارة/شاحنة/باص (مجمَّعة)
    1:  "motorcycle",         # دراجة نارية (منفصلة للخوذة)
    2:  "person",
    3:  "traffic_light_red",
    4:  "traffic_light_yellow",
    5:  "traffic_light_green",
    6:  "helmet",
    7:  "license_plate",
    8:  "crosswalk",
    9:  "lane_line_solid",
    10: "lane_line_dashed",
    11: "stop_line",
    12: "no_parking_sign",
}
```

**معايير القبول**:
- pseudo-labeling لـ 100 مقطع في < 30 دقيقة (على RTX 4070)
- CVAT يفتح ويحمّل المهمة بدون أخطاء
- استيراد التصنيفات المُراجَعة بصيغة YOLOv8 صالحة

---

### 7.3 وحدة التدريب (Trainer)

**الغرض**: fine-tuning موديل YOLO على البيانات المُصنَّفة.

**الواجهة (UI)**:
- اختيار الموديل الأساس: YOLOv8n/s/m/l/x
- إعدادات: epochs, batch_size, imgsz, learning rate
- زر "بدء التدريب"
- شاشة logs مباشرة + رسم بياني للـ loss
- شاشة evaluation: confusion matrix + mAP per class

**المنطق الأساسي** (`core/trainer.py`):
```python
class TrainerService:
    def prepare_dataset(self, split: tuple = (0.7, 0.2, 0.1)) -> Path: ...
    def train(self, config: TrainConfig) -> TrainResult: ...
    def evaluate(self, model_path: Path) -> EvalReport: ...
    def export_onnx(self, model_path: Path): ...
```

**Default Training Config**:
```yaml
model: yolov8m.pt
epochs: 100
batch: 16
imgsz: 640
patience: 20
optimizer: AdamW
lr0: 0.001
augment: True
mosaic: 1.0
mixup: 0.1
device: 0   # CUDA
```

**معايير القبول**:
- تدريب 100 epoch على dataset 500 مقطع في < 8 ساعات
- mAP50 > 0.7 للـ classes الأساسية
- التطبيق لا يجمد أثناء التدريب (worker thread)

---

### 7.4 وحدة التحليل (Analyzer)

**الغرض**: تشغيل الموديل النهائي على كل المقاطع واستخراج المخالفات.

**Pipeline**:
```
فيديو → YOLOv8 (detection) → ByteTrack (tracking) → Rules Engine → Violations DB
                                                          ↓
                                                  PaddleOCR (للوحات)
                                                          ↓
                                                  Evidence Frames
```

**الواجهة (UI)**:
- لائحة المقاطع غير المعالجة
- زر "تحليل الكل" مع مؤشر تقدم
- إعدادات: confidence threshold, IoU threshold
- panel للأخطاء (مقاطع فشلت)

**المنطق الأساسي** (`core/analyzer.py`):
```python
class AnalyzerService:
    def analyze_video(self, video_id: int, config: AnalysisConfig) -> AnalysisResult: ...
    def analyze_batch(self, video_ids: list[int]): ...
    def extract_evidence_frames(self, violation: Violation): ...
```

**معايير القبول**:
- معالجة فيديو 5 دقائق 1080p في < 2 دقيقة (RTX 4070)
- كل مخالفة لها 3-5 evidence frames
- لوحات السيارات تنقرأ بدقة > 60% للوحات السعودية

---

### 7.5 وحدة الداشبورد (Dashboard)

**الغرض**: عرض الإحصاءات وتصدير الدراسات.

**العناصر**:

**1. البطاقات العلوية (KPIs)**:
- إجمالي المقاطع
- إجمالي المخالفات
- متوسط مخالفات/مقطع
- توزيع المصادر

**2. الرسوم البيانية**:
- Bar chart: المخالفات حسب النوع
- Line chart: المخالفات عبر الزمن
- Heatmap: ساعة اليوم × يوم الأسبوع
- Pie chart: نسب المخالفات

**3. مستعرض المخالفات**:
- جدول قابل للفلترة والترتيب
- نقرة → فتح الفيديو على الـ timestamp
- عرض الـ bbox فوق الفيديو
- أزرار: confirmed | false_positive | uncertain

**4. التصدير**:
- Excel (شيتات متعددة: summary, by_type, by_time, details)
- PDF تقرير عربي RTL مع رسوم
- JSON خام لكل البيانات
- CSV مفلتر

**معايير القبول**:
- الداشبورد يفتح في < 2 ثانية حتى مع 10,000 مخالفة
- تصدير PDF عربي يدعم RTL بشكل صحيح
- كل الرسوم تفاعلية (zoom, pan, tooltip)

---

## 8. محرك المخالفات (Rules Engine)

كل مخالفة تُمثَّل كـ class يرث من `BaseViolationDetector`:

```python
class BaseViolationDetector:
    def detect(self, frames: list[Frame], detections: list[Detection],
               tracks: list[Track], zones: list[Zone]) -> list[Violation]:
        raise NotImplementedError
```

### 8.1 قطع الإشارة الحمراء (red_light_running)
**المنطق**:
- وجود `traffic_light_red` في الفريم
- track من نوع vehicle/motorcycle يعبر خط `stop_line` (zone)
- اتجاه الحركة باتجاه الإشارة
- خلال نافذة زمنية = طول مدة الإشارة الحمراء

**الثقة**: عالية لو الإشارة واضحة + الخط محدد.

---

### 8.2 الاتجاه المعاكس (wrong_direction)
**المنطق**:
- حساب الاتجاه السائد للحركة في كل lane (من tracks متعددة)
- لو track يتحرك > 80% بعكس الاتجاه السائد لمدة > 2 ثانية → مخالفة
- يحتاج zone محدد للـ lane

**الثقة**: متوسطة-عالية، تعتمد على عدد العينات.

---

### 8.3 عدم لبس الخوذة (no_helmet)
**المنطق**:
- detection `motorcycle` + لا يوجد `helmet` متداخل (IoU > 0.1) مع الراكب لمدة > 2 ثانية
- التحقق: detection `person` فوق الـ motorcycle (bbox مركز فوق الـ motorcycle)

**الثقة**: عالية مع كاميرا واضحة.

---

### 8.4 الوقوف الخاطئ (illegal_parking)
**المنطق**:
- track `vehicle` ثابت (إزاحة < 5 بكسل) لمدة > 60 ثانية
- مركز bbox داخل `zone` نوعها `no_parking`
- يحتاج تعريف يدوي للمناطق

**الثقة**: عالية لو الـ zone محدد بدقة.

---

### 8.5 التجاوز الخاطئ (illegal_overtaking)
**المنطق**:
- track `vehicle` يعبر `lane_line_solid` (الخط مع IoU > 0 مع مسار الـ track)

**الثقة**: متوسطة، تعتمد على دقة كشف الخط.

---

### 8.6 السرعة الزائدة (speeding) — اختياري
**المنطق**:
- يتطلب `calibration` للفيديو (meters_per_px)
- حساب السرعة من track displacement عبر الفريمات
- مقارنة بسرعة معيارية (مدخلة يدوياً لكل zone/مقطع)

**ملاحظة**: متاحة فقط لـ CCTV الثابتة. غير مناسبة للداش كام.

---

### 8.7 ما يُستبعد من هذه الخطة
- **الحزام (no_seatbelt)** و **استخدام الجوال (phone_use)**: لا يمكن كشفهما بدقة من كاميرات الشارع. تحتاج كاميرا قريبة من الواجهة الأمامية (مثل أنظمة الرادار الحديثة).
- **يُسجَّل كـ class** في الـ detections لو ظهر بمصادفة، لكن لا توجد لها rules.

---

## 9. خارطة الطريق (8 أسابيع)

### 🟦 الأسبوع 1: الأساس والـ DB

**المهام**:
- [ ] إعداد البيئة: Python 3.11 venv + CUDA 12 + PyTorch + Ultralytics
- [ ] هيكل المشروع كاملاً (مجلدات فارغة + ملفات __init__)
- [ ] requirements.txt + pyproject.toml
- [ ] DuckDB schema + migrations
- [ ] `app/main.py` يفتح نافذة PyQt6 بـ 5 tabs فارغة
- [ ] `core/db.py` مع connection pool وقوالب الاستعلامات الأساسية
- [ ] `config.py` يقرأ من `.env`
- [ ] `utils/video_utils.py`: FFmpeg metadata extraction
- [ ] `utils/hash_utils.py`: file_hash + phash

**Deliverables**:
- ✅ التطبيق يفتح ويعرض 5 tabs
- ✅ DuckDB ينشئ schema تلقائياً عند أول تشغيل
- ✅ اختبار: استيراد مقطع واحد يدوياً ينحفظ في DB

**Acceptance Criteria**:
- `pytest tests/test_db.py` ينجح
- لا أخطاء في startup logs

---

### 🟦 الأسبوع 2: وحدة المكتبة الكاملة

**المهام**:
- [ ] واجهة `library_view.py` كاملة
- [ ] استيراد drag & drop + اختيار مجلد
- [ ] `import_worker.py` يستورد بـ thread منفصل
- [ ] شبكة thumbnails (lazy loading)
- [ ] مشغل فيديو في panel جانبي (`video_player.py`)
- [ ] بحث وفلترة (تاريخ، مدة، مصدر)
- [ ] PySceneDetect للمقاطع > 10 دقائق
- [ ] إدارة التكرار (phash matching)
- [ ] تحديد source_type يدوي (multi-select)

**Deliverables**:
- ✅ استيراد 100 مقطع في < 10 دقائق
- ✅ كل مقطع له thumbnail
- ✅ المقاطع الطويلة تتقطع تلقائياً

---

### 🟦 الأسبوع 3: Pre-labeling والـ Ontology

**المهام**:
- [ ] تنزيل YOLOv8x.pt في `models/pretrained/`
- [ ] `core/analyzer.py` الجزء الأساسي (inference فقط)
- [ ] batch inference على كل المقاطع → جدول `detections` يتعبأ
- [ ] تصدير pseudo-labels بصيغة CVAT XML
- [ ] script `setup_cvat.ps1` للنشر المحلي عبر Docker Desktop
- [ ] استيراد المقاطع لـ CVAT تلقائياً
- [ ] تعريف الـ DETECTION_CLASSES النهائي

**Deliverables**:
- ✅ كل المقاطع لها detections في DB
- ✅ CVAT يشتغل على `http://localhost:8080`
- ✅ مهمة CVAT جاهزة فيها 300-500 مقطع

---

### 🟦 الأسبوع 4: التصنيف اليدوي

**المهام**:
- [ ] دليل تصنيف داخلي (`docs/annotation_guide.md`)
- [ ] مراجعة وتصحيح ~300-500 مقطع في CVAT
- [ ] إضافة annotations للـ classes الناقصة (helmet, traffic_light state, lane_lines)
- [ ] جودة الـ annotations (cross-check بين عينات)
- [ ] تصدير بصيغة YOLOv8 إلى `data/annotations/reviewed/`
- [ ] تقسيم train/val/test تلقائياً (70/20/10)

**Deliverables**:
- ✅ dataset مصنف بجودة عالية
- ✅ `dataset.yaml` صالح لـ YOLOv8
- ✅ كل class له على الأقل 100 سامبل

---

### 🟦 الأسبوع 5: التدريب الأول

**المهام**:
- [ ] `core/trainer.py` كامل
- [ ] واجهة `trainer_view.py`
- [ ] `training_worker.py` مع progress signals
- [ ] fine-tune YOLOv8m على 100 epoch
- [ ] evaluation: mAP, precision, recall, confusion matrix
- [ ] رسوم بيانية للـ loss curves
- [ ] حفظ best.pt + last.pt في `models/finetuned/baseer-v1/`

**Deliverables**:
- ✅ موديل مدرَّب مع mAP50 ≥ 0.65
- ✅ تقرير evaluation كامل
- ✅ التطبيق لا يجمد أثناء التدريب

---

### 🟦 الأسبوع 6: تحسين الموديل + OCR

**المهام**:
- [ ] error analysis: identify weak classes
- [ ] augmentation إضافية للـ classes الضعيفة
- [ ] إعادة تدريب → baseer-v2
- [ ] تكامل PaddleOCR في `core/ocr.py`
- [ ] crop لوحات السيارات → OCR → تطبيع النص العربي
- [ ] benchmark على مقاطع اختبار خارج dataset

**Deliverables**:
- ✅ موديل نهائي mAP50 ≥ 0.75 على الـ classes الأساسية
- ✅ OCR للوحات السعودية بدقة ≥ 60%

---

### 🟦 الأسبوع 7: محرك التحليل والمخالفات

**المهام**:
- [ ] `core/analyzer.py` الكامل (مع ByteTrack)
- [ ] `core/rules.py` مع جميع violation detectors
- [ ] واجهة `analyzer_view.py`
- [ ] `inference_worker.py` للمعالجة الـ batch
- [ ] تعريف zones يدوياً للـ CCTV (no_parking, stop_line)
- [ ] `calibration.py` للمعايرة (اختياري)
- [ ] استخراج evidence frames
- [ ] معالجة شاملة لكل المقاطع

**Deliverables**:
- ✅ جدول `violations` ممتلئ
- ✅ كل مخالفة لها evidence frames
- ✅ تقرير الأخطاء (مقاطع فشلت)

---

### 🟦 الأسبوع 8: الداشبورد، التصدير، التوثيق

**المهام**:
- [ ] `dashboard_view.py` بكل العناصر
- [ ] KPI cards
- [ ] رسوم PyQtGraph: bar, line, heatmap, pie
- [ ] مستعرض المخالفات مع فيديو + bbox overlay
- [ ] أزرار المراجعة (confirmed / false_positive / uncertain)
- [ ] `core/exporter.py`: Excel + PDF + JSON + CSV
- [ ] PDF عربي RTL مع reportlab + arabic-reshaper
- [ ] `README.md` كامل
- [ ] `docs/` الكامل
- [ ] tests إضافية (coverage ≥ 60%)

**Deliverables**:
- ✅ تطبيق كامل قابل للاستخدام النهائي
- ✅ تصدير دراسة كاملة بـ 3 صيغ
- ✅ توثيق شامل

---

## 10. منهجية العمل

### 10.1 gstack
لكل ميزة جديدة:
1. **Think**: أسئلة توضيحية، اكتشاف المتطلبات الخفية
2. **Plan**: تصميم بدون كود
3. **Build**: كتابة الكود بإيجاز
4. **Review**: قراءة الكود وتنظيفه
5. **Test**: اختبارات unit + يدوي
6. **Ship**: commit + push
7. **Reflect**: ما الذي تعلمناه؟

### 10.2 أسلوب الكود
- **اللغة**: Python 3.11+ مع type hints صارمة
- **التنسيق**: `black` + `ruff`
- **التحقق**: `mypy --strict`
- **الـ Docstrings**: عربي مختصر + إنجليزي للـ params لو معقد
- **UI Strings**: عربي فصيح (مو دارجي، لأنه تطبيق احترافي)
- **Comments**: عربي للمنطق، إنجليزي عند المكتبات
- **أسماء المتغيرات**: `snake_case` إنجليزي

### 10.3 قواعد الكود الصارمة
- ❌ لا ملف > 500 سطر
- ❌ لا دالة > 50 سطر
- ❌ لا monolith files
- ❌ لا منطق UI في الـ core
- ❌ لا I/O في الـ main thread
- ✅ كل عملية ثقيلة → QThread/Worker
- ✅ كل ميزة → unit test
- ✅ Git commit واحد = ميزة واحدة كاملة

### 10.4 التعديل والـ Refactoring
عند تعديل ملف موجود: **قدّم الكود القديم + الكود الجديد للاستبدال المباشر**. لا تذكر أرقام السطور أبداً.

### 10.5 Git
```
main      ← الإصدار المستقر
develop   ← التطوير اليومي
feature/* ← ميزات منفصلة
```
- Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`
- كل أسبوع → tag: `week-1`, `week-2`, ...

---

## 11. المخاطر والتخفيف

| المخاطرة | الاحتمالية | الأثر | التخفيف |
|----------|------------|-------|---------|
| دقة منخفضة لـ class معين | عالية | متوسط | زيادة عينات + class weights + augmentation |
| اختلاف جودة المصادر | عالية | عالي | preprocessing موحد (resize + denoise) |
| السرعة من داش كام متحرك | عالية | عالي | استبعاد السرعة من المصادر غير الثابتة |
| استهلاك تخزين كبير | متوسط | متوسط | symlinks + ضغط الـ evidence frames بـ jpeg q=85 |
| تجميد UI أثناء العمليات الثقيلة | متوسط | عالي | QThread/Worker لكل عملية > 100ms |
| PaddleOCR ضعيف على بعض اللوحات | عالية | متوسط | fallback لـ EasyOCR + manual review |
| CVAT لا يشتغل على ويندوز | متوسط | عالي | استخدام Docker Desktop + WSL2 |
| الـ pseudo-labels غير دقيقة | متوسط | عالي | مراجعة يدوية إجبارية لكل سامبل قبل التدريب |
| تكاليف وقت التدريب | متوسط | متوسط | بدء بـ YOLOv8m بدل x، استخدام checkpoints |
| فشل في كشف مخالفات معينة | عالية | متوسط | تصميم rules قابلة للتعديل والـ tuning |

---

## 12. التبعيات والتثبيت

### 12.1 المتطلبات الأساسية (System)
- Windows 11
- Python 3.11.x
- NVIDIA Driver ≥ 550
- CUDA 12.4+
- Docker Desktop (للـ CVAT)
- FFmpeg (في PATH)
- Git

### 12.2 requirements.txt
```
# AI/ML
ultralytics>=8.3.0
torch>=2.5.0
torchvision>=0.20.0
opencv-python>=4.10.0
opencv-contrib-python>=4.10.0
paddleocr>=2.8.0
paddlepaddle-gpu>=2.6.0
numpy>=1.26.0
scipy>=1.13.0

# Database
duckdb>=1.1.0
pandas>=2.2.0

# UI
PyQt6>=6.7.0
PyQt6-Qt6>=6.7.0
qt-material>=2.14
pyqtgraph>=0.13.0
qtawesome>=1.3.0

# Video processing
ffmpeg-python>=0.2.0
scenedetect>=0.6.4
Pillow>=10.4.0
imagehash>=4.3.0

# Arabic text
arabic-reshaper>=3.0.0
python-bidi>=0.5.0

# Export
openpyxl>=3.1.0
reportlab>=4.2.0
fpdf2>=2.7.0

# Config
python-dotenv>=1.0.0
pydantic>=2.8.0

# Dev
pytest>=8.3.0
pytest-qt>=4.4.0
pytest-cov>=5.0.0
black>=24.8.0
ruff>=0.6.0
mypy>=1.11.0
```

### 12.3 خطوات التثبيت
```powershell
# 1. إنشاء venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. تثبيت PyTorch مع CUDA 12.4
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# 3. باقي التبعيات
pip install -r requirements.txt

# 4. تنزيل موديل YOLOv8x
python scripts/download_models.py

# 5. إعداد CVAT (Docker)
.\scripts\setup_cvat.ps1

# 6. تشغيل التطبيق
python -m app.main
```

---

## 13. إرشادات Claude Code

### 13.1 منهجية العمل المتوقعة

**اقرأ هذا الملف كاملاً قبل البدء**. كل قرار معماري موضح هنا.

**التزم بـ gstack**:
1. قبل أي ميزة، اسأل أسئلة توضيحية تتحدى الافتراضات
2. قدّم خطة قبل الكود
3. اكتب الكود
4. راجع وحسّن
5. اختبر
6. سلّم

### 13.2 قواعد صارمة

| القاعدة | التفصيل |
|---------|---------|
| لا تنفّذ أسبوعين معاً | شغّل أسبوع واحد، ووقّف للمراجعة قبل التالي |
| لا monolith files | لو ملف اقترب من 400 سطر، قسّمه |
| لا تعديل بأرقام السطور | قدّم الكود القديم + الكود الجديد |
| لا UI logic في core | الـ core لا يستورد من PyQt6 |
| لا I/O في main thread | كل عملية ثقيلة → Worker |
| اللغة العربية الفصحى للـ UI | لا دارجة في النصوص الظاهرة |
| Tests إلزامية | كل function في core لها اختبار |

### 13.3 ترتيب التنفيذ

```
ابدأ بالأسبوع 1 ← أوقف وراجع ← الأسبوع 2 ← أوقف وراجع ← ...
```

لا تقفز للأسابيع التالية حتى يتم اعتماد السابق.

### 13.4 أول prompt متوقع
> "ابدأ بالأسبوع 1 من ملف baseer-plan.md.
> أنشئ هيكل المشروع، requirements.txt، skeleton التطبيق بـ PyQt6،
> DuckDB schema. اعرض عليّ المخرجات قبل الانتقال للأسبوع 2."

### 13.5 أسلوب التواصل
- ردود مختصرة عملية
- لا فلسفة، تركيز على التنفيذ
- إن كان قرار غير واضح، اسأل
- إن وجدت تعارض في الخطة، نبّه فوراً
- العربية السعودية للتواصل، الإنجليزية للكود والمصطلحات التقنية

---

## ملاحظات ختامية

هذا الملف **مرجع حي** — يُعدَّل كلما تطلَّب المشروع. أي تغيير معماري يُوثَّق هنا أولاً.

**الهدف النهائي**: تطبيق احترافي يمكن استخدامه لإنتاج دراسات قابلة للنشر، مع إمكانية فتح المصدر لاحقاً ليكون مرجعاً عربياً في تحليل المخالفات المرورية.

---

**المالك**: عبدالكريم العبود
**التاريخ**: 2026
**الإصدار**: 1.0
**الترخيص**: مفتوح المصدر (سيُحدَّد لاحقاً)
