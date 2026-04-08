# Canvas Downloader — Claude Context

## Project Overview
Desktop app for batch-downloading Canvas LMS course materials. Built with Python + Streamlit, packaged as a standalone `.exe` (Windows) and `.app` (macOS) via PyInstaller. Runs locally in a pywebview window.

## Architecture

### Module Map
```
app.py                      # Main download mode and app orchestrator — routing, session init
sync_ui.py                  # Sync mode orchestrator
ui/
  auth.py                   # Sidebar: API token, debug mode, nav
  course_selector.py        # Step 1: course checklist, CBS filters, segmented toggle
  download_settings.py      # Step 2: Card 1/2/3 config UI (~1,400 lines)
  hub_dialog.py             # Sync Hub modal (saved groups)
  sync_dialogs.py           # Sync pair configuration dialogs
  sync_review.py            # Pre-sync diff/analysis review UI
  sync_confirmation.py      # Final confirmation before sync
  presets.py                # Preset engine + hub UI
core/
  state_registry.py         # Single source of truth for session state keys & defaults
  cancellation.py           # Global cancel flags + polling logic
engine/
  progress_dashboard.py     # Shared terminal log + visual dashboard UI
  post_processing_bridge.py # Unified post-processing init (sync + download)
  applescript_bridge.py     # macOS osascript runner (shared by PDF/Word/Excel converters)
sync/
  analysis.py               # Diff logic + async download tasks
  execution.py              # Background sync execution
  persistence.py            # Atomic JSON persistence (os.replace + threading.Lock)
  completion.py             # Post-sync UI and history logging
styles/
  global.css                # Static structural CSS
  preset_dialogs.css        # Preset/hub dialog CSS
  __init__.py               # inject_css() via st.html() (no caching to allow dev hot-reloads)
canvas_logic.py             # Canvas API wrapper, sanitization, async download engine
sync_manager.py             # SQLite manifest engine (Levenshtein collision resolution)
post_processing.py          # Unified conversion pipeline runner
theme.py                    # Centralized design tokens / CSS variables
ui_helpers.py               # esc(), get_base64_image(), path utils, disk check
ui_shared.py                # Shared dialogs (error_log_dialog), render_config_summary_badges
version.py                  # __version__
```

### Key Data Files (runtime)
- `canvas_sync_pairs.json` — active folder ↔ course mappings
- `saved_sync_groups.json` — reusable multi-course sync groups
- `canvas_sync_history.json` — last 50 sync operations
- `.canvas_sync.db` — per-folder SQLite manifest (hidden file)

### Sync Contract
The SQLite manifest (`.canvas_sync.db`) is the **single source of truth** for sync settings. `_show_sync_confirmation` unconditionally reads the contract from the DB — there are no on-the-fly UI overrides. The extracted contract is bound to `st.session_state['res_data']['contract']` for post-processing.

## Streamlit UI Rules (Critical)

### CSS Injection
- **Static CSS** → `styles/*.css` files, loaded via `styles.inject_css()` (uses `st.html()`, module caching disabled for dev).
- **Dynamic CSS** (depends on session state or Python vars) → inline `st.html(f'<style>...</style>')` inside `ui/` modules.
- **Headless Injection Rule**: Never use `st.markdown` for CSS, Base64 wrappers, or HTML spacers. Streamlit React forces `stMarkdownContainer` on it, injecting a 1rem bottom margin ("Ghost Box"). Always use `st.html()` for zero-footprint DOM injection.
- **Always hoist** dynamic CSS injections *above* the widget they target — injecting below causes a ~100ms grey flash on rerun (React sub-frame race condition).
- **Double-escape** all CSS braces in f-strings: `{{` and `}}`.
- **Scope** all CSS to keyed containers (`div[class*="st-key-my_key"]`) to prevent global leakage.
- Never use `:has()` + sibling combinators (`~`) on main-app components — it leaks into `stDialog` portals with high specificity.

### Dialogs (`@st.dialog`)
- No nested dialogs — Streamlit crashes. Flatten to single-layer modals.
- Trigger dialogs directly inside `if st.button():` — no dangling session state flags.
- Close buttons inside modals must use `st.rerun(scope="app")`, not plain `st.rerun()`.
- Hide the native close button via CSS: `div[data-testid="stDialog"] button[aria-label="Close"] { display: none !important; }`.
- **Zero-Width Space Hack  & invisible title**: Pass `"\u200b"` to `@st.dialog(...)` to satisfy Streamlit's non-empty validation while rendering an invisible title. Inject a custom HTML header and pull it up with `margin-top: -70px`.

### Containers & Keys
- `st.container(key="x")` does **not** reliably generate `st-key-x` CSS class unless `border=True` is set. Use `border=True` then strip the border via CSS ("Border Strip" trick).
- Use `st.rerun(scope="app")` when closing dialogs to force full DOM repaint.

### State Management
- Widget values lost on step navigation — explicitly save to `persistent_*` session state keys before `st.rerun()`.
- Protect `on_click` array mutations against double-click: all mutations must be idempotent.
- After updating a UI placeholder before a heavy blocking operation, add `time.sleep(0.2)` to guarantee Streamlit flushes the DOM paint.

### Buttons as Cards ("Native Button is the Card")
- Never overlay invisible buttons over `st.markdown` content — Streamlit's React DOM will collapse the hitbox.
- Style native `st.button` as a card using CSS (`height`, `background-image`, `::before`/`::after` pseudo-elements).
- Icons → Base64 via `get_base64_image()`, injected into CSS `background-image`.
- Use `::before` for icon layers in buttons next to text.

### HTML Safety
- All Canvas data interpolated into `st.html()` or `st.markdown(unsafe_allow_html=True)` must be wrapped with `esc()` (`html.escape`) to prevent XSS/DOM corruption.

## Platform Notes
- **Windows**: `win32com.client` COM automation for Office → PDF conversions. `ctypes` to hide `.canvas_sync.db`.
- **macOS**: `osascript` (AppleScript) via `engine/applescript_bridge.py` for Office conversions. Requires `com.apple.security.automation.apple-events` entitlement in `.spec`.
- **Keyring**: Lazy-loaded on Windows only — prevents macOS import/permission cascades.
- **File I/O**: Always specify `encoding='utf-8'` explicitly — Windows defaults to CP1252, causing Mojibake in emoji-heavy UI files.

## Build
- Windows: `pyinstaller Canvas_Downloader.spec`
- macOS: `pyinstaller --clean Canvas_Downloader_macOS.spec` + `codesign --force --deep -s - Canvas\ Downloader.app`
- Launcher: `start.py` — daemonized Streamlit thread + `pywebview.start()` on main thread (required for macOS Cocoa).
