; Compile through build-installer.ps1 so the payload paths are explicit.
#ifndef AppExe
  #error AppExe is required
#endif
#ifndef PayloadDirectory
  #error PayloadDirectory is required
#endif
#ifndef OutputDirectory
  #error OutputDirectory is required
#endif
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{25E8B59F-4705-49E0-A77F-772F0DE9A781}
AppName=Video Caster
AppVersion={#AppVersion}
AppPublisher=Video Caster
AppPublisherURL=https://github.com/TVAVAE/video-caster
DefaultDirName={autopf}\Video Caster
DefaultGroupName=Video Caster
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
OutputDir={#OutputDirectory}
OutputBaseFilename=VideoCaster-Setup
Compression=lzma2/fast
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\VideoCaster.ico
SetupIconFile=..\app\assets\videocaster.ico
; tells Explorer at the end that icons changed
ChangesAssociations=yes

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked
Name: privatefirewall; Description: "Allow TVs to connect on private local networks (recommended)"; Check: IsAdminInstallMode
; the Virtual Display Driver (MIT, github.com/VirtualDrivers/Virtual-Display-Driver) inside VideoCaster.exe:
; installed now if ticked, else the first time someone picks 'Second display' (Windows asks then)
Name: virtualdisplay; Description: "Install the virtual display for 'Second display' (the TV as an extra screen; Virtual Display Driver, MIT license)"; Flags: unchecked; Check: IsAdminInstallMode

[Files]
Source: "{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PayloadDirectory}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; The logo as its own file for the shortcuts: Windows caches a shortcut's icon by the file it
; comes from, so shortcuts that took it from VideoCaster.exe kept showing an older icon
Source: "..\app\assets\videocaster.ico"; DestDir: "{app}"; DestName: "VideoCaster.ico"; Flags: ignoreversion
; the Virtual Display Driver inside VideoCaster.exe (for 'Use the TV as a second display') is MIT licensed
Source: "..\third_party\VirtualDisplayDriver\LICENSE"; DestDir: "{app}\licenses"; DestName: "VirtualDisplayDriver-LICENSE.txt"; Flags: ignoreversion

[Icons]
; AppUserModelID: the app's own ID (main.py), so Windows names its notifications "Video Caster"
Name: "{group}\Video Caster"; Filename: "{app}\VideoCaster.exe"; IconFilename: "{app}\VideoCaster.ico"; AppUserModelID: "VideoCaster.App"
Name: "{autodesktop}\Video Caster"; Filename: "{app}\VideoCaster.exe"; IconFilename: "{app}\VideoCaster.ico"; AppUserModelID: "VideoCaster.App"; Tasks: desktopicon

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Video Caster - Private TCP"" program=""{app}\VideoCaster.exe"""; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Video Caster - Private UDP"" program=""{app}\VideoCaster.exe"""; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Video Caster - Private TCP"" dir=in action=allow program=""{app}\VideoCaster.exe"" enable=yes profile=private remoteip=localsubnet protocol=TCP"; Flags: runhidden; Tasks: privatefirewall; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Video Caster - Private UDP"" dir=in action=allow program=""{app}\VideoCaster.exe"" enable=yes profile=private remoteip=localsubnet protocol=UDP"; Flags: runhidden; Tasks: privatefirewall; Check: IsAdminInstallMode
Filename: "{app}\VideoCaster.exe"; Parameters: "--install-display-driver ""{tmp}\virtual-display.json"""; StatusMsg: "Installing the virtual display..."; Flags: runhidden waituntilterminated; Tasks: virtualdisplay; Check: IsAdminInstallMode
Filename: "{app}\VideoCaster.exe"; Description: "Launch Video Caster"; Flags: nowait postinstall skipifsilent runasoriginaluser
; an update from inside the app (/SILENT /RESTARTAPP=1): start Video Caster again when it's done -
; through PowerShell, which first drops what this Setup inherited from the old copy (see RestartCommand)
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -Command ""{code:RestartCommand}"""; Flags: nowait runhidden runasoriginaluser; Check: RestartRequested

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Video Caster - Private TCP"" program=""{app}\VideoCaster.exe"""; Flags: runhidden; Check: IsAdminInstallMode; RunOnceId: RemovePrivateTCP
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Video Caster - Private UDP"" program=""{app}\VideoCaster.exe"""; Flags: runhidden; Check: IsAdminInstallMode; RunOnceId: RemovePrivateUDP
; the virtual display goes too - only if Video Caster installed it (now or later from the app); one set up by hand stays
Filename: "{app}\VideoCaster.exe"; Parameters: "--uninstall-display-driver -"; Flags: runhidden waituntilterminated; Check: IsAdminInstallMode; RunOnceId: RemoveVirtualDisplay

; User playlists and watch progress live outside {app}; uninstall preserves them.

[Code]
function SetEnvironmentVariable(lpName, lpValue: String): BOOL;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

{ Started by Video Caster's updater (0.3.6 and earlier), Setup inherits the old copy's notes about
  its temporary _MEI folder (PyInstaller's _PYI_* variables). A Video Caster started from here would
  look for Python in that folder - deleted once the old copy closed: "Failed to load Python DLL".
  PYINSTALLER_RESET_ENVIRONMENT=1 makes it start afresh. }
function InitializeSetup: Boolean;
begin
  SetEnvironmentVariable('PYINSTALLER_RESET_ENVIRONMENT', '1');
  Result := True;
end;

function RestartRequested: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:restartapp|0}') = '1');
end;

{ The restart runs as the original user, from the Setup process the updater started - which still
  has the inherited variables, so the command sets the reset itself. }
function RestartCommand(Param: String): String;
var
  Exe: String;
begin
  Exe := ExpandConstant('{app}\VideoCaster.exe');
  StringChangeEx(Exe, '''', '''''', True);
  Result := '$env:PYINSTALLER_RESET_ENVIRONMENT=''1''; Get-ChildItem Env:_PYI_* | Remove-Item; ' +
            'Start-Process -FilePath ''' + Exe + '''';
end;
