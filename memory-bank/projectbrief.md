# Project Brief: Canvas Downloader

## Core Purpose & Business Value
The **Canvas Downloader** is a robust desktop application built to solve a critical pain point for university students and educators: the inability to easily batch-download and synchronize complete course structures (files, pages, external links) from the Canvas LMS. This application provides immense value by creating an offline, searchable, and always-up-to-date repository of educational materials.

Recently, the application has evolved beyond simple downloading to include a **NotebookLM Compatible Download** suite, automatically converting complex educational formats into AI-digestible plaintext formats, bridging the gap between raw LMS content and modern AI research tools.

## Key Features & Capabilities
1. **Batch Downloading & Directory Structuring**:
   - Pulls all modules, sub-modules, and files, directly replicating the Canvas structure locally.
   - Offers robust options for organized folder hierarchies or flattened directories ("Flat" mode).
2. **Smart Synchronization Engine**:
   - Matches local folders with Canvas courses and tracks them via a hidden SQLite manifest (`.canvas_sync.db`).
   - Intelligently downloads only new or altered files, skipping unchanged content (utilizing `sync_manager.py`).
   - Safely renames local edits (e.g., `_NewVersion.pdf`) to avoid overwriting user notes.
3. **Synthetic Shortcut Sync**:
   - Downloads Canvas Pages (`.html`) and External Links/Tools (`.url`) securely, using a "Negative ID" pattern.
4. **NotebookLM Compatible Features (AI Optimization)**:
   - **PowerPoints to PDF**: Native `win32com.client` conversion (`.pptx` -> `.pdf`).
   - **Legacy Word to PDF**: Native conversion for old formats (`.doc`, `.rtf`, `.odt` -> `.pdf`).
   - **Excel to PDF**: Native `win32com.client` conversion (`.xlsx`, `.xls`, `.xlsm` -> `.pdf`) with tabular integrity PageSetup.
   - **HTML to Markdown**: Converts Canvas Pages to clean `.md` (`beautifulsoup4`, `markdownify`).
   - **Code/Data to TXT**: Appends `.txt` to ~50 programming/data formats (e.g., `script_py.txt`) while enforcing UTF-8.
   - **Link Compilation**: Scrapes `.url` shortcuts into a master `NotebookLM_External_Links.txt` file per course.
   - **Video to Audio**: Extracts `.mp3` tracks from `.mp4`/`.mov` using `moviepy`, deleting the heavy original video.
   - **Auto-Extract Archives**: Unzips `.zip`/`.tar.gz` and inserts a 0-byte `.extracted` ghost stub to satisfy the sync engine without ballooning disk space.

## Architecture & Technology
- **Frontend**: Streamlit, leveraging advanced custom CSS injection, fraction-column layouts, and `.st.dialog` modals to create a native-feeling desktop experience in a local browser window.
- **Backend**: Python 3.10+, utilizing `aiohttp` and `asyncio` for highly concurrent, non-blocking downloads.
- **Data Layer**: SQLite3 for the manifest database and JSON for configuration/sync pair tracking.
- **APIs**: `canvasapi` heavily utilized for fetching course structures.
- **Distribution**: Packaged via PyInstaller into a standalone Windows `.exe` to remove the need for standard users to install Python environments.

## Development Approach
The development is focused on high-performance concurrent processing coupled with an incredibly polished, responsive UI. Error handling is paramount, relying on fallback string matching (Levenshtein distance) and robust COM thread execution (with UI flushing) to smoothly bypass external environment limitations (e.g., missing Office installations or restricted LTI media blocks).
