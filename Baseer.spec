# -*- mode: python ; coding: utf-8 -*-
"""ملف PyInstaller spec لتطبيق Baseer (بَصير).

البناء:
    pyinstaller Baseer.spec --clean --noconfirm

الناتج:
    dist/Baseer/  — مجلد كامل يحوي Baseer.exe وكل التبعيات (onedir)
"""

from pathlib import Path

block_cipher = None

# الأصول التي ستُحزَم مع التطبيق
datas = [
    ("assets/icon.ico", "assets"),
    ("assets/icon.png", "assets"),
]

# أي ملف .env.example موجود يُحزم كقالب
if Path(".env.example").exists():
    datas.append((".env.example", "."))

# مكتبات يصعب على PyInstaller اكتشافها تلقائياً
hiddenimports = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "pyqtgraph",
    "duckdb",
    "scenedetect",
    "imagehash",
    "PIL",
    "ffmpeg",
    "pydantic_settings",
]

a = Analysis(
    ["app/main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # استبعاد الموديولات غير المستخدمة لتقليل حجم الـbundle
        "tkinter",
        "matplotlib.tests",
        "numpy.tests",
        "PIL.tests",
        "pytest",
        "pytest_cov",
        "torch.test",
        "torch.testing",
        "torch.distributed",  # غير مستخدم في Baseer
        "torch.onnx",  # غير مستخدم
        "torch.jit",  # غير مستخدم في الاستخدام العادي
        "scipy.io.tests",
        "scipy.signal.tests",
        "scipy.stats.tests",
        # ملاحظة: لو لا تحتاج OCR، أضف هنا: "paddle", "paddleocr"
        # ولو تريد CPU-only، استخدم torch CPU wheel — انظر docs/slim_installer.md
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Baseer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # نافذة GUI فقط — بدون terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,                # UPX قد يتسبب في false positive من antivirus
    upx_exclude=[],
    name="Baseer",
)
