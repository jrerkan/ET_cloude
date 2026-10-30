; ETAP Kilit Yönetimi - Inno Setup betiği (GitHub Actions tarafından derlenir)
#define AppName "ETAP Kilit Yönetimi"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6F1B2C84-3A5D-4E7B-9C21-8D4E5F6A7B90}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=ETAP Kilit
DefaultDirName={autopf}\ETAP Kilit
DefaultGroupName=ETAP Kilit
OutputDir=Output
OutputBaseFilename=ETAPKilit-Kurulum-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\ETAPKilit.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "Masaüstüne kısayol oluştur"; Flags: unchecked
Name: "startup"; Description: "Windows ile birlikte otomatik başlat (önerilir)"

[Files]
Source: "..\dist\ETAPKilit\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\ETAP Kilit Yönetimi"; Filename: "{app}\ETAPKilit.exe"
Name: "{autodesktop}\ETAP Kilit Yönetimi"; Filename: "{app}\ETAPKilit.exe"; Tasks: desktopicon
Name: "{commonstartup}\ETAP Kilit"; Filename: "{app}\ETAPKilit.exe"; Parameters: "--minimized"; Tasks: startup

[Run]
; Güvenlik duvarı: tahtaların ve öğretmen telefonlarının programa ulaşabilmesi için
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""ETAP Kilit"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""ETAP Kilit"" dir=in action=allow program=""{app}\ETAPKilit.exe"" enable=yes profile=any"; Flags: runhidden
Filename: "{app}\ETAPKilit.exe"; Description: "ETAP Kilit Yönetimi'ni başlat"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""ETAP Kilit"""; Flags: runhidden
