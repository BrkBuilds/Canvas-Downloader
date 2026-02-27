# System Patterns: Canvas Downloader

## Core Architecture
Modular design centered around Streamlit for UI and CanvasAPI for backend communication.

### File Structure
- **`app.py`**: Main entry point, UI controller.
- **`sync_ui.py`**: All sync-related UI logic.
- **`ui_helpers.py`**: Shared UI utilities (disk check, plurals, path utils).
- **`canvas_logic.py`**: Canvas API interactions.
- **`sync_manager.py`**: Sync backend (SQLite manifest, MD5 hashing, analysis engine).
- **`translations.py`**: Centralized i18n dictionary.

## UI Architecture & Patterns
- **Modals**: Use **`st.dialog`** for complex isolated interactions.
- **Interactive Lists**: Use HTML `<details>` and `<summary>` inside modals to handle large file lists without overwhelming the main view.
- **Component Constriction**: Use fractional columns to limit component width on large screens.
- **Zero-Indentation HTML String Pattern**:
    - Streamlit's markdown parser converts indented HTML strings into `<pre><code>` blocks.
    - *Robust Pattern*: Construct long HTML/CSS strings in Python without any leading indentation on the multi-line closing quotes/content to ensure they render as raw HTML.
- **Flex-box Hanging Indent Pattern**:
    - To support emojis + multi-line text:
    - Use `display: flex; align-items: flex-start;` on `<li>`.
    - Wrap the icon in a fixed-width `span` (e.g., `24px`).
    - Wrap the text in a `flex:1` `span` with `word-break: break-word`.
- **Progress Bar Visibility Pattern**:
    - For disk space checks: `min(100, max(1, real_pct))` if `bytes > 0`.
    - Pure linear mapping on high-capacity drives makes small downloads look like 0% (invisibility). Always implement a 1% floor for any non-zero sync size.

## Synchronization Strategy
- **SQLite Manifest Tracking**: Stores metadata (ID, path, size, date) for 1:1 mapping.
- **Negative ID Pattern**: Synthetic shortcuts (Pages, ExternalUrls, ExternalTools) are assigned `id = -int(item.id)`. This keeps them unique and prevents primary key collisions with physical Canvas `File` objects in SQLite.
- **Shortcut Bypass Logic**: `_is_canvas_newer()` in `sync_manager.py` explicitly returns `False` for `id < 0`. This bypasses unreliable module timestamps and forces the engine to rely on local existence checks.
- **Sync Restoration Interception**: The download pipeline in `sync_ui.py` intercepts negative IDs and recreates `.url` or `.html` files locally using static templates rather than performing an HTTP GET.
- **URL Extraction Priority**: For synthetic shortcuts, `html_url` is prioritized over `external_url` to ensure LTI tools route through the Canvas wrapper for authentication.
- **Deduplication**: Files are deduplicated by calculated target path and size to handle identical items linked in multiple modules.
- **Analysis Engine**: Diffing Canvas vs Local Manifest vs Local Disk.
- **Path Determination**: `detect_structure()` must precede analysis to correctly calculate relative paths for "Flat" vs "Folders" modes.

## Error Handling & Logging
- **Locked File Pruning**: Pre-filtering Canvas `File` objects for missing `url` attributes to prevent batch download crashes.
- **LTI/Media Catch**: Graceful reporting of restricted media streams via extension/URL inspection.
- **Centralized Logs**: `download_errors.txt` created in the workspace root.
