<div dir="rtl">

# مراجعة شاملة — بَصير | Baseer

**التاريخ:** 2026-07-29 · **المُراجَع:** `main @ 9dca007` (v0.1.0)
**النطاق:** كامل المستودع — 51 ملف Python في `app/`، 9 سكربتات، 28 ملف اختبار، CI، نظام البناء، التوثيق.
**منهجية التحقق:** قراءة كاملة للكود + تشغيل فعلي لمجموعة الاختبارات + قياس التغطية + تشغيل ruff/black + فحص resolution للتبعيات من PyPI.

> **ملاحظة على السياق:** يوجد في المستودع مراجعة سابقة (`docs/reviews/engineering-review-2026-07.md`, 2026-07-15) نُفِّذت معظم بنودها. هذه المراجعة **مستقلة** وتقيس الحالة الحالية بعد تلك الإصلاحات، ولا تعيد سرد ما أُصلح إلا حين يبقى أثره.

---

## 1. نظرة عامة سريعة

**بَصير** تطبيق سطح مكتب محلي بالكامل (بلا سحابة) يحوّل مقاطع فيديو مرورية (داش كام/CCTV/سوشل ميديا) إلى بيانات مخالفات منظّمة: استيراد ← pseudo-labeling بـ YOLO ← تصنيف يدوي في CVAT ← fine-tuning ← استخراج مخالفات بمحرك قواعد ← داشبورد وتصدير. البنية أربع طبقات: `ui/` (PyQt6) ← `workers/` (QThread) ← `core/` (منطق نقي بلا Qt) ← `data/results.duckdb`.

**التقنيات:** Python 3.10+ · PyQt6 + pyqtgraph · DuckDB · Ultralytics YOLOv8 (+ByteTrack) · PaddleOCR · OpenCV · PySceneDetect · FFmpeg/ffprobe (subprocess) · pydantic-settings · reportlab + arabic-reshaper + python-bidi · openpyxl · PyInstaller + Inno Setup · pytest/ruff/black/mypy + GitHub Actions.

**نتائج التحقق الفعلي:**

| ما جُرِّب | النتيجة |
|---|---|
| `pytest` | **231 نجاح + 8 متخطّى** في 7.3 ثانية (4 منها تخطّت لغياب `libEGL` في بيئتي، و4 لغياب `openpyxl`/`reportlab`) |
| تغطية `--cov=app` | **43% إجمالي** — `core/` ~90%، `ui/` **0%**، `workers/` **0%** |
| `ruff check app tests scripts` | نظيف 100% ✔ |
| `black --check` (26.3.1) | ملفان يحتاجان إعادة تنسيق (CI يثبّت 24.8.0 فيمرّ) |
| `pip index versions paddleocr` | أحدث إصدار **3.7.0** — و`requirements.txt` يقول `>=2.8.0` |

---

## 2. المراجعة التقنية والهندسية (وزن 45%) — **7.3/10**

### 2.1 البنية المعمارية وفصل المسؤوليات — **9/10**

الفصل حقيقي ومُنفَّذ بانضباط نادر: `app/core/` **لا يستورد PyQt6 إطلاقاً** (تحقّقت بالفحص الشامل)، والعمليات الثقيلة كلها في عمّال منفصلين، وحقن التبعيات ممنهج (`InferenceCallable` في `analyzer.py:58`، `TrainFunction/ValFunction` في `trainer.py:77-78`، `RecognizeCallable` في `ocr.py:45`، `FrameProvider` Protocol في `frame_sampler.py:14`). هذا بالضبط ما جعل 231 اختباراً يعمل في 7 ثوانٍ بلا GPU ولا ultralytics.

**الخصومات — تسريب التغليف (Encapsulation leak):** طبقة الواجهة تصل إلى `Database` الخاص بالخدمات مباشرة في **15 موضعاً** موسوماً بـ `# noqa: SLF001`:

```python
# app/ui/analysis_view.py:164
rows = self._service._db.fetch_all(  # noqa: SLF001
    "SELECT v.id, v.filename, v.status, "
    "COALESCE((SELECT COUNT(*) FROM detections d WHERE d.video_id = v.id), 0), ..."
```

ومثله `dashboard_view.py:273,317`، `annotator_view.py:141`، `duplicates_dialog.py:127`، `scripts/export_study.py:66`. النتيجة: **SQL خام مكتوب داخل ملفات الواجهة** — وهذا يناقض حرفياً ما يقوله `docs/architecture.md`: «الواجهة **لا تحتوي على أي منطق تجاري** — تستدعي Core Services فقط». كل `noqa: SLF001` هنا ليس استثناءً مبرَّراً بل دَين معماري مُوثَّق.

**الحل:** أضف التوابع الناقصة للخدمات — `LibraryService.video_summaries()`، `DashboardService.list_violations_for_editing()`، `AnalyzerService.videos_with_counts()` — واحذف كل `_db` من `app/ui/`. تكلفة تقديرية: يوم واحد، وتفتح الباب لاختبار هذه الاستعلامات في `core/`.

### 2.2 قابلية القراءة والصيانة — **8/10**

الكود ممتاز القراءة: docstrings عربية على كل دالة عامة تقريباً، أسماء واضحة، تعليقات تشرح **لماذا** لا **ماذا** (مثال ممتاز: `db.py:150-159` يشرح سبب آلية التعافي من WAL، و`library.py:277-279` يشرح لماذا لا يُلَفّ الحذف في معاملة).

**المشكلة الأولى — قراءة الصفوف بالمؤشر الرقمي:**

```python
# app/ui/library_view.py:314-327
cols = [
    ("المعرّف", row[0]), ("الاسم", row[2]), ("المصدر", row[3]),
    ("المدة (ثانية)", row[4]), ..., ("الحالة", row[18]),
]
```

هذا مبني على `SELECT *` من جدول `videos` بترتيب أعمدة **ضمني**. أي `ALTER TABLE videos ADD COLUMN` مستقبلي — والمشروع يستخدم هذا النمط فعلاً في `db.py:102-103` — سيُزيح `row[18]` بصمت ويعرض بيانات خاطئة بلا أي خطأ. **الحل:** استبدل `SELECT *` بقائمة أعمدة صريحة، أو أعِد dataclass من `LibraryService.get_video()` بدل tuple.

**المشكلة الثانية — مخالفة القواعد الصارمة المُعلَنة:** `docs/architecture.md` و`README.md:306` يعلنان «لا ملف > 500 سطر ✅» و«لا دالة تتجاوز 50 سطر». الواقع:
- `app/core/rules.py` = **568 سطراً** (يتجاوز الحد، والـ README يضع علامة ✅ بجانبه).
- `AnalysisView._build_ui()` (`analysis_view.py:77-158`) = **81 سطراً**.
- `ManualViolationDialog._build_ui()` (`manual_violation_dialog.py:73-145`) = **72 سطراً**.

هذه ليست كارثة هندسية، لكن **قاعدة مُعلَنة ومخروقة أسوأ من عدم وجود قاعدة** — لأنها تُفقد الثقة ببقية جدول «معايير الجودة». إما تُفعّل القاعدة في CI (`ruff` قواعد `PLR0915`/حد أسطر ملف) أو تُحذف من التوثيق.

**المشكلة الثالثة — لا نظام ترحيل (migrations):** المخطط في `db.py:19-136` عبارة عن tuple ثابتة تُنفَّذ كاملة عند كل إقلاع، والترحيلات مضافة كسطور `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` داخلها (`db.py:102-104`). مع كل ترحيل جديد تطول القائمة، ولا يوجد جدول `schema_version` ولا مسار للتراجع ولا لترحيلات تحتاج تحويل بيانات. **الحل:** جدول `schema_migrations(version, applied_at)` + قائمة `MIGRATIONS: list[tuple[int, str]]` تُطبَّق بالترتيب مرة واحدة.

### 2.3 التكرار (DRY) و Code Smells — **7/10**

DRY جيد عموماً: حساب السرعة موحَّد في `geometry.speed_from_centers_kmh` ويستدعيه كاشفا السرعة والمسافة، وأنماط `Zone/Track/ViolationCandidate` مشتركة.

**التكرار المتبقي:**

1. **`_frame_where_track_crosses` مكرَّرة حرفياً مرتين** — `rules.py:176-185` (RedLight) و`rules.py:436-444` (IllegalOvertaking) — نفس الخوارزمية بنفس الحلقة، الفرق فقط في المتغير المُمرَّر. **الحل:** دالة وحدة `first_crossing_frame(track, lines) -> int | None` على مستوى الوحدة.
2. **بناء `Detection` من صف DB مكرَّر** — `analyzer.py:141-151` و`annotator.py:121-131` بنفس التسع أعمدة وبنفس التحويلات. **الحل:** `Detection.from_row(r)` classmethod.
3. **نمط `QThread + worker + 6 وصلات signals` مكرَّر ثلاث مرات** — `library_view.py:209-225`، `annotator_view.py:194-209`، `trainer_view.py:203-221` — نفس الستة أسطر بالضبط (`started→run`, `finished→quit`, `failed→quit`, `finished→deleteLater`, `failed→deleteLater`, `thread.finished→deleteLater`). **الحل:** `app/workers/runner.py: run_in_thread(worker, *, on_finished, on_failed) -> QThread`.
4. **دوال `start_*_in_thread` ميتة** — `import_worker.py:65`، `inference_worker.py:56`، `training_worker.py:48` — ثلاث دوال (≈70 سطراً) لا يستدعيها أي شيء في المستودع؛ الواجهة تبني الـ threads يدوياً. كود ميت يجب حذفه أو استخدامه كـ helper الموحَّد أعلاه.

**Code smells محددة:**

- **`hash()` غير حتمي في اسم ملف** — `library.py:159`:
  ```python
  thumb_path = thumb_dir / f"{file_path.stem}_{abs(hash(str(file_path)))}.jpg"
  ```
  `hash()` على النصوص في Python **مُلَح عشوائياً لكل عملية تشغيل** (PYTHONHASHSEED). نفس الملف يعطي اسم thumbnail مختلفاً في كل جلسة → thumbnails يتيمة تتراكم في `data/thumbnails/` بلا مرجع. **الحل:** `hashlib.sha1(str(path).encode()).hexdigest()[:12]`.
