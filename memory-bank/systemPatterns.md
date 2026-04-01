# System Patterns: Canvas Downloader

## Core Architecture
Modular design centered around Streamlit for UI and CanvasAPI for backend communication.

### File Structure
- **`app.py`**: Main entry point, UI controller.
- **`sync_ui.py`**: All sync-related UI logic.
- **`ui_helpers.py`**: Shared UI utilities (disk check, path utils).
- **`canvas_logic.py`**: Canvas API interactions.
- **`sync_manager.py`**: Sync backend (SQLite manifest, MD5 hashing, analysis engine).
- **`excel_converter.py`**: Excel to PDF conversion utility (Win32COM + AppleScript).

## Temp File Shadowing (Win32 MAX_PATH Bypass)
- **Pattern**: `office_safe_path(original_path)` context manager in `ui_helpers.py`.
- **Policy**: Office COM APIs hard-crash on paths ≥255 chars. Shadow long paths into `%TEMP%` with short UUID names, yield safe paths, move results back on exit.
- **Threshold**: 240 characters (15-char safety margin). Short paths pass through at zero cost.
- **Ghost PDF Guard**: Exit block checks `temp_pdf.exists()` before `shutil.move()`. If COM crashed, no orphaned ghost file is created at the destination.
- **Cleanup**: `temp_source.unlink(missing_ok=True)` in `finally` block — always runs.
- **Injection Points**: `pdf_converter.py`, `word_converter.py`, `excel_converter.py` — Windows COM blocks only. macOS AppleScript branches are never touched.
- **Yields**: 3-tuple `(safe_source, safe_pdf, original_pdf)` — converters use first two for COM, third for return value.

## ZIP Encoding (Mojibake Fix)
- **Pattern**: `archive_extractor.py` uses Python-version-aware UTF-8 decoding for ZIP entry filenames.
- **Policy**: Python's `zipfile` defaults to CP437 for filenames when the UTF-8 flag (bit 11) is not set, mangling non-ASCII characters.
- **Python 3.11+**: Uses native `metadata_encoding='utf-8'` parameter.
- **Python <3.11**: Iterates `infolist()`, re-decodes CP437→UTF-8 for entries without the flag, passes mutated members list to `extractall(path=..., members=mutated_members)`.

- **Dual-Engine Automation Bridge**:
    - *Policy*: Achieve 100% feature parity between Windows and macOS without disabling features on UNIX.
    - *Implementation*: Office converters (`word`, `excel`, `pdf`) use a dynamic `if sys.platform == 'darwin':` branch inside their `convert()` methods. Windows uses `win32com` with self-healing. macOS uses `subprocess.run(['osascript'])` to inject AppleScript payloads directly into the local Mac Office applications.
    - *Excel COM Scalar Trap*: `sheet.UsedRange.Value` returns a 2D tuple for standard sheets, but if exactly 1 cell contains data, it returns a primitive scalar. Extractors must dynamically coerce scalars via `isinstance()` checks to prevent iteration crashes.
    - *AppleScript Native CSV Extraction*: When automating Mac Office, explicitly avoid AppleScript string concatenation loops (`set cellVal to string value...`) as internal line-breaks (`\r` or `\n`) within cells will fatally destroy tabular row alignment. Instead, command Excel to natively `save as active sheet ... file format CSV file format` to a secure temp directory, and let python parse the perfectly formatted output.
- **Native Cocoa Rendering Parity**:
    - *Policy*: Where Tkinter's cross-platform bridges fail to mimic native macOS expectations (crashes, ugly UI), bypass Tkinter entirely via subprocess AppleScript execution.
    - *Implementation*: `native_folder_picker()` on macOS pipes straight to `osascript -e POSIX path of (choose folder)` to leverage the actual macOS Finder dialog. Also, `open_folder()` leverages `open -R {path}` and an explicit `tell application "Finder" to activate` to guarantee the explorer window punches through Streamlit to seize the foreground.
- **Windows PyInstaller Native Dialogue Parity**:
    - *Policy*: Avoid using `tkinter` in Streamlit applications when compiled via PyInstaller, as invoking it outside the main thread frequently causes application segfaults.
    - *Implementation*: `native_folder_picker()` on Windows uses a `subprocess.run` to spawn `powershell -Command` loading `System.Windows.Forms.FolderBrowserDialog`. This perfectly natively executes the Windows folder picker in a totally isolated OS process, ensuring the Streamlit background runner never hangs or crashes.
- **AppleScript Lifecycle Controller Parity (macOS)**:
    - *Policy*: Avoid terminal-bound infinite loops or unstable Tkinter root windows to manage the application lifecycle on macOS.
    - *Implementation*: The `start.py` launcher uses a synchronous `osascript` dialog ("Open Browser", "Stop Server") executed via `subprocess.run()`. This acts as a native blocking controller for the `os.urandom` daemon thread, keeping the Streamlit server alive while allowing a graceful, user-friendly shutdown without zombie processes.
- **AppleScript Defensive Execution**:
    - *Pattern*: `osascript` subprocesses are strictly wrapped with `timeout=120` to guarantee the main Python async pipeline cannot freeze if the Mac Office GUI throws a blocking "Recover Document" or "Update Links" modal.
    - *Path Formatting*: AppleScript blocks natively accept `POSIX file "/Users/..."` strings. Paths are escaped (`path.replace('"', '\\"')`) for injection defense-in-depth.
- **Code-Signing Bundle Safety**:
    - *Policy*: Persistent settings files (`.json`) must never be written relative to `app.py` when compiled as a macOS `.app` bundle, as the `Contents/MacOS/` directory is code-signed and read-only.
    - *Implementation*: `ui_helpers.get_config_dir()` detects `sys.frozen` + `Darwin` and automatically routes database/JSON writes to the strictly writable `~/Library/Application Support/CanvasDownloader/` user domain.
- **Platform-Guarded Dependencies**:
    - *Pattern*: Windows-exclusive wheels like `pywin32` are constrained in `requirements.txt` via environment markers (`pywin32==308; sys_platform == 'win32'`), allowing a single universal requirements file to build cleanly on both operating systems.

## Security & State Patterns
- **Hybrid OS-Native Credential Storage (`keyring` & Obfuscated JSON)**: 
    - *Policy*: Never store sensitive API tokens in plaintext files (JSON/YAML) unless operating system UX constraints demand an explicit fallback.
    - *Implementation*: On Windows (`nt`), use Python's `keyring` module to securely delegate token storage to the Windows Credential Manager. On macOS (`Darwin`), `keyring` triggers repeated blocking "Keychain Access" UI modals for unsigned Python apps. Therefore, macOS explicitly pivots to Base64-encoded token storage alongside standard settings in JSON to guarantee a seamless, zero-prompt UX.
- **Defensive Exception Handling**:
    - *Policy*: Never use bare `except:` clauses.
    - *Implementation*: Always catch `Exception` explicitly (`except Exception as e:`) to prevent silently dropping vital OS-level interrupts like `KeyboardInterrupt` or `SystemExit`.
- **Atomic Config Serialization (The `.tmp` Swap Pattern)**:
    - *Problem*: Directly utilizing `json.dump(f)` to write user configurations or sync contracts is prone to disk tearing if the overarching Streamlit thread crashes, restarts, or is terminated mid-write, resulting in permanent `JSONDecodeError`s.
    - *Implementation*: Configuration operations mathematically enforce atomicity by dumping to a named `.tmp` file, calling `f.flush()` and `os.fsync(f.fileno())` to guarantee disk saturation, and finally utilizing `os.replace(temp, final)` for a perfectly instantaneous, uninterruptible OS-level swap.
