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
| 🚦 **التحليل** | 9 كواشف مخالفات تلقائية + إدخال يدوي (إضافة/تعديل/حذف) مع حفظ المخالفات اليدوية عند إعادة التحليل |
| 📊 **الداشبورد** | KPIs ملوّنة، رسوم تفاعلية (bar/line/heatmap)، مستعرض مخالفات بمراجعة، تصدير JSON/CSV/Excel/PDF عربي |

---

## 🚦 المخالفات المدعومة

يغطّي التطبيق حالياً **9 أنواع مخالفات تلقائية** + قناة **إدخال يدوي** للحالات التي يرى المراجع البشري الحاجة لتسجيلها.

| # | المخالفة | النوع | الكاشف | متطلبات |
|---|----------|------|--------|---------|
| 1 | 🚦 قطع الإشارة الحمراء | تلقائي | `RedLightDetector` | منطقة `stop_line` |
| 2 | 🔄 السير بالاتجاه المعاكس | تلقائي | `WrongDirectionDetector` | عيّنة tracks ≥ 3 |
| 3 | 🪖 عدم لبس الخوذة | تلقائي | `NoHelmetDetector` | — |
| 4 | 🅿️ الوقوف الخاطئ | تلقائي | `IllegalParkingDetector` | منطقة `no_parking` |
| 5 | ⤴️ التجاوز الخاطئ | تلقائي | `IllegalOvertakingDetector` | خط `lane_line_solid` |
| 6 | 🏎️ السرعة الزائدة | تلقائي | `SpeedingDetector` | معايرة `meters_per_px` |
| 7 | 🛣️ عدم الالتزام بالمسار | تلقائي | `LaneKeepingDetector` | خطوط مسار (YOLO أو zones) |
| 8 | 💡 إساءة استخدام أنوار التلاقي | تلقائي (heuristic) | `HighBeamDetector` | ملف فيديو + إطارات ليلية |
| 9 | 🚗💨 عدم ترك مسافة آمنة | تلقائي | `FollowingDistanceDetector` | معايرة `meters_per_px` |
| ✍️ | مخالفة يدوية أخرى | **يدوي** | `ManualViolationDialog` | — |

**ملاحظات تقنية:**

- **عدم الالتزام بالمسار**: يقيس "التطفل" المستمر على خط مسار عبر قص قطعة-bbox (Liang–Barsky) لمدة ≥ 2 ثانية — مختلف عن التجاوز الذي يكشف عبور مرة واحدة لخط متصل.
- **المسافة الآمنة**: يستخدم Time-to-Collision (TTC) + قاعدة نصف السرعة، مع اقتران المركبات في نفس المسار (x-tolerance) وتجاهل التوقف عند الإشارات (`< 15 km/h`).
- **إساءة الأنوار** (heuristic — المرحلة 1): يكشف الإطارات الليلية (HSV mean V) ثم البقع البيضاء المشبعة في منطقة المصابيح، ويوسَم في الملاحظات بـ `[heuristic]` للمراجعة البشرية. المرحلة 2 (مستقبلية) تستبدل هذا بفئة YOLO `high_beam_on` مدرَّبة.
- **التدخل البشري**: المخالفات اليدوية تُحفظ بـ `source='manual'` و `notes='[manual] ...'` ولا تُحذف عند إعادة التحليل بفضل شرط `AND source='auto'` في DELETE.

### مراجع GitHub المفتوحة المستفاد منها

