# Product Context: Canvas Downloader

## Purpose
Desktop application for university students to batch download and synchronize course materials from Canvas LMS. Mirrors course structure locally and keeps files up-to-date.

## Key Features
- **Batch Download**:
    - **Wizard Interface**: Guided 4-step process (Select -> Settings -> Progress -> Complete).
    - **Structure Options**: Choose between organized module structure (with subfolders) or a single flat folder ("Flat" structure).
    - **Centralized Error Log**: Consolidates all download errors into a single `download_errors.txt` in the root folder, grouped by course.
    - **Resilient Progress**: Tracks successful and failed downloads, ensuring feedback even during network instability.
- **Smart Sync**:
    - **Saved Sync Groups**: Create, edit, and manage reusable multi-course sync profiles ("Groups") via a 3-layered interactive Hub dialog. Easily swap between full semesters of configured folders.
    - **Pop-up Course Selector**: Powerful dialog for selecting courses to sync, with search and filtering (Favorites, CBS filters) matching the main download page.
    - **Persistent Pairs**: Local folder ↔ Canvas course mapping saved to JSON, survives app restarts.
    - **Friendly Course Names**: Intelligently prioritizes "Friendly Names" (e.g., "Macroeconomics") over raw Canvas names to reduce clutter.
    - **Intelligent Updates**: Only downloads new or modified files; skips up-to-date ones.
    - **Quick Sync**: One-click sync for all configured pairs.
    - **Conflict Safety**: `_NewVersion` suffix preserves user edits on original files.
    - **Manifest Tracking**: Hidden JSON manifests track file history even if moved/renamed locally.
    - **Duplicate Detection**: Prevents pairing the same folder+course twice.
    - **Detailed History**: Logs past sync operations.
- **Offline Access**: Materials available without internet after download/sync.
- **NotebookLM Compatible Content Generation**:
    - Extends the core downloaded assets by dynamically converting or extracting them into formats optimized for LLM ingestion (like Google NotebookLM).
    - **Unified Excel Pipeline**: Features a single "Excel → PDF & AI Data" toggle that generates both a visual PDF and a structured `_Data.txt` sidecar.
    - **Smart-CSV Data Extraction**: Uses Win32 COM automation on Windows and native AppleScript on macOS to extract raw tabular data from Excel into unified sidecars with an AI-optimized `META-CONTEXT` header. This avoids the loss of tabular integrity inherent in PDF parsing.
    - **Native PDF Conversion**: Automates local Office applications to convert PowerPoints, Word Docs, and Excel spreadsheets into high-fidelity PDFs.
    - **URL Shortcut Merging**: Compiles internet shortcuts into a single master TXT file (`url_compiler.py`).
    - **Markdown Transformation**: Strips HTML Canvas pages down to pristine Markdown (`md_converter.py`).
    - **Data/Code Extension Shadowing**: Appends `.txt` extensions to raw programming/data files (e.g., `.js`, `.py`, `.csv`) to ensure they can be read by NotebookLM.
    - **Audio Extraction**: Swaps large video files with lightweight `.mp3` audio tracks to fit AI file limits (`video_converter.py`).
    - **Archive Extraction**: Auto-extracts `.zip` and `.tar.gz` payloads, bypassing the sync engine's deletion checks while keeping the local workspace clean.
- **User-Friendly UI**:
    - **Visual Step Trackers**: Clear progress indicators with emojis for both Download and Sync modes.
    - **CBS Filters**: Filter courses by Type, Semester, and Year (sorted newest first).
    - **Error Feedback**: Explicitly reports failed items in the progress bar.
    - **Styled Components**: Modern, clean interface with Streamlit.

## Technology Stack
- **Language**: Python 3.10+
- **Frontend**: Streamlit (with Custom Components & Dialogs)
- **API**: CanvasAPI
- **Distribution**: PyInstaller (Windows .exe)