- **`phash_distance()` ميتة عملياً** — `hash_utils.py:50` مُختبَرة (`test_hash_utils.py:34-41`) لكن لا يستدعيها أي كود إنتاج. `detect_duplicates()` (`library.py:323-327`) يجمّع بـ **تساوي phash التام** لا بمسافة Hamming — أي أن الشيفرة المكتوبة لاكتشاف التشابه البصري **غير مستعملة**، وكل تشابه ليس متطابقاً 100% يفوت. هذا يقلّل قيمة "إدارة التكرار" المُعلَنة في README.
- **إعدادات ميتة** — `config.py:75-76`: `ui_theme` و`ui_language` معرّفتان وموثّقتان في `.env.example:24-25` و**لا يقرؤهما أي كود**. المستخدم الذي يضبط `BASEER_UI_THEME=dark` لا يحدث شيء.
- **دمج نصوص ضمني عرضي** — `dashboard.py:64`، `calibration.py:106`، `exporter.py:376`، `annotator_view.py:167`: `"... " "..."` — دمج سلاسل متجاورة بلا `+`. يعمل، لكنه مصدر شائع لأخطاء المسافات المفقودة في SQL، وهو سبب اختلاف black بين الإصدارات (انظر 2.8).

### 2.4 معالجة الأخطاء والحالات الحدّية — **6/10**

هذا أضعف محور هندسي. النمط السائد `except Exception: # noqa: BLE001` + `logger` موجود في **أكثر من 25 موضعاً**، وفي عدة مواضع يُخفي فشلاً يهم المستخدم:

**(أ) فشل الكواشف صامت تماماً:**
```python
# app/core/rules.py:529-533
for detector in detectors:
    try:
        out.extend(detector.detect(tracks, by_frame, zones, fps))
    except Exception as exc:  # noqa: BLE001
        logger.exception("فشل الكاشف %s: %s", detector.__class__.__name__, exc)
```
لو انهار `HighBeamDetector` على كل مقطع، يرى المستخدم في الواجهة «اكتمل — 0 مخالفة» ولا شيء غير ذلك. الرسالة في ملف log لن يفتحه أحد. **الحل:** أعِد `(candidates, failures: list[str])` من `run_detectors`، ومرّرها عبر إشارة الـ worker إلى شريط الحالة: «اكتمل — 12 مخالفة، فشل كاشفان (انظر السجل)».

**(ب) الأدلة تُنسب لإطارات خاطئة — خطأ صحّة مؤكَّد:**
```python
# app/ui/dialogs/evidence_dialog.py:178-186
frame_nos = evidence_frame_numbers(self._row["evidence_frames"])
images = extract_evidence_images(...)
for frame, image in zip(frame_nos, images, strict=False):
    layout.addWidget(self._thumb_widget(frame, image, container))
```
و`extract_evidence_images` (`evidence_dialog.py:72-75`) **تُسقط بصمت** أي إطار يُرجع `None`:
```python
for frame_no in frame_nos[:max_frames]:
    frame = provider.get_frame(frame_no)
    if frame is not None:
        images.append(frame)
```
فإذا كانت `evidence_frames = [100, 250, 400]` وفشلت قراءة الإطار 100، تصبح `images = [صورة250, صورة400]` ويربطها `zip` بـ `[100, 250]` → **صورة الإطار 250 معنونة «إطار 100»**. في تطبيق مُخرَجه دليل على مخالفة مرورية، هذا خطأ ذو ثقل. **الحل:** أعِد `list[tuple[int, np.ndarray]]` من `extract_evidence_images` بدل قائمة صور مجرّدة.

**(ج) مدة «بلا خوذة» تُحسب من إطارات غير متتالية:**
```python
# app/core/rules.py:317-321
if not no_helmet_frames:
    continue
duration_s = (no_helmet_frames[-1] - no_helmet_frames[0]) / max(fps, 1e-6)
if duration_s < self._min_duration_sec:
```
`no_helmet_frames` مجموعة **متفرقة**. دراجة كُشفت بلا خوذة في الإطار 10 ثم لبس الراكب الخوذة ثم اختفت الخوذة مجدداً في الإطار 400 (30fps) تُحسب لها مدة 13 ثانية → مخالفة مؤكدة زائفة. لاحظ أن الكاشفين الآخرين (`lane_keeping.py:69-106`, `following_distance.py`) يستخدمان منطق runs متتالية بشكل صحيح — فالمعالجة غير متسقة داخل نفس المشروع. **الحل:** طبّق نفس منطق `_find_straddle_runs` هنا (أطول تتابع، مع سماح فجوة إطار أو إطارين).

**(د) لا معاملة حول حذف+إدراج المخالفات:**
```python
# app/core/analyzer.py:191-219
self._db.execute("DELETE FROM violations WHERE video_id = ? AND source = 'auto'", (video_id,))
rows = [...]
if rows:
    self._db.executemany("INSERT INTO violations ...", rows)
```
لو فشل `executemany` (قيد، قرص ممتلئ، انقطاع)، تكون المخالفات التلقائية القديمة **حُذفت** والجديدة **لم تُكتب** → فقدان بيانات صامت. `Database` لا يوفّر أصلاً `begin/commit/rollback` أو context manager للمعاملات. **الحل:** أضف `Database.transaction()` (contextmanager يُصدر BEGIN/COMMIT/ROLLBACK) ولُفّ العملية بها.

**(هـ) انهيار الإقلاع قبل وجود واجهة:**
```python
# app/main.py:47-55
_configure_logging()
...
db = get_database(settings)   # لا try/except
...
app = QApplication(sys.argv)  # ← الواجهة تُبنى بعد ذلك
```
لو فشل فتح DuckDB (نسخة ثانية من التطبيق تحتفظ بالقفل، صلاحيات، قرص ممتلئ) يموت التطبيق بـ traceback في stdout. وفي بناء PyInstaller بـ `console=False` (`Baseer.spec:85`) **لا يوجد stdout أصلاً** — المستخدم ينقر الأيقونة ولا يحدث شيء إطلاقاً. **الحل:** أنشئ `QApplication` أولاً، ثم لُفّ التهيئة بـ try/except يعرض `QMessageBox.critical` بالسبب.

**(و) `_on_progress` يرفع استثناءً كآلية إلغاء** — `import_worker.py:58-61` يرفع `InterruptedError` داخل callback التقدّم ليخترق `LibraryService.import_paths`؛ يعمل لكنه استخدام لتدفّق الاستثناءات في مسار عادي، ويُظهر للمستخدم «فشل الاستيراد» بدل «أُلغي».

### 2.5 الأداء واستهلاك الموارد — **5/10**

**(أ) 🔴 استهلاك ذاكرة كارثي في `HighBeamDetector`:**
```python
# app/core/detectors/high_beam.py:100-102
frame_cache: dict[int, np.ndarray | None] = {}
for f in sorted(sampled_frames):
    frame_cache[f] = provider.get_frame(f)
```
هذا **يقرأ ويحتفظ في الذاكرة بكل الإطارات المسحوبة دفعةً واحدة** قبل معالجة أيٍّ منها. `sampled_frames` = كل إطار فيه مركبة ورقمه يقبل القسمة على `sample_every_n_frames` (=5 افتراضياً). لمقطع 5 دقائق بـ 30fps و1080p:

> 9000 إطار ÷ 5 = **1800 إطار** × (1920×1080×3 بايت) ≈ **1800 × 6.2 م.ب ≈ 11 جيجابايت**

على جهاز 32GB RAM هذا سيتسبب في تبديل قرص عنيف، وعلى مقاطع أطول أو دفعة مقاطع → `MemoryError`. والكاشف يُضاف **افتراضياً** لأي مقطع ملفه موجود (`analyzer.py:182-183`). **الحل (سطران):** ادمج الحلقتين — عالج كل إطار فور قراءته واحتفظ بالنتيجة البوليانية فقط، لا بالمصفوفة.

**(ب) HSV يُعاد حسابه لكل كشف لا لكل إطار** — `high_beam.py:113` يستدعي `_is_night_frame(frame, cv2)` داخل حلقة `for det in track.detections`، فتُحوَّل **الصورة الكاملة** إلى HSV مرة لكل مركبة في الإطار. عشر مركبات = عشرة تحويلات 1080p متطابقة. **الحل:** احسب `is_night` مرة لكل `frame_no` وخزّن `dict[int, bool]`.

**(ج) `FollowingDistanceDetector` تربيعية** — `following_distance.py:58-71`: حلقة مزدوجة على كل أزواج المركبات، وكل `_check_pair` يبني قاموسين ويفرز ثلاث قوائم. 200 track في مقطع مزدحم = 40,000 استدعاء. **الحل:** فهرسة مكانية بسيطة — جمّع الـ tracks في «سلال x» بعرض `same_lane_x_tolerance_px` وقارن داخل السلة والسلتين المجاورتين فقط.

**(د) I/O في الـ main thread — مخالفة صريحة لقاعدة معمارية مُعلَنة:** `docs/architecture.md` يقول «لا I/O في main thread» و README:307 يضع ✅. لكن:
- `MainWindow._build_tabs()` (`main_window.py:84-88`) يبني **التبويبات الخمسة كلها فوراً**، وكل تبويب يستدعي `refresh()` في مُنشئه (`library_view.py:46`، `dashboard_view.py:51`، `analysis_view.py:75`، `annotator_view.py:46`) → موجة استعلامات DuckDB متزامنة قبل ظهور النافذة.
- `ThumbnailGrid._load_icon` (`thumbnail_grid.py:78-81`) يقرأ ملف JPEG من القرص ويبني `QPixmap` **لكل بطاقة** في الـ main thread. مكتبة 500 مقطع = 500 قراءة قرص متزامنة تُجمّد الواجهة (والصنف موصوف في docstring بأنه «تحميل كسول» — وهو ليس كذلك).
- `DashboardView._refresh_charts()` (`dashboard_view.py:188-225`) يهدم ويعيد بناء كل widgets الرسوم (بما فيها `pg.ImageView`) عند كل تحديث.

