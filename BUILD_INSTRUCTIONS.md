# Build Instructions for Canvas Downloader

This document contains the exact configuration needed to compile the application into an optimized standalone executable (~43MB).

## 📦 Dependencies

### Required Packages
These must be installed in your Python environment before building:
```bash
pip install streamlit==1.53.0 canvasapi aiohttp
```

## 🛠️ PyInstaller Configuration

The `Canvas_Downloader.spec` file is configured to:
1.  **Include** all Streamlit dependencies (`collect_all('streamlit')`)
2.  **Include** CanvasAPI (`collect_all('canvasapi')`)
3.  **Include** critical network libraries (`requests`, `aiohttp`, `urllib3`, etc.)
4.  **Exclude** heavy unused libraries to save ~100MB

### 🚫 Excludes List (Critical for Size Optimization)
Do **NOT** remove these from the `excludes` list in the spec file, or the executable size will triple.

| Package | Why it's excluded | Size Savings |
|---------|-------------------|--------------|
| `pyarrow` | Not used by this simple app | ~28 MB |
| `pandas` | Not used (we use simple lists/dicts) | ~30 MB |
| `numpy` | Not used | ~20 MB |
| `altair` | No charts used | ~10 MB |
| `pydeck` | No maps used | ~10 MB |
| `PIL` / `Pillow` | No image processing | ~5 MB |
| `streamlit.external.langchain` | AI features not used | ~5 MB |

### ⛔ Do NOT Exclude
These packages are **required**:
- `jinja2` (Required by Streamlit)
- `tornado` (Required by Streamlit)
- `watchdog` (Required by Streamlit)
- `toml` (Required by Streamlit)

## 🚀 How to Build

1.  **Clean previous builds** (Optional but recommended):
    ```powershell
    Remove-Item -Path "build", "dist" -Recurse -Force
    ```

2.  **Run PyInstaller**:
    ```powershell
    pyinstaller --clean Canvas_Downloader.spec
    ```

3.  **Verify**:
    - Output location: `dist/Canvas_Downloader.exe`
    - Expected Size: **~40-45 MB**
