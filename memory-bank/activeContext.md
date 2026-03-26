# Active Context: Canvas Downloader

## Current Focus
## Recent Changes (Session 2026-03-26 — Temp File Shadowing Pipeline & Encoding Fix)
- **Win32 MAX_PATH Bypass (`ui_helpers.py`, `pdf_converter.py`, `word_converter.py`, `excel_converter.py`)**:
    - **Root Cause**: Deeply nested Canvas course folder structures generate absolute file paths exceeding Win32 MAX_PATH (255 chars), causing Office COM APIs (`Presentations.Open`, `Documents.Open`, `Workbooks.Open`) to hard-crash.
    - **Solution**: Implemented `office_safe_path()` context manager in `ui_helpers.py` that transparently shadows long paths (≥240 chars) into `%TEMP%` with short UUID-based names, yields safe paths for COM, and moves results back on exit.
    - **Ghost PDF Guard**: Exit block checks `temp_pdf.exists()` before `shutil.move()` — handles COM failures without orphaned ghost PDFs.
    - **Unconditional Cleanup**: Temp source file always deleted via `temp_source.unlink(missing_ok=True)` in `finally` block.
    - **Cross-Drive Safety**: Uses `shutil.move(str, str)` for Windows cross-drive and overwrite compatibility.
    - **Converter Injection**: All three converters (`pdf_converter.py`, `word_converter.py`, `excel_converter.py`) wrap their Windows COM blocks in `with office_safe_path(...)`. macOS AppleScript branches are completely untouched.
    - **Threshold**: 240 characters (15-char safety margin below MAX_PATH).
- **ZIP Encoding Fix (`archive_extractor.py`)**:
    - **Root Cause**: Python's `zipfile` defaults to CP437 filename decoding, mangling Danish characters (ø, æ, å) into Mojibake.
    - **Python 3.11+**: Uses native `metadata_encoding='utf-8'` parameter.
    - **Python <3.11**: Iterates `infolist()`, re-decodes CP437→UTF-8 for entries without UTF-8 flag (bit 11), passes mutated members list to `extractall()`.
- [x] **Active Feature: Temp File Shadowing Pipeline (Complete)**: Permanently bypasses Win32 MAX_PATH crashes in all Office COM converters.
- [x] **Active Feature: ZIP Encoding Fix (Complete)**: Fixes Danish character Mojibake in extracted archive folder/file names.


- **Step 2 UI Modernization & CSS Stabilization (`app.py`)**:
    - **CSS Architecture Pivot**: Replaced the failing `stVerticalBlockBorderWrapper` selector (deprecated in Streamlit 1.51.0) with a robust, version-agnostic "Trojan Horse" architecture.
    - **Trojan Horse Pattern**: Injected a custom class (`step-2-card-target`) into the injected HTML of each card header for the three Step 2 cards.
    - **Indestructible Selector**: Implemented a modern `:has()` CSS selector array targeting `div[data-testid="stContainer"]:has(.step-2-card-target)` to apply background elevation (`rgba(255, 255, 255, 0.04)`), ensuring visual parity across Streamlit versions.
    - **Direct Key Targeting**: Augmented the selector with explicit Streamlit Key targeting (`st-key-card_core_files`, etc.) for maximum reliability.
    - **Typography Refinements**: Polished "(Optional)" text in Card 2 and 3 headers by isolating it in a `<span>` with muted color (`#64748b`), reduced weight, and smaller size.
    - **Icon Badge Layout**: Finalized the "Corner Badge" icon layout where icons are centered on the top-left border of cards, with descriptions fully flush-left.


## Recent Changes (Session 2026-03-25 — Step 2 UI Modernization: Conversion Settings)
- **Conversion Settings UI Revamp (`app.py`)**:
    - Replaced legacy tree-view checkboxes with a premium 4x2 grid of orange-themed (`#f97316`) button-toggle cards.
    - Implemented a "Select All" master button spanning all 4 columns with a dedicated description sub-text.
    - Integrated a dynamic selection counter (`None selected` / `X enabled` / `All enabled`) in the card header for real-time feedback.
    - Engineered idempotent callbacks (`_toggle_conv_master`, `_toggle_conv_sub`) to handle complex state synchronization between the master toggle and individual settings.
    - Applied high-fidelity CSS overrides for icons, borders, and hover effects, achieving visual parity with the "Additional Course Content" component.
    - Refined icon scaling: increased sub-button icons to 30px (25% increase) while maintaining 24px for the master button for optimal balance.

- **Additional Course Content UI Refactor (`app.py`)**:
    - Replaced native `st.radio` components with high-fidelity segmented button controls matching the "Include Files" design.
    - Implemented a 4-column responsive grid for secondary entity toggles (Assignments, Announcements, etc.).
    - Bound all UI states to `st.session_state['dl_isolate_secondary']` to ensure 1:1 backend logical parity.
- **2-Column Top Row Conversion (`app.py`)**:
    - Refactored the core Download Settings view from a 3-column layout into a 2-column (`[1, 1, 1.5]`) layout for "Organization" and "Content", meticulously preserving the original card width on ultra-wide monitors without stretching.
- **Constrained Bottom Row (`app.py`)**:
    - Extracted "Additional Settings / NotebookLM" into a dedicated bottom row, horizontally constrained by a dummy column wrapper (`[2, 1.5]`). This spans the exact combined width of the top two equal-width cards, keeping it perfectly flush.
    - Verified `sync_ui.py` does not utilize this interactive block and uses a read-only 4-col layout instead, requiring no parity changes.

- [x] **Active Feature: Step 2 UI Modernization & CSS Stabilization (Complete)**: Transitioned to a version-agnostic "Trojan Horse" architecture for the Step 2 cards. Injected custom classes into header HTML and used modern `:has()` CSS selectors to ensure stable background elevation across Streamlit 1.51+ versions.
- [x] **Active Feature: Conversion Settings UI Revamp (Complete)**: Modernized the conversion settings into a high-fidelity orange grid of button-toggle cards. Implemented robust state synchronization, dynamic counters, and scaled iconography.

- [x] **Active Feature: Additional Course Content UI Refactor (Complete)**: Refactored secondary content toggles into a premium segmented control/grid layout with 100% backend logical parity.
- [x] **Active Feature: Native Button Card Architecture (Complete)**: Refactored the "File Organization" UI in `app.py` to use a native `st.button` card architecture. This ensures 100% click reliability across the entire card surface by styling the native button itself into the card, bypassing brittle DOM overlay hacks.
- [x] **Active Feature: Step 2 UI Structural Refactor (Complete)**: Refactored the core Download Settings view in `app.py` into a premium 3-column Card layout. Implemented strict horizontal symmetry using identical <h3> structures and hoisted all Python callbacks/CSS to the top-level scope to prevent DOM unmounting. Replaced the NotebookLM st.expander with a bordered container for unified visual weight.
- [x] **Active Feature: Sync Engine Bypass for URL Compiler (Pivot Complete)**: Initially implemented a "Ghost Stub" pattern, but pivoted to a cleaner "Pure Deletion & Sync Engine Bypass" approach. Original .url and .webloc files are now strictly deleted after compilation into NotebookLM_External_Links.txt, and the Sync Engine is modified to intelligently ignore their absence, ensuring 100% NotebookLM compatibility without breaking sync integrity.
- [x] **Active Feature: Final E2E Validation**: Monitoring the system for any remaining edge cases in the sync engine or UI feedback loops now that the core metric and diffing blocks have been audited and patched.
- [x] **Active Feature: Secondary Entity Phase Rebuilding (Completed)**: Successfully patched the UI Metric denominator locking issue in `app.py` and the `Step 5` Order of Operations failure in `sync_manager.py`.
- [x] **Active Feature: Structural Audit Fixes (Complete)**: Rectified the parameter hallucination in `sync_manager.py`'s database commit (`local_relative_path` -> `local_path`), implemented dynamic UI metric fetching in `app.py` to prevent overflow, and enforced strict Byte-to-MB conversion for secondary attachments in the `update_ui` callback.
- [x] **Active Feature: Catch-All Overlap & UI Ledger Parity (Complete)**: Eradicated a 30-file phantom jump in the `x/y` tracker by enforcing strict exclusion parity between the Module scanning phase and the Catch-All phase. Injected `module_file_ids` tracking into `canvas_logic.py` and moved UI increments strictly inside the `if msg:` block in `app.py` to prevent silent skips from inflating counts.
- [x] **Active Feature: UI Metric Desync Rectification (Phase 2 Complete)**: Resolved the final UI ledger mismatch by enforcing `explicit_filepath` injections into the `progress_callback` loops of `_save_secondary_entity` and `_create_link`. Eradicated `TypeError` crashes during byte comparison checks when Canvas APIs inject explicit `None` payloads via `or 0` coalescing cascade.
- [x] **Canvas API "Anonymous Discussion" Access Debugging (Complete)**: Resolved fetch phase access errors for active discussion topics.
- [x] **Attachment ID REVERT & Sync Retry Fix (Complete)**: Reverted a failed negative ID scheme for attachments to use true positive Canvas file IDs (essential for SQLite deduplication). Fixed a critical blank UI issue when retrying failed sync items by resetting the `sync_cancelled` flag.
- [x] **Active Feature: Arch. Audit Follow-Up - Critical Windows Concurrency Fixes (Complete)**: Rectified sharing violations in SQLite, injected strict async file mutexing for `.part` downloads in the sync loop, and transitioned to atomic `os.replace` backed by `PermissionError` rescue logic to protect against files opened in external editors.
- [x] **Active Feature: Phase 6 Final Architecture Audit Resolution**: Executed the final 5 architecture fixes. Resolved async event loop freezing, fixed asyncio memory leaks, eliminated JSON TOCTOU race conditions using thread locks, substituted Tkinter for native PowerShell folder pickers on Windows, and implemented aggressive FFmpeg process tree pruning via `psutil`.
- [x] **Active Feature: Phase 4 Secondary Content Engine UI (Complete)**: Executed a comprehensive UI pass refining the user experience of toggling and organizing Canvas secondary entities. Fixed layout overlap, corrected missing CSS tree-lines, built dynamic conditional widgets, injected custom radio component tooltips, and securely aligned backend default variables with the "In Course Folder" paradigm.
- [x] **Active Feature: Phase 3 Secondary Content Engine Backend (Complete)**: Architected and verified the full backend engine (`canvas_logic.py`, `sync_manager.py`) for downloading Assignments, Syllabus, Announcements, Discussions, Quizzes, and Rubrics using dynamically generated HTML artifacts and a Negative ID Offset Registry.
- [x] **Active Feature: Phase 2 Deferred Issues (Complete)**: Evaluated and implemented the deferred major/minor issues from the V1 Master Audit. Addressed JSON atomic writes, FFmpeg subprocess stalls, post-processing failure UI surfacing, and import hoisting. Dropped architectural monolith splitting for V2.0.
- [x] **Active Feature: V1.0 Master Audit Refinements (Complete)**: Executed the final 10 codebase fixes addressing edge cases, data concurrency, URL injection, and UX state persistence based on the final audit report.
- [x] **Active Feature: V1.0 Master Audit Roadmap (Complete)**: Executed the final critical blockers identified in the Master Audit Report (missing `time` import in `excel_converter`, unconditional COM imports in `word_converter`, XML `.webloc` string escaping, `tarfile` zip-bomb/traversal protection, and UI duplication extraction). The only remaining task is establishing a baseline test suite.
- **Ghost DB Receipt Fix**: Resolved a critical bug where secondary attachments (PDFs in announcements/assignments) were downloaded to disk but not recorded in the SQLite manifest due to an `AttributeError` (Interface Mismatch).
- **Interface Hydration (SimpleNamespace)**: Implemented `types.SimpleNamespace` to hydrate raw attachment dictionaries into dot-notation compliant objects, ensuring the existing `_download_file_async` pipeline can commit them to the database without modification.
- **Active Feature: V1.0 Polish Sweep (Complete)**: Executed the remaining Tier 2 and Tier 3 findings from the Master Audit Report. Centralized design tokens, added strict HTML escaping, hoisted inline imports, eliminated bare except clauses, and instituted a formal `version.py` tracker.
- **Active Feature: PyWebView Native Presentation**: Implemented a transition in the Windows executable from spawning an external browser tab to rendering Streamlit natively inside an encapsulated edge-based OS window using `pywebview`.
- **Active Feature: V3.0 Architecture Audit Fixes (Complete)**: Implemented deep structural fixes across the async download engine to permanently eradicate data loss edge cases, race conditions, and semaphore locks identified in the V3 audit.
- **Active Feature: V1.0 Audit Fixes (Complete)**: Implemented all Critical (🔴) and Major (🟡) fixes identified in the 360-degree Master Audit Report to ensure release readiness.
- **Active Feature: Saved Sync Groups (Phases 1-3 Complete)**: Full 3-phase implementation of reusable course/folder group management. Backend manager, save workflow, 3-layered Hub dialog, and pre-flight merge engine are all shipping.

