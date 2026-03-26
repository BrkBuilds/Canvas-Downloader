# Tech Context: Canvas Downloader

## Core Technologies
- **Python 3.10+**: Primary language.
- **Streamlit 1.51.0**: Web application framework for the UI (specifically pinned for targeting stability).
- **Modern CSS (:has)**: Utilized for version-agnostic "Trojan Horse" container targeting.

- **CanvasAPI**: Python wrapper for the Canvas LMS API.
- **aiohttp / asyncio**: For high-performance, concurrent file downloads.
- **Tkinter**: Used for native folder selection dialogs (as Streamlit runs in browser).
- **SQLite3**: Robust local database management for sync manifests.

## Development Environment
- **OS**: Windows and macOS (100% native feature parity).
- **Package Management**: `requirements.txt`.
- **Run Command**: `streamlit run app.py`

## Key Libraries
- `streamlit`: UI rendering (heavily using **`st.dialog`** for modals and `st.container` for layout).
- `canvasapi`: REST API interaction.
- `aiohttp`: Async HTTP requests.
- `keyring`: OS-native secure credential vault for storing API tokens (Windows).
- `base64`: Explicit macOS `keyring` permission bypass (used to encode token directly into settings JSON).
- `urllib.parse`: URL handling for robust filename decoding.
- `shutil`: Disk space checking (`disk_usage`).
- `sqlite3`: Robust manifest database management.
- `difflib`: Levenshtein string matching for collision resolution (`SequenceMatcher`).
- **pywin32 / osascript**: Dual-engine architecture for Office-to-PDF conversions. Windows uses `win32com.client` COM automation. macOS uses native `osascript` (AppleScript) subprocess execution to achieve exact feature parity for `.doc`, `.pptx`, and `.xlsx` files without heavy dependencies.
- `beautifulsoup4` / `markdownify`: Cleaning HTML Canvas Pages and converting them to Markdown.
- `moviepy`: Lightweight extraction of audio tracks (`.mp3`) from large video payloads.
- `zipfile` / `tarfile`: Native extraction of compressed payloads.

## File Structure
```
Canvas_LMS_batch_file_downloader/
├── app.py              # Main Streamlit app (~1400 lines)
├── sync_ui.py          # Sync mode UI (~4000 lines) — Step 1 & Step 4
├── ui_helpers.py       # Shared utilities (disk check, path utils, HTML escape)
├── canvas_logic.py     # Canvas API wrapper + sanitization
├── sync_manager.py     # Sync backend — Manifest Logic (SQLite, Levenshtein)
├── version.py          # Global version tracker (e.g., __version__)
├── theme.py            # Centralized design tokens and CSS variables
├── assets/             # Icons, images
├── post_processing.py  # Unified translation/conversion runner pipeline
├── pdf_converter.py    # Native PPTX/PPT to PDF COM converter
├── word_converter.py   # Native DOC/RTF to PDF COM converter
├── code_converter.py   # Code & Data raw file format preservation logic
├── url_compiler.py     # Master compilation engine for Synthetic Shortcuts (.url)
├── md_converter.py     # Canvas Page HTML->MD parser
├── video_converter.py  # Zero-logger Video->MP3 extraction utility
├── archive_extractor.py# Extractor and 0-byte Stub-generator for .zip payloads
├── excel_converter.py  # Native Excel to PDF COM converter (Tabular Integrity logic)
├── canvas_sync_pairs.json  # Persistent sync pair storage (runtime)
└── saved_sync_groups.json  # Persistent saved sync groups storage
```

## Sync Implementation Details
- **Robustness**: Uses `robust_filename_normalize` helper to handle Windows case-insensitivity vs Canvas case-sensitivity. Falls back to Levenshtein distance matching when size collisions occur during missing file detection.
- **Manifest Database**: `.canvas_sync.db` (per course folder, standard SQLite3)
    - **Tables**: `sync_manifest` (files) and `sync_metadata` (configuration k/v store).
    - **Attributes**: `canvas_file_id`, `canvas_filename`, `local_path`, `canvas_updated_at`, `downloaded_at`, `original_size`, `is_ignored`.
    - **Windows**: Hidden via `ctypes.windll.kernel32.SetFileAttributesW`.
- **Sync Pairs/Groups Files**: 
    - `canvas_sync_pairs.json` — stores active `local_folder`, `course_id`, `course_name`, `last_synced`.
    - `saved_sync_groups.json` — managed by `SavedGroupsManager`, stores reusable multi-course groups with unique `group_id`s.
- **Sync History File**: `canvas_sync_history.json` — last 50 entries with timestamp, files_synced, courses, errors.
- **ACID Consistency (Await-and-Inject)**: 
    - During Sniper Retries, the system enforces a strict synchronous discovery phase for secondary entities. 
    - Parent metadata is unpacked and committed to the manifest *before* attachment download tasks are injected into the async queue.
    - This prevents orphaned children if the application crashes between parent recording and child processing.

## Build System
- **PyInstaller**: Standalone `.exe` and macOS bundle `.app` compilation.
- **Optimization**: Specific excludes to reduce binary size.
- **macOS Entitlements**: Specifically requires `entitlements.plist` enabling `com.apple.security.automation.apple-events` bound to the `.spec` file to prevent OS-level blocks when driving Office conversions.
