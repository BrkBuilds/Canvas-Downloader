# Custom Loading Overlay for Page Navigation UI Breaks

**Date**: 2026-04-28  
**Issue**: Streamlit's slow reruns during full page navigation (1-5s on slow machines) caused visible intermediate DOM states: old UI grayed out, CSS unloaded, raw empty containers below new UI, then suddenly styled UI appeared.  
**User Feedback**: Explicitly rejected native Streamlit spinner as "unprofessional"; needed a fully custom, professional solution.

## Solution Implemented

### Architecture
- **Custom overlay**: Fixed-position full-page div, dark background (`#0e1117`), centered spinner + "Loading…" text
- **Activation**: JavaScript click listener fires ONLY for buttons inside keyed navigation containers (allowlist)
- **Deactivation**: 500ms of DOM mutation settlement + one `requestAnimationFrame` (ensures hide after browser paint commit)
- **Safety valve**: 8s force-hide if rerun stalls
- **Hot-reload resilience**: `isConnected` check re-attaches overlay if Streamlit hot-reload detaches it from DOM

### Key Technical Insights

1. **Fragment Protection**: Download Settings uses `@st.fragment` decorators (partial reruns, no full DOM tear). Sync Review transitions also don't fully break. These don't need the overlay—they're already optimized by Streamlit.

2. **Allowlist Click Detection**: Instead of showing overlay on EVERY button (chevrons, toggles, filters, Settings, dialog buttons), the JS selector allowlist targets only known navigation containers. Prevents disruptive flashes during in-page interactions like expanding cards.

3. **`components.html()` Iframe Lifecycle**: Each Streamlit rerun destroys and recreates the `components.html()` iframe. The old MutationObserver is garbage-collected. Solution: store all state on `window.parent._cdp` (parent window object), which persists across iframe reloads.

4. **500ms Settle + rAF Pattern**: 
   - First wave: Streamlit inserts DOM nodes → MutationObserver fires
   - Brief pause: React hydration applies classes/styles (attribute mutations NOT observed since `attributes: false`)
   - 500ms settle: ensures hydration finishes
   - rAF: defers actual `display: none` until after browser commits a full paint of the new content
   - Result: overlay disappears only after new page is fully styled and rendered

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
- ✅ Updated stale comments (old 150ms settle timer reference, phantom 300ms show delay)
- ✅ Fixed JS selector allowlist to prevent accidental triggers on non-navigation buttons
- ✅ Clean inline comments explaining iframe lifecycle, state persistence, and settle logic
- ✅ Strict boolean guard `if(!p.vis)return` prevents re-showing already-visible overlay
- ✅ 8s safety timeout prevents hung overlays from trapping the user

### User Testing Feedback

- ✅ User confirmed overlay appears and disappears correctly
- ✅ Solves the visual break on slow machines (previously saw broken UI for ~500ms after overlay hid)
- ✅ 500ms timer prevents the "half-second flash of unstyled UI" that occurred with 150ms
- ✅ No disruptive overlays during in-page interactions (confirmed by testing chevron clicks on Download Settings)

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
3. **Mutation settlement + rAF**: Waits for full render commit, not just DOM insertion
4. **Hot-reload guard**: Gracefully handles development workflow interruptions

Not a workaround—a robust, production-ready solution for Streamlit's inherent rendering lag during major reruns.
