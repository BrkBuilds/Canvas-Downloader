# Tech Context: Canvas Downloader

3: ## Core Technologies
4: - **Python 3.10+**: Primary language.
5: - **Streamlit 1.51.0**: Web application framework for the UI (specifically pinned for targeting stability).
6: - **Modern CSS (:has)**: Utilized for version-agnostic "Trojan Horse" container targeting.
- **Styling Standards**:
    - **Physical Volume Aesthetic**: Tactile UI with inset bevels, gradients, and soft glows.
    - **Snug Header Alignment**: Precise flex-based baseline alignment for help icons and headers.
    - **Flex-Based Centering**: Universal replacement of manual top-offsets with robust flexbox centering.
7: 
8: - **CanvasAPI**: Python wrapper for the Canvas LMS API.
9: - **aiohttp / asyncio**: For high-performance, concurrent file downloads.
10: - **Architecture / UI**: "Bring Your Own Browser" (BYOB) architecture on macOS via `customtkinter` Controller Window launching Google Chrome. Windows continues to use a native pywebview Edge backend for seamless desktop integration.
11: - **SQLite3**: Robust local database management for sync manifests.
12: 
13: ## Development Environment
14: - **OS**: Windows and macOS (100% native feature parity).
15: - **Package Management**: `requirements.txt`.
16: - **Run Command**: `streamlit run app.py`
17: 
18: ## Key Libraries
19: - `streamlit`: UI rendering (heavily using **`st.dialog`** for modals and `st.container` for layout).
20: - `canvasapi`: REST API interaction.
21: - `aiohttp`: Async HTTP requests.
22: - `keyring`: OS-native secure credential vault for storing API tokens (macOS Keychain / Windows Credential Manager).
23: - `pync`: Native macOS notifications (terminal-notifier) with app-focus support.
24: - `urllib.parse`: URL handling for robust filename decoding.
25: - `shutil`: Disk space checking (`disk_usage`).
26: - `sqlite3`: Robust manifest database management.
27: - `difflib`: Levenshtein string matching for collision resolution (`SequenceMatcher`).
28: - **pywin32 / osascript**: Dual-engine architecture for Office-to-PDF conversions. Windows uses `win32com.client` COM automation. macOS uses native `osascript` (AppleScript) subprocess execution to achieve exact feature parity for `.doc`, `.pptx`, and `.xlsx` files.
- **Zero-Dependency Smart-CSV Extraction**: Engineered a custom memory-to-CSV extraction layer in `excel_converter.py` that utilizes the existing COM/AppleScript bridge.
- `customtkinter` / `PIL`: Used on macOS exclusively to render the lightweight Controller Window.
30: - `beautifulsoup4` / `markdownify`: Cleaning HTML Canvas Pages and converting them to Markdown.
31: - `html`: Native security library used for XSS-safe URL escaping in generated HTML artifacts.
- `moviepy`: Lightweight extraction of audio tracks (`.mp3`) from large video payloads.
32: - `zipfile` / `tarfile`: Native extraction of compressed payloads.
33: 
34: ## File Structure
35: ```
36: Canvas_LMS_batch_file_downloader/
37: ├── app.py              # Main Streamlit app (~1400 lines)
38: ├── sync_ui.py          # Sync mode UI (~4000 lines)
39: ├── ui_helpers.py       # Shared utilities (disk check, folder picker, notifications)
40: ├── start.py            # Cross-platform entrypoint + platform branching
├── macos_controller.py # macOS CustomTkinter server controller
├── canvas_logic.py     # Canvas API wrapper + sanitization
├── sync_manager.py     # Sync backend (SQLite, Levenshtein, manifest logic)
├── version.py          # Global version tracker (e.g., __version__)
43: ├── theme.py            # Centralized design tokens and CSS variables
44: ├── assets/             # Icons, images, chime.wav
45: ├── post_processing.py  # Unified translation/conversion runner pipeline
46: ├── pdf_converter.py    # Native PPTX/PPT to PDF converter
47: ├── word_converter.py   # Native DOC/RTF to PDF converter
48: ├── code_converter.py   # Code & Data raw file format preservation logic
49: ├── url_compiler.py     # Master compilation engine for Synthetic Shortcuts (.url)
50: ├── md_converter.py     # Canvas Page HTML->MD parser
51: ├── video_converter.py  # Zero-logger Video->MP3 extraction utility
52: ├── archive_extractor.py# Extractor and 0-byte Stub-generator for .zip payloads
53: ├── excel_converter.py  # Dual-Pipeline Excel converter (PDF + AI-optimized CSV/TXT Sidecars)
└── Canvas_Downloader_macOS.spec # macOS build specification (BYOB + CustomTkinter)
55: ```
56: 
57: ## Path Management
58: - **Config Directory**:
59:     - **Windows**: `%APPDATA%/CanvasDownloader/` (Frozen build).
60:     - **macOS**: `~/Library/Application Support/CanvasDownloader/`.
61: - **Filesystem Parity**: All paths standardized to forward slashes (`/`) for manifest storage.
62: - **Memory-Efficient Lazy Pagination**: Uses `canvasapi` paginators as lazy iterators rather than materializing `list()` results, protecting against `MemoryError` on 50,000+ file courses.
63: - **API Token Redaction**: Custom `__repr__` on `CanvasManager` masks sensitive tokens as `'****'` to prevent accidental log exposure.
64: 
65: ## Build System
66: - **Windows Distribution**:
67:     - **PyInstaller spec**: `Canvas_Downloader.spec` — one-dir mode (mirrors macOS spec structure)
68:     - **Installer**: `Canvas_Downloader_Setup.iss` (Inno Setup 6.7.1)
69:     - **Installation**: Per-user default to `%LOCALAPPDATA%\Programs\Canvas Downloader\`; user can opt for machine-wide via UAC
70: - **macOS Distribution**:
71:     - **PyInstaller spec**: `Canvas_Downloader_macOS.spec` — one-dir + BUNDLE
72:     - **Distribution**: `.app` bundle
73:     - **macOS Entitlements**: Requires `entitlements.plist` enabling `com.apple.security.automation.apple-events`.
74: - **Optimization**:
    - Explicit excludes (`win11toast`, `winsound` for macOS, `webview`, `PySide6`, heavy data science libs) to reduce binary size.
    - Windows `upx=False` — removed decompression overhead at startup.
- **Size Estimates**: 
    - Windows: ~347MB (one-dir bundle on disk)
    - macOS: ~70-90MB (BYOB native `.app` bundle without embedded Chromium engine)
