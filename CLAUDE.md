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
  canvas_logic.py           # Canvas API wrapper, sanitization, async download engine
  sync_manager.py           # SQLite manifest engine (Levenshtein collision resolution)
  preset_manager.py         # Preset persistence engine
  canvas_debug.py           # Debug logging helpers
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
converters/                 # File conversion pipeline + per-format converters
  post_processing.py        # Unified conversion pipeline runner
  pdf.py / word.py / excel.py                       # Office → PDF/data (Win COM, mac osascript)
  code.py / md.py / url.py / video.py / archive.py  # code→txt, html→md, url→txt, video→mp3, zip extract
shared/                     # Cross-cutting UI utilities (import-safe from anywhere)
  helpers.py                # esc(), get_base64_image(), path utils, disk check (was ui_helpers.py)
  components.py             # Shared dialogs (error_log_dialog), render_config_summary_badges (was ui_shared.py)
  theme.py                  # Centralized design tokens / CSS variables
scripts/                    # Build & maintenance tooling (NOT bundled in the app)
  build_windows.py          # Windows release build (version_info → PyInstaller → Inno)
  build_msix.py             # Microsoft Store MSIX packaging
  patch_streamlit_webkit.py # Strips lookbehind regex for old WebKit (loaded by both specs)
  verify_architecture.py    # Architecture rule audit
