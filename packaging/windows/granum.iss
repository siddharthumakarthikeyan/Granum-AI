; Granum for Windows: one Setup.exe that installs the self-contained app for the current user.
; Built by packaging/windows/build-installer.ps1, which passes AppVersion, SourceDir and OutputDir.
;
; Installs into %LOCALAPPDATA%\Programs\Granum without administrator rights. Projects, reviews,
; runs and model weights live under the user's project root (default %USERPROFILE%\granum) and
; are never touched by installing, upgrading or uninstalling.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\build\windows\Granum"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif

[Setup]
AppId={{3F40157B-CFB6-4957-9595-CC915B2DAC3C}
AppName=Granum
AppVersion={#AppVersion}
AppVerName=Granum {#AppVersion}
AppPublisher=Siddharth Umakarthikeyan and Melvin Jacob
AppCopyright=Copyright (c) 2026 Siddharth Umakarthikeyan and Melvin Jacob
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Granum installer
DefaultDirName={localappdata}\Programs\Granum
DefaultGroupName=Granum
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
WizardStyle=modern
SetupIconFile={#SourceDir}\granum.ico
UninstallDisplayIcon={app}\granum.ico
UninstallDisplayName=Granum
LicenseFile={#SourceDir}\LICENSE.txt
OutputDir={#OutputDir}
OutputBaseFilename=Granum-{#AppVersion}-Setup
; ultra64's 1.5 GB dictionary exhausts the 32-bit compiler; ultra (64 MB) in a 64-bit
; helper process compresses nearly as well.
Compression=lzma2/ultra
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
; Setup stops a running Granum itself (see [Code]); the Restart Manager prompt is not needed.
CloseApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; Replace the previous version's files completely, so no stale package survives an upgrade.
Type: filesandordirs; Name: "{app}\python"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Granum"; Filename: "{app}\python\Granum.exe"; Parameters: "-X utf8 -m granum open"; \
  WorkingDir: "{app}"; IconFilename: "{app}\granum.ico"; AppUserModelID: "Granum.Granum"; \
  Comment: "Inspect, review and improve computer-vision datasets"
Name: "{autodesktop}\Granum"; Filename: "{app}\python\Granum.exe"; Parameters: "-X utf8 -m granum open"; \
  WorkingDir: "{app}"; IconFilename: "{app}\granum.ico"; AppUserModelID: "Granum.Granum"; Tasks: desktopicon

[Run]
Filename: "{app}\python\Granum.exe"; Parameters: "-X utf8 -m granum open"; WorkingDir: "{app}"; \
  Description: "Open Granum"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Bytecode caches written after installation.
Type: filesandordirs; Name: "{app}"

[Code]
{ Stop every process running from the install folder: the window, the background service and
  any training it started. Their files cannot be replaced or removed while they run. }
procedure StopGranum();
var
  Folder, Command: String;
  Code: Integer;
begin
  Folder := AddBackslash(ExpandConstant('{app}'));
  StringChangeEx(Folder, '''', '''''', True);
  Command := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' +
    'Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith(''' + Folder + ''', ''OrdinalIgnoreCase'') } | ' +
    'Stop-Process -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 800"';
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Command, '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopGranum();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopGranum();
end;