**(هـ) بحث بلا debounce يعيد بناء الشبكة كاملة على كل حرف:**
```python
# app/ui/library_view.py:128
self._search_box.textChanged.connect(self.refresh)
```
و`refresh()` (`library_view.py:281-303`) يُجري `list_videos()` + `count_videos()` + `total_duration_seconds()` (ثلاثة استعلامات) ثم يعيد بناء كل البطاقات وكل الـ QPixmaps. كتابة «test» = **4 دورات كاملة**. والأسوأ: الفلترة النصية تُطبَّق **في Python بعد جلب كل الصفوف** (`library_view.py:296`) بدل `WHERE filename ILIKE ?`. **الحل:** `QTimer` بمهلة 250ms + نقل الفلترة إلى SQL.

**(و) `get_settings()` يعيد قراءة `.env` في كل استدعاء** — `config.py:96-98` تُنشئ `AppSettings()` جديداً بلا cache، وتُستدعى في مُنشئ كل خدمة وكل view. **الحل:** `@lru_cache` أو singleton.

### 2.6 الاختبارات — **7/10**

**ما هو ممتاز:** 231 اختباراً يمر في 7.3 ثانية بلا GPU. الاختبارات ذات معنى حقيقي — `test_rules.py` (21 اختباراً)، `test_geometry.py` (23)، `test_dataset.py` (18)، `test_ocr.py` (16) — وتغطي حالات حدّية فعلية لا مجرد happy path. وجود `test_db_wal_recovery.py` و`test_violations_source_migration.py` و`test_config_frozen.py` يدل على أن الاختبارات تُكتب كـ **حراس ضد نكوص أخطاء حقيقية** — وهذا أنضج مستوى.

**الفجوة المقيسة (بيانات `pytest --cov`):**

| الطبقة | التغطية |
|---|---|
| `app/core/zones.py`, `constants.py` | 100% |
| `app/core/calibration, annotator, rules, detectors/*, error_analysis` | 93–98% |
| `app/core/analyzer.py` | 69% |
| `app/core/exporter.py` | 33% (Excel/PDF متخطّيان لغياب المكتبات) |
| `app/utils/video_utils.py` | **25%** |
| **`app/ui/**` (11 ملفاً)** | **0%** |
| **`app/workers/**` (3 ملفات)** | **0%** |
| `app/main.py` | 0% |
| **الإجمالي** | **43%** |

ملاحظة إنصاف: 4 من ملفات اختبار الحوارات تخطّت في بيئتي لغياب `libEGL`؛ في CI (الذي يثبّت `libegl1`) تعمل وتغطي `manual_violation_dialog`, `evidence_dialog`, `zone_editor_dialog`, `duplicates_dialog`. لكن **الخمسة views الرئيسية والعمّال الثلاثة لا يوجد لها ملف اختبار أصلاً** — تحقّقت بالبحث في `tests/`.

**ما ينقص تحديداً:**
1. **لا اختبار قبول E2E واحد** يمشي `استيراد → استدلال (mock) → extract_violations → قراءة من DB`. المراجعة السابقة أوصت بهذا صراحةً ولم يُنفَّذ. هذا هو الاختبار الذي كان سيكشف فجوة التكامل الأصلية (C1)، ولا يزال غيابه يعني أن أي انفصال جديد بين المكوّنات لن يُكتشف.
2. **`video_utils.py` بتغطية 25%** رغم أنه بوابة كل الاستيراد؛ `_parse_fps`، `_parse_recorded_at`، وتحليل ناتج ffprobe كلها قابلة للاختبار بـ JSON مُثبَّت بلا FFmpeg.
3. **العمّال بلا اختبار** رغم أنهم منطق تزامن (الأخطر) ورغم توفّر `pytest-qt` في `requirements.txt` (وهو **غير موجود** في `requirements-ci.txt` — فحتى لو كُتبت اختبارات signals لن تعمل في CI).
4. **لا بوابة تغطية في CI** — يمكن حذف نصف الاختبارات وسيبقى CI أخضر.

### 2.7 التوثيق — **7/10**

التوثيق غزير وعالي الجودة شكلاً: README شامل بالعربية RTL مع جداول ومخططات، `docs/baseer-plan.md` (1005 أسطر)، `docs/architecture.md`، `docs/build_installer.md`، `docs/slim_installer.md`، `docs/annotation_guide.md`، ومراجعة هندسية سابقة موثّقة. الـ docstrings تغطي فعلياً كل دالة عامة تقريباً.

**المشكلة: التوثيق يعِد بأكثر مما يُنجز، وبعضه غير دقيق قابل للقياس:**

| ادّعاء | الموضع | الواقع المقيس |
|---|---|---|
| «**212 اختبار** (208 نجاح + 4 متخطّى)» | `README.md:162,303` | 239 مجمّع — **231 نجاح + 8 متخطّى** |
| «لا ملف > 500 سطر ✅» | `README.md:306` | `rules.py` = **568 سطراً** |
| «لا I/O في main thread ✅» | `README.md:307` | خمسة تبويبات تستعلم DB في مُنشئاتها + قراءة thumbnails في main thread |
| «الواجهة لا تحتوي أي منطق تجاري» | `docs/architecture.md` | SQL خام في 4 ملفات واجهة |
| «لا دالة تتجاوز 50 سطر» | `docs/architecture.md` | `AnalysisView._build_ui` = 81 سطراً |
| «الترخيص: سيُحدَّد لاحقاً» | `README.md:335` | لا ملف LICENSE، مع تبعية AGPL (انظر 4.8) |

جدول «معايير الجودة» في README مصمَّم ليقرأه مقيّم خارجي، وثلاثة من ستة بنوده غير صحيحة. **الحل:** إما تُفعَّل هذه القواعد في CI (فتصبح الادعاءات صحيحة تلقائياً)، أو تُحوَّل الجداول إلى «أهداف» بدل «حالة». وإضافة سطر `pytest --collect-only -q | tail -1` في CI يُبقي الرقم دقيقاً.

نقص إضافي: **لا `CONTRIBUTING.md`، لا `CHANGELOG.md`، لا `.github/pull_request_template.md`، لا LICENSE** — رغم أن README يستقبل PRs.

### 2.8 اتفاقيات التسمية ونمط الكود الموحّد — **8/10**

`ruff` (E, W, F, I, B, UP, N) يمر نظيفاً 100% — تحقّقت بالتشغيل. التسمية متسقة: `_private`، `SCREAMING_CASE` للثوابت مع `Final`، `PascalCase` للأصناف، `from __future__ import annotations` في كل ملف، type hints شاملة، `__all__` معرَّفة في أغلب الوحدات. الترميز العربي متسق في الرسائل والتعليقات مع إنجليزية في المصطلحات التقنية — قرار جيد.

**ثغرتان:**

1. **`mypy` مُعدّ بـ `strict = true` في `pyproject.toml:69-75` ولا يُشغَّل في أي مكان.** `ci.yml` يشغّل ruff + black + pytest فقط. إعداد صرامة معطّل = وهم أمان؛ ومن المرجّح أن الكود لن يمر منه اليوم بلا عمل (مثال: `library.py:67` يستخدم `progress_cb: callable | None` بحرف صغير — وهي `builtins.callable` الدالة لا `typing.Callable`، وهذا تلميح نوع خاطئ فعلياً يكشفه mypy فوراً).
2. **`black` مثبَّت على 24.8.0 في CI بلا آلية تحديث.** بـ black 26.3.1 الحالي يحتاج ملفان إعادة تنسيق (`annotator_view.py:167`, `duplicates_dialog.py:47`) — كلاهما بسبب نمط الدمج الضمني للسلاسل. ليس فشلاً اليوم، لكنه انحراف صامت يتراكم. **الحل:** Dependabot/Renovate على أدوات اللينت، أو `pre-commit` مع `autoupdate`.

---

## 3. المظهر العام والتصميم وتجربة المستخدم UX/UI (وزن 30%) — **6.2/10**

### 3.1 الاتساق البصري — **6/10**

**الجيد:** بنية موحّدة عبر التبويبات الخمسة (شريط أدوات ← محتوى ← شريط تقدّم ← شريط حالة)، هوامش متسقة (`setContentsMargins(8,8,8,8)`)، ولوحة ألوان Flat UI منسجمة (`#3498db`, `#e74c3c`, `#f39c12`, `#2ecc71`).

**المشكلة الجوهرية — لا نظام تصميم:** الألوان مكتوبة يدوياً كـ hex داخل `setStyleSheet` في كل موضع على حدة:
- `dashboard_view.py:163-166` — ألوان بطاقات KPI
- `dashboard_view.py:249-251` — ألوان أزرار المراجعة
- `dashboard_view.py:175, 180, 183` — ثلاث stylesheets منفصلة داخل بطاقة واحدة
- `main_window.py:52` — `color: #888`
- `annotator_view.py:55` — `color:#666`
- `stats_charts.py:35,79` — `plot.setBackground("w")`
- `frame_canvas.py:100,114` — `#202020`, `#e74c3c`

لا يوجد ملف QSS ولا `theme.py` ولا ثوابت ألوان. تغيير لون العلامة التجارية يعني تعديل ثمانية ملفات. **والأخطر:** `config.py:75` يُعرّف `ui_theme = "dark"` ولا أحد يقرؤه — فالتطبيق يعمل بثيم النظام الافتراضي بينما `stats_charts.py` يفرض خلفية **بيضاء** على الرسوم و`frame_canvas.py` يفرض **#202020** على اللوحة. على ويندوز بثيم داكن، الداشبورد يعرض رسوماً بيضاء ساطعة وسط واجهة داكنة، وبطاقات KPI ملوّنة بالكامل. عدم انسجام واضح.

**الحل:** ملف `app/ui/theme.py` بثوابت (`COLOR_PRIMARY`, `COLOR_DANGER`, `SPACING_MD`…) + `app/ui/style.qss` واحد يُطبَّق في `main.py` عبر `app.setStyleSheet()`، مع تفعيل `ui_theme` فعلياً (نسختان من QSS).

### 3.2 سهولة الاستخدام ووضوح التنقل — **7/10**

