import streamlit as st
import streamlit.components.v1 as components
from canvas_logic import CanvasManager, DownloadError
import asyncio
import collections
import os
import logging
import sys
import time
from datetime import datetime

import theme
import version

logger = logging.getLogger(__name__)
from pathlib import Path
from sync_ui import render_sync_step1, render_sync_step4
from ui_helpers import esc, render_download_wizard
from ui_shared import (
    render_completion_card, render_folder_cards,
    render_error_section, render_pp_warning, SECONDARY_ENTITY_ICONS,
    error_log_dialog,
)
from styles import inject_css
from ui_shared import inject_material_icons_font
from core.state_registry import (
    ensure_download_state,
)
from core.cancellation import cancel_download, is_download_cancelled, reset_download_cancel
from engine.progress_dashboard import DashboardPlaceholders, render_full_dashboard, render_active_file
from engine.post_processing_bridge import invoke_post_processing, build_conversion_contract
from engine.notifications import play_completion_beep, request_macos_notification_permission

# Page Config
st.set_page_config(page_title="Canvas Downloader", page_icon="assets/icon.png", layout="wide")

# Custom CSS (extracted to styles/)
inject_css('global.css')

# macOS: ask for notification permission once, early — so the first "Download
# Complete" / "Sync Complete" banner isn't dropped while a fresh install's
# permission is still pending. Idempotent per process; no-op off macOS.
request_macos_notification_permission()

# Cancel button hover CSS (dynamic - requires theme variables)
st.html(f"""
    <style>
    .st-key-cancel_download_btn button:hover,
    .st-key-cancel_pp_download button:hover,
    .st-key-cancel_sync_btn button:hover,
    .st-key-cancel_pp_btn button:hover {{
        border-color: {theme.ERROR} !important;
        background-color: {theme.ERROR_BG} !important;
        color: {theme.ERROR} !important;
        transition: all 0.2s ease-in-out;
    }}
    </style>
""")

# Preset & Dialog CSS (extracted to styles/)
inject_css('preset_dialogs.css')

# Google Material Symbols font — injected once here (M-24: was duplicated in every _mat() call).
inject_material_icons_font()

# Loading overlay - hides the raw intermediate DOM during Streamlit page-navigation reruns.
# Uses window.parent.document because components.html() runs inside an iframe.
# All state is stored on window.parent._cdp so it survives iframe reloads
# (components.html() recreates its iframe on every rerun; without this the
# MutationObserver is garbage-collected and the overlay stops working after the
# first rerun).
# Activation: click listener fires ONLY for buttons inside known navigation
# containers (NAV_SEL allowlist) - in-page interactions (chevrons, filters,
# dialogs) are excluded.
# Hide (3-phase geometry-polling):
#   Phase 1: 150 ms debounce - batches rapid-fire mutations.
#   Phase 2: Poll for stStatusWidget removal - waits until the Python script
#            has finished executing.
#   Phase 3: Poll page geometry (scrollHeight + element count) every 200 ms.
#            Only hides after 4 consecutive identical readings (800 ms of
#            layout stability). Directly detects old-element cleanup regardless
#            of whether mutations fire.
#   An 8 s safety valve force-hides if a rerun hangs.
components.html("""<script>
(function(){
    // All state lives on window.parent._cdp so it survives iframe reloads.
    // components.html() recreates its iframe on every Streamlit rerun; without
    // this pattern the MutationObserver (tied to the old iframe context) is
    // garbage-collected and the overlay stops working after the first rerun.
    var win=window.parent, doc=win.document;
    var p=win._cdp||(win._cdp={vis:false,hT:null,safeT:null,el:null,obs:null,clickAdded:false,awaitChange:false,preFP:null});

    // --- Create overlay element once ---
    if(!p.el){
        var s=doc.createElement('style');
        s.textContent='@keyframes _cdR{to{transform:rotate(360deg)}}';
        doc.head.appendChild(s);
        p.el=doc.createElement('div');
        p.el.id='_cdOv';
        p.el.style.cssText='position:fixed;top:0;left:0;right:0;bottom:0;'
            +'background:#0e1117;z-index:99999;display:none;flex-direction:column;'
            +'align-items:center;justify-content:center;gap:16px';
        p.el.innerHTML=
            '<div style="width:30px;height:30px;border:2.5px solid rgba(255,255,255,.07);'
            +'border-top-color:#38bdf8;border-radius:50%;animation:_cdR .75s linear infinite"></div>'
            +'<div style="color:rgba(255,255,255,.38);font:13px/1 system-ui,sans-serif;'
            +'letter-spacing:.04em">Loading…</div>';
        doc.body.appendChild(p.el);
    }

    function show(){
        if(p.vis)return;
        // Re-attach if Streamlit hot-reload replaced document.body while we were detached
        if(!p.el.isConnected)doc.body.appendChild(p.el);
        p.el.style.display='flex'; p.vis=true;
        // Safety valve: force-hide after 8 s so a hung rerun can't trap the overlay
        if(p.safeT)clearTimeout(p.safeT);
        p.safeT=setTimeout(function(){p.el.style.display='none';p.vis=false;p.safeT=null;},8000);
    }

    // Streamlit injects [data-testid="stStatusWidget"] while the Python script
    // is executing and removes it once the rerun completes.  If the element is
    // absent the script has finished (or the attribute was removed in a future
    // Streamlit version - graceful degradation: treat as "ready").
    function isStReady(){
        return !doc.querySelector('[data-testid="stStatusWidget"]');
    }

    // Returns a fingerprint of the page layout.  Uses querySelectorAll('*') on
    // the main vertical block to catch deep-subtree reconciliation (e.g. old
    // course-list elements still present) that childElementCount misses.
    // O(n) but negligible at 200 ms intervals (~1 ms for 500 elements).
    function pageFingerprint(target){
        var vb=doc.querySelector('[data-testid="stVerticalBlock"]');
        return target.scrollHeight+'|'+(vb?vb.querySelectorAll('*').length:target.childElementCount);
    }

    function schedHide(){
        // Don't cancel the safety valve - it is the ultimate fallback.
        // Only clear it once we actually commit the hide (in Phase 3).
        if(p.hT)clearTimeout(p.hT);

        // Phase 1 - 150 ms debounce.  Batches the rapid-fire mutations that
        // occur during React's initial DOM insertion.
        p.hT=setTimeout(function(){

            // Phase 2 - Wait for Streamlit's Python script to finish.
            // Poll every 150 ms until stStatusWidget is removed from the DOM.
            // The 8 s safety valve guarantees we can never poll forever.
            function waitForReady(){
                if(!isStReady()){
                    p.hT=setTimeout(waitForReady,150);
                    return;
                }
                // Phase 3 - Script is done, but React DOM reconciliation may still
                // be running.  awaitChange=true is always set for all nav buttons:
                // we compare against p.preFP (fingerprint captured at click time)
                // and do not start counting stability until the DOM has changed
                // from the pre-click state.  This handles:
                //   (a) Two-rerun pattern: sidebar nav buttons call st.rerun() at
                //       the end of Rerun 1, creating a gap where stStatusWidget is
                //       absent.  Without awaitChange, Phase 3 would count the old
                //       (unchanged) page as stable and hide prematurely.
                //   (b) Slow startup: Streamlit may not have injected stStatusWidget
                //       yet when Phase 2 first polls.
                // - If DOM already differs from preFP → React reconciled during
                //   Phase 1/2; just count stability normally (no extra wait).
                // - If DOM still matches preFP → old page still displayed;
                //   wait for the first geometry change, then count stability.
                var target=doc.querySelector('[data-testid="stMain"]')||doc.body;
                var hasChanged=!p.awaitChange||(pageFingerprint(target)!==(p.preFP||''));
                var lastFP='';
                var stableCount=0;
                function pollStable(){
                    // If a new rerun started (e.g. st.query_params.update() on the
                    // previous rerun triggered a second server round-trip), go back
                    // to Phase 2 so we wait for it to finish before counting stability.
                    if(!isStReady()){p.hT=setTimeout(waitForReady,150);return;}
                    var fp=pageFingerprint(target);
                    if(!hasChanged){
                        if(fp!==p.preFP){
                            // DOM moved past pre-click state - begin stability.
                            hasChanged=true;lastFP=fp;stableCount=0;
                        }
                        // else: old page still displayed - keep polling.
                    }else{
                        if(fp===lastFP){
                            stableCount++;
                            if(stableCount>=6){
                                // Layout stable for ~1200 ms.  Attempt hide.
                                p.awaitChange=false;p.preFP=null;
                                // Scroll to top - Streamlit uses internal scroll
                                // containers, not the window.  Hit all candidates.
                                win.scrollTo(0,0);
                                var sc=doc.querySelectorAll(
                                    '[data-testid="stMain"],'
                                    +'[data-testid="stAppViewContainer"],'
                                    +'[data-testid="stVerticalBlock"]'
                                );
                                for(var i=0;i<sc.length;i++) sc[i].scrollTop=0;
                                // Capture the stable fingerprint for the rAF guard.
                                var commitFP=lastFP;
                                requestAnimationFrame(function(){
                                    // Guard against the ~16 ms rAF gap: a late mutation
                                    // (deep React cleanup, URL-param update, second rerun)
                                    // may have fired between the stableCount decision and
                                    // now.  If the DOM changed or a new rerun started,
                                    // restart Phase 3 instead of hiding prematurely.
                                    var curFP=pageFingerprint(target);
                                    if(!isStReady()||curFP!==commitFP){
                                        stableCount=0;lastFP=curFP;
                                        p.hT=setTimeout(pollStable,200);
                                        return;
                                    }
                                    if(p.safeT){clearTimeout(p.safeT);p.safeT=null;}
                                    p.el.style.display='none';p.vis=false;p.hT=null;
                                });
                                return;
                            }
                        }else{
                            // Layout still changing - reset stability counter.
                            stableCount=0;lastFP=fp;
                        }
                    }
                    p.hT=setTimeout(pollStable,200);
                }
                pollStable();
            }
            waitForReady();
        },150);
    }

    // --- Register click listener once ---
    // Only show overlay for page-navigation buttons (mode switch, Continue,
    // Analyze/Quick-Sync, Back, Go-to-front-page).  In-page interactions
    // (chevrons, filters, dialog open/close, Settings) are excluded so the
    // overlay does NOT flash on every checkbox or card expand.
    var NAV_SEL=[
        'div[class*="st-key-page_nav_"]',         // Continue, Back, Yes Start Sync, Go to front page (all variants)
        'div[class*="st-key-nav_btn_download"]',  // sidebar: Download Courses
        'div[class*="st-key-nav_btn_sync"]',      // sidebar: Sync Local Folders
        'div[class*="st-key-nav_btn_logout"]',    // sidebar: Logout
        'div[class*="st-key-login_submit_btn"]',  // login submission button
        'div[class*="st-key-btn_analyze_sync"]',  // Analyze, Review & Sync
        'div[class*="st-key-btn_quick_sync"]',    // Quick Sync All
        'div[class*="st-key-btn_custom_download"]',// Course Selector: Custom Download
        'div[class*="st-key-btn_quick_download"]', // Course Selector: Quick Download
        'div[class*="st-key-sync_back"]',         // Back in sync review (container-keyed)
        'div[class*="st-key-action_dl_back"]',    // Back in download settings
        'div[class*="st-key-cancel_sync_dialog"]',// No, Go back in sync confirmation
        'div[class*="st-key-qd_goto_advanced"]'   // Customize configuration in Quick Download
    ].join(',');
    if(!p.clickAdded){
        p.clickAdded=true;
        doc.addEventListener('click',function(e){
            if(!e.target.closest('button'))return;
            var btn = e.target.closest(NAV_SEL);
            if(!btn)return;
            
            // Sidebar nav buttons: skip overlay when already at the target mode's
            // step 1 (clicking would cause a no-op rerun with no page change).
            if(btn.matches('div[class*="st-key-nav_btn_download"]')||btn.matches('div[class*="st-key-nav_btn_sync"]')){
                var stEl=doc.getElementById('cdp_nav_state');
                if(stEl){
                    var curMode=stEl.getAttribute('data-mode')||'';
                    var curStep=parseInt(stEl.getAttribute('data-step')||'0',10);
                    var tMode=btn.matches('div[class*="st-key-nav_btn_download"]')?'download':'sync';
                    if(curMode===tMode&&curStep===1)return;
                }
            }
            // Custom validation: Don't show overlay if clicking Course Selector download buttons with no courses selected
            if(btn.matches('div[class*="st-key-btn_custom_download"],div[class*="st-key-btn_quick_download"]')){
                var checkedCourses=doc.querySelectorAll('div[class*="st-key-dl_chk_"] input[type="checkbox"]:checked');
                var countEl=doc.getElementById('cdp_selected_courses_count');
                var backendCount=countEl?parseInt(countEl.getAttribute('data-count'),10):0;
                if(checkedCourses.length===0&&backendCount===0)return;
            }
            // Always capture the pre-click fingerprint for all nav buttons.
            // Phase 3 will not count stability until the DOM has actually changed
            // from the pre-click state. This fixes the two-rerun race condition:
            // sidebar nav buttons (Download/Sync) call st.rerun() at the end of
            // Rerun 1, creating a brief gap where stStatusWidget is absent between
            // Rerun 1 and Rerun 2. Without awaitChange, Phase 3 would see the old
            // page as "stable" for 1200ms and hide the overlay before the new page
            // renders. It also handles slow Streamlit startup where stStatusWidget
            // hasn't been injected yet when Phase 2 first polls.
            p.awaitChange=true;
            p.preFP=pageFingerprint(doc.querySelector('[data-testid="stMain"]')||doc.body);
            show();
        },true);
    }

    // --- Recreate MutationObserver on every iframe load ---
    // The previous observer (from the last iframe context) was disconnected when
    // that iframe was destroyed.  Always create a fresh one here.
    // The observer triggers schedHide() on DOM changes to kick off the 3-phase
    // sequence.  Phase 3 itself uses geometry polling (not mutations) to decide
    // when to hide - so even if mutations stop while stale elements linger,
    // the polling loop catches the eventual cleanup.
    if(p.obs){try{p.obs.disconnect();}catch(_){}}
    p.obs=new MutationObserver(function(){
        if(!p.vis)return;
        schedHide(); // restarts the 3-phase sequence on every DOM change
    });
    p.obs.observe(doc.querySelector('[data-testid="stMain"]')||doc.body,
        {childList:true,subtree:true,attributes:false,characterData:false});

    // --- Server-shutdown watchdog (branded "app closed" screen) ---
    // When the user quits the controller/app the Streamlit server dies but the
    // browser tab survives, and Streamlit's own handling shows a gray overlay
    // with a confusing "Streamlit/connection error" message. We poll the
    // health endpoint and, after 3 consecutive failures (~7.5 s), cover the
    // page with a branded full-screen notice instead.
    // Lifetime note: this interval lives in THIS iframe's JS context. On every
    // rerun the iframe is recreated (old timer is GC'd with it, failure count
    // resets), but once the server dies no further reruns can occur — so the
    // last iframe and its timer survive exactly as long as we need them.
    var hFails=0;
    function hDead(){
        if(doc.getElementById('_cdClosed'))return;
        try{if(p.safeT){clearTimeout(p.safeT);}p.el.style.display='none';p.vis=false;}catch(_){}
        var ov=doc.createElement('div');
        ov.id='_cdClosed';
        ov.style.cssText='position:fixed;top:0;left:0;right:0;bottom:0;background:#0e1117;'
            +'z-index:2147483647;display:flex;flex-direction:column;align-items:center;'
            +'justify-content:center;gap:18px;font-family:-apple-system,BlinkMacSystemFont,'
            +'"Segoe UI",sans-serif;text-align:center;padding:24px';
        ov.innerHTML=
            '<div style="width:64px;height:64px;background:rgba(77,168,218,.12);border-radius:16px;'
            +'display:flex;align-items:center;justify-content:center">'
            +'<svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="#4DA8DA" '
            +'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            +'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
            +'<polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></div>'
            +'<div style="color:#fafafa;font-size:1.25rem;font-weight:600">Canvas Downloader has been closed</div>'
            +'<div style="color:rgba(255,255,255,.45);font-size:.95rem;line-height:1.6;max-width:420px">'
            +'The app was shut down, so this window is no longer connected.<br>'
            +'You can safely close it. To start again, open the Canvas Downloader app.</div>';
        doc.body.appendChild(ov);
        try{doc.title='Canvas Downloader';}catch(_){}
    }
    setInterval(function(){
        if(doc.getElementById('_cdClosed'))return;
        fetch(win.location.origin+'/_stcore/health',{cache:'no-store'})
            .then(function(r){
                if(r.ok){hFails=0;}else{hFails++;if(hFails>=3)hDead();}
            })
            .catch(function(){hFails++;if(hFails>=3)hDead();});
    },2500);
})();
</script>""", height=0)

