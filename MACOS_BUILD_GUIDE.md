# macOS Build Guide — Canvas Downloader

> **Audience**: The developer compiling Canvas Downloader on a macOS machine
> (native or cloud runner).
>
> **Prerequisite**: macOS 12 (Monterey) or later, Python 3.11+ installed via
> [python.org](https://www.python.org/downloads/macos/) or Homebrew.

---

## 1. Create and Activate a Virtual Environment

Open **Terminal** in the project root directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

> [!IMPORTANT]
> Use a clean `venv`, **not** a Conda environment. Conda pulls in hundreds of MB
> of extras that cause PyInstaller bundles to balloon to 500+ MB.

---

## 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

Key macOS-specific packages installed by this command:

| Package | macOS role |
|---|---|
| `pywebview>=5.1` | Native desktop window. Canvas Downloader forces the **Qt backend** (`gui='qt'`) for Chromium-based rendering identical to Windows Edge. |
| `PySide6` | Qt framework, required by pywebview's Qt backend. |
| `PySide6-WebEngine` | QtWebEngine (bundled Chromium). Provides rendering parity with Windows. Adds ~100 MB to the bundle. |
| `pync` | Wraps `terminal-notifier` for proper Notification Center alerts attributed to "Canvas Downloader" with click-to-activate support. |
| `keyring` | Stores the Canvas API token in **macOS Keychain** (same secure store used by Safari, 1Password, etc.). |
| `moviepy` | Bundles FFmpeg via `imageio_ffmpeg`. The binary is auto-downloaded on first import. |
| `pywin32` | **Skipped** automatically on macOS (`sys_platform == 'win32'` marker). |
| `win11toast` | **Skipped** automatically on macOS. |

---

## 3. Install PyInstaller

```bash
pip install pyinstaller>=6.0
```

> [!NOTE]
> PyInstaller is a **build-time** dependency only — intentionally excluded from
> `requirements.txt` since end-users running from source don't need it.

---

## 4. Verify Required Assets

Before building, confirm these files exist in the project root:

```bash
ls assets/icon.icns      # App icon — must be .icns format
ls entitlements.plist    # Grants Apple Events automation rights for Office converters
ls Canvas_Downloader_macOS.spec
ls .streamlit/config.toml  # Bundled UI theme — must be present
```

---

## 5. Build the `.app` Bundle

```bash
rm -rf build/ dist/
pyinstaller --clean Canvas_Downloader_macOS.spec
```

### Expected Output

```
dist/
└── Canvas Downloader.app
    └── Contents/
        ├── Info.plist
        ├── MacOS/
        │   └── Canvas_Downloader
        └── Resources/
            └── icon.icns
```

**Expected bundle size: ~230–270 MB**

This is larger than the Windows build (~130–150 MB) because PySide6 + QtWebEngine
bundle a full Chromium runtime. This is intentional — it eliminates all
WebKit/Chromium CSS rendering differences between platforms.

### Troubleshooting Build Failures

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: imageio_ffmpeg` | Not installed | `pip install imageio_ffmpeg` |
| `FileNotFoundError: assets/icon.icns` | Missing icon | Ensure `assets/icon.icns` exists |
| `No module named 'webview'` | pywebview not installed | `pip install pywebview` |
| `No module named 'PySide6'` | PySide6 not installed | `pip install PySide6 PySide6-WebEngine` |
| `No module named 'pync'` | pync not installed | `pip install pync` |
| Bundle is 500+ MB | Conda/Anaconda environment | Switch to a clean `python3 -m venv` |

---

## 6. Ad-Hoc Code Signing (Required for Apple Silicon)

macOS on Apple Silicon (M1/M2/M3/M4) refuses to run unsigned native binaries.
Perform a free ad-hoc signature:

```bash
codesign --force --deep -s - "dist/Canvas Downloader.app"
```

| Flag | Purpose |
|---|---|
| `--force` | Overwrites any existing signature (safe for rebuilds). |
| `--deep` | Signs the bundle *and* all nested frameworks/dylibs recursively. |
| `-s -` | Ad-hoc identity — free, local-only, satisfies Apple Silicon execution without a paid Developer ID. |

### Verification

```bash
codesign --verify --verbose=2 "dist/Canvas Downloader.app"
# Expected output ends with: valid on disk / satisfies its Designated Requirement
```

> [!IMPORTANT]
> **Ad-hoc signing does NOT bypass Gatekeeper.** Users who download the `.app`
> from the internet will still see the "unidentified developer" warning.
> See `README_INSTALL.md` for end-user bypass instructions.

---

## 7. Test the Bundle

```bash
# Launch normally
open "dist/Canvas Downloader.app"

# Or run the binary directly for verbose crash output
"dist/Canvas Downloader.app/Contents/MacOS/Canvas_Downloader"
```

**Verification checklist:**

- [ ] A native Qt/Chromium desktop window opens (not a browser tab, not WebKit/Safari).
- [ ] The Streamlit dark theme loads correctly (dark background, blue primary colour).
- [ ] Login and logout work — token is stored in macOS Keychain, not in any JSON file.
- [ ] Logging out clears the token from Keychain (re-launch should show the login form).
- [ ] File downloads complete to a user-selected folder (folder picker dialog appears correctly).
- [ ] "Open Folder" after download opens *into* the folder in Finder (not the parent).
- [ ] A Notification Center alert appears when a download completes, attributed to **"Canvas Downloader"** (not "Script Editor").
- [ ] Clicking the notification activates/focuses the Canvas Downloader window.
- [ ] Post-processing conversions (Word, Excel, PDF via AppleScript) execute if Microsoft Office is installed.
- [ ] Video-to-MP3 conversion succeeds (FFmpeg bundled correctly via imageio_ffmpeg).

---

## 8. Package for Distribution

```bash
cd dist/
zip -r -y "Canvas_Downloader_macOS.zip" "Canvas Downloader.app"
```

The `-y` flag preserves symbolic links inside the bundle, which is critical for
macOS framework references inside the PySide6/QtWebEngine bundle.

Distribute `Canvas_Downloader_macOS.zip` alongside `README_INSTALL.md`.

---

## Quick Reference — Full Build Sequence

```bash
# One-shot: from clean clone to distributable .zip
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller>=6.0
rm -rf build/ dist/
pyinstaller --clean Canvas_Downloader_macOS.spec
codesign --force --deep -s - "dist/Canvas Downloader.app"
cd dist/ && zip -r -y "Canvas_Downloader_macOS.zip" "Canvas Downloader.app"
```
