### 📋 The Master Streamlit UI Guardrails & Architecture Guidelines

#### 1. Dialogs & Fragments (`@st.dialog`) Architecture
* **No Nested Dialogs:** Streamlit fundamentally crashes if you attempt to trigger an `@st.dialog` from inside another `@st.dialog`. **Rule:** Flatten modal architecture; use inline UI components (like `st.selectbox` or inline edit cards) within a single dialog.
* **Dialog Persistence:** Streamlit natively keeps dialogs open as long as they are called. Trigger the dialog strictly inside the `if st.button:` block; do not use dangling session state flags (e.g., `dialog_open = True`) which cause "Ghost Dialogs" on unrelated reruns.
* **The Ghost Toast Pattern:** Calling `st.toast()` and then immediately triggering `st.rerun()`, or calling a toast directly inside a fragment's `on_click` callback, wipes the DOM and causes a `Fragment rerun was triggered...` crash. **Rule:** Set a scoped variable (e.g., `st.session_state['pending_toast'] = "Success"`) and consume it via `st.toast()` at the absolute top of the main render function or dialog body.
* **Supercharged Close / DOM Refresh:** Closing a dialog fragment natively or via a standard `st.rerun()` leaves the main app behind it frozen in a stale state. **Rule:** Custom "Close" buttons inside modals must use `st.rerun(scope="app")` to force a top-to-bottom repaint of the main UI. Hide the native Streamlit 'X' via CSS (`div[data-testid="stDialog"] button[aria-label="Close"] { display: none !important; }`) to force users through the state-aware button.
* **Intra-Dialog Routing:** Do not use `st.rerun()` for tab/layer navigation inside a dialog, as it will abruptly close the SPA (Single Page Application) modal. **Rule:** Use `on_click` callbacks on buttons to mutate session state *before* the dialog re-evaluates its layout.

#### 2. CSS Injection & DOM Targeting
* **Keyed Container Scoping:** Streamlit's default margins are often too loose. Wrap target loops or sections in `st.container(key="some_key")`. **Rule:** Inject CSS using partial attribute selectors (`div[class*="st-key-some_key"]`) to override internal `stHorizontalBlock` or `stVerticalBlock` styling without polluting the global scope.
* **Wildcard Selectors for Dynamic Widgets:** Standard class selectors fail on dynamic keys (e.g., `key=f"cat_new_{course.id}"`). **Rule:** Use CSS wildcard attribute selectors (`div[class*="st-key-cat_new"]`) to style identical dynamic widgets globally.
* **Page-Level CSS Injection:** NEVER inject `<style>` tags inside an `st.empty().container()` context; Streamlit discards them during DOM transitions. **Rule:** All critical UI CSS must be injected at the PAGE level, outside dynamic empty containers.
* **CSS Specificity & Leakage Prevention:** Avoid using the `:has()` pseudo-class combined with sibling combinators (`~`) to style main app components, as it climbs the DOM tree and inadvertently matches the Streamlit `stDialog` portal, leaking styles with devastating `(1,1,4)` specificity. **Rule:** ALWAYS prefix dialog button CSS with `div[data-testid="stDialog"]` to ensure bulletproof styling.
* **Merged CSS/HTML Injection:** Separate `st.markdown` calls for `<style>` and HTML generate multiple hidden Streamlit wrapper `divs` that add unwanted vertical padding. **Rule:** Bundle the CSS `<style>` block and HTML tags into a *single* `st.markdown(unsafe_allow_html=True)` call.
* **The F-String CSS Trap (Fatal NameErrors):** When injecting CSS via `st.markdown(f'''<style>...''')` to pass Python variables (like Base64 strings or Theme colors), standard CSS brackets `{` and `}` will be evaluated as Python code and crash the app with a `NameError`. **Rule:** You MUST double-escape all literal CSS brackets as `{{` and `}}` inside Python f-strings.
* **The Specificity Shield (Active vs Hover states):** Streamlit's shadow DOM and your own generic `:hover` states (e.g., `div[class*="st-key-btn_"] button:hover`) carry heavy CSS specificity because of the pseudo-class. This will accidentally overwrite your active state styles (like blue borders) when the user hovers over an already-active button. **Rule:** Always create a Specificity Shield rule directly below your active state: `div.st-key-{active_key} button:hover { border-color: {active_color} !important; }` to protect it from generic hover degradation.
* **Overriding Streamlit's Inner Button Wrappers:** Telling an `st.button` to be `text-align: left` or `display: flex` often fails because Streamlit injects a hidden `div[data-testid="stMarkdownContainer"]` inside the button that aggressively forces center-alignment. **Rule:** To force text alignment inside a custom button card, you must explicitly target the inner wrappers: `div.st-key-my_button button > div { text-align: left !important; width: 100% !important; justify-content: flex-start !important; }`.

