# Custom Loading Overlay for Page Navigation UI Breaks

**Date**: 2026-04-28 (updated 2026-04-29)  
**Issue**: Streamlit's slow reruns during full page navigation (1-5s on slow machines) caused visible intermediate DOM states: old UI grayed out, CSS unloaded, raw empty containers below new UI, then suddenly styled UI appeared.  
**User Feedback**: Explicitly rejected native Streamlit spinner as "unprofessional"; needed a fully custom, professional solution.

## Solution Implemented

### Architecture
- **Custom overlay**: Fixed-position full-page div, dark background (`#0e1117`), centered spinner + "Loading…" text
- **Activation**: JavaScript click listener fires ONLY for buttons inside keyed navigation containers (allowlist)
- **Deactivation (3-Phase Geometry-Polling)**: 
  1. **Phase 1 (Debounce):** 150ms debounce to batch rapid-fire mutations from initial React DOM insertion.
  2. **Phase 2 (Python Done):** Polls every 150ms for `stStatusWidget` removal (Streamlit's signal that the Python script finished executing).
  3. **Phase 3 (React Cleanup Done):** Polls page geometry (`scrollHeight` + total element count) every 200ms. Only hides after 4 consecutive identical readings (800ms of layout stability). This reliably detects when lingering old elements are finally removed by React.
  - *Why not MutationObserver for Phase 3?* Stale UI elements sitting at the bottom of the page generate *no mutations* while they linger. Geometry polling actively detects their eventual removal.
- **Safety valve**: 8s force-hide if rerun stalls (only cleared when committing the actual hide in Phase 3).
- **Hot-reload resilience**: `isConnected` check re-attaches overlay if Streamlit hot-reload detaches it from DOM

### Key Technical Insights

1. **Fragment Protection**: Download Settings uses `@st.fragment` decorators (partial reruns, no full DOM tear). Sync Review transitions also don't fully break. These don't need the overlay—they're already optimized by Streamlit.

2. **Allowlist Click Detection**: Instead of showing overlay on EVERY button (chevrons, toggles, filters, Settings, dialog buttons), the JS selector allowlist targets only known navigation containers. Prevents disruptive flashes during in-page interactions like expanding cards.

3. **`components.html()` Iframe Lifecycle**: Each Streamlit rerun destroys and recreates the `components.html()` iframe. The old MutationObserver is garbage-collected. Solution: store all state on `window.parent._cdp` (parent window object), which persists across iframe reloads.

4. **Geometry-Polling Hide Pattern (2026-04-29 upgrade)**:
   - **Problem with Mutation-Settle only**: On slow machines, the first wave of DOM mutations settled quickly, but the NEW page UI was still hydrating and old elements were lingering. Overlay hid too early because stale elements sitting there generate zero DOM mutations.
   - **Solution**: 
     - Added `stStatusWidget` check as an authoritative "Streamlit Python script done" signal.
     - Switched to **Geometry Polling** (`pageFingerprint = scrollHeight + '|' + elementCount`) to detect when React finally removes the old elements. 
     - The `MutationObserver` now just acts as an external trigger to restart the 3-phase check sequence on any DOM changes, but the hide decision is based strictly on layout stability, not mutation silence.
   
5. **Safety Valve Independence**: The 8s safety timeout is now only cleared when the hide actually commits (inside Phase 3), not when `schedHide` starts. This prevents edge cases where the safety valve is prematurely cancelled but `stStatusWidget` never disappears.

### Navigation Buttons Covered (Allowlist)

| Button | File | Key / Container |
|---|---|---|
| Download Courses | auth.py | `nav_btn_download` |
| Sync Local Folders | auth.py | `nav_btn_sync` |
| Logout | auth.py | `nav_btn_logout` |
| Continue | course_selector.py | `page_nav_continue` |
| Back (settings error) | app.py | `page_nav_back_to_settings` |
| Back (sync error, final page) | sync_ui.py | `page_nav_back` |
| Back (sync review error) | sync_review.py | `page_nav_back_sr_err` |
| Analyze, Review & Sync | sync_ui.py | `btn_analyze_sync` |
| Quick Sync All | sync_ui.py | `btn_quick_sync` |
| Back (sync review) | sync_review.py | `btn_sync_back` (container) |
| No, Go back | sync_confirmation.py | `cancel_sync_dialog_btn` |
| Yes, Start Sync | sync_confirmation.py | `page_nav_start_sync` |
| Go to front page (download done) | app.py | `page_nav_front_page` |
| Go to front page (sync error) | completion.py | `page_nav_front_page_sync` |
| Go to front page (sync done) | completion.py | `page_nav_front_page_sync_complete` |

**Excluded (fragment-protected or in-page)**: Confirm and Download, Sync & Download X files, all dialog open/close buttons, Settings button, chevrons, toggles, filters.

### Code Quality & Robustness

- ✅ Added `isConnected` guard in `show()` to re-attach overlay after dev hot-reload
- ✅ Fixed JS selector allowlist to prevent accidental triggers on non-navigation buttons
- ✅ Clean inline comments explaining iframe lifecycle, state persistence, and settle logic
- ✅ Strict boolean guard `if(!p.vis)return` prevents re-showing already-visible overlay
- ✅ 8s safety timeout prevents hung overlays from trapping the user
- ✅ `isStReady()` graceful degradation for future Streamlit versions
- ✅ Geometry polling guarantees overlay stays up through React's slow DOM reconciliation on slow machines

### User Testing Feedback

- ✅ User confirmed overlay appears and disappears correctly
- ✅ Solves the visual break on slow machines (previously saw broken UI for ~500ms after overlay hid)
- ✅ No disruptive overlays during in-page interactions (confirmed by testing chevron clicks on Download Settings)
- 🔄 2026-04-29: Upgraded to 3-phase Geometry-Polling architecture because mutation-settle failed to account for slow React DOM reconciliation where lingering old elements generate zero mutations.

## Files Modified

- `app.py`: Full overlay implementation, updated comments, added keys to "Go Back" and "Go to front page" buttons
- `course_selector.py`: Added `key="page_nav_continue"` to Continue button
- `sync_ui.py`: Added `key="page_nav_back"` to Back button
- `sync_review.py`: Added `key="page_nav_back_sr_err"` to error-state Back button
- `sync_confirmation.py`: Added `key="page_nav_start_sync"` to Yes/Start Sync button
- `completion.py`: Added `key="page_nav_front_page_sync"` and `key="page_nav_front_page_sync_complete"` to completion buttons

## Architectural Pattern

This overlay approach can be reused for any Streamlit app with similar page-transition UI breaks. Key principles:

1. **State on parent window**: Allows survival across iframe reloads
2. **Allowlist click detection**: Prevents overlay on every interaction
3. **Geometry-Polling Hide**: Don't rely on mutations stopping. Poll `scrollHeight` and element counts to verify layout stability, gated behind `stStatusWidget` removal.
4. **Hot-reload guard**: Gracefully handles development workflow interruptions
5. **Graceful degradation**: Falls back to Geometry Polling only if stStatusWidget is removed

Not a workaround—a robust, production-ready solution for Streamlit's inherent rendering lag during major reruns.