تبويبات خمسة بأسماء عربية واضحة تتبع تدفّق العمل الطبيعي (المكتبة ← التصنيف ← التدريب ← التحليل ← الداشبورد)، والأزرار مسمّاة بأفعال صريحة، والرموز التعبيرية (🗺️ 📏 ➕ ✏️ 🗑️) تُسرّع المسح البصري.

**المشاكل:**

1. **لا اكتشافية للترتيب الإجباري.** التدفّق فيه تبعيات صارمة (لا استخراج مخالفات بلا استدلال، ولا كاشف سرعة بلا معايرة، ولا كاشف إشارة بلا zone) لكن الواجهة **لا تُظهر أياً منها**. المستخدم يضغط «استخراج المخالفات لكل المقاطع» في تبويب فارغ ويحصل على «اكتمل — 0 مخالفة». لا wizard، لا أزرار معطّلة مع tooltip يشرح السبب، لا شارة «هذا المقطع بلا معايرة».
   **الحل الأرخص:** عمود «الجاهزية» في جدول `analysis_view` يعرض شارات (`🗺️ مناطق: ✗` / `📏 معايرة: ✓`) ورسالة عند 0 مخالفة تشرح أي متطلب ناقص.
2. **زر «تعديل» يعمل على مخالفة تلقائية ويحوّلها بصمت إلى يدوية.** `manual_violation_dialog.py:259` يضع `source = 'manual'` عند أي تعديل — وهذا قرار تصميمي **صحيح** (يمنع حذفها عند إعادة التحليل) لكنه **غير مُبلَّغ للمستخدم**. لا رسالة، والحوار عنوانه «تعديل مخالفة يدوية» حتى وهو يعدّل مخالفة تلقائية. **الحل:** سطر تنبيه في الحوار: «تعديل هذه المخالفة سيحوّلها إلى يدوية ولن تُحذَف عند إعادة التحليل».
3. **زر «الوقت الحالي» بلا وظيفة عملياً** — `manual_violation_dialog.py:102-105` يعيد ضبط الحقل على `current_time_ms` المُمرَّر عند فتح الحوار، و`analysis_view.py:316` **لا يمرّره إطلاقاً** (فيصبح 0). فالزر يعيد القيمة إلى الصفر دائماً. tooltip يقول «(0 ms)» — إشارة على أن السلوك لم يُختبر بصرياً.
4. **تعارض تكرار المسار** — `_iter_video_files` (`library.py:352`) يمشي `rglob("*")` على المجلد بلا حد عمق ولا تجاهل لمجلدات نظام؛ اختيار مجلد كبير خطأً يجمّد الواجهة قبل ظهور أي progress (التعداد يحدث قبل الحلقة).
5. **الاختصارات:** `Ctrl+Q` فقط (`main_window.py:99`). لا `Ctrl+O` للاستيراد، لا `F5` للتحديث، لا `Delete` للحذف، لا `Ctrl+E` للتصدير — مع أن كل هذه الأفعال لها أزرار.

### 3.3 الاستجابة عبر أحجام الشاشات — **5/10**

**الجيد:** استخدام `QSplitter` مع `setStretchFactor` (`library_view.py:67-68`, `dashboard_view.py:72-73`)، و`stretch` في التخطيطات، و`QScrollArea` في مستعرض الأدلة — كلها ممارسات Qt صحيحة تُنتج تكيّفاً معقولاً.

**المشاكل:**

1. **`resize(1280, 800)` بلا `setMinimumSize`** (`main_window.py:73`). على شاشة لابتوب 1366×768، النافذة أطول من الشاشة. وبتصغيرها، جدولا `analysis_view` (كلاهما `stretch=2`) + شريطا الأدوات ينضغطان حتى يختفي المحتوى بلا scroll.
2. **بطاقات KPI في شبكة ثابتة أفقياً** — `dashboard_view.py:168-169`: `addWidget(card, 0, col)` لأربع بطاقات في **صف واحد دائماً**. لا يوجد إعادة تدفّق (reflow) إلى صفين على العرض الضيق؛ البطاقات تنضغط حتى يُقصّ نص «متوسط مخالفات/مقطع».
3. **`resizeColumnsToContents()` في كل تحديث** (`dashboard_view.py:242`, `analysis_view.py:174,198`, `annotator_view.py:152`, `trainer_view.py:286`) — يجعل عرض الأعمدة تابعاً للمحتوى لا للنافذة؛ مع أسماء ملفات طويلة يتجاوز الجدول عرض النافذة ويظهر شريط تمرير أفقي بدل استغلال المساحة. **الحل:** `horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)` للأعمدة النصية و`ResizeToContents` للرقمية فقط.
4. **`setMinimumSize(720,560)` في `ZoneEditorDialog`** و`(760,560)` في `EvidenceDialog` — أكبر من المساحة المتاحة على شاشات صغيرة، والحوارات غير قابلة للتمرير داخلياً.
5. **لا دعم DPI عالٍ صريح** — لا ضبط لـ `AA_EnableHighDpiScaling`/`HighDpiScaleFactorRoundingPolicy` في `main.py`. Qt6 يتعامل معه افتراضياً بشكل أفضل من Qt5، لكن `setIconSize(QSize(240,135))` و`setGridSize(QSize(260,200))` و`setFixedWidth(32)` (`dashboard_view.py:255`) قيم بكسل صلبة تصبح صغيرة جداً على شاشة 4K بتحجيم 150%. **الحل:** اشتقّ المقاسات من `fontMetrics()` أو `logicalDotsPerInch()`.

### 3.4 دعم اللغة العربية و RTL — **8.5/10**

**هذا أقوى محور في التطبيق، ومُنفَّذ باحتراف حقيقي:**
- `Qt.LayoutDirection.RightToLeft` مضبوط على مستوى `QApplication` (`main.py:59`) ثم مؤكَّد على النافذة والتبويبات وشريط القوائم وكل جدول وحوار — لا يُترك للوراثة وحدها.
- **قرار ذكي:** `trainer_view.py:68` يضبط سجل التدريب على **LTR** لأن مخرجات ultralytics إنجليزية/أرقام — خلطها في RTL كان سيُنتج فوضى بصرية. هذا مستوى انتباه نادر.
- **`arabic_utils.py`** تطبيع شامل: تشكيل، تطويل، توحيد أشكال الهمزة/الياء/التاء المربوطة، وتحويل الأرقام الهندية **والفارسية** إلى لاتينية — مهم جداً لقراءة اللوحات السعودية.
- **PDF العربي مُعالَج بجدّية:** `exporter.py:30-70` يبحث عن خط عربي بترتيب (متغير بيئة ← `assets/fonts/` ← خطوط النظام لثلاث منصات)، ثم `shape_for_pdf` يطبّق `arabic_reshaper` + `bidi` (`arabic_utils.py:56-64`)، وكل جداول التقرير `hAlign="RIGHT"` مع `ALIGN...RIGHT`. هذا هو الحل الصحيح لأصعب مشكلة في تصدير العربية.
- CSV يُكتب بـ `utf-8-sig` (`exporter.py:134`) — يفتح في Excel العربي بلا رموز مشوّهة. تفصيلة عملية تدل على خبرة.

**النواقص:**

1. **لا يوجد خط عربي مُرفَق** — `assets/fonts/` غير موجود في المستودع (تحقّقت)، فالتصدير يعتمد على خط النظام. على ويندوز `arial.ttf` موجود، لكن على Linux لو غاب Amiri/Noto فالنص يفشل بصمت بـ Helvetica (`exporter.py:231`) الذي لا يرسم العربية → **PDF فارغ من النص العربي مع مجرد تحذير في السجل**. **الحل:** أرفق `NotoNaskhArabic-Regular.ttf` (SIL OFL) في `assets/fonts/` وأضفه إلى `Baseer.spec` datas — يحل المشكلة نهائياً ويجعل PDF حتمياً عبر المنصات.
2. **لا خط عربي للواجهة** — لا `QFont` مضبوط، فالواجهة ترث خط النظام. على ويندوز بلا خط عربي جيد، الأرقام والنص يظهران بأوزان غير متجانسة.
3. **`ui_language` معرّف وغير مستعمل** (`config.py:76`) — كل النصوص مضمّنة حرفياً بالعربية بلا `tr()` ولا ملفات `.ts`، فالتبديل للإنجليزية يتطلب إعادة كتابة كل ملفات الواجهة. مقبول لمنتج عربي، لكن التوثيق يوحي بغير ذلك.
4. **أسماء العربية في محاور pyqtgraph** (`dashboard_view.py:197-202`) — تُمرَّر أسماء المخالفات العربية كـ ticks. Qt يتعامل مع تشكيل العربية في الرسم، لكن دوران المحور والاتجاه في pyqtgraph غير مضبوطين لـ RTL، والأسماء الطويلة («إساءة استخدام أنوار التلاقي») ستتداخل. لم أتحقق بصرياً — يحتاج فحصاً يدوياً.

### 3.5 إمكانية الوصول (Accessibility) — **4/10**

هذا أضعف محور في التطبيق كله.

1. **أزرار برمز واحد بلا اسم يمكن الوصول إليه:**
   ```python
   # app/ui/dashboard_view.py:248-259
   for label, status, color in (("✓", ReviewStatus.CONFIRMED, "#27ae60"),
                                ("✗", ReviewStatus.FALSE_POSITIVE, "#c0392b"),
                                ("؟", ReviewStatus.UNCERTAIN, "#f39c12")):
       btn = QPushButton(label, container)
       btn.setFixedWidth(32)
   ```
   لا `setAccessibleName()` ولا `setToolTip()` على الثلاثة (زر 🎬 وحده لديه tooltip في السطر 262). قارئ الشاشة سيقرأ «علامة صح» بلا سياق. وثلاثة أزرار بعرض 32px متجاورة في خلية جدول = **هدف لمس/نقر أصغر من الحد الموصى به (44×44)**.
