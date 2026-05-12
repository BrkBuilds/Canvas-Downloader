# Windows Build Script for Canvas Downloader
# This script compiles the application using PyInstaller and creates an installer with Inno Setup.

$ErrorActionPreference = "Stop"

Write-Host "--- Starting Windows Build Process ---" -ForegroundColor Cyan

# 1. Clean previous builds
Write-Host "[1/4] Cleaning previous builds..." -ForegroundColor Yellow
if (Test-Path "build") { Remove-Item -Path "build" -Recurse -Force }
if (Test-Path "dist") { Remove-Item -Path "dist" -Recurse -Force }
Write-Host "Cleanup complete."

# 2. Run PyInstaller
Write-Host "[2/4] Running PyInstaller..." -ForegroundColor Yellow
pyinstaller --noconfirm Canvas_Downloader.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "PyInstaller build successful."

# 3. Run Inno Setup Compiler
Write-Host "[3/4] Compiling Installer with Inno Setup..." -ForegroundColor Yellow
$isccPath = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $isccPath)) {
    Write-Host "Error: ISCC.exe not found at $isccPath. Please ensure Inno Setup 6 is installed." -ForegroundColor Red
    exit 1
}

& $isccPath Canvas_Downloader_Setup.iss
if ($LASTEXITCODE -ne 0) {
    Write-Host "Inno Setup compilation failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "Installer compilation successful."

# 4. Success
$version = Get-Content version.py | Select-String "__version__ = `"(.*)`"" | ForEach-Object { $_.Matches.Groups[1].Value }
Write-Host "--- Build Complete! ---" -ForegroundColor Green
Write-Host "Installer location: installer_output\Canvas_Downloader_Setup_$version.exe" -ForegroundColor Green
