# بَصير | Baseer

> نظام تحليل المخالفات المرورية من الفيديوهات — تطبيق سطح مكتب محلي بالكامل

تطبيق احترافي لتحويل مئات المقاطع المرورية (داش كام، CCTV، سوشل ميديا) إلى بيانات منظمة قابلة للتحليل، يعمل بدون أي اعتماد على السحابة.

## الحالة

🚧 قيد التطوير — المرحلة الأولى (الأسبوع 1: الأساس والـ DB)

## المتطلبات

- Windows 11
- Python 3.11.x
- NVIDIA Driver ≥ 550 + CUDA 12.4+
- FFmpeg في `PATH`
- Docker Desktop (للـ CVAT — يُستخدم في المرحلة 3)

## التثبيت

```powershell
# 1. إنشاء venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. تثبيت PyTorch مع CUDA 12.4
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# 3. باقي التبعيات
pip install -r requirements.txt

# 4. نسخ ملف البيئة
copy .env.example .env

# 5. تشغيل التطبيق
python -m app.main
```

## المعمارية

```
app/
├── ui/          # واجهات PyQt6 (5 تبويبات)
├── core/        # المنطق التطبيقي (DB، تحليل، قواعد المخالفات)
├── workers/     # عمليات ثقيلة في QThread
└── utils/       # أدوات مساعدة (فيديو، hashing، هندسة)
```

## التوثيق

- [الخطة الكاملة](./docs/baseer-plan.md)
- [المعمارية](./docs/architecture.md)
- [قواعد المخالفات](./docs/violation_rules.md)

## الترخيص

سيُحدَّد لاحقاً.
