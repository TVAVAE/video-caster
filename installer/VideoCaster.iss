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

[Files]
Source: "{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PayloadDirectory}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; The logo as its own file for the shortcuts: Windows caches a shortcut's icon by the file it
; comes from, so shortcuts that took it from VideoCaster.exe kept showing an older icon
Source: "..\app\assets\videocaster.ico"; DestDir: "{app}"; DestName: "VideoCaster.ico"; Flags: ignoreversion
; the Virtual Display Driver inside VideoCaster.exe (for 'Use the TV as a second display') is MIT licensed
Source: "..\third_party\VirtualDisplayDriver\LICENSE"; DestDir: "{app}\licenses"; DestName: "VirtualDisplayDriver-LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\Video Caster"; Filename: "{app}\VideoCaster.exe"; IconFilename: "{app}\VideoCaster.ico"
Name: "{autodesktop}\Video Caster"; Filename: "{app}\VideoCaster.exe"; IconFilename: "{app}\VideoCaster.ico"; Tasks: desktopicon

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Video Caster - Private TCP"" program=""{app}\VideoCaster.exe"""; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Video Caster - Private UDP"" program=""{app}\VideoCaster.exe"""; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Video Caster - Private TCP"" dir=in action=allow program=""{app}\VideoCaster.exe"" enable=yes profile=private remoteip=localsubnet protocol=TCP"; Flags: runhidden; Tasks: privatefirewall; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Video Caster - Private UDP"" dir=in action=allow program=""{app}\VideoCaster.exe"" enable=yes profile=private remoteip=localsubnet protocol=UDP"; Flags: runhidden; Tasks: privatefirewall; Check: IsAdminInstallMode
Filename: "{app}\VideoCaster.exe"; Description: "Launch Video Caster"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Video Caster - Private TCP"" program=""{app}\VideoCaster.exe"""; Flags: runhidden; Check: IsAdminInstallMode; RunOnceId: RemovePrivateTCP
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Video Caster - Private UDP"" program=""{app}\VideoCaster.exe"""; Flags: runhidden; Check: IsAdminInstallMode; RunOnceId: RemovePrivateUDP

; User playlists and watch progress live outside {app}; uninstall preserves them.