- **DEEP QA AUDIT VERIFIED (V2 Fixes)**: Conducted an exhaustive code-reading audit of the V2 structural fixes. Verified Path Integrity (Absolute vs Basename separation), Structural Error Guards (preventing retry loops), Tuple Identity (O(1) mapping robustness), and ACID Transactions (Await-and-Inject pattern). Confirmed the engine is mathematically robust against orphaned attachments and state amnesia.
- **ARCHITECTURAL DESK-CHECK VERIFIED (Secondary Content & Retry)**: Performed a comprehensive QA assessment verifying 5 core pillars: Discovery & Pathing (synthetic negative IDs + true positive attachment IDs), two-layer Deduplication Safety, Sync Diffing (handling locally deleted subfolders), Download Execution (subfolder recreation and attachment passback), and Sniper Retry State (clean UI recovery without blanking).
- **GLOBAL POST-PROCESSING CANCELLATION GUARD (`app.py`)**: Identified and patched a critical vulnerability in the main download flow. Previously, the post-processing pipeline (`run_all_conversions`) lacked a cancellation check, allowing it to trigger even after a user aborted the download. This is now fully guarded by `cancel_requested` and `download_cancelled` state checks.

- **SYNC AMNESIA ERADICATED (`sync_ui.py`)**: Repaired a regression where "Retry Failed Downloads" in Sync Mode wiped historical session metrics. Refactored the internal `synced_counter` initialization within `download_sync_files_batch` to aggregate existing `st.session_state` progress dynamically during retries.
- **SUCCESS AMNESIA FIXED: Retry State Sandboxing (`app.py`)**: Engineered a definitive fix for the UI metric-wipe bug. Introduced `retry_isolated_details`, `retry_downloaded_items`, and `retry_failed_items` session state keys to sandbox retry operations. The application no longer clears global download metrics (`downloaded_items`, `download_file_details`) during a retry, preserving historical run data and preventing "Amnesia" after successful retries.
- **SERIALIZATION TRAP NEUTRALIZED: Safe Property Extraction (`app.py`)**: Fortified the Post-Retry Synthesis block against Streamlit's "Proxy Dictionary" serialization bug. Implemented a strict `getattr(obj, attr, None) if not isinstance(obj, dict) else obj.get(attr)` pattern for `course_name`, `item_name`, and `context`. This explicitly prevents `AttributeError` crashes when Streamlit converts `DownloadError` objects into dictionaries across session re-runs.
- **CONDITIONAL PROGRESS ROUTING (`app.py`)**: Bifurcated the `update_ui` callback logic. It now detects if `download_status == 'isolated_retry'` to route progress increments to either the sandbox or global state variables, preventing cross-contamination of metrics.
- **SAFE ERROR RESOLUTION & AUDIT LOGGING (`app.py`)**: Rewrote the reconciliation loop to safely compare retried file paths against historical errors. Resolved errors are now accurately removed from the UI list, counters are adjusted, and `[RESOLVED]` entries are appended to the local `download_errors.txt` log, ensuring an immutable record of the environment "fighting back."
- **REHYDRATION SYNTHESIS (`app.py`)**: Implemented a final merge stage that hydrates `download_file_details` with successes from the retry sandbox, ensuring that once the retry finishes, the "Done" screen reflects the absolute total state of the session.
- **UI PATH BLEED V2: Presentation/Data Separation (`app.py`)**: (Revised) Completely decoupled the data persistence from the UI presentation layer. `retry_isolated_details` now strictly stores the full OS-level `explicit_filepath` to ensure `post_processing.py` can resolve targets. The UI `render_folder_cards` function now extracts `Path(p).name` JIT, maintaining a pristine completion screen without breaking the backend.
- **STRUCTURAL ERROR LOOP GUARD (`app.py`)**: Implemented the `has_retriable_errors` boolean check. This evaluates if any items in the error list have file-specific context. The "Retry Failed Items" button is now hidden if only un-retriable structural errors remain, preventing infinite loops.
- **TUPLE IDENTITY DEFENSE (`sync_ui.py`)**: Fortified the O(1) hash map re-queuing logic against SQLite tuple decomposition. Injected a robust `getattr(failed_item, 'id', getattr(failed_item, 'canvas_file_id', failed_item[0] if isinstance(failed_item, tuple) else None))` fallback to prevent identity loss during Sync Mode retries.
- **ACID TRANSACTION FIX ("Orphaned Attachment Amnesia")**: Found and fixed a critical data-loss vulnerability in `sync_ui.py`. Previously, secondary entities (Assignments, pages) executed a database commit *before* their associated file attachments were queued. We decoupled the commit, updated `download_secondary_entity` to return `canvas_updated_at`, and now manually trigger the DB write strictly *after* all child attachments are safely injected into the async download queue.
- **SNIPER RETRY ACID REFACTOR ("Await-and-Inject")**: Completed a comprehensive architectural refactor of `download_isolated_batch_async` in `canvas_logic.py`. Replaced blind `asyncio` queueing with a strict "Await-and-Inject" pattern. The retry loop now synchronously awaits the discovery of secondary entities, unpacks the 4-tuple metadata, and executes an atomic database commit via `sync_manager.record_downloaded_file()` *before* dynamically injecting attachment download tasks into the live queue. This permanently eliminates "Database Amnesia" where parent entities were recorded while their children remained orphaned or lost.
## Recent Changes (Session 2026-03-23 — Native Button Card Architecture)
- **Native Button Card Architecture Implementation (`app.py`)**:
    - **Physical Overlap Pivot**: Abandoned brittle `position: absolute` and "Invisible Overlay" hacks in favor of styling native `st.button` widgets as cards. This guarantees the entire rectangular area is natively clickable and responsive.
    - **CSS-Driven Aesthetics**: Injected scoped CSS targeting `div[class*="st-key-btn_org_"] button` to apply backgrounds, padding, and border-radius.
    - **Pseudo-Element Metadata**: Utilized `::after` pseudo-elements to inject descriptive text ("Matches Canvas Modules", "All files in one folder") directly into the button surface without adding DOM bloat.
    - **Base64 Icon Integration**: Embedded `get_base64_image` icons directly into the CSS `background-image` property for zero-dependency visual fidelity.
    - **Dynamic Active Highlighting**: Implemented real-time border and background color shifts (`st.session_state['download_mode']`) using f-string CSS injection.
    - [x] **Segmented Control Injection**: Upgraded the "Include Files" segmented buttons by crushing stHorizontalBlock gaps, implementing flex-column layouts for vertical alignment, and separating icon states into ::before pseudo-element toggles.
    - [x] **Hover State Parity**: Injected global hover rules and active-state protection to ensure unselected cards react to mouse interaction without overriding the primary selection highlight.
    - **Interactive Hover Logic**: Integrated dynamic hover states for all Native Button Cards, including subtle background shifts and icon "wake-up" transitions (`filter: grayscale(10%)`) that are gracefully preserved or overridden by the active session state.

