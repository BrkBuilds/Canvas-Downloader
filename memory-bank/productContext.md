# Product Context: Canvas Downloader

## Purpose
Desktop application for university students to batch download and synchronize course materials from Canvas LMS. Mirrors course structure locally and keeps files up-to-date.

## Key Features
- **Batch Download**:
    - **Wizard Interface**: Guided 4-step process (Select -> Settings -> Progress -> Complete).
    - **Structure Options**: Choose between organized module structure (with subfolders) or a single flat folder.
    - **Centralized Error Log**: Consolidates all download errors into a single `download_errors.txt` in the root folder, grouped by course.
    - **Resilient Progress**: Tracks successful and failed downloads, ensuring feedback even during network instability.
- **Smart Sync**:
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
- **Internationalization**: Full English and Danish support (53+ sync keys).
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
