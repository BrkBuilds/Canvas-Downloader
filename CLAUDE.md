# Canvas Downloader - Claude Context

## Project Overview
Desktop app for batch-downloading Canvas LMS course materials. Built with Python + Streamlit, packaged as a standalone `.exe` (Windows) and `.app` (macOS) via PyInstaller. Runs locally in a pywebview window.

## Architecture

### Module Map
```
app.py                      # Main download mode and app orchestrator - routing, session init
sync_ui.py                  # Sync mode orchestrator
ui/
  auth.py                   # Sidebar: Canvas Access Token, debug mode, nav
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
- `canvas_sync_pairs.json` - active folder ↔ course mappings
- `saved_sync_groups.json` - reusable multi-course sync groups
- `canvas_sync_history.json` - last 50 sync operations
- `.canvas_sync.db` - per-folder SQLite manifest (hidden file)

### Sync Contract
The SQLite manifest (`.canvas_sync.db`) is the **single source of truth** for sync settings. `_show_sync_confirmation` unconditionally reads the contract from the DB - there are no on-the-fly UI overrides. The extracted contract is bound to `st.session_state['res_data']['contract']` for post-processing.

## Streamlit UI Rules (Critical)

### CSS Injection
- **Static CSS** → `styles/*.css` files, loaded via `styles.inject_css()` (uses `st.html()`, module caching disabled for dev).
- **Dynamic CSS** (depends on session state or Python vars) → inline `st.html(f'<style>...</style>')` inside `ui/` modules.
- **Fragment Rerun Unmounting Bug**: Streamlit's `st.html()` is unstable when used for injecting `<style>` blocks in the main script if a fragment (like `@st.dialog` callbacks) triggers a partial rerun. Streamlit's React reconciliation can silently unmount `st.html()` blocks, completely breaking the main page layout while the dialog is open.
- **Headless Injection Rule (Updated)**: For layout-critical static CSS, move it entirely to a static `.css` file (e.g., `global.css`). For dynamic CSS that must be injected inline, use `st.markdown(f'<style>...</style>', unsafe_allow_html=True)`. The "Ghost Box" (1rem margin) created by `st.markdown` is already safely eliminated by the `div[data-testid="element-container"]:has(> div[data-testid="stMarkdownContainer"] style) { display: none !important; }` rule in `global.css`. Do **not** use `st.html()` for critical CSS layout structures.
- **Always hoist** dynamic CSS (especially for widget-dependent logic like colors/masks) to the absolute top of the function call before any containers or widgets are declared. Injecting inside/below deep containers causes Streamlit to drop the payload.
- **Double-escape** all CSS braces in f-strings: `{{` and `}}`.
- **Scope** all CSS to keyed containers (`div[class*="st-key-my_key"]`) to prevent global leakage.
- **Key Lowercasing Rule**: Streamlit lowercases widget `key` strings when generating DOM classes (e.g. `st-key-PDF` becomes `st-key-pdf`). Always apply `.lower()` to keys used in CSS selectors.
- **Modal Specificity Rule**: Standard CSS often fails inside `@st.dialog` because modals live in a separate high-specificity portal. Always prepend `div[data-testid="stDialog"] ` to modal-targeted CSS selectors.
- Never use `:has()` + sibling combinators (`~`) on main-app components - it leaks into `stDialog` portals with high specificity.
- **`st.html()` shadow root isolates `margin`**: `margin` on elements inside `st.html()` (e.g. `<hr style='margin:15px 0'>`) does NOT create external layout space - it is absorbed by the shadow root. To add real spacing around injected HTML, wrap in `<div style='padding: Xpx 0'>` instead; padding inflates the shadow root's rendered height.
- **Side-by-side buttons**: Use `st.columns([1,1])` + `use_container_width=True` in Python. Never use CSS `:has()` flex hacks on `stVerticalBlock` - unreliable and leaks specificity.
- **Streamlit checkbox gap**: Target `[data-testid="stCheckbox"] label` with `display: flex !important; gap: Xpx !important`. The `label > span` is the visual checkbox; `label > div` is the text wrapper. CSS `gap` cannot go negative - use `margin-left: -Xpx` on the text wrapper div for sub-zero tightness. Fix 1-2px vertical misalignment with `position: relative; top: -1px` on the `span`.
- **Full-Height Clickable Rows**: When checkboxes are in `st.columns(vertical_alignment="center")`, Streamlit injects `margin: 5px 0` creating unclickable dead zones. Kill the margin (`margin: 0 !important`), force `align-items: stretch` on the `stHorizontalBlock`, and apply a `flex: 1` + `display: flex; flex-direction: column` chain all the way down to the `<label>` to make the hit area 100% of the row height.

### Dialogs (`@st.dialog`)
- No nested dialogs - Streamlit crashes. Flatten to single-layer modals.
- Trigger dialogs directly inside `if st.button():` - no dangling session state flags.
- Close buttons inside modals must use `st.rerun(scope="app")`, not plain `st.rerun()`.
- Hide the native close button via CSS: `div[data-testid="stDialog"] button[aria-label="Close"] { display: none !important; }`.
- **Zero-Width Space Hack  & invisible title**: Pass `"\u200b"` to `@st.dialog(...)` to satisfy Streamlit's non-empty validation while rendering an invisible title. Inject a custom HTML header and pull it up with `margin-top: -70px`.

### Containers & Keys
- `st.container(key="x")` does **not** reliably generate `st-key-x` CSS class unless `border=True` is set. Use `border=True` then strip the border via CSS ("Border Strip" trick).
- Use `st.rerun(scope="app")` when closing dialogs to force full DOM repaint.

### Targeting Streamlit Widget Wrappers with CSS (Critical Lessons)

**The only reliable CSS selectors for widget children inside keyed containers are the class-based ones:**
```css
div[class*="st-key-my_key_"] [data-testid="stButton"] { ... }
```
These are the same selectors that work for styling the button itself. Do NOT use `:has()` to find `[data-testid="stButton"]` - it fails silently for widget wrapper divs even when `:has()` works for styling other descendants in the same container.

**`[data-testid="stButton"]` wrapper layout:**
- **st.markdown breaks CSS Sibling Hacks**: Never change an `st.html()` injection block to `st.markdown(unsafe_allow_html=True)` if the injected HTML contains a hidden marker `div` used for CSS sibling targeting (e.g., `div:has(> div > #marker) + div[data-testid="stExpander"]`). `st.markdown()` wraps its contents in a `<p>` tag inside a `stMarkdownContainer`, which breaks the exact DOM hierarchy that CSS sibling selectors rely on, causing the styles to detach instantly. Stick to `st.html()` when injecting structural markers for sibling hacks.
- By default Streamlit renders `[data-testid="stButton"]` as a block-level full-width wrapper.
- `margin-left: Xpx` on the wrapper shifts the entire block right. With `use_container_width=False` on the button, the button is content-sized and sits at the left edge of the (now-shifted) wrapper - this is the correct way to indent a button by a fixed pixel amount.
- Do NOT add `width: auto !important` or change `display` on `[data-testid="stButton"]` - it causes the wrapper to collapse and the button appears squished or disappears.
- Do NOT use `margin-left` on the `<button>` element itself (child of stButton) - Streamlit's `display: flex !important` override on the button causes it to not respond predictably.
- Do NOT use `padding-left` on `[data-testid="stButton"]` - Streamlit overrides it internally and it has no visible effect.

**st.columns() for button indent is unreliable across zoom/window sizes:**
- A percentage-based spacer column (`st.columns([0.05, 0.95])`) shifts the button by a percentage of the container width. Since the target alignment (e.g. matching a fixed-size icon) is in pixels, the column fraction that "looks right" on one screen drifts at different zoom levels or window sizes.
- **Always use CSS `margin-left` with fixed pixels on `[data-testid="stButton"]` (via class-based selector) for pixel-accurate button indentation.** This is screen-size independent.

**Key prefix selector coverage for folder cards:**
- Download mode cards: `div[class*="st-key-dl_fc_"]`
- Sync mode cards: `div[class*="st-key-sync_complete_fc_"]`
- Note: `div[class*="st-key-sync_fc_"]` does NOT match `sync_complete_fc_` - the substring `sync_fc_` is not contiguous in `sync_complete_fc_`. Always use the full prefix.

### CSS Checkbox Hack for Pure-CSS Toggle/Expand

To build an interactive expand/collapse inline with HTML content (no JS, no Streamlit state reruns):
```html
<input type="checkbox" id="my-toggle" class="toggle-class"/>
<label for="my-toggle" class="trigger-class">Click me</label>
<div class="content-class">Hidden content</div>
```
```css
.toggle-class { display: none; }
/* All three elements must be direct children of the same parent for ~ to work */
.toggle-class:checked ~ .trigger-class { /* active trigger style */ }
.toggle-class:checked ~ .content-class { /* reveal content */ }
```
- Use `max-width: 0 → max-width: 1000px` + `opacity: 0 → 1` transitions for smooth slide-in of inline content.
- Add a slight delay on `opacity` in the expand direction (`transition: max-width 0.28s, opacity 0.18s ease 0.06s`) so width starts opening before content fades in.
- For chevron rotation/thickness on toggle: target the inline SVG's `stroke-width` via CSS (`stroke-width: 5`) rather than `transform: rotate()` if you want a "bolder" active indicator instead of directional rotation. CSS can override SVG presentation attributes (`stroke`, `stroke-width`, `fill`) on inline SVGs.
- To make only a child element (e.g. a chevron) change color on toggle while the parent text stays neutral: use `stroke: #color` directly on the SVG element class inside the `:checked ~` rule, rather than relying on `color: inherit` propagation.