version.py                  # __version__ (stays at repo root; read by CI + build specs)
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
- **Ghost-box-inside-container/column inflates spacing (Critical)**: The `global.css` ghost-box purge rule reliably zeroes the 1rem margin of a `st.markdown(<style>)` injection **only at page/`stVerticalBlock` top level**. When you inject `<style>` via `st.markdown` *inside* a bordered `st.container` (e.g. `sync_list_outline`) or *inside* an `st.columns` column - especially a row with `vertical_alignment="bottom"` - the ghost element-container still contributes height/gap, which silently inflates the space above the next row or pushes a column's button down out of alignment. **Fix:** if the CSS is static (the only "dynamic" value is an immutable constant like `theme.WHITE`/`#ffffff`), move it **entirely to a static `.css` file** that is injected once near the top of the page (e.g. `sync_hub.css` via `inject_hub_global_css()`). Never leave a `<style>` injection as a sibling/child inside a layout-critical container or column. Symptom to recognize: a gap between the last list item and a button row that is visibly larger than the inter-item gap, or a button that sits lower than the container's symmetric left/top padding.
- **Divider/separator spacing must use `padding`, not `margin-top`, to survive margin-collapse (Critical)**: A separator element (e.g. the `.cat-section-sep` divider between sync categories) shared by MULTIPLE container contexts will look correct in one and broken in another if its above-the-line spacing is a `margin-top`. A first-child's `margin-top` **collapses to zero** when its container has no top border/padding (true inside the sync-history `shist_body_` container), so the divider sits flush against the row above it - while the SAME element renders fine on the completion screen. **Padding never collapses.** Fix: draw the line as a `border-bottom` (or an inner 1px child) and put the above-space on `padding-top`; keep the below-space on `margin-bottom` (safe when the following header has `margin-top: 0`). Symptom: identical markup, divider spacing differs between two screens; "the divider is basically inside the last row above it" in one of them.
- **Double-escape** all CSS braces in f-strings: `{{` and `}}`.
- **Scope** all CSS to keyed containers (`div[class*="st-key-my_key"]`) to prevent global leakage.
- **Key Lowercasing Rule**: Streamlit lowercases widget `key` strings when generating DOM classes (e.g. `st-key-PDF` becomes `st-key-pdf`). Always apply `.lower()` to keys used in CSS selectors.
- **Modal Specificity Rule**: Standard CSS often fails inside `@st.dialog` because modals live in a separate high-specificity portal. Always prepend `div[data-testid="stDialog"] ` to modal-targeted CSS selectors.
- Never use `:has()` + sibling combinators (`~`) on main-app components - it leaks into `stDialog` portals with high specificity.
- **Descendant `:has()` matches ANCESTORS too - gap/style leak (Critical)**: `div[data-testid="stVerticalBlock"]:has(div[class*="st-key-X_chk_"])` matches **every** vertical block that *contains* a matching descendant - not just the immediate parent. In a dialog the top-level block contains the list's checkboxes as deep descendants, so a rule meant only for the list's own block (e.g. restoring `gap: 1rem` for checkbox rows after compacting the dialog to `0.4rem`) **also lands on the dialog's top-level block**, inflating the gap between every chrome element (pill, search, `hr`, list, button) and breaking flush `-Xrem` scroll-container margins that were tuned for the compact gap. Symptom: adding any element to a dialog "expands it wildly" with padding above/below the list. **Fix: use the direct-child form `:has(> div[class*="st-key-X_chk_"])`** so only the checkboxes' immediate parent block matches. Always prefer `:has(> ...)` over `:has(...)` unless you genuinely intend to match ancestors.
- **Inject inline dynamic CSS with `st.markdown(<style>)`, NOT `st.html(<style>)`, inside dialogs/flex flows**: `st.markdown`'s ghost-box element-container is auto-collapsed by the `global.css` rule (`element-container:has(> stMarkdownContainer style){display:none}`), so it contributes **no gap slot** to the parent `stVerticalBlock`'s flex `gap`. An `st.html(<style>)` element-container is NOT collapsed (only its margins are zeroed) and therefore still occupies a flex slot, adding a `gap`-worth of space between neighbors each time. (0-height `components.html` iframes ARE pulled out of flow by existing `global.css` rules scoped to `stDialog` and `stMain`, so JS bridges add no gap.)
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
- **Dialog title + subtitle must be ONE `st.markdown` call**: Two separate `st.markdown` calls for title and subtitle create Streamlit's ~1rem inter-element block gap between them regardless of any `margin-bottom` set on inner divs. The outer `element-container` wrapper is what creates the gap \u2014 inner CSS cannot escape it. Always combine title and subtitle HTML into a single `st.markdown(unsafe_allow_html=True)` call.
- **Dialog top/bottom padding lives on `div[role="dialog"] > div:first-child`**, NOT on `div[role="dialog"]` itself. Targeting `div[data-testid="stDialog"] div[role="dialog"]` with padding overrides may have no effect or stack additively. To reduce vertical padding while preserving the native horizontal padding (sides), target: `div[data-testid="stDialog"] div[role="dialog"] > div:first-child { padding-top: X !important; padding-bottom: Y !important; }`. The `margin-top: -70px` custom header needs the top padding to be at least `~1.5rem` or the title clips against the dialog edge.
- **Custom dialog header icon sizing**: Inline SVG icons used in dialog title headers (like `SVG_SAVE_COLORFUL`) should be sized at `~1.6em` to visually match the large icons used in other dialogs (e.g. Sync Hub). `1.2em` or smaller looks mismatched and too small.

