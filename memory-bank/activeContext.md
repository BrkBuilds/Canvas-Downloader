# Active Context: Canvas Downloader

## Current Focus
- **Active Feature: Saved Sync Groups (Phases 1-3 Complete)**: Full 3-phase implementation of reusable course/folder group management. Backend manager, save workflow, 3-layered Hub dialog, and pre-flight merge engine are all shipping.

## Recent Changes (Session 2026-03-09 — Quick Sync Architecture Refactor)
- **Per-Course Batch Conversions Fix**: Discovered and resolved a major architectural flaw in `sync_ui.py` (`_run_sync`) post-processing where the iterative Quick Sync loop would overwrite the `persistent_convert_*` global flags. Refactored the `get_synced_file_paths(target_exts, conversion_key)` helper to extract `convert_*` settings strictly from each individual course's payload contract (`res_data['contract']`). This ensures that during a multi-course batch sync, Course A can be converted to PDF while Course B is skipped, rather than the final course blindly dictating the entire batch.
- **Zero-Download Bypass**: Modified `_run_analysis()` to prevent Quick Sync from unnecessarily falling back to the manual review screen (Step 2) when 0 "new" or "updated" files exist. If a sync attempt only features "locally deleted" or "deleted on canvas" files, it now bypasses straight to Step 5 (Sync Complete).
- **Bulletproof Skipped File Tally**: Established `st.session_state['qs_skipped']` using a robust dictionary/attribute checking loop designed to tally locally deleted and canvas deleted files before zero-download overrides. This enables the Success Screen to output a single, detailed warning outlining exactly how many deleted files were bypassed.
- **Cancel Routing Precision**: Injected an indestructible `qs_cancel_route` flag into the Quick Sync button trigger. When a user cancels the download loop (Phase 3), the cancel handler reads this flag to definitively route them back to Step 1 instead of Step 2.
- **Streamlit Ghost UI (Pass 1)**: Corrected a Streamlit layout oddity where an invisible submit button was breaking the DOM layout by injecting an HTML block with a JS payload (`window.parent.document.querySelector()`) to systematically hunt down and disable `display` on the specific layout node during Pass 1.

## Recent Changes (Session 2026-03-09 — Safe Fragment UX Refactor)
- **Safe Fragment Toasts**: Fixed a fatal white-screen crash where Streamlit wipes the DOM if `st.toast()` is called directly within an `on_click` callback attached to a fragment (`@st.dialog`). Reverted direct toast calls inside mutating callbacks (e.g., `_delete_group_callback`, `_save_inline_edit_cb`) to assign messages to a scoped `st.session_state['hub_toast']` variable. This toast is then safely consumed and displayed `st.toast()` at the very beginning of the `_saved_groups_hub_dialog` execution body.
- **Supercharged Close Button**: Solved a stale background UI issue by upgrading the explicit "Close" buttons inside the Hub Dialog. Replaced standard `st.rerun()` calls with `st.rerun(scope="app")` (wrapped in a `try/except TypeError` block for backward compatibility). This forces the entire application to redraw instantly, ensuring the main UI evaluates and reflects any pending database mutations correctly.
- **Hidden Native Close Button**: Injected a CSS rule (`display: none !important`) targeting `div[data-testid="stDialog"] button[aria-label="Close"]` inside `_inject_hub_global_css()`. This hides the native Streamlit 'X' close button, perfectly funneling all user exits through the custom state-aware "Close" button to guarantee the `scope="app"` full DOM refresh fires.

## Recent Changes (Session 2026-03-09 — Hub Dialog Button Rerender Fix & Logic Audit)
- **Standalone Pair Logic Fix**: Fixed a bug where the inline "Save Pair" (💾) button became erroneously disabled if a pair was already saved nested inside a multi-course Group. Updated the `_saved_pair_sigs` signature builder to strict-filter `is_single_pair == True`, accurately isolating Standalone Pairs from Group Pairs.
- **Group ID Database Separation**: Validated the architecture of `SavedGroupsManager`. Re-saving an existing nested Pair as a Standalone Pair correctly generates a novel `group_id` with `is_single_pair=True`, completely averting database collisions and UX overlap. Inline edits to Standalone Pairs remain perfectly isolated from their identically-named Group counterparts because state mutations are strictly scoped by `group_id`.
- **Hub Card Spacing Reduction**: Tightened the vertical rhythm of the Hub list by assigning specific CSS keys (`hub_group_item_` and `hub_pair_item_`) to the card containers and injecting a `-12px` (user tweaked to `-2px`) bottom margin. This effectively counteracts Streamlit's native flexbox gap, converting the individual cards into a cohesive visual sequence.
- **Tab State Synchronization**: Refactored the `_saved_groups_hub_dialog` tab navigation ("View All", "Groups", "Pairs") avoiding conditional `if st.button:` logic. Implemented a `set_view_mode` `on_click` callback to guarantee session state updates *before* the Streamlit dialog layout is evaluated. This solves the double-click state-lag bug where active tab styling failed to update instantly.
- **Expander CSS Restoration**: Re-wired CSS selectors to use the updated `st-key-hub_group_item_` key to restore lost styling on group expander titles and unordered list alignment (1.5rem padding, bullet point nudging).
- **Pair Course Text Layout**: Transformed the single pair display from `🎓 {course_name}` to `Course: {course_name}` encapsulated in a highly-targetable `<div class='pair-course-subtitle'>`. Styled the text to directly match the group expander summaries and appended `margin-bottom: 8px` formatting for breathing room.
- **UI Element Polish**: Replaced "Back to Groups" button text with "Back to overview". Injected direct key-targeting CSS (`[class*="st-key-hub_add_"]`) bypassing the generic Streamlit `stTooltipHoverTarget` class to force disabled/tooltipped buttons to scale cleanly to a uniform `40px` min-height, resolving a layout drift bug.

## Recent Changes (Session 2026-03-08 — Saved Groups UI Polish & Card Layout)
- **Layer 2 Pair Card Layout Restructure**: Fixed a persistent visual clipping bug caused by Streamlit's native nested column containers `st.columns` conflicting with border-bottom padding. Reverted the `c_title, c_save` layout to a pure sequential Markdown rendering flow, preserving the card's native vertical flexbox rhythm.
- **Save Button Absolute Positioning**: Transitioned the inline `💾` button to `position: absolute` pinned to the top-right corner (`top: 15px`, `right: 16px`) of the `st.container`. Collapsed the button's flex block using `height: 0` while keeping `overflow: visible`, completely preventing the button from displacing the card's folder path text.
- **Card Vertical Padding and Gap Control**: Injected precise padding rules (`padding: 5px 12px 20px 12px`) into the course cards to accommodate the absolutely positioned button while preventing bottom clip. Enforced a `gap: 10px` and `justify-content: flex-start` on the internal text to align content to the top edge seamlessly.
- **Ghost Emoji Styling**: Stripped all Streamlit background, border, and padding chrome from the `st-key-save_pair_` buttons, transforming them into floating emojis with scaling hover states without disrupting layout geometry.
- **Tab Navigation Revision**: Replaced the chunky segmented control navigation in the Hub dialog with native button tabs wrapped in a scoped container (`hub_tabs_container`), styled to mimic a slim macOS tab-bar.
- **Streamlit Dialog State Stability**: Removed `st.rerun()` calls from the Hub dialog layer navigation callbacks (`_change_hub_layer`), relying strictly on `on_click` state mutations to prevent the entire SPA dialog from closing unexpectedly.

