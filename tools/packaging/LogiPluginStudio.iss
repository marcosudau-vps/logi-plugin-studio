; Logitech Plugin Studio – Windows Setup (Inno Setup 6, free).
; Built ONLY by tools/packaging/build_release.py, which passes:
;   /DAppVersion=1.0.0-rc2 /DAppVersionNumeric=1.0.0.2 /DPayload=<payload dir>
;   /DOutputDir=<release_candidate> /DOutputBaseFilename=LogiPluginStudio-Setup-<v>
; The payload is byte-identical to the Portable ZIP. The Setup edition only adds
; studio-edition.json and the Windows integration (Start menu, uninstall entry).
;
; Data protection (AP-POLISH-001 / AP-03):
; * Studio program files only in {app}. User data lives in
;   %LOCALAPPDATA%\LogiPluginStudio (projects wherever the user saved them),
;   installed plugins in %LOCALAPPDATA%\Logi\LogiPluginService\Plugins.
;   Neither location is ever written or deleted by this installer/uninstaller.
; * Nothing from Logitech or Microsoft is installed, repaired or changed.

#ifndef AppVersion
  #error AppVersion must be passed by build_release.py
#endif
#ifndef Payload
  #error Payload must be passed by build_release.py
#endif

[Setup]
AppId={{6B0F3B51-2C6E-4E0E-9B7C-7E1D5A0C4F11}
AppName=Logitech Plugin Studio
AppVersion={#AppVersion}
AppVerName=Logitech Plugin Studio {#AppVersion}
AppPublisher=Logitech Plugin Studio (privates Projekt, nicht von Logitech)
VersionInfoVersion={#AppVersionNumeric}
VersionInfoProductVersion={#AppVersionNumeric}
VersionInfoProductTextVersion={#AppVersion}
VersionInfoDescription=Logitech Plugin Studio {#AppVersion} Setup
DefaultDirName={autopf}\LogiPluginStudio
DefaultGroupName=Logitech Plugin Studio
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\LogiPluginStudio.exe
UninstallDisplayName=Logitech Plugin Studio {#AppVersion}
InfoBeforeFile={#Payload}\README.txt
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
UsePreviousAppDir=yes
ShowLanguageDialog=no

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung anlegen"; GroupDescription: "Zusätzliche Verknüpfungen:"; Flags: unchecked

[InstallDelete]
; Update/repair: remove the previous PROGRAM payload first so no stale DLL of an
; older Studio version can be mixed in. Only Studio-owned program directories.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\hostruntime"
Type: filesandordirs; Name: "{app}\component_types"
Type: filesandordirs; Name: "{app}\licenses"

[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "studio-edition.json"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Logitech Plugin Studio"; Filename: "{app}\LogiPluginStudio.exe"; WorkingDir: "{app}"
Name: "{group}\Diagnose (Voraussetzungen prüfen)"; Filename: "{app}\Diagnose.cmd"; WorkingDir: "{app}"
Name: "{group}\Anwenderhandbuch"; Filename: "{app}\ANWENDERHANDBUCH.md"
Name: "{group}\Logitech Plugin Studio deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Logitech Plugin Studio"; Filename: "{app}\LogiPluginStudio.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\LogiPluginStudio.exe"; Description: "Logitech Plugin Studio jetzt starten"; Flags: nowait postinstall skipifsilent

[Code]
var
  PrereqPage: TOutputMsgMemoWizardPage;

function DotnetSdkMajorAtLeast(Minimum: Integer): Boolean;
var
  FindRec: TFindRec;
  Major: Integer;
  Name: String;
begin
  Result := False;
  if FindFirst(ExpandConstant('{commonpf64}\dotnet\sdk\*'), FindRec) then
  try
    repeat
      Name := FindRec.Name;
      if (Name <> '.') and (Name <> '..') and (Pos('.', Name) > 0) then
      begin
        Major := StrToIntDef(Copy(Name, 1, Pos('.', Name) - 1), 0);
        if Major >= Minimum then
          Result := True;
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

function Line(Ok: Boolean; Text, Missing: String): String;
begin
  if Ok then
    Result := '[OK]      ' + Text
  else
    Result := '[FEHLT]   ' + Text + ' – ' + Missing;
end;

procedure InitializeWizard;
var
  Service, Api, Options, Dotnet: Boolean;
begin
  Service := FileExists(ExpandConstant('{commonpf64}\Logi\LogiPluginService\LogiPluginService.exe'));
  Api := FileExists(ExpandConstant('{commonpf64}\Logi\LogiPluginService\PluginApi.dll'));
  Options := FileExists(ExpandConstant('{commonpf64}\LogiOptionsPlus\logioptionsplus_agent.exe'));
  Dotnet := DotnetSdkMajorAtLeast(8);
  PrereqPage := CreateOutputMsgMemoPage(wpSelectDir,
    'Voraussetzungen auf diesem PC',
    'Nur Information – das Setup installiert oder verändert keine Logitech- oder Microsoft-Programme.',
    'Das Studio startet auch, wenn hier etwas fehlt. Betroffene Funktionen (Plugin-Build, Installation ' +
    'in den Logi Plugin Service) zeigen dann eine Diagnose. Fehlende Programme sind kostenlos beim ' +
    'jeweiligen Hersteller erhältlich.',
    Line(True, 'Windows 10 (1809) oder neuer, 64 Bit', '') + #13#10 +
    Line(Options, 'Logi Options+', 'von logitech.com installieren') + #13#10 +
    Line(Service, 'Logi Plugin Service', 'wird mit Logi Options+ installiert') + #13#10 +
    Line(Api, 'PluginApi.dll (lokale Logitech-SDK-Datei, wird nie mitgeliefert)', 'kommt mit dem Logi Plugin Service') + #13#10 +
    Line(Dotnet, '.NET SDK 8 oder neuer (nur zum Bauen von Plugins)', 'https://dotnet.microsoft.com/download') + #13#10 + #13#10 +
    'Benutzerdaten (Projekte, Builds, Pairing-Schlüssel, Einstellungen) und installierte Plugins ' +
    'bleiben bei Update, Reparatur und Deinstallation erhalten.');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    MsgBox('Logitech Plugin Studio wurde entfernt.' + #13#10 + #13#10 +
      'Bewusst NICHT gelöscht wurden:' + #13#10 +
      '  • Ihre Projekte (dort, wo Sie sie gespeichert haben)' + #13#10 +
      '  • %LOCALAPPDATA%\LogiPluginStudio (Builds, Pakete, Pairing-Schlüssel, Einstellungen, Protokolle)' + #13#10 +
      '  • installierte Plugins in %LOCALAPPDATA%\Logi\LogiPluginService\Plugins samt ihrer eigenen Host-Laufzeit' + #13#10 +
      '  • Logi Options+ und dessen Profile/Tastenbelegungen' + #13#10 + #13#10 +
      'Installierte Plugins laufen ohne Studio weiter. Plugins entfernen Sie vor der Studio-Deinstallation ' +
      'im Studio (Tab „Installation“) oder später nach einer erneuten Studio-Installation.',
      mbInformation, MB_OK);
end;