# --- URL Query-Param Navigation Persistence ---

def _restore_nav_from_query_params() -> None:
    """On a fresh session, pre-seed mode/step from URL query params before defaults are applied.

    Steps that require live download/sync state (3, 4 for download; 4 for sync)
    cannot be meaningfully restored and are capped to the nearest safe step.
    """
    if '_session_alive' in st.session_state:
        return  # not a fresh session — don't override in-session navigation
    try:
        raw_mode = st.query_params.get('mode', '')
        raw_step = st.query_params.get('step', '')
        if raw_mode not in ('download', 'sync'):
            return
        step = int(raw_step) if isinstance(raw_step, str) and raw_step.isdigit() else 1
        if raw_mode == 'download':
            step = min(step, 2)   # steps 3+ need a live download session
        else:
            step = 1              # sync step 4 needs live sync state; step 1 is always safe
        st.session_state['current_mode'] = raw_mode
        st.session_state['step'] = step
        if raw_mode == 'sync':
            st.session_state['sync_mode'] = True
        # Restore Quick Download flag so step 2 renders the correct screen.
        if raw_mode == 'download' and step == 2:
            raw_quick = st.query_params.get('quick', '')
            if raw_quick == '1':
                st.session_state['quick_download_mode'] = True
    except Exception:
        pass
    finally:
        st.session_state['_session_alive'] = True  # Always set, even on exception or early return


def _write_nav_to_query_params() -> None:
    """Keep URL query params in sync with current mode/step on every rerun.

    Uses .update() so both keys are written atomically without triggering an
    extra rerun (Streamlit silently updates the URL from the server side).
    """
    try:
        if not st.session_state.get('is_authenticated', False):
            # Auth page: clean URL with just ?mode=auth, no stale params.
            if st.query_params.get('mode') != 'auth' or set(st.query_params.keys()) != {'mode'}:
                st.query_params.clear()
                st.query_params['mode'] = 'auth'
            return
        mode = st.session_state.get('current_mode', 'download')
        step = str(st.session_state.get('step', 1))
        is_quick = bool(st.session_state.get('quick_download_mode'))
        # 'quick' is only present in the URL when True; absent otherwise.
        expected_quick = '1' if is_quick else None
        if (st.query_params.get('mode') != mode
                or st.query_params.get('step') != step
                or st.query_params.get('quick') != expected_quick):
            if not is_quick and 'quick' in st.query_params:
                del st.query_params['quick']
            st.query_params.update({'mode': mode, 'step': step, **({'quick': '1'} if is_quick else {})})
    except Exception:
        pass


# --- Session State Initialization (centralized in core/state_registry.py) ---
_restore_nav_from_query_params()
ensure_download_state()
_write_nav_to_query_params()

