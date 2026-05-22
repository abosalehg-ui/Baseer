# المعمارية

تطبيق بَصير مبني على أربع طبقات منفصلة:

## 1. طبقة الواجهة (UI Layer)
- `app/ui/main_window.py` — النافذة الرئيسية مع خمسة تبويبات
- `app/ui/widgets/` — مكونات قابلة لإعادة الاستخدام (مشغل فيديو، شبكة thumbnails، رسوم بيانية)
- مكتوبة بـ PyQt6 بدعم RTL كامل
- **لا تحتوي على أي منطق تجاري** — تستدعي Core Services فقط

## 2. طبقة الخدمات الأساسية (Core Services)
- `app/core/db.py` — DuckDB connection + queries
- `app/core/library.py` — استيراد المقاطع وفهرستها (المرحلة 2)
- `app/core/annotator.py` — جسر CVAT (المرحلة 3-4)
- `app/core/trainer.py` — تدريب YOLO (المرحلة 5-6)
- `app/core/analyzer.py` — inference + ByteTrack (المرحلة 7)
- `app/core/rules.py` — محرك المخالفات (المرحلة 7)
- `app/core/exporter.py` — تصدير التقارير (المرحلة 8)
- **لا تستورد من PyQt6** — مستقلة تماماً عن الواجهة

## 3. طبقة العمال (Workers)
- `app/workers/` — كل عملية ثقيلة تجري في `QThread` منفصل
- التواصل مع الـ UI عبر `pyqtSignal`/`pyqtSlot`
- يضمن عدم تجميد الواجهة أثناء الاستيراد/التحليل/التدريب

## 4. طبقة التخزين (Storage)
- `data/results.duckdb` — قاعدة البيانات الرئيسية
- `data/videos/` — المقاطع المستوردة (أو symlinks)
- `data/thumbnails/`, `data/frames/`, `data/annotations/` — أصول مساعدة

## القرارات المفتاحية
- **DuckDB** بدلاً من SQLite/PostgreSQL: تحليلي سريع، لا يحتاج سيرفر، يقرأ Parquet مباشرة.
- **YOLOv8/v11** بدلاً من Detectron2: fine-tuning أسهل، أداء ممتاز على RTX 4070.
- **CVAT محلي** عبر Docker بدلاً من Roboflow السحابية: 100% محلي، تحكم كامل.
- **PaddleOCR** بدلاً من Tesseract: أداء أفضل على العربية ولوحات السيارات.

## قواعد صارمة
- لا ملف يتجاوز 500 سطر
- لا دالة تتجاوز 50 سطر
- لا I/O في main thread
- كل ميزة في `core/` لها unit test
