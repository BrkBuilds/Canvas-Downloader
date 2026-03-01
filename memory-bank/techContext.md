# Tech Context: Canvas Downloader

## Core Technologies
- **Python 3.10+**: Primary language.
- **Streamlit**: Web application framework for the UI.
- **CanvasAPI**: Python wrapper for the Canvas LMS API.
- **aiohttp / asyncio**: For high-performance, concurrent file downloads.
- **Tkinter**: Used for native folder selection dialogs (as Streamlit runs in browser).
- **SQLite3**: Robust local database management for sync manifests.

## Development Environment
- **OS**: Windows (primary target).
- **Package Management**: `requirements.txt`.
- **Run Command**: `streamlit run app.py`

## Key Libraries
- `streamlit`: UI rendering (heavily using **`st.dialog`** for modals and `st.container` for layout).
- `canvasapi`: REST API interaction.
- `aiohttp`: Async HTTP requests.
- `urllib.parse`: URL handling for robust filename decoding.
- `shutil`: Disk space checking (`disk_usage`).
- `sqlite3`: Robust manifest database management.
- `difflib`: Levenshtein string matching for collision resolution (`SequenceMatcher`).
- `pywin32` (`win32com.client`, `pythoncom`): Windows COM automation for natively converting PPTX files to PDF.

## File Structure
```
Canvas_LMS_batch_file_downloader/
├── app.py              # Main Streamlit app (~900 lines)
├── sync_ui.py          # Sync mode UI (774 lines) — Step 1 & Step 4
├── ui_helpers.py       # Shared utilities (185 lines)
├── canvas_logic.py     # Canvas API wrapper + sanitization
├── sync_manager.py     # Sync backend — Manifest Logic (SQLite, Levenshtein)
├── translations.py     # EN/DA translations
├── assets/             # Icons, images
└── canvas_sync_pairs.json  # Persistent sync pair storage (runtime)
```

## Sync Implementation Details
- **Robustness**: Uses `robust_filename_normalize` helper to handle Windows case-insensitivity vs Canvas case-sensitivity. Falls back to Levenshtein distance matching when size collisions occur during missing file detection.
- **Manifest Database**: `.canvas_sync.db` (per course folder, standard SQLite3)
    - **Tables**: `sync_manifest` (files) and `sync_metadata` (configuration k/v store).
    - **Attributes**: `canvas_file_id`, `canvas_filename`, `local_path`, `canvas_updated_at`, `downloaded_at`, `original_size`, `is_ignored`.
    - **Windows**: Hidden via `ctypes.windll.kernel32.SetFileAttributesW`.
- **Sync Pairs File**: `canvas_sync_pairs.json` — stores `local_folder`, `course_id`, `course_name`, `last_synced`.
- **Sync History File**: `canvas_sync_history.json` — last 50 entries with timestamp, files_synced, courses, errors.

## Build System
- **PyInstaller**: Standalone `.exe` compilation.
- **Optimization**: Specific excludes to reduce binary size.