#### 3. Component Workarounds & Layout Hacks
* **Hitbox Margin Defeat:** Pulling text labels tight against active UI widgets (like checkboxes) using negative `margin-bottom` causes the text's transparent DOM bounding box to overlay and physically block mouse clicks on the widget below. **Rule:** Use `margin-bottom: 0px` on text labels, and achieve tightness by using negative *top* margins on the elements beneath them.
* **Aggressive Header Suction:** Native Streamlit `###` headers have massive default bottom margins. **Rule:** Replace them with custom HTML `<h3 style='margin-bottom: -25px;'>` to forcefully pull widgets up against the header.
* **Extreme Column Ratios:** Default `st.columns(2)` splits are too wide for small trigger buttons next to inputs. **Rule:** Use extreme ratios like `[1.5, 8.5]` or `[1, 6]` to perfectly align layout elements horizontally.
* **Dynamic Expander Counters (CSS Ghost Text):** Injecting dynamic variables directly into the Python string of `st.expander(f"🆕 [{x}/{y}]")` changes the widget ID on rerun, destroying the user's open/closed state. **Rule:** Keep the title static (`st.expander("🆕 Files")`) and project the dynamic counter onto the screen using the `::after` CSS pseudo-element targeting the summary tag.
* **Radio Widget Granular Tooltips:** Streamlit lacks per-option tooltips for radios. **Rule:** Inject a styled HTML block (`st.markdown`) directly beneath the radio using `ⓘ` icons, `color: #6b7280`, and `font-size: 0.78rem` to visually fake native hints.
* **Zero-Indentation HTML:** Streamlit parses indented HTML strings as `<pre><code>` blocks. **Rule:** Keep multi-line HTML/CSS strings strictly unindented in Python code.
* **Dynamic Equal-Height Columns (Elastic Cards):** When placing buttons/cards side-by-side in st.columns, they will render at different heights if the text wraps unevenly. Streamlit stretches the invisible outer columns, but leaves the inner stButton wrappers at height: auto. **Rule:** To create uniform card rows, never hardcode pixel heights. Instead, inject CSS to stretch the middlemen: `div[data-testid="column"] > div, div[data-testid="stButton"] { height: 100% !important; }` and then set your custom button to `height: 100% !important;`.
* **Bordered Container Height Synchronization (The Flex Bottleneck):**
    * **Problem:** When using Native Streamlit `st.container(border=True, key="my_card")` elements side-by-side, they will fail to match each other's height dynamically if one expands. Streamlit 1.51+ injects an intermediate `stLayoutWrapper` parent *around* your keyed card, hardcoded to `flex: 0 1 auto`, permanently blocking vertical growth from the parent column. Furthermore, `st.container(border=True)` does *not* create an inner `stContainer` element; the keyed `stVerticalBlock` is the container itself.
    * **Rule:** Do NOT use JavaScript `MutationObserver` components to sync heights (Streamlit's React engine will fight it, causing race conditions and infinite loops).
    * **Solution:** To force dynamic height parity, apply a surgical two-tier CSS flex-chain directly mapping the DOM bottleneck:
        ```css
        /* Tier 1: Target the intermediate stLayoutWrapper parent */
        div[data-testid="stLayoutWrapper"]:has(> [class*="st-key-my_card"]) { flex: 1 !important; }
        /* Tier 2: Ensure the target card wrapper itself actually expands */
        div[class*="st-key-my_card"] { flex: 1 !important; display: flex !important; flex-direction: column !important; }
        ```
* **CSS `:has()` Depth Limits:**
    * **Problem:** Attempting to build deep ancestor flex-chain selectors like `div:has(> div > div > [class*="st-key-my_card"])` often fails silently (`NO MATCH` in browser) because browser CSS engines struggle with deeply nested `:has()` pseudo-classes attached to partial attribute selectors within complex DOMs like Streamlit's.
    * **Rule:** Never guess Streamlit wrapper depths. Map the exact DOM, and write minimal `parent:has(> child)` CSS selectors targeting precisely the bottleneck identified (like `stLayoutWrapper`).
* **Crushing Streamlit Column Gaps:** st.columns(gap="small") still enforces a rigid 0.5rem minimum gap. **Rule:** To pull segmented controls or cards tightly together, target the specific wrapper's flexbox container: `div[class*="st-key-my_wrapper"] [data-testid="stHorizontalBlock"] { gap: 4px !important; }`.
* **Side-By-Side Button Layouts (The Flex Row Hack):**
    * **Problem:** Placing auto-sized widgets (like `st.button`) side-by-side using `st.columns()` forces them into rigid, screen-proportional grids. On large screens, this creates a massive, ugly gap. On small screens, the columns become too small and the buttons overlap or wrap improperly.
    * **Rule:** Do NOT use `st.columns()` to place standard buttons side-by-side if you want them to naturally hug their content and maintain a fixed gap.
    * **Solution:** Place both buttons inside a single `st.container(key="my_button_row")`. Remove `use_container_width=True` from the buttons in Python so they natively render as `width: auto`. Then, add the static structural CSS to `styles/global.css` (adhering to the Dual-Layer CSS strategy in Section 9) to force the container into a flex row:
        ```css
        /* Force the container into a flex row (Place in styles/global.css) */
        div.st-key-my_button_row,
        div.st-key-my_button_row > div,
        div.st-key-my_button_row > div > div, 
        div.st-key-my_button_row > div > div > div {
            display: flex !important;
            flex-direction: row !important;
            align-items: center !important;
            gap: 12px !important;
            flex-wrap: wrap !important;
            width: 100% !important;
        }
        /* Defeat Streamlit's 100% block width applied to elements */
        div.st-key-my_button_row div[data-testid="element-container"],
        div.st-key-my_button_row div.stElementContainer {
            width: auto !important;
            flex: 0 0 auto !important;
            margin-bottom: 0px !important;
        }
        ```
        This completely destroys Streamlit's strict scaling and establishes standard web-native behavior. The buttons will maintain exactly a 12px gap at all screen sizes, hugging their own text lengths natively, and smartly dropping to the next line (`flex-wrap: wrap`) on mobile screens without overlapping.
#### 4. State Management, Reactivity & Lifecycle
* **First-Render Checkbox Hydration:** Stuffing `True` into `st.session_state["my_key"]` before declaring `st.checkbox` often fails visually on the first frame (the box flashes or appears unchecked). **Rule:** Always explicitly define the parameter: `st.checkbox("Label", key="my_key", value=st.session_state.get("my_key", False))` to guarantee 100% visual parity on the initial draw.
* **Widget Cleanup Bypass:** Navigating away from a step destroys its widgets and deletes their keys from `st.session_state`. **Rule:** Capture crucial widget booleans into custom `persistent_` state keys explicitly inside the `if st.button('Next'):` block, right before the `st.rerun()` trigger.
* **Idempotent Array Mutations:** Rapidly double-clicking buttons triggers `on_click` events twice before the render loop executes. **Rule:** All array manipulations (like appending to a list of UI elements) must be strictly idempotent to prevent duplicate keys and subsequent Streamlit crashes.
* **UI Thread Flushing (DOM Paint Locking):** Launching heavy blocking backend threads (like COM automation) immediately after updating a UI placeholder freezes the UI before the browser can paint the new text. **Rule:** Inject an explicit `time.sleep(0.2)` immediately after rendering loading states to guarantee Streamlit flushes the HTML to the DOM.
* **Un-Throttled Per-File Status Indicators:** Updating UI placeholders at high speeds (e.g., inside a fast file-download loop) crashes Streamlit's render budget. **Rule:** Throttle the main UI dashboard renders (e.g., `if time.time() - last_update > 0.4:`), but keep the lightweight `active_file_placeholder` text *outside* the throttle for instant, responsive feedback.

#### 5. Frontend Security
* **Strict HTML Escaping (`esc()`):** Passing raw, user-controlled variables (Canvas Course names, filenames, error strings) into `st.markdown(unsafe_allow_html=True)` opens the UI to DOM-corruption and XSS if the string contains `<script>` or unclosed `</div>` tags. **Rule:** Universally wrap all interpolated variables inside HTML structures with the `esc()` utility (wraps `html.escape`). *Exception:* Canvas Rich Text payloads (like Discussion bodies).

***
#### 6. Advanced Button & Card Architectures (The Clickable Card)
* **Anti-Pattern: The "Invisible Button Overlay" (DOM Layering Hacks):**

**Problem:** Attempting to make a visually rich card (built with st.container and st.markdown) clickable by stretching a transparent st.button over it using position: absolute, CSS Grid stacking, or negative margin overlap (-140px) will always fail. Streamlit dynamically wraps st.button inside multiple hidden flexbox containers (like element-container and stVerticalBlock). The React frontend constantly recalculates the heights of these inner wrappers during render cycles, causing the absolute button to collapse into a tiny, unclickable dead-zone at the bottom of the card.

**Rule:** NEVER attempt to layer an invisible Streamlit button over HTML/Markdown content to fake a clickable area. Do not try to strip Streamlit's internal position: relative wrappers. The React DOM will always fight back and break the hitbox.

* **The "Native Button is the Card" Architecture:**

**Problem:** You need a large, visually rich UI card containing an icon/image, a primary title, and a sub-description, where 100% of the surface area is perfectly clickable and correctly triggers a Streamlit on_click callback without layout glitches.

**Solution:** Discard st.container and st.markdown wrappers entirely. Instantiate a raw, native st.button("Primary Title", key="my_card", use_container_width=True) and use highly targeted CSS to dress the native <button> DOM element in a "card suit".

**Implementation Rules:**

**The Base Component:** Instantiate only the native button. The string you pass to the button will act as the <h3> Primary Title.

**Image Injection (Base64):** Never use <img> tags. Inject your icons/images dynamically into the button's CSS background-image property using Base64 encoded strings. Use background-position and background-size to center the icon at the top of the button. 

**Independent image/Icon Layers (::before Hack):** * Problem: If you apply background-image directly to the <button> and want to make the icon monochrome/grayscale when inactive, applying filter: grayscale(100%) to the button will also turn the text and background grey!

**Rule:** Detach the icon from the button background. Give the button position: relative !important;. Then, create an independent layer using button::before { content: ""; position: absolute; ... }. Inject the Base64 image into the ::before element. You can now safely apply filter: grayscale(100%) opacity(50%) to the inactive ::before icon, and remove the filter on the active state, without affecting the button's text or background color.

**Dimensions & Flexbox:** Force the button to act as a card by setting a strict height (e.g., 140px !important). Use padding-top to push the primary title text down below the background image. Set display: flex; flex-direction: column; align-items: center;.

**Descriptions via Pseudo-Elements:** Streamlit buttons do not accept HTML subtitles. To add a description below the primary title, inject a CSS ::after pseudo-element attached to the button (e.g., content: "Matches Canvas Modules" !important; margin-top: 4px; color: #a0a0a0;).

**Dynamic Active States:** Use the specific widget key (div.st-key-my_card button) to apply standard hover states and dynamically inject Python f-string logic to apply an active border/background when the card matches the current st.session_state.

**Example CSS Skeleton for "Native Button is the Card":**

CSS
/* Base Card Styling */
div.st-key-my_custom_card button {
    height: 140px !important;
    background-color: transparent !important;
    background-image: url('data:image/png;base64,...') !important; /* Base64 Icon */
    background-repeat: no-repeat !important;
    background-position: center 15px !important;
    background-size: 64px !important;
    padding-top: 85px !important; /* Pushes text below image */
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 8px !important;
    display: flex !important;
    flex-direction: column !important;
}

/* Primary Title Formatting */
div.st-key-my_custom_card button p {
    font-size: 1.1rem !important;
    font-weight: 600 !important;
    color: #ffffff !important;
}

/* Sub-description Injection */
div.st-key-my_custom_card button::after {
    content: "Sub-description text goes here" !important;
    font-size: 0.85rem !important;
    color: #a0a0a0 !important;
}

#### 7. CSS-Based Disabled States (Streamlit Native API)
* **Native Selector Targeting:** Streamlit buttons and widgets apply a `disabled` attribute to the underlying `<button>` tag when `disabled=True` is passed to the Python function.
* **Rule:** Target `button[disabled]` natively within the parent keyed container CSS to handle dimming and interactivity locks for the entire "Card" unit:
```css
div[class*="st-key-btn_sec_org_"] button[disabled] {
    opacity: 0.4 !important;
    filter: grayscale(100%) !important;
    pointer-events: none !important;
}
```
* **Typography Stability:** Pair the native button dimming with a manual color toggle for the section label (e.g., using `#475569` for "Deep Dim" state) to maintain HTML structure while visually communicating a locked state.

***
#### 8. CSS Injection Ordering & DOM Render Ghosting (The React Sub-frame Race Condition)

**Problem (The "Ghost Box" Interaction Flaw):**
During state-toggling UI interactions (e.g., clicking on a custom-masked `st.button` acting as an expansion chevron), the button briefly flashes a solid grey background for ~50-150ms. This looks like a CSS specificity failure or a `::focus-visible` ring piercing the CSS.

**The Execution Architecture Failure:**
We attempted to solve this by aggressively targeting Streamlit's inner BaseWeb elements (`span.ripple`, `div[data-testid="stMarkdownContainer"]`, `button:active`, `[disabled]`) with `all: unset !important;` and `display: none !important;`. The "Nuclear Option" failed. It failed because **the CSS does not exist in the DOM** when the button renders. 

Streamlit's Python-to-React translation reads sequentially top-to-bottom. If your dynamic CSS styling relies on the `st.session_state` of the button, and you inject the `<style>` block *after* the `st.button` declaration:
1. User clicks the button.
2. The Streamlit Engine triggers a full page Rerun.
3. React enters DOM Reconciliation.
4. Python executes `st.button("Toggle")` -> Sends raw unstyled BaseWeb button JSON to React.
5. React mounts the bare button to the DOM. **(The Flash Event happens here)**. 
6. Python executes `css_blocks.append()` -> `st.markdown("<style>")`.
7. React mounts the new `<style>` node into the `.element-container` below it.
8. The browser parses the CSS and snaps the button back to the correct custom mask and background color.

**Rule:** NEVER place dynamic CSS injections *below* the target elements they intend to style.

**Solution: "Static Hoisting" (Pre-Injection)**
All CSS overrides that structurally alter or mask Streamlit components must be hoisted and injected into the DOM **before** the component is instantiated in Python. 

1. **Calculate State First:** Run your boolean logic (e.g., `is_expanded = st.session_state.get('toggle')`) at the top of the logic block.
2. **Compute Colors Beforehand:** Derive your theme colors based on state (`c_base = "#f97316" if is_expanded else "#64748b"`).
3. **Inject the Containerized Style Block:** Call `st.markdown(f"<style>...</style>", unsafe_allow_html=True)`.
4. **Instantiate the Target:** *Then* execute the `st.button` or container.

With the CSS already loaded into the browser memory before React is asked to re-render the Native Button, there is a 0ms vulnerability window. The Rerun completely bypasses rendering the default styles and directly inherits the custom masks.

***
#### 9. The Modularized UI Architecture & CSS Strategy
* **God-File Teardown & Module Routing:** The original monolithic `app.py` has been decomposed. UI templates now strictly reside in the `ui/` directory (e.g., `ui/course_selector.py`, `ui/download_settings.py`, `ui/auth.py`). `app.py` handles route orchestration, session state initialization, and the global layout wrapper, while delegating all granular UI rendering to specialized functions imported from the `ui/` namespace.
* **Static vs Dynamic CSS Dual-Layer:** 
    * **Static CSS:** All static, structural CSS (base layout styles that do not rely on Python execution logic or `st.session_state`) has been extracted into physical `.css` files located in the `styles/` directory (e.g., `global.css`, `preset_dialogs.css`). It is injected globally via the custom `styles.inject_css('filename.css')` interface, which caches the CSS in memory (`_CSS_CACHE`) to bypass disk reads during Streamlit's rapid rerun loop.
    * **Dynamic CSS:** Any CSS that inherently requires Python context (like f-string evaluation for Theme colors, `st.session_state` boolean logic, or base-64 image strings) MUST remain inline inside the respective `ui/` module functions. It must be injected using `st.markdown(f'<style>...</style>', unsafe_allow_html=True)` and strictly abide by the "Static Hoisting" (Pre-Injection) rule described in Section 8.

#### 10. Custom Base64 Icon Workflow
* **The Problem:** Referencing external images directly via path in Streamlit CSS (e.g., `background-image: url('assets/icon.png')`) often fails in production because of the Streamlit static server routing and PyInstaller binary bundling. 
* **The Solution (Base64 CSS Injection):** All custom icons used inside our "Clickable Card" architecture (Section 6) must be injected as raw Base64 strings.
* **Implementation Workflow:**
    1. **Store Physical Assets:** Save your transparent `.png` or `.svg` icons in the project's root `assets/` folder.
    2. **Convert at Runtime:** Inside your UI module (e.g., `ui/download_settings.py`), import the centralized helper: `from ui_helpers import get_base64_image`.
    3. **Generate String:** `b64_icon = get_base64_image("assets/my_custom_icon.png")` (this helper automatically handles reading and `b64encode`).
    4. **Inject via F-String:** Embed the resulting string into your Python-generated `<style>` block: 
       ```python
       st.markdown(f'''
           <style>
           div.st-key-my_card button {{
               background-image: url('data:image/png;base64,{b64_icon}') !important;
           }}
           </style>
       ''', unsafe_allow_html=True)
       ```
    5. **Apply Image Filters:** To manage disabled or active states, use CSS `filter`, such as `filter: grayscale(100%) opacity(50%);`, rather than modifying the asset itself.
#### 11. The Button-Based Segmented Control & Container Key Bug
*   **The Container Key Generation Bug:**
    *   **Problem:** In this Streamlit version, calling `st.container(key="my_tray")` does *not* reliably generate a corresponding `st-key-my_tray` class in the DOM unless the container is "active" in some way (like having a border). This makes it impossible to target the outer tray for background/radius styling via CSS.
    *   **Rule:** To guarantee CSS-targetability for a container, always use `st.container(border=True, key="...")`.
    *   **Solution (The "Border Strip" Trick):** Immediately strip the unwanted native Streamlit border and padding in your hoisted CSS:
        ```css
        div[class*="st-key-my_tray"] {
            border: none !important; /* Strips native Streamlit border */
            padding: 4px !important;  /* Apply custom tray padding */
            background: rgba(0,0,0,0.25) !important;
            border-radius: 12px !important;
            max-width: 380px !important; /* Prevents full-width stretch */
        }
        ```

*   **Segmented Button Architecture (Better than `st.radio`):**
    *   **Problem:** Native `st.radio` has a rigid DOM structure that is extremely difficult to style as a premium segmented control (e.g., adding icons, custom active blue tints, or unequal column widths).
    *   **Architecture:** Use `st.columns` inside a keyed container, and render standard `st.button` widgets in each column. Use an `on_click` callback to update the active state in `st.session_state`.
    *   **Rule:** Always use "Static Hoisting" (Section 8) to inject the button's background-image (icons) and active-state colors *before* the buttons are rendered. This prevents the "Grey Flash" when React re-renders the buttons during a state-toggle rerun.
    *   **Icon Injection (Data URIs):** Inject SVG or PNG icons directly into the button's `background-image` property using data URIs. Use `padding-left: 40px !important` or similar to push the button text away from the icon.
        ```css
        div[class*="st-key-btn_fav_favorites"] button {
            background-image: url("data:image/svg+xml,...") !important;
            background-repeat: no-repeat !important;
            background-position: 14px center !important;
            background-size: 18px !important;
        }
        ```
    *   **Active State Identification:** Since individual buttons stay in the DOM, targeting "the currently active" button requires passing a dynamic key to the button that includes the active state name, or using a specific class-prefix targeting the active button's key. 
        ```python
        # In Python:
        st.button("Label", key=f"btn_{mode}_{namespace}")
        # In CSS (Hoisted):
        div.st-key-btn_{active_mode}_{namespace} button {
            background-color: rgba(56, 189, 248, 0.1) !important;
            border-color: rgba(56,189,248,0.3) !important;
            color: #ffffff !important;
        }
        ```
