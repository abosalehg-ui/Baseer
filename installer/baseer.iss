; ============================================
; Baseer (بَصير) — Inno Setup Installer Script
; ============================================
; قبل التشغيل: ابنِ التطبيق أولاً بواسطة:
;     pyinstaller Baseer.spec --clean --noconfirm
; ثم افتح هذا الملف بـ Inno Setup Compiler واضغط Build.

#define MyAppName "Baseer"
#define MyAppNameAr "بَصير"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Abdulkarim Alaboud"
#define MyAppURL "https://github.com/abosalehg-ui/Baseer"
#define MyAppExeName "Baseer.exe"
#define MyAppId "{{A57B3E2C-9F4A-4C1D-B0D2-7E6B2F9C5D80}"
#define SourceDir "..\dist\Baseer"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist\installer
OutputBaseFilename=Baseer-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
CloseApplications=force
RestartApplications=no
MinVersion=10.0
; دعم اللغة العربية في معلومات الـ uninstaller
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} - Traffic Violation Analysis
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1
Name: "associatemp4"; Description: "ربط ملفات الفيديو (.mp4, .mov, .mkv) بـ {#MyAppNameAr}"; GroupDescription: "اقترانات الملفات:"; Flags: unchecked

[Files]
; كل ملفات PyInstaller الناتجة في dist/Baseer
Source: "{#SourceDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "{#MyAppExeName}"; Flags: ignoreversion recursesubdirs createallsubdirs
; ملف ترخيص واختياري README
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Dirs]
; نُنشئ مجلد بيانات قابل للكتابة في %LocalAppData% للمستخدم الحالي
; التطبيق يستخدمه تلقائياً (عبر app/config.py عند اكتشاف الـ frozen bundle)
Name: "{localappdata}\Baseer"; Permissions: users-modify
Name: "{localappdata}\Baseer\data"; Permissions: users-modify
Name: "{localappdata}\Baseer\models"; Permissions: users-modify
Name: "{localappdata}\Baseer\logs"; Permissions: users-modify

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"; Tasks: quicklaunchicon

[Registry]
; اقتران ملفات الفيديو (اختياري — مهمة منفصلة)
Root: HKA; Subkey: "Software\Classes\.mp4\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppName}.Video"; ValueData: ""; Flags: uninsdeletevalue; Tasks: associatemp4
Root: HKA; Subkey: "Software\Classes\.mkv\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppName}.Video"; ValueData: ""; Flags: uninsdeletevalue; Tasks: associatemp4
Root: HKA; Subkey: "Software\Classes\.mov\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppName}.Video"; ValueData: ""; Flags: uninsdeletevalue; Tasks: associatemp4
Root: HKA; Subkey: "Software\Classes\{#MyAppName}.Video"; ValueType: string; ValueName: ""; ValueData: "{#MyAppName} Video"; Flags: uninsdeletekey; Tasks: associatemp4
Root: HKA; Subkey: "Software\Classes\{#MyAppName}.Video\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\assets\icon.ico"; Tasks: associatemp4
Root: HKA; Subkey: "Software\Classes\{#MyAppName}.Video\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associatemp4

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; لا نحذف بيانات المستخدم في AppData تلقائياً — نُبقيها للسلامة
Type: filesandordirs; Name: "{app}\logs"

[Code]
function InitializeSetup(): Boolean;
begin
  // فحص أن المنصة 64-بت
  if not IsWin64 then begin
    MsgBox('يتطلب التطبيق نسخة Windows 64-bit.', mbError, MB_OK);
    Result := False;
  end else
    Result := True;
end;
