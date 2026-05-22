<div dir="rtl" align="right">

# بَصير | Baseer

> نظام تحليل المخالفات المرورية من الفيديوهات — تطبيق سطح مكتب محلي بالكامل

تطبيق احترافي لتحويل مئات المقاطع المرورية (داش كام، CCTV، سوشل ميديا) إلى بيانات منظمة قابلة للتحليل، يعمل بدون أي اعتماد على السحابة. مبني بـ **Python 3.11+ • PyQt6 • DuckDB • YOLOv8 • PaddleOCR**.

---

## ✨ المميزات

| التبويب | الوصف |
|--------|------|
| 📚 **المكتبة** | استيراد drag & drop، thumbnails، فلاتر، PySceneDetect، إدارة التكرار |
| 🏷️ **التصنيف** | pseudo-labeling بـ YOLOv8x، تصدير CVAT XML، تجهيز dataset YOLOv8 (70/20/10) |
| 🧠 **التدريب** | fine-tune YOLOv8m، live logs، تقييم mAP لكل class |
| 🚦 **التحليل** | 6 كواشف مخالفات (إشارة حمراء، عكسي، خوذة، وقوف، تجاوز، سرعة)، evidence frames |
| 📊 **الداشبورد** | KPIs ملوّنة، رسوم تفاعلية (bar/line/heatmap)، مستعرض مخالفات بمراجعة، تصدير JSON/CSV/Excel/PDF عربي |

---

## 🛠️ المتطلبات

| المكوّن | الإصدار الأدنى |
|--------|---------------|
| نظام التشغيل | Windows 11 (Linux/macOS مدعوم تجريبياً) |
| Python | 3.10.x أو أحدث (3.11/3.12 مدعومة) |
| NVIDIA Driver | ≥ 550 |
| CUDA Toolkit | 12.4+ |
| FFmpeg | في `PATH` (يُستعمل لاستخراج البيانات الوصفية والـ thumbnails) |
| Docker Desktop | للـ CVAT (التصنيف اليدوي) |

العتاد المرجعي: RTX 4070 (12GB VRAM) + 32GB RAM + SSD سريع.

---

## 🚀 التثبيت

### 1️⃣ استنساخ المستودع

```powershell
git clone https://github.com/abosalehg-ui/Baseer.git
cd Baseer
```

### 2️⃣ إنشاء بيئة Python معزولة

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # على Windows
# source .venv/bin/activate    # على Linux/macOS
```

### 3️⃣ تثبيت PyTorch مع CUDA

```powershell
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
```

### 4️⃣ تثبيت باقي التبعيات

```powershell
pip install -r requirements.txt
```

### 5️⃣ إعداد متغيرات البيئة

```powershell
copy .env.example .env
# عدّل القيم لو احتجت (مسارات، CVAT URL، CUDA device)
```

### 6️⃣ تنزيل النماذج الجاهزة

```powershell
python scripts/download_models.py
# يُنزّل YOLOv8x.pt و YOLOv8m.pt إلى models/pretrained/
```

### 7️⃣ (اختياري) تشغيل CVAT للتصنيف اليدوي

```powershell
.\scripts\setup_cvat.ps1
# يستنسخ CVAT، يُشغّل Docker compose، يُنشئ حساب admin
# يفتح على http://localhost:8080
```

### 8️⃣ تشغيل التطبيق

```powershell
python -m app.main
```

سيفتح نافذة عربية RTL بخمسة تبويبات جاهزة.

---

## 🧪 الاختبارات

```powershell
# تشغيل كل الاختبارات
python -m pytest

# مع تقرير تغطية
python -m pytest --cov=app --cov-report=term