## Recent Changes (Session 2026-03-23 — Step 2 UI Structural Refactor)
- **3-Column Card Layout Implementation (`app.py`)**:
    - **Structural Geometry**: Transitioned "Step 2: Download Settings" from a vertical stack to a balanced `st.columns(3, gap="medium")` layout.
    - **Horizontal Symmetry Guard**: Enforced exact horizontal alignment by replicating the custom `<h3>` header structure at the top of each column, ensuring column borders and titles start at the same pixel-row.
    - **Logic & CSS Hoisting**: Hoisted all `@st.fragment` callbacks (like `folder_picker`) and multi-line CSS `<style>` blocks to the very top of `render_download_step2`. This prevents Streamlit from unmounting/re-rendering widgets mid-interaction when nested container states change.
    - **Container Modernization**: Replaced the previous `st.expander` for NotebookLM with a permanent `st.container(border=True)`. This grants the "Additional Settings" block the same visual weight as the primary "Organization" and "Content" cards.

## Recent Changes (Session 2026-03-22 — URL Pivot: Sync Engine Bypass)
- **Merge-Append Strategy (`url_compiler.py`)**: Upgraded the URL compiler from destructive overwrite to a stateful ledger system.
    - **State Hydration**: The script now reads `NotebookLM_External_Links.txt` on startup, extracting existing URLs into an in-memory `set` to prevent duplicates.
    - **Robust Parsing**: Implemented aggressive `.strip()` and strict `utf-8` encoding to prevent `UnicodeDecodeError` and ensure deduplication accuracy.
    - **Deduplication Logic**: Decoupled physical file management from text compilation; duplicate files are still unlinked even if their URLs are already in the ledger.
- **Extension Trap Guardrail**: Implemented strict path-suffix checking (`.url`, `.webloc`) in `sync_manager.py` loops (Phase 1, Phase 2, and Step 5) to accurately identify shortcuts regardless of unstable Canvas API metadata names.
- **Contract-Aware Bypassing**: The bypass logic is conditionally activated only when the `sync_contract` confirms that URL compilation is enabled for the specific course.

## Recent Changes (Session 2026-03-22 — Presentation Layer & Deduplication Fixes)
- **Data-Layer Deduplication for Sync Review UI (`sync_manager.py`)**: Implemented strict, O(1) string-based deduplication (`dedup_loc_del_ids` and `_phase1_locdel_seen`) in `analyze_course()` before yielding `locally_deleted_files`. This permanently neutralizes a critical `StreamlitDuplicateElementKey` crash when secondary content attachments with true positive IDs were surfaced from both module and secondary API scans simultaneously.
- **Physical Path Alignment (Path Blindness Fix) (`sync_ui.py`)**: Completely eradicated the "Path Blindness" bug in the Sync Review UI. Checkboxes now dynamically extract `Path(sync_info.local_path).name` to display the exact physical filename (e.g., `File (1).pdf`) instead of the generic Canvas API name. This ensures the UI perfectly matches the user's filesystem.
- **Success Screen Path Fidelity (`sync_ui.py`)**: Fixed "Success Screen Amnesia" by modifying `download_sync_files_batch` to populate the `synced_details` array and terminal logs with `filepath.name` (the actual collision-resolved name written to disk) instead of the pre-download display name.
- **Secondary Content Success Tracking (`sync_ui.py`)**: Standardized the secondary content success logs to inject `sec_filepath.name`, ensuring consistency across all syncable entity types.

## Recent Changes (Session 2026-03-22 — Sync Filename & Path Alignment)
- **Sync Filename Generation Alignment (`canvas_logic.py`)**: Fixed a bug where synthetic HTML files for Announcements were vanishing from the "Locally Deleted" bucket. Spliced the missing `date_prefix` logic into `get_secondary_content_metadata` to enforce 1:1 parity with the initial download manifest.
- **Sync Confirmation 0-Bytes UI Bug (`sync_ui.py`)**: Rectified a Python typing mismatch in the `total_bytes` redownload calculator. The integer-indexed Hash Map (`f.id`) was being queried using string-coerced SQLite IDs (e.g., `"-90001235"`), resulting in silent `.get()` failures and 0-byte fallbacks. Enforced string coercion `str(f.id)` universally across dictionary instantiation and lookups, accurately restoring file sizes in the "Confirm Sync" expander.
- **Attachment Path Flattening Defense (`sync_ui.py`)**: Fixed a parallel type-mismatch in `download_sync_files_batch` where target paths for redownloaded items defaulted to the `course_root`. Standardized `str(info.canvas_file_id) == str(getattr(file, 'id', None))` so the engine perfectly hooks the `_target_local_path` strings out of the SQLite mapping, guaranteeing missing attachments are restored to their precise subfolder (e.g., `Announcements/Weekly update/`) instead of flattening.

## Recent Changes (Session 2026-03-22 — Catch-All Overlap & UI Ledger Parity)
- **Catch-All Exclusion Parity (`canvas_logic.py`)**: Injected a dual-guard clause `if int(file.id) in {int(i) for i in downloaded_file_ids} or int(file.id) in {int(i) for i in module_file_ids}:` into the Catch-All phase. This ensures files processed via modules (even if skipped on disk) are never re-queued by the secondary scan.
- **Module ID Tracking (`canvas_logic.py`)**: Added `module_file_ids` set to the module execution loop to capture Canvas File IDs dynamically during the first pass.
- **Empty Message Ledger Bypass (`app.py`)**: Relocated `downloaded_items += 1` strictly inside the `if msg:` block for `skipped` progress types. This mathematically prevents "Phantom Skips" (files already on disk) from incrementing the UI numerator unless they are being reported to the user.
- **Signature Standardization Follow-up**: Fixed two leftover `local_relative_path` references causing `NameError` exceptions during secondary content sync in `sync_manager.py` (`add_file_to_manifest`) and `sync_ui.py` (`download_sync_files_batch`), successfully aligning them with the new `local_path` parameter signature.

- [x] **Post-Retry Synthesis Integrity (`app.py`)**: (NEW) Fixed a critical `IndentationError` on line 2103 where the reconciliation loop following successful retries was incorrectly indented outside its parent conditional block, causing the application to crash on launch.
- **RETRY ATTACHMENT UI FEEDBACK**: Integrated `progress_type='attachment'` into the `isolated_retry` completion block. This ensures that dynamically discovered attachments during a sniper retry correctly increment UI progress bars and reflect in the final "Done" screen metrics.
- **RETRY POST-PROCESSING CANCELLATION GUARD (`app.py`)**: Injected a `st.session_state.get('download_cancelled')` check at the start of the retry post-processing pipeline. If a user cancels a retry attempt mid-download, the application now correctly skips the sluggish conversion phase instead of falling through to the "overkill" loop.
## Recent Changes (Session 2026-03-21 — Structural Audit Execution & Guardrail Verification)
- **Signature Standardization (`sync_manager.py`)**: Renamed `local_relative_path` to the standard `local_path` in the `record_downloaded_file` signature and dictionary mapping to ensure SQLite manifest strings are correctly populated.
- **ACID Commit Guard Update (`canvas_logic.py`)**: Performed a global sweep and updated all 11 explicit calls to `sync_manager.record_downloaded_file` to pass the correct `local_path` keyword.
- **Dynamic UI Metrics (`app.py`)**: Refactored `render_dashboard` to pull `total_mb` dynamically from `st.session_state` and added a `max(0, active_total_mb - current_mb)` guard to permanently eradicate negative "Time Remaining" overflows.
- **Byte-to-MB Conversion Hook (`app.py`, `canvas_logic.py`)**: Injected `size=att.get('size', 0)` into the attachment `progress_callback` and implemented a strict `(size / (1024 * 1024))` conversion factor in the `update_ui` state mutator to ensure progress metrics remain accurate for multi-megabyte attachments.

## Recent Changes (Session 2026-03-21 — Secondary Entity Extraction & Manifest Parity Audit)
- **UI Lexical Scope Fix (`app.py`)**: Resolved the metric fraction lock (e.g., 64/31 stuck) by refactoring `render_dashboard` to pull `active_total` and `active_current` from `st.session_state` at render-time. The UI now dynamically reflects increments to the file count and total items.
- **Step 5 Order of Operations Fix (`sync_manager.py`)**: Corrected an logic error in the diffing engine where synthetic entities were being bypassed even if they were missing locally. Implemented a strict `if (not exists) / elif (is_synthetic) / else (deleted_on_canvas)` structure to ensure missing files are always detected first.
- **Registry Expansion (`sync_manager.py`)**: Fixed a fatal `KeyError` by mapping `'attachment': 60000000` to the `SECONDARY_ID_OFFSETS` dictionary.


## Recent Changes (Session 2026-03-21 — Attachment ID Reversion & Retry UI Fix)
- **Attachment ID Scheme Reverted (`canvas_logic.py`)**: Reverted `make_secondary_id('attachment', id)` to use true positive Canvas `file.id` for all attachments within Assignments, Discussions, etc. This ensures correct SQLite manifest deduplication.
- **Negative ID Decoding Removed (`canvas_logic.py`, `sync_ui.py`)**: Stripped all "refresh/decode" logic associated with negative attachment IDs since they are no longer in use. Entities themselves (HTML) still use negative IDs.
- **Sync Retry UI Blanking Fixed (`sync_ui.py`)**: Injected `st.session_state['sync_cancelled'] = False` into the "Retry Failed Downloads" button callback. This prevents a stale cancel flag from causing a blank screen/short-circuit during the retry phase.
- **Verification & Compilation**: Verified zero remaining `make_secondary_id('attachment'` references and confirmed the codebase compiles cleanly (`py_compile`).

## Recent Changes (Session 2026-03-21 — Login & Import Troubleshooting)
- **CANVAS API LOGIN RESTORED (`canvas_logic.py`)**: Resolved a fatal login failure where `CanvasManager` was passing an invalid `request_kwargs={'timeout': 30}` argument to the `Canvas` constructor. This argument was found to be unsupported by the installed `canvasapi` version, causing silent initialization failures and subsequent "Check your URL" warnings.
- **IMPORT NAMESPACE CORRECTION (`canvas_logic.py`)**: Fixed an `ImportError` where `CanvasFileInfo` was being incorrectly imported from `ui_shared`. It has been correctly rerouted to its true origin in `sync_manager.py`.
- **UI RECONCILIATION INDENTATION FIX (`app.py`)**: Corrected an `IndentationError` in the "Retry Failed Items" completion block that prevented the script from compiling.
## Recent Changes (Session 2026-03-21 — ACID Retry Architecture Refactor)
- **Await-and-Inject Pattern Implementation (`canvas_logic.py`)**: Refactored the sniper retry loop to handle complex entities (Assignments, Quizzes, Discussions) with mathematical precision. The engine now halts to unpack `(sec_filepath, sec_id, sec_attachments, canvas_updated)` returns, ensuring the parent is committed to SQLite with its true Canvas timestamp before any children are spun off into the background.
- **Async Task Injection**: Implemented dynamic `asyncio.create_task` calls within the retry loop. Discovered attachments are minted as `CanvasFileInfo` objects and "injected" directly into the running task list, inheriting the main loop's error handling and semaphore protections.
- **Strict Path Relay V2**: Validated that `retry_isolated_details` strictly stores absolute OS paths, while the UI utilizes JIT `Path(p).name` extraction. This preserves backend file resolution for post-processing while maintaining a clean, basename-only presentation layer.