### SVG Icons in CSS and HTML

**URL-encoded data URIs** (for CSS `background-image`, `<img src="...">`):
- Replace `<` → `%3C`, `>` → `%3E`, `#` → `%23` in the SVG source.
- Use single quotes inside the SVG attributes (not double quotes) to avoid breaking the outer CSS string.
- Solid/filled icon: `fill='%23hexcolor'` with no stroke.
- Outlined icon: `fill='none' stroke='%23hexcolor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'`.

**Inline SVGs** (for `st.markdown(unsafe_allow_html=True)` HTML strings):
- Use raw `<svg>` tags directly - no URL encoding needed.
- Can use CSS classes (`class='my-chevron'`) and `stroke='currentColor'` to inherit parent `color`.
- CSS can override SVG attributes (`stroke`, `stroke-width`, `fill`) on inline SVGs targeting the element's class.

### `st.html()` Shadow Root Behaviour (Extended)
- `st.html()` renders into a shadow root - CSS inside it is completely isolated from the main page, and main-page CSS cannot reach into it.
- Elements rendered by `st.markdown(unsafe_allow_html=True)` ARE in the main DOM and ARE reachable by external CSS selectors.
- Use `st.html()` ONLY for injecting `<style>` tags or zero-content spacers. Use `st.markdown(unsafe_allow_html=True)` for actual HTML content that needs to be styled by external CSS.

