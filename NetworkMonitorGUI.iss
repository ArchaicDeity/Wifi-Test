[Setup]
AppName=Network Monitor
AppVersion=1.0
DefaultDirName={pf}\Network Monitor GUI
DefaultGroupName=Network Monitor GUI
OutputDir=installer
OutputBaseFilename=NetworkMonitor_Installer
Compression=lzma
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Use the built EXE (pyinstaller output). If the build produced
; `NetworkMonitor_build2.exe`, include that as the source but install
; it under the canonical name `NetworkMonitor.exe` so shortcuts/Run work.
Source: "dist\NetworkMonitor_build2.exe"; DestDir: "{app}"; DestName: "NetworkMonitor.exe"; Flags: ignoreversion
; Optional: include Ookla Speedtest CLI if you want bundled speed tests.
; Download the Windows CLI from https://www.speedtest.net/apps/cli and
; place it at `extras\speedtest.exe` before building the installer.
Source: "extras\speedtest.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Network Monitor"; Filename: "{app}\NetworkMonitor.exe"
Name: "{commondesktop}\Network Monitor"; Filename: "{app}\NetworkMonitor.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\NetworkMonitor.exe"; Description: "{cm:LaunchProgram,Network Monitor}"; Flags: nowait postinstall skipifsilent