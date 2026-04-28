# Build Instructions — Canvas Downloader

This document covers building the standalone executables for both platforms.
For the full macOS build walkthrough see **`MACOS_BUILD_GUIDE.md`**.

---

## Windows Build

### Prerequisites

- Python 3.11+ (from [python.org](https://www.python.org/downloads/) — **not** Anaconda/Conda)
- A clean virtual environment (Conda pulls in hundreds of MB of extras that bloat the bundle)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller>=6.0
```

### Run the Build

```powershell
# Remove stale artifacts (recommended)
Remove-Item -Path "build", "dist" -Recurse -Force -ErrorAction SilentlyContinue

# Build
pyinstaller --clean Canvas_Downloader.spec
```

Output: `dist\Canvas Downloader.exe`  
**Expected size: ~130–150 MB**

---

## macOS Build

See **`MACOS_BUILD_GUIDE.md`** for the complete step-by-step guide including
ad-hoc code signing and distribution packaging.

**Expected size: ~230–270 MB** (larger than Windows due to the bundled PySide6 + QtWebEngine Chromium runtime that provides rendering parity with Windows Edge).

---

## Excludes — Why They Matter

Both specs exclude a set of heavy packages that Streamlit pulls in transitively
but that Canvas Downloader never uses. Removing any of these from the `excludes`
list will roughly double or triple the bundle size.

| Package | Reason excluded | Approx. savings |
|---|---|---|
| `polars` | Heavy data-processing lib auto-imported by Streamlit | ~154 MB |
| `botocore` / `boto3` | AWS SDK pulled in transitively | ~17 MB |
| `pyarrow` | Not used | ~28 MB |
| `pandas` | Not used | ~30 MB |
| `altair` | No charts | ~10 MB |
| `pydeck` | No maps | ~10 MB |
| `scipy`, `numpy` | Not used | ~40 MB |
| `tensorflow`, `torch` | Not used | hundreds of MB |
| `matplotlib`, `seaborn` | Not used | ~15 MB |

### Packages that must NOT be excluded

| Package | Required by |
|---|---|
| `jinja2` | Streamlit templating |
| `tornado` | Streamlit HTTP server |
| `watchdog` | Streamlit hot-reload |
| `toml` | Streamlit config parsing |
| `sqlite3` | Sync manifest DB |
| `plistlib` | macOS `.webloc` shortcut parsing |

---

## Platform-Specific Dependencies

| Package | Windows | macOS | Notes |
|---|---|---|---|
| `pywin32` | ✅ Required | ❌ Excluded | COM automation for Office converters |
| `win11toast` | ✅ Required | ❌ Excluded | Native toast notifications |
| `winsound` | ✅ Required | ❌ Excluded | Completion sound |
| `pync` | ❌ Not needed | ✅ Required | Notification Center via terminal-notifier |
| `PySide6` | ❌ Not needed | ✅ Required | Qt framework for Chromium rendering |
| `PySide6-WebEngine` | ❌ Not needed | ✅ Required | QtWebEngine (Chromium) for pywebview |
| `keyring` | ✅ Required | ✅ Required | Windows Credential Manager / macOS Keychain |
| `moviepy` + FFmpeg | ✅ Required | ✅ Required | Video-to-MP3 conversion |
