# ============================================
# Baseer — سكربت بناء المُثبِّت الكامل (Windows)
# ============================================
# يُشغّل المراحل الثلاث بترتيب:
#   1. توليد الأيقونة (Pillow)
#   2. بناء التطبيق (PyInstaller)
#   3. تجميع المُثبِّت (Inno Setup)
#
# الاستخدام:
#   .\scripts\build_installer.ps1
#   .\scripts\build_installer.ps1 -SkipIcon         # بدون إعادة توليد الأيقونة
#   .\scripts\build_installer.ps1 -SkipInstaller    # PyInstaller فقط بدون Inno
#
# المتطلبات في PATH:
#   • python (مع .venv مفعَّل)
#   • pyinstaller (pip install pyinstaller)
#   • iscc.exe (Inno Setup 6 — https://jrsoftware.org/isdl.php)

param(
    [switch]$SkipIcon,
    [switch]$SkipInstaller,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $root

function Write-Step($msg) {
    Write-Host ""
    Write-Host "════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host "════════════════════════════════════════════" -ForegroundColor Cyan
}

try {
    if ($Clean) {
        Write-Step "تنظيف مجلدات البناء"
        Remove-Item -Recurse -Force "build", "dist" -ErrorAction SilentlyContinue
    }

    # ─────── 1. الأيقونة ───────
    if (-not $SkipIcon) {
        Write-Step "1/3 — توليد الأيقونة"
        python scripts/build_icon.py
        if ($LASTEXITCODE -ne 0) { throw "فشل توليد الأيقونة" }
    } else {
        Write-Host "↪ تخطّي توليد الأيقونة" -ForegroundColor Yellow
    }

    if (-not (Test-Path "assets/icon.ico")) {
        throw "أيقونة assets/icon.ico غير موجودة. شغّل بدون -SkipIcon."
    }

    # ─────── 2. PyInstaller ───────
    Write-Step "2/3 — بناء Baseer.exe بـ PyInstaller"
    $pyinstaller = Get-Command pyinstaller -ErrorAction SilentlyContinue
    if (-not $pyinstaller) {
        throw "pyinstaller غير موجود. نفّذ: pip install pyinstaller"
    }
    pyinstaller Baseer.spec --clean --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "فشل PyInstaller" }

    $exePath = "dist/Baseer/Baseer.exe"
    if (-not (Test-Path $exePath)) {
        throw "لم يُولَّد $exePath"
    }
    $exeSize = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
    Write-Host "✅ بُني Baseer.exe (${exeSize} MB)" -ForegroundColor Green
    $bundleSize = [math]::Round((Get-ChildItem dist/Baseer -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1)
    Write-Host "✅ حجم المجلد كاملاً: ${bundleSize} MB" -ForegroundColor Green

    # ─────── 3. Inno Setup ───────
    if ($SkipInstaller) {
        Write-Host "↪ تخطّي بناء المُثبِّت" -ForegroundColor Yellow
        return
    }

    Write-Step "3/3 — تجميع المُثبِّت بـ Inno Setup"
    $iscc = Get-Command iscc -ErrorAction SilentlyContinue
    if (-not $iscc) {
        # محاولة المسارات الافتراضية
        $candidates = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
        )
        foreach ($c in $candidates) {
            if (Test-Path $c) { $iscc = $c; break }
        }
        if (-not $iscc) {
            throw "ISCC.exe غير موجود. ثبّت Inno Setup 6 من https://jrsoftware.org/isdl.php"
        }
    }

    & $iscc "installer/baseer.iss"
    if ($LASTEXITCODE -ne 0) { throw "فشل Inno Setup" }

    $installer = Get-ChildItem "dist/installer/Baseer-Setup-*.exe" | Select-Object -Last 1
    if ($installer) {
        $instSize = [math]::Round($installer.Length / 1MB, 1)
        Write-Host ""
        Write-Host "🎉 اكتمل البناء بنجاح" -ForegroundColor Green
        Write-Host "   المُثبِّت: $($installer.FullName) (${instSize} MB)" -ForegroundColor Green
    }
}
catch {
    Write-Host ""
    Write-Host "❌ فشل البناء: $_" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