2. **تباين ألوان يفشل معايير WCAG AA:** نص أبيض على `#f39c12` (البرتقالي) نسبة تباين ≈ **2.2:1**، وعلى `#2ecc71` (الأخضر) ≈ **1.9:1** — كلاهما دون الحد الأدنى **4.5:1** للنص العادي و**3:1** للنص الكبير. تُستخدم هذه التركيبات في بطاقات KPI (`dashboard_view.py:163-166` مع `color: white` في السطر 175) وأزرار المراجعة. **الحل:** نص داكن `#1a1a1a` على الخلفيات الفاتحة، أو تغميق الخلفيات إلى `#b8770a`/`#1e8449`.
3. **اللون وحده يحمل المعنى** — حالة المراجعة تُميَّز بالأخضر/الأحمر/البرتقالي فقط. مستخدم بعمى ألوان أحمر-أخضر (8% من الذكور) لا يميّز «مؤكّدة» من «إيجابية كاذبة» في بطاقات KPI. **الحل:** أضف أيقونة/نصاً مع اللون.
4. **لا ترتيب tab مضبوط ولا اختصارات للحقول** — لا `setTabOrder()`، ولا `&` في تسميات النماذج (`form.addRow("Epochs:", ...)`) فلا يوجد وصول بلوحة المفاتيح للحقول. الجداول قابلة للتنقّل بالأسهم افتراضياً، لكن أزرار الأفعال داخل الخلايا (`setCellWidget`) **لا تُدخَل بلوحة المفاتيح إطلاقاً** — أي أن مراجعة المخالفات مستحيلة بلا فأرة.
5. **الصور بلا بدائل نصية** — `thumbnail_grid.py:73` و`evidence_dialog.py:198-200` يضعان `QPixmap` بلا `setAccessibleDescription`.
6. **لا خيار لتكبير الخط** — أحجام الخطوط صلبة (`font-size: 26px`, `12px`, `setPointSize(24)`) ولا تتبع إعداد النظام.

### 3.6 التغذية الراجعة للمستخدم — **7/10**

**الجيد — وبعضه ممتاز فعلاً:**
- **تشخيص FFmpeg نموذجي:** `main.py:98-107` يحذّر عند الإقلاع، و`library_view.py:247-269` يكتشف بعد الفشل أن السبب FFmpeg ويعرض رسالة مع **أمر التثبيت الجاهز** (`winget install --id Gyan.FFmpeg`) وخطوات ما بعده. هذا مستوى «رسائل خطأ قابلة للتنفيذ» الذي تفتقر إليه معظم التطبيقات.
- أشرطة تقدّم حقيقية بنسب (`(3/17) filename.mp4`)، حالة indeterminate أثناء التعداد ثم محدَّدة (`library_view.py:205`, `228-229`)، وتأكيد قبل الحذف في موضعين (`analysis_view.py:368`, `duplicates_dialog.py:111`).
- منع التشغيل المتزامن مع رسالة واضحة في المسارات الثلاثة الطويلة.

**النواقص:**

1. **🔴 عملية مدمّرة بلا تأكيد:**
   ```python
   # app/ui/annotator_view.py:266
   report = DatasetService().prepare(source, output, overwrite=True)
   ```
   و`prepare` تستدعي `write_yolo_layout(..., overwrite=True)` التي تنفّذ `shutil.rmtree(out)` (`dataset.py:151-154`) على `data/dataset/`. المستخدم ينقر «تجهيز Dataset (YOLOv8)» ويختار مجلداً → **يُحذف dataset السابق كاملاً بلا سؤال ولا نسخة احتياطية**. لو كان يعيد التجهيز من مصدر ناقص، فقد dataset ساعات من المراجعة اليدوية. **الحل:** `QMessageBox.question` تعرض المسار وعدد الملفات التي ستُحذف، أو أعِد التسمية إلى `dataset.bak` بدل الحذف.
2. **لا زر إلغاء للعمليات الطويلة.** `_ExtractWorker.cancel()` موجودة (`analysis_view.py:41-42`) و`ImportWorker.cancel()` موجودة (`import_worker.py:39-41`) و**لا شيء يستدعيهما** (تحقّقت: المستدعي الوحيد لـ `.cancel()` في `app/` هو `trainer_view.py:225`). استخراج مخالفات لـ 500 مقطع = لا مخرج سوى قتل العملية.
3. **بتر صامت للنتائج.** `dashboard_view.py:232` يجلب `limit=500` و`analysis_view.py:183` يجلب `LIMIT 500` — بلا أي مؤشر أن هناك المزيد ولا ترقيم صفحات. مستخدم لديه 3000 مخالفة يرى 500 ويظن أن هذا كل شيء. **الحل:** «عرض 500 من 3,142» + ترقيم.
4. **لا حالة فارغة إرشادية.** التبويبات عند أول تشغيل جداول فارغة بلا رسالة توجّه. (`stats_charts.py` يعرض «لا توجد بيانات» في الرسوم — جيد، لكن غير معمّم على الجداول.)
5. **الشريط الحالة يُدهَس.** `library_view.refresh()` (السطر 301) يكتب «إجمالي المقاطع…» فوق نتيجة الاستيراد التي كُتبت للتو في `_on_import_finished` (السطر 234) لأن `refresh()` يُستدعى بعدها مباشرة (السطر 245) — فرسالة «اكتمل: 12 مُستورد، 3 مكرر» تختفي فوراً وقد لا يراها المستخدم.
6. **`QStatusBar` الرئيسي مجمّد على «جاهز»** (`main_window.py:110`) — لا تبويب يستخدمه؛ كل تبويب لديه `QLabel` خاصته. اتساق ضائع.

---

## 4. المراجعة الأمنية (Cybersecurity) (وزن 25%) — **6.3/10**

سياق التقييم: تطبيق سطح مكتب **محلي بالكامل، أحادي المستخدم، بلا خادم ولا شبكة واردة**. هذا يُسقط فئات كاملة (CORS، CSRF، أمان الجلسات، رؤوس HTTP). التقييم يركّز على ما ينطبق فعلاً: الأسرار، الحقن، التحقق من المدخلات، البيانات الحساسة، وسلسلة التوريد.

### 4.1 تخزين المفاتيح السرية وبيانات الاعتماد — **8/10** · خطورة: 🟡 بسيط

**سليم:** لا سرّ واحد مضمَّن في الكود (بحث شامل عن `api_key|secret|token|password\s*=` لم يُرجع أي نتيجة إنتاجية). `.env` مُستبعَد في `.gitignore:46-47`، و`.env.example` يحوي `CVAT_PASSWORD=` **فارغة** (`.env.example:14`) — قالب صحيح.

**الملاحظات:**
1. **`CvatSettings.cvat_password` (`config.py:93`) نص عادي في `.env` بلا استخدام.** بحثت: لا يقرأ أحد هذا الحقل — `AnnotatorService` يستخدم `cvat_url` فقط. أي أن حقل كلمة مرور موثَّقاً في `.env.example` يطلب من المستخدم كتابة كلمة سر لا يستهلكها أي كود. **الحل:** احذفه حتى يوجد تكامل REST فعلي، أو انقله إلى keyring نظام التشغيل (`keyring` package) عند تنفيذ التكامل.
2. **`.env` في `%LOCALAPPDATA%` للنسخة المحزومة** (`config.py:50`) بصلاحيات الملف الافتراضية — مقبول لتطبيق أحادي المستخدم، ويجب توثيقه.
3. **`Baseer.spec:22-23` يحزم `.env.example`** — صحيح أنه القالب لا الملف الحقيقي. جيد. لكن يستحق تعليقاً تحذيرياً يمنع تغييره لاحقاً إلى `.env`.

### 4.2 ثغرات الحقن (SQLi / XSS / Command Injection) — **8.5/10** · خطورة: 🟡 بسيط

**SQL Injection — نظيف عملياً.** كل الاستعلامات ذات المدخلات تستخدم معاملات `?` (تحقّقت من كل موضع). الثلاثة مواضع التي تبني SQL نصياً آمنة:
- `library.py:244` و`dashboard.py:173`: `sql += f" LIMIT {int(limit)}"` — تمرير عبر `int()` يمنع أي حقن.
- `library.py:287`: `f"DELETE FROM {table} WHERE video_id = ?"` — `table` يأتي من الثابت الخاص `_CHILD_TABLES` (`library.py:263-269`) لا من مدخل مستخدم. آمن، لكن يستحق تعليق «الاسم من ثابت داخلي فقط» يمنع تعديلاً مستقبلياً خاطئاً.

**Command Injection — نظيف.** `video_utils.py:57` و`:132` يستخدمان `subprocess.run(cmd_list, ...)` بقوائم وسائط و**بلا `shell=True`** في كل المستودع (تحقّقت). مسارات الملفات تُمرَّر كعناصر منفصلة، فاسم ملف مثل `; rm -rf ~` يُعامَل كنص.

**XSS — منخفض لكنه موجود.** لا متصفح، لكن Qt يرندر HTML في عدة widgets، وبيانات غير موثوقة تُحقن فيه بلا هروب:
```python
# app/ui/library_view.py:328
lines = [f"<b>{label}:</b> {value if value is not None else '—'}" for label, value in cols]
```
`value` يشمل `filename` و`notes` القادمين من نظام الملفات/المستخدم. اسم ملف مثل `<img src=x>` أو `</b><a href="file:///...">` يُرندر كـ HTML. الأثر محدود جداً في `QLabel` (لا JS)، لكن `<a href>` قابل للنقر ويمكن أن يفتح مسارات محلية. نفس النمط في `evidence_dialog.py:149-153` (يحقن `filename` و`notes` و`license_plate`) وفي `library_view.py:262` (يحقن `first_error`).
**الحل:** `html.escape()` على كل قيمة قبل التنسيق، أو `setTextFormat(Qt.TextFormat.PlainText)` حيث لا يُحتاج التنسيق.
**الخطورة:** 🟡 بسيط (تطبيق محلي، بلا تنفيذ سكربتات في QLabel).

### 4.3 التحقق من المدخلات والتنقية — **6/10** · خطورة: 🟠 متوسط

**الجيد:** `ZoneService.add_zone` (`zones.py:62-68`) يتحقق من نوع المنطقة ضد قائمة بيضاء ومن حد أدنى للنقاط. `compute_meters_per_px` (`calibration.py:32-37`) يتحقق من الأطوال والقيم الموجبة. `ManualViolationDialog._validate` (`manual_violation_dialog.py:182-189`) يتحقق من ترتيب الأوقات. الامتدادات مُقيَّدة بقائمة بيضاء (`SUPPORTED_VIDEO_EXTENSIONS`).

