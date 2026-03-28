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
