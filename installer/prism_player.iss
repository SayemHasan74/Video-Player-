#define MyAppName "Prism Player"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Prism Player"
#define MyAppExeName "PrismPlayer.exe"

[Setup]
AppId={{3D62B65C-3160-4F7E-84DD-1315B79AA0F3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Prism Player
DefaultGroupName=Prism Player
AllowNoIcons=yes
OutputDir=..\installer_output
OutputBaseFilename=PrismPlayerSetup
SetupIconFile=..\prism_player\assets\prism_logo.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
ChangesAssociations=yes
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "..\dist\PrismPlayer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Prism Player"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Prism Player"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\PrismPlayer.Media"; ValueType: string; ValueName: ""; ValueData: "Prism Player media file"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\PrismPlayer.Media\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCU; Subkey: "Software\Classes\PrismPlayer.Media\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

Root: HKCU; Subkey: "Software\Classes\.mp4\OpenWithProgids"; ValueType: string; ValueName: "PrismPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mkv\OpenWithProgids"; ValueType: string; ValueName: "PrismPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.avi\OpenWithProgids"; ValueType: string; ValueName: "PrismPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mov\OpenWithProgids"; ValueType: string; ValueName: "PrismPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.webm\OpenWithProgids"; ValueType: string; ValueName: "PrismPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mp3\OpenWithProgids"; ValueType: string; ValueName: "PrismPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.flac\OpenWithProgids"; ValueType: string; ValueName: "PrismPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.wav\OpenWithProgids"; ValueType: string; ValueName: "PrismPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Prism Player"; Flags: nowait postinstall skipifsilent