| المخالفة | المرجع |
|----------|--------|
| المسار | [`cfzd/Ultra-Fast-Lane-Detection`](https://github.com/cfzd/Ultra-Fast-Lane-Detection)، [`Turoad/lanedet`](https://github.com/Turoad/lanedet) |
| المسافة الآمنة (TTC) | [`enginBozkurt/SFND_3D_Object_Tracking-1`](https://github.com/enginBozkurt/SFND_3D_Object_Tracking-1)، [`visualbuffer/copilot`](https://github.com/visualbuffer/copilot) |
| المسافة (px→m) | [`paul-pias/Object-Detection-and-Distance-Measurement`](https://github.com/paul-pias/Object-Detection-and-Distance-Measurement) |
| الأنوار العالية | [`lewjiayi/Vehicle-Headlight-Tracker`](https://github.com/lewjiayi/Vehicle-Headlight-Tracker) |

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

## 📦 بناء مُثبِّت Windows (.exe)

لتوزيع التطبيق كملف تنصيب واحد بدون الحاجة لتثبيت Python على جهاز المستخدم:

```powershell
pip install pyinstaller
.\scripts\build_installer.ps1
```

السكربت يولّد الأيقونة، يحزم التطبيق بـ PyInstaller، ويبني مُثبِّت Windows عبر Inno Setup → `dist/installer/Baseer-Setup-0.1.0.exe`.

📖 **التفاصيل الكاملة**: [`docs/build_installer.md`](./docs/build_installer.md)

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

**337 اختباراً** تمر في ~20 ثانية بدون GPU ولا ultralytics، بتغطية **71%**:

| الطبقة | التغطية |
|--------|---------|
| `app/core/` | ~90% |
| `app/utils/` | ~85% |
| `app/ui/` + `app/workers/` | ~55% (ودجات حقيقية بـ`QT_QPA_PLATFORM=offscreen`) |

يشمل ذلك **اختبار قبول E2E** (`tests/test_e2e_pipeline.py`) يمشي المسار الكامل
استيراد → استدلال → استخراج → تصدير بمكوّنات محقونة، ويمنع تكرار فجوات التكامل.
CI يفرض `--cov-fail-under=60`.

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
│   │   ├── dialogs/           # ManualViolationDialog (إضافة/تعديل مخالفة يدوية)
│   │   └── widgets/           # thumbnail_grid, video_player, stats_charts
│   │
│   ├── core/                  # المنطق التطبيقي (لا يستورد PyQt6)
│   │   ├── db.py              # DuckDB connection + 7 جداول + ترحيل source/manual_user
│   │   ├── library.py         # استيراد، dedup، metadata
│   │   ├── annotator.py       # CVAT XML export
│   │   ├── dataset.py         # CVAT YOLO → YOLOv8 (70/20/10)
│   │   ├── trainer.py         # YOLOv8 fine-tuning (mockable)
│   │   ├── analyzer.py        # inference + ByteTrack + extract_violations
│   │   ├── rules.py           # 6 كواشف أصلية + Base/Zone/Track
│   │   ├── detectors/         # كواشف إضافية (lane_keeping, following_distance, high_beam)
│   │   ├── frame_sampler.py   # قارئ إطارات حسب الرقم (لـ HighBeam)
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
│   ├── constants.py           # DETECTION_CLASSES (13) + ViolationType (10) + ViolationSource
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
├── tests/                     # 212 اختبار
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

# تعريف مناطق مقطع (خط توقف، ممنوع الوقوف، خط مسار) — يفكّ حصار كواشف المناطق
python scripts/define_zones.py --video-id 3 --zones zones.json
python scripts/define_zones.py --video-id 3 --list

# معايرة مقطع (meters_per_px) — يفكّ حصار كاشفَي السرعة والمسافة الآمنة
python scripts/calibrate.py --video-id 3 --points 100 500 400 500 --distances 10

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
| اختبارات وحدة | **337** نجاح (تغطية 71%) |
| Ruff (lint) | نظيف 100% |
| Black (format) | منسّق (الإصدار مثبَّت في CI ويُحدَّث عبر Dependabot) |
| حدود حجم الملفات والدوالّ | ✅ **مفروضة في CI** عبر `scripts/check_structure.py` |
| لا I/O ثقيل في main thread | ✅ (العمليات الطويلة → QThread، الصور المصغّرة → QThreadPool، التبويبات تُبنى كسولاً) |
| Core بدون PyQt | ✅ (`app/core/` لا يستورد من Qt) |
| فحص الأنواع (mypy) | ✅ يعمل في CI على `app/` |
| فحص ثغرات التبعيات | ✅ `pip-audit` في CI + Dependabot أسبوعي |
| تباين الألوان WCAG AA | ✅ مُختبَر آلياً لكل تركيبة في `app/ui/theme.py` |

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

## 🔐 الخصوصية والبيانات

بَصير يخزّن **بيانات شخصية** بموجب أي إطار حماية بيانات معاصر (بما فيه نظام
حماية البيانات الشخصية السعودي PDPL): أرقام لوحات، أوقات، إحداثيات موقع،
وإطارات إثبات قد تحوي وجوهاً. اقرأ هذا قبل الاستخدام الجادّ:

| السؤال | الجواب |
|--------|--------|
| أين تُخزَّن؟ | محلياً فقط: `data/results.duckdb` (أو `%LOCALAPPDATA%\Baseer` في النسخة المحزومة). لا يُرسَل شيء لأي خادم. |
| هل هي مشفَّرة؟ | **لا** — الملف بصلاحيات نظام التشغيل الافتراضية. لا تضع القاعدة على تخزين مشترك. |
| ماذا يُصدَّر؟ | التصدير **مجهّل افتراضياً**: كل لوحة تُستبدَل برمز ثابت `PLATE-XXXXXXXXXX`. أزل تحديد «تصدير مجهّل» فقط عند حاجة فعلية للأرقام (أو مرّر `--with-plates` في `scripts/export_study.py`). |
| هل الرمز قابل للعكس؟ | لا. ويمكن تغيير الملح بـ`BASEER_ANON_SALT` لفصل الدراسات عن بعضها. |
| ماذا يعني حذف مقطع؟ | تُحذف سجلات القاعدة والصورة المصغّرة. **ملف الفيديو الأصلي يبقى على القرص** — احذفه يدوياً إن أردت إزالة محتواه فعلياً. |
| من سجّل هذه المخالفة اليدوية؟ | العمود `manual_user` يحفظ اسم مستخدم نظام التشغيل. ⚠️ **ليست هوية مُصادَقاً عليها** — التطبيق بلا نظام دخول والقيمة قابلة للانتحال. تُستخدم كأثر تشغيلي لا كإثبات. |
| هل هناك سجل تدقيق؟ | نعم — جدول `audit_log` يحفظ تغييرات حالة المراجعة والتعديلات والحذف مع القيمة السابقة. |

---

## 📄 الترخيص

**[AGPL-3.0](./LICENSE)** — وهو ليس اختياراً حراً: المشروع يعتمد على
**Ultralytics YOLOv8** المرخَّص AGPL-3.0 ويحزمه في مُثبِّت مُوزَّع، وهذا ترخيص
copyleft قوي يسري على العمل المشتق كله.

📖 التفاصيل وبدائل الترخيص المتساهل: [`docs/licensing.md`](./docs/licensing.md)

---

**المالك**: عبدالكريم العبود · **النسخة**: 0.1.0 · **2026**

</div>