## Recent Changes (Session 2026-03-05 — Saved Sync Groups: Full Feature)

### Phase 1: Backend Manager & Save Workflow
- **`SavedGroupsManager` class (`sync_manager.py`)**: JSON-backed persistence (`saved_sync_groups.json`) with `load_groups()`, `save_group()`, `delete_group()`, `update_group()`, and `matches_existing_group()` (signature-based duplicate detection using `frozenset` of `(course_id, local_folder)` tuples). Uses `uuid.uuid4().hex` for IDs.
- **Save Dialog (`sync_ui.py`)**: `@st.dialog("💾 Save as Group")` with text input, Create/Cancel buttons, and CSS overrides for disabled states. Uses `pending_toast` pattern to avoid ghost toasts.
- **"Save List as Group" button**: Disabled when <2 pairs or exact match to an existing group. Columns: `[1.5, 1.5, 7]` layout with `gap="small"` for aggressive left alignment next to "Add Course folder".

### UI Layout Polish & Architecture (This Session)
- **Hub Config Data Binding Fix**: Corrected logical bugs in `_render_hub_config` where the "Flat/Subfolder" checkbox and "NotebookLM" checkbox failed to read their respective metadata keys properly. The function now correctly reads `download_mode` directly from the `SyncManager` and evaluates the NotebookLM status by logically checking if all 8 conversion sub-settings are `True`.
- **Inline Edit Architecture Refactor**: Completely eliminated `layer_3` and `layer_4_add_pair` from the Hub Dialog. Replaced them with context-aware, in-place edit cards (`hub_editing_pair_idx`) and a dedicated Add-Pair inline state (`hub_is_adding_new_pair`). Utilized an explicit `_cancel_edit_name_cb` on-click pattern to dismiss states safely, resulting in a cleaner, flatter Layer 2 UI component without heavy re-renders.
- **Windows Focus Stealing Bypass**: Integrated a `ctypes` Alt-key simulation (`VK_MENU`) inside the cross-platform `open_folder()` utility. By momentarily simulating an ALT release before spawning `os.startfile(path)`, the script cleanly bypasses the restrictive Windows 10/11 taskbar focus lock, forcing the newly launched File Explorer window directly into the visual foreground.
- **Config Expander HTML Redesign**: Replaced the previous emoji-based summary in `_render_hub_config()` with a professional 3-column HTML layout. Instead of native Streamlit disabled checkboxes (which wash out the UI), wrapped active `input type='checkbox'` DOM elements in `pointer-events: none` CSS wrappers. This allowed retaining bright colors and native `#3b82f6` Streamlit blue checkboxes in read-only mode, coupled with tight recursive indentation for visually hierarchical sub-settings.
- **Aggressive Layout Refinement & Bullet Specificity**: Escaped Streamlit's internal 1rem `stExpanderDetails` margins not via the global CSS wrapper (which clashed dynamically) but through aggressive explicit inline `<style>` injections (`margin-top: -15px`). Realigned Streamlit's native markdown `<ul>` elements inside the `layer_1` accordion expanders by explicitly crushing the native `margin-inline-start` properties on `.stMarkdownContainer`, allowing bullets to shift left perfectly under the expander arrow.
- **CSS Specificity Fix for Bulletproof Button Styling**: Diagnosed and fixed a CSS specificity conflict where Hub Dialog buttons lost their custom styling when the sync list was empty. Root cause: a broad `div[data-testid="stDialog"] button[kind="secondary"]` selector in `_save_group_dialog` (specificity `(0,2,1)`) was overriding per-key selectors (specificity `(0,1,1)`). Fix: boosted ALL dialog button selectors by prepending `div[data-testid="stDialog"]` to every key-based rule.
- **Page-Level CSS Injection (CRITICAL)**: `st.empty().container()` in `app.py` discards `<style>` tags during DOM transitions (empty→non-empty state changes). All Hub CSS is now injected in `app.py` at PAGE level (line ~484), OUTSIDE the `st.empty()` context. The `_inject_hub_global_css()` function is called from `app.py`, NOT from `render_sync_step1`. This is the definitive architectural fix.
- **Future-Proofing Rule (CSS Specificity & Leakage)**: (1) ALL dialog button CSS selectors MUST include a `div[data-testid="stDialog"]` prefix. (2) NEVER inject `<style>` tags inside `st.empty().container()` — they will be discarded during DOM transitions. Always inject at the page level. (3) NEVER use the `:has()` pseudo-class combined with sibling combinators (`~`) and broad selectors (e.g., `div:has(span#id) ~ div button`) within the main app to style empty states. The `:has(#id)` selector climbs the entire DOM tree to root-level ancestor `div`s, and the `~ div` sibling combinator will then inadvertently match the Streamlit `stDialog` portal container. This causes main-app CSS to leak into modals with devastatingly high specificity (`1,1,4`), overriding all targeted dialog button styles. Always scope empty-state button CSS uniquely by their native Streamlit widget key (e.g., `div.st-key-btn_empty_state button`).
- **Top-Level CSS Hoisting for Bulletproof Rendering**: Moved both the comprehensive Hub Dialog `<style>` block and the main Hub button `<style>` block (previously nested inside `col_hub`) to the absolute top level of the `render_sync_step1` main page rendering flow. This structural refactor completely bypasses Streamlit's aggressive virtual DOM diffing logic, which was previously unmounting nested CSS blocks when the application transitioned to an empty state, ensuring the Hub Dialog's visual hierarchy remains 100% stable at all times.
- **Tightened Layer 2 Pair Cards Vertical Rhythm**: Consolidated the Streamlit native markdown text elements (h3 title and folder path span) inside Layer 2 pair cards into a single HTML structure. This completely bypassed Streamlit's implicit paragraph spacing, allowing for precise 14px font sizing and flush alignment. Additionally, reduced the container's top padding (`padding-top: 8px`) to tighten the vertical space above the title, creating a more cohesive and compact card layout.
- **Layer 2 Pair Cards & Button Hierarchy**: Adjusted the styling of the Course/Folder pair cards in Layer 2 to match the established visual hierarchy from Layer 1. The pair card background was made slightly lighter (`rgba(255, 255, 255, 0.05)`). The "Open Folder" and "Edit Pair" buttons, along with the "See Configuration" expander summary, were styled to be lighter than the card background and brighten further on hover. The "Remove" button was updated with defensive design, defaulting to a darker recessed grey (`rgba(0, 0, 0, 0.3)`) but retaining its danger red hover state.
- **Layer 1 Group Action Buttons Hierarchy**: Injected specific CSS rules targeting the dynamic keys for the three action buttons inside Layer 1 Group Cards ("Add to Sync List", "Edit Group", "Delete"). Restyled them to establish a clear visual hierarchy: "Edit" and "Add" default to a light grey, "Edit" gets lighter on hover, "Add" turns indigo on hover, and "Delete" is recessed with a dark grey background and transitions to danger red on hover.
- **Layer 1 Group Cards Elevation**: Injected a dynamic key (`hub_overview_group_card_{g_idx}`) to the groups overview cards and added a specific CSS rule to apply a subtle yellowish tint (`rgba(255, 230, 150, 0.1)`) and a soft drop shadow. This elevates the visual hierarchy to match the depth introduced in Layer 2.
- **Group Feature Color Coordination**: Visually linked the "Save List as Group" and "Saved Groups" (Hub) buttons using a "Dusty Slate-Indigo" theme (`background-color: rgba(110, 115, 180, 0.35)` with `border: 1px solid rgba(110, 115, 180, 0.6)`). This desaturated, slightly transparent palette merges perfectly into the dark mode UI while retaining a sleek IDE aesthetic.
- **Dialog Cancel Button Styling**: Refined the hover state for the secondary "Cancel" button inside the `_save_group_dialog` to match the app's standard "Ghost Danger" aesthetic. The solid red background (`#ef4444`) was replaced with a persistent dark background (`#262730`) while only the border and text transition to Streamlit standard red (`#ff4b4b`), keeping the UI balanced.
- **Streamlit 1.34+ SPA Dialog Routing Fix**: Patched a critical navigation bug within the `_saved_groups_hub_dialog`. In newer Streamlit versions, calling `st.rerun()` inside an `@st.dialog` acts as a native "close and rerun main app" command. The fix was two-fold: (1) stripped `st.rerun()` from all intra-dialog buttons, and (2) refactored all layer-navigation buttons to use `on_click=_change_hub_layer` callbacks. This ensures session state is mutated *before* the dialog function re-evaluates its layout, eliminating the double-click bug caused by Streamlit's top-to-bottom execution model. The `_change_hub_layer` helper supports `_pop_keys` for cleanup on back-navigation.
- **Hub Dialog Top-Level Refinements**: Standardized the `_saved_groups_hub_dialog` visual hierarchy by substituting basic text with Markdown headers (`### 🗂️`) and bold course counts. Swapped the buggy CSS `vh` height logic for a native `st.container(height=400, border=False)` around the group iterator loop. This guarantees a scrollable inner list of groups while pinning the `btn_hub_close` button persistently at the bottom of the dialog. Enforced strict Streamlit keys (`btn_hub_close`, `btn_hub_delete_*`) to allow isolated CSS targeting, and completely refactored the Dialog CSS block to eliminate conflicting rules, guaranteeing the Delete buttons achieve the "Ghost Danger" (red border/text over dark background) hover state uniformly. Fine-tuned the exact pixel spacing of the Hub navigation via aggressive CSS injections: squeezing the massive native margins off `h3` and `p` elements inside Layer 2, locking the tertiary "Back" buttons to explicit keys (`btn_back_to_groups`, `btn_cancel_add_pair`, `btn_hub_back_l3`), pinning down fixed opacities (`0.75` shifting to `1`) on hover for all tertiary buttons. After determining that aggressive CSS layout overrides (`width: 100%`, negative margins, High-Specificity container targeting, and custom `border-bottom` separators) were inherently fighting Streamlit's DOM logic and secretly causing left-shifted content and layout instability, a "Great Purge" was executed. All destructive layout hacks, including custom header lines and scroll container border removals, were entirely stripped. The dialog was successfully reverted to Streamlit's native, perfectly-centered modal geometry, ensuring long-term rendering stability. The tertiary Back buttons align naturally within this restored layout flow.
- **Hub Dialog Layer 2 UX Overhaul**: Completely redesigned the Layer 2 ("Edit Group") screen. Implemented a progressive disclosure UX pattern for the Group Name: a clean "View Mode" features a dominant `h1` title (line-height: 1), vertically compressed layout, and Flexbox CSS (`flex-end`) to perfectly baseline-align the compact "Edit" button flush with the bottom of the title. Clicking edit seamlessly toggles into an "Edit Mode" inline title editor (75/25 column split) wrapped in a distinct meta-container (`hub_edit_group_meta`) with a subtle grey-yellow background tint to separate settings from content. Crucially, saving the name utilizes an `on_click` callback to mutate state instantly instead of `st.rerun()`, preventing the `@st.dialog` from abruptly closing. Elevated the pair card visual hierarchy with Markdown layout (`#### 🎓` for course names) and injected dynamic keys (`hub_pair_card_{p_idx}`) to apply a faint background lightening and soft drop shadow, creating visual depth. Standardized card actions into an equal-width 3-column layout (Open Folder, Edit Pair, Remove) and injected the 'Ghost Danger' CSS targeting the new `btn_hub_remove_pair_*` key. Introduced an `on_click=_remove_pair_from_group` callback for instant list truncation without abruptly closing the SPA. Appended a global "Add a new course" navigation hook explicitly styled with a faint blue/indigo, highly-transparent aesthetic to match the main app's theme without overwhelming the dark mode UI. Unified all inner-dialog *navigation* elements by enforcing the `type="tertiary"` parameter directly on every `st.button` constructor across all modal layers (including error and rescue states). This root Python fix allowed the deployment of a single, clean universal `button[kind="tertiary"]` CSS rule guaranteeing borderless, grey-to-white hover states application-wide and eliminating fragmented, key-specific CSS overrides. Note: the form-action "Cancel" button in Layer 3 alongside "Save Changes" was intentionally kept as `secondary` to maintain proper button hierarchy.
- **Ignored Files Button Legibility**: Upgraded the CSS block for `div[class*="st-key-ignored_btn_"]` to be state-aware. When enabled, it enforces `color: #ffffff !important` overcoming Streamlit's dimmed secondary button styling. When `[disabled]`, the text and emojis revert to a dim grey (`rgba(255, 255, 255, 0.4)`) to clearly indicate the button is untrackable (i.e. 0 ignored files).
- **Step Tracker Spacing**: Injected a 15px physical spacer immediately under `render_sync_wizard` to give breathing room before the Sync list area.
- **Hub Button Row Alignment**: Fixed the `<h3>` "Canvas Courses to Sync" margin displacement caused by previous CSS hacks. Shifted the column ratio to `[0.7, 0.3]` and set vertical alignment to `center`. Explicitly reset the heading's inline styling to `margin-top: -10px; margin-bottom: 0px; padding-bottom: 0px;` to enforce perfect vertical symmetry within the row and pull the title up flush with the button.
- **Hub Button Vertical Spacing**: Replaced the brittle top-margin hack with a robust 3-part CSS strategy:
  1. Stripped default margins from `div.st-key-btn_hub_main` to align it naturally with the step header.
  2. Targeted the parent `stHorizontalBlock` row containing the Hub button using `:has(.st-key-btn_hub_main)` to kill its padding and negative bottom margin.
  3. Yanked the main `div.st-key-sync_list_outline` container up uniformly by -10px, achieving a perfect, tight 5px visual gap below the button row.