**الثغرات:**

1. **JSON من قاعدة البيانات يُفكّ بلا تحقق ولا حماية:**
   ```python
   # app/core/rules.py:545-547
   polygon_data = json.loads(r[1]) if r[1] else []
   polygon = [(float(p[0]), float(p[1])) for p in polygon_data]
   ```
   ومثله `zones.py:95`، `calibration.py:111`، `analyzer.py`. لو تلف الصف أو عُدِّل بأداة خارجية، يرتفع `JSONDecodeError`/`IndexError`/`TypeError` **غير مُلتقَط** ← يُبتلع في `run_detectors` كفشل كاشف صامت، أو ينهار المسار في `zones.py`. الوحيد الذي عالج هذا صحيحاً هو `evidence_dialog.evidence_frame_numbers` (`evidence_dialog.py:36-46`) — نمط دفاعي جيد يجب تعميمه.
   **الحل:** دالة `parse_polygon_json(raw) -> list[Point]` واحدة مع try/except وتحقق من الشكل، تستخدمها المواضع الأربعة.
2. **لا تحقق من حجم/سلامة الفيديو قبل المعالجة** — `library._import_single` يستدعي `extract_metadata` مباشرة. ملف تالف أو مصنوع خبيثاً يُمرَّر إلى ffprobe ثم إلى OpenCV/ultralytics. **هذا سطح الهجوم الحقيقي الوحيد في التطبيق:** المستخدم يستورد مقاطع من «سوشل ميديا» (نوع مصدر مدعوم رسمياً — `SourceType.SOCIAL`)، وثغرات فك التشفير في FFmpeg/OpenCV تاريخياً قابلة للاستغلال بملف مُصاغ. **التخفيف:** ثبّت إصدارات `opencv-python`، فعّل تحديثاً دورياً، وفكّر في تشغيل ffprobe بمهلة (`timeout=30`) — حالياً `subprocess.run` بلا `timeout` فملف مُصاغ قد يُعلّق العملية للأبد.
3. **`webbrowser.open(self._annotator.cvat_url)`** (`annotator_view.py:251`) — الرابط من `.env` بلا تحقق من المخطط. `CVAT_URL=file:///etc/passwd` أو مخطط مسجَّل خبيث يُفتح مباشرة. الخطورة منخفضة (المستخدم يملك ملف `.env`) لكن التحقق سطر واحد: `if not url.startswith(("http://","https://")): return`.
4. **`--video-id` في السكربتات بلا تحقق من الوجود** — `scripts/define_zones.py` و`calibrate.py` يُدرجان لـ `video_id` غير موجود؛ DuckDB يفرض FK فيفشل برسالة تقنية بدل «لا يوجد مقطع بهذا المعرّف».

### 4.4 إدارة الصلاحيات والمصادقة — **5/10** · خطورة: 🟠 متوسط (سياقياً)

**لا يوجد أي نظام مصادقة أو صلاحيات** — وهو **قرار مقبول ومناسب** لتطبيق سطح مكتب أحادي المستخدم يعمل بصلاحيات حساب النظام. الحماية الفعلية هي حماية ملفات نظام التشغيل.

**لكن هناك مشكلة سياقية حقيقية:** المشروع مصمَّم لإنتاج **دراسة مخالفات مرورية** — أي مُخرَج يُحتمل أن يُستشهَد به. ومع ذلك:

1. **`manual_user` غير موثوق ولا يمكن التحقق منه:**
   ```python
   # app/ui/dialogs/manual_violation_dialog.py:212
   user = getpass.getuser()
   ```
   يُخزَّن اسم مستخدم نظام التشغيل كـ «المراجع البشري» للمخالفة اليدوية. أي شخص يمكنه ضبط `USER`/`USERNAME` في البيئة، أو تعديل ملف DuckDB مباشرة (فهو غير محمي وغير موقَّع)، أو ببساطة استخدام حساب شخص آخر. **سلسلة العهدة (chain of custody) غير موجودة.**
2. **لا سجل تدقيق (audit trail).** تغيير حالة المراجعة (`dashboard.py:203-210`) يكتب `review_status` و`reviewed_at` فوق القيمة السابقة — لا سجل بمن غيّر ماذا ومتى ومن أي قيمة إلى أي قيمة. حذف مخالفة (`analysis_view.py:375`) لا يترك أثراً إطلاقاً.
   **الحل المتناسب مع المشروع:** جدول `audit_log(id, entity, entity_id, action, old_value, new_value, actor, at)` يُكتب إليه من الخدمات — تكلفة نصف يوم، وتحوّل المخرَج من «بيانات» إلى «دليل قابل للدفاع عنه». وثّق صراحةً في README أن `manual_user` معرّف نظام تشغيل لا هوية مُصادَق عليها.
3. **`Baseer.spec` + `installer/baseer.iss:38` يستخدم `PrivilegesRequired=lowest`** — قرار أمني **صحيح**؛ التطبيق لا يحتاج صلاحيات مدير ولا يطلبها. يستحق ذكره كنقطة قوة.

### 4.5 التعامل الآمن مع البيانات الحساسة — **4/10** · خطورة: 🟠 متوسط

هذا أضعف محور أمني، والسبب أن **طبيعة البيانات لم تُعامَل كبيانات شخصية**:

قاعدة `data/results.duckdb` تجمع، لكل مخالفة: **رقم لوحة سيارة** (`violations.license_plate` — معرّف شخصي مباشر يربط بمالك مركبة)، + **طابع زمني** (`videos.recorded_at`)، + **إحداثيات موقع** (`videos.location_lat/lon` — عمودان موجودان في المخطط `db.py:46-47`)، + **إطارات إثبات** تحوي وجوهاً ولوحات، + **اسم مستخدم نظام التشغيل**. هذا **تنميط سلوكي كامل لأشخاص محدَّدين** بموجب أي إطار حماية بيانات معاصر (بما فيه نظام حماية البيانات الشخصية السعودي PDPL، الذي يصنّف بيانات الموقع والمعرّفات المركبية كبيانات شخصية).

**الحالة الفعلية:**
1. **لا تشفير عند التخزين (at rest).** ملف DuckDB نص/ثنائي عادي في `%LOCALAPPDATA%\Baseer`. أي عملية تعمل بحساب المستخدم تقرؤه. DuckDB يدعم التشفير (AES) — غير مستخدم.
2. **لا تشفير في التصدير.** JSON/CSV/Excel/PDF تُكتب عادية (`exporter.py`) وتُحفظ حيث يختار المستخدم؛ الافتراضي `data/exports/`. ملف CSV يحوي كل اللوحات بلا أي حماية.
3. **لا تخفٍّ ولا إخفاء هوية (redaction/anonymization).** لا خيار لتصدير «مجهّل» (تجزئة اللوحة/حجب الوجوه) رغم أن الاستخدام المُعلَن هو **دراسة إحصائية** لا ملاحقة أفراد — والدراسة الإحصائية لا تحتاج اللوحات أصلاً. هذا أهم إجراء وقائي مفقود: **زر «تصدير مجهّل»** يستبدل `license_plate` بـ `sha256(plate + salt)[:8]` ويحذف الإحداثيات.
4. **لا سياسة احتفاظ ولا حذف.** لا آلية لحذف بيانات أقدم من N شهراً. `delete_video` يحذف صفوف DB والـ thumbnail (`library.py:290-294`) لكن **لا يحذف ملف الفيديو الأصلي** — فتبقى المقاطع (والوجوه واللوحات فيها) على القرص بعد أن يظن المستخدم أنه حذفها. سلوك مفاجئ يستحق توضيحاً في الواجهة على الأقل.
5. **السجلات قد تسرّب مسارات وأسماء** — `logging` يكتب مسارات ملفات كاملة إلى `logs/baseer.log` بلا تدوير أمني (يوجد `RotatingFileHandler` بحجم — جيد) وبلا تنقية. منخفض، لكنه جزء من نفس الإهمال.

**التوصية بترتيب الأثر:** (1) زر تصدير مجهّل، (2) قسم «الخصوصية والبيانات» في README يوضّح ما يُخزَّن وأين وكيف يُحذف، (3) تشفير DuckDB اختياري بعبارة مرور، (4) سياسة احتفاظ + حذف كامل يشمل ملف الفيديو.

### 4.6 التبعيات القديمة/المُعرَّضة — **4/10** · خطورة: 🔴 حرج (كسر وظيفي مؤكَّد) + 🟠 متوسط (سلسلة توريد)

**(أ) 🔴 كسر مؤكَّد: PaddleOCR 3.x يكسر كود OCR بالكامل.**
`requirements.txt:13` يقول `paddleocr>=2.8.0` بلا حد أعلى. فحصت PyPI: **أحدث إصدار 3.7.0**. أي أن `pip install -r requirements.txt` **اليوم** يثبّت 3.x. والكود يستدعي:
```python
# app/core/ocr.py:200-202
self._paddle_engine = PaddleOCR(
    use_angle_cls=True, lang=self._lang, use_gpu=self._use_gpu, show_log=False
)
# app/core/ocr.py:182
result = engine.ocr(arg, cls=True)
```
هذه المعاملات الأربعة (`use_angle_cls`, `use_gpu`, `show_log`, و`cls=` في `.ocr()`) **أُزيلت في PaddleOCR 3.x**، وبنية الناتج المفكوكة في `ocr.py:186-190` تغيّرت أيضاً. النتيجة: `TypeError` عند أول محاولة قراءة لوحة — وقراءة اللوحات في المسار التلقائي (`analyzer._read_plates`) **تُبتلع بصمت** لأن `_safe_read` (`ocr.py:139-144`) يلتقط `Exception` ويُسجّل تحذيراً. فالمستخدم يحصل على عمود لوحات فارغ دائماً بلا أي خطأ ظاهر. لاحظ أن الاختبارات **لا تكشف هذا** لأنها كلها تحقن `recognize_fn` وتتخطى المسار الحقيقي (`ocr.py:176-203` هي بالضبط الأسطر غير المغطاة في تقرير التغطية).
**الحل الفوري:** `paddleocr>=2.8,<3` في `requirements.txt`، **أو** حدّث `_default_recognize`/`_get_paddle_engine` لواجهة 3.x. وأضف اختبار عقد (contract test) يُشغَّل اختيارياً مقابل المكتبة الحقيقية.