# C-3: Guard against stale cancel events left by a prior run that bypassed
# cleanup_download_state(). Safe to reset whenever no background download
# thread is running — i.e. when not in any of the active download phases
# (scanning, running, isolated_retry). Note: the earlier value `'downloading'`
# was a typo that never matched the real download_status values and caused
# this branch to fire on every rerun, defeating the guard.
_active_dl_statuses = {'scanning', 'running', 'isolated_retry'}
if st.session_state.get('download_status', '') not in _active_dl_statuses:
    reset_download_cancel()

# L-4: Clear a stale debug log exactly once per Streamlit session when debug
# mode is already enabled (e.g. persisted from a previous session via keyring).
# Prevents the user from seeing log entries from an unrelated prior run.
if '_debug_log_cleared' not in st.session_state:
    st.session_state['_debug_log_cleared'] = True
    if st.session_state.get('debug_mode', False):
        from canvas_debug import clear_debug_log as _clear_debug_log
        from pathlib import Path as _Path
        _dbg = _Path(st.session_state.get('download_path', str(_Path.home() / 'Downloads'))) / 'debug_log.txt'
        _clear_debug_log(str(_dbg))

# --- Helper Functions ---

def select_folder():
    from ui_helpers import native_folder_picker
    folder_path = native_folder_picker(initial_dir=st.session_state.get('download_path') or None)
    if folder_path:
        st.session_state['download_path'] = folder_path

def select_sync_folder():
    """Open folder picker for sync mode and store in pending_sync_folder."""
    from ui_helpers import native_folder_picker
    folder_path = native_folder_picker(initial_dir=st.session_state.get('pending_sync_folder') or None)
    if folder_path:
        st.session_state['pending_sync_folder'] = folder_path

def check_cancellation():
    """Backward-compatible alias for is_download_cancelled (used by canvas_logic.py)."""
    return is_download_cancelled()

def cancel_download_callback():
    """Backward-compatible alias for cancel_download (used in on_click= handlers)."""
    cancel_download()



@st.cache_resource(ttl=600, show_spinner=False)  # 10-minute TTL; spinner handled by course selector placeholder
def fetch_courses(token, url):
    """Return all enrolled courses, each annotated with .is_favorite (bool).

    Callers that previously filtered by fav_only should now do:
        [c for c in courses if c.is_favorite]  # favorites
        courses                                  # all
    """
    mgr = CanvasManager(token, url)
    all_courses = list(mgr.get_courses(favorites_only=False))
    all_courses.sort(key=lambda c: (c.name or "").lower())
    try:
        fav_ids = {c.id for c in mgr.get_courses(favorites_only=True)}
    except Exception as e:
        logger.warning(f"fetch_courses: favorites fetch failed, treating all as non-favorite: {e}")
        fav_ids = set()
    for c in all_courses:
        c.is_favorite = c.id in fav_ids
    return all_courses

# --- Sidebar: Navigation & Settings (delegated to ui.auth) ---
if st.session_state['is_authenticated']:
    with st.sidebar:
        from ui.auth import render_sidebar
        render_sidebar(fetch_courses)

# --- Unauthenticated Early-Stop Hook ---
if not st.session_state['is_authenticated']:
    from ui.auth import render_login_page
    render_login_page(fetch_courses)
    st.stop()