### Containers & Keys
- `st.container(key="x")` does **not** reliably generate `st-key-x` CSS class unless `border=True` is set. Use `border=True` then strip the border via CSS ("Border Strip" trick).
- **Streamlit 1.51: `stVerticalBlockBorderWrapper` does NOT exist (Critical)**: The DOM element `[data-testid="stVerticalBlockBorderWrapper"]` was removed in Streamlit 1.51. All existing CSS patterns targeting it (e.g. in global.css sidebar rules or auth.py card borders) silently do nothing in 1.51. To custom-style a bordered container, use `st.container(key="x")` **without** `border=True` and apply the visual border/background/radius directly to `div[class*="st-key-x"]`. Do NOT use `st.container(border=True)` if you need custom CSS - the Streamlit-injected border comes from Styled Components (st-emotion-cache-*) and cannot be overridden reliably. The `border=True` flag is still useful to obtain the key class reliably on the outer wrapper, but in Streamlit 1.51 both `border=True` and plain `st.container(key="x")` reliably generate `st-key-x` on the outer div.
- **Streamlit 1.51 Flex `gap` Targeting (Critical)**: Because `st.container(key="x")` places the `st-key-x` class directly on the outer `stVerticalBlock` flex container, you must apply `gap` directly to `div.st-key-x` to space its immediate children (e.g. rows). DO NOT target `div.st-key-x [data-testid="stVerticalBlock"]` to set the container's gap - that selector will drill down and erroneously apply the gap to *nested* flex blocks (like `st.columns` inside the rows) while leaving the main container's row spacing unchanged.
- **Button key class is on `stButton` itself, not on an ancestor**: For `st.button(key="my_key")`, the `st-key-my_key` class lands on the `stButton` div element itself. So `div.st-key-my_key button` correctly targets the `<button>` inside. But `div.st-key-my_key [data-testid="stButton"]` is **wrong** - it looks for a `stButton` *inside* `stButton` which never exists. For margin-left indentation of a button, target `div.st-key-my_key { margin-left: Xpx !important; }` (the stButton wrapper itself), combined with `use_container_width=False` so the wrapper is content-sized and doesn't overflow.
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
- **`help=` tooltip shrinks/detaches a button (Critical)**: Passing `help="..."` to `st.button` wraps the `<button>` in a `[data-testid="stTooltipHoverTarget"]`, so it is no longer a direct child of `.stButton`. This silently drops the `.stButton > button` sizing (`min-height: 3em`, `width: 100%`), and the button renders ~3/4 height / narrower than its tooltip-less siblings in the same `st.columns` row (e.g. a disabled "Save Changes" shrinking next to "Cancel"). **Two-part fix required in `global.css`** - add BOTH selectors for any new full-width button:
  1. `div.st-key-<key> [data-testid="stTooltipHoverTarget"] { width: 100% !important; }` + `> button { width/height/min-height/padding !important; }` - covers the tooltip-wrapped (disabled+help) case.
  2. `div.st-key-<key> button { min-height: 3em !important; height: auto !important; padding: 0.5rem !important; width: 100% !important; }` - covers the no-tooltip case (help=None while disabled, or enabled): the base `.stButton>button` rule lacks `!important` on `min-height` so Streamlit's disabled-primary CSS can win. The direct `button` rule with `!important` fixes both states unconditionally.
  - For dynamic-index keys (e.g. `hub_save_edit_0`, `hub_save_edit_1`), use a prefix selector: `div[class*="st-key-hub_save_edit_"]`.
  - **Currently registered keys in `global.css`** (do not re-derive - just add new ones to the existing combined rule): `save_group_create`, `preset_save_create`, `confirm_pair`, `sync_confirm_btn`, `hub_save_edit_` (prefix), `hub_cs_confirm_btn`.

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

**SVG icons in expander labels and button labels**: Streamlit's `st.expander(label)` and `st.button(label)` accept plain text/markdown only - no HTML or SVG. To replace an emoji with an SVG icon:
1. Remove the emoji from the Python label string entirely.
2. Inject CSS `::before` on the label's rendered `<p>` element using a URL-encoded SVG data URI as `background-image`. Always use `content: ""` (empty string), not `content: url(...)` - the latter can't be sized.
3. Add `display: flex !important; align-items: center !important;` on the `<p>` so the pseudo-element and text sit on the same baseline.
4. **Specificity ordering for multiple container scopes**: A broad rule (e.g. `div[data-testid="stDialog"] ... summary p::before`) applies to all dialogs by default. More specific container-key selectors (e.g. `div[class*="st-key-preset_card_"] ... summary p::before`) naturally override it without needing `!important` tricks, as long as the specific rule has more attribute selectors. Put the broad rule first (earlier in CSS), specific overrides later.
5. The Streamlit expander label `<p>` lives at: `div[data-testid="stButton"] button p` (and for expanders: `div[data-testid="stExpander"] details summary p`).

