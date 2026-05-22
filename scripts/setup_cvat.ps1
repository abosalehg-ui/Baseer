# ============================================
# setup_cvat.ps1 — تثبيت CVAT محلي على Windows 11
# ============================================
# المتطلبات: Docker Desktop + WSL2
# الاستخدام:  .\scripts\setup_cvat.ps1
# ============================================

[CmdletBinding()]
param(
    [string]$InstallDir = "$env:USERPROFILE\cvat",
    [string]$AdminUser  = "admin",
    [string]$AdminEmail = "admin@baseer.local",
    [string]$Port       = "8080"
)

$ErrorActionPreference = "Stop"

function Test-Docker {
    Write-Host "→ التحقق من Docker Desktop..." -ForegroundColor Cyan
    try {
        docker version | Out-Null
    }
    catch {
        Write-Host "✗ Docker Desktop غير مثبَّت أو غير مُشغَّل." -ForegroundColor Red
        Write-Host "  ثبّته من: https://www.docker.com/products/docker-desktop"
        exit 1
    }
    Write-Host "✔ Docker متاح" -ForegroundColor Green
}

function Get-Cvat {
    Write-Host "→ استنساخ مستودع CVAT..." -ForegroundColor Cyan
    if (Test-Path $InstallDir) {
        Write-Host "  المجلد موجود مسبقاً: $InstallDir" -ForegroundColor Yellow
        Set-Location $InstallDir
        git pull
    }
    else {
        git clone https://github.com/cvat-ai/cvat.git $InstallDir
        Set-Location $InstallDir
    }
}

function Start-Cvat {
    Write-Host "→ بدء حاويات CVAT (قد يستغرق التنزيل أول مرة 5-15 دقيقة)..." -ForegroundColor Cyan
    $env:CVAT_HOST = "localhost"
    $env:CVAT_PORT = $Port

    docker compose up -d
}

function New-CvatAdmin {
    Write-Host "→ إنشاء حساب admin..." -ForegroundColor Cyan
    Write-Host "  ستحتاج لإدخال كلمة المرور:" -ForegroundColor Yellow
    docker compose exec -it cvat_server bash -ic `
        "python3 ~/manage.py createsuperuser --username $AdminUser --email $AdminEmail"
}

function Show-Status {
    Write-Host ""
    Write-Host "════════════════════════════════════════" -ForegroundColor Green
    Write-Host "✔ CVAT جاهز على: http://localhost:$Port" -ForegroundColor Green
    Write-Host "════════════════════════════════════════" -ForegroundColor Green
    Write-Host ""
    Write-Host "أوامر مفيدة:"
    Write-Host "  docker compose logs -f       # متابعة السجلات"
    Write-Host "  docker compose stop          # إيقاف"
    Write-Host "  docker compose start         # تشغيل بعد الإيقاف"
    Write-Host "  docker compose down          # حذف الحاويات"
    Write-Host ""
    Write-Host "بعد فتح المتصفح:"
    Write-Host "  1. سجّل دخول بحساب admin"
    Write-Host "  2. أنشئ Project باسم 'بَصير'"
    Write-Host "  3. أضف labels من DETECTION_CLASSES (انظر app/constants.py)"
}

# تنفيذ
Test-Docker
Get-Cvat
Start-Cvat
New-CvatAdmin
Show-Status