- **Atomic File Writing vs Concurrent Thread Locks (JSON TOCTOU)**:
    - *Problem*: While writing to a `.tmp` file and using `os.replace` guarantees the file on disk isn't corrupted (Disk Tearing), doing so during a concurrent Read-Modify-Write cycle without a `threading.Lock` still causes TOCTOU (Time-Of-Check-To-Time-Of-Update) data loss. Furthermore, passing a stale, pre-read monolithic memory state (`st.session_state`) into the lock completely defeats the mutex.
    - *Implementation (Signature-Based Modifiers)*: Ensure the wrapper (e.g., `atomic_update(modifier_func)`) accepts a callable that modifies freshly read data *inside* the lock. Rip out monolithic state saves. Migrate to granular operations (`_add_pair`, `_remove_pairs_by_signature`) that mutate the fresh JSON array matched by a strict unique signature (`course_id` + `local_folder`) rather than volatile list indices. Finally, synchronously rehydrate the application state with the wrapper's exact return value.
- **Pipeline Interruption Guards (Cancellation Flow)**:
    - *Problem*: Long-running pipelines (like post-processing conversions) that trigger automatically after a primary task (like downloading) are vulnerable to "Execution Leakage" if the user cancels during the primary task. If the secondary pipeline lacks explicit cancellation guards, it may trigger on a partial or aborted state, leading to "Overkill" loops or processing of half-downloaded files.
    - *Implementation*: Enforce a strict "Pre-Flight Interruption Check" before every major pipeline transition. In `app.py`, the `run_all_conversions` sequence is explicitly guarded by `not st.session_state.get('cancel_requested')` and `not st.session_state.get('download_cancelled')`. This ensures that an aborted download terminates the entire logic tree instantly, rather than falling through to the next phase.

## Concurrency, Async & Subprocess Patterns
- **Active Subprocess ThreadPool Management**:
    - *Problem*: Utilizing the synchronous `with ThreadPoolExecutor() as pool:` context manager blocks the executing thread unconditionally on `__exit__`. If the spawned task interacts with misbehaving native subprocesses (e.g., FFmpeg grinding on corrupted MP4s), the top-level Python controller thread will hang indefinitely even if a `timeout=` is caught on the `Future.result()`.
    - *Implementation*: Abandon the `with` context pattern. Initialize the `pool` manually, capture the `TimeoutError`, and rigorously enforce termination inside a `finally` block using `pool.shutdown(wait=False, cancel_futures=True)`. This cleanly severs Python's blocking relationship with the zombie child process.
- **Semaphore Exemption (Slot Yielding)**:
    - *Problem*: Executing an `asyncio.sleep()` exponential backoff penalty (e.g., waiting 60 seconds after a 429 Rate Limit) *inside* the `async with semaphore:` block inherently holds that concurrency slot hostage, draining the application's ability to process other healthy files.
    - *Implementation*: Eject sleep mechanisms outside the semaphore's scope. HTTP 429 endpoints instantly raise a custom exception that is caught in the outer retry wrapper, releasing the semaphore before invoking the sleep penalty.
- **Dual-Layer Async Deduplication Locks**:
    - *Problem*: Two identical Canvas modules initiating high-speed downloads can breach pre-execution path deduplication checks if spanning happens concurrently. Both worker threads will instantly stream bytes to the identical `file.pdf.part` temp path, mutating data randomly or violently triggering OS `[WinError 32]` violations.
    - *Implementation*: Enact a Dictionary Mutex Pattern. A top-level global `_lock_mutex = asyncio.Lock()` guards access to a hash map (`_download_locks = {}`). Threads eagerly lookup or generate a unique `asyncio.Lock()` bound explicitly to their normalized target file path. The actual `.part` file download stream is then perfectly serialized behind that path-specific lock.
- **FFmpeg Zombie Process Pruning (`psutil`)**:
    - *Problem*: Simply dropping the Future from a `ThreadPoolExecutor` or calling `shutdown(wait=False, cancel_futures=True)` abandons the Python thread, but the underlying OS Process (FFmpeg) spawned by `moviepy` continues churning indefinitely in the background, locking files and burning RAM.
    - *Implementation*: Extract the parent PID and utilize `psutil.Process(pid).children(recursive=True)` inside a `timeout` handler. Explicitly send `.kill()` to every child process in the tree, guaranteeing complete execution halt.
- **Asyncio Lock Memory Leaks (Reference Counting)**:
    - *Problem*: Using a globally caching dictionary (`_locks[path] = asyncio.Lock()`) generates a permanent memory leak if the locks are never cleaned up after downloading thousands of files.
    - *Implementation*: Wrap the global dictionary interaction in an `@asynccontextmanager` utilizing reference counting (`"count": 0`). The lock is newly forged on count 1, incremented, used securely, and finally explicitly `del _locks[path]` when the reference count hits exactly 0.
- **Event Loop I/O Block Avoidance**:
    - *Problem*: Executing blocking synchronous routines (like `sqlite3` database commits or massive JSON writes) directly inside an `async def` function completely stalls the overarching `asyncio` event loop.
    - *Implementation*: Offload all heavy synchronous database and filesystem I/O into native background threads using `await asyncio.to_thread(func, *args)`.
- **Streamlit Async Context Safety (`safe_thread_wrapper`)**:
    - *Problem*: Asynchronous `asyncio.to_thread` calls lose the Streamlit `ScriptRunContext`, causing `StreamlitAPIException` when background threads attempt to access `st.session_state` or UI placeholders.
    - *Implementation*: Implement a `safe_thread_wrapper` using `streamlit.runtime.scriptrunner.add_script_run_ctx`. Capture the context in the main async thread via `get_script_run_ctx()` and inject it into the worker thread before dispatching. Ensure Streamlit-specific imports remain deferred inside the function for framework independence in `canvas_logic.py`.

## UI Architecture & Patterns
- **Modals**: Use **`st.dialog`** for complex isolated interactions.
- **Interactive Lists**: Use HTML `<details>` and `<summary>` inside modals to handle large file lists without overwhelming the main view.
- **Component Constriction**: Use fractional columns to limit component width on large screens.
- **Radio Widget Granular Tooltips Pattern**:
    - *Problem*: Streamlit's native `st.radio` component supports a single global `help` parameter, but does not allow tooltips on individual radio options, limiting complex contextual choices.
    - *Solution*: Avoid writing custom React components. Instead, inject a styled `st.markdown` HTML block directly beneath the radio component utilizing `ⓘ` icons, `font-size: 0.78rem`, `color: #6b7280`, and `line-height: 1.5` to visually mimic native Streamlit granular hint text per option.
- **Hitbox Margin Defeat Pattern**:
    - *Problem*: Pulling text labels tight against active UI widgets (checkboxes, radios) using aggressive `margin-bottom: -15px` causes the transparent DOM bounding box of the text `<p>` to overlay on top of the widget, physically blocking mouse clicks and creating "dead" unresponsive UI zones.
    - *Solution*: Never push negative bottom margins into interactive hitboxes. Instead, use a zero-bottom margin (`margin-bottom: 0px`) on the text label and construct tightness by actively pulling the *container* upward or utilizing negative top margins (`margin-top: -5px`) on non-interactive adjacent elements.
- **Design Token Centralization (`theme.py`)**:
    - *Problem*: Hardcoded hex colors (e.g., `#ffffff`, `#8A91A6`) scattered across UI files create maintenance debt and brittle aesthetic updates.
    - *Solution*: Extract all colors into a centralized `theme.py` module as semantic tokens (e.g., `theme.TEXT_PRIMARY`, `theme.BG_CARD`). Inject them into CSS blocks and HTML spans using standard f-strings (`f"color: {theme.ERROR};"`).
- **Strict HTML Escaping (`esc()`)**:
    - *Problem*: Passing raw user-controlled variables (Course Names, File Names, Error Messages) into `st.markdown(unsafe_allow_html=True)` immediately opens the application to XSS and DOM-corruption if a Canvas server returns payload strings containing `<script>` or unclosed HTML tags `</div>`.
    - *Solution*: Universally wrap all interpolated variables inside HTML structures with the custom `esc()` utility (from `ui_helpers.py`), which safely standardizes `html.escape` behavior across the codebase.
- **Zero-Indentation HTML String Pattern**:
    - Streamlit's markdown parser converts indented HTML strings into `<pre><code>` blocks.
    - *Robust Pattern*: Construct long HTML/CSS strings in Python without any leading indentation on the multi-line closing quotes/content to ensure they render as raw HTML.