**(ب) 🟠 لا حدود عليا ولا ملف قفل إطلاقاً.** كل الـ 26 تبعية في `requirements.txt` بصيغة `>=` فقط. لا `requirements.lock`، لا `pip-tools`، لا `poetry.lock`، لا `uv.lock`. النتيجة: **بناءان في يومين مختلفين ينتجان تطبيقين مختلفين**، ولا يمكن إعادة إنتاج إصدار مُوزَّع، ولا يمكن معرفة ما الذي شُحن للمستخدم في `Baseer-Setup-0.1.0.exe`. هذا في حد ذاته مشكلة أمنية (سلسلة توريد) قبل أن يكون مشكلة هندسية. المشكلة نفسها تنطبق على `ultralytics>=8.3.0` (أحدث الآن **8.4.109** — قفزة نسخة ثانوية كاملة مع تغييرات API محتملة).
**الحل:** `pip-compile` (أو `uv pip compile`) لإنتاج `requirements.lock` بـ hashes، والبناء منه حصراً.

**(ج) 🟠 لا فحص ثغرات في CI.** `ci.yml` يشغّل ruff + black + pytest فقط. لا `pip-audit`، لا Dependabot (`.github/` يحوي `workflows/` فقط)، لا `bandit`، لا SBOM. مشروع يعتمد على torch + opencv + paddle — وهي مكتبات بتاريخ ثغرات فك تشفير/تسلسل نشط — بلا أي مراقبة.
**الحل (نصف ساعة):** أضف خطوة `pip-audit -r requirements.txt` و`.github/dependabot.yml` أسبوعياً.

**(د) 🟡 حمولة `torch.load` غير موثوقة نظرياً.** `YOLO(str(config.model_path))` (`analyzer.py:350`, `trainer.py:222`) يحمّل ملف `.pt` يختاره المستخدم عبر `QFileDialog`. ملفات pickle تنفّذ كوداً عند التحميل. المسار الافتراضي (`scripts/download_models.py`) يُنزّل من GitHub الرسمي عبر HTTPS — سليم، لكن السكربت **يحسب SHA256 ويطبعه ولا يقارنه بأي قيمة معروفة** (`download_models.py:25,43`). أي أن التحقق موجود شكلاً بلا فائدة. **الحل:** ضع القيم المتوقعة في القاموس `MODELS` وافشل عند عدم التطابق — تعديل عشرة أسطر.

### 4.7 إعدادات CORS / رؤوس الأمان — **غير منطبق (لا يُحتسب)**

لا خادم HTTP، ولا واجهة برمجة مكشوفة، ولا socket مستمع في التطبيق. `webbrowser.open` نحو CVAT محلي هو الاتصال الشبكي الوحيد من الواجهة (بالإضافة إلى تنزيل النماذج في سكربت منفصل). لا شيء يُقاس هنا؛ استُبعد من متوسط درجة الأمن بدل احتسابه 0 أو 10 زوراً.

### 4.8 مسألة ترخيصية بأثر قانوني — 🟠 مهم

خارج نطاق «الأمن» الضيق لكنها مخاطرة حقيقية تستحق الذكر: **Ultralytics YOLOv8 مرخَّص AGPL-3.0**. المشروع (أ) يعتمد عليه كتبعية أساسية، و(ب) **يحزمه في مُثبِّت ويندوز للتوزيع** (`Baseer.spec` + `installer/baseer.iss`). AGPL-3.0 عدوى (copyleft قوي): توزيع عمل مشتق يوجب إتاحة كامل الشيفرة تحت AGPL-3.0، أو شراء ترخيص Ultralytics التجاري. و`pyproject.toml:11` يقول `license = { text = "TBD" }` و README:335 «سيُحدَّد لاحقاً» — أي أن المشروع **يُوزَّع اليوم بلا ترخيص محدَّد وبتبعية copyleft قوية**.
**الحل:** إما اعتماد AGPL-3.0 للمشروع كله (متسق مع نية «مرجع عربي مفتوح» في README)، أو استبدال Ultralytics بنموذج بترخيص متساهل، أو ترخيص تجاري. القرار مطلوب **قبل** أي توزيع للـ `.exe`.

---

## 5. الدرجة الإجمالية المرجّحة

**تفصيل الدرجات الفرعية:**

| المحور | البند | الدرجة |
|---|---|---|
| **هندسي** | البنية وفصل المسؤوليات | 9 |
| | القراءة والصيانة | 8 |
| | DRY و Code Smells | 7 |
| | معالجة الأخطاء والحالات الحدّية | 6 |
| | الأداء والموارد | 5 |
| | الاختبارات | 7 |
| | التوثيق | 7 |
| | التسمية ونمط الكود | 8 |
| | **المتوسط** | **7.3** |
| **UX/UI** | الاتساق البصري | 6 |
| | سهولة الاستخدام والتنقل | 7 |
| | الاستجابة | 5 |
| | العربية و RTL | 8.5 |
| | إمكانية الوصول | 4 |
| | التغذية الراجعة | 7 |
| | **المتوسط** | **6.2** |
| **أمن** | الأسرار وبيانات الاعتماد | 8 |
| | ثغرات الحقن | 8.5 |
| | التحقق من المدخلات | 6 |
| | الصلاحيات والمصادقة | 5 |
| | البيانات الحساسة | 4 |
| | التبعيات | 4 |
| | CORS/Headers | غير منطبق |
| | **المتوسط** | **6.3** |

**الحساب:** (7.3 × 0.45) + (6.2 × 0.30) + (6.3 × 0.25) = 3.29 + 1.86 + 1.58

| الناحية | الدرجة | الوزن | المساهمة |
|---|---|---|---|
| تقنية وهندسية | 7.3/10 | 45% | 3.29 |
| UX/UI | 6.2/10 | 30% | 1.86 |
| أمن سيبراني | 6.3/10 | 25% | 1.58 |
| **الإجمالي** | | | **6.7/10** |

**قراءة الدرجة:** 6.7 هي درجة **مشروع v0.1.0 جيد جداً بنيوياً وناقص في الصقل التشغيلي**. الأساس المعماري (9/10) والعربية/RTL (8.5/10) في مستوى منتج ناضج ويستحقان الحفاظ عليهما كما هما. ما يسحب الدرجة للأسفل ليس «كوداً رديئاً» بل **فجوات في ما بعد الكود**: الأداء تحت حمل حقيقي، إمكانية الوصول، وضبط سلسلة التوريد. أغلب هذه الفجوات إصلاحها رخيص نسبياً — الجدول التالي يقدّر أن الوصول إلى ~8/10 يحتاج نحو 12–15 يوم عمل.

---

## 6. خطة الإصلاح المرتبة بالأولوية