# اختبارات ملف محدد
python -m pytest tests/test_rules.py -v
```

**185 اختبار** يغطّي كل وحدات الـ core بدون الحاجة لـ GPU.

---

## 📂 المعمارية

```
baseer/
├── app/
│   ├── ui/                    # PyQt6 — 5 تبويبات (RTL كامل)
│   │   ├── main_window.py
│   │   ├── library_view.py
│   │   ├── annotator_view.py
│   │   ├── trainer_view.py
│   │   ├── analysis_view.py
│   │   ├── dashboard_view.py
│   │   └── widgets/           # thumbnail_grid, video_player, stats_charts
│   │
│   ├── core/                  # المنطق التطبيقي (لا يستورد PyQt6)
│   │   ├── db.py              # DuckDB connection + 7 جداول
│   │   ├── library.py         # استيراد، dedup، metadata
│   │   ├── annotator.py       # CVAT XML export
│   │   ├── dataset.py         # CVAT YOLO → YOLOv8 (70/20/10)
│   │   ├── trainer.py         # YOLOv8 fine-tuning (mockable)
│   │   ├── analyzer.py        # inference + ByteTrack + extract_violations
│   │   ├── rules.py           # 6 كواشف مخالفات + Zone + Track
│   │   ├── calibration.py     # meters_per_px + سرعة
│   │   ├── ocr.py             # PaddleOCR + تطبيع لوحات سعودية
│   │   ├── error_analysis.py  # تحديد classes ضعيفة + توصيات
│   │   ├── dashboard.py       # KPIs + تجميعات للداشبورد
│   │   └── exporter.py        # JSON / CSV / Excel / PDF عربي
│   │
│   ├── workers/               # كل عملية ثقيلة في QThread
│   │   ├── import_worker.py
│   │   ├── inference_worker.py
│   │   └── training_worker.py
│   │
│   ├── utils/
│   │   ├── video_utils.py     # ffprobe + thumbnails + scene detect
│   │   ├── hash_utils.py      # partial SHA256 + phash
│   │   ├── arabic_utils.py    # تطبيع عربي شامل
│   │   └── geometry.py        # bbox, polygon, IoU, intersection
│   │
│   ├── config.py              # pydantic-settings من .env
│   ├── constants.py           # DETECTION_CLASSES (13) + ViolationType (6)
│   └── main.py                # نقطة الدخول
│
├── models/
│   ├── pretrained/            # yolov8x.pt / yolov8m.pt
│   └── finetuned/             # baseer-v1, baseer-v2 ...
│
├── data/
│   ├── videos/                # المقاطع المستوردة
│   ├── thumbnails/            # صور مصغرة
│   ├── annotations/{raw,reviewed}/
│   ├── dataset/               # YOLOv8 layout (train/val/test)
│   ├── exports/               # JSON / Excel / PDF / CSV
│   └── results.duckdb         # القاعدة الرئيسية
│
├── scripts/                   # CLI tools
│   ├── download_models.py
│   ├── setup_cvat.ps1
│   ├── prepare_dataset.py
│   ├── train.py
│   ├── error_analysis.py
│   ├── ocr_plates.py
│   └── export_study.py
│
├── docs/
│   ├── baseer-plan.md         # الخطة الكاملة
│   ├── architecture.md
│   └── annotation_guide.md
│
├── tests/                     # 185 اختبار
└── .github/workflows/ci.yml   # ruff + black + pytest على كل PR
```

---

## 🗂️ سير العمل من الصفر إلى الدراسة

```
1. استيراد المقاطع (تبويب المكتبة)
        ↓
2. تشغيل pre-labeling بـ YOLOv8x (تبويب التصنيف)
        ↓
3. تصدير CVAT XML → مراجعة يدوية في CVAT
        ↓
4. تجهيز dataset YOLOv8 من ناتج المراجعة
        ↓
5. fine-tune YOLOv8m → baseer-v1 (تبويب التدريب)
        ↓
6. تحليل أخطاء النموذج → إعادة تدريب → baseer-v2
        ↓
7. استخراج المخالفات لكل المقاطع (تبويب التحليل)
        ↓
8. مراجعة + تصدير الدراسة (تبويب الداشبورد)
```

كل خطوة لها زر في الواجهة + سكربت CLI.

---

## 📜 سكربتات CLI

```powershell
# تنزيل النماذج الجاهزة
python scripts/download_models.py

# تجهيز dataset من CVAT export
python scripts/prepare_dataset.py --source data/annotations/reviewed --output data/dataset

# تدريب YOLOv8m
python scripts/train.py --base models/pretrained/yolov8m.pt --data data/dataset/dataset.yaml --epochs 100

# تحليل أخطاء النموذج
python scripts/error_analysis.py --model models/finetuned/baseer-v1/weights/best.pt --data data/dataset/dataset.yaml

# قراءة لوحات (PaddleOCR)
python scripts/ocr_plates.py plate1.jpg plate2.jpg plate3.jpg

# تصدير الدراسة كاملة
python scripts/export_study.py --format all --output data/exports
```

---

## 🛡️ معايير الجودة

| المعيار | الحالة |
|--------|--------|
| اختبارات وحدة | **185** اختبار مارّ |
| Ruff (lint) | نظيف 100% |
| Black (format) | منسّق |
| لا ملف > 500 سطر | ✅ (أكبر ملف: `rules.py` ≈ 480 سطر) |
| لا I/O في main thread | ✅ (كل عملية ثقيلة → QThread) |
| Core بدون PyQt | ✅ (`app/core/` لا يستورد من Qt) |

---

## 📚 التوثيق التفصيلي

- [الخطة الكاملة (8 أسابيع)](./docs/baseer-plan.md)
- [المعمارية](./docs/architecture.md)
- [دليل التصنيف في CVAT](./docs/annotation_guide.md)

---

## 🤝 المساهمة

هذا مشروع شخصي حالياً. الـ PRs مرحَّب بها بعد فتح issue للنقاش.

```
main           ← الإصدار المستقر
claude/phase-* ← فروع التطوير (تُحذف بعد الدمج)
```

كل PR يُشغّل CI تلقائياً: **ruff → black → pytest**.

---

## 📄 الترخيص

سيُحدَّد لاحقاً (مرشّح للفتح كمصدر مفتوح كمرجع عربي).

---

**المالك**: عبدالكريم العبود · **النسخة**: 0.1.0 · **2026**

</div>