- **Flex-box Hanging Indent Pattern**:
    - To support emojis + multi-line text:
    - Use `display: flex; align-items: flex-start;` on `<li>`.
    - Wrap the icon in a fixed-width `span` (e.g., `24px`).
    - Wrap the text in a `flex:1` `span` with `word-break: break-word`.
- **Keyed Container Scoping for CSS Overrides**:
    - *Problem*: Streamlit's default margins/paddings on `st.columns` and `st.container` are often too loose for dense data lists.
    - *Solution*: Wrap targeted loops in `st.container(key="some_key")`. 
    - Injected CSS then uses partial attribute selectors `div[class*="st-key-some_key"]` to target the internal `stHorizontalBlock` (columns) or `stVerticalBlock` without polluting the global scope or colliding with other keyed instances in loops.
- **Wildcard Attribute Selector for Dynamic Widgets**:
    - *Problem*: When widget keys are dynamic (e.g., `key=f"cat_new_{course.id}"`), standard class selectors like `.st-key-cat_new` fail.
    - *Solution*: Use CSS wildcard attribute selectors `div[class*="st-key-cat_new"]` to target all dynamically keyed containers that share a common prefix. This allows a single global CSS block to style many unique widgets simultaneously.
- **Progress Bar Visibility Pattern**:
    - For disk space checks: `min(100, max(1, real_pct))` if `bytes > 0`.
    - Pure linear mapping on high-capacity drives makes small downloads look like 0% (invisibility). Always implement a 1% floor for any non-zero sync size.
- **Dynamic File Selection Counting (CSS Ghost Text) Pattern**:
    - *Problem*: Expander titles in Streamlit are used as their internal state ID. If you inject dynamic numbers (e.g. `[1 / 5]`) directly into the Python string `st.expander()`, the ID changes on every rerun. This destroys the user's open/closed state, causing them to forcefully pop open or snap shut unexpectedly.
    - *Solution*: Revert the expander title to a purely static string (e.g., `st.expander("🆕 New files")`). Calculate the `selectedCount` dynamically via a list comprehension on `st.session_state`. Then, project that string onto the screen by injecting a targeted `<style>` block that uses the `::after` CSS pseudo-element on the expander's summary tag. Streamlit's reactive rerun model updates the CSS instantly without destroying the widget state constraint.
- **Margin Collapse Override (Scoped CSS)**:
    - *Problem*: Streamlit's internal layout often swallows HTML `<div style='height:Xpx'>` spacers due to margin collapsing or negative margins on nearby components.
    - *Solution*: Wrap the target component (e.g., a button row) in a keyed `st.container` and use scoped CSS with `!important` on the `margin-top` of the `.st-key-...` class to force the desired vertical break.
- **Aggressive Header Suction Pattern**:
    - *Problem*: Native Streamlit `###` headers have large default bottom margins that create excessive dead space.
    - *Solution*: Replace with custom HTML `<h3 style='margin-bottom: -25px;'>` to forcefully pull widgets up against the header. Adjust margin-bottom per widget type (e.g., -10px for deeper widgets, -25px for flat ones).
- **3-Column Card Layout (Horizontal Symmetry) Pattern**:
    - *Problem*: Multi-column layouts in Streamlit often look "jagged" if top-level widgets (like headers or different input types) have different vertical paddings, causing column borders and titles to start at disparate heights.
    - *Solution*: Negate native Streamlit container gaps by injecting a single, identical `st.markdown(<h3>...)` block at the absolute top of every column. By using custom HTML headers with negative bottom margins (`margin-bottom: -15px`), you lock every column to a shared horizontal baseline, creating a professional, symmetrical grid.
- **Callback & CSS Hoisting Pattern**:
    - *Problem*: Defining `@st.fragment` callback functions or `<style>` blocks inside `st.columns` or `st.container` blocks can cause Streamlit to unmount and re-re-render those elements when the parent container's state changes. This leads to "flapping" UI or lost widget focus.
    - *Solution*: Always hoist fragments, callbacks, and CSS definitions to the absolute top of the parent render function, *before* any layout containers (`columns`, `tabs`, `expanders`) are instantiated. This ensures the logic and styling remain stable regardless of the layout's internal branch mutations.
- **Dialog Function Global Hoisting (`@st.dialog`)**:
    - *Problem*: If a dialog function is defined structurally inside an `if st.session_state['step'] == 1:` block, it effectively ceases to exist in the global Python namespace when the UI advances to `elif step == 2:`, crashing the application when a Step 2 button attempts to invoke the modal.
    - *Solution*: Dialog definitions (`def _my_dialog():`) decorated with `@st.dialog` must be hoisted to the absolute top of the parent container wrapper (before any step-routing logical branches). This ensures they are compiled and accessible universally regardless of the user's current progression in the wizard.
- **Dialog Full-Scope Rerun (`st.rerun(scope="app")`)**:
    - *Problem*: When an action inside a dialog mutates the core `st.session_state` (like Applying a Preset), a standard `st.rerun()` only restarts the modal fragment itself. The underlying parent page remains completely visually stale until the user manually clicks away or closes the modal.
    - *Solution*: Use `st.rerun(scope="app")` paired with a `try/except TypeError` fallback (for older Streamlit versions). This guarantees the modal is violently destroyed and the entire native application tree re-renders from the top using the newly injected state variables.
- **The Ghost Toast Pattern (Pending Toasts)**:
    - *Problem*: `st.toast()` notifications fired inside a dialog immediately disappear if the next line of code runs an `st.rerun(scope="app")`, because the modal container they were bound to is instantly destroyed.
    - *Solution*: Do not call `st.toast` inside the dialog. Instead, inject the message into `st.session_state['pending_toast'] = "✅ Success"`. At the absolute top of the target page's layout block (e.g. `Step 2`), write a consumer: `if 'pending_toast' in session_state: st.toast(session_state.pop('pending_toast'))`. The toast will now cleanly render precisely as the dialog drops and the main page refreshes.
- **Merged CSS/HTML Injection Pattern**:
    - *Problem*: Separate `st.markdown` calls for `<style>` and HTML headers create multiple hidden Streamlit wrapper `divs`, each adding extra vertical padding.
    - *Solution*: Bundle the CSS `<style>` block and the HTML `<h3>` tag into a *single* `st.markdown(unsafe_allow_html=True)` call to minimize div overhead.
- **The "Trojan Horse" CSS Selector Pattern**:
    - *Problem*: Streamlit's internal DOM refactoring (especially in version 1.51.0+) frequently strips or renames the wrapper classes (`stVerticalBlockBorderWrapper`, etc.) that developers rely on for targeting containers with custom CSS. Even explicit `st-key` classes can be moved or stripped by the rendering engine.
    - *Solution*: Plant a custom, developer-controlled CSS class (a "Trojan Horse") inside an injected HTML block (e.g., `<div class='step-2-card-target'>...</div>`).
    - *Selector Architecture*: Use the modern CSS `:has()` pseudo-class to target the high-level Streamlit container that contains the Trojan class: `div[data-testid="stContainer"]:has(.step-2-card-target)`. This effectively anchors the styling to a stable, identifiable element within the content, allowing for robust application-level overrides regardless of Streamlit's internal structural shifts.
