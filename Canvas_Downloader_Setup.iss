; Canvas Downloader - Inno Setup 6 Installer Script
; Build order: pyinstaller Canvas_Downloader.spec → iscc Canvas_Downloader_Setup.iss
; Output: installer_output\Canvas_Downloader_Setup_{version}.exe

#define AppName        "Canvas Downloader"
#define AppVersion     "2.0.0"
#define AppPublisher   "Canvas Downloader"
#define AppExeName     "Canvas Downloader.exe"
#define AppURL         "https://github.com/birkls/canvas-downloader"
#define SourceDir      "dist\Canvas Downloader"

[Setup]
; Stable GUID - never change this or Windows will treat updates as new apps
AppId={{A3F2D1E0-8B4C-4F7A-9C2E-5D6B3A1F8E2D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
AppComments=Batch-download your Canvas LMS course materials to your computer.

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

; Compression (DEV MODE - FAST)
Compression=none
SolidCompression=no

; (Revert to these when building the final release:)
; Compression=lzma2/ultra64
; SolidCompression=yes

; Platform requirements
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Privileges: per-user by default, user can choose machine-wide (triggers UAC)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

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
; Comment out this line during UI testing so it doesn't pack your whole app
; Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu (modern: no Uninstall entry - users remove via Settings > Apps)
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startmenu
; Desktop
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

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