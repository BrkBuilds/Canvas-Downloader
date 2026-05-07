# macOS Build Guide — Canvas Downloader

> **Audience**: The developer compiling Canvas Downloader on a macOS machine
> (native or cloud runner).
>
> **Prerequisite**: macOS 12 (Monterey) or later, Python 3.13 installed via
> [python.org](https://www.python.org/downloads/macos/) or Homebrew.

> [!TIP]
> **Don't have a Mac?** Use GitHub Actions to build in the cloud for free —
> no Mac hardware required. See **`GITHUB_ACTIONS_GUIDE.md`** for a
> step-by-step walkthrough. The workflow at
> `.github/workflows/build-macos.yml` builds a native Apple Silicon
> target automatically.

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
| `customtkinter` | Provides the lightweight, modern macOS Controller UI. |
| `pillow` | Image processing for CustomTkinter icons. |
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

**Expected bundle size: ~70–90 MB**

This is smaller than the Windows build (~130–150 MB) because macOS uses a Bring Your Own Browser (BYOB) architecture. We do not bundle a heavy Chromium runtime; instead, we strictly launch the user's native Google Chrome application.

### Troubleshooting Build Failures

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: imageio_ffmpeg` | Not installed | `pip install imageio_ffmpeg` |
| `FileNotFoundError: assets/icon.icns` | Missing icon | Ensure `assets/icon.icns` exists |
| `No module named 'customtkinter'` | customtkinter not installed | `pip install customtkinter pillow` |
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

- [ ] The lightweight CustomTkinter controller window opens.
- [ ] The app natively launches a new tab in Google Chrome.
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

Create a `.dmg` image (the standard macOS distribution format):

```bash
hdiutil create -volname "Canvas Downloader" \
  -srcfolder "dist/Canvas Downloader.app" \
  -ov -format UDZO \
  dist/Canvas_Downloader_macOS.dmg
```

Distribute `Canvas_Downloader_macOS.dmg` alongside `README_INSTALL.md`.

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
hdiutil create -volname "Canvas Downloader" -srcfolder "dist/Canvas Downloader.app" -ov -format UDZO dist/Canvas_Downloader_macOS.dmg
```

---

## 9. Building via GitHub Actions (Cloud — No Mac Required)

The repository includes a pre-configured GitHub Actions workflow that runs the
full build sequence above on GitHub's macOS servers for free.

**When to use this instead of a local build:**
- You don't have a Mac available.
- You want a reproducible build that isn't affected by your local environment.
- You need a clean build environment.

**Files involved:**

| File | Purpose |
|---|---|
| `.github/workflows/build-macos.yml` | The workflow — triggers the build |
| `GITHUB_ACTIONS_GUIDE.md` | Step-by-step instructions for running it |

**Summary of what the workflow does:**

1. Checks out the repository on a real macOS GitHub runner.
2. Installs Python 3.13 and all dependencies from `requirements.txt`.
3. Runs `pyinstaller --clean Canvas_Downloader_macOS.spec`.
4. Runs `codesign --force --deep -s - "dist/Canvas Downloader.app"`.
5. Zips the `.app` and uploads it as a downloadable artifact.

The workflow runs a single `macos-latest` (ARM64) job. It produces a `.dmg` artifact valid for 30 days.

**Trigger**: Manual only. Go to the GitHub Actions tab → "Build macOS" →
"Run workflow". See `GITHUB_ACTIONS_GUIDE.md` for screenshots and detail.

> [!NOTE]
> The ad-hoc signing limitation applies equally to cloud builds: users will
> still see the Gatekeeper "unidentified developer" warning and must
> right-click → Open on first launch. See `README_INSTALL.md`.
