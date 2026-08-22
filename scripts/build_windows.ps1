# Windows build for Canvas Downloader - a thin wrapper, ON PURPOSE.
#
# This script used to be a SECOND, divergent implementation of the build, and it
# was comprehensively wrong on 2026-08-22:
#
#   * it ran a bare `pyinstaller Canvas_Downloader.spec`, so version_info.py -
#     the PE version resource, which is generated AND checked in - was never
#     regenerated. The build stamped whatever version was last committed.
#   * it called `iscc Canvas_Downloader_Setup.iss` with NO /DAppVersion, so the
#     .iss fell back to a hardcoded "2.0.0". On a 2.0.2 tree it produced
#     Canvas_Downloader_Setup_2.0.0.exe - wrong in the filename, in Add/Remove
#     Programs, and in the upgrade logic keyed on AppId.
#   * it then printed "Installer location: ...Canvas_Downloader_Setup_2.0.2.exe",
#     a file it had not created.
#
# None of that was visible from reading either script alone; it was visible from
# noticing there were two. A build with two implementations is a build where one
# of them is out of date, so this one now delegates and owns no logic at all.
# Add anything new to scripts/build_windows.py.

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    python scripts/build_windows.py @args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
