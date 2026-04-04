# macOS Build Guide — Canvas Downloader

> **Audience**: The developer compiling Canvas Downloader on a macOS machine
> (native or cloud runner).
>
> **Prerequisite**: This guide assumes you have cloned the repository and are
> running macOS 12 (Monterey) or later with Python 3.11+ installed via
> [python.org](https://www.python.org/downloads/macos/) or Homebrew.

---

## 1. Create and Activate a Virtual Environment

Open **Terminal** in the project root directory:

```bash
# Create a fresh virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Upgrade pip (recommended)
pip install --upgrade pip
```

## 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

This installs all runtime dependencies. Key macOS-specific notes:

| Package | macOS Note |
|---------|------------|
| `pywebview>=5.1` | Automatically pulls in the macOS **Cocoa/WebKit** backend. No extra deps needed. |
| `pywin32` | Skipped automatically on macOS (`sys_platform == 'win32'` marker). |
| `keyring` | Installs but is lazy-loaded at runtime; your unsigned `.app` will use Base64 fallback instead of Keychain. |
| `moviepy` | Bundles FFmpeg via `imageio_ffmpeg`. The binary is auto-downloaded on first import. |

## 3. Install PyInstaller

```bash
pip install pyinstaller>=6.0
```

> [!NOTE]
> PyInstaller is a **build-time** dependency only. It is intentionally excluded
> from `requirements.txt` since end-users running from source do not need it.

## 4. Verify Required Assets

Before building, confirm these files exist in the project root:

```bash
# App icon — must be .icns format for macOS
ls assets/icon.icns

# Entitlements plist — grants AppleScript / Apple Events automation rights
ls entitlements.plist

# The macOS-specific PyInstaller spec
ls Canvas_Downloader_macOS.spec
```

## 5. Build the `.app` Bundle

```bash
# Clean any stale build artifacts (recommended)
rm -rf build/ dist/

# Run PyInstaller with the macOS spec
pyinstaller --clean Canvas_Downloader_macOS.spec
```

### Expected Output

```
dist/
└── Canvas Downloader.app      ← The distributable .app bundle
    └── Contents/
        ├── Info.plist
        ├── MacOS/
        │   └── Canvas_Downloader    ← Native executable
        └── Resources/
            └── icon.icns
```

**Expected bundle size**: ~130–160 MB (comparable to the Windows `.exe`).

### Troubleshooting Build Failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: imageio_ffmpeg` | `imageio_ffmpeg` not installed | `pip install imageio_ffmpeg` |
| `FileNotFoundError: assets/icon.icns` | Missing icon file | Ensure `assets/icon.icns` exists |
| `No module named 'webview'` | `pywebview` not installed | `pip install pywebview` |
| Extremely large bundle (500+ MB) | Anaconda/Conda environment | Use a clean `python3 -m venv` instead |

## 6. Ad-Hoc Code Signing (Required for Apple Silicon)

macOS on Apple Silicon (M1/M2/M3/M4) **refuses to execute** unsigned native
binaries. Since we do not hold a paid Apple Developer Account ($99/yr), we
perform a **free ad-hoc signature** instead.

```bash
codesign --force --deep -s - "dist/Canvas Downloader.app"
```

### What this does

| Flag | Purpose |
|------|---------|
| `--force` | Overwrites any existing signature (safe for rebuilds). |
| `--deep` | Signs the bundle *and* all nested frameworks/dylibs recursively. |
| `-s -` | The dash (`-`) tells `codesign` to use an **ad-hoc identity** — a free, local-only signature that satisfies Apple Silicon's binary execution requirement without a paid Developer ID. |

### Verification

```bash
# Confirm the signature is valid
codesign --verify --verbose=2 "dist/Canvas Downloader.app"

# Expected output should end with:
# valid on disk
# satisfies its Designated Requirement
```

> [!IMPORTANT]
> **Ad-hoc signing does NOT bypass Gatekeeper.** Users who download the `.app`
> from the internet will still see the "unidentified developer" warning.
> See `README_INSTALL.md` for end-user bypass instructions.

## 7. Test the Bundle

```bash
# Launch the app from Terminal to see any crash output
open "dist/Canvas Downloader.app"

# Or run the binary directly for verbose debugging
"dist/Canvas Downloader.app/Contents/MacOS/Canvas_Downloader"
```

Verify:
- [ ] The native WebKit window opens (not a browser tab).
- [ ] The Streamlit UI loads inside the window.
- [ ] Authentication (login/logout) works with the Base64 fallback.
- [ ] File downloads complete to a user-selected folder.
- [ ] Post-processing conversions (Word, Excel, PDF via AppleScript) execute.
- [ ] Video-to-MP3 conversion succeeds (FFmpeg bundled correctly).

## 8. Package for Distribution

```bash
# Create a compressed .zip for distribution
cd dist/
zip -r -y "Canvas_Downloader_macOS.zip" "Canvas Downloader.app"
```

The `-y` flag preserves symbolic links inside the bundle, which is critical for
macOS framework references.

Distribute `Canvas_Downloader_macOS.zip` alongside the `README_INSTALL.md` file.

---

## Quick Reference — Full Build Sequence

```bash
# One-shot: From clean clone to distributable .zip
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller>=6.0
rm -rf build/ dist/
pyinstaller --clean Canvas_Downloader_macOS.spec
codesign --force --deep -s - "dist/Canvas Downloader.app"
cd dist/ && zip -r -y "Canvas_Downloader_macOS.zip" "Canvas Downloader.app"
```