- **Action Button Alignment**: Overrode the `[0.22, 0.22, 0.56]` column layout for the Add and Save buttons to a much firmer `[1.5, 1.5, 7]` container split, strictly pinning both buttons to the left wall. Included `use_container_width=True` on the Add button for size parity.

### Phase 2: The Hub (Refactored SPA Dialog)
- **Architecture**: Single `@st.dialog("📚 Saved Groups", width="large")` with flattened `st.session_state['hub_layer']` navigation (now exclusively `layer_1`, `layer_2`, and `rescue_mode`). Layers 3 and 4 were obliterated.
- **Dialog Persistence Pattern**: Streamlit natively keeps dialogs open. The Hub dialog is now triggered strictly within the `if st.button:` block. The old dangling `hub_dialog_open` session state flag was removed entirely to prevent state-leakage ("Ghost Dialogs") triggering unexpectedly upon unrelated reruns.
- **Layer 1 (Overview)**: Group cards with ➕ Add to Sync List, ✏️ Edit Group, 🗑️ Delete. Delete uses `pending_toast` pattern.
- **Layer 2 (Group Details & Inline Editing)**: Editable group name (with dedicated Cancel button) + pair cards. Pairs toggle an inline editor card using `hub_editing_pair_idx`. Each pair has 📂 Open Folder, ✏️ Edit Pair, and ⚙️ See Configuration expander. Config reads `sync_contract` JSON from `.canvas_sync.db` via `SyncManager._load_metadata('sync_contract')` and renders cleanly padded HTML Checkboxes with `convert_*` booleans. Add functionality generates a blank inline edit component at the bottom via `hub_is_adding_new_pair`.