# --- Wizard Steps ---
# Wrap in st.empty().container() to prevent stale elements from previous steps
# persisting during long-running operations (e.g., sync downloads via asyncio.run).
_main_content = st.empty()
with _main_content.container():

    # Preset Dialogs (delegated to ui.presets)
    from ui.presets import _save_config_dialog, _presets_hub_dialog

    # STEP 1: Different UI based on mode
    if st.session_state['step'] == 1:
        
        # ========== SYNC MODE - STEP 1 ==========
        if st.session_state['current_mode'] == 'sync':
            render_sync_step1(fetch_courses, _main_content)

        
            # ========== DOWNLOAD MODE - STEP 1 ==========
        else:
            from ui.course_selector import render_course_selector
            render_course_selector(fetch_courses)


    # STEP 2: DOWNLOAD SETTINGS (quick or advanced)
    elif st.session_state['step'] == 2:
        if st.session_state.get('quick_download_mode', False):
            from ui.quick_download import render_quick_download
            render_quick_download(fetch_courses)
        else:
            from ui.download_settings import render_download_settings
            render_download_settings(fetch_courses)


    elif st.session_state['step'] == 3:
        wiz_step = 4 if st.session_state.get('download_status') == 'done' else 3
        render_download_wizard(st, wiz_step)
        
        current_status = st.session_state.get('download_status', 'scanning')
        
        if current_status == 'done':
            st.markdown('<h2 class="step-header">Download Complete!</h2>', unsafe_allow_html=True)
        elif current_status == 'cancelled':
            pass
        else:
            st.markdown('<h2 class="step-header">Downloading...</h2>', unsafe_allow_html=True)
        
        # Safety check: ensure download state exists
        if 'courses_to_download' not in st.session_state or 'current_course_index' not in st.session_state:
            _is_sync = st.session_state.get('current_mode') == 'sync'
            _err_msg = 'Sync state not initialized.' if _is_sync else 'Download state not initialized.'
            st.error(f'{_err_msg} Please go back and try again.')
            _btn_label = 'Go Back to Sync Hub' if _is_sync else 'Go Back to Settings'
            if st.button(_btn_label, key="page_nav_back_to_settings"):
                st.session_state['step'] = 1 if _is_sync else 2
                st.rerun()
            st.stop()
        
        total = len(st.session_state['courses_to_download'])
        current_idx = st.session_state['current_course_index']
        
        # UI elements in correct order
        if st.session_state.get('download_status') == 'running':
            if 'start_time' not in st.session_state:
                st.session_state['start_time'] = time.time()
            if 'log_deque' not in st.session_state:
                st.session_state['log_deque'] = collections.deque(maxlen=200)
                
            header_placeholder = st.empty()
            progress_placeholder = st.empty()
            metrics_placeholder = st.empty()
            active_file_placeholder = st.empty()
            log_placeholder = st.empty()

            st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
            
            cancel_placeholder = st.empty()
            cancel_placeholder.button(
                'Cancel Download',
                type="secondary",
                key="cancel_download_btn",
                on_click=cancel_download_callback,
            )
            # Reserve the post-processing cancel slot NOW so it is always
            # cleared on rerun, preventing the previous course's Cancel PP
            # button from lingering in the DOM during the next download phase.
            pp_cancel_placeholder = st.empty()
        else:
            status_text = st.empty()
            progress_container = st.empty()  # For custom progress bar with text
            mb_counter = st.empty()  # For "Downloading: X / Y MB"
            log_area = st.empty()
        
        # Handle download state
        if st.session_state.get('download_status') == 'scanning':
            # Modern Course Analysis UI (Phase 1)
            total_courses = len(st.session_state['courses_to_download'])
            
            # 1. Define the UI placeholder first
            analysis_ui_placeholder = st.empty()
            
            # 2. Define the Cancel button placeholder second (so it sits below)
            cancel_placeholder = st.empty()
            
            # 3. RENDER THE GLOBAL CANCEL BUTTON ONCE, OUTSIDE THE LOOP.
            # We're currently in the course-analysis (scanning) phase regardless
            # of which mode the user picked, so "Cancel Analysis" is more
            # accurate than "Cancel Download" here.
            cancel_placeholder.button(
                'Cancel Analysis',
                type="secondary",
                key="cancel_download_btn",
                on_click=cancel_download_callback,
            )
            
            cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
            total_items = 0
            total_mb = 0
            
            for idx, course in enumerate(st.session_state['courses_to_download']):
                # Check if the user clicked the global cancel button before processing the next course
                if st.session_state.get('cancel_requested', False):
                    break # Escape the loop immediately!
                    
                current_course_num = idx + 1
                percent = int((current_course_num / total_courses) * 100)
                
                # Progress Hook for granular module scanning
                def analysis_progress_hook(current_mod, total_mods, mod_status_text):
                    mod_percent = int((current_mod / total_mods) * 100) if total_mods > 0 else 0
                    analysis_ui_placeholder.markdown(f"""
                    <div style="background-color: {theme.BG_DARK}; padding: 20px; border-radius: 8px; border: 1px solid {theme.BG_CARD}; margin-bottom: 20px;">
                        <h4 style="color: {theme.TEXT_PRIMARY}; margin-top: 0;">🔍 Analyzing Course Data...</h4>
                        <p style="color: {theme.TEXT_SECONDARY}; font-size: 0.9rem;">Course {current_course_num} of {total_courses}: <b>{esc(course.name)}</b></p>
                        <p style="color: {theme.ACCENT_BLUE}; font-size: 0.8rem; margin-bottom: 5px;">{mod_status_text}</p>
                        <div style="background-color: {theme.BG_CARD}; border-radius: 4px; width: 100%; height: 8px; overflow: hidden;">
                            <div style="background-color: {theme.ACCENT_BLUE}; width: {mod_percent}%; height: 100%; transition: width 0.1s ease;"></div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Cancel button is already rendered above with on_click callback
                    # No need to re-render inside the hook - the callback fires instantly

                # Render initial modern loading UI
                analysis_ui_placeholder.markdown(f"""
                <div style="background-color: {theme.BG_DARK}; padding: 20px; border-radius: 8px; border: 1px solid {theme.BG_CARD}; margin-bottom: 20px;">
                    <h4 style="color: {theme.TEXT_PRIMARY}; margin-top: 0;">🔍 Analyzing Course Data...</h4>
                    <p style="color: {theme.TEXT_SECONDARY}; font-size: 0.9rem;">Course {current_course_num} of {total_courses}: <b>{esc(course.name)}</b></p>
                    <div style="background-color: {theme.BG_CARD}; border-radius: 4px; width: 100%; height: 8px; margin-top: 10px; overflow: hidden;">
                        <div style="background-color: {theme.ACCENT_BLUE}; width: 0%; height: 100%; transition: width 0.3s ease;"></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                
                # Use robust Hybrid file fetching logic directly, identical to actual download loop
                try:
                    # Build scanning-phase secondary settings for accurate counting
                    _scan_secondary = {
                        'download_assignments': st.session_state.get('persistent_dl_assignments', False),
                        'download_syllabus': st.session_state.get('persistent_dl_syllabus', False),
                        'download_announcements': st.session_state.get('persistent_dl_announcements', False),
                        'download_discussions': st.session_state.get('persistent_dl_discussions', False),
                        'download_quizzes': st.session_state.get('persistent_dl_quizzes', False),
                        'download_rubrics': st.session_state.get('persistent_dl_rubrics', False),
                        'isolate_secondary_content': st.session_state.get('persistent_dl_isolate_secondary', True),
                    }
                    course_files, _, _module_map = cm.get_course_files_metadata(
                        course,
                        progress_callback=analysis_progress_hook,
                        secondary_content_settings=_scan_secondary,
                        is_scanning_phase=True
                    )
                    
                    # Apply file filter if needed ('study' vs 'all')
                    allowed_exts = ['.pdf', '.ppt', '.pptx', '.pptm', '.pot', '.potx']
                    filtered_files = []
                    for f in course_files:
                        if st.session_state['file_filter'] == 'study':
                            # Synthetic secondary items (negative ID) bypass the file filter
                            # Since the user specifically checked the box to download them.
                            if getattr(f, 'id', 1) < 0:
                                filtered_files.append(f)
                            else:
                                ext = os.path.splitext(getattr(f, 'filename', ''))[1].lower()
                                if ext in allowed_exts:
                                    filtered_files.append(f)
                        else:
                            filtered_files.append(f)
                            
                    # Calculate accurate file count by excluding synthetic secondary items (id < 0)
                    # from the initial total_items count. These items, along with Pages/Links, 
                    # self-increment total_items during the download phase.
                    initial_file_count = sum(1 for f in filtered_files if getattr(f, 'id', 1) > 0)
                    total_items += initial_file_count

                    
                    # Guard against API returning literal None for size which breaks sum()
                    total_mb += sum((getattr(f, 'size', 0) or 0) for f in filtered_files) / (1024 * 1024)
                    
                except Exception as _analysis_err:
                    # Fallback to older count_course_items if Hybrid fetch fails critically
                    logger.warning(f"Analysis: hybrid fetch failed for '{course.name}', using fallback count: {_analysis_err}")
                    total_items += cm.count_course_items(course, mode=st.session_state['download_mode'], file_filter=st.session_state['file_filter'])
                    total_mb += cm.get_course_total_size_mb(course, st.session_state['download_mode'], file_filter=st.session_state['file_filter'])
            
            # Clear UI before dashboard
            analysis_ui_placeholder.empty()
            
            st.session_state['total_items'] = total_items
            st.session_state['total_mb'] = total_mb
            st.session_state['download_status'] = 'running'

            # Re-arm the completion notification for THIS run. The sentinel is a
            # single flag shared with sync and is otherwise only reset by the
            # cleanup handlers — so a prior download/sync that left it True (e.g.
            # the user navigated away without going through cleanup) would
            # silently swallow this run's "Download Complete" notification.
            st.session_state['completion_beep_fired'] = False
            # Re-arm the "quit Office apps on completion" one-shot for this run.
            st.session_state['_office_quit_fired'] = False
            # macOS: forget any Office apps primed by a previous run (they were quit
            # at that run's completion) so this run launches them fresh + scoped.
            if sys.platform == 'darwin':
                try:
                    from engine.applescript_bridge import reset_office_priming
                    reset_office_priming()
                except Exception:
                    pass

            st.session_state['start_time'] = time.time() # Reset timer immediately before running loop
            
            st.rerun()

        elif st.session_state.get('download_status') == 'running':
            if st.session_state.get('cancel_requested', False) or st.session_state.get('download_cancelled', False):
                st.session_state['download_status'] = 'cancelled'
                st.rerun()
            elif current_idx < total:
                
                # Fetch state variables initialized up top
                start_time = st.session_state.get('start_time', time.time())
                log_deque = st.session_state.get('log_deque', collections.deque(maxlen=200))
                
                # Initialize counters if first run
                if 'downloaded_items' not in st.session_state:
                    st.session_state['downloaded_items'] = 0
                if 'failed_items' not in st.session_state:
                    st.session_state['failed_items'] = 0
                if 'download_errors_list' not in st.session_state:
                    st.session_state['download_errors_list'] = []  # Track error messages in memory
                if 'course_mb_downloaded' not in st.session_state:
                    st.session_state['course_mb_downloaded'] = {}
                    
                # Download the current course
                course = st.session_state['courses_to_download'][current_idx]
                total_items = st.session_state.get('total_items', 1)
                total_mb = st.session_state.get('total_mb', 0)
                
                # Build the shared dashboard placeholders dataclass
                _dp = DashboardPlaceholders(
                    header=header_placeholder,
                    progress=progress_placeholder,
                    metrics=metrics_placeholder,
                    active_file=active_file_placeholder,
                    log=log_placeholder,
                )

                def render_dashboard():
                    current_mb = sum(st.session_state.get('course_mb_downloaded', {}).values())
                    is_retry = st.session_state.get('download_status') == 'isolated_retry'
                    active_total = st.session_state.get('total_items', total_items)
                    active_current = st.session_state.get('retry_downloaded_items', 0) if is_retry else st.session_state.get('downloaded_items', 0)
                    active_current += st.session_state.get('retry_failed_items', 0) if is_retry else st.session_state.get('failed_items', 0)
                    _dl_header = f"Downloading Course {current_idx + 1}/{total}" if total > 1 else "Downloading"
                    render_full_dashboard(
                        _dp, log_deque,
                        header_label=_dl_header,
                        course_name=esc(course.name),
                        current_files=active_current,
                        total_files=active_total,
                        downloaded_mb=current_mb,
                        total_mb=st.session_state.get('total_mb', total_mb),
                        start_time=start_time,
                    )
                
                # Render initial state
                render_dashboard()
                
                def _clean_display_name(raw_msg):
                    """Strip progress-callback prefixes so only the bare filename is stored."""
                    s = str(raw_msg)
                    for prefix in ('Downloading file: ', 'Created link: ', 'Creating link: ', 'Saved: '):
                        if s.startswith(prefix):
                            return s[len(prefix):]
                    return s
                
                def update_ui(msg, progress_type='log', **kwargs):
                    """Update UI with progress information. Wrapped in try/except for async safety."""
                    try:
                        # Exit silently if cancellation is in progress
                        if st.session_state.get('cancel_requested') or st.session_state.get('download_cancelled'):
                            return
                        
                        # Lazy-init download file details tracker
                        if 'download_file_details' not in st.session_state:
                            st.session_state['download_file_details'] = {}

                        if progress_type == 'skipped':
                            st.session_state['downloaded_items'] += 1   # always count the skip
                            if msg:
                                log_deque.append(f"<span style='color: {theme.TEXT_SECONDARY};'>⏭️ Skipped: {msg}</span>")
                            if kwargs.get('explicit_filepath'):
                                course_key = course.name
                                if course_key not in st.session_state['download_file_details']:
                                    st.session_state['download_file_details'][course_key] = []
                                st.session_state['download_file_details'][course_key].append(kwargs['explicit_filepath'])
                                st.session_state['download_file_details'] = st.session_state['download_file_details']
                            render_dashboard()

                        elif progress_type == 'size_skipped':
                            # Track for completion screen display
                            if 'size_skipped_files' not in st.session_state:
                                st.session_state['size_skipped_files'] = []
                            if msg:
                                st.session_state['size_skipped_files'].append(msg)
                            # Oversized file skip: shrink the denominator so progress
                            # math stays honest (file was never queued to download).
                            # Also subtract its size from total_mb for ETA accuracy.
                            sz = kwargs.get('file_size', 0) or 0
                            st.session_state['total_items'] = max(0, st.session_state.get('total_items', total_items) - 1)
                            st.session_state['total_mb'] = max(0.0, st.session_state.get('total_mb', total_mb) - (sz / (1024 * 1024)))
                            if msg:
                                log_deque.append(f"<span style='color: {theme.TEXT_SECONDARY};'>⏭️ Skipped (too large): {msg}</span>")
                            render_dashboard()

                        elif progress_type == 'attachment_discovered':
                            size = kwargs.get('size', 0)
                            st.session_state['total_mb'] = st.session_state.get('total_mb', total_mb) + (size / (1024 * 1024))
                            st.session_state['total_items'] = st.session_state.get('total_items', total_items) + 1
                            render_dashboard()

                        elif progress_type in ('page', 'link', 'secondary'):
                            # Synthetic entities bypass Phase 1, so they must scale BOTH metrics simultaneously
                            st.session_state['downloaded_items'] += 1
                            st.session_state['total_items'] = st.session_state.get('total_items', total_items) + 1
                            if msg:
                                if progress_type == 'secondary':
                                    entity_type = kwargs.get('entity_type', '')
                                    icon = SECONDARY_ENTITY_ICONS.get(entity_type, '📄')
                                    render_active_file(active_file_placeholder, str(msg))
                                    log_deque.append(f"✅ {icon} {_clean_display_name(str(msg))}")
                                else:
                                    render_active_file(active_file_placeholder, str(msg))
                                    log_deque.append(f"✅ {_clean_display_name(str(msg))}")
                                    
                                # Track filename for completion screen
                                course_key = course.name
                                if course_key not in st.session_state['download_file_details']:
                                    st.session_state['download_file_details'][course_key] = []
                                _ledger_name = kwargs.get('explicit_filepath') or _clean_display_name(msg)
                                st.session_state['download_file_details'][course_key].append(_ledger_name)
                                # Guardrail 2: Force state rebind for deep mutation
                                st.session_state['download_file_details'] = st.session_state['download_file_details']
                            render_dashboard()

                        elif progress_type == 'downloading_start':
                            if msg:
                                render_active_file(active_file_placeholder, str(msg))

                        elif progress_type in ('download', 'attachment'):
                            st.session_state['downloaded_items'] += 1
                            if msg:
                                if progress_type == 'attachment':
                                    log_deque.append(f"<span style='color: {theme.ACCENT_BLUE};'>📎 {msg}</span>")
                                else:
                                    log_deque.append(f"✅ {_clean_display_name(str(msg))}")

                                # Track filename for completion screen
                                course_key = course.name
                                if course_key not in st.session_state['download_file_details']:
                                    st.session_state['download_file_details'][course_key] = []
                                _ledger_name = kwargs.get('explicit_filepath') or _clean_display_name(msg)
                                st.session_state['download_file_details'][course_key].append(_ledger_name)
                                # Guardrail 2: Force state rebind for deep mutation
                                st.session_state['download_file_details'] = st.session_state['download_file_details']
                            render_dashboard()

                        elif progress_type == 'phase':
                            # Phase transition (e.g. "Files" → "Secondary Content")
                            phase_name = kwargs.get('phase_name', 'Processing')
                            new_total = kwargs.get('new_total', 0)
                            if new_total > 0:
                                st.session_state['total_items'] += new_total
                            log_deque.append(
                                f"<span style='color: {theme.ACCENT_BLUE};'>"
                                f"Phase: {phase_name}</span>"
                            )
                            render_dashboard()

                            
                        elif progress_type == 'error':
                            if msg:
                                if isinstance(msg, DownloadError):
                                    error_obj = msg
                                else:
                                    error_obj = DownloadError(course.name, "Unknown Item", "Generic Error", str(msg))
                                
                                sig = f"{error_obj.course_name}|{error_obj.item_name}|{error_obj.error_type}|{str(error_obj.message)[:80]}"
                                seen = st.session_state.get('seen_error_sigs', set())

                                if sig not in seen:
                                    seen.add(sig)
                                    st.session_state['seen_error_sigs'] = seen
                                    st.session_state['failed_items'] += 1  # <-- STRICTLY INSIDE THE GUARD
                                    st.session_state['total_items'] = max(st.session_state.get('total_items', total_items), st.session_state.get('downloaded_items', 0) + st.session_state['failed_items'])
                                    
                                    if 'download_errors_list' not in st.session_state:
                                        st.session_state['download_errors_list'] = []
                                    st.session_state['download_errors_list'].append(error_obj)
                                    
                                    _msg_text = esc(error_obj.message if hasattr(error_obj, 'message') else str(msg))
                                    error_text = f"[{esc(course.name)}] {_msg_text}"
                                    log_deque.append(f"<span style='color: #FF7B72;'>❌ {error_text}</span>")
                                    
                            render_dashboard()

                        elif progress_type == 'mb_progress':
                            mb_down_course = kwargs.get('mb_downloaded', 0)
                            if 'course_mb_downloaded' not in st.session_state:
                                 st.session_state['course_mb_downloaded'] = {}
                            st.session_state['course_mb_downloaded'][course.id] = mb_down_course
                            render_dashboard()
                        
                        elif msg and progress_type == 'log':
                            new_line = f"[{esc(course.name)}] {msg}"
                            log_deque.append(f"<span style='color: {theme.TEXT_SECONDARY};'>ℹ️ {new_line}</span>")
                            render_dashboard()
                    except (KeyboardInterrupt, SystemExit):
                        raise
                    except Exception as _e:
                        # Swallow rendering noise (e.g. RuntimeError from asyncio
                        # teardown) so a UI hiccup never kills a download.
                        # NOTE: Streamlit's RerunException/StopException inherit
                        # from BaseException and deliberately pass THROUGH this
                        # handler — that propagation is what makes the Cancel
                        # button abort the running course (the rerun then fires
                        # the on_click cancel callback and routes to the
                        # cancelled screen; the state machine resumes any
                        # non-cancel interruption via skip-existing downloads).
                        _ename = type(_e).__name__
                        if _ename != 'RuntimeError':
                            logger.debug(f"update_ui swallowed unexpected exception: {_ename}: {_e}")
                        pass


                cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
                cm.error_log_enabled = st.session_state.get('error_log_enabled', False)
                # Build the Sync Contract - all settings for this download
                _pp_settings = {
                    'file_filter': st.session_state.get('file_filter', 'all'),
                    'convert_zip': st.session_state.get('persistent_convert_zip', False),
                    'convert_pptx': st.session_state.get('persistent_convert_pptx', False),
                    'convert_html': st.session_state.get('persistent_convert_html', False),
                    'convert_code': st.session_state.get('persistent_convert_code', False),
                    'convert_urls': st.session_state.get('persistent_convert_urls', False),
                    'convert_word': st.session_state.get('persistent_convert_word', False),
                    'convert_video': st.session_state.get('persistent_convert_video', False),
                    'convert_excel': st.session_state.get('persistent_convert_excel', False),
                }
                # Build secondary content settings from persisted state
                _secondary_settings = {
                    'download_assignments': st.session_state.get('persistent_dl_assignments', False),
                    'download_syllabus': st.session_state.get('persistent_dl_syllabus', False),
                    'download_announcements': st.session_state.get('persistent_dl_announcements', False),
                    'download_discussions': st.session_state.get('persistent_dl_discussions', False),
                    'download_quizzes': st.session_state.get('persistent_dl_quizzes', False),
                    'download_rubrics': st.session_state.get('persistent_dl_rubrics', False),
                    'download_submissions': st.session_state.get('persistent_dl_submissions', False),
                    'isolate_secondary_content': st.session_state.get('persistent_dl_isolate_secondary', True),
                }
                if st.session_state.get('debug_mode', False):
                    from canvas_debug import log_debug as _app_log
                    from canvas_debug import set_active_debug_file as _set_dbg, log_session_header as _dbg_header
                    _dl_dbg = str(Path(st.session_state['download_path']) / 'debug_log.txt')
                    # Register for the logging bridge: from here on, every
                    # logger.info/error from any app module (converters,
                    # post-processing, applescript bridge...) is mirrored
                    # into this file automatically.
                    _set_dbg(_dl_dbg)
                    if current_idx == 0:
                        _dbg_header(_dl_dbg, context=f"Download mode | {total} course(s)")
                    _pp_active = [k.replace('convert_', '') for k, v in _pp_settings.items() if v and k.startswith('convert_')]
                    _sec_active = [k.replace('download_', '') for k, v in _secondary_settings.items() if v and k.startswith('download_')]
                    _app_log(f"=== Download Start: {course.name} | Course {current_idx + 1}/{total} ===", _dl_dbg)
                    _app_log(f"Mode: {st.session_state['download_mode']} | Filter: {st.session_state.get('file_filter', 'all')}", _dl_dbg)
                    _app_log(f"Post-processing: [{', '.join(_pp_active) or 'none'}]", _dl_dbg)
                    _app_log(f"Secondary content: [{', '.join(_sec_active) or 'none'}]", _dl_dbg)

                try:
                    asyncio.run(cm.download_course_async(
                        course,
                        st.session_state['download_mode'],
                        st.session_state['download_path'],
                        progress_callback=update_ui,
                        check_cancellation=check_cancellation,
                        file_filter=st.session_state['file_filter'],
                        debug_mode=st.session_state.get('debug_mode', False),
                        post_processing_settings=_pp_settings,
                        secondary_content_settings=_secondary_settings
                    ))
                except Exception as _dl_crash:
                    logger.error(f"Download engine crashed for '{course.name}': {_dl_crash}", exc_info=True)
                    _crash_err = DownloadError(
                        course.name, "Download Engine", "Fatal Crash",
                        f"Download loop terminated unexpectedly: {_dl_crash}",
                        raw_error=_dl_crash, is_app_error=True,
                    )
                    st.session_state.setdefault('download_errors_list', []).append(_crash_err)
                    log_deque.append(
                        f"<span style='color: #FF7B72;'>❌ Fatal: download engine crashed for "
                        f"{esc(course.name)}: {esc(str(_dl_crash))}</span>"
                    )
                    render_dashboard()
                
                # --- Post-Processing: Setup ---
                _has_pp = any(
                    _pp_settings.get(k, False) for k in (
                        'convert_zip', 'convert_pptx', 'convert_html', 'convert_code',
                        'convert_urls', 'convert_word', 'convert_video', 'convert_excel'
                    )
                )

                # --- Post-Processing: Setup logging for NotebookLM hooks ---
                save_dir = st.session_state['download_path']
                debug_mode = st.session_state.get('debug_mode', False)
                root_dir = Path(save_dir)
                course_name = cm._sanitize_filename(course.name)
                course_folder_for_debug = root_dir / course_name
                debug_file = (root_dir / "debug_log.txt") if debug_mode else None

                # Inject course header into the global debug log (append, never overwrite)
                if debug_file:
                    try:
                        with open(debug_file, "a", encoding="utf-8") as f:
                            f.write(f"\n{'='*50}\n--- Post-Processing: {esc(course.name)} ---\n{'='*50}\n")
                    except Exception:
                        pass

                # --- Post-Download Conversion Pipeline (via engine) ---
                course_name_sanitized = cm._sanitize_filename(course.name)
                course_folder = Path(st.session_state['download_path']) / course_name_sanitized

                if course_folder.exists():
                    if _has_pp:
                        st.session_state['is_post_processing'] = True
                        cancel_placeholder.empty()
                        pp_cancel_placeholder.button(
                            "Cancel Post-Processing",
                            key="cancel_pp_download",
                            type="secondary",
                            on_click=cancel_download_callback,
                        )
                    # macOS: launch (hidden) ONLY the Office apps this course will
                    # actually use — scoped to the file types present in the folder,
                    # so a course with just .pptx never opens Word or Excel. Cheap and
                    # idempotent per app across the multi-course run.
                    if sys.platform == 'darwin':
                        try:
                            from engine.applescript_bridge import (
                                prime_office_automation, office_contract_from_folder,
                            )
                            prime_office_automation(
                                office_contract_from_folder(course_folder, _pp_settings)
                            )
                        except Exception as _prime_err:
                            logger.warning(f"Failed to prime Office automation: {_prime_err}")
                    invoke_post_processing(
                        course_folder=course_folder,
                        course_id=course.id,
                        course_name=course.name,
                        placeholders=_dp,
                        log_deque=log_deque,
                        error_log_path=Path(st.session_state['download_path']) if st.session_state.get('error_log_enabled', False) else None,
                        mode='download',
                    )
                    if debug_file:
                        from canvas_debug import log_debug as _pp_fin_log
                        _pp_active_done = [k.replace('convert_', '') for k, v in _pp_settings.items() if v and k.startswith('convert_')]
                        _dl_count_done = len(st.session_state.get('download_file_details', {}).get(course.name, []))
                        _err_count_done = len(st.session_state.get('download_errors_list', []))
                        _pp_fin_log(
                            f"=== Course Finished: {course.name} | "
                            f"Downloaded: {_dl_count_done} items | Errors: {_err_count_done} ===",
                            str(debug_file),
                        )
                        if _has_pp:
                            _pp_fin_log(f"Post-processing ran: [{', '.join(_pp_active_done) or 'none'}]", str(debug_file))
                # --- End Post-Download Conversion Pipeline ---
                # Reset post-processing flag now that PP for this course is done.
                # If we cancel during the NEXT course's download (before its PP
                # starts), the cancelled screen must say "Cancelled during
                # download", not "Cancelled during post-processing".
                st.session_state['is_post_processing'] = False
                # Clear the blue status text so it doesn't linger on completion
                active_file_placeholder.empty()

                # Move to next course (unless cancelled)
                if st.session_state.get('download_cancelled', False):
                    st.session_state['download_status'] = 'cancelled'
                    st.rerun()
                
                st.session_state['current_course_index'] += 1
                
                # Check if we're done
                if st.session_state['current_course_index'] >= total:
                    st.session_state['download_status'] = 'done'

                # Auto-rerun instantly to process next course or done screen
                st.rerun()
            else:
                # All done
                st.session_state['download_status'] = 'done'
                
                # --- NEW: Force-write session error log (Backup/Guaranteed file) ---
                if 'download_errors_list' in st.session_state and st.session_state['download_errors_list'] and st.session_state.get('error_log_enabled', False):
                    try:
                        from pathlib import Path
                        root_path = Path(st.session_state['download_path'])
                        root_path.mkdir(parents=True, exist_ok=True)
                        session_log = root_path / "session_errors.txt"
                        with open(session_log, "w", encoding="utf-8") as f:
                            f.write(f"Session Error Log - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                            f.write("===================================================\n")
                            for err in st.session_state['download_errors_list']:
                                f.write(f"{err.to_log_entry()}\n")
                    except Exception as e:
                        logger.error(f"Failed to write session log: {e}")
                # -------------------------------------------------------------------
        
        elif st.session_state.get('download_status') == 'isolated_retry':
                
            header_placeholder = st.empty()
            progress_placeholder = st.empty()
            metrics_placeholder = st.empty()
            active_file_placeholder = st.empty()
            log_placeholder = st.empty()
            
            st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
            cancel_placeholder = st.empty()
            cancel_placeholder.button(
                'Cancel Retry',
                type="secondary",
                key="cancel_retry_btn",
                on_click=cancel_download_callback,
            )

            queue = st.session_state.get('isolated_retry_queue', [])

            # 1. Update total_items to reflect strictly the retry queue
            total_items = len(queue)
            st.session_state['total_items'] = total_items

            # 2. Dynamically calculate MB from the encapsulated file_dict (Object/Dict safe)
            total_bytes = 0
            for err in queue:
                # Safely handle both Object and Dict representations of the error payload
                ctx = getattr(err, 'context', None) if not isinstance(err, dict) else err.get('context')
                
                if isinstance(ctx, dict):
                    f_dict = ctx.get('file_dict', {})
                    if isinstance(f_dict, dict):
                        total_bytes += f_dict.get('size', 0)

            total_mb = total_bytes / (1024 * 1024) if total_bytes > 0 else 0.0

            # 3. Explicitly overwrite the global session state so progress metrics use the new denominator
            st.session_state['total_mb'] = total_mb
            start_time = st.session_state.get('start_time', time.time())
            log_deque = st.session_state.get('log_deque', collections.deque(maxlen=200))
            
            # Map course_name -> course object
            course_map = {c.name: c for c in st.session_state.get('courses_to_download', [])}
            
            # Group errors by course_name
            queue_by_course = {}
            for err in queue:
                queue_by_course.setdefault(err.course_name, []).append(err)
            
            # Build the retry dashboard placeholders
            _dp = DashboardPlaceholders(
                header=header_placeholder,
                progress=progress_placeholder,
                metrics=metrics_placeholder,
                active_file=active_file_placeholder,
                log=log_placeholder,
            )

            def render_dashboard(current_course_name):
                bytes_down = st.session_state.get('retry_mb_tracker', {}).get('bytes_downloaded', 0)
                current_mb = bytes_down / (1024 * 1024)
                active_total = st.session_state.get('total_items', 1)
                active_current = st.session_state.get('retry_downloaded_items', 0) + st.session_state.get('retry_failed_items', 0)
                render_full_dashboard(
                    _dp, log_deque,
                    header_label="Retrying Failed Items",
                    course_name=esc(current_course_name),
                    current_files=active_current,
                    total_files=active_total,
                    downloaded_mb=current_mb,
                    total_mb=st.session_state.get('total_mb', total_mb),
                    start_time=st.session_state.get('start_time', time.time()),
                    show_total_mb=False,
                )
            
            # Use same update_ui logic to append errors/successes
            def update_ui(msg, progress_type='log', **kwargs):
                try:
                    if st.session_state.get('cancel_requested') or st.session_state.get('download_cancelled'): return
                    
                    is_retry = st.session_state.get('download_status') == 'isolated_retry'
                    
                    if 'download_file_details' not in st.session_state:
                         st.session_state['download_file_details'] = {}
                    if is_retry and 'retry_isolated_details' not in st.session_state:
                         st.session_state['retry_isolated_details'] = {}
                         
                    course_name_ref = kwargs.get('course_name', 'Unknown')
                         
                    if progress_type == 'skipped':
                        if msg:
                            if is_retry:
                                st.session_state['retry_downloaded_items'] = st.session_state.get('retry_downloaded_items', 0) + 1
                            else:
                                st.session_state['downloaded_items'] += 1
                            log_deque.append(f"<span style='color: {theme.TEXT_SECONDARY};'>⏭️ Skipped: {msg}</span>")
                            if kwargs.get('explicit_filepath'):
                                if is_retry:
                                    if course_name_ref not in st.session_state['retry_isolated_details']:
                                        st.session_state['retry_isolated_details'][course_name_ref] = []
                                    st.session_state['retry_isolated_details'][course_name_ref].append(kwargs['explicit_filepath'])
                                    st.session_state['retry_isolated_details'] = st.session_state['retry_isolated_details']
                                else:
                                    if course_name_ref not in st.session_state['download_file_details']:
                                        st.session_state['download_file_details'][course_name_ref] = []
                                    st.session_state['download_file_details'][course_name_ref].append(kwargs['explicit_filepath'])
                                    st.session_state['download_file_details'] = st.session_state['download_file_details']
                        render_dashboard(course_name_ref)

                    elif progress_type == 'size_skipped':
                        # Track for completion screen display
                        if 'size_skipped_files' not in st.session_state:
                            st.session_state['size_skipped_files'] = []
                        if msg:
                            st.session_state['size_skipped_files'].append(msg)
                            log_deque.append(f"<span style='color: {theme.TEXT_SECONDARY};'>⏭️ Skipped (too large): {msg}</span>")
                        # In the retry path the total_items denominator is the length
                        # of the retry queue, not the global total, so we leave it alone.
                        render_dashboard(course_name_ref)

                    elif progress_type == 'attachment_discovered':
                        st.session_state['total_items'] = st.session_state.get('total_items', 1) + 1
                        render_dashboard(course_name_ref)

                    elif progress_type == 'downloading_start':
                        if msg:
                            render_active_file(active_file_placeholder, str(msg))

                    elif progress_type in ('download', 'page', 'link', 'secondary', 'attachment'):
                        if is_retry:
                            st.session_state['retry_downloaded_items'] = st.session_state.get('retry_downloaded_items', 0) + 1
                        else:
                            st.session_state['downloaded_items'] += 1
                        if msg:
                            log_deque.append(f"✅ {_clean_display_name(str(msg))}")
                            
                            if kwargs.get('explicit_filepath'):
                                if is_retry:
                                    if course_name_ref not in st.session_state['retry_isolated_details']:
                                        st.session_state['retry_isolated_details'][course_name_ref] = []
                                    st.session_state['retry_isolated_details'][course_name_ref].append(kwargs['explicit_filepath'])
                                    st.session_state['retry_isolated_details'] = st.session_state['retry_isolated_details']
                                else:
                                    if course_name_ref not in st.session_state['download_file_details']:
                                        st.session_state['download_file_details'][course_name_ref] = []
                                    st.session_state['download_file_details'][course_name_ref].append(kwargs['explicit_filepath'])
                                    st.session_state['download_file_details'] = st.session_state['download_file_details']
                        render_dashboard(course_name_ref)
                    
                    elif progress_type == 'error':
                        if not is_retry:
                            st.session_state['failed_items'] += 1
                            st.session_state['total_items'] = max(st.session_state.get('total_items', 1), st.session_state.get('downloaded_items', 0) + st.session_state['failed_items'])
                        if msg:
                            if isinstance(msg, DownloadError): error_obj = msg
                            else: error_obj = DownloadError(course_name_ref, "Unknown Item", "Generic Error", str(msg))
                            
                            # Deduplicate errors to prevent log spam.
                            # During retry, use course_name|item_name only (no error_type)
                            # so that a file with 'No URL' (initial) and 'URL Expiration'
                            # (retry) is recognized as the same underlying failure.
                            if is_retry:
                                sig = f"{error_obj.course_name}|{error_obj.item_name}"
                            else:
                                sig = f"{error_obj.course_name}|{error_obj.item_name}|{error_obj.error_type}"
                            seen = st.session_state.get('seen_error_sigs', set())
                            if sig not in seen:
                                seen.add(sig)
                                st.session_state['seen_error_sigs'] = seen
                                
                                # Increment retry counter INSIDE dedup guard so
                                # suppressed duplicates don't inflate the count.
                                if is_retry:
                                    st.session_state['retry_failed_items'] = st.session_state.get('retry_failed_items', 0) + 1
                                
                                if 'download_errors_list' not in st.session_state: st.session_state['download_errors_list'] = []
                                st.session_state['download_errors_list'].append(error_obj)
                                
                                _msg_text = esc(error_obj.message if hasattr(error_obj, 'message') else str(msg))
                                error_text = f"[{esc(course_name_ref)}] {_msg_text}"
                                log_deque.append(f"<span style='color: #FF7B72;'>❌ {error_text}</span>")
                        render_dashboard(course_name_ref)

                    elif msg and progress_type == 'log':
                        new_line = f"[{esc(course_name_ref)}] {msg}"
                        log_deque.append(f"<span style='color: {theme.TEXT_SECONDARY};'>ℹ️ {new_line}</span>")
                        render_dashboard(course_name_ref)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as _e:
                    # Match the main update_ui handler: swallow rendering noise.
                    # RerunException/StopException are BaseException and pass
                    # through — that is what makes Cancel work mid-retry.
                    _ename = type(_e).__name__
                    if _ename != 'RuntimeError':
                        logger.debug(f"retry update_ui swallowed: {_ename}: {_e}")

            cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
            cm.error_log_enabled = st.session_state.get('error_log_enabled', False)
            
            if 'retry_mb_tracker' not in st.session_state:
                st.session_state['retry_mb_tracker'] = {'bytes_downloaded': 0}
            
            for course_name, errors in queue_by_course.items():
                if st.session_state.get('cancel_requested') or st.session_state.get('download_cancelled'): break
                course = course_map.get(course_name)
                if not course: continue
                
                render_dashboard(course.name)
                
                try:
                    dropped_errors = asyncio.run(cm.download_isolated_batch_async(
                        course=course,
                        error_queue=errors,
                        save_dir=st.session_state['download_path'],
                        progress_callback=lambda msg, progress_type='log', **kw: update_ui(msg, progress_type, course_name=kw.pop('course_name', course.name), **kw),
                        check_cancellation=check_cancellation,
                        debug_mode=st.session_state.get('debug_mode', False),
                        mb_tracker=st.session_state['retry_mb_tracker']
                    ))
                except Exception as _retry_crash:
                    logger.error(f"Isolated retry engine crashed for '{course.name}': {_retry_crash}", exc_info=True)
                    update_ui(f"Retry engine crashed: {_retry_crash}", progress_type='log', course_name=course.name)
                    dropped_errors = 0
                if dropped_errors:
                    st.session_state['skipped_discovery_errors'] = st.session_state.get('skipped_discovery_errors', 0) + dropped_errors
            
            # --- Post-Processing Pipeline for Retry (via engine) ---
            if st.session_state.get('cancel_requested') or st.session_state.get('download_cancelled'):
                if not st.session_state.get('_sync_cancel_warning_shown', False):
                    from ui.amber_notice import render_amber_notice
                    render_amber_notice(
                        "Retry cancelled — post-processing skipped.",
                        detail="Any files that downloaded successfully before cancellation are available in your folder.",
                    )
                    st.session_state['_sync_cancel_warning_shown'] = True
            else:
                for course_name in queue_by_course.keys():
                    course = course_map.get(course_name)
                    if not course: continue
                    course_name_sanitized = cm._sanitize_filename(course.name)
                    course_folder = Path(st.session_state['download_path']) / course_name_sanitized
    
                    if course_folder.exists():
                        contract = build_conversion_contract()
    
                        if any(contract.values()):
                            # --- FIX: Post-Processing Overkill Pipeline Swaps ---
                            success_names = st.session_state.get('retry_isolated_details', {}).get(course.name, [])
                            if not success_names:
                                continue  # Skip post-processing entirely if nothing actually succeeded during this retry
                                
                            success_paths = []
                            for n in success_names:
                                if Path(n).is_absolute():
                                    success_paths.append(str(Path(n).resolve()))
                                else:
                                    success_paths.append(str((course_folder / cm._sanitize_filename(n)).resolve()))
                            
                            st.session_state['is_post_processing'] = True
                            invoke_post_processing(
                                course_folder=course_folder,
                                course_id=course.id,
                                course_name=course.name,
                                placeholders=_dp,
                                log_deque=log_deque,
                                error_log_path=Path(st.session_state['download_path']) if st.session_state.get('error_log_enabled', False) else None,
                                mode='download',
                                contract=contract,
                                explicit_files=success_paths,
                            )
                            # PP done — clear the flag so subsequent cancel
                            # messages don't misreport the phase (see same
                            # rationale in the normal download path).
                            st.session_state['is_post_processing'] = False
            # --- End Post-Processing Pipeline ---

            # --- Success Metrics Rehydration & Error Resolution ---
            retry_success_details = st.session_state.get('retry_isolated_details', {})
            global_details = st.session_state.get('download_file_details', {})
            global_errors = st.session_state.get('download_errors_list', [])
            
            resolved_count = 0
            
            from pathlib import Path
            temp_cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
            
            for c_name, success_list in retry_success_details.items():
                # 1. Merge into global details
                if c_name not in global_details:
                    global_details[c_name] = []
                for p in success_list:
                    if p not in global_details[c_name]:
                        global_details[c_name].append(p)
                
                # 2. Iterate successes to find resolved errors
                success_basenames = {Path(p).name for p in success_list}
                resolved_for_course = []
                
                # Filter out errors that are now resolved
                new_global_errors = []
                for err in global_errors:
                    # Guardrail 2: The Serialization Trap
                    ctx = getattr(err, 'context', None) if not isinstance(err, dict) else err.get('context')
                    err_filepath = ctx.get('filepath') if isinstance(ctx, dict) else None
                    
                    err_course_name = getattr(err, 'course_name', None) if not isinstance(err, dict) else err.get('course_name')
                    err_item_name = getattr(err, 'item_name', None) if not isinstance(err, dict) else err.get('item_name')
                    
                    is_resolved = False
                    if err_filepath:
                         is_resolved = any(str(Path(p).resolve()) == str(Path(err_filepath).resolve()) for p in success_list)
                    else:
                         is_resolved = (err_course_name == c_name and err_item_name in success_basenames)
                         
                    if is_resolved:
                        resolved_for_course.append(err_item_name)
                        resolved_count += 1
                        
                        # --- FIX: Error Signature Drift ---
                        # Reconstruct the exact signature used to deduplicate the error
                        err_error_type = getattr(err, 'error_type', 'Unknown Type') if not isinstance(err, dict) else err.get('error_type', 'Unknown Type')
                        sig = f"{c_name}|{err_item_name}|{err_error_type}"
                        
                        # Safely purge from tracking buffer to prevent permanent muting
                        # CRITICAL: Use .discard() instead of .remove() to prevent KeyError crashes
                        seen = st.session_state.get('seen_error_sigs', set())
                        if sig in seen:
                            seen.discard(sig)
                            st.session_state['seen_error_sigs'] = seen
                        
                        # Guardrail 3: Safe Directory Resolution (fallback to course folder if err_filepath missing)
                        save_dir = Path(err_filepath).parent if err_filepath else Path(st.session_state['download_path']) / temp_cm._sanitize_filename(c_name)
                        log_file = save_dir / "download_errors.txt"
                        if log_file.exists() and st.session_state.get('error_log_enabled', False):
                            try:
                                with open(log_file, "a", encoding="utf-8") as f:
                                    f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [RESOLVED] Successfully downloaded: {err_item_name}\n")
                            except Exception as e:
                                logger.error(f"Failed to write [RESOLVED] log: {e}")
                    else:
                        new_global_errors.append(err)
                global_errors = new_global_errors

            # Update session state with rehydrated metrics
            st.session_state['download_file_details'] = global_details
            st.session_state['download_errors_list'] = global_errors
            st.session_state['downloaded_items'] = st.session_state.get('downloaded_items', 0) + st.session_state.get('retry_downloaded_items', 0)
            st.session_state['failed_items'] = max(0, st.session_state.get('failed_items', 0) - resolved_count)

            # Record retry outcome for the completion screen feedback card
            st.session_state['retry_attempted'] = True
            st.session_state['retry_resolved_count'] = resolved_count
            st.session_state['retry_total_attempted'] = len(st.session_state.get('isolated_retry_queue', []))

            # Post-retry cleanup
            # --- FIX: Cancel-to-Done Bypass ---
            if st.session_state.get('cancel_requested') or st.session_state.get('download_cancelled'):
                st.session_state['download_status'] = 'cancelled'
            else:
                st.session_state['download_status'] = 'done'
            st.rerun()

        elif st.session_state.get('download_status') == 'done':
            # --- Premium Completion Screen (Parity with Sync) ---
            download_errors = st.session_state.get('download_errors_list', [])
            # Use ACTUAL downloaded bytes (tracked by mb_progress callback),
            # not the estimated total from the scanning phase which can be 0
            # if Canvas API returns null sizes, and gets overwritten by retry.
            actual_downloaded_mb = sum(st.session_state.get('course_mb_downloaded', {}).values())
            total_bytes = int(actual_downloaded_mb * 1024 * 1024)

            # Build the set of failed filenames so we can filter them out of the
            # file-detail list. This ensures the card count matches the expander.
            _failed_names = set()
            for err in download_errors:
                if hasattr(err, 'item_name') and err.item_name:
                    _failed_names.add(err.item_name)

            file_details_raw = st.session_state.get('download_file_details', {})
            file_details = {}
            for k, paths in file_details_raw.items():
                # Present only the base name to the UI rendering loop to preserve Completion Card aesthetics
                filtered = [Path(p).name for p in paths if Path(p).name not in _failed_names]
                if filtered:
                    file_details[k] = filtered
            st.session_state['download_file_details'] = file_details

            success_count = sum(len(v) for v in file_details.values())

            # Completion beep - fired exactly once per run via a session
            # sentinel, using the accurate filtered success_count so the
            # notification matches what the completion card shows.
            if (
                st.session_state.get('notifications_enabled', True)
                and not st.session_state.get('completion_beep_fired', False)
            ):
                _dl_courses = len(file_details)
                _dl_summary = f"Downloaded {success_count} file{'s' if success_count != 1 else ''} across {_dl_courses} course{'s' if _dl_courses != 1 else ''}."
                play_completion_beep(mode='download', summary=_dl_summary)
                st.session_state['completion_beep_fired'] = True

            # macOS: post-processing is finished and we're on the completion
            # screen — tidy away the Office apps we launched for conversion
            # NOW (the user expects them gone here, not only after clicking
            # "Go to front page"). Quits only apps with zero open documents, so
            # a user's own workbook/deck is never touched. Separate one-shot
            # sentinel so it fires regardless of the notifications toggle.
            import sys as _sys_q
            if _sys_q.platform == 'darwin' and not st.session_state.get('_office_quit_fired'):
                st.session_state['_office_quit_fired'] = True
                try:
                    from engine.applescript_bridge import quit_idle_office_apps
                    quit_idle_office_apps()
                except Exception:
                    pass

            # 1. Summary card (absorbs retry feedback + discovery warnings)
            size_skipped = st.session_state.get('size_skipped_files', [])
            limit_mb = st.session_state.get('max_file_size_mb', 0)
            retry_attempted = st.session_state.get('retry_attempted', False)
            retry_total = st.session_state.get('retry_total_attempted', 0)
            retry_resolved = st.session_state.get('retry_resolved_count', 0)

            _retry_failed = retry_attempted and retry_total > 0 and retry_resolved == 0

            with st.container(border=True, key='completion_dashboard'):
                # Split errors: retriable file errors / unresolvable file errors / app-level errors
                _app_errors = sum(1 for err in download_errors if getattr(err, 'is_app_error', False))
                _file_errors = [err for err in download_errors if not getattr(err, 'is_app_error', False)]
                _retriable = sum(
                    1 for err in _file_errors
                    if isinstance(getattr(err, 'context', None), dict)
                    and err.context.get('filepath')
                    and getattr(err, 'error_type', '') != 'LTI/Media Stream'
                )
                _unresolvable = len(_file_errors) - _retriable

                render_completion_card(
                    synced_count=success_count,
                    error_count=len(download_errors),
                    total_bytes=total_bytes,
                    mode='download',
                    size_skipped_files=size_skipped,
                    size_limit_mb=limit_mb,
                    retry_attempted=retry_attempted,
                    retry_resolved=retry_resolved,
                    retry_total=retry_total,
                    retriable_count=_retriable,
                    unresolvable_count=_unresolvable,
                    app_error_count=_app_errors,
                    courses_count=len(file_details),
                )

                # 2. Post-processing warning
                render_pp_warning(st.session_state.get('pp_failure_count', 0))

                # Office watchdog broad-kill warning (parity with the sync
                # completion screen — previously only shown there even though
                # the same converters run in the download flow).
                if st.session_state.pop('pp_force_kill_warning', False):
                    from ui.amber_notice import render_amber_notice
                    render_amber_notice(
                        "An Office process was force-closed during conversion.",
                        icon="⚠️",
                        detail=(
                            "A hung Office process was terminated to unblock conversion. "
                            "If you had other unsaved Word, Excel, or PowerPoint files open, "
                            "they may have been closed without saving."
                        ),
                    )

                # Size-skipped files are now rendered inside render_completion_card

                # 3. Error section (with retry button inside)
                download_path = Path(st.session_state['download_path'])
                error_log_paths = []
                for c in st.session_state.get('courses_to_download', []):
                    cm_temp = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
                    log_file = download_path / cm_temp._sanitize_filename(c.name) / "download_errors.txt"
                    if log_file.exists():
                        error_log_paths.append(log_file)

                # Check if retriable errors exist (file errors with filepath context, not LTI streams, not app errors)
                has_retriable_errors = any(
                    not getattr(err, 'is_app_error', False)
                    and isinstance(getattr(err, 'context', None), dict)
                    and err.context.get('filepath')
                    and getattr(err, 'error_type', '') != 'LTI/Media Stream'
                    for err in download_errors
                ) if download_errors else False

                def _do_retry():
                    """Sniper Retry callback - jump straight to isolated_retry."""
                    current_errors = list(st.session_state.get('download_errors_list', []))

                    retriable_queue = []
                    structural_count = 0
                    for err in current_errors:
                        ctx = getattr(err, 'context', None) if not isinstance(err, dict) else err.get('context')
                        if isinstance(ctx, dict) and ctx.get('filepath') and getattr(err, 'error_type', '') != 'LTI/Media Stream':
                            retriable_queue.append(err)
                        else:
                            structural_count += 1

                    st.session_state['isolated_retry_queue'] = retriable_queue
                    st.session_state['download_status'] = 'isolated_retry'

                    # Initialize sandboxed variables for the retry isolated UI
                    st.session_state['retry_isolated_details'] = {}
                    st.session_state['retry_downloaded_items'] = 0
                    st.session_state['retry_failed_items'] = 0
                    st.session_state['retry_attempted'] = False

                    st.session_state['cancel_requested'] = False
                    st.session_state['download_cancelled'] = False

                    # Rebuild seen_error_sigs using course_name|item_name only (no error_type)
                    existing_errors = list(st.session_state.get('download_errors_list', []))
                    normalized_sigs = set()
                    for _err in existing_errors:
                        if hasattr(_err, 'course_name') and hasattr(_err, 'item_name'):
                            normalized_sigs.add(f"{_err.course_name}|{_err.item_name}")
                    st.session_state['seen_error_sigs'] = normalized_sigs
                    st.session_state['skipped_discovery_errors'] = structural_count
                    st.session_state['pp_failure_count'] = 0
                    st.session_state['pp_success_count'] = 0
                    st.session_state['log_content'] = ""
                    st.session_state['start_time'] = time.time()

                    st.session_state['total_items'] = len(st.session_state['isolated_retry_queue'])

                    st.rerun()

                render_error_section(
                    download_errors, error_log_paths,
                    dialog_fn=error_log_dialog,
                    key_prefix='dl',
                    retry_btn_callback=_do_retry if has_retriable_errors and not retry_attempted else None,
                    has_retriable_errors=has_retriable_errors,
                    retry_failed=_retry_failed,
                )

            # 4. Per-course folder cards with filetype summary
            folder_paths = {}
            for c in st.session_state.get('courses_to_download', []):
                cm_temp = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
                course_folder = download_path / cm_temp._sanitize_filename(c.name)
                folder_paths[c.name] = str(course_folder)

            render_folder_cards(file_details, folder_paths, key_prefix='dl')
        
        elif st.session_state.get('download_status') == 'cancelled':
            # Premium styled cancellation card (matches sync_ui.py design)
            downloaded_count = st.session_state.get('downloaded_items', 0)
            total_items_count = st.session_state.get('total_items', 0)
            
            # Dynamic text: "course" during scanning, "file" during download, post-processing status
            if st.session_state.get('is_post_processing', False):
                cancel_summary_msg = "Cancelled during post-processing."
            else:
                is_file_phase = total_items_count > 0
                if is_file_phase:
                    cancel_summary_msg = f"Cancelled after {downloaded_count} of {total_items_count} file{'s' if total_items_count != 1 else ''}."
                else:
                    cancel_summary_msg = "Cancelled during Course Analysis."
            
            st.markdown(f"""
            <div style="
                background: linear-gradient(135deg, {theme.ERROR_BG} 0%, {theme.BG_PAGE} 100%);
                border: 1px solid {theme.ERROR};
                border-radius: 12px;
                padding: 28px 32px;
                margin: 20px 0;
                box-shadow: 0 4px 20px rgba(239, 68, 68, 0.15);
            ">
                <div style="display: flex; align-items: center; gap: 14px; margin-bottom: 12px;">
                    <span style="font-size: 2rem;">🛑</span>
                    <h2 style="margin: 0; color: {theme.ERROR}; font-size: 1.5rem; font-weight: 700;">Download Cancelled</h2>
                </div>
                <p style="color: {theme.TEXT_LIGHT}; font-size: 1rem; margin: 0 0 8px 0;">
                    {'Download was cancelled.'}
                </p>
                <div style="
                    background: rgba(239, 68, 68, 0.08);
                    border-radius: 8px;
                    padding: 12px 16px;
                    margin-top: 12px;
                    display: inline-block;
                ">
                    <span style="color: {theme.ERROR_LIGHT}; font-size: 0.9rem; font-weight: 600;">
                        {cancel_summary_msg}
                    </span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Show errors if any
            download_errors = st.session_state.get('download_errors_list', [])
            if download_errors:
                with st.expander(f"Error Details ({len(download_errors)})", expanded=False):
                    for err in download_errors[:20]:
                        if hasattr(err, 'message'):
                            st.markdown(f"\u274c {err.message}")
                        else:
                            st.markdown(f"\u274c {err}")
                    if len(download_errors) > 20:
                        st.caption(f"  ... and {len(download_errors) - 20} more")
        
        if st.session_state['download_status'] in ['done', 'cancelled']:
            st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
            button_text = 'Go to front page'
            col_front, _ = st.columns([0.35, 0.65])
            with col_front:
                if st.button(button_text, type="primary", use_container_width=True, key="page_nav_front_page"):
                    from core.state_registry import cleanup_download_state
                    cleanup_download_state()
                    st.rerun()


    # STEP 4: SYNC ANALYSIS (Only shown when current_mode is 'sync')
    elif st.session_state['step'] == 4:
        render_sync_step4()
