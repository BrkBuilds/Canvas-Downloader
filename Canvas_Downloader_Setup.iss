; Canvas Downloader - Inno Setup 6 Installer Script
; Preferred build: python build_windows.py
;   (reads version.py, generates version_info.py, runs pyinstaller, then
;    calls: iscc /DAppVersion=X.Y.Z Canvas_Downloader_Setup.iss)
;
; Manual build fallback: iscc Canvas_Downloader_Setup.iss
;   Uses the #define below. Keep in sync with version.py.
;
; Output: installer_output\Canvas_Downloader_Setup_{version}.exe

#define AppName        "Canvas Downloader"
; AppVersion is injected by build_windows.py via /DAppVersion=X.Y.Z.
; The #ifndef guard preserves manual-iscc compatibility with the hardcoded fallback.
#ifndef AppVersion
  #define AppVersion   "2.0.0"
#endif
#define AppPublisher   "Canvas Downloader"
#define AppExeName     "Canvas Downloader.exe"
#define AppURL         "https://canvasdownloader.app"
; Three SEPARATE urls, not one with suffixes appended. AppURL used to be the
; GitHub repo, so "{#AppURL}/issues" and "/releases" happened to resolve; once
; AppURL became the website those became canvasdownloader.app/issues, which
; does not exist. Each destination is now stated in full.
#define AppSupportURL  "https://github.com/BrkBuilds/Canvas-Downloader/issues"
#define AppUpdatesURL  "https://canvasdownloader.app/releases.html"
#define SourceDir      "dist\Canvas Downloader"

[Setup]
; Stable GUID - never change this or Windows will treat updates as new apps
AppId={{A3F2D1E0-8B4C-4F7A-9C2E-5D6B3A1F8E2D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppSupportURL}
AppUpdatesURL={#AppUpdatesURL}
AppComments=Batch-download your Canvas course materials to your computer.

; Install location
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; Don't show "Select Start Menu Folder" page - handled by task below
DisableProgramGroupPage=yes

; Output
OutputDir=installer_output
OutputBaseFilename=Canvas_Downloader_Setup_{#AppVersion}

; Branding
SetupIconFile=assets\icon.ico
WizardStyle=modern
WizardImageFile=assets\WizardImageFile.png
WizardSmallImageFile=assets\WizardSmallImageFile.png

; Compression
Compression=lzma2/ultra64
SolidCompression=yes

; Platform requirements
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Privileges: per-user installation (no UAC dialog)
PrivilegesRequired=lowest

; Behaviour
CloseApplications=yes
RestartIfNeededByRun=no
ShowLanguageDialog=no

; Programs & Features / Settings > Apps entry
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Both checked by default - user can opt out during install
Name: "startmenu";  Description: "Create a &Start Menu shortcut";  GroupDescription: "Shortcuts:"
Name: "desktopicon"; Description: "Create a &desktop shortcut";     GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu (modern: no Uninstall entry - users remove via Settings > Apps)
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startmenu
; Desktop
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Register AUMID so Windows attributes toast notifications to Canvas Downloader.
; Without this, clicking a notification activates an unregistered AUMID and
; Windows foregrounds a random window (e.g. whatever was last active).
; Flags: uninsdeletekey ensures cleanup on uninstall.
Root: HKCU; Subkey: "SOFTWARE\Classes\AppUserModelId\CanvasDownloader.App"; Flags: uninsdeletekey
Root: HKCU; Subkey: "SOFTWARE\Classes\AppUserModelId\CanvasDownloader.App"; ValueType: string; ValueName: "DisplayName"; ValueData: "Canvas Downloader"
Root: HKCU; Subkey: "SOFTWARE\Classes\AppUserModelId\CanvasDownloader.App"; ValueType: string; ValueName: "IconUri"; ValueData: "{app}\assets\icon.ico"

[Run]
; "Launch Canvas Downloader" checkbox on the final page
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove everything Inno Setup placed in {app} on uninstall
Type: filesandordirs; Name: "{app}"

[Code]
procedure InitializeWizard;
var
  IndentOffset, RightMarginOffset: Integer;
begin
  // 1. Shift elements to the right to perfectly left-align with "Which additional tasks..."
  // ScaleX ensures this scales correctly on high-resolution/4K monitors
  IndentOffset := ScaleX(12);

  // 2. Shrink the width to force text to wrap before hitting the icon's vertical line
  RightMarginOffset := ScaleX(32);

  // --- Adjust the Body Text ("Select the additional tasks...") ---
  WizardForm.SelectTasksLabel.Left := WizardForm.SelectTasksLabel.Left + IndentOffset;
  WizardForm.SelectTasksLabel.Width := WizardForm.SelectTasksLabel.Width - IndentOffset - RightMarginOffset;

  // --- Adjust the Task Checklist ("Shortcuts:") ---
  // We apply the exact same offset so it stays perfectly left-aligned with the text above it
  WizardForm.TasksList.Left := WizardForm.TasksList.Left + IndentOffset;
  WizardForm.TasksList.Width := WizardForm.TasksList.Width - IndentOffset - RightMarginOffset;
end;