| # | الأولوية | الناحية | المشكلة | الحل المقترح | التأثير المتوقع بعد الحل |
|---|---|---|---|---|---|
| 1 | حرج 🔴 | أمن/تبعيات | `paddleocr>=2.8.0` بلا حد أعلى يثبّت 3.x الذي أزال `use_angle_cls`/`use_gpu`/`show_log`/`cls=` (`ocr.py:182,200-202`) → OCR يفشل صامتاً في كل تثبيت جديد | ثبّت `paddleocr>=2.8,<3` فوراً، أو حدّث `_default_recognize`/`_get_paddle_engine` لواجهة 3.x + اختبار عقد اختياري | قراءة اللوحات تعمل فعلاً في التثبيتات الجديدة بدل عمود فارغ دائم |
| 2 | حرج 🔴 | أداء | `HighBeamDetector` يحمّل كل الإطارات المسحوبة في الذاكرة دفعة واحدة (`high_beam.py:100-102`) — ≈11 ج.ب لمقطع 5 دقائق 1080p | ادمج حلقة القراءة مع حلقة المعالجة؛ احتفظ بالنتيجة البوليانية لا بالمصفوفة + خزّن `is_night` لكل إطار مرة واحدة | يزول خطر `MemoryError`/التبديل؛ يصبح استهلاك الذاكرة ثابتاً بدل خطي |
| 3 | حرج 🔴 | هندسي/بيانات | `DELETE` ثم `executemany` بلا معاملة (`analyzer.py:191-219`) — فشل الإدراج يمحو المخالفات التلقائية بلا بديل | أضف `Database.transaction()` contextmanager (BEGIN/COMMIT/ROLLBACK) ولُفّ العملية | لا فقدان بيانات صامت عند فشل جزئي |
| 4 | حرج 🔴 | UX/بيانات | «تجهيز Dataset» ينفّذ `shutil.rmtree` على `data/dataset/` بلا تأكيد (`annotator_view.py:266` → `dataset.py:151-154`) | `QMessageBox.question` تعرض المسار وعدد الملفات، أو إعادة تسمية إلى `dataset.bak` بدل الحذف | لا فقدان لساعات مراجعة يدوية بنقرة واحدة |
| 5 | حرج 🔴 | صحّة/دليل | صور الأدلة تُعنوَن بأرقام إطارات خاطئة عند فشل قراءة أي إطار (`evidence_dialog.py:72-75,185`) | أعِد `list[tuple[int, np.ndarray]]` من `extract_evidence_images` بدل قائمة صور | الأدلة المعروضة تطابق أرقام إطاراتها — أساسي لمُخرَج يُستشهَد به |
| 6 | مهم 🟠 | أمن/خصوصية | لوحات + مواقع + أوقات + وجوه مخزّنة ومُصدَّرة بلا تشفير ولا تجهيل ولا سياسة احتفاظ | زر «تصدير مجهّل» (تجزئة اللوحة + حذف الإحداثيات) + قسم «الخصوصية» في README + خيار تشفير DuckDB | يجعل المُخرَج قابلاً للمشاركة والنشر بأمان قانوني |
| 7 | مهم 🟠 | أمن/توريد | لا ملف قفل ولا حدود عليا ولا `pip-audit` ولا Dependabot | `pip-compile` → `requirements.lock` بـ hashes + خطوة `pip-audit` في CI + `dependabot.yml` + قارن SHA256 في `download_models.py:43` | بناء قابل لإعادة الإنتاج + إنذار مبكر بالثغرات |
| 8 | مهم 🟠 | قانوني | Ultralytics AGPL-3.0 يُحزَم في مُثبِّت مُوزَّع بينما ترخيص المشروع «TBD» (`pyproject.toml:11`) | اعتمد AGPL-3.0 للمشروع (متسق مع نية README)، أو ترخيص Ultralytics تجاري، أو نموذج بديل — **قبل** أي توزيع | إزالة مخاطرة قانونية على التوزيع |
| 9 | مهم 🟠 | صحّة | مدة «بلا خوذة» تُحسب بين إطارات غير متتالية (`rules.py:317-321`) → إيجابيات كاذبة | طبّق منطق runs المتتالية المستخدم في `lane_keeping._find_straddle_runs` | دقة أعلى وتقليل مراجعة بشرية زائدة |
| 10 | مهم 🟠 | UX/أداء | I/O في main thread: 5 تبويبات تستعلم DB في مُنشئاتها + thumbnails تُقرأ في main thread (`main_window.py:84-88`, `thumbnail_grid.py:78-81`) | بناء كسول للتبويبات عند أول ظهور (`currentChanged`) + تحميل thumbnails في `QThreadPool` مع placeholder | إقلاع فوري وواجهة لا تتجمّد مع مكتبة كبيرة |
| 11 | مهم 🟠 | UX | لا زر إلغاء للاستخراج/الاستيراد رغم وجود `cancel()` غير المستدعاة (`analysis_view.py:41`, `import_worker.py:39`) | أضف زر «إيقاف» يستدعي `cancel()` (كما في `trainer_view.py:225`) | المستخدم لا يُحتجَز في عملية طويلة |
| 12 | مهم 🟠 | إتاحة | تباين ألوان دون WCAG AA (أبيض على `#f39c12` ≈ 2.2:1) وأزرار رمزية بلا اسم وصول (`dashboard_view.py:248-259`) | غمّق الخلفيات أو استخدم نصاً داكناً + `setAccessibleName`/`setToolTip` + أيقونة مع اللون | واجهة قابلة للاستخدام لضعاف البصر وعمى الألوان |
| 13 | مهم 🟠 | UX | بحث بلا debounce يعيد بناء الشبكة على كل حرف + فلترة في Python لا SQL (`library_view.py:128,296`) | `QTimer` 250ms + `WHERE filename ILIKE ?` | بحث سلس بدل تجمّد بكل ضغطة مفتاح |
| 14 | مهم 🟠 | هندسي | SQL خام في 4 ملفات واجهة عبر `_db` (15 موضع `noqa: SLF001`) — يناقض `architecture.md` | أضف توابع للخدمات واحذف كل `_db` من `app/ui/` | يصبح الاستعلام قابلاً للاختبار في `core/` وتعود المعمارية لما تدّعيه |
| 15 | مهم 🟠 | اختبارات | لا اختبار قبول E2E؛ `ui/` و`workers/` بتغطية 0%؛ لا بوابة تغطية | اختبار E2E واحد (استيراد mock → استدلال mock → extract → تحقق من DB) + `pytest-qt` في `requirements-ci.txt` + `--cov-fail-under=60` | يمنع نكوص فجوات التكامل ويقيس ما يُدّعى |
| 16 | مهم 🟠 | هندسي | فشل الكواشف صامت (`rules.py:529-533`) ولا رسالة عند 0 مخالفة | أعِد قائمة الإخفاقات من `run_detectors` واعرضها + عمود «الجاهزية» (مناطق/معايرة) في جدول التحليل | المستخدم يفهم لماذا لا مخالفات بدل الظن أن التطبيق معطّل |
| 17 | مهم 🟠 | موثوقية | فشل فتح DB يقتل التطبيق قبل وجود واجهة، وفي بناء `console=False` بلا أي أثر مرئي (`main.py:47-55`) | أنشئ `QApplication` أولاً ولُفّ التهيئة بـ try/except يعرض `QMessageBox.critical` | لا «نقرة بلا استجابة» عند مشكلة إقلاع |
| 18 | تحسين 🟡 | اتساق | لا نظام تصميم: ألوان hex في 8 ملفات، `ui_theme` معرّف وغير مستعمل، رسوم بخلفية بيضاء قسراً | `app/ui/theme.py` + `style.qss` واحد يُطبَّق في `main.py`، وفعّل `ui_theme` بنسختين | مظهر موحّد ينسجم مع ثيم النظام وتغيير الهوية من ملف واحد |
| 19 | تحسين 🟡 | استجابة | `resize(1280,800)` بلا حد أدنى، KPI في صف ثابت، `resizeColumnsToContents` في كل تحديث | `setMinimumSize` + إعادة تدفّق KPI حسب العرض + `QHeaderView.Stretch` للأعمدة النصية | استخدام مريح على لابتوب 1366×768 وشاشات 4K |
| 20 | تحسين 🟡 | صيانة | `SELECT *` مع مؤشرات رقمية (`library_view.py:314-327`) — يكسر بصمت عند إضافة عمود | أعمدة صريحة أو dataclass من `get_video()` | يمنع عرض بيانات خاطئة بعد أي ترحيل |
| 21 | تحسين 🟡 | صيانة | لا نظام migrations؛ `ALTER TABLE` مضافة داخل `SCHEMA_STATEMENTS` (`db.py:102-104`) | جدول `schema_migrations` + قائمة مرقّمة تُطبَّق مرة واحدة | ترحيلات آمنة وقابلة للتتبع مع نمو المخطط |
| 22 | تحسين 🟡 | DRY | `_frame_where_track_crosses` مكرّرة (`rules.py:176`, `:436`)، نمط QThread مكرّر 3 مرات، `start_*_in_thread` ميتة (≈70 سطراً) | دالة عبور موحّدة + `workers/runner.py` + احذف الدوال الميتة | −150 سطراً وسطح صيانة أصغر |
| 23 | تحسين 🟡 | جودة | `mypy strict` معدّ ولا يُشغَّل؛ `black` مثبّت بلا آلية تحديث؛ `progress_cb: callable` تلميح خاطئ (`library.py:67`) | أضف `mypy app` لـ CI (ولو بـ `--ignore-errors` تدريجياً) + Dependabot لأدوات اللينت | الصرامة المُعلَنة تصبح مُفعَّلة فعلاً |
| 24 | تحسين 🟡 | صحّة | التكرار الحسّي يُجمَّع بتساوي phash التام و`phash_distance` ميتة (`library.py:323-327`) | استخدم `phash_distance` بعتبة Hamming (≈6/64) للتجميع | «إدارة التكرار» تعمل فعلاً على المتشابهات لا المتطابقات فقط |
| 25 | تحسين 🟡 | أمن | HTML غير مهروب في `QLabel` (`library_view.py:328`, `evidence_dialog.py:149-153`)، `webbrowser.open` بلا تحقق مخطط، `subprocess.run` بلا `timeout` | `html.escape()` + تحقق `http(s)://` + `timeout=30` لـ ffprobe/ffmpeg | إغلاق أسطح هجوم صغيرة لكن حقيقية |
| 26 | تحسين 🟡 | أداء | `FollowingDistanceDetector` تربيعية على الأزواج (`following_distance.py:58-71`)؛ `get_settings()` بلا cache | فهرسة سلال-x + `@lru_cache` على `get_settings` | استخراج أسرع بوضوح على المشاهد المزدحمة |
| 27 | تحسين 🟡 | تدقيق | لا سجل تدقيق لتغيير حالة المراجعة/الحذف؛ `manual_user` من `getpass` غير موثوق | جدول `audit_log` + توثيق صريح أن `manual_user` معرّف نظام لا هوية مُصادَقة | مُخرَج قابل للدفاع عنه كدليل |
| 28 | تحسين 🟡 | توثيق | ادعاءات غير دقيقة: «212 اختبار» (الفعلي 231)، «لا ملف >500 سطر» (`rules.py`=568)، «لا I/O في main thread» | صحّح الأرقام أو فعّل القواعد في CI + أضف LICENSE و CONTRIBUTING و CHANGELOG | استعادة مصداقية جدول «معايير الجودة» |
| 29 | تحسين 🟡 | UX | بتر صامت عند 500 صف؛ «الوقت الحالي» يعيد 0 دائماً (`analysis_view.py:316` لا يمرّر `current_time_ms`) | «عرض 500 من N» + ترقيم + مرّر الوقت الفعلي للمشغّل | شفافية البيانات ووظيفة زر معطّلة تعمل |
| 30 | تحسين 🟡 | عربية | لا خط عربي مُرفَق — PDF يفشل بصمت إلى Helvetica على أنظمة بلا خط عربي (`exporter.py:231`) | أرفق `NotoNaskhArabic-Regular.ttf` (SIL OFL) في `assets/fonts/` وأضفه لـ `Baseer.spec` datas | PDF عربي حتمي عبر كل المنصات |

---

## 7. خلاصة

**ما يجب الحفاظ عليه كما هو:** الفصل المعماري (`core/` بلا Qt)، حقن التبعيات الممنهج، الـ lazy imports، آلية التعافي من WAL، الحفاظ على المخالفات اليدوية عبر `source`، دعم RTL/العربية، ورسائل الخطأ القابلة للتنفيذ. هذه قرارات صحيحة يصعب الوصول إليها لاحقاً لو فُقدت.

**ما يجب أن يتغير أولاً:** البنود 1–5 (حرج) قابلة للإنجاز في **2–3 أيام** مجتمعة، وكلها تعالج إما كسراً وظيفياً مؤكَّداً أو فقدان بيانات أو خطأ في مُخرَج يُعتمَد عليه كدليل. البند 6–8 (الخصوصية، القفل، الترخيص) هي شروط عملية **قبل** أي توزيع خارجي للمُثبِّت.

**الحكم:** المشروع في وضع «هيكل ممتاز يحتاج صقلاً تشغيلياً». لا يحتاج إعادة كتابة أي جزء منه — كل ما ورد أعلاه إصلاحات موضعية داخل البنية القائمة، وهذا في حد ذاته شهادة على جودة التصميم الأصلي.

</div>
