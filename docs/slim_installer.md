<div dir="rtl" align="right">

# 📉 تقليل حجم مُثبِّت Baseer

الـbundle الافتراضي يصل ≈ **1.6 GB** بسبب torch + ultralytics + paddleocr + cuDNN. هذا الدليل يشرح **3 استراتيجيات** لتقليصه — من الأبسط للأكثر تعقيداً.

---

## 📊 توزيع الحجم (تقريبي)

| المكوّن | الحجم |
|--------|------|
| `torch` (CUDA wheels) | ~1.2 GB |
| `paddlepaddle-gpu` + cuDNN | ~400 MB |
| `ultralytics` + dependencies | ~50 MB |
| `PyQt6` + Qt binaries | ~120 MB |
| `opencv-python` + numpy | ~60 MB |
| Baseer code + assets | ~5 MB |
| **المجموع** | **~1.85 GB** |

> 💡 الأهداف الواقعية: **400-600 MB** للنسخة CPU، **120-200 MB** للنسخة "الخفيفة" (بدون AI، تُحمَّل عند الحاجة).

---

## 🎯 الاستراتيجية 1: نسخة CPU-only (أبسط — ينخفض إلى ~700 MB)

استبدل `torch` بنسخة CPU في `requirements.txt` (لا حاجة لـ CUDA).

### الخطوات

1. عدّل `requirements.txt`:
   ```diff
   - torch>=2.5.0
   - torchvision>=0.20.0
   + torch>=2.5.0 --index-url https://download.pytorch.org/whl/cpu
   + torchvision>=0.20.0 --index-url https://download.pytorch.org/whl/cpu
   ```

2. احذف `paddlepaddle-gpu` (احتفظ بـ `paddleocr` فقط — يستخدم CPU تلقائياً):
   ```diff
   - paddlepaddle-gpu>=2.6.0
   ```

3. أعد البناء:
   ```powershell
   pip install -r requirements.txt --force-reinstall
   .\scripts\build_installer.ps1 -Clean
   ```

**النتيجة**: ~700 MB. مناسبة جداً للمستخدمين بدون GPU.

---

## 🎯 الاستراتيجية 2: استبعاد paddleocr (للحالات التي لا تحتاج لقراءة لوحات)

إن كان مستخدمو التطبيق لا يحتاجون لـ OCR للوحات السيارات:

```diff
# requirements.txt
- paddleocr>=2.8.0
- paddlepaddle-gpu>=2.6.0
```

ضمن الكود، اجعل استيراد PaddleOCR lazy ومحمي بـ `try/except` (موجود بالفعل في `app/core/ocr.py`).

**النتيجة**: ~500 MB.

---

## 🎯 الاستراتيجية 3 (الموصى بها): Bootstrap installer + lazy AI

النموذج: **مُثبِّت خفيف (≈ 150 MB)** يحوي PyQt6 + DuckDB + OpenCV فقط. عند أول تشغيل لميزة AI، يحمّل التطبيق `torch` و `ultralytics` في `%LocalAppData%\Baseer\runtime\` ويستوردها lazy.

### المعمارية

```
Baseer-Setup-0.1.0-lite.exe   (~ 150 MB)
    ↓ تثبيت
C:\Program Files\Baseer\
    ├── Baseer.exe            (PyQt6 GUI + core)
    └── _internal/            (PyQt6 + DuckDB + OpenCV)

عند أول استخدام للتحليل:
    %LocalAppData%\Baseer\runtime\
        ├── torch/            (يُحمَّل من PyPI ~1 GB)
        ├── ultralytics/
        └── installed.lock
```

### خطوات التنفيذ (مخطط معماري)

1. **استثناء التبعيات الثقيلة من `Baseer.spec`**:
   ```python
   excludes = [
       "torch", "torchvision", "ultralytics",
       "paddle", "paddleocr",
   ]
   ```

2. **إضافة `app/core/ai_bootstrap.py`**:
   ```python
   from pathlib import Path
   import subprocess, sys
   
   def ensure_ai_deps(parent_widget=None) -> bool:
       runtime = Path(os.environ["LOCALAPPDATA"]) / "Baseer" / "runtime"
       lock = runtime / "installed.lock"
       if lock.exists():
           sys.path.insert(0, str(runtime))
           return True
       # عرض QProgressDialog وتشغيل pip في QThread
       runtime.mkdir(parents=True, exist_ok=True)
       cmd = [
           sys.executable, "-m", "pip", "install",
           "--target", str(runtime),
           "torch", "torchvision", "ultralytics",
           "--index-url", "https://download.pytorch.org/whl/cpu",
       ]
       result = subprocess.run(cmd, capture_output=True)
       if result.returncode == 0:
           lock.touch()
           sys.path.insert(0, str(runtime))
           return True
       return False
   ```

3. **استدعاء في كل مكان يستخدم AI** (analyzer.py, trainer.py):
   ```python
   def analyze_video(...):
       from app.core.ai_bootstrap import ensure_ai_deps
       if not ensure_ai_deps():
           raise RuntimeError("لم يتم تحميل تبعيات AI")
       from ultralytics import YOLO   # lazy
       ...
   ```

4. **توفير python.exe المضمّن**:
   PyInstaller لا يحوي pip. حلول:
   - **(أ)** إضافة `python.exe` المضمن (Embedded Python) في الـbundle (~10 MB) + استخدامه لتشغيل pip
   - **(ب)** استخدام مكتبة `pip._internal.cli.main` المضمّنة في wheel package

### المزايا والعيوب

| المزية | العيب |
|--------|------|
| ✅ المُثبِّت 10× أصغر (≈ 150 MB) | ❌ المستخدم يحتاج إنترنت في أول تشغيل |
| ✅ التحديثات أسرع | ❌ تعقيد إضافي في الكود |
| ✅ كل مستخدم يحصل على أحدث torch | ❌ يحتاج 5-15 دقيقة عند أول تشغيل |
| ✅ يدعم تثبيت CUDA/CPU حسب جهاز المستخدم | ❌ مشاكل صلاحيات pip محتملة |

---

## ⚠️ مهم: مشكلة Program Files (محلولة في v0.1.1)

التطبيق كان يكتب الـlogs في `C:\Program Files\Baseer\` → `PermissionError`. الحل في `app/config.py`:
- عند اكتشاف `sys.frozen` (PyInstaller bundle)، يستخدم `%LocalAppData%\Baseer\`
- كل من logs/data/db يذهب لمجلد قابل للكتابة بدون صلاحيات مدير

لا حاجة لتدخّل من المستخدم.

---

## 📝 خلاصة التوصية

| الحالة | الاستراتيجية | الحجم المتوقع |
|--------|--------------|---------------|
| إصدار مبدئي / تجريبي | كما هو (GPU كامل) | 1.6 GB |
| توزيع عام للمستخدمين | **CPU-only** | ~700 MB |
| إصدار "الإنتاج" المثالي | **Bootstrap + lazy AI** | ~150 MB |

ابدأ بـ **CPU-only** الآن (سهل وسريع)، وانتقل لـ Bootstrap عند الحاجة.

</div>
