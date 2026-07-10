#define MyAppName "Comet Player"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Comet Player"
#define MyAppExeName "CometPlayer.exe"

[Setup]
AppId={{8A0F5B33-9AAE-4D72-97F3-AC5D363A57C8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Comet Player
DefaultGroupName=Comet Player
AllowNoIcons=yes
OutputDir=..\installer_output
OutputBaseFilename=CometPlayerSetup
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
Source: "..\dist\CometPlayer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Comet Player"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Comet Player"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\CometPlayer.Media"; ValueType: string; ValueName: ""; ValueData: "Comet Player media file"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\CometPlayer.Media\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCU; Subkey: "Software\Classes\CometPlayer.Media\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

Root: HKCU; Subkey: "Software\Classes\.mp4\OpenWithProgids"; ValueType: string; ValueName: "CometPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mkv\OpenWithProgids"; ValueType: string; ValueName: "CometPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.avi\OpenWithProgids"; ValueType: string; ValueName: "CometPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mov\OpenWithProgids"; ValueType: string; ValueName: "CometPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.webm\OpenWithProgids"; ValueType: string; ValueName: "CometPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mp3\OpenWithProgids"; ValueType: string; ValueName: "CometPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.flac\OpenWithProgids"; ValueType: string; ValueName: "CometPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.wav\OpenWithProgids"; ValueType: string; ValueName: "CometPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Comet Player"; Flags: nowait postinstall skipifsilent