**Vertically centring an icon + text label inside a button (Critical recipe)**: When you add a `::before` icon to a text button (e.g. a folder glyph left of "Open Folder"), the content visibly sits ABOVE the button's true centre unless you flex the **whole chain**. Flexing only the `<p>` is NOT enough - the `<p>` lives inside `[data-testid="stMarkdownContainer"]`, which is the button's actual flex child, so the container itself stays uncentred. The exact, proven recipe (see `inject_file_action_css`'s Open Folder block in `ui_shared.py` and the `pan_open_dialog_btn` block in `ui/download_settings.py`):
   1. `... button { align-items: center !important; justify-content: center !important; }` - centre the button's own content.
   2. `... button [data-testid="stMarkdownContainer"] { display: flex !important; align-items: center !important; }` - **the missing piece**: centre the label block (the real flex child).
   3. `... button p { display: inline-flex !important; align-items: center !important; gap: 8px !important; margin: 0 !important; }` - put icon + text on one centred line. The `margin: 0` is **required**: the label `<p>`'s default bottom margin is part of the flex item's margin-box, so `align-items: center` centres the margin-box and the visible content is pushed UP by half that margin. Symptom: content sits slightly high.
   4. **Do NOT set `line-height: 1`** on the `<p>`. It shrinks the line box below the glyph height, so the text overflows its own box and reads as mis-centred (visible in a box-model overlay as glyphs poking out the top of the text's box). Leave line-height at its default.
   5. `::before` icon: `content: ""; display: inline-block; width/height; flex-shrink: 0; background-image/size/position`. For grey-at-rest → white-on-hover, define two data-URI variants (e.g. `fill='%23b1bac4'` and `fill='%23ffffff'`) and swap via `... button:hover p::before { background-image: url(...) }`.
   6. Scope the whole block to the button's `key` prefix (`div[class*="st-key-<prefix>_open_"]`) so it never bleeds onto the per-file `fileact_open_` icon buttons that share the substring `_open_`.

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

### `components.html` JS Bridges (`window.parent` DOM manipulation)

When pure CSS/Python can't express an interaction (Shift-click range select, live-as-you-type filtering, etc.), inject a same-origin `<script>` via `st.components.v1.html(..., height=0)` that reaches into `window.parent.document`. Hard-won rules:

- **NEVER use a one-time `if (st.bound) return;` guard to attach a listener once for the page lifetime.** `components.html` builds a **fresh iframe on every rerun and destroys the previous one**. A listener attached from inside a destroyed iframe's JS realm **silently stops firing** (the realm/closure is dead). With a one-time guard, the listener is never re-attached, so the feature works on first load and then **dies permanently after the first iframe teardown** - most visibly after a *full-page* rerun (e.g. a segmented toggle outside the fragment). Symptom: "works when I refresh, but once it stops it never recovers, and manual blur/click still works."
- **Correct pattern: re-bind a fresh listener on EVERY injection.** The bridge function is called at the end of the fragment, so it re-runs on every fragment + full-page rerun. Each run: (1) remove the previous listener (`doc.removeEventListener('evt', reg.handler, true)` inside a `try/catch` - the stored ref stays valid for removal even if its realm is dead), (2) create a fresh handler closure (alive realm), (3) `addEventListener` it, (4) stash it on `reg.handler`. A blur/click that commits triggers a rerun → re-injection → fresh handler, so there's always a live listener.
- **Persist mutable state on `window.parent`, NOT in the iframe closure.** Store `{handler, timer, last, anchorKey, applying, ...}` on a `window.parent._cdXxx` registry object so it survives across re-binds (the iframe closure is recreated/destroyed every rerun). Use `window.parent.setTimeout`/`clearTimeout` so timer ids stay valid no matter which realm clears them.
- **Use event delegation on `document`** (capture phase where order matters) and re-query the live node set on each event, rather than binding to specific widget nodes that Streamlit reconciles/replaces.
- **Committing a text input live (filter-as-you-type):** Streamlit only commits a text input's value to Python on **blur or Enter**. A *synthetic* `Enter` `KeyboardEvent` is **ignored** (untrusted key events don't trigger React's commit). A programmatic **`inp.blur()` reliably fires the same onBlur commit as clicking out**; immediately `inp.focus({preventScroll:true})` and restore the caret with `inp.setSelectionRange(start,end)` so typing continues uninterrupted. Debounce (~180-200ms) and guard with a `last`-committed-value check to keep reruns to ~one per typing pause. (See `inject_search_live_bridge` and `inject_shift_select_bridge` in `ui/course_selector.py` for the canonical implementations.)

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
