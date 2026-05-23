<div dir="rtl" align="right">

# 📦 بناء مُثبِّت Baseer لـ Windows

دليل كامل لتحويل المشروع إلى **`Baseer-Setup-0.1.0.exe`** قابل للتوزيع على أي جهاز Windows 10/11 (64-bit) بدون الحاجة لتثبيت Python.

---

## 🔧 المتطلبات (لمرة واحدة)

| الأداة | الوصف | التثبيت |
|--------|------|---------|
| **Python 3.11+** | بيئة التشغيل | [python.org](https://www.python.org/downloads/) |
| **PyInstaller** | تحويل Python → exe | `pip install pyinstaller` |
| **Inno Setup 6** | تجميع المُثبِّت | [jrsoftware.org/isdl.php](https://jrsoftware.org/isdl.php) |
| **FFmpeg** | (للمستخدم النهائي) | `winget install Gyan.FFmpeg` |

تأكّد أن `iscc.exe` (Inno Setup Compiler) في `PATH`، أو اتركه في موقعه الافتراضي `C:\Program Files (x86)\Inno Setup 6\`.

---

## 🚀 البناء السريع (3 أوامر)

```powershell
# 1) فعّل البيئة وثبّت التبعيات
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pyinstaller

# 2) شغّل سكربت البناء الكامل
.\scripts\build_installer.ps1
```

السكربت يُنفّذ تلقائياً:
1. **توليد الأيقونة** (`scripts/build_icon.py` → `assets/icon.ico`)
2. **بناء التطبيق** (`pyinstaller Baseer.spec` → `dist/Baseer/`)
3. **تجميع المُثبِّت** (`iscc installer/baseer.iss` → `dist/installer/Baseer-Setup-0.1.0.exe`)

الناتج النهائي حجمه ≈ 400–700 MB (يعتمد على torch/ultralytics).

### خيارات السكربت

```powershell
.\scripts\build_installer.ps1 -Clean              # حذف build/dist قبل البدء
.\scripts\build_installer.ps1 -SkipIcon           # بدون إعادة توليد الأيقونة
.\scripts\build_installer.ps1 -SkipInstaller      # PyInstaller فقط (للاختبار)
```

---

## 🔍 البناء اليدوي خطوة بخطوة

### المرحلة 1: الأيقونة

```powershell
python scripts/build_icon.py
```

يُولِّد:
- `assets/icon.ico` — متعدد الأحجام (16، 24، 32، 48، 64، 128، 256)
- `assets/icon.png` — 1024×1024 للنشر
- `assets/icon_64.png` — استخدام الواجهة

> 💡 لو أردت تخصيص الألوان أو الشكل، عدّل `scripts/build_icon.py` ثم أعد التشغيل. السكربت يستخدم Pillow فقط (لا حاجة لـ Inkscape/Illustrator).

### المرحلة 2: PyInstaller

```powershell
pyinstaller Baseer.spec --clean --noconfirm
```

ملف `Baseer.spec` مُهيَّأ مسبقاً لـ:
- **onedir** (مجلد كامل بدلاً من ملف واحد) — أسرع في البدء وأسهل في التصحيح
- **windowed** (بدون terminal) — مناسب لتطبيق GUI
- يحزم `assets/icon.ico` و `.env.example` ضمن الـbundle
- يستبعد `tkinter` والاختبارات لتقليل الحجم
- بدون UPX لتفادي تحذيرات antivirus الكاذبة

ناتج البناء: `dist/Baseer/Baseer.exe`

#### اختبار سريع

```powershell
.\dist\Baseer\Baseer.exe
```

يجب أن تظهر النافذة مع أيقونة Baseer في شريط المهام والـ titlebar.

### المرحلة 3: Inno Setup

افتح `installer/baseer.iss` بـ **Inno Setup Compiler** أو شغّل:

```powershell
iscc installer\baseer.iss
```

يُولِّد: `dist/installer/Baseer-Setup-0.1.0.exe`

#### ما يفعله المُثبِّت تلقائياً

- ✅ يثبّت في `%LocalAppData%\Programs\Baseer` (بدون صلاحيات مدير)
- ✅ يُنشئ اختصار في قائمة Start و (اختيارياً) سطح المكتب
- ✅ يدعم **العربية والإنجليزية** في معالج التثبيت
- ✅ (اختياري) يربط ملفات `.mp4`/`.mkv`/`.mov` بـ Baseer
- ✅ يُسجّل Baseer في "إضافة/إزالة برامج" مع الأيقونة الصحيحة
- ✅ uninstaller نظيف يُبقي بيانات المستخدم في `%AppData%\Baseer`

---

## 🎨 تخصيص الأيقونة

التصميم الحالي: **عين بصيرة** فيها بؤبؤ بإشارة مرور (أحمر/أصفر/أخضر) + قوس طريق أصفر متقطّع، على خلفية كحلية متدرّجة.

### تعديل الألوان

عدّل القيم في أعلى `scripts/build_icon.py`:

```python
BG_TOP = (15, 42, 79)        # كحلي عميق
BG_BOTTOM = (28, 75, 138)    # أزرق متوسط
EYE_WHITE = (245, 248, 252)
TL_RED = (231, 76, 60)
TL_YELLOW = (241, 196, 15)
TL_GREEN = (46, 204, 113)
```

ثم أعد التوليد:
```powershell
python scripts/build_icon.py
```

### استخدام أيقونة جاهزة بدلاً من التصميم البرمجي

ضع `icon.ico` (متعدد الأحجام) في `assets/icon.ico` وستلتقطها كل من PyInstaller و Inno Setup مباشرة. أدوات مفيدة:
- [convertio.co/png-ico/](https://convertio.co/png-ico/) — تحويل PNG إلى ICO
- [iconverticons.com](https://iconverticons.com) — توليد multi-resolution
- [icoconvert.com](https://icoconvert.com) — معاينة على Windows shell

### ربط الأيقونة بالنافذة في الكود

موجودة بالفعل في `app/main.py:_load_app_icon()` — تبحث في:
1. `sys._MEIPASS/assets/icon.ico` (داخل PyInstaller bundle)
2. `assets/icon.ico` (عند التشغيل المباشر)
3. النسخة `.png` كاحتياط

---

## ⚠️ مشاكل شائعة وحلولها

### "ModuleNotFoundError" بعد البناء

أضف الموديول المفقود إلى `hiddenimports` في `Baseer.spec`:

```python
hiddenimports = [..., "اسم_الموديول"]
```

### تحذير antivirus عند تشغيل المُثبِّت

طبيعي لتطبيقات PyInstaller غير الموقَّعة. الحلول:
1. **توقيع الكود** (code signing): اشتر شهادة من DigiCert/Sectigo (~$200/سنة) واستخدم `signtool.exe`
2. أو **رفعه على VirusTotal** للتحقق من نظافته وإرسال false positive للمزوّدين

### المُثبِّت ضخم (> 1 GB)

السبب الأكبر: `torch` + `ultralytics` + `paddlepaddle`. الحلول مرتبة بالأولوية:

1. **torch CPU-only** (الأسرع — ينخفض إلى ~700 MB): عدّل `requirements.txt` ليثبت `torch` من `https://download.pytorch.org/whl/cpu`
2. **استبعد paddleocr** إن لم تستخدم OCR (احذف من `requirements.txt`)
3. **Bootstrap installer** (الأمثل — ~150 MB): انظر `docs/slim_installer.md`
4. **upx مضغوط** (يُخفض ≈30٪): فعّله بـ `upx=True` في `Baseer.spec` بعد تثبيت [UPX](https://upx.github.io/)

📖 **التفاصيل الكاملة لكل استراتيجية**: [`docs/slim_installer.md`](./slim_installer.md)

### "Permission denied" عند الكتابة في Program Files

**محلول في v0.1.1**: التطبيق يستخدم `%LocalAppData%\Baseer\` تلقائياً عند اكتشاف PyInstaller bundle.

لو رأيت هذا الخطأ على نسخة قديمة، حدّث `app/config.py` لاستخدام `sys.frozen` للكشف عن الـbundle (PR رقم 19).

### `_duckdb.InternalException: Failure while replaying WAL file`

**محلول في v0.1.2**: التطبيق يكتشف ملف `.wal` فاسد (مخلّفات من crash سابق قبل إصلاح PermissionError) وينقله تلقائياً إلى `*.wal.broken-<timestamp>` ثم يفتح القاعدة من جديد. البيانات الملتزمة سليمة.

لو احتجت تنظيف يدوي:
```powershell
del "$env:LOCALAPPDATA\Baseer\data\results.duckdb.wal"
```

### تحذيرات `Hidden import "*__mypyc" not found` أثناء PyInstaller

**آمنة، يمكن تجاهلها**. هذه إضافات mypyc-compiled لمكتبة `charset-normalizer` (تابعة `requests`). PyInstaller يبحث عنها كاحتياط لكنها اختيارية — المكتبة تعمل بدونها عبر pure Python fallback.

أمثلة للتحذيرات المتوقَّعة:
```
WARNING: Hidden import "ascii__mypyc" not found!
WARNING: Hidden import "utf8__mypyc" not found!
WARNING: Hidden import "validity__mypyc" not found!
```

### الـapp لا يجد ffmpeg

التطبيق يحذّر المستخدم عند البدء (في `app/main.py:_warn_if_ffmpeg_missing`). الحل: ضمّن مجلد ffmpeg في الـbundle عبر `binaries` في الـspec:

```python
binaries = [("C:\\ffmpeg\\bin\\ffmpeg.exe", ".")]
```

---

## 📦 توزيع النسخة

بعد البناء، الملف الوحيد الذي يحتاجه المستخدم النهائي:

```
dist/installer/Baseer-Setup-0.1.0.exe
```

يكفي:
1. تحميل الملف
2. تشغيله (double-click)
3. اتباع المعالج (3 ضغطات)
4. التطبيق جاهز في قائمة Start بأيقونته

---

## 🔄 إصدارات جديدة

عند رفع الإصدار من `0.1.0` إلى `0.2.0` مثلاً:

1. عدّل `__version__` في `app/__init__.py`
2. عدّل `MyAppVersion` في `installer/baseer.iss`
3. أعد التشغيل: `.\scripts\build_installer.ps1 -Clean`
4. أرفع `Baseer-Setup-0.2.0.exe` كـ GitHub Release

الـ `AppId` ثابت → Windows يكتشف الترقية تلقائياً ويستبدل الإصدار القديم.

---

</div>