- **Bordered Container Height Synchronization (The Flex Bottleneck)**:
    - *Problem*: When placing `st.container(border=True, key="my_card")` elements side-by-side in `st.columns`, they will not stretch to match each other's height dynamically if one expands. Unlike standard columns, the `stHorizontalBlock` stretches, but Streamlit injects an `stLayoutWrapper` parent around your keyed card with `flex: 0 1 auto`, which acts as a hard bottleneck blocking vertical growth.
    - *Anti-Pattern*: Do NOT use JS components or `MutationObserver` to sync heights (Streamlit's React engine will fight it and cause infinite loops). Do NOT assume there is an inner `stContainer` (in Streamlit 1.51+, the `st.container(border=True)` renders the keyed `stVerticalBlock` *as* the bordered container itself).
    - *Solution*: Apply a two-tier CSS flex-chain targeting exactly the bottlenecks identified, combined with an established "Baseline Height" for static cards (e.g., **185px** for Card 1 buttons) to ensure cards start flush and grow in lockstep.
      ```css
      /* Tier 1: Force the stLayoutWrapper bottleneck to grow */
      div[data-testid="stLayoutWrapper"]:has(> [class*="st-key-my_card"]) { flex: 1 !important; }
      /* Tier 2: Ensure the keyed card fills the new space */
      div[class*="st-key-my_card"] { flex: 1 !important; }
      ```
- **CSS-Based Disabled States (Streamlit Native API)**:
    - *Problem*: When a widget like `st_segmented_control` or `st.button` is disabled via the `disabled=True` attribute, Streamlit applies its own internal dimming, but custom parent card styling (backgrounds, icons, etc.) remains fully bright, creating a "Functional but not Visual" disabled state.
    - *Solution*: Target the `button[disabled]` selector natively within the keyed container CSS. Apply `opacity: 0.4`, `filter: grayscale(100%)`, and `pointer-events: none` to the entire card unit. Combine this with a session-state-driven color toggle for adjacent label text (`:gray` or `#475569`) to ensure the entire card region is visually locked.
- **Filter-Position Containment Pattern**:
    - *Problem*: Applying a CSS `filter` (e.g., `grayscale(60%)`) to a parent container causes the browser to create a new "containing block" for all absolutely positioned children. If the filter is removed on hover (`filter: none`), the containing block is destroyed, causing `absolute` children to lose their anchor and jump to the next `relative` ancestor.
    - *Solution*: Always explicitly declare `position: relative !important;` on any container that uses CSS filters and houses absolutely positioned pseudo-elements (like radio buttons). This forces the anchor to remain locked to the container regardless of filter state changes.
- **Inset Box-Shadow Border Pattern (Geometric Lockdown)**:
    - *Problem*: Increasing `border-width` (e.g., 1px to 2px) on hover/active states physically changes the element's dimensions or shrinks its `padding-box`, causing layout shifts or displacing absolute coordinates.
    - *Solution*: Keep the physical `border-width` constant (e.g., `1px solid`). To achieve a "thick" visual effect for active states, apply an `inset box-shadow`: `box-shadow: inset 0 0 0 1px {color} !important;`. This draws the "border" inward over the background without affecting the CSS Box Model or displacing child element anchors.
- **CSS `:has()` Depth Limits**:
    - *Problem*: Attempting to build deep ancestor selectors like `div:has(> div > div > [class*="st-key-my_card"])` to map Streamlit's wrapper maze often fails instantly (returning `NO MATCH`) because browser CSS engines struggle with deeply nested `:has()` pseudo-classes attached to partial attribute selectors.
    - *Rule*: Never guess Streamlit wrapper depths. Use direct `parent:has(> child)` CSS selectors targeting precisely the DOM bottleneck.

- **SVG Alpha Mask "Cutout" Indicator Pattern**:
    - *Problem*: Standard solid-colored icons can feel visually heavy and don't react to background color changes.
    - *Solution*: Use an SVG mask featuring a transparent "cutout" of the check/radio dot. The indicator background fills the container, but the icon itself is a hole that reveals the underlying card's background.
    - *Aesthetic*: Ensures the checkmark/dot always has perfect contrast and changes "color" dynamically as the card background shifts during hover or activation.
- **Checkbox-to-Radio Visual Distinction Pattern**:
    - *Problem*: Streamlit doesn't distinguish between single-select and multi-select cards visually when using styled buttons.
    - *Solution*: Enforce strict geometric consistency:
        - **Multi-select**: Square indicators (`border-radius: 2px`).
        - **Mutually Exclusive**: Circular indicators (`border-radius: 50%`).
    - *Implementation*: Use `::before` for the indicator box and `mask-image` for the inner icon (check vs dot).

### Native Button Card Architecture
To ensure 100% click reliability across the entire card surface, we style native `st.button` widgets into cards.

#### 1. Wildcard Header/Styling
When managing multiple related buttons (e.g., Conversion Settings), use a wildcard CSS selector based on the button key prefix:
```css
div[class*="st-key-btn_convert_"] button {
    /* Base card styles */
}
```
This ensures that any button starting with `btn_convert_` (including the `master` toggle) inherits the same foundation, while specific overrides can be applied via full key matches.

#### 2. Selective Icon Sizing
For complex grids where a "Master" button is used alongside "Sub" buttons, apply different icon scales for visual hierarchy:
- **Sub-buttons**: 30px (e.g., `div[class*="st-key-btn_convert_sub_"]`) for maximum clarity in 4-column grids.
- **Master-button**: 24px (e.g., `div[class*="st-key-btn_convert_master"]`) to prevent the icon from overwhelming the larger card container.

#### 3. Idempotent State Callbacks
UI toggles must use idempotent callbacks to synchronize master/sub states:
- **Master Callback**: Evaluates current state to decide whether to turn "All On" or "All Off".
- **Sub Callback**: Toggles the individual state and then checks if the master toggle needs to be synchronized (e.g., if all sub-states are now `True`, set master to `True`).
- **Initialization Guard**: All `st.session_state` keys must be explicitly initialized before UI rendering to prevents `KeyError` during callback execution.
    - *Problem*: Streamlit's nested DOM wrappers and flexbox layout make absolute positioning or "invisible overlay" hacks for card-wide clickability extremely brittle and prone to failure across different browser sizes or Streamlit versions.
    - *Solution*: Style the native `st.button` widget to *become* the card. This ensures that the entire rectangular area is natively clickable.
    - *Technique*:
        1. Inject CSS targeting the button's key-based wrapper (e.g., `div[class*="st-key-btn_org_"] button`).
        2. Set `height`, `background-color`, `border`, etc.
        3. Use `background-image` with Base64 SVGs/PNGs for icons.
        4. Use `::after` pseudo-elements for secondary descriptions.
        5. Use `padding-top` to shift the native button label (the `<p>` tag) down to accommodate the icon.
        6. Dynamic active state styling using f-strings in the CSS block to inject the active button's key and theme colors.
- **First-Render Checkbox Hydration Pattern**:
    - *Problem*: In Streamlit, manually stuffing values into `st.session_state["my_checkbox"]` *before* the script reaches the `st.checkbox("Label", key="my_checkbox")` declaration often fails to visually check the box on its very first render. The UI appears unchecked (flashing), even though the underlying state dictionary reads `True`.
    - *Solution*: For dynamically populated configurations (like loading saved JSON settings from SQLite), always explicitly define the `value=` parameter falling back to the state key: `st.checkbox("Label", key="my_key", value=st.session_state.get("my_key", False))`. This guarantees 100% visual parity on the initial draw frame without triggering duplicate state assignment warnings.
- **Extreme Column Ratio Alignment Pattern**:
    - *Problem*: Default `st.columns(2)` splits are too wide for small buttons, pushing dependent content too far right.
    - *Solution*: Use extreme ratios like `[1, 6]` or `[1.2, 8.8]` to crush the trigger-widget's column, pulling the main input field horizontally into a tight layout.
- **Dynamic Master/Sub Syncing Pattern**:
    - *Problem*: Binary master toggles don't reflect how many sub-options are active.
    - *Solution*: Use a `TOTAL_SUBS` constant and calculate `active_subs = sum([...])` on every rerun. Use an f-string label for the master checkbox: `f"Master Label :gray[({active_subs}/{TOTAL_SUBS})]"` to provide real-time mathematical feedback.
- **Sniper Retry UI Bypassing**:
    - *Problem*: Retrying failed downloads forces a full multi-minute Canvas analysis phase.
    - *Solution*: Manually bridge Streamlit states on button click (`download_status = 'running'`), zero out success/fail counters, but leave `courses_to_download` and `files_to_download` cached variables intact. This seamlessly fast-forwards the UI directly back into execution mode.
- **Zero-Files UX Exit Ramp Pattern**:
    - *Problem*: When a user manually ignores the remainder of an execution payload (or the engine naturally diffs out all files), rendering a red `st.error` alert and blocking progress creates a UX dead-end that feels like a failure.
    - *Solution*: Intercept `total_active_files == 0` loops and render a celebratory `st.success` message. Replace the disabled actionable loops with a primary `st.button` ("Return to Front Page") that safely executes `_cleanup_sync_state()` and routes vertically via `st.rerun()`.
- **Safe Fragment Toast Pattern**:
    - *Problem*: Calling `st.toast()` or rendering other UI elements directly inside an `on_click` callback attached to an `@st.dialog` (fragment) causes Streamlit to crash and wipe the DOM, throwing a `Fragment rerun was triggered with a callback that displays elements` warning.
    - *Solution*: Extract UI commands from the callback. Instead, set a scoped session state string (e.g., `st.session_state['pending_dialog_toast'] = "Success"`). Consume that state variable by running `if 'pending_dialog_toast' in st.session_state: st.toast(st.session_state.pop(...))` at the exact top of the dialog's python function body so the toast fires naturally during the fragment's refresh cycle.
- **Supercharged Fragment Close Pattern & Native Hiding**:
    - *Problem*: Closing a `@st.dialog` fragment (either natively or via standard `st.rerun()`) only unmounts the modal context; the main application UI behind the modal remains completely frozen in its previous state until the user interacts with it, leaving things like save buttons stale.
    - *Solution*: Upgrade custom routing "Close" buttons inside the dialog to execute `st.rerun(scope="app")`. This tears down the fragment and forces a top-to-bottom paint of the main application. To ensure users don't bypass this fix, universally inject `div[data-testid="stDialog"] button[aria-label="Close"] { display: none !important; }` in CSS to hide the native Streamlit 'X', forcing interaction with the state-aware button.
- **The CSS `{{` Escaping Trap**:
    - *Problem*: In Streamlit, if you put `{{` and `}}` in a raw `st.markdown(""" ... """)` string to escape the braces, they render identically as literal `{{` into the HTML DOM, breaking all CSS inside the block because standard browser CSS only accepts single `{`. Conversely, if you use an f-string `st.markdown(f"""...{theme.ERROR}...""")`, you *must* double bracket `{{` for raw CSS blocks, otherwise python throws a `KeyError`.
    - *Solution*: Strictly separate raw static CSS from dynamic variable-injected CSS. Create two distinct `st.markdown` blocks: one plain string using standard `{` brackets, and one `f`-string block that safely uses `{{` and accepts dynamic `{variables}`. This guarantees that all styling applies successfully.
- **Base64 Tab/Button Icon Pattern**:
    - *Problem*: Native `st.tabs` or `st.button` lack support for embedding rich image assets alongside the text label without fragile and complex DOM manipulation.
    - *Solution*: Convert image assets to Base64 via `get_base64_image()`. Target the exact widget's key-wrapper in CSS and inject the image via `background-image: url('data:image/png;base64,...');` onto the `::before` pseudo-element. Apply `position: absolute; left: 12px;` to properly anchor the icon independently of the button text.
- **Sniper Retry Sandboxing Pattern**:
    - *Problem*: "Success Amnesia" occurs when global session state variables (like `downloaded_items`) are reset for a retry, losing the context of the initial successful run.
    - *Solution*: Instantiate an isolated `retry_` sandbox in `st.session_state`. Bifurcate the UI progress callback (`update_ui`) to route increments to the sandbox if `download_status == 'isolated_retry'`. This keeps the global state immutable during the retry and allows for a "Synthesis" phase to merge results purely at the end of the operation.
- **Safe Property Extraction Pattern (The Serialization Trap)**:
    - *Problem*: Streamlit may serialize complex objects into dictionaries when stored in `session_state` across reruns. Subsequent dot-notation access (`err.course_name`) triggers an `AttributeError`.
    - *Solution*: Use a strict abstraction for property extraction: `getattr(obj, attr, None) if not isinstance(obj, dict) else obj.get(attr)`. This guarantees robustness across both object and dictionary representations, particularly critical in post-execution reconciliation loops.
- **Data/Presentation Layer Separation (Pathing)**:
    - *Problem*: Stripping file paths for a cleaner UI (e.g., displaying only the filename) at the storage level breaks downstream logic (like post-processing) that requires absolute paths to resolve file locations on disk.
    - *Solution*: Maintain a strict "Full Path Data Layer". Store the absolute, un-mutated `explicit_filepath` in session state dictionaries. High-level UI rendering functions (like `render_folder_cards`) should perform JIT (Just-In-Time) transformations using `Path(p).name` ONLY for the visual layer, never for the underlying state.
- **Structural Error Guard Pattern**:
    - *Problem*: Re-rendering a "Retry" button when only un-retriable errors persist (e.g., API 404s on course metadata, rather than missing files) creates an infinite UX loop where the user clicks "Retry" and nothing happens.
    - *Solution*: Pre-evaluate the error list for **retriability**. Implement a boolean guard (`has_retriable_errors`) that checks if any error possesses a valid `filepath` context. Conditionally hide the Retry button and render a "Full Rescan Required" warning if the guard fails.
- **Tuple Identity Fallback (O(1) Hash Map)**:
    - *Problem*: Advanced retry logic often uses O(1) dictionary maps to re-queue failed items. If the source items are raw database tuples (SQLite rows) rather than named objects, standard `getattr(id)` calls will fail.
    - *Solution*: Use a cascaded identity lookup: `getattr(item, 'id', getattr(item, 'canvas_file_id', item[0] if isinstance(item, tuple) else None))`. This ensures raw database results are handled with the same identity integrity as high-level API objects.

## Synchronous API Integration Patterns (Win32COM)
- **COM Application Context Managers**:
    - *Problem*: Cold-booting and tearing down instances of Excel, Word, or PowerPoint for *every single file* in a batch download creates massive CPU overhead and severely bottlenecks post-processing speed.
    - *Solution*: Refactored `pdf_converter.py`, `word_converter.py`, and `excel_converter.py` into Python Context Managers (`__enter__`, `__exit__`). The `with ConverterClass() as converter:` block strictly wraps the outside of the file processing loops. This guarantees the heavyweight COM application is initialized exactly once per batch and safely exits securely when the block completes.
- **Widget Cleanup Bypass via Button Hooks**:
    - *Problem*: Transitioning from a step with an active widget (e.g., a checkbox) to a new step destroys the widget and deletes its key from `st.session_state`.
    - *Solution*: Capture the widget's boolean state into a custom, non-widget `persistent_` session state key directly inside the `if st.button('Next'):` execution block, immediately before the app reruns.
- **UI Thread Flushing**:
    - *Problem*: Initiating heavy blocking synchronous calls (like `PowerPoint.Application.SaveAs`) immediately after rendering new Streamlit placeholders causes the backend to lock up before the frontend DOM has time to paint the new UI state.
    - *Solution*: Inject an explicit `time.sleep(0.2)` explicitly between rendering the loading UI and initiating the blocking COM thread to guarantee frontend synchronization.
- **Office 365 COM Visibility Bypass**:
    - *Problem*: Modern click-to-run Office 365 environments throw `Invalid request` exceptions when attempting to coerce `Application.Visible = False`.
    - *Solution*: Wrap visibility attribute coercions in a `try...except` block, allowing the COM script to fall back to a visible window state if security constraints prevent hidden execution.
- **Proactive COM Health Checks (`_is_alive`)**:
    - *Problem*: Repeatedly opening and closing files via headless COM often silently corrupts the RPC channel. The COM object reference (`self.app`) remains non-None, but the next `Workbooks.Open` command crashes.
    - *Solution*: Implement a lightweight method (`try: self.app.Version`) at the very start of the `convert()` loop. If the ping fails, immediately execute the self-healing routine (`Quit()` + `_init_app()`) *before* attempting the actual file conversion.
- **Headless COM Throttling**:
    - *Problem*: Sequential high-speed COM operations (`Open` -> `Export` -> `Close`) outpace the physical hardware spooler or thread release, destabilizing batch loops.
    - *Solution*: Explicitly inject small `time.sleep(0.3)` pauses between massive synchronous milestones (e.g., ExportAsFixedFormat) to give the application time to stabilize the thread.

## Database & Entity Organization Patterns
- **ID-Based Entity Isolation**:
    - *Pattern*: Never use human-readable Names (like Group Name or Course Name) as primary keys for editing or state mutation, as users frequently duplicate them (e.g., saving "Programming" as both a Group and a Standalone Pair).
    - *Implementation*: Utilize underlying system IDs (like `group_id` UUIDs or Canvas API `course_id`s) universally across all UI edit callbacks (e.g., `_save_inline_edit_cb`). This strictly scopes JSON database mutations mapping 1:1 to the exact container block manipulated, completely protecting sibling items sharing identical human-facing metadata from cross-contamination.

## NotebookLM Data Pipeline Patterns
  - **Excel to PDF (Tabular Integrity & Global Export)**:
    - *Pattern*: Unlike Word/PPT, Excel sheets are "infinite". To ensure LLM readability, the system modifies `PageSetup` to `FitToPagesWide = 1` and `FitToPagesTall = False`, while setting all margins to 0. 
    - *Anti-Pattern Avoidance*: Never attempt to select sheets via `ActiveWindow` or filter data via `WorksheetFunction.CountA(sheet.Cells)`. `ActiveWindow` crashes reliably in `Visible=False` environments, and `CountA` sweeps billions of cells causing guaranteed RPC timeouts. The cleanest strategy is to just export the entire workbook via `ExportAsFixedFormat(0)`—empty sheets will produce small harmless PDFs instead of crashing the batch pipeline.
- **Pure Deletion + Sync Engine Bypass**:
    - *Pattern Description*: For destructive conversions (like URL compilation and Archive extraction), we DO NOT use Ghost Stubs (`.extracted` files) to represent the missing source file.
    - *Problem*: Physical file deletion after automated conversion/extraction causes the standard Sync Engine to flag files as "Locally Deleted," triggering redundant re-downloads.
    - *Solution*: Delete the source file completely (Pure Deletion). To prevent re-downloads, we inject extension traps tied to the `sync_contract` inside `sync_manager.py` (specifically at Diffing Phase 1, Phase 2, and Step 5) to silently ignore the missing files. The original filepath remains untouched in the manifest database.
    - *Use Cases*: 
        - **Archives**: Prevents re-downloading large `.zip`/`.tar.gz` files after extraction without polluting the user's workspace with `.extracted` dummy files.
        - **URL Compiler**: Removes `.url`/`.webloc` files (which are unsupported by NotebookLM) while keeping the Sync Engine satisfied.
- **Top-of-Pipeline Extraction**:
    - *Pattern*: Always run Archive Extraction *before* any other post-processing hook (like HTML->MD or Code->TXT). This ensures files liberated from a student's ZIP folder are caught by the subsequent loops and format-shifted properly.
- **Manifest Translation**:
    - *Pattern*: When converting a file (e.g., `.pptx` to `.pdf`), the system updates the `local_path`, `original_size`, and `original_md5` in the database to match the new derivative file, but preserves the original `canvas_filename`. This effectively tricks the sync diffing engine into linking a remote PPTX to a local PDF for version control.

## Synchronization Strategy & Data Integrity
- **Performance-Safe Path Divergence & Dynamic Accounting**:
    - *Problem*: To prevent massive UI freezes before a download begins, the system must not execute hundreds of deep individual Canvas API queries (e.g., pulling every assignment's full description to find attachments) just to count files. However, if the sync engine skips these fetches, it fails to evaluate the true physical path structures of attachments, falsely flagging them as "Deleted on Canvas".
    - *Solution*: A strict boolean passthrough (`is_scanning_phase=True/False`) allows the UI (`app.py`) to bypass deep queries during the initial count. Later, as files download, they emit `'attachment'` progress hooks which dynamically increment `st.session_state['total_items']` to correct the denominator on the fly. The Sync Engine (`sync_ui.py`) uses `is_scanning_phase=False`, paying the API cost to map exact structural (`Assignments/Assignment Name/Attachment.pdf`) parity for accurate diffing.
- **Dynamic Disk Space Validation**:
    - *Problem*: Static disk space minimums (e.g., 1GB) allow massive 10GB+ sync payloads to pass validation and then crash midway through execution when the drive fills.
    - *Solution*: Replaced all static `min_free_gb` floor additions with a dynamic algorithm: `max(min_free_gb * 1024**3, required_bytes * 1.2)`. This unconditionally guarantees a 20% safety margin scaled directly against the calculated active payload.
- **Network Retry Resilience**:
    - *Problem*: Synchronous or zero-retry download loops permanently fail actionable files on receipt of a single transient HTTP 429, 500, or `TimeoutError`.
    - *Solution*: Wrapped all `aiohttp` download block core expressions (`session.get()`) in an explicit 5-retry loop. Implemented exponential backoff (`2^attempt` seconds) for 5xx and Network Errors, and explicitly extract and bind to the `Retry-After` header for 429 Rate Limits.
- **Format-Agnostic Shortcut Extraction**:
    - *Pattern*: Windows shortcut formats (`.url` INI files) and macOS shortcut formats (`.webloc` binary/XML plists) require radically different parsing engines.
    - *Implementation*: `url_compiler.py` uses branch-dependent `rglob` scanning (`*.url` vs `*.webloc`) and parses macOS plists natively via Python's `plistlib.load()`, merging both arbitrary OS formats into an identical NotebookLM text payload.
- **SQLite Manifest Tracking**: Stores metadata (ID, path, size, date) for 1:1 mapping.
- **Sync Run #0 (Download-to-Sync Handoff)**:
    - *Problem*: The initial Download engine (`canvas_logic.py`) merely wrote files to disk, bypassing the Sync DB. When the Sync tab later analyzed the folder, the manifest was empty, causing all files (even manually deleted ones) to appear as "New" rather than "Locally Deleted".
    - *Solution*: Threaded the `SyncManager` directly into the `canvas_logic.py` async download loop. Immediately after an atomic download succeeds, `sm.record_downloaded_file()` performs a direct SQLite write (bypassing the in-memory dictionary for thread/async safety). The chosen `download_mode` ('flat' or 'modules') is saved to the new `sync_metadata` table, ensuring the Sync engine inherits a perfect state replication (Sync Run #0) perfectly synchronized with the user's initial choices.
- **The Sync Contract (Persistent UI Configurations)**:
    - *Problem*: File format tracking (NotebookLM toggles) previously lived in ephemeral `session_state`, forcing users to remember and re-click options every time they synced.
    - *Solution*: Built a definitive UI/DB binding contract. The initial download dumps all `convert_*` flags and the `file_filter` array into a JSON text blob committed securely to the `sync_metadata` table under `sync_contract`. `Quick Sync All` flows universally query this SQLite blob before falling back to `session_state` defaults, mathematically guaranteeing deterministic post-processing environments from Run 1 to Run N.
- **Atomic Symbiosis Pattern**:
    - *Problem*: Crashes, immediate cancellations, or network failures during file downloads historically corrupted the SQLite manifest or left halfway-written files on disk, leading to "Cancel Ghosting" (0 files to sync on retry). Furthermore, destructive DB re-writes regularly wiped the `is_ignored` flag selected by users during previous reviews.
    - *Solution 1 (Zero-Amnesia Upserts)*: Eliminated bulk `DELETE FROM` query routines tracking the manifest. Reengineered scalar and bulk saves to exclusively utilize `INSERT INTO ... ON CONFLICT(canvas_file_id) DO UPDATE SET ...` while specifically excluding the `is_ignored` column from the excluded target block.
    - *Solution 2 (The `.part` Pattern)*: All active downloads append a `.part` extension to the filename during streaming. Cancel checks fire every 1MB chunk. If interrupted or cancelled, the `.part` file is unlinked. The file is only atomically renamed to its final extension upon 100% byte verification.
    - *Solution 3 (Semantic Purity Guards)*: DB commit loops (`save_manifest` and `_save_single_file_to_db`) strictly occur *after* all physical disk verification is complete, and are shielded by top-level execution guards (e.g., `if st.session_state.sync_cancelled: st.rerun()`) to ensure zero database mutations occur during a cancelled session.
- **ACID Transaction Shift (Delayed DB Commit)**: 
    - *Problem*: In synthetic entity loops (Assignments, Pages), the system previously executed `sync_manager.record_downloaded_file()` inside `_save_secondary_entity`. This committed the parent entity to SQLite *before* its associated file attachments were queued or saved. If the sync was cancelled or crashed during attachment processing, the parent remained marked "Downloaded", permanently orphaning its children on future runs ("Orphaned Attachment Amnesia").
    - *Implementation (Delayed Commit)*: Decoupled the DB commit from the leaf-level save function. `_save_secondary_entity` and `download_secondary_entity` now return a 4-tuple including the Canvas `updated_at` timestamp. The responsibility for the DB commit is shifted upward to the `_fetch_and_save_*` orchestrators (in Phase 1) or `sync_ui.py` (in Phase 2). The commit is manually triggered only *after* all attachments have been successfully injected into the asynchronous download queue or saved locally, ensuring 100% ACID compliance for complex entity trees.
- **Await-and-Inject Pattern (Sniper Retry ACID Integrity)**:
    - *Problem*: During "Sniper Retries" of failed secondary entities, blind `asyncio` queueing of the parent task leads to a race condition where the parent is committed to the manifest before its children are discovered or queued.
    - *Implementation*: The `download_isolated_batch_async` loop in `canvas_logic.py` executes a strict "Await-and-Inject" sequence for secondary items. It **awaits** the synchronous result of `download_secondary_entity` to ensure 100% discovery, performs an explicit **ACID Commit** to the manifest using the unpacked 4-tuple, and then **injects** attachment sub-tasks as fresh `asyncio.create_task` objects into the live execution list.
- **Negative ID Pattern & Offset Registry**: 
    - *Problem*: Synthetic shortcuts (Pages, ExternalUrls) and dynamic entities (Assignments, Quizzes, Discussions) need to be tracked in the SQLite manifest, but they don't possess traditional file IDs. Blindly assigning them negative IDs risks primary key collisions if multiple synthetic types share the same numerical space.
    - *Implementation*: Utilizes a massive `SECONDARY_ID_OFFSETS` registry in `sync_manager.py` that allocates 10-million wide ranges for each entity type (e.g., Module Items: 0 to -9.9M, Assignments: -10M to -19.9M, Syllabus: -20M to -29.9M). This mathematically eliminates namespace overlap.
- **Shortcut Bypass Logic**: `_is_canvas_newer()` in `sync_manager.py` explicitly returns `False` for `id < 0`. This bypasses unreliable module timestamps and forces the engine to rely on local existence checks.
- **Sync Engine Bypass Pattern (External Deletions / Conversions)**:
    - *Problem*: Features like "URL Compilation" require deleting original files (`.url`/`.webloc`) post-download to satisfy external requirements (like NotebookLM compatibility). Normally, this would trigger the Sync Engine to flag these files as "Locally Deleted," causing redundant re-downloads.
    - *Solution*: Instead of creating stubs, modify the Sync Engine to be feature-aware. If a specific conversion feature is enabled in the `sync_contract`, the engine's analysis loops (Phase 1, Phase 2, and Step 5) are injected with guard clauses that skip flagging the absence of those specific file types as a deletion.
    - *Extension Trap Guardrail*: Bypass logic must never rely on display names or API metadata (which can lack extensions). It must strictly check the `local_path` or `calc_path` suffix against the known shortcut extensions (`.url`, `.webloc`).
- **Merge-Append / State Hydration Pattern (Conversion Ledgers)**:
    - *Problem*: When converting multiple small items (shortcuts) into one master ledger file, a standard overwrite (`w`) destroys previous state during subsequent syncs because the original sources are physically deleted post-conversion.
    - *Solution*: Hydrate high-level state by reading the existing master file before scanning. Use a deduplication `set` (UTF-8 safe, stripped) to filter incoming duplicates. Use append mode (`a`) for new data while maintaining the physical teardown of all processed sources.
- **Sync Restoration Interception**: The download pipeline in `sync_ui.py` intercepts negative IDs and recreates `.url` or `.html` files locally using static templates rather than performing an HTTP GET.
- **URL Extraction Priority**: For synthetic shortcuts, `html_url` is prioritized over `external_url` to ensure LTI tools route through the Canvas wrapper for authentication.
- **Retry Identity Preservation (Hash Map Pattern)**:
    - *Problem*: In Streamlit, retrying a subset of items (e.g., from a "Failed" list) often loses the original object context (like custom flags or synthetic IDs) if the list only contains raw names or IDs. This causes "Update" retries to be demoted to "New" retries, losing versioning traits.
    - *Solution*: Use O(1) Dictionary Hash Maps to pre-index the original complex object lists before iterating over the failure list. Use `getattr(f, 'id', None)` or strict identity tuples as keys to "pluck" the original object back into the correct retry queue, guaranteeing that structured intent is preserved across the retry boundary.
- **Deduplication Strategy (Path vs API IDs)**:
    - *Problem*: Relying solely on Canvas API IDs (`file.id`) fails because identically named duplicate module items, synthetic pages, and LTI tools can carry different DB IDs (or negative ones) but resolve to the identical local filepath. If they enter the `asyncio` task queue simultaneously, both workers write to `duplicate_file.pdf.part`, causing fatal `[WinError 32]` access crashes.
    - *Solution*: Deduplication must *always* key off the computed, sanitized local path target (`target_folder / sanitize(filename)`) *before* generating async tasks.
- **Two-Layer Deduplication Safety (HTML & API)**:
    - *Problem*: Deduplicating file attachments across both an HTML body embedded link list and the Canvas API's official `attachments` array without double-downloading.
    - *Implementation*: A two-layer defense. First, `_extract_canvas_file_links()` uses an internal `seen_ids` set to deduplicate inline links within the HTML body itself. Second, every entity builder (e.g., Announcements, Assignments) explicitly loads the true positive Canvas IDs from the API attachments array into an `existing_att_ids` set *before* parsing the HTML, blocking any inline link whose ID is already known. No file can be yielded twice.
- **True Positive ID Attachment Handling**:
    - *Problem*: Attachments on Canvas Assignments or Announcements are real Canvas `File` objects. Forcing them to adopt synthetic negative IDs (derived from their parent Assignment ID) permanently breaks sync timestamp diffing and completely defeats local deduplication if the instructor also placed the exact same file in the actual "Files" directory.
    - *Solution*: Extract the true, positive `file.id` direct from the attachment metadata block. Send it directly into the standard `_download_file_async()` pipeline without mutation. Deduplication naturally deduplicates the byte-for-byte matches.
- **Analysis Engine**: Diffing Canvas vs Local Manifest vs Local Disk.
- **Path Determination**: `detect_structure()` must precede analysis to correctly calculate relative paths for "Flat" vs "Folders" modes.
- **Universal Secondary Handler**:
    - *Pattern*: `download_secondary_entity()` in `canvas_logic.py` serves as the single source of truth for both the initial download pipeline and the secondary sync loop, returning a standardized 3-tuple `(filepath, synthetic_id, attachments)`.
- **Sync Loop Attachment Offloading**:
    - *Problem*: Secondary entities (Assignments, Announcements) can contain real Canvas file attachments. Downloading these synchronously inside the HTML generation function blocks the Streamlit UI thread and breaks cancellation hooks.
    - *Solution*: Extract the metadata and return it to the caller. `sync_ui.py` then dynamically mints mock `CanvasFileInfo` objects with **positive** Canvas IDs and appends them directly back into the live `all_files` async queue. 
    - *Deduplication*: A hash set guard (`_queued_ids`) tracks existing IDs in the queue and updates mid-iteration to prevent double-downloading if a file appears twice in a document or was already queued by the main sync engine.
- **Synthetic Entity Sync Bypass**:
    - *Problem*: Generating HTML for secondary entities relies on dynamic API endpoints. Minor timestamp drift or regeneration on every sync causes the engine to endlessly flag freshly downloaded secondary content as "Updates Available".
    - *Solution*: `_is_canvas_newer()` explicitly returns `False` for all negative IDs. Since synthetic entities are reconstructed from live API data, timestamp-based diffing is unreliable; the engine relies solely on local existence and manual user override.
- **Sync Diffing for Deleted Target Subfolders**:
    - *Problem*: When a user locally deletes an entire secondary subfolder (like `Announcements/Week 1 Update/`), both the synthesized `.html` file and its nested attachments must be accurately flagged as "Locally Deleted".
    - *Implementation*: The local disk scanner bypasses them (`os.walk`), but the SQLite manifest lookup still finds their past records (both negative IDs for HTML and positive for attachments). Since `local_path.exists()` returns `False` and their `downloaded_at` is truthy, the diffing engine accurately routes both files to `AnalysisResult.locally_deleted_files`. 
- **Download Execution & Attachment Passback**:
    - *Pattern*: `download_secondary_entity` dynamically evaluates `has_attachments=bool(attachments)`. When True, `_save_secondary_entity` constructs the path as `Folder/Name/Name.html`, implicitly creating the parent subfolder via `Path.mkdir(parents=True, exist_ok=True)`. The function then passes the positive-ID `attachments` array back up to the caller so they can be injected into the main task queue, safely nesting inside the newly guaranteed directory.
- **Phase 1 & Step 5 Existence Guard Pattern**:
    - *Problem*: Sync engines often rely on remote API results to drive their analysis. If an API call is restricted or fails to return an entity, the engine may skip the local existence check, creating a "Black Hole" where locally deleted files go undetected.
    - *Solution*: Enforce an unconditional `Path.exists()` check at the top of every analysis loop. In Phase 1, verify existence before marking a file as "Seen." In the Step 5 deletion loop, prioritize the "Missing on Disk" check before any Canvas API guards. This guarantees local deletions are surfaced regardless of API availability.
- **SimpleNamespace Proxy Reconstruction Pattern**:
    - *Problem*: Redownloading locally-deleted synthetic entities (which don't have a direct URL and are generated via API) fails if they aren't present in the active Canvas file scan.
    - *Solution*: Use `types.SimpleNamespace` to reconstruct a proxy object from the SQLite manifest data. This lightweight proxy provides the required attributes (`id`, `filename`, etc.) to route the entity into the secondary generation pipeline while shielding it from the primary URL downloader, avoiding complex imports of internal data classes.

## Error Handling & Logging
- **Locked File Pruning**: Pre-filtering Canvas `File` objects for missing `url` attributes to prevent batch download crashes.
- **LTI/Media Catch**: Graceful reporting of restricted media streams via extension/URL inspection.
- **Centralized Logs**: `download_errors.txt` created in the workspace root.
- **Post-Processing Dual Logging Architecture**:
    - `canvas_debug.log_debug(message, debug_file)` — writes timestamped plain text to `debug_log.txt` (gated by Debug Mode toggle). The `debug_file` is `Path(save_dir) / "debug_log.txt"` or `None`.
    - `log_post_process_error(directory, filename, error_msg)` — inline helper defined in `app.py` that appends `[Post-Processing]`-tagged entries to `download_errors.txt` (always active on failures).
    - Every post-processing log message is mirrored to three destinations: `log_deque` (Streamlit terminal UI), `logger.info/error` (Python logging), and `log_debug` (debug file).
- **Two-Layer Error Deduplication**:
    - *Problem*: A single problematic LTI link appearing across multiple modules fails multiple times during identical scanning passes, flooding the UI terminal and `.txt` log with duplicate entries.
    - *Solution*: Implement unified signature verification (`f"{course}|{item}|{message}"`). 
      - **Layer 2 (State)**: Inside the Streamlit `update_ui` callback (`st.session_state['seen_error_sigs']`) to guard the accumulator list driving the frontend dashboard.
- **Strict Exception Handling**: Always use `except Exception:` instead of `except BaseException:`. Catching `BaseException` swallows `SystemExit` and `KeyboardInterrupt`, preventing PyInstaller and Streamlit execution loops from tearing down cleanly.
- **Defensive Lazy Importing**: When importing fragile C-extensions (like `psutil`) inside fallback or error-handler functions, always wrap them in `try: import psutil except ImportError:`. This prevents the error handler itself from crashing the host process if the dependency fails to load.
- **Blind 200 Guarding (Content-Type)**: Do not blindly trust `status == 200` for binary file downloads. Canvas LMS often returns 200 OK with `text/html` payloads containing server error messages. Always validate the response `Content-Type` against the expected file extension before opening a local `.part` file handler.

## UI Component Patterns
- **Un-Throttled Per-File Status Indicator**:
    - *Problem*: High-speed asynchronous download loops often exceed Streamlit's UI rerun budget (rerunning every 10ms for 100 small files would crash the browser). Throttling the *entire* UI block (e.g., `if time.time() - last_ui_update > 0.4:`) causes the "Currently downloading: filename" text to lag behind the terminal log.
    - *Solution*: Segregate heavy UI updates (progress bars, terminal logs, metrics) into a throttled block, but keep the per-file status text (`active_file_placeholder`) **outside** the throttle. This ensures the user receives instantaneous feedback on precisely which file is active while preserving overall browser performance.
- **Expander for Sub-Toggles**:
    - *Problem*: 8+ sub-checkboxes clutter the Step 2 UI and visually overwhelm the page.
    - *Solution*: Keep the master toggle (`notebooklm_master`) always visible, and nest all sub-checkboxes inside `st.expander(f"⚙️ Advanced Conversion Settings ({active}/{total})")`. The dynamic label updates on rerun. No custom CSS indentation needed — the expander provides natural visual hierarchy.
- **Sniper Retry UI Bypassing & Path Provisioning**:
    - *Problem*: Retrying failed downloads normally requires resetting the UI to the "scanning" state, forcing the user to wait multiple minutes while the app recursively rescans every Canvas module and folder just to rebuild the `files_to_download` queue. Furthermore, if the user manually deleted a folder *after* the initial failure, the sniper retry will crash with a `FileNotFoundError` as it attempts to write a file into a non-existent directory.
    - *Solution 1 (State Jump)*: Jump Streamlit directly back to the execution phase by surgically injecting `download_status = 'running'` (or `'isolated_retry'`). Preserve the existing `courses_to_download` and total metrics in `st.session_state`. Only zero out the success/fail counters. This fast-forwards the UI and skips the multi-minute analysis bottleneck.
    - *Solution 2 (State De-cluttering)*: On every "Retry Failed Items" click, explicitly reset `st.session_state['seen_error_sigs'] = set()`. This ensures that identical errors occurring during the retry are not suppressed by the session-wide deduplication filter.
    - *Solution 3 (Surgical Directory Guards)*: Inside the `download_isolated_batch_async` loop, always execute `Path(filepath.parent).mkdir(parents=True, exist_ok=True)` before initiating the download task for each item. This guarantees folder existence even if the environment was modified between the initial scan and the retry attempt.
    - *Solution 4 (Download Retry State Reset)*: The standard "Retry Failed Items" button safely sets `download_status = 'isolated_retry'` (ensuring the full dashboard renders without blanking) and defensively resets `cancel_requested = False`, `download_cancelled = False`, `retry_downloaded_items = 0`, and `retry_failed_items = 0`.
    - *Solution 5 (Sync Retry State Reset)*: The Sync Tab's "Retry Failed Downloads" button resets `sync_cancel_requested = False` and `sync_cancelled = False` while forcing `download_status = 'syncing'` and `step = 3`, perfectly re-routing the pipeline back into the execution phase with a clean slate.