## Recent Changes (Session 2026-03-20 — Retry Logic Audit & Final Architecture Fixes)
- **Direct Path Relay for Retry Loop (`app.py`, `canvas_logic.py`)**: Completely abandoned "String Hacking" and `_clean_display_name` wrappers parsing terminal output strings to rebuild target `os.path` targets. Upgraded the entire `isolated_retry` infrastructure to strictly ingest the exact `explicit_filepath` injected directly by the async download engine into the UI callback args. This permanently solves the silent post-processing retry failure and Path Flattening overlap bugs (Bug 1 & 3).
- **Asynchronous File Mutexing for Legacy Shortcuts (`canvas_logic.py`, `sync_ui.py`)**: Identified a critical source of Event Loop blocking where `.url`, `.webloc`, and `.html` shortcuts were being generated using synchronous `open()` contexts. Refactored `download_isolated_batch_async` and `download_sync_files_batch` to use `aiofiles.open(str(filepath.resolve()), ...)` with robust string casting to circumvent Windows-specific `Path` string coercion bugs (Bug 2).
- **'Skipped' UI Router (`app.py`)**: Fixed an accounting UI desync where `update_ui` lacked a `elif progress_type == 'skipped':` branch. Skipped items are now accurately tallied and injected into `st.session_state['download_file_details']` using their `explicit_filepath`, ensuring downstream post-processing accurately tracks files bypassed during isolated retries (Bug 4).
- **REGRESSION DEFENSE IMPLEMENTATION (Strict Typing & Context Safety)**: Engineered structural safeguards to lock in retry logic stability. Implemented `safe_thread_wrapper` in `canvas_logic.py` using `add_script_run_ctx` for async Streamlit context propagation. Enforced strict `Dict[int, CanvasFileInfo/SyncFileInfo]` type hinting in `sync_ui.py` with PEP-8 compliant module-level import hoisting.
- **POST-PROCESSING EFFICIENCY: Targeted Retry Harvest (`post_processing.py` & `app.py`)**: Eradicated the "overkill" bug where retrying a single file triggered re-processing of the entire course directory. Refactored `run_all_conversions()` and `_glob_files()` to support a normalized, absolute-path `explicit_files` list. `app.py` now harvested successful downloads directly from `st.session_state['download_file_details']`, accurately targeting only the retried files for conversion.
- **PATH NORMALIZATION GUARD (`post_processing.py`)**: Implemented strict `Path(p).resolve()` sets for file comparison inside the converter's globbing logic. This prevents cross-platform slash mismatch bugs (\ vs /) and ensures that explicit file targeting is mathematically robust.
- **SYNC IDENTITY PRESERVATION: O(1) Hash Map Re-Queuing (`sync_ui.py`)**: Solved the `_NewVersion` identity loss bug. When retrying failed "updates" or "redownloads," the app now uses Dictionary Hash Maps to pre-index the original structured objects (e.g., `CanvasFileInfo` with its `_NewVersion` flag). By "plucking" from the map using `getattr(id)` or tuple keys, the retry logic correctly preserves the original download intent, preventing incorrectly renamed conflict files.
- **FINAL RETRY ARCHITECTURE AUDIT**: Conducted a definitive codebase audit verifying that "Sniper Retries" strictly download only failed files, handle directory creation fails (`Path.mkdir`), orchestrate state-rehydration safely via `retry_selections`, and bypass Streamlit UI threads appropriately in both modes.
- **DEEP DIVE POST-PROCESSING BUGFIX (`app.py`)**: Fixed a severe logic gap in "Sniper Retry" where valid absolute paths were erroneously filtered through `cm._sanitize_filename(n)`, destroying file paths (removing `:` and `\`) and causing 100% of retried files to be skipped in the conversion step.
- **DEEP DIVE SYNC WIZARD ROUTING BUGFIX (`sync_ui.py`)**: Repaired an infinite UI loop triggered by the "Retry Failed Downloads" button in Sync Mode by natively injecting the explicit phase variable (`st.session_state['step'] = 3`).

## Recent Changes (Session 2026-03-20 — Sync Retry Architecture Fixes)
- **CRITICAL: Streamlit Re-hydration Crash Eradicated (`sync_ui.py`)**: Completely decoupled the synchronous `cm_retry.get_course(course_id)` Canvas API call from the Streamlit button callback (`"Retry Failed Downloads"`). It now safely passes a null blueprint (`course=None`) down to the async execution block (`download_sync_files_batch`). The async pipeline uses `await asyncio.to_thread` to securely open the network channel, catching endpoints timeouts and natively returning error logs to the Streamlit UI without crashing the global user session.
- **ThreadContext Boundary Protection (`sync_ui.py`)**: Secured the transition natively off the Streamlit main thread by explicitly extracting `api_token` and `api_url` from `st.session_state` *before* invoking `asyncio.run()`, successfully preventing `StreamlitAPIException` (missing ThreadContext) crashes.
- **STRUCTURAL FLAW: Discovery Omission Tracking (`sync_manager.py` & `sync_ui.py`)**: Modified the `AnalysisResult` dataclass to structurally track deep API failures (e.g., 500 error when scanning Canvas module folders) during the Course Analysis step by incrementing a new `structural_errors` metric. Added a visually matching `st.warning` in the Sync Completion screen that warns the user if entire modules were silently dropped due to backend API unavailability, alerting them that targeted "Sniper Retries" cannot recover these missing files and a full course rescan is necessary.

## Recent Changes (Session 2026-03-19 — Secondary Content Sync Diagnostics & Architecture Restructure)
- **Add Course Folder to Sync UI Polish (`sync_ui.py`)**: Increased the width of the main `Add Course folder to Sync` button by 50% to prevent text wrapping, and adjusted its top margin from `-35px` to `-50px` to halve the visual distance to the pair cards above it. Also enforced `use_container_width=True` and a `2.25` column ratio on the empty-state variant to ensure visual uniformity across all states.
- **Empty State UI Polish (`sync_ui.py`)**: Adjusted the top margin of the empty state `Add Course folder to Sync` button (` margin-top: -10px`) to pull it closer to the top edge of its container, refining the visual alignment in the Sync Review screen.
- **False-Positive HTML Updates Fixed**: Overhauled `_is_canvas_newer()` in `sync_manager.py` to immediately return `False` for all IDs in the negative secondary content registry (`id < 0`). Time-based diffing for synthetic entities was inherently flawed due to Canvas API timestamp drift frequently exceeding the 300s tolerance window. Local existence is now the sole diffing check for secondary HTML files.
- **Split-Brain Pathing Resolved**: Uncovered and fixed a critical namespace divergence in `get_secondary_content_metadata()`. Extracted inline attachments are now dynamically prefixed with their parent entity's exact subfolder structure (e.g., `Assignments/MyAssignment/document.pdf`) before being wrapped into `CanvasFileInfo` objects, enabling the sync engine to properly track and cross-reference them against the local manifest.
- **Zero-Byte Synthetic Auto-Discovery**: Handled an edge-case in `analyze_course()` preventing recovery of lost manifests. Bypassed the strict `local_size == c_file.size` auto-discovery parity check exclusively for negative-ID entities, since SQLite records them strictly as `original_size=0` while physical extraction creates padded 5-50KB HTML artifacts locally.
- **Manifest Naming Asymmetry Addressed**: Repaired `_save_secondary_entity()` to explicitly pass the full prefixed path (e.g. `Assignments/...`) into the SQLite wrapper's `canvas_filename` parameter, eradicating memory asymmetry between the backend deduplication loop and bare basename storage.
- **Safe Path Sanitization (Sync Loop)**: Fixed a path-traversal regression in `sync_ui.py` where `_sanitize_filename` was mangling directory slashes in subfolder-prefixed attachment names. Implemented `Path.parts` extraction to isolate and sanitize only the final component, preserving the `/` separators.
- **Bulletproof Attachment Deduplication**: Injected a dynamic hash set guard (`_queued_ids`) into the sync loop's attachment offloading routine. This actively tracks IDs during iteration, preventing both cross-queue duplication (HTML + attachment deleted) and intra-document duplicate links from triggering redundant downloads.

## Recent Changes (Session 2026-03-19 — Secondary Content Path Divergence & Performance)
- **Dynamic Scanning Phase (`canvas_logic.py`, `app.py`)**: Introduced an `is_scanning_phase` boolean flag passed from the `app.py` UI down into `get_course_files_metadata` and `get_secondary_content_metadata`. This dramatically improves initial load performance by deliberately skipping expensive individual `course.get_assignment()` API calls during the analysis phase, relying instead on aggregate Canvas list endpoints.
- **Dynamic Totals Incrementing (`app.py`)**: Integrated a reactive UI lock in `update_ui` that manually increments `st.session_state['total_items'] += 1` uniquely when `progress_type == 'attachment'` triggers. This elegantly resolves `[x/y]` file count visual overlap bugs (where downloaded files eclipsed the initial scanned total) that occurred due to skipping deep-attachment scanning for performance.
- **Structural Integrity & Path Parity (`canvas_logic.py`)**: Natively bound the `CanvasFileInfo` data model directly to the `_ENTITY_ROUTING` dictionary. Filenames for all 6 secondary entity types (Assignments, Quizzes, Discussions, etc.) now correctly inherit their prefix directories (e.g., `Assignments/Name.html`) and subdirectories (e.g., `Assignments/Name/Name.html` for attachments), guaranteeing the Sync engine's path analysis perfectly mirrors the physical extraction layout built by the initial Download engine.

## Recent Changes (Session 2026-03-19 — Discussion & Announcement Reply Fetching)
- **Recursive Reply Engine (`canvas_logic.py`)**: Developed `_build_discussion_replies_html_sync` to recursively fetch and render threaded Canvas discussion replies. Offloaded via `asyncio.to_thread` to prevent event loop blocking.
- **Canvas Rich Text Preservation (`canvas_logic.py`)**: Explicitly removed `esc()` sanitization from the core `message` body of discussion replies. Since Canvas returns pre-formatted HTML from its Rich Text Editor, escaping the string destroyed the document structure. Author names, dates, and attachment URLs remain strictly escaped.
- **Threaded UI Aesthetic (`canvas_logic.py`)**: Implemented a Notion-style chatroom design with `3px solid #3b82f6` left-borders for nested hierarchy, system font stacks, and delicate margin controls.
- **UI Bug Fixes**: Resolved the "Literal `\n` String" bug by correcting the string joiner logic. Fixed "Massive Vertical Gaps" by removing `white-space: pre-wrap;` and allowing block-level `<p>` tags to govern their own margins.

## Recent Changes (Session 2026-03-19 — Secondary Content Inline Attachments & Metadata)
- **Assignment Inline HTML Parsing (`canvas_logic.py`)**: Implemented `_extract_canvas_file_links()` utilizing `beautifulsoup4` to recursively parse raw HTML descriptions within Assignments. This resolves a critical limitation where instructors embed Canvas file links (`<a href="/files/...">`) directly inside the text editor rather than using the native `attachments` array. Discovered links are routed through a `try/except (Unauthorized, ResourceDoesNotExist)` block around synchronous `course.get_file(id)` calls to gracefully skip dead links without crashing the async loop.
- **Positive ID Parity for Inline Links (`canvas_logic.py`)**: Validated that all inline-discovered file attachments are fed into the system using their true, positive Canvas API IDs. This architectural decision guarantees they integrate perfectly with the SQLite `canvas_sync.db` deduplication engine.
- **Universal Metadata Hydration (`canvas_logic.py`)**: Executed a sweeping update across all 6 secondary content generators (Assignments, Quizzes, Discussions, Announcements, Syllabus, Rubrics). Injected the target entity's `html_url` property into the payload `metadata` arrays for both the initial download pipeline and the active sync engine.
- **Clickable Hyperlink Rendering (`canvas_logic.py`)**: Modified the central HTML template builder `_build_entity_html` to auto-detect metadata values starting with `http://` or `https://`. These raw URLs are now wrapped in `<a href="..." target="_blank">` anchor tags, converting the static metadata row into a functional springboard bridging the offline HTML document directly back to the active Canvas page.

## Recent Changes (Session 2026-03-19 — Secondary Content Post-Fix Bug Fixes)
- **Attachment Pathing Normalization (`sync_ui.py`)**: Resolved a critical path-traversal bug where Assignment and Announcement file attachments were generating absolute OS paths instead of relative project paths (`file.relative_to(local_path)`). This absolute path was crashing the download loop when passed to `CanvasFileInfo`.
- **Sync Review UI Crash (`sync_ui.py`)**: Fixed a `TypeError` destructuring crash during the presentation of the "Updates Available" table. Modified the visual iteration loop to access object properties (`f.size`) instead of attempting to treat the Canvas objects like tuples (`f[0].size`).
- **Universal Attachment Offloading (`canvas_logic.py`, `sync_ui.py`)**: Modified the architecture of `download_secondary_entity()` to return a 3-tuple `(filepath, synthetic_id, attachments)`. This extracts inner Canvas files (e.g. Assignment attachments) and allows `sync_ui.py` to mint real, positive ID `CanvasFileInfo` objects containing direct URLs, dynamically appending them to the active `all_files` sync iteration queue. This allows attachments to inherently benefit from the main async loop's retries, `.part` atomicity, and cancellation monitoring.
- **Canvas API Timestamp Drift Tolerance (`sync_manager.py`)**: Solved the False Positive "Updates Available" bug affecting synthetic entities by injecting a 60-second tolerance window into `_is_canvas_newer()` strictly for IDs matching the secondary content negative registry ranges (`id <= -10000000`).
- **Sync Review Tuple Crash (`sync_ui.py`)**: Resolved a `TypeError: 'CanvasFileInfo' object is not subscriptable` in `_show_analysis_review()` layout logic by correctly referencing `f.size` instead of `f[0].size` after the variables had already been destructured from the initial payload tuples.

## Recent Changes (Session 2026-03-19 — Metric Card UI Hotfix)
- **Inactive Metric Card Styling (`sync_ui.py`)**: Resolved a CSS parsing bug where literal Python f-string brackets (`"{theme.SUCCESS_ALT}"`) were inadvertently passed directly to the `_render_metric_card` function rather than being evaluated. This generated invalid CSS (e.g. `linear-gradient(..., {theme.SUCCESS_ALT}1A)`), causing modern browsers to silently drop the background and border properties for zero-value sync counters. Removed the string wrappers, allowing proper hex resolution and restoring the intended muted/dimmed aesthetic for inactive file type metrics.

## Recent Changes (Session 2026-03-14 — Native PyWebView Encapsulation & Size Optimization)
- **Executable Size Optimization (`Canvas_Downloader.spec`)**: Resolved massive Python bloating (~350MB executable size) caused by Streamlit's `collect_all` directive improperly bundling heavy data science and AWS libraries. Added `polars` (~154MB) and `botocore`/`boto3` (~17MB) into the PyInstaller `excludes` list. The final application now properly targets a ~130MB baseline footprint, accommodating the core framework and the 83MB FFmpeg Engine needed for video audio extraction. User specifically elected to retain `tkinter` dependencies to preserve native Windows File Explorer dialog pickers.
- **Windows Browser Evasion (`start.py`)**: Stripped the legacy `tkinter` dependency from the `CanvasLauncher` class and rewrote the global script lifecycle to use a blocking `pywebview` window. The Streamlit backend now effectively masquerades as a true native desktop application on Windows, removing reliance on unpredictable external web browsers like Chrome or Edge.
- **Dependency Pipeline Updated (`Canvas_Downloader.spec`)**: Rewrote the PyInstaller build graph to execute `collect_all('webview')`, physically packing `EdgeWebView2` bootstraps into the binary while leaving the untouched macOS equivalent unaffected by this UI shift.

## Recent Changes (Session 2026-03-13 — Phase 7: Audited Concurrency & Security Fixes)
- **Resolved SQLite Win32 IO Sharing Violation (`sync_manager.py`)**: Removed all `os.name == 'nt'` `_windows_unhide_file()` attribute flags from within the `save_manifest` and other DB transactional methods. This solves the core trace of concurrent thread locks thrown by SQLite operations being interrupted by Windows Defender / OS-level file permission assertions mid-write.
- **Asyncio Sync Mutexing for File Paths (`sync_ui.py`)**: Designed and injected `manage_sync_download_lock` into `_run_sync`. A global `_sync_lock_mutex` now serializes dictionary bindings that vend `asyncio.Lock()` objects uniquely keyed per physical file path. This successfully throttles concurrent network threads downloading the same resource across dual cross-mapped courses without duplicating handles or mangling raw byte streams inside `aiofiles`.
- **Atomic Windows Replacing with Deep Permission Guards (`sync_ui.py`, `canvas_logic.py`)**: Eradicated the legacy `os.rename` approach for completing `.part` downloads on Windows, substituting it with the atomic OS primitive `os.replace`. Recognizing that Windows rigidly enforces file usage (unlike POSIX), embedded explicit `PermissionError` (`[WinError 32]`) exception blocks. If a user natively opens a target file (e.g. Acrobat Reader viewing a syllabus) during a sync loop, the application intercepts the crash, surgically unlinks the redundant `[].part` payload, and bubbles an intelligent log message, avoiding an overarching fatal exit.

## Recent Changes (Session 2026-03-13 — Phase 6 Final Architecture Audit Resolution)
- **Async SQLite Unblocking (`canvas_logic.py`)**: Offloaded the synchronous `record_downloaded_file` database commit directly into a background thread utilizing `await asyncio.to_thread`. This definitively stops heavy IO writes from pausing the core concurrent asyncio event loop.
- **Asyncio Memory Leak Fixed (`canvas_logic.py`)**: Purged the unbound `_download_locks` dictionary memory leak by structurally deploying an `@asynccontextmanager`. Locks now employ a dynamic reference `count`; when the active count reaches zero, the specific path's `asyncio.Lock()` is explicitly deleted from memory via `try...finally`.
- **JSON TOCTOU Race Eradicated (`ui_helpers.py`, `sync_manager.py`)**: Discovered that `.tmp` atomic replacements did *not* resolve the TOCTOU issue where two simultaneous Read-Modify-Write threads would blindly overwrite each other's updates. Completely rewrote `save_sync_pairs` into `atomic_update_sync_pairs` and `SavedGroupsManager` routines by wrapping their execution in robust `threading.Lock()` mutexes.
- **PowerShell PyInstaller Safety (`ui_helpers.py`)**: Substituted the unstable Streamlit-Tkinter `sys.executable -c` Windows folder picker string. Deployed a highly-reliable `powershell.exe -Command` wrapped string invoking `System.Windows.Forms.FolderBrowserDialog`. This perfectly aligns with the PyInstaller constraint on preventing thread-based crashes.
- **Definitive Zombie Pruning (`video_converter.py`)**: Integrated `psutil` into the `moviepy` executor. In instances where corrupt video payloads completely stall FFmpeg, abandoning the `Future` is no longer acceptable. The timeout loop now actively crawls the `Process` tree to systematically send forceful termination signals (`kill()`) to the exact worker processes, guaranteeing resource reclamation.

## Recent Changes (Session 2026-03-13 — Phase 4 Secondary Content Engine UI)
- **UI Architecture Sequencing (`app.py`, `sync_ui.py`)**: Restructured the visual flow of the secondary content configuration block. Checkboxes ("Select what to include") now deliberately precede structural routing decisions ("Organize by:"), aligning the UI with standard user intent models.
- **Dynamic UX Condensing**: Engineered the structural radio buttons ("In Course Folder" vs "In Subfolders") to collapse entirely into a null state if `_active == 0` (no secondary checkboxes selected), eliminating extraneous cognitive load.
- **Component Limitation Bypassing**: Streamlit's `st.radio` lacks granular `help=""` tooltips per option. Engineered a seamless workaround by injecting a custom HTML `div` below the radio group with grayed-out `ⓘ` instructional text matching standard Streamlit aesthetics.
- **Initialization State Alignment**: Purged 8 instances of `True` (In Subfolders) defaulting for `isolate_secondary_content` / `dl_isolate_secondary` scattered across SQLite handoffs, session states, and initial renders, unifying the application around the safer `False` ("In Course Folder/Modules") baseline.
- **CSS Variable Injection Repair**: Traced and fixed a CSS rendering bug where the vertical tree-lines disappeared. Replaced broken literal `{theme.BG_CARD_HOVER}` enclosed in triple quotes with active Python string concatenation to ensure the `bg_card_hover` hex correctly interpolated into the style block.
- **Precision Hitbox Padding (`margin-bottom`)**: Resolved a Streamlit layout engine defect where negative margins (`margin-bottom: -15px`) on text labels caused transparent hitboxes to overlap and physically block clicks on checkboxes directly beneath them. Margins were carefully audited and relaxed to `margin-bottom: 0px` combined with dynamic `margin-top` adjustments to preserve tight visuals without sacrificing interactive integrity.

## Recent Changes (Session 2026-03-12 — Phase 3 Secondary Content Engine Backend)
- **Negative ID Offset Registry (`sync_manager.py`)**: Designed a 10-million wide integer range registry (`SECONDARY_ID_OFFSETS`) per synthetic entity. This safely records HTML-wrapped Canvas entities (like Assignments `-10M` or Quizzes `-50M`) in the SQLite database without risking primary key collisions with real Canvas file IDs.
- **Universal HTML Construction (`canvas_logic.py`)**: Centralized the payload conversion logic into `_build_entity_html()` and `_save_secondary_entity()`, guaranteeing all 6 new Canvas entities receive consistent, styled HTML bodies embedding metadata (due dates, total points).
- **ISO 8601 Date Formatting Engine (`canvas_logic.py`)**: Built `_format_canvas_date` to globally intercept and parse raw UTC ('Z') timestamp strings directly within the HTML metadata generation loop. Canvas API dates (e.g., `2025-08-26T14:07:50Z`) are now automatically evaluated against the user's local operating system timezone and cleanly rendered into human-centric ordinal formats (e.g., `August 26th, 2025 at 14:07`) before being wrapped in the modern UI cards.
- **Modern Responsive Document Styling (`canvas_logic.py`)**: Completely overhauled the injected HTML/CSS payload for secondary entities. Transformed the raw 1990s Canvas HTML text into a sleek, Notion-style reading experience. Injected a `-apple-system` font stack, a light grey `--bg-canvas` backdrop, and a clean white 60%-width document "Card" container with a soft drop shadow (`box-shadow: 0 4px 6px -1px rgba(...)`). Implemented responsive breakpoints (`80%` on medium, `95%` on mobile) and heavily stylized the metadata block with left-border accent colors (`#3b82f6`) and bold labels. Styled inner Canvas HTML elements like tables, responsive images, code blocks, and blockquotes for perfect offline readability.
- **Mode A/B Routing System (`canvas_logic.py`)**: Implemented `_resolve_secondary_path()` to support two physical layouts: Mode A (Inline injection using prefixed names like `Assignment: Homework.html`) and Mode B (Isolated subfolders like `Assignments/Homework.html`).
- **True Positive ID Attachment Handling (`canvas_logic.py`)**: Resolved a critical architectural flaw by strictly tracking Assignment and Announcement attachments via their true Canvas `file.id`. This ensures perfect SQLite deduplication if the exact same file exists natively in the instructor's 'Files' tab.
- **Sync Plane Integration (`canvas_logic.py`)**: Expanded `_get_files_from_modules()` to emit mock `CanvasFileInfo` objects for secondary items found directly inside modules. Added `get_secondary_content_metadata()` to fetch and merge standalone entities into the main diffing pipeline, granting full visibility to the Sync UI.

## Recent Changes (Session 2026-03-12 — Phase 2 Deferred Issues)
- **JSON Atomic Writes (`sync_manager.py`)**: Migrated the non-atomic `add_entry` logic in `SyncHistoryManager` to write payload data sequentially to a `.tmp` file before executing a secure `os.replace()`, preventing unrecoverable `.json` corruption if the thread crashes mid-save.
- **FFmpeg Hang Protection (`video_converter.py`)**: Wrapped `moviepy`'s internal `.close()` calls within an isolated `ThreadPoolExecutor`. If the underlying FFmpeg subprocess hangs indefinitely on a corrupt video fragment, the 10-second `timeout` guard cleanly abandons the thread instead of paralyzing the entire download queue.
- **Failure UI Visibility (`app.py`, `sync_ui.py`, `post_processing.py`)**: Added semantic `pp_success_count` and `pp_failure_count` attributes to the `UIBridge` dataclass. The 7 converter runners now actively push failure state. Wired `st.session_state` persistence to permanently warn users via a UI banner on the final completion screens if any post-processing hooks trigger a conversion failure.
- **Import Optimizations (`app.py`, `canvas_logic.py`)**: Cleaned up the module headers. Hoisted `platform` and `base64` strictly to module-level imports, stripped redundant inline `aiofiles` and `shutil` duplicates, and actively block-commented the intentional deferred status of `streamlit` inside core logic to preserve framework independence.

## Recent Changes (Session 2026-03-12 — V1.0 Final Blockers & Polish)
- **Atomic Data Integrity (`canvas_logic.py`)**: Secured the `shutil.move` cross-drive fallback with a `try/finally` block to proactively `os.unlink` partially transferred destination files if the move process crashes or is interrupted.
- **Path Divergence Fix (`canvas_logic.py`)**: Prevented `_handle_conflict()` from mutating filenames that were explicitly requested via `explicit_filepath` and already deduplicated upstream by the module parser.
- **SQLite Concurrency Defense (`sync_manager.py`)**: Upgraded `ignore_file` and `restore_file` to use an explicit 3-retry loop wrapped around `sqlite3.connect(timeout=30.0)`, aligning manual UI triggers with the exact lock-contention resilience used during bulk syncing.
- **INI Injection Prevention (`canvas_logic.py`)**: Sanitized Canvas URLs payload strings by strictly stripping `\r\n` characters before embedding them within the `.url` Windows shortcut format.
- **Session Bleed Prevention (`app.py`)**: Fixed a severe UX glitch where completing a download maliciously wiped the application's authentication state (`canvas_downloader_token`, `auth_status`) and customized user paths. `keys_to_keep` is now defensively expanded.
- **Cache Stagnation (`app.py`)**: Enforced a `ttl=600` parameter on the `@st.cache_data` Course List fetcher, forcing the app to rehydrate course data every 10 minutes rather than locking stale layouts infinitely.
- **Filesystem Dotfile Preservation (`canvas_logic.py`)**: Modified `_sanitize_filename` from `.strip('. _')` to `.lstrip(' _').rstrip('. _')` to preserve vital leading dots for dotfiles (`.gitignore`, `.env`) while still neutralizing trailing period OS bugs.
- **Namespacing & Clean Logging (`sync_manager.py`, `sync_ui.py`)**: Elevated `compute_local_md5` from a monkey-patched assignment into a strict `@staticmethod` within `SyncManager`, and eliminated terminal noise in `sync_ui.py` by converting raw `print()` loops into standard `logger.debug()`.

## Recent Changes (Session 2026-03-11 — V1.0 Final Clearance Execution)
- **AppleScript Lifecycle Controller (macOS)**: Completely rewrote the `start.py` macOS launcher. Scrapped the infinite loop to avoid zombie processes. Replaced it with a native, blocking AppleScript dialog (`osascript` "Open Browser" / "Stop Server") that controls the Streamlit daemon thread and allows smooth, user-driven graceful termination.
- **Path Traversal Guard (`archive_extractor.py`)**: Implemented a mandatory manual path validation check (`os.path.abspath(os.path.join(...)).startswith(...)`) for `tarfile` extraction on Python versions < 3.12 lacking the `data_filter` attribute.
- **Theme Color Interpolation (`post_processing.py`)**: Corrected 19 instances where `theme.XYZ` constants were rendered as literal strings instead of evaluated f-strings (including 3 `_COLOR_MAP` entries and 16 `_log_msg` calls).
- **Graceful Subprocess Cleanup (`video_converter.py`)**: Restructured the moviepy audio extraction logic within a `try/finally` block to explicitly call `.close()` on both the audio subclip and the main video clip, stopping FFmpeg subprocess leaks.
- **Database Lock Defense (`sync_manager.py`)**: Hardened the concurrent SQLite writes inside `update_converted_file` by injecting `timeout=30.0` into the `sqlite3.connect` call.
- **2026-03-20**: **Retry Logic Audit & Sniper Fixes**:
    - Conducted a comprehensive audit of the "Retry Failed Items" functionality across both Download and Sync modes.
    - Fixed a critical state leak in `app.py` where `st.session_state['seen_error_sigs']` was not being reset during retries, leading to silenced error logs.
    - Resolved a `FileNotFoundError` in `canvas_logic.py` within the `download_isolated_batch_async` loop (Sniper Retry) by adding explicit `Path.mkdir(parents=True, exist_ok=True)` logic to ensure target directories exist before file writes.
    - Verified that Sync Mode's retry logic is already robust due to its re-hydration of the full `CanvasManager` context and existing directory creation guards.
- **Error Visibility & Noise Reduction**: Upgraded fallback scan errors in `canvas_logic.py` from silent `pass` to `log_debug`; stripped `esc()` HTML escaping from plaintext error logs in `post_processing.py`; moved `datetime` imports out of inner loops in `app.py`; and ensured `BaseException` catches globally re-raise `KeyboardInterrupt` / `SystemExit`.

## Recent Changes (Session 2026-03-11 — macOS V1.0 Polish & Crash Fixes)
- **Tkinter Thread-Bomb Eradicated (`ui_helpers.py`)**: Rewrote `native_folder_picker()` to branch for Darwin and use `osascript` subprocess calls (`choose folder`), avoiding main-thread Tkinter segfaults when called from Streamlit background threads.
- **AppleScript UX Hang Prevention (`ui_helpers.py`)**: Upgraded the `native_folder_picker()` `osascript` payload to explicitly force the prompt to the foreground (`tell application (path to frontmost application as text)`). Bound the subprocess to a strict 60-second timeout catching `subprocess.TimeoutExpired`, permanently neutralizing a critical UX freeze where backgrounded dialogs could lock the Streamlit execution thread indefinitely.
- **Finder Foreground Forcing (`ui_helpers.py`)**: Enhanced `open_folder()` on macOS to use a dual-command flow (`open -R` followed by `osascript tell application "Finder" to activate`) to force the window cleanly to the foreground.
- **AppleScript GUI Dialog Hangs (`*_converter.py`)**: Injected `set display alerts to false` (and `wdAlertsNone`) into the AppleScript execution strings for Excel, Word, and PPTX to permanently suppress blocking native GUI dialogs that previously hung the conversion pipelines.
- **Hidden File Windows API Guard (`sync_manager.py`)**: Added strict `os.name != 'nt'` early exits to `_windows_hide_file` and `_windows_unhide_file` to completely shield macOS and Linux environments from fatal `ctypes.windll` exception crashes.
- **macOS Build Entitlements (`Canvas_Downloader_macOS.spec` / `entitlements.plist`)**: Generated a dedicated `entitlements.plist` activating the `com.apple.security.automation.apple-events` permission. Integrated this into the macOS PyInstaller build spec to ensure the compiled `.app` bundle is trusted by the OS to trigger external Office automation processes.
- **Keychain Prompt Evasion (`app.py`)**: Designed a sophisticated bypass for macOS `keyring` permission loops. On Darwin, Canvas API tokens are now structurally encoded via Base64 and merged silently into the active `canvas_downloader_settings.json` payload, providing seamless, persistent authentication without triggering OS-level credential dialogs.

## Recent Changes (Session 2026-03-11 — macOS V1.0 Native Release)
- **P0 CRITICAL: Tkinter Thread-Bomb Eradicated (`app.py`)**: Stripped all legacy `tkinter` imports from the main Streamlit module. macOS (Darwin) fundamentally rejects cross-thread UI calls and crashes instantly; this completes our migration to AppleScript subprocesses for folder selection.
- **P1: Hybrid API Token Storage (`app.py`)**: Rewrote the authentication loop to bypass relentless macOS Keychain privacy prompts. Windows securely relies on `keyring`, while Darwin (`platform.system() == 'Darwin'`) explicitly uses Base64-encoded fallback storage within the user's `canvas_downloader_settings.json`.
- **P2: macOS Icon Fallback Guard (`start.py`)**: Guarded the `.iconphoto()` deployment inside a strict `try/except` block to gracefully bypass non-fatal `TclError` exceptions that spontaneously occur on macOS Big Sur and above.
- **P0 CRITICAL: Excel Converter Crash Fix (`excel_converter.py`)**: Removed top-level `import pythoncom` / `import win32com.client` that caused `ModuleNotFoundError` on macOS. All COM imports are now lazy (inside `__enter__` and `_init_app`) with `try/except ImportError`, matching the pattern already used by `word_converter.py`.
- **P0: Platform-Guarded Dependencies (`requirements.txt`)**: Added `; sys_platform == 'win32'` marker to `pywin32==308` so `pip install` no longer fails on macOS/Linux.
- **P0: Cross-Platform .spec Fix (`Canvas_Downloader.spec`)**: Removed `'difflib'` from excludes (it was breaking `sync_manager.py`'s heal manifest on BOTH platforms). Also removed stale `'translations.py'` reference from datas.
- **P1: Config Path Safety (`ui_helpers.py` + `app.py`)**: Unified `get_config_dir()` to route config files to `~/Library/Application Support/CanvasDownloader/` on frozen macOS bundles (preventing `PermissionError` from writing inside read-only `.app` bundles). `app.py`'s `get_config_path()` now delegates to this unified function.
- **P2: AppleScript Office Bridge (`excel_converter.py`, `word_converter.py`, `pdf_converter.py`)**: Implemented full AppleScript (`osascript`) fallbacks inside each converter's `convert()` method. When `sys.platform == 'darwin'`, the converters bypass COM and use `subprocess.run(['osascript', '-e', ...])` to control Microsoft Excel, Word, and PowerPoint natively on macOS. Features: 120s timeout, `POSIX file` path format, quote escaping for defense-in-depth, stateless per-invocation (no self-healing needed).
- **P2: `.webloc` Support (`url_compiler.py`)**: Added platform-aware globbing (`*.webloc` on Darwin, `*.url` on Windows) and a `plistlib`-based parser for macOS bookmark files. The NotebookLM URL compilation feature now works identically on both platforms.

## Architectural Decisions — macOS
- **AppleScript helpers are duplicated** (~15 lines each) as `@staticmethod` in each of the 3 converter classes rather than shared in a module. Keeps converters self-contained.
- **No UI warnings** for missing Mac Office. Silent graceful failure (returns `None` + logs error), matching Windows behavior.
- **Config path routing**: `sys.frozen + Darwin → ~/Library/Application Support/`. `sys.frozen + Windows → exe directory`. `Script mode → __file__ parent`.

## Recent Changes (Session 2026-03-11 — V1.0 Final Action Plan Execution)
- **COM Self-Healing (`word_converter.py`)**: Ported the robust self-healing architecture from `excel_converter.py` into the legacy Word document converter. Added `_ensure_app()` to perform a lightweight health check before every single conversion. If a corrupted document crashes the COM channel, the converter forcefully kills the dead Word instance and re-initializes it, preventing cascading batch failures.
- **Disk Space Hardening (`ui_helpers.py`)**: Fixed a vulnerability in `check_disk_space()` where nested, non-existent target paths (e.g. `X:\future_folder`) caused `shutil.disk_usage()` to throw an exception, silently returning a false-positive `True`. It now iteratively walks up the path tree until it finds the closest existing parent directory (e.g. `X:\`) to accurately evaluate available drive space.

## Recent Changes (Session 2026-03-11 — V1.0 Polish Sweep & Final Audit Items)
- **Item 3: Dead Error UI Fix**: Fixed a logical contradiction in `app.py`'s cancellation handler that prevented error messages from correctly displaying after an aborted download loop.
- **Item 5: Centralized Logging**: Purged amateur `print()` statements from all 7 converter loops (`pdf`, `word`, `excel`, `video`, `code`, etc.) and replaced them with standard Python `logging` for persistent disk traceability.
- **Item 8: Centralized Versioning**: Created `version.py` (`__version__ = "2.0.0"`) and injected a styled version badge `Canvas Downloader v2.0.0` dynamically into the bottom of the Streamlit sidebar.
- **Item 9: Import Hoisting**: Eradicated 26 inline imports (e.g., `import time`, `import json`) buried deep inside functions/loops across `app.py`, `sync_ui.py`, `sync_manager.py`, and `ui_helpers.py`, hoisting them cleanly to the top-level module scope for performance and PEP-8 compliance. Deferred imports were intentionally kept for highly specific scopes (e.g. `win32com`, `tkinter`).
- **Item 10: Strict Exception Defensive Coding**: Scanned the entire workspace and upgraded 9 dangerous bare `except:` clauses to explicit `except Exception:` blocks across `app.py`, `canvas_logic.py`, and `video_converter.py` to prevent silencing vital system interrupts (like `KeyboardInterrupt`).
- **Item 13: Aggressive CSS Token Centralization**: Extracted 20+ hardcoded hex colors into a unified `theme.py` design system. Executed a massive workspace-wide sweep replacing 249 raw hex string occurrences across `app.py`, `sync_ui.py`, and `post_processing.py` with dynamic f-string references (e.g., `theme.TEXT_PRIMARY`, `theme.ERROR_ALT`), establishing a single source of truth for the app's visual identity.
- **Item 14: Strict UI String Validation (HTML Escaping)**: Engineered an `esc()` utility inside `ui_helpers.py` wrapping the standard `html.escape`. Deployed this function uniformly to wrap 46 instances of user-controlled variables (like Course Names and File Names) injected into HTML spans across the entire application, neutralizing XSS and DOM-corruption attack surfaces.

## Recent Changes (Session 2026-03-10 — V3.0 Architecture Audit Fixes)
- **Resolved "Modules Mode" Silent Data Loss (`canvas_logic.py`)**: Deleted the `downloaded_file_ids` ID-based deduplication tracker that was incorrectly skipping files present in multiple Canvas modules. Replaced it with a system that only tracks module files for Catch-All exclusion, ensuring every module link is processed.
- **Synchronous Path Conflict Resolution (`canvas_logic.py`)**: Fixed a concurrency bug where exact duplicate filenames crashing into the same local folder were being quietly discarded by the `seen_target_paths` and `seen_flat_paths` sets. Implemented synchronous `(1)`, `(2)` suffix generation before dispatching the `asyncio` file download task, guaranteeing 100% data preservation and zero `[WinError 32]` collisions.
- **Prevented Global Timeout Starvation (`canvas_logic.py` & `sync_ui.py`)**: Replaced the rigid `aiohttp.ClientTimeout(total=300)` with an adaptive timeout structure (`total=None, sock_read=60, sock_connect=15`). This ensures massive video files downloading over slow connections are no longer killed unconditionally at the 5-minute mark.
- **Eliminated Semaphore Freezing (`sync_ui.py`)**: Restructured the HTTP `429 Too Many Requests` rate limit handler. The `asyncio.sleep(wait)` backoff penalty is now mathematically pushed completely *outside* of the active `async with sem:` block. This immediately releases the slot back to the concurrency pool, allowing other files to download while the rate-limited task awaits its timeout.
- **Fortified SQLite Volatility (`sync_manager.py`)**: Injected `timeout=30.0` into the `sqlite3.connect` call within `_save_single_file_to_db` to gracefully handle extreme parallel insert flooding at the end of high-concurrency download batches, eliminating fatal `database is locked` crashes.

## Recent Changes (Session 2026-03-10 — V1.0 Audit Fixes)
- **Token Encryption (Keyring)**: Replaced plaintext token storage in JSON with OS-native credential vault storage via the `keyring` Python package. Includes auto-migration for legacy JSON tokens and secure wipe on logout.
- **DB Corruption Rescue**: Fortified `SyncManager._init_db` against SQLite corruption crashes. Added `PRAGMA quick_check` and an auto-rescue mechanism that renames corrupted `.canvas_sync.db` files and cleanly re-initializes.
- **In-App Error Viewer**: Implemented `_view_error_log_dialog()` and `_download_error_log_dialog()` using `@st.dialog` to display the contents of `download_errors.txt` inside the app. Wired into the Done/Cancelled screens for both standard Download and Sync modes.
- **Write Validation**: Ensured failed disk writes to `canvas_downloader_settings.json` now explicitly alert the user via `st.error()` rather than failing silently.

## Recent Changes (Session 2026-03-10 — Translation System Eradication)
- **Pure English Architecture**: Completely deleted `translations.py`. Purged all `get_text()`, `pluralize()`, and `language` parameters from 6 core source files (`app.py`, `sync_ui.py`, `ui_helpers.py`, `canvas_logic.py`, `sync_manager.py`, `start.py`).
- **Standardized String Formatting**: Replaced translation-key lookups with direct English strings or f-strings. Replaced the `pluralize()` utility with inline Python ternary operators (e.g., `f"{count} file{'s' if count != 1 else ''}"`) for zero-dependency rendering.
- **Simplified Class Constructors**: Stripped the `language` parameter from `CanvasManager` and `SyncManager` constructors. All backend logic now operates without language-state awareness.
- **UI Decoupling**: Removed the sidebar language selector and purged all `language` and `ui_lang` keys from `st.session_state`.
- **Sync Review HTML Fix**: Resolved an HTML rendering bug in `sync_ui.py` where literal tags were visible; ensured all headers use `st.markdown(..., unsafe_allow_html=True)` and corrected emoji corruption.

## Recent Changes (Session 2026-03-10 — 3-Tier Batch Sync Configuration UX)
- **Complete UX Paradigm Shift**: Replaced the single "Context-Aware Override" checkbox with a 3-mode `st.radio` switchboard: Mode 0 (Keep Existing), Mode 1 (Global Override), Mode 2 (Individual Course Tweaks).
- **Settings Diff Table**: Mode 1 renders an HTML diff table showing ✅/❌ per course per setting when a batch has mixed configs — solves the "blind spot" problem.
- **Per-Course Editing**: Mode 2 uses a `st.selectbox` course picker with dynamically-keyed checkboxes (`ind_convert_*_{cid}`). Streamlit auto-persists all edits per course.
- **Backend Handoff Parity**: `_show_sync_confirmation` branches on `_sync_config_mode`. Mode 0 loads SQLite, Mode 1 writes global, Mode 2 writes per-course. All paths bind `res_data['contract']` for Phase 3.
- **Initialization Sweep Bug Fix from Audit**: Moved `try/except` inside the `for` loop so one corrupted JSON contract can't abort the entire sweep. Also now sweeps `file_filter` for mixed-state detection.

## Recent Changes (Session 2026-03-10 — 3-Tier Sync Audit Refinements)
- **Diff Table Context**: The HTML settings diff table in Mode 1 now renders unconditionally for batches of 2+ courses (regardless of uniform/mixed state). Uniform batches must also display the table to provide users visual confirmation of their identical baseline settings before applying global overrides.
- **Handoff Exception Silencing**: Pushed `try/except` blocks deep inside the `for` loops across all three Modes (0, 1, and 2) in `_show_sync_confirmation`. This prevents a single malformed SQLite contract from implicitly zeroing out the payloads of all subsequent healthy courses in the batch.
- **`_CONVERT_KEYS` Unification**: Eliminated the redundant `_CONVERT_KEYS_LOCAL` list in the handoff function, explicitly passing `_CONVERT_KEYS_HANDOFF = ['convert_zip', ...]` inline to ensure identical index mapping with the upstream init sweep.
- **Global Key Cleanup**: Appended exhaustive `.pop()` commands at the end of the `Sync Now` handoff sequence to aggressively wipe `st.session_state` global conversion keys (`convert_*`, `notebooklm_master`, `file_filter`). This guarantees Zero-Bleed if the user navigates directly back to the `Download Page`.

## Recent Changes (Session 2026-03-10 — Truthful Batch Settings UI Paradigm)
- **Context-Aware Settings Override**: Completely overhauled how the Manual Sync (Step 2) Review screen handles global conversion settings during a multi-course batch sync.
- **Mixed State Detection**: Built a logic sweep into `_show_analysis_review` initialization that scans the `sync_contract` of every selected course. It mathematically detects if `len(set(_batch_settings_map[key])) > 1` (i.e. Course A converts PPTX but Course B does not).
- **Truthful UI Locking**: If a mixed batch is detected, the 8 conversion checkboxes are correctly forced to an unchecked `disabled=True` state, and a warning `⚠️ Mixed Settings Detected` is rendered. This explicitly prevents Course A from visually dictating the state of Course B, an anti-pattern caused by Streamlit's lack of "indeterminate" checkboxes.
- **Master Override Toggle**: Introduced a `🔄 Override settings for all selected courses` checkbox. Checking it enables the conversion checkboxes, providing pure user intent that they wish to destructively override the historically saved individual contracts with a new, uniform setting for the batch.
- **Backend Execution Parity**: Modified the `"Yes, Start Sync"` execution handoff. If a batch is mixed AND the user opts out of overriding it, the execution loop explicitly extracts each course's unique `sync_contract` from SQLite and passes it into `_s['res_data']['contract']`. This completely solves the memory-state failure point and aligns the Manual Sync architecture 1:1 with Quick Sync, allowing `get_synced_file_paths(target_exts, conversion_key)` in Phase 3 to read individual course truths rather than falling back to the mutated global `st.session_state`.

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

## Recent Changes (Session 2026-03-20 - v1.0 Audit Resolution)
- **Sniper Retry Architecture (`app.py`)**:
  - Overhauled the "Retry Failed Items" button logic. Instead of resetting the download status to `'scanning'` (forcing a multi-minute Canvas analysis phase), the button now surgically applies `download_status = 'running'`.
  - Cached variables (`courses_to_download`, `total_items`, `total_mb`) are explicitly preserved, instantly fast-forwarding the UI matrix directly back into execution mode to redownload isolated failures.
- **Fail-Safe Networking (`canvas_logic.py`)**:
  - **Fail-Safe Networking**: (DEPRECATED) Attempted to inject a socket timeout via `request_kwargs={'timeout': 30}` in the `Canvas` client. *Observation: This caused a fatal TypeError in the current `canvasapi` version and was removed on 2026-03-21.*
  - **Content-Type Validation**: Added a pre-write guard in `_download_file_async`. If Canvas unexpectedly returns a `200 OK` status with `text/html` instead of binary data (a known catastrophic failure mode for the LMS), the block manually raises a `ValueError` rather than silently saving an HTML error page masked as a PDF or Zip.
- **Crash Immunity & Sandboxing**:
  - **Graceful Process Handling**: Eradicated 5 rogue `except BaseException:` catch-alls across `app.py`, `post_processing.py`, and `sync_ui.py`. The app correctly routes `SystemExit` (for PyInstaller teardowns) and `KeyboardInterrupt` while utilizing standard `except Exception:` isolation.
  - **Defensive Importing**: Wrapped the vulnerable `import psutil` within `video_converter.py` in a `try/except ImportError` block, allowing the application to safely launch even on malformed environments lacking the C-extension dependency, degrading to a graceful terminal warning instead of a hard crash.

## Recent Changes (Session 2026-03-04 - UI Polish & Status Sync)
- **Unified Blue Status Indicator (`sync_ui.py` & `app.py`)**:
  - **Desync Fix (Phase 2 Download)**: Moved the `active_file_placeholder` update for current filenames **outside** the 0.4s UI throttle block in `sync_ui.py`. The status text now updates instantly for every file, ensuring it never lags behind the terminal output.
  - **Standardized Styling**: Implemented a consistent `#38bdf8` blue color with `font-weight: 500` for all "Currently downloading:" and "Currently processing:" status messages.
  - **Post-Processing Visibility**: Injected the blue status indicator into all 7 conversion/extraction loops (Archives, PPTX, HTML, Code, Word, Excel, Video) in both `sync_ui.py` and `app.py`.
  - **Cleanup Hooks**: Added `active_file_placeholder.empty()` calls after all post-processing completions to ensure the status text is cleared once the course/batch is finished.

## Recent Changes (Session 2026-03-13 - Built-to-Last Architecture Fixes)
- **Concurrency & Rate Limit Unblocking (`canvas_logic.py`)**:
  - **Semaphore Release Penalty**: Moved `asyncio.sleep()` for 403/429 Canvas rate limiting outside the core processing lock (`async with sem:`). Rate-limited tasks now peacefully wait out their penalty without stealing active concurrent connection slots from healthy tasks.
  - **Target-Path Serialization**: Interwoven a new mutex dictionary global lock (`_download_locks`) directly into `.part` file operations. Multiple threads attempting to write overlapping file structures are seamlessly serialized byte-for-byte instead of colliding or throwing OS File in Use exceptions.
- **Deadlock Eradication (`video_converter.py` & `sync_manager.py`)**:
  - **Zombie FFmpeg Neutralization**: Disassembled the synchronous `with ThreadPoolExecutor` used for `moviepy` destruction. Invoked strict asynchronous exit directives (`wait=False, cancel_futures=True`) to prevent the entire download thread from hanging infinitely on corrupted MP4/MOV headers.
  - **DB Flood Defense Escalation**: Standardized all `sqlite3.connect` initializations globally to block for up to `30.0` seconds instead of 20.0, granting slow hard drives massive breathing room to write sync states.
- **Atomic State Guarantees (`ui_helpers.py`)**:
  - **Configuration Immutability**: All edits to `canvas_sync_pairs.json` now employ a `.tmp` file and `os.replace` shadow-swap, protecting configuration states from cross-thread tear interference.

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
