[Preprocessor]
#define AppVersionEnv GetEnv("YTD_GUI_VERSION")
#if AppVersionEnv == ""
  #define AppVersion "1.2.0"
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
AppName=YTD Converter
AppVersion={#AppVersion}
AppPublisher=YTD Converter
DefaultDirName={autopf}\YTD Converter
DefaultGroupName=YTD Converter
DisableProgramGroupPage=yes
OutputBaseFilename={#OutputName}
SetupIconFile=..\img\mini_url_converter.ico
UninstallDisplayIcon={app}\YTDConverter.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired={#Privileges}
PrivilegesRequiredOverridesAllowed=commandline
Uninstallable={#Uninstallable}

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "..\dist\mini_url_converter.exe"; DestDir: "{app}"; DestName: "YTDConverter.exe"; Flags: ignoreversion
; Runtime tools are stored in user-writable app data and maintained by the update center.
; The experimental Chrome bridge stays in source control but is intentionally not shipped in v1.2.0.

[InstallDelete]
; v1.1.x installed the executable under the legacy product name. Keep the same
; AppId for an in-place upgrade, but remove that old executable after it exits.
Type: files; Name: "{app}\mini_url_converter.exe"
Type: files; Name: "{commondesktop}\Mini URL Converter.lnk"
Type: files; Name: "{group}\Mini URL Converter.lnk"

[Icons]
Name: "{#DesktopDir}\YTD Converter"; Filename: "{app}\YTDConverter.exe"; Tasks: desktopicon
Name: "{group}\YTD Converter"; Filename: "{app}\YTDConverter.exe"

[Run]
Filename: "{app}\YTDConverter.exe"; Description: "Launch YTD Converter"; Flags: nowait postinstall skipifsilent
