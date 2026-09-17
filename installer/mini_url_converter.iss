[Preprocessor]
#define AppVersionEnv GetEnv("YTD_GUI_VERSION")
#if AppVersionEnv == ""
  #define AppVersion "1.1.0"
#else
  #define AppVersion AppVersionEnv
#endif

#ifndef SmokeBuild
  #define Privileges "admin"
  #define Uninstallable "yes"
  #define DesktopDir "{commondesktop}"
  #define OutputName "MiniURLConverterSetup"
  #define AppGuid "B56A8D1E-70F4-4FB5-9B4C-8F0BBCC4A1D3"
#else
  #define Privileges "lowest"
  #define Uninstallable "no"
  #define DesktopDir "{userdesktop}"
  #define OutputName "MiniURLConverterSetup-smoke"
  ; Use a different AppId for smoke builds so they don't leave a second uninstall entry.
  #define AppGuid "4E67F0D5-0F48-4F89-8A44-8AD8C2E3F1B1"
#endif

[Setup]
AppId={{{#AppGuid}}
AppName=Mini URL Converter
AppVersion={#AppVersion}
AppPublisher=Mini URL Converter
DefaultDirName={autopf}\Mini URL Converter
DefaultGroupName=Mini URL Converter
DisableProgramGroupPage=yes
OutputBaseFilename={#OutputName}
SetupIconFile=..\img\mini_url_converter.ico
UninstallDisplayIcon={app}\mini_url_converter.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired={#Privileges}
PrivilegesRequiredOverridesAllowed=commandline
Uninstallable={#Uninstallable}

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "..\dist\mini_url_converter.exe"; DestDir: "{app}"; Flags: ignoreversion
; Tools are fetched on demand into user-writable app data (see ensure_tools_present/self_test),
; so the installer does not bundle yt-dlp/ffmpeg binaries.

[Icons]
Name: "{#DesktopDir}\Mini URL Converter"; Filename: "{app}\mini_url_converter.exe"; Tasks: desktopicon
Name: "{group}\Mini URL Converter"; Filename: "{app}\mini_url_converter.exe"

[Run]
Filename: "{app}\mini_url_converter.exe"; Description: "Launch Mini URL Converter"; Flags: nowait postinstall skipifsilent