### State Management
- Widget values lost on step navigation - explicitly save to `persistent_*` session state keys before `st.rerun()`.
- Protect `on_click` array mutations against double-click: all mutations must be idempotent.
- After updating a UI placeholder before a heavy blocking operation, add `time.sleep(0.2)` to guarantee Streamlit flushes the DOM paint.

### Buttons as Cards ("Native Button is the Card")
- Never overlay invisible buttons over `st.markdown` content - Streamlit's React DOM will collapse the hitbox.
- Style native `st.button` as a card using CSS (`height`, `background-image`, `::before`/`::after` pseudo-elements).
- Icons → Base64 via `get_base64_image()`, injected into CSS `background-image`.
- Use `::before` for icon layers in buttons next to text.

### HTML Safety
- All Canvas data interpolated into `st.html()` or `st.markdown(unsafe_allow_html=True)` must be wrapped with `esc()` (`html.escape`) to prevent XSS/DOM corruption.

## Platform Notes
- **Windows**: `win32com.client` COM automation for Office → PDF conversions. `ctypes` to hide `.canvas_sync.db`.
- **macOS**: `osascript` (AppleScript) via `engine/applescript_bridge.py` for Office conversions. Requires `com.apple.security.automation.apple-events` entitlement in `.spec`.
- **Keyring**: Lazy-imported inside functions on all platforms (`ui/auth.py`). macOS = Keychain with a 90s watchdog: a CLEAN install never prompts (creating/reading your own item is silent); only a REBUILD with a new ad-hoc signature reading the previous build's item triggers the one-time "enter login keychain password" prompt. Windows = Credential Manager (5s watchdog) + DPAPI-encrypted `.token_fallback` file; macOS deliberately has NO disk fallback.
- **File I/O**: Always specify `encoding='utf-8'` explicitly - Windows defaults to CP1252, causing Mojibake in emoji-heavy UI files.

## Build
- Windows: `pyinstaller Canvas_Downloader.spec`
- macOS: `pyinstaller --clean Canvas_Downloader_macOS.spec` + `codesign --force --deep -s - --entitlements entitlements.mac.plist Canvas\ Downloader.app`
- Launcher: `start.py` - daemonized Streamlit thread + `pywebview.start()` on main thread (required for macOS Cocoa).