### Phase 3: Pre-Flight Merge Engine
- **Duplicate Filtering**: Compares incoming `course_id`s against existing `sync_pairs`. Drops duplicates silently with count toast.
- **Folder Existence Check**: `Path(pair['local_folder']).exists()` for each unique pair. If all exist → merge immediately + persist + close Hub. If any missing → `rescue_mode`.
- **Rescue Mode**: Warning UI listing only missing pairs. Per-pair "📂 Locate folder" buttons using `_rescue_select_folder(pair_idx)` with isolated `rescue_paths` dict. "Confirm & Add Group" button disabled until all remapped. On confirm: updates group JSON + merges into session + persists.

### Code Quality Audit Fixes (This Session)
- **Ghost Toast Bug**: Fixed in 4 locations (delete, rename, edit pair, all-duplicates) — converted `st.toast()` + `st.rerun()` to `pending_toast` pattern consumed at top of `render_sync_step1`.
- **Delete Button Danger Styling**: CSS targets `div[class*="st-key-hub_del_"] button:hover` for red (#7f1d1d bg, #ef4444 border).
- **Cancel Button Red Hover**: CSS targets `hub_cancel_*` and `cancel_save_group` keys.
- **Config Expander Spacing**: Changed from `"\n\n".join()` (double-spaced) to `"<br>".join()` (tight).
- **Dialog Primary Buttons**: Full blue/disabled styling ported from Save dialog into Hub CSS.

### Key Streamlit Patterns Learned
1. **No Nested Dialogs**: Streamlit crashes on `@st.dialog` inside `@st.dialog`. Use inline widgets (`st.selectbox`) instead.
2. **Dialog Persistence**: `@st.dialog` functions must be called on every rerun to stay open. Use a session state flag (`hub_dialog_open`) and call the dialog outside the button's `if` block.
3. **Ghost Toast Pattern**: `st.toast()` + `st.rerun()` = invisible toast. Always use `st.session_state['pending_toast']` consumed at the top of the render function.
4. **Isolated Tkinter State**: When using tkinter folder pickers inside dialogs, store results in dialog-specific session state keys (e.g., `hub_temp_folder`) to prevent contamination of the main UI state.
5. **CSS Key Targeting**: Use `div[class*="st-key-{widget_key}"] button` selectors to style specific buttons by their session state key.
6. **Focus Hack Bypass**: Opening an `os.startfile` command via backend Python often steals background focus. In Windows natively, leveraging a quick `ctypes` ALT-key (`0x12`) release via `keybd_event` tricks the OS out of its background-app defensive stance.

## Recent Changes (Session 2026-03-04 - Ignored Files UI Polish)
- **Bulk Selection Matrix Architecture**:
  - Rewrote both the multi-course (`_ignored_files_dialog`) and single-course (`_show_course_ignored_files_inner`) dialogs to abandon "visibility filtering" in favor of remote-control bulk selection. All files are now constantly visible.
  - Implemented smart `(selected/total)` filetype unit counters that elegantly disappear when selection matches 0 or the total amount.
  - Wired explicit bidirectional state forcing `st.session_state[unit_key] = is_all_checked` before widgets render, ensuring manual file unchecking perfectly mimics the logical unit state without latency/ghosting.
- **Ghost File Elimination (Data Freshness)**:
  - Inside both dialog execution blocks, enforced top-of-routine database fresh fetches `files = sm.get_ignored_files()`. When files are restored, the dialog instantly reruns and recalculates the exact list seamlessly.
- **Visual Polish & Bug Mitigation**:
  - Resolved Streamlit Dark Mode dialog flashing by locking container max heights to `500px`.
  - Tightened UI horizontal spacing using specific negative margin HTML fragments (`margin-top: -10px; margin-bottom: 15px`) around "Or" separators.
  - Refined modal `Close` buttons exclusively to `type="secondary"` to differentiate from destructive/primary actions.
  - Standardized "🗑️" emojis to "🚫" uniformly tracking ignored items globally.

## Recent Changes (Session 2026-03-04 - V1.0 Architecture Audit Fixes)
- **Eliminated `handle_sweep` NameError (`sync_ui.py`)**:
  - Found and fixed a critical bug where `file_ids_to_ignore` was referenced but never defined. Instantiated it directly from `items_to_ignore` to prevent runtime crashes during bulk "Ignore unchecked" operations in the Review Phase.
- **Orphaned `.part` File Cleanup (`sync_ui.py`)**:
  - Refactored the sync download loop to use a strict `try/finally` block. If the `atomic_rename_done` flag fails to trigger, the temporary `.part` file is unconditionally unlinked, preventing disk bloat during network drops or disk full scenarios.
- **Sync Download Resilience (`sync_ui.py`)**:
  - Engineered parity with `canvas_logic.py`'s download engine by porting the 5-retry exponential backoff loop directly into Phase 3's download block. The Sync engine now transparently retries 429 Rate Limits (respecting `Retry-After`), 5xx server errors, and temporary network timeouts instead of permanently failing actionable files.
- **Dynamic Disk Space Validation (`canvas_logic.py` & `ui_helpers.py`)**:
  - Upgraded the legacy static 1GB floor to a responsive `max(1GB, payload_bytes * 1.2)` algorithm. This accurately calculates a 20% safety margin for massive downloads (e.g. 10GB courses), catching structural capacity issues immediately prior to execution.

## Recent Changes (Session 2026-03-04 - Sync Contract & Atomic Execution)
- **Zero-Amnesia UPSERTs (`sync_manager.py`)**:
  - Replaced `INSERT OR REPLACE` with `INSERT INTO ... ON CONFLICT(canvas_file_id) DO UPDATE SET` across both the scalar `_save_single_file_to_db` and bulk `save_manifest` methods.
  - Explicitly excluded the `is_ignored` column from the `UPDATE` payload, mathematically guaranteeing that a user's Review Phase ignore-decisions survive both Sync Run #0 pipeline writes and subsequent sync executions.
- **The Sync Contract Architecture (`sync_metadata`)**:
  - Engineered a persistent configuration state. The Download pipeline now packages `file_filter` alongside all 8 `convert_*` post-processing booleans into a JSON blob and commits it to the SQLite `sync_metadata` table under the `sync_contract` key.
  - Quick Sync universally queries this DB contract before falling back to `session_state` defaults, guaranteeing perfect structural replication on 1-click runs.
  - **Filter Gatekeeping (`sync_ui.py`)**: Upgraded the "Quick Sync All" flow to actively intercept and filter `actionable_new`, `actionable_missing`, and `actionable_upd` file lists against the `file_filter` (e.g. `study` extensions) retrieved from the DB contract before queuing them. Also resolved a critical Python namespace shadowing bug (`UnboundLocalError`) by hoisting the `from pathlib import Path` requirement out of the Quick Sync local scope and utilizing the global `Path` import.
- **UI Contract Binding (`sync_ui.py`)**:
  - Overhauled `_show_analysis_review` to auto-load the course's Sync Contract and unconditionally overwrite the active `session_state` conversion keys on first render. 
  - Validated that downstream DB saves perfectly harvest user mutations from the checkboxes during the "Yes, Start Sync" execution phase.
- **Zero-Files UX Revamp**:
  - Eliminated the `st.error` dead-end that occurred when a user ignored the last actionable file in a payload. Replaced it with a positive `st.success` exit ramp and a "Done - Return to Front Page" button that cleans state and triggers `st.rerun()`.

## Recent Changes (Session 2026-03-04 - Sync Run #0 Handoff Architecture)
- **DB Population During Initial Download**:
  - Bridged the disconnect between the Download Engine (`canvas_logic.py`) and Sync Engine (`sync_manager.py`). The Download Engine now instantiates the `SyncManager` and populates `.canvas_sync.db` in real-time as files download.
  - Implemented `record_downloaded_file()` in `SyncManager` to perform direct, concurrent SQLite writes (bypassing the in-memory dict) immediately after atomic `.part` renames.
- **Authoritative Structure Detection**:
  - Created a `sync_metadata` table to persistently store the selected `download_mode` ('flat', 'modules', 'files') at the end of the initial download.
  - Upgraded `detect_structure()` to query this metadata as the absolute source of truth before falling back to filesystem heuristics.
- **Safety & Purity Guards**:
  - Preserved cancellation purity by strictly recording DB entries *after* 100% byte verification and `.part` rename phase. Cancelled connections never reach the SQLite write phase.

## Recent Changes (Session 2026-03-04 - Settings Redesign & Debug Persist)
- **Settings Modal UI ("Card" Layout)**:
  - Redesigned the global settings modal (`⚙️ Settings`) by leveraging Streamlit's `st.container(border=True)` to create discrete layout "Cards" for Download Settings and Sync Settings.
  - Eliminated vertical dead space by consolidating headers and descriptions into custom HTML blocks with strictly controlled CSS margins.
  - Capped `Max Concurrent Downloads` slider at 15 and explicitly warned users about Canvas rate limits causing crashes.
  - Injected custom CSS to style the slider track a vibrant light blue (`#38bdf8`).
- **Debug Mode Persistence**:
  - Rewired the `debug_mode` state so that the `canvas_downloader_settings.json` backend logic permanently saves and automatically loads the troubleshooting toggle choice.
  - The Settings Modal now maps the `Enable Troubleshooting Mode` checkbox value directly against the persistent config file variables.

## Recent Changes (Session 2026-03-04 - Error Logging & Concurrency Fixes)
- **Error Deduplication & Cleanup**:
  - Truncated `download_errors.txt` at the start of each run via `clear_error_log()`.
  - Removed redundant disk-fallback reader in `app.py` that extended in-memory session arrays.
  - Eliminated the `session_errors.txt` force-write dump since `_log_error` handles real-time disk persistence.
- **Sniper Retry Flow (`app.py`)**:
  - Rewired the "Retry Failed Items" button to instantly bypass the scanning/analysis phase and jump straight into `download_status = 'running'` for surgical retries of failed links.
- **Path-Based Concurrency Deduplication (`canvas_logic.py`)**:
  - Discovered that relying on Canvas API file IDs fails to deduplicate LTI/synthetic shortcuts and multi-module inclusions, leading to `[WinError 32]` collisions when async workers attempt to write to the same `.part` file.
  - Implemented hard path-based deduplication (`target_folder / sanitize(filename)`) guarded by `seen_target_paths` and `seen_flat_paths` sets across all 4 entry points (modules, flat scan, flat-fallback, catch-all).
- **Universal Error Logger Deduplication**:
  - Implemented a 2-layer signature-based deduplication (`course|item|message`) to prevent duplicate rendering of LTI/catch-all failure loops.
  - Layer 1 (Disk): Checks `CanvasManager._logged_error_sigs` before appending to `download_errors.txt`.
  - Layer 2 (UI): Checks `st.session_state['seen_error_sigs']` in the `update_ui` callback before updating the list.

## Recent Changes (Session 2026-03-04 - UI Polish & Status Sync)
- **Unified Blue Status Indicator (`sync_ui.py` & `app.py`)**:
  - **Desync Fix (Phase 2 Download)**: Moved the `active_file_placeholder` update for current filenames **outside** the 0.4s UI throttle block in `sync_ui.py`. The status text now updates instantly for every file, ensuring it never lags behind the terminal output.
  - **Standardized Styling**: Implemented a consistent `#38bdf8` blue color with `font-weight: 500` for all "Currently downloading:" and "Currently processing:" status messages.
  - **Post-Processing Visibility**: Injected the blue status indicator into all 7 conversion/extraction loops (Archives, PPTX, HTML, Code, Word, Excel, Video) in both `sync_ui.py` and `app.py`.
  - **Cleanup Hooks**: Added `active_file_placeholder.empty()` calls after all post-processing completions to ensure the status text is cleared once the course/batch is finished.

## Recent Changes (Session 2026-03-03 - UI Polish)
- **Quick Sync Flow Repair (`sync_ui.py`)**:
  - **Payload Completion**: Fixed a bug where `AnalysisResult.locally_deleted_files` was fundamentally ignored by the Quick Sync interceptor, causing courses with only local deletions to incorrectly fall back to the Review page (reporting `total_count = 0`). Locally deleted files are now correctly merged into the `redownload` payload matching the normal flow.
  - **State Key Consistency**: Synchronized session state checkbox keys in the Quick Sync flow to use `cid` (Course ID) rather than `idx` (loop index), matching the normal UI flow to prevent toggle desync on back-navigation.
  - **Post-Processing Variables**: Added persistence hooks (`persistent_convert_*`) to the Quick Sync flow, ensuring background conversions (e.g., zip extraction, PDF rendering) aren't bypassed.
  - **Cancel Guard Reset**: Enforced a nuclear reset of four `cancel_requested` permutations directly inside the "Analyze" and "Quick Sync" button triggers to prevent stale states from silently aborting the analysis loop on iteration 0.
- **Dynamic Download Headers (`app.py` & `translations.py`)**:
  - Replaced the hardcoded "Step 3: Downloading..." success header with conditional rendering tied to `st.session_state['download_status']`.
  - Added new `step4_download_header` containing "Step 4: Complete!" to English and Danish translation dictionaries to accurately reflect the 'done' state.
- **Sync Review Layout Finalization (`sync_ui.py`)**:
  - **CSS Truncation**: Fixed the "Confirm Sync" dialog breaking vertical rhythm on single-course syncs by applying a flex layout with `white-space: nowrap; overflow: hidden; text-overflow: ellipsis;` to the destination row, along with a hover `title` attribute for long course names.
  - **Settings Relocation**: Moved the NotebookLM / File Format expander from the middle of the file selection UI down to the absolute bottom, immediately above the Action buttons.
  - **Visual Hierarchy**: Prepended the "🛠️" emoji to the settings expanders in both `app.py` and `sync_ui.py` for cross-mode consistency. Injected a custom-styled `<hr>` separator and a strict `20px` height spacer `div` to enforce margin isolation above the final Action buttons, bypassing Streamlit's native collapsing margins.

## Recent Changes (Session 2026-03-03 - Atomic Symbiosis)
- **Database Surgery (`sync_manager.py`)**:
  - Replaced bulk `DELETE FROM sync_manifest` query with iterative `INSERT OR REPLACE` upserts to prevent data loss on mid-sync crashes.
  - Eliminated the defunct `create_initial_manifest()` function and transitioned entirely to active auto-discovery pipelines in `analyze_course()`.
- **The `.part` File Pattern (`app.py` & `sync_ui.py`)**:
  - Rewrote both `_download_file_async` loops to stream bytes exclusively to `filename.ext.part` files.
  - Added instant cancel-flag evaluations directly inside the 1MB chunk `while` loops for immediate interruption.
  - Handled interrupted state by actively `unlink()`ing the partial file and enforcing exact byte-size verification before `rename()`ing to the target extension.
- **Semantic Purity Guards**:
  - Fixed premature committing in `sync_ui.py` by filtering the pre-download DB dump to exclusively save `.is_ignored()` settings, preventing auto-discovered files from flashing into the DB before validation.
  - Structurally shifted the final Phase 2 `sync_mgr.save_manifest()` cascade to execute strictly *after* the top-level Cancel evaluator, ensuring an aborted run triggers zero post-download state mutations.

## Recent Changes (Session 2026-03-03 - Cancel UX Overhaul)
- **Cancel Infrastructure Overhaul**:
  - **Instant Callback**: Added `cancel_process_callback()` module-level function using `on_click=` pattern instead of `if button():` return-value checking. This fires immediately even during heavy blocking loops.
  - **Persistent Cancel Button**: The cancel button no longer disappears during post-processing. After clearing Phase 2 UI containers, a new "Cancel Post-Processing" button is rendered with `on_click` callback.
  - **8-Loop Cancel Guards**: Every post-processing `for` loop (Archives, PPTX, HTML, Code, URLs, Word, Excel, Video) now checks `sync_cancelled` at the top of each iteration and breaks gracefully with a red cancellation log message.
  - **Red Hover CSS**: Injected `button[data-testid="stBaseButton-secondary"]:hover` CSS in both Phase 2 and Post-Processing phases — red outline (#ef4444), dark red-gray bg (#2c1616).
  - **Premium Cancelled Screen**: Redesigned `_show_sync_cancelled()` with a gradient card (linear-gradient from #2c1616 to #1a1a2e), red border, file count badge, and full-width "Go to front page" primary button.
  - **State Management**: Added `sync_cancelled` to `_init_sync_session_state()` defaults and `_cleanup_sync_state()` cleanup list.
  - **Phase 2/3 Isolation Guard**: Added an explicit `if sync_cancelled: st.rerun()` guard between the Phase 2 async block and Phase 3 Post-Processing setup. This blocks the Python script from falling through and setting `is_post_processing = True` when a download is aborted.
  - **COM Button Render Forcing**: Reused the Phase 2 `cancel_placeholder` for the Phase 3 button because its DOM position renders it immune to the CSS `display: none` cleanup rules. Increased the pre-COM `time.sleep()` to `0.3s` to guarantee Streamlit flushes the HTML button to the browser before the Win32COM thread locks.
  - **Rerun Flag Protection**: Guarded the top-level `is_post_processing = False` initialization inside `_run_sync` so it doesn't wipe the flag during the final `on_click` cancel rerun, allowing the red cancellation card to accurately say "Cancelled during post-processing."

## Recent Changes (Session 2026-03-02)
- **Post-Processing Dual Logging**:
  - Added a setup block in `app.py` (before all NotebookLM hooks) that imports `log_debug` from `canvas_debug`, computes `debug_file` from session state, and defines a `log_post_process_error()` helper for writing to `download_errors.txt`.
  - Added 32 `log_debug()` calls across all 8 hooks (start, progress, success, error, complete messages) — plain text is mirrored to `debug_log.txt` when Debug Mode is on.
  - Added 7 `log_post_process_error()` calls on every ❌ failure path, writing timestamped entries to `download_errors.txt` with a `[Post-Processing]` tag.
  - `sync_ui.py` confirmed to have zero post-processing hooks — no changes needed.
- **NotebookLM UI Refactor (Step 2)**:
  - Removed the `st.expander` wrapper for the 8 NotebookLM sub-settings.
  - Placed sub-checkboxes directly beneath the master toggle and injected custom "Tree-View" CSS targeting their widget keys (`.st-key-convert_zip`, etc.).
  - The CSS structurally nests the items with a 28px margin, 2px solid left-border (#3E4353), and tightened vertical padding, creating a clear visual parent-child relationship without Python indentation rules.

## Recent Changes (Session 2026-03-02 - Excel COM Polish)
- **Robust Excel COM Converter Rewrite**:
  - **Removed CountA() Inspection**: Discovered that calling `CountA` on 17-billion-cell Excel sheets hung the COM thread, causing RPC timeouts and cascading batch failures. Removed all sheet data inspection.
  - **Removed ActiveWindow Selection**: Headless COM without a visible UI often fails to instantiate an `ActiveWindow`, crashing `SelectedSheets.ExportAsFixedFormat`.
  - **Global Export Strategy**: Simplified script to export the entire workbook via `wb.ExportAsFixedFormat` regardless of empty sheets. (Empty sheets safely produce small, valid PDFs).
  - **Proactive COM Health Checks**: Added `_is_alive()` ping (`self.app.Version`) at the start of every conversion to immediately detect and revive a COM channel silently corrupted by a previous file's `wb.Close()`.
  - **COM Throttling**: Added `time.sleep(0.3)` pauses between major COM commands to give the print spooler time to settle.
- **Global Append Logging**:
  - `debug_log.txt` and `download_errors.txt` now default to the root workspace directory rather than per-course folders.
  - Added programmatic course headers (e.g., `=== Post-Processing: CourseName ===`) injected into the single session log, preventing file overwrites during multi-course syncs.
- **Cancel UX Safety**: Added `try...except` guards around `progress_container.progress()` to prevent `NameError` crashes if a user cancels a download before the UI placeholder has fully rendered.

## Recent Changes (Session 2026-03-01 Revision)
- **Step 2 Download Settings Overhaul**:
  - **Terminology Pivot**: Changed "Full" download structure to "Flat" for better user clarity.
  - **Aggressive Header Suction**: Replaced native Streamlit markdown headers with custom HTML `h3` tags using `-25px` bottom margins to eliminate dead vertical space.
  - **Merged CSS Injection**: Combined scoped CSS `<style>` blocks with HTML headers in single `st.markdown` calls to remove implicit `div` wrapper gaps.
  - **Destination Alignment**: Implemented a `[1, 6]` fractional column ratio with a `28px` invisible spacer to horizontally and vertically align the "Select Folder" button with the "Path" input box.
- **Settings Relocation**:
  - **Debug Mode**: Moved "Enable Troubleshooting Mode (Debug Log)" from the main wizard view into the global `⚙️ Application Settings` modal.
- **NotebookLM Sync Logic**:
  - **Dynamic (x/y) Counter**: Implemented a mathematical sync logic for master/sub toggles that tracks current active features in real-time.

## Recent Changes (Session 2026-03-01 - NotebookLM Full Suite)
- **NotebookLM Compatible Download Expansion**:
  - **Archive Extraction (Ghost Stub)**: Built `archive_extractor.py` to automatically unzip `.zip` and `.tar.gz` payloads. Designed a 0-byte `.extracted` stub system to satisfy the sync engine and prevent endless re-downloads. Injected this step at the *very top* of the post-processing pipeline to ensure unpacked format-viable files (like raw HTML or PPTX trapped in a zip) are handed to downstream converters.
  - **Video to Audio**: Implemented `video_converter.py` using `moviepy` to rip `.mp3` tracks from massive `.mp4/.mov` payloads, deleting the original video to save space and enable NotebookLM transcription.
  - **Legacy Word to PDF**: Expanded the Win32COM architecture via `word_converter.py` to target `.doc`, `.rtf`, and `.odt` files, upgrading them to modern `.pdf` format.
  - **HTML to Markdown**: Built `md_converter.py` using `beautifulsoup4` and `markdownify` to strip Canvas Pages of nested HTML boilerplate and convert them into clean `.md` files.
  - **Code & Data Preservation**: Developed `code_converter.py` to intercept the top 50 student programming/data extensions (e.g., `.py`, `.java`, `.json`) and safely append a `.txt` suffix (e.g., `script_py.txt`) while enforcing UTF-8 encoding.
  - **URL Complier**: Engineered `url_compiler.py` to scrape directories for synthetic `.url` shortcuts and aggregate them into a single `NotebookLM_External_Links.txt` reference file per course.
  - **Win32COM PowerPoint to PDF**: (Previously Implemented) `pdf_converter.py` for `.pptx` and `.ppt`.
  - **Excel to PDF (Tabular Integrity)**: Built `excel_converter.py` to handle `.xlsx`, `.xls`, and `.xlsm`. Designed a specific `PageSetup` logic (`FitToPagesWide = 1`, `FitToPagesTall = False`, zero margins) to ensure wide spreadsheets are rendered as 1-page-wide, infinitely-tall PDFs, preserving tabular structure for LLM ingestion. Original files are deleted post-conversion.
  - **COM Context Manager Refactoring**: Upgraded the core Win32COM PDF converters (`pdf_converter.py`, `word_converter.py`, `excel_converter.py`) from isolated utility functions into Python Context Managers (`__enter__`, `__exit__`). Wrapped the download conversion loops in `app.py` directly inside these context managers to solve massive CPU bottlenecking. The heavy Office COM application is now initialized only *once* per entire file batch, rather than cold-booting and tearing down for every single file.
- **Streamlit UI Hijacking & Post-Processing**:
  - **Progress Bar Re-routing**: Prevented the download UI from appearing "frozen" at 100% by hijacking the main download progress bar, status text, and metrics placeholders to visually track the slow post-processing extraction/conversion loops.
  - **Native Terminal Hooks**: Removed isolated `st.status` expanders and injected the conversion progress directly into the custom `log_deque` / `terminal_log` HTML rendering loops.
- **Streamlit State & COM Debugging**:
  - **Widget Cleanup Bypass**: Fixed a bug where transitioning from the Settings Step to the Download Step destroyed the NotebookLM checkbox value. Captured the value into a `persistent_convert_pptx` state key precisely on button-click before `st.rerun()`.
  - **UI Thread Flushing**: Injected explicit `time.sleep(0.2)` pauses immediately after rendering the post-processing UI framework. This guarantees Streamlit completes the browser DOM paint before the thread locks up on heavy blocking Python or Win32COM operations.
  - **Office 365 Strict Constraints**: Wrapped `powerpoint.Visible = False` in a `try...except` block, safely bypassing modern click-to-run Office versions that throw exceptions when attempting to hide the application window.

## Recent Changes (Session 2026-02-28)
- **Batch Sync Stability & Duplicate Key Fixes**:
  - **Dynamic Container Keys**: Resolved `StreamlitDuplicateElementKey` bug by appending `_{course.id}` to all `st.container` keys in `sync_ui.py`.
  - **Wildcard CSS Scoping**: Updated the global expander styling to use wildcard attribute selectors (`div[class*="st-key-cat_new"]`), ensuring color-coded borders work across all dynamically keyed course blocks.
  - **Phase 1 Global Cancel**: Injected a unified "Cancel Analysis" button above the Canvas scanning loop, allowing users to safely abort Phase 1 of a multi-course sync.
- **Sync Review UI Layout Finalization**:
  - **Compact Headers & Numbering**: Reduced header bottom margin (16px → 4px) and padding for a slim profile; added blue index numbering (`1.`, `2.`, etc.) for batch tracking.
  - **Course Isolation Spacing**: Injected 20px physical gaps between course container blocks to prevent visual bleeding.
  - **Dynamic Expander Counters**: Live selection tracking (`selected / total`) projected via CSS `::after` ghost text to maintain expander persistence.
  - **Clean Title Formatting**: Replaced bullets (`•`) with double-space padding for a sleeker, symbol-free finish.
  - **Button Spacing Correction**: Fixed margin-collapsing on Bulk Selection buttons via keyed container overrides.
- **Progress Parity & Dialog Polish**:
  - **Vertical Centering**: Forced `st.dialog` to center-screen via global CSS injection.
  - **Frontend Yield Hack**: Implemented JS-triggered "hidden button" clicks to ensure modals unmount before heavy processing starts.

## Recent Changes (Session 2026-02-27)
- **Synthetic Shortcut Sync Support**:
  - **Manifest Integration**: Support for Pages, ExternalUrls, and ExternalTools using the "Negative ID Pattern" to prevent database collisions.
  - **LTI URL Priority Fix**: Prefer `html_url` for ExternalTools to ensure correct Canvas-wrapped authentication.
- **Sync Review UI Restructure**:
  - **Flush Header Band**: Negative margin bleed trick to create seamless course headers.
- **Synthetic Shortcut Sync Support**:
  - **Manifest Integration**: Modified `_save_page` and `_create_link` to return filepaths. Captured these in download loops to create `CanvasFileInfo` mock objects with negative IDs (e.g., `-int(item.id)`).
  - **Shortcut-Aware Live Fetching**: Upgraded `_get_files_from_modules` in `canvas_logic.py` to generate reciprocal mock objects during sync analysis, ensuring the Sync engine "sees" Pages and ExternalUrls as matching database entries.
  - **LTI URL Priority Fix**: Flipped extraction logic to strictly prefer `html_url` over `external_url`, ensuring ExternalTools route through the Canvas wrapper for correct JWT authentication.
  - **Size Normalization**: Hardcoded `size=0` for all synthetic items across both Manifest generation and Live Fetching to prevent perpetual "Update Available" size mismatches.
- **Sync Engine Reconciliation**:
  - **Negative ID Bypass**: Injected a bypass in `sync_manager.py`'s `_is_canvas_newer()` function. If `canvas_file.id < 0`, the engine skips timestamp comparison (which is unreliable for module items) and falls through to a strict local existence check.
  - **Restoration Interception**: Modified `sync_ui.py`'s download batch loop to detect negative IDs and recreate `.url`/`.html` shortcut files directly using Pathlib instead of attempting an HTTP byte-download.
- **Sync Execution UI Overhaul**: (Previous session changes maintained...)
  - **Speed & ETA Dashboard**: Replaced the static Streamlit text metric with a sleek, injected HTML/CSS 4-column dashboard rendering Sync Progress (X/Y), Downloaded (MB), Speed (MB/s), and ETA (MM:SS).
  - **Live Terminal Log**: Added a native-looking terminal window tracking active asynchronous downloads in real-time. Checkmarks and cross emojis visually categorize file successes, skips, and failures.
- **Sync Review Feature Fixes**:
  - **Ignored Files Rendering**: Fixed a conditional block that hid the analyze summary if zero actionable files existed; the section now persists if `total_ignored > 0`.
  - **Locally Deleted Binding**: Checkboxes for manually deleted local files now initialize by checking the global aggregate filters before falling back to False.
  - **Key Synchronization**: Unified all file-level checkbox keys to use `course_id`, ensuring state Persistence across filter changes.
  - **Zero-Value Metric Card Muting**: Transitioned from static HTML cards to a dynamic `_render_metric_card` Python helper. Zero-value cards intelligently drop their background opacity to 10% and remove box-shadows.
- **Confirm Sync Modal UX**:
  - **Vertical Centering**: Injected CSS globally within Step 4 to force `st.dialog` to appear dead-center in the viewport.
  - **Immediate Closure Strategy**: Implemented a "Frontend Yield" hack using a hidden button click triggered by a 200ms `setTimeout` JS script.
- **Standard Download UX Parity**:
  - **Confirmation Dialog**: Ported the `@st.dialog` vertical centering modal logic over to `app.py` Step 2.
  - **Dashboard Analytics**: Upgraded the standard download progress block (Step 3) to strictly utilize the injected HTML Sync metrics rendering structure.

## Active Tasks
- [x] Implement robust Row Separator CSS using keyed container scoping
- [x] Implement Opt-Out filter paradigm and fix state-lock bugs
- [x] Port Sync Progress UI to Analysis phase
- [x] Refine Trash/Ignored UX (Clean grey text, Persistent expander)
- [x] Fix terminal log rendering lag by immediate markdown updates
- [x] Standardize filename unquoting across all UI components
- [x] Refine "Select files to sync" box (Group header, filter options, and global uncheck buttons)
- [x] Refine "Sync Review" expanders (Wrap course blocks in master containers)

## Architecture Notes
- **Scoped Layout Overrides**: Use `st.container(key="...")` combined with targeted CSS (e.g., `.st-key-X > div[data-testid="stVerticalBlock"]`) to override Streamlit's default 1rem gaps without affecting the rest of the application.
- **Separator Tightening**: Targeting `hr` within keyed containers allows for pixel-perfect vertical positioning of logical dividers.
- **Idempotent Data Mutation**: When writing state callbacks tied to `st.button` `on_click` events in Streamlit, always ensure the array manipulations are strictly idempotent. Rapidly double-clicking buttons triggers the event twice before the rendering loop executes, leading to duplicate entities in session-state arrays which subsequently crashes Streamlit if those entries dynamically generate widget keys.
- **Frontend Yield for Dialogs**: When starting a heavy, blocking task immediately after closing an `st.dialog`, use a hidden button click triggered via `components.html` with a small JS timeout (e.g., 200ms). This allows the Streamlit frontend to receive the "unmount modal" command and clear the UI before the Python server locks up on the heavy processing loop.
