import streamlit as st
import streamlit.components.v1 as components
from core.canvas_logic import CanvasManager, DownloadError
import asyncio
import collections
import os
import logging
import sys
import time
from datetime import datetime

from shared import theme

logger = logging.getLogger(__name__)
from pathlib import Path
from sync_ui import render_sync_step1, render_sync_step4
from shared.helpers import (
    esc, learned_transfer_priors, remember_transfer_priors, render_download_wizard,
    split_delivery_errors,
)
from shared.components import (
    render_completion_card, render_folder_cards,
    render_error_section, render_pp_warning,
    render_archives_skipped_notice,
    error_log_dialog, render_panopto_summary,
    fresh_container,
)
from styles import inject_css
from shared.components import inject_material_icons_font
from core.state_registry import (
    ensure_download_state,
)
from core.cancellation import cancel_download, is_download_cancelled, reset_download_cancel
from engine.estimation import panopto_estimators, stepwise_estimator, transfer_estimator
from engine.progress_dashboard import (
    DashboardPlaceholders, render_full_dashboard, render_active_file,
    render_progress_header, render_progress_bar, render_metrics,
    render_analysis_dashboard, analysis_percent, render_terminal_log, PHASE_BAR_COLOR,
    metric_count, metric_eta, metric_elapsed, metric_speed, metric_transferred,
    metric_value, log_line, log_divider, log_meta, file_icon_svg, entity_icon_svg,
)
from engine.post_processing_bridge import invoke_post_processing, build_conversion_contract
from engine.notifications import play_completion_beep, request_macos_notification_permission

# Page Config
st.set_page_config(page_title="Canvas Downloader", page_icon="assets/icon.png", layout="wide")

# Custom CSS (extracted to styles/)
inject_css('global.css')

# macOS: ask for notification permission once, early - so the first "Download
# Complete" / "Sync Complete" banner isn't dropped while a fresh install's
# permission is still pending. Idempotent per process; no-op off macOS.
request_macos_notification_permission()

# Cancel button hover CSS (dynamic - requires theme variables)
st.html(f"""
    <style>
    .st-key-cancel_download_btn button:hover,
    .st-key-cancel_pp_download button:hover,
    .st-key-cancel_sync_btn button:hover,
    .st-key-cancel_pp_btn button:hover,
    .st-key-cancel_panopto_btn button:hover,
    .st-key-cancel_panopto_sync_btn button:hover,
    div[class*="st-key-pan_model_cancel_"] button:hover,
    .st-key-pan_cuda_cancel button:hover,
    .st-key-cancel_retry_btn button:hover {{
        border-color: {theme.ERROR} !important;
        background-color: {theme.ERROR_BG} !important;
        color: {theme.ERROR} !important;
        transition: all 0.2s ease-in-out;
    }}
    </style>
""")

# Preset & Dialog CSS (extracted to styles/)
inject_css('preset_dialogs.css')

# Google Material Symbols font - injected once here (M-24: was duplicated in every _mat() call).
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
import base64
import os
try:
    with open(os.path.join(os.path.dirname(__file__), 'assets', 'icon.png'), 'rb') as _f:
        _app_icon_b64 = base64.b64encode(_f.read()).decode()
        _app_logo_html = '<div style="width:64px;height:64px;background:rgba(0,114,206,0.18);border-radius:16px;display:flex;align-items:center;justify-content:center"><img src="data:image/png;base64,' + _app_icon_b64 + '" style="width:36px;height:36px;" /></div>'
except Exception:
    _app_logo_html = '<div style="width:64px;height:64px;background:rgba(77,168,218,.12);border-radius:16px;display:flex;align-items:center;justify-content:center"><svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="#4DA8DA" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg></div>'

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
            +'background:#0d1117;z-index:99999;display:none;flex-direction:column;'
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
        p.el.style.display='flex'; p.vis=true; p.abortScroll=false;
        // Safety valve: force-hide after 8 s so a hung rerun can't trap the overlay.
        // Also kill any pending poll timer - otherwise the stabilization loop keeps
        // running as a zombie AFTER the overlay is hidden and later fires its
        // scroll-to-top, yanking the user back up while they read a settled page.
        if(p.safeT)clearTimeout(p.safeT);
        p.safeT=setTimeout(function(){p.el.style.display='none';p.vis=false;p.safeT=null;if(p.hT){clearTimeout(p.hT);p.hT=null;}},8000);
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
                // Overlay already hidden (safety valve or a prior hide): stop the
                // loop so it can never fire scroll/side-effects after teardown.
                // Also bail if the overlay got detached from the DOM (a Streamlit
                // hot-reload can replace document.body): p.vis would still say
                // "visible" while nothing actually covers the page, so the user is
                // free to click - and this loop would later yank them to the top.
                if(!p.vis||!p.el.isConnected){p.vis=false;p.hT=null;return;}
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
                    // Overlay already hidden (safety valve or a prior hide), or
                    // detached from the DOM: abort so a stale loop can never yank
                    // scroll after the overlay is gone / while it isn't covering.
                    if(!p.vis||!p.el.isConnected){p.vis=false;p.hT=null;return;}
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
                                // Capture the stable fingerprint for the rAF guard.
                                var commitFP=lastFP;
                                requestAnimationFrame(function(){
                                    // The overlay may have been torn down during the
                                    // ~16 ms rAF gap (the 8 s safety valve can fire, or a
                                    // hot-reload can detach it).  pollStable's guard ran
                                    // BEFORE this callback was queued, so re-check here -
                                    // otherwise the scroll below still executes on a page
                                    // the user is already reading and interacting with.
                                    if(!p.vis||!p.el.isConnected){p.vis=false;p.hT=null;return;}
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
                                    // Confirmed stable AND still the active navigation
                                    // overlay.  Scroll to top as the LAST act before
                                    // hiding, so it fires exactly once per navigation -
                                    // never early, never repeatedly, and never while the
                                    // user reads a settled page.  Streamlit uses internal
                                    // scroll containers, not the window - hit all
                                    // candidates.
                                    //
                                    // abortScroll: a click reached a button while the
                                    // overlay was supposedly covering the page, so it was
                                    // NOT actually blocking input.  The user is already
                                    // interacting (e.g. expanding a sync-history card);
                                    // hide silently rather than yanking them to the top.
                                    if(!p.abortScroll){
                                        win.scrollTo(0,0);
                                        var sc=doc.querySelectorAll(
                                            '[data-testid="stMain"],'
                                            +'[data-testid="stAppViewContainer"],'
                                            +'[data-testid="stVerticalBlock"]'
                                        );
                                        for(var i=0;i<sc.length;i++) sc[i].scrollTop=0;
                                    }
                                    p.abortScroll=false;
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
        'div[class*="st-key-nav_btn_today"]',     // sidebar: Today dashboard
        'div[class*="st-key-nav_btn_download"]',  // sidebar: Download Courses
        'div[class*="st-key-nav_btn_sync"]',      // sidebar: Sync Course Folders
        'div[class*="st-key-nav_btn_logout"]',    // sidebar: Logout
        'div[class*="st-key-login_submit_btn"]',  // login submission button
        'div[class*="st-key-btn_analyze_sync"]',  // Analyze, Review & Sync
        'div[class*="st-key-btn_quick_sync"]',    // Quick Sync All
        'div[class*="st-key-btn_custom_download"]',// Course Selector: Custom Download
        'div[class*="st-key-btn_quick_download"]', // Course Selector: Quick Download
        'div[class*="st-key-action_dl_back"]',    // Back in download settings
        'div[class*="st-key-qd_goto_advanced"]'   // Customize configuration in Quick Download
    ].join(',');
    if(!p.clickAdded){
        p.clickAdded=true;
        doc.addEventListener('click',function(e){
            if(!e.target.closest('button'))return;
            var btn = e.target.closest(NAV_SEL);
            // A click reached a button while the overlay claims to be visible, so it
            // is NOT actually blocking input (it was detached, or is mid-teardown).
            // Cancel the pending scroll-to-top: the user is already interacting with
            // a settled page (e.g. expanding a sync-history card) and yanking them
            // to the top is exactly the intermittent bug this guards against.
            if(p.vis&&!btn)p.abortScroll=true;
            if(!btn)return;
            
            // Sidebar nav buttons: skip overlay when already at the target mode's
            // step 1 (clicking would cause a no-op rerun with no page change).
            if(btn.matches('div[class*="st-key-nav_btn_download"]')||btn.matches('div[class*="st-key-nav_btn_sync"]')||btn.matches('div[class*="st-key-nav_btn_today"]')){
                var stEl=doc.getElementById('cdp_nav_state');
                if(stEl){
                    var curMode=stEl.getAttribute('data-mode')||'';
                    var curStep=parseInt(stEl.getAttribute('data-step')||'0',10);
                    var tMode=btn.matches('div[class*="st-key-nav_btn_download"]')?'download':(btn.matches('div[class*="st-key-nav_btn_sync"]')?'sync':'today');
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
    // resets), but once the server dies no further reruns can occur - so the
    // last iframe and its timer survive exactly as long as we need them.
    var hFails=0;
    function hDead(){
        if(doc.getElementById('_cdClosed'))return;
        try{if(p.safeT){clearTimeout(p.safeT);}p.el.style.display='none';p.vis=false;}catch(_){}
        var ov=doc.createElement('div');
        ov.id='_cdClosed';
        ov.style.cssText='position:fixed;top:0;left:0;right:0;bottom:0;background:#0d1117;'
            +'z-index:2147483647;display:flex;flex-direction:column;align-items:center;'
            +'justify-content:center;gap:18px;font-family:-apple-system,BlinkMacSystemFont,'
            +'"Segoe UI",sans-serif;text-align:center;padding:24px';
        ov.innerHTML=
            '""" + _app_logo_html + """'
            +'<div style="color:#ffffff;font-size:1.25rem;font-weight:600">Canvas Downloader has been closed</div>'
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

# --- Settings → Panopto transcription-dialog transition mask ---
# Clicking "Configure transcription" in the Settings modal closes Settings, fires
# a full-app rerun, and re-opens the Panopto config dialog. For ~0.5s the bare
# (undimmed) main page flashes through between the two modals. The big overlay
# above is geared to MAIN-PAGE navigation (it polls stMain geometry to hide) and
# would hang here because the background page doesn't actually change - so this is
# a dedicated, self-contained mask: show on click, hide the instant the Panopto
# dialog's own content has rendered (or after a short safety timeout).
# State lives on window.parent and the click handler is re-bound every injection
# (the components.html iframe is destroyed/recreated each rerun; a listener from a
# dead iframe realm silently stops firing - see CLAUDE.md JS-bridge rules).
components.html("""<script>
(function(){
    var win=window.parent, doc=win.document;
    var M=win._cdPanMask||(win._cdPanMask={handler:null,el:null,timer:null});

    function maskEl(){
        if(M.el && M.el.isConnected) return M.el;
        var e=doc.getElementById('_cdPanMaskOv');
        if(!e){
            var s=doc.getElementById('_cdPanMaskKf');
            if(!s){s=doc.createElement('style');s.id='_cdPanMaskKf';
                s.textContent='@keyframes _cdPanR{to{transform:rotate(360deg)}}';
                doc.head.appendChild(s);}
            e=doc.createElement('div');
            e.id='_cdPanMaskOv';
            e.style.cssText='position:fixed;top:0;left:0;right:0;bottom:0;'
                +'background:#0d1117;z-index:99999;display:none;flex-direction:column;'
                +'align-items:center;justify-content:center;gap:16px';
            e.innerHTML=
                '<div style="width:30px;height:30px;border:2.5px solid rgba(255,255,255,.07);'
                +'border-top-color:#b89dfe;border-radius:50%;'
                +'animation:_cdPanR .75s linear infinite"></div>'
                +'<div style="color:rgba(255,255,255,.38);font:13px/1 system-ui,sans-serif;'
                +'letter-spacing:.04em">Loading…</div>';
            doc.body.appendChild(e);
        }
        M.el=e; return e;
    }

    function show(){
        var e=maskEl();
        e.style.display='flex';
        if(M.timer)win.clearTimeout(M.timer);
        var start=Date.now();
        (function poll(){
            // The Panopto dialog is identifiable by its language card, which only
            // exists once that dialog has rendered its body. Wait a beat after it
            // appears so the dialog's scoped CSS has painted (no flash of unstyled
            // cards), then drop the mask. 2.5s hard cap so a hung rerun can't trap it.
            var ready=doc.querySelector('div[data-testid="stDialog"] div[class*="st-key-pan_lang_card"]');
            if(ready || Date.now()-start>2500){
                M.timer=win.setTimeout(function(){
                    var el=doc.getElementById('_cdPanMaskOv');
                    if(el)el.style.display='none';
                }, ready?90:0);
                return;
            }
            M.timer=win.setTimeout(poll,60);
        })();
    }

    // Re-bind a fresh listener every injection (old realm may be dead).
    try{ if(M.handler) doc.removeEventListener('click',M.handler,true); }catch(_){}
    M.handler=function(e){
        if(!e.target||!e.target.closest)return;
        if(!e.target.closest('button'))return;
        if(e.target.closest('div[class*="st-key-stg_btn_pan"]')) show();
    };
    doc.addEventListener('click',M.handler,true);
})();
</script>""", height=0)

# --- URL Query-Param Navigation Persistence ---

def _restore_nav_from_query_params() -> None:
    """On a fresh session, pre-seed mode/step from URL query params before defaults are applied.

    Steps that require live download/sync state (3, 4 for download; 4 for sync)
    cannot be meaningfully restored and are capped to the nearest safe step.
    """
    if '_session_alive' in st.session_state:
        return  # not a fresh session - don't override in-session navigation
    try:
        raw_mode = st.query_params.get('mode', '')
        raw_step = st.query_params.get('step', '')
        if raw_mode not in ('download', 'sync', 'today'):
            return
        step = int(raw_step) if isinstance(raw_step, str) and raw_step.isdigit() else 1
        if raw_mode == 'download':
            step = min(step, 2)   # steps 3+ need a live download session
        else:
            step = 1              # sync/today step 4 need live state; step 1 is always safe
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

# Adopt the saved settings + login BEFORE anything renders. This must sit here,
# between ensure_download_state() (which installs the defaults it overrides) and
# _write_nav_to_query_params() (which writes ?mode=auth when signed out). It used
# to run inside render_login_page and finish with st.rerun(), so a launch with a
# saved login rendered one entirely blank script run - keyring and two Canvas
# round-trips behind an empty window - and then threw it away and started over.
from ui.auth import restore_saved_session
restore_saved_session()

_write_nav_to_query_params()

# Breadcrumb for the local health record: if this session dies without running
# our exit path (crash / OOM kill / Task Manager), the next launch reports the
# phase it was in - see core/health_log.py. Hooked HERE, on the one line every
# rerun passes through, deliberately: `download_status` is already the app's
# phase variable, but it is assigned from ~20 sites across app.py, sync/ and
# core/auto_sync.py, and a breadcrumb bolted onto each of those is guaranteed to
# drift the first time someone adds a twenty-first. note_phase() early-returns
# when the phase is unchanged, so the common rerun costs a dict lookup.
try:
    from core.health_log import note_phase
    note_phase(st.session_state.get('download_status') or 'idle')
except Exception:
    pass

# C-3: Guard against stale cancel events left by a prior run that bypassed
# cleanup_download_state(). Safe to reset whenever no background download
# thread is running - i.e. when not in any of the active download phases.
# Note: the earlier value `'downloading'` was a typo that never matched the real
# download_status values and caused this branch to fire on every rerun, defeating
# the guard. `'panopto'` had the OPPOSITE bug: it was MISSING here, so during the
# terminal Panopto phase (an active phase with live download/transcription
# workers) this reset fired on every rerun and NUKED the cancel event the instant
# on_click set it - so Cancel was silently ignored and the phase restarted its
# discovery (re-scan) instead of stopping. Must mirror cancellation.py's
# _IN_PROGRESS_DOWNLOAD_STATUSES exactly.
_active_dl_statuses = {'scanning', 'running', 'isolated_retry', 'panopto'}
if st.session_state.get('download_status', '') not in _active_dl_statuses:
    reset_download_cancel()

# L-4: Clear a stale debug log exactly once per Streamlit session when debug
# mode is already enabled (e.g. persisted from a previous session via keyring).
# Prevents the user from seeing log entries from an unrelated prior run.
if '_debug_log_cleared' not in st.session_state:
    st.session_state['_debug_log_cleared'] = True
    if st.session_state.get('debug_mode', False):
        from core.canvas_debug import clear_debug_log as _clear_debug_log
        from pathlib import Path as _Path
        _dbg = _Path(st.session_state.get('download_path', str(_Path.home() / 'Downloads'))) / 'debug_log.txt'
        _clear_debug_log(str(_dbg))

# --- Helper Functions ---

def select_folder():
    from shared.helpers import native_folder_picker
    folder_path = native_folder_picker(initial_dir=st.session_state.get('download_path') or None)
    if folder_path:
        st.session_state['download_path'] = folder_path

def select_sync_folder():
    """Open folder picker for sync mode and store in pending_sync_folder."""
    from shared.helpers import native_folder_picker
    folder_path = native_folder_picker(initial_dir=st.session_state.get('pending_sync_folder') or None)
    if folder_path:
        st.session_state['pending_sync_folder'] = folder_path

def check_cancellation():
    """Backward-compatible alias for is_download_cancelled (used by canvas_logic.py)."""
    return is_download_cancelled()

def cancel_download_callback():
    """Backward-compatible alias for cancel_download (used in on_click= handlers)."""
    cancel_download()


def _panopto_run_contract() -> dict:
    """Per-run Panopto contract (output formats + layout) from the confirmed
    download settings.

    Mirrors the Canvas Content flow: Section 4's toggles are saved to
    ``persistent_pan_*`` session keys on Confirm; this reads them back into the
    {output_mp4/mp3/txt/srt, layout} contract shape that the runtime consumes.
    The engine config (model/device/language) is layered in by
    ``panopto.settings.compose_settings``.
    """
    from panopto.settings import make_contract
    return make_contract(
        mp4=st.session_state.get('persistent_pan_out_mp4', False),
        mp3=st.session_state.get('persistent_pan_out_mp3', False),
        txt=st.session_state.get('persistent_pan_out_txt', False),
        srt=st.session_state.get('persistent_pan_out_srt', False),
        layout=st.session_state.get('persistent_pan_layout', 'match'),
    )


def _next_phase_after_courses() -> str:
    """Decide the status after all courses' files + post-processing finish.

    Runs the terminal Panopto phase when the user selected at least one Panopto
    output format in Section 4 of the download settings; otherwise goes straight
    to the completion screen.
    """
    try:
        from panopto.settings import is_enabled
        if is_enabled(_panopto_run_contract()):
            return 'panopto'
    except Exception:
        pass
    return 'done'



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

# --- Daily Auto-Sync Launch Hook (Today dashboard) ---
# Runs at most once per Streamlit session: the first time the app is opened on a
# new logical day (day rolls at 4am), if the user enabled daily auto-sync and
# curated at least one course, kick off a headless Quick Sync over that set. The
# run surfaces on the Today page as a slim progress bar (see core.auto_sync).
if not st.session_state.get('_auto_sync_checked'):
    st.session_state['_auto_sync_checked'] = True
    # Only on a clean entry point - never interrupt an in-progress download/sync
    # that a query-param restore may have landed us in.
    if not st.session_state.get('download_status'):
        try:
            from core.auto_sync import should_auto_sync, start_today_sync
            if should_auto_sync():
                start_today_sync(is_auto=True)  # sets state + st.rerun(); never falls through
        except Exception:
            logger.warning("Daily auto-sync launch check failed", exc_info=True)

# (The Panopto transcription-config dialog and the global Settings dialog are
#  hosted at the BOTTOM of this file - see "Deferred dialog hosts". They must be
#  emitted after the main page or they shift its element indices and the page
#  behind them renders mis-styled for a few frames.)

# --- Wizard Steps ---
# Wrap in st.empty().container() to prevent stale elements from previous steps
# persisting during long-running operations (e.g., sync downloads via asyncio.run).
_main_content = st.empty()
with _main_content.container():

    # (No preset-dialog import here: ui/download_settings.py opens them at its
    #  own call sites, so importing them into this scope bound two names that
    #  nothing in app.py ever referenced.)

    # NOTE: Panopto is no longer a standalone page. Its output formats + layout are
    # configured per-download in Section 4 of the download settings, and its engine
    # setup lives in the transcription-config dialog (ui.panopto_page) opened from
    # there. The old `current_mode == 'panopto'` route has been removed.

    # STEP 1: Different UI based on mode
    if st.session_state['step'] == 1:

        # ========== TODAY DASHBOARD - STEP 1 ==========
        if st.session_state['current_mode'] == 'today':
            from ui.today_dashboard import render_today_dashboard
            render_today_dashboard(fetch_courses)

        # ========== SYNC MODE - STEP 1 ==========
        elif st.session_state['current_mode'] == 'sync':
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
        current_status = st.session_state.get('download_status', 'scanning')

        # The scan is its own step now. It always WAS its own phase - it renders
        # the analysis dashboard, and its Cancel button says "Cancel Analysis" -
        # but the tracker (and the heading) called it "Downloading", so the first
        # ~30s of every run described work that had not started.
        render_download_wizard(st, 'complete' if current_status == 'done'
                                   else 'analyze' if current_status == 'scanning'
                                   else 'download')

        if current_status == 'done':
            st.markdown('<h2 class="step-header">Download Complete!</h2>', unsafe_allow_html=True)
        elif current_status == 'cancelled':
            pass
        elif current_status == 'panopto':
            st.markdown('<h2 class="step-header">Panopto Recordings</h2>', unsafe_allow_html=True)
        elif current_status == 'scanning':
            st.markdown('<h2 class="step-header">Analyzing...</h2>', unsafe_allow_html=True)
        else:
            st.markdown('<h2 class="step-header">Downloading...</h2>', unsafe_allow_html=True)
        
        # Safety check: ensure download state exists
        if 'courses_to_download' not in st.session_state or 'current_course_index' not in st.session_state:
            _is_sync = st.session_state.get('current_mode') == 'sync'
            _err_msg = 'Sync state not initialized.' if _is_sync else 'Download state not initialized.'
            from ui.amber_notice import render_error_notice
            render_error_notice(f'{_err_msg} Please go back and try again.')
            _btn_label = 'Go back'
            if st.button(_btn_label, key="page_nav_back_to_settings"):
                st.session_state['step'] = 1 if _is_sync else 2
                st.rerun()
            st.stop()
        
        total = len(st.session_state['courses_to_download'])
        current_idx = st.session_state['current_course_index']
        
        # UI elements in correct order.
        #
        # Scanning and running share ONE dashboard card, built here, because the
        # two phases must produce an IDENTICAL element tree. When the scan built
        # its own `st.container(key="progress_dashboard")` further down the page,
        # the switch to the download phase shifted every element after it by one
        # slot, and Streamlit - which reconciles by position - handed the card's
        # DOM node (class and all) to whatever element inherited that slot. The
        # inheritor was the empty post-processing cancel placeholder, so the
        # download screen grew a stray 38px empty card below the Cancel button
        # that no code was rendering into. Same family of bug as the dialog
        # ordering one in CLAUDE.md: the fix is to stop the indices moving, not
        # to hunt the ghost node.
        if st.session_state.get('download_status') in ('running', 'scanning'):
            # First-run macOS permission batch is in flight: tell the user the
            # upcoming system dialogs are expected and one-time. Rendered for the
            # whole first run; the flag is re-armed False at every run start.
            if st.session_state.get('_tcc_batch_active'):
                from ui.amber_notice import render_info_notice
                render_info_notice(
                    "<b>First-time macOS setup:</b> macOS will show a few one-time permission "
                    "dialogs (control of Microsoft PowerPoint / Word / Excel, System Events, "
                    "and folder access). Click <b>Allow / OK</b> on each - Canvas Downloader uses them "
                    "only to convert Office files to PDF on your own Mac.",
                    icon="🔐",
                    allow_html=True,
                )
            if 'start_time' not in st.session_state:
                st.session_state['start_time'] = time.time()
            if 'log_deque' not in st.session_state:
                st.session_state['log_deque'] = collections.deque(maxlen=200)
                
            # One card around the whole readout - see the "Run dashboard card"
            # block in global.css.
            with st.container(key="progress_dashboard"):
                header_placeholder = st.empty()
                progress_placeholder = st.empty()
                metrics_placeholder = st.empty()
                active_file_placeholder = st.empty()
                log_placeholder = st.empty()

            st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)

            cancel_placeholder = st.empty()
            cancel_placeholder.button(
                # Same button, same key, same callback - only the wording
                # changes with the phase. Rendering it from one place is what
                # keeps the element indices stable across the transition.
                'Cancel Analysis'
                if st.session_state.get('download_status') == 'scanning'
                else 'Cancel Download',
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
            # Course analysis (phase 1) - renders through the SAME dashboard
            # chrome as the download itself (see render_analysis_dashboard).
            total_courses = len(st.session_state['courses_to_download'])

            # The dashboard card, its placeholders and the (already-rendered)
            # "Cancel Analysis" button all come from the shared block above -
            # deliberately, so the tree does not change shape when this phase
            # hands over to the download.
            _scan_dp = DashboardPlaceholders(
                header=header_placeholder, progress=progress_placeholder,
                metrics=metrics_placeholder, active_file=active_file_placeholder,
            )

            # Courses are the unit of work here; ~5 s each is a fair opening
            # guess for a Canvas course with modules, and it is replaced by the
            # measured rate as soon as the first course finishes scanning.
            _scan_eta = stepwise_estimator(5.0)
            _scan_files = 0
            _scan_mb = 0.0

            cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
            total_items = 0
            total_mb = 0
            
            for idx, course in enumerate(st.session_state['courses_to_download']):
                # Check if the user clicked the global cancel button before processing the next course
                if st.session_state.get('cancel_requested', False):
                    break # Escape the loop immediately!
                    
                current_course_num = idx + 1

                def _paint_scan(status_text, current_mod=0, total_mods=0,
                                _num=current_course_num, _course=course):
                    """One renderer for the whole scan - the seed paint and every
                    sub-step tick go through it, so they cannot drift apart."""
                    _scan_eta.update(units_done=idx, units_total=total_courses)
                    render_analysis_dashboard(
                        _scan_dp,
                        course_label=(f"Analyzing Course {_num}/{total_courses}"
                                      if total_courses > 1 else "Analyzing Course"),
                        course_name=_course.name,
                        status_text=status_text,
                        # Courses are the unit the row counts, so they are the
                        # unit the bar measures too - the module sub-step only
                        # supplies the fraction of the course in hand.
                        percent=analysis_percent(idx, total_courses,
                                                 current_mod, total_mods),
                        # Most sub-steps report total=1, where a bar pinned near
                        # 0% reads as a hang rather than as work in progress.
                        indeterminate=total_mods <= 1,
                        metrics=[
                            metric_count('Courses', idx, total_courses),
                            metric_count('Items Found', _scan_files),
                            metric_transferred(_scan_mb * 1024 * 1024, label='Size'),
                            metric_eta(_scan_eta.eta_text()),
                        ],
                    )

                # Progress hook for granular module scanning
                def analysis_progress_hook(current_mod, total_mods, mod_status_text):
                    # Cancel button is already rendered above with on_click callback
                    # No need to re-render inside the hook - the callback fires instantly
                    _paint_scan(mod_status_text, current_mod, total_mods)

                _paint_scan(f"Connecting to {course.name}…")

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
                        is_scanning_phase=True,
                        download_mode=st.session_state.get('download_mode'),
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

                # Credit the finished course so the next one's ETA is measured,
                # and let the running totals reach the metrics row.
                _scan_files, _scan_mb = total_items, total_mb
                _scan_eta.update(units_done=current_course_num, units_total=total_courses)

            # Clear the analysis readout before the download phase fills the
            # SAME placeholders on the next run.
            header_placeholder.empty(); progress_placeholder.empty()
            metrics_placeholder.empty(); active_file_placeholder.empty()

            st.session_state['total_items'] = total_items
            st.session_state['total_mb'] = total_mb
            st.session_state['download_status'] = 'running'

            # Re-arm the completion notification for THIS run. The sentinel is a
            # single flag shared with sync and is otherwise only reset by the
            # cleanup handlers - so a prior download/sync that left it True (e.g.
            # the user navigated away without going through cleanup) would
            # silently swallow this run's "Download Complete" notification.
            st.session_state['completion_beep_fired'] = False
            # Re-arm the "quit Office apps on completion" one-shot for this run.
            st.session_state['_office_quit_fired'] = False
            # macOS: forget any Office apps primed by a previous run (they were quit
            # at that run's completion) so this run launches them fresh + scoped.
            st.session_state['_tcc_batch_active'] = False
            if sys.platform == 'darwin':
                try:
                    from engine.applescript_bridge import (
                        reset_office_priming, first_run_permission_setup,
                        arm_app_data_access,
                    )
                    reset_office_priming()
                    # One-time per machine: fire ALL outstanding Office permission
                    # prompts NOW, while the user is at the screen (they just
                    # clicked Start) - instead of letting each app's prompt ambush
                    # a later run mid-conversion. Uses the UNscoped toggles on
                    # purpose; the per-course prime stays file-scoped.
                    _conv_contract = {
                        'convert_pptx': st.session_state.get('persistent_convert_pptx', False),
                        'convert_word': st.session_state.get('persistent_convert_word', False),
                        'convert_excel': st.session_state.get('persistent_convert_excel', False),
                    }
                    if first_run_permission_setup(_conv_contract):
                        st.session_state['_tcc_batch_active'] = True
                    # Every session (not one-time): the macOS 15+ App Data consent
                    # is forgotten at quit by OS design, so re-fire its single
                    # prompt at run start rather than mid-conversion.
                    arm_app_data_access(_conv_contract)
                except Exception:
                    pass

            st.session_state['start_time'] = time.time() # Reset timer immediately before running loop
            # Fresh time-remaining model for this run (it spans all courses).
            st.session_state.pop('_download_estimator', None)

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

                # One estimator for the WHOLE run, not per course: the counters
                # it is fed are already run-wide, and a fresh model at every
                # course boundary would throw away everything learned about this
                # connection three times over on a three-course run. It lives in
                # session state because each course is its own Streamlit rerun.
                _dl_eta = st.session_state.get('_download_estimator')
                if _dl_eta is None:
                    _dl_eta = transfer_estimator(**learned_transfer_priors())
                    st.session_state['_download_estimator'] = _dl_eta

                def render_dashboard():
                    current_mb = sum(st.session_state.get('course_mb_downloaded', {}).values())
                    is_retry = st.session_state.get('download_status') == 'isolated_retry'
                    active_total = st.session_state.get('total_items', total_items)
                    active_current = st.session_state.get('retry_downloaded_items', 0) if is_retry else st.session_state.get('downloaded_items', 0)
                    active_current += st.session_state.get('retry_failed_items', 0) if is_retry else st.session_state.get('failed_items', 0)
                    _dl_total_mb = st.session_state.get('total_mb', total_mb)
                    _dl_eta.update(
                        units_done=active_current, bytes_done=current_mb * 1024 * 1024,
                        units_total=active_total, bytes_total=_dl_total_mb * 1024 * 1024,
                    )
                    _dl_header = f"Downloading Course {current_idx + 1}/{total}" if total > 1 else "Downloading"
                    render_full_dashboard(
                        _dp, log_deque,
                        header_label=_dl_header,
                        course_name=course.name,
                        current_files=active_current,
                        total_files=active_total,
                        downloaded_bytes=current_mb * 1024 * 1024,
                        total_bytes=_dl_total_mb * 1024 * 1024,
                        estimator=_dl_eta,
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
                            # A file already on disk transfers no bytes, so its
                            # size must leave the denominator - the engine has
                            # always sent `file_size` here for exactly that (see
                            # the "Remove skipped files from Total MB count"
                            # comment at the emit site) but nothing consumed it.
                            # The cost was severe on any re-run: every byte of an
                            # 849 MB course stayed "still to download", so the
                            # counter sat at 0.0 / 849.4 MB from start to finish
                            # and the ETA kept pricing in bytes that were never
                            # going to move. The item itself stays counted - it
                            # IS done - so only the MB total shrinks.
                            _skip_sz = kwargs.get('file_size', 0) or 0
                            if _skip_sz > 0:
                                st.session_state['total_mb'] = max(
                                    0.0,
                                    st.session_state.get('total_mb', total_mb) - (_skip_sz / (1024 * 1024)),
                                )
                            if msg:
                                _name = _clean_display_name(str(msg))
                                log_deque.append(log_line('skip', _name, icon=file_icon_svg(_name)))
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
                                _name = _clean_display_name(str(msg))
                                log_deque.append(log_line('skip', _name, icon=file_icon_svg(_name), detail='Skipped - Exceeds filesize limit'))
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
                                _name = _clean_display_name(str(msg))
                                render_active_file(active_file_placeholder, str(msg))
                                if progress_type == 'secondary':
                                    entity_type = kwargs.get('entity_type', '')
                                    log_deque.append(log_line('success', _name, icon=entity_icon_svg(entity_type)))
                                else:
                                    log_deque.append(log_line('success', _name, icon=file_icon_svg(_name)))

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
                                _name = _clean_display_name(str(msg))
                                log_deque.append(log_line('success', _name, icon=file_icon_svg(_name)))

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
                            log_deque.append(log_divider(phase_name))
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
                                    
                                    _msg_text = error_obj.message if hasattr(error_obj, 'message') else str(msg)
                                    log_deque.append(log_line('error', f"[{course.name}] {_msg_text}"))

                            render_dashboard()

                        elif progress_type == 'mb_progress':
                            mb_down_course = kwargs.get('mb_downloaded', 0)
                            if 'course_mb_downloaded' not in st.session_state:
                                 st.session_state['course_mb_downloaded'] = {}
                            st.session_state['course_mb_downloaded'][course.id] = mb_down_course
                            render_dashboard()
                        
                        elif msg and progress_type == 'log':
                            log_deque.append(log_meta(f"[{course.name}] {msg}"))
                            render_dashboard()
                    except (KeyboardInterrupt, SystemExit):
                        raise
                    except Exception as _e:
                        # Swallow rendering noise (e.g. RuntimeError from asyncio
                        # teardown) so a UI hiccup never kills a download.
                        # NOTE: Streamlit's RerunException/StopException inherit
                        # from BaseException and deliberately pass THROUGH this
                        # handler - that propagation is what makes the Cancel
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
                    from core.canvas_debug import log_debug as _app_log
                    from core.canvas_debug import set_active_debug_file as _set_dbg, log_session_header as _dbg_header
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
                    log_deque.append(log_line('error', f"Download engine crashed for {course.name}: {_dl_crash}"))
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
                    # actually use - scoped to the file types present in the folder,
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
                    # H-9: scope conversions to THIS RUN's files (the ledger of
                    # everything downloaded / skipped-as-existing this course).
                    # Without this, run_all_conversions globbed the ENTIRE
                    # course folder - so a re-download into an existing folder
                    # converted (and deleted the originals of) files from
                    # previous runs, kept Panopto MP4s, and any media/Office
                    # files the user had placed there themselves.
                    _run_files = []
                    for _lf in st.session_state.get('download_file_details', {}).get(course.name, []):
                        try:
                            _lp = Path(_lf)
                            if not _lp.is_absolute():
                                _lp = course_folder / _lp
                            if _lp.exists():
                                _run_files.append(str(_lp))
                        except (OSError, ValueError):
                            continue
                    # Empty ledger (nothing downloaded or skipped this course)
                    # → nothing to convert. Skipping outright matters: the
                    # bridge treats a falsy explicit_files as "no scoping" and
                    # would glob the whole folder again.
                    if _run_files:
                        invoke_post_processing(
                            course_folder=course_folder,
                            course_id=course.id,
                            course_name=course.name,
                            placeholders=_dp,
                            log_deque=log_deque,
                            error_log_path=Path(st.session_state['download_path']) if st.session_state.get('error_log_enabled', False) else None,
                            mode='download',
                            explicit_files=_run_files,
                        )
                    if debug_file:
                        from core.canvas_debug import log_debug as _pp_fin_log
                        _pp_active_done = [k.replace('convert_', '') for k, v in _pp_settings.items() if v and k.startswith('convert_')]
                        _dl_count_done = len(st.session_state.get('download_file_details', {}).get(course.name, []))
                        # THIS course's errors, not the batch's. `download_errors_list`
                        # is created once before the course loop and never reset -
                        # it is called `global_errors` where the completion screen
                        # reads it - so `len()` reported every earlier course's
                        # errors again here. Measured on a three-course run: the
                        # third course contributed zero errors and its line said
                        # "Errors: 5". The download count on the same line is
                        # per-course, so the two halves disagreed about what they
                        # were counting.
                        _err_count_done = sum(
                            1 for _e in st.session_state.get('download_errors_list', [])
                            if getattr(_e, 'course_name', None) == course.name)
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
                    st.session_state['download_status'] = _next_phase_after_courses()
                    # Pass this connection's measured rates to whatever runs
                    # next (the Panopto phase, or the next run in this session).
                    remember_transfer_priors(_dl_eta)

                # Auto-rerun instantly to process next course or done screen
                st.rerun()
            else:
                # All done
                st.session_state['download_status'] = _next_phase_after_courses()
                
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
                
            # One card around the whole readout - see the "Run dashboard card"
            # block in global.css.
            with st.container(key="progress_dashboard"):
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

            _retry_eta = st.session_state.get('_retry_estimator')
            if _retry_eta is None:
                _retry_eta = transfer_estimator(**learned_transfer_priors())
                st.session_state['_retry_estimator'] = _retry_eta

            def render_dashboard(current_course_name):
                bytes_down = st.session_state.get('retry_mb_tracker', {}).get('bytes_downloaded', 0)
                active_total = st.session_state.get('total_items', 1)
                active_current = st.session_state.get('retry_downloaded_items', 0) + st.session_state.get('retry_failed_items', 0)
                _retry_total_mb = st.session_state.get('total_mb', total_mb)
                _retry_eta.update(units_done=active_current, bytes_done=bytes_down,
                                  units_total=active_total,
                                  bytes_total=_retry_total_mb * 1024 * 1024)
                render_full_dashboard(
                    _dp, log_deque,
                    header_label="Retrying Failed Items",
                    course_name=current_course_name,
                    current_files=active_current,
                    total_files=active_total,
                    downloaded_bytes=bytes_down,
                    # The retry queue's sizes come from cached error contexts and
                    # are often absent, so a "/ X MB" denominator here would be a
                    # number the run cannot honour. The count is the honest one.
                    total_bytes=None,
                    estimator=_retry_eta,
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
                            _name = _clean_display_name(str(msg))
                            log_deque.append(log_line('skip', _name, icon=file_icon_svg(_name)))
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
                            _name = _clean_display_name(str(msg))
                            log_deque.append(log_line('skip', _name, icon=file_icon_svg(_name), detail='Skipped - Exceeds filesize limit'))
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
                            _name = _clean_display_name(str(msg))
                            log_deque.append(log_line('success', _name, icon=file_icon_svg(_name)))

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
                                
                                _msg_text = error_obj.message if hasattr(error_obj, 'message') else str(msg)
                                log_deque.append(log_line('error', f"[{course_name_ref}] {_msg_text}"))
                        render_dashboard(course_name_ref)

                    elif msg and progress_type == 'log':
                        log_deque.append(log_meta(f"[{course_name_ref}] {msg}"))
                        render_dashboard(course_name_ref)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as _e:
                    # Match the main update_ui handler: swallow rendering noise.
                    # RerunException/StopException are BaseException and pass
                    # through - that is what makes Cancel work mid-retry.
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
                        "Retry cancelled - post-processing skipped.",
                        detail="Any files that downloaded successfully before cancellation are available in your folder.",
                        margin="12px 0 2px 0",
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
                            # PP done - clear the flag so subsequent cancel
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

            # Any retriable error that survived the retry is now permanent: flag it
            # so the completion screen re-categorizes it from "Failed to Download"
            # into "Cannot Be Downloaded" (a re-retry would just fail again). LTI
            # streams and app-level errors were never in the retry queue, so skip them.
            # Skip when the retry was cancelled - some queued items never actually
            # ran, so they are not genuinely exhausted.
            _retry_was_cancelled = (
                st.session_state.get('cancel_requested') or st.session_state.get('download_cancelled')
            )
            if not _retry_was_cancelled:
                for err in global_errors:
                    if getattr(err, 'is_app_error', False) or isinstance(err, dict):
                        continue
                    ctx = getattr(err, 'context', None)
                    err_filepath = ctx.get('filepath') if isinstance(ctx, dict) else None
                    err_type = getattr(err, 'error_type', '')
                    if err_filepath and err_type != 'LTI/Media Stream':
                        err.retry_exhausted = True

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

        elif st.session_state.get('download_status') == 'panopto':
            # ── Terminal Panopto phase (grouped by activity) ──
            # Runs after every course's files + post-processing have finished.
            # Three distinct phases across ALL selected courses: discover every
            # lecture, then download every audio file, then transcribe each one.
            # Each phase owns its own dashboard look (colour + metrics), mirroring
            # the Download -> Post-Processing flow.
            from panopto.settings import compose_settings, extract_contract
            from panopto.runner import run_panopto_batch

            # Cancel re-entry guard: a cancel click raises RerunException at a
            # render call mid-run; on the rerun the event is set, so route to the
            # cancelled screen instead of restarting the phase.
            if is_download_cancelled():
                st.session_state['download_status'] = 'cancelled'
                st.rerun()

            # Build the run settings from the confirmed Section 4 contract (output
            # formats + layout) layered over the persisted engine config. One
            # global contract drives every selected course in download mode.
            _pan_contract = _panopto_run_contract()
            pan_settings = compose_settings(_pan_contract)

            # One card around the whole readout - see the "Run dashboard card"
            # block in global.css.
            with st.container(key="progress_dashboard"):
                header_placeholder = st.empty()
                progress_placeholder = st.empty()
                metrics_placeholder = st.empty()
                active_file_placeholder = st.empty()
                log_placeholder = st.empty()
            st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
            cancel_placeholder = st.empty()
            cancel_placeholder.button(
                'Cancel', type="secondary", key="cancel_panopto_btn",
                on_click=cancel_download_callback,
            )

            log_deque = st.session_state.get('log_deque') or collections.deque(maxlen=200)
            st.session_state['log_deque'] = log_deque
            if 'panopto_run_started' not in st.session_state:
                st.session_state['panopto_run_started'] = time.time()
            pan_start = st.session_state['panopto_run_started']

            st.session_state.setdefault('panopto_mb_tracker', {'bytes': 0})
            st.session_state.setdefault('download_file_details', {})
            st.session_state.setdefault('course_mb_downloaded', {})
            _pan_warned = st.session_state.setdefault('_panopto_warned', set())

            _pan_dp = DashboardPlaceholders(
                header=header_placeholder, progress=progress_placeholder,
                metrics=metrics_placeholder, active_file=active_file_placeholder,
                log=log_placeholder,
            )
            # Live phase state (kept off session_state - this branch runs to
            # completion in one pass, so a plain dict closure is enough).
            _pan = {
                'phase': 'search', 'course': '', 'detail': '',
                'courses_total': len(st.session_state.get('courses_to_download', [])),
                'courses_scanned': 0, 'found': 0,
                'dl_total': 0, 'dl_done': 0,
                'tx_total': 0, 'tx_done': 0, 'tx_pct': 0, 'tx_pct_shown': -10,
            }
            # Pre-fill the header's course line (the h3 under the phase label -
            # same slot the file-download dashboard fills with the course name).
            # Without it the download/transcribe phases rendered an EMPTY h3:
            # a phantom gap between the phase label and the progress bar.
            # Single-course runs seed it here; multi-course runs update it from
            # the per-recording events as work flows.
            _pan_course_list = st.session_state.get('courses_to_download', [])
            if len(_pan_course_list) == 1:
                _pan['course'] = getattr(_pan_course_list[0], 'name', '') or ''

            _pan_eta = panopto_estimators(learned_transfer_priors())

            def _render_pan():
                ph = _pan['phase']
                _pan_bytes = st.session_state['panopto_mb_tracker']['bytes']
                if ph == 'download':
                    # No esc(): render_progress_header html-escapes the course
                    # name itself (pre-escaping showed "&amp;" in & names).
                    render_progress_header(_pan_dp, "Downloading Lectures", _pan['course'])
                    pct = int(_pan['dl_done'] / _pan['dl_total'] * 100) if _pan['dl_total'] else 0
                    render_progress_bar(_pan_dp, min(100, pct), color=PHASE_BAR_COLOR['panopto'])
                    # Panopto media has no known byte size until each stream is
                    # resolved, so the byte total is left unknown and the
                    # recording count carries the estimate. Speed is still real.
                    _pan_eta['download'].update(units_done=_pan['dl_done'],
                                                bytes_done=_pan_bytes,
                                                units_total=_pan['dl_total'])
                    render_metrics(_pan_dp, [
                        metric_transferred(_pan_bytes, None, accent=PHASE_BAR_COLOR['panopto']),
                        metric_speed(_pan_eta['download'].bytes_per_sec),
                        metric_count('Recordings', _pan['dl_done'], _pan['dl_total'],
                                     accent=PHASE_BAR_COLOR['panopto']),
                        metric_eta(_pan_eta['download'].eta_text()),
                    ])
                elif ph == 'transcribe':
                    render_progress_header(_pan_dp, "Transcribing Recordings", _pan['course'])
                    # The in-flight file's own percentage is real progress, so it
                    # counts as a fraction of a unit - without it the estimate
                    # would sit frozen for the whole of a 40-minute lecture.
                    _base = _pan['tx_done'] + (_pan['tx_pct'] / 100.0)
                    pct = int(_base / _pan['tx_total'] * 100) if _pan['tx_total'] else 0
                    render_progress_bar(_pan_dp, min(100, pct), color=PHASE_BAR_COLOR['transcribe'])
                    _pan_eta['transcribe'].update(units_done=_base, units_total=_pan['tx_total'])
                    render_metrics(_pan_dp, [
                        metric_count('Transcribed', _pan['tx_done'], _pan['tx_total'],
                                     accent=PHASE_BAR_COLOR['transcribe']),
                        metric_value('Current File', f"{_pan['tx_pct']}%",
                                     PHASE_BAR_COLOR['transcribe']),
                        metric_eta(_pan_eta['transcribe'].eta_text()),
                    ])
                else:  # search
                    render_progress_header(_pan_dp, "Searching for Panopto Recordings", _pan['course'])
                    render_progress_bar(_pan_dp, 0, color=PHASE_BAR_COLOR['search'],
                                        indeterminate=True, label="Searching…")
                    # Discovery genuinely cannot be estimated - the walk finds
                    # out how many folders there are by walking them - so this
                    # phase reports elapsed time and does not pretend otherwise.
                    render_metrics(_pan_dp, [
                        metric_count('Courses Scanned', _pan['courses_scanned'], _pan['courses_total']),
                        metric_count('Recordings Found', _pan['found'], color=theme.SUCCESS_STAT),
                        metric_elapsed(time.time() - pan_start),
                    ])
                render_terminal_log(_pan_dp, log_deque)

            def _pan_ledger_add(course_name, path):
                if not course_name or not path:
                    return
                d = st.session_state['download_file_details']
                d.setdefault(course_name, [])
                if path not in d[course_name]:
                    d[course_name].append(path)
                st.session_state['download_file_details'] = d

            def pan_progress(kind, **kw):
                try:
                    # Keep the header's course line current on every event that
                    # knows its course (multi-course runs flow through here).
                    if kw.get('course'):
                        _pan['course'] = kw['course']
                    # ── Discovery phase ──
                    if kind == 'discovering':
                        _pan['phase'] = 'search'
                        _pan['course'] = kw.get('course', '')
                        log_deque.append(log_divider(f"Scanning · {kw.get('course', '')}"))
                        render_active_file(active_file_placeholder,
                                           f"Scanning {kw.get('course', '')} for lecture recordings…",
                                           phase='search')
                        _render_pan()
                    elif kind == 'scan_stage':
                        render_active_file(active_file_placeholder,
                                           f"Scanning {esc(_pan['course'])} - {kw.get('name', '')}",
                                           phase='search', label='Searching')
                        _render_pan()
                    elif kind == 'scan_item':
                        render_active_file(active_file_placeholder, kw.get('detail', ''),
                                           phase='search', label='Searching')
                        _render_pan()
                    elif kind == 'scan_found':
                        _pan['found'] += 1
                        log_deque.append(log_line('success', kw.get('title', ''),
                                                  icon=file_icon_svg('x.mp4'), detail='recording found'))
                        render_active_file(active_file_placeholder,
                                           f"Found: {kw.get('title', '')}", phase='search')
                        _render_pan()
                    elif kind == 'found':
                        _pan['courses_scanned'] += 1
                        cnt = kw.get('count', 0)
                        if not cnt:
                            log_deque.append(log_meta(f"No Panopto recordings in {kw.get('course', '')}"))
                        _render_pan()
                    elif kind == 'discovery_done':
                        _n = kw.get('found', 0)
                        log_deque.append(log_divider(
                            f"{_n} recording{'s' if _n != 1 else ''} found"))
                        _render_pan()
                    elif kind == 'skipped':
                        cn = kw.get('course', '')
                        for p in kw.get('paths', []):
                            _pan_ledger_add(cn, p)
                        log_deque.append(log_line('skip', kw.get('title', ''),
                                                  icon=file_icon_svg('x.mp3'),
                                                  detail='already saved'))
                        _render_pan()

                    # ── Download phase ──
                    elif kind == 'download_phase':
                        _pan['phase'] = 'download'
                        _pan['dl_total'] = kw.get('total', 0)
                        log_deque.append(log_divider(
                            f"Downloading {_pan['dl_total']} recording{'s' if _pan['dl_total'] != 1 else ''}"))
                        _render_pan()
                    elif kind == 'video_start':
                        render_active_file(active_file_placeholder, kw.get('title', ''),
                                           phase='panopto')
                    elif kind == 'downloaded':
                        size = kw.get('size', 0) or 0
                        st.session_state['panopto_mb_tracker']['bytes'] += size
                        if not kw.get('intermediate'):
                            _pan['dl_done'] += 1
                            cmb = st.session_state['course_mb_downloaded']
                            cmb['panopto'] = cmb.get('panopto', 0) + size / (1024 * 1024)
                            st.session_state['course_mb_downloaded'] = cmb
                            log_deque.append(log_line('success', kw.get('title', ''),
                                                      icon=file_icon_svg(kw.get('path') or 'x.mp3'),
                                                      detail=f"{size / (1024 * 1024):.1f} MB"))
                        else:
                            # Throwaway transcription intermediate - still advance
                            # the bar, but mark it as audio so the log is honest.
                            _pan['dl_done'] += 1
                            log_deque.append(log_line('success', kw.get('title', ''),
                                                      icon=file_icon_svg('x.mp3'),
                                                      detail='audio'))
                        _render_pan()
                    elif kind == 'size_skipped':
                        # A recording exceeded the skip-large-files limit and was
                        # skipped + ignored mid-download. Drop it from the phase
                        # denominator (it never ran) and surface it on the
                        # completion screen alongside any size-skipped Canvas files.
                        _pan['dl_total'] = max(0, _pan['dl_total'] - 1)
                        _sz_mb = (kw.get('size', 0) or 0) / (1024 * 1024)
                        if 'size_skipped_files' not in st.session_state:
                            st.session_state['size_skipped_files'] = []
                        st.session_state['size_skipped_files'].append(
                            f"{kw.get('title', '')} (~{_sz_mb:.0f} MB)")
                        log_deque.append(log_line(
                            'skip', kw.get('title', ''),
                            icon=file_icon_svg('x.mp4'),
                            detail=f"Skipped - exceeds filesize limit · ~{_sz_mb:.0f} MB"))
                        _render_pan()
                    elif kind == 'download_tick':
                        # Heartbeat during concurrent downloads - repaint so
                        # elapsed/speed keep ticking between 'downloaded' events.
                        _render_pan()
                    elif kind == 'download_done':
                        _render_pan()

                    # ── Transcription phase ──
                    elif kind == 'transcribe_phase':
                        _pan['phase'] = 'transcribe'
                        _pan['tx_total'] = kw.get('total', 0)
                        log_deque.append(log_divider(
                            f"Transcribing {_pan['tx_total']} recording{'s' if _pan['tx_total'] != 1 else ''}"))
                        _render_pan()
                    elif kind == 'transcribe_start':
                        _pan['tx_pct'] = 0
                        _pan['tx_pct_shown'] = -10
                        render_active_file(active_file_placeholder, kw.get('title', ''),
                                           phase='transcribe')
                        _render_pan()
                    elif kind == 'transcribe':
                        _pan['tx_pct'] = kw.get('pct', 0)
                        # Throttle: only repaint when the integer pct moves enough.
                        if _pan['tx_pct'] - _pan['tx_pct_shown'] >= 2 or _pan['tx_pct'] >= 99:
                            _pan['tx_pct_shown'] = _pan['tx_pct']
                            _render_pan()
                    elif kind == 'transcribed':
                        _pan['tx_done'] += 1
                        _pan['tx_pct'] = 0
                        _made = kw.get('paths', []) or []
                        _det = ", ".join(Path(p).suffix.lstrip('.').upper() for p in _made) or None
                        log_deque.append(log_line('success', kw.get('title', ''),
                                                  icon=file_icon_svg('x.txt'), detail=_det))
                        _render_pan()
                    elif kind == 'transcribe_done':
                        _render_pan()

                    # ── Shared ──
                    elif kind == 'produced':
                        _pan_ledger_add(kw.get('course', ''), kw.get('path', ''))
                    elif kind == 'warn':
                        msg = kw.get('message', '')
                        if msg not in _pan_warned:
                            _pan_warned.add(msg)
                            log_deque.append(log_line('attention', msg))
                            _render_pan()
                    elif kind == 'error':
                        err = kw.get('error')
                        if err is not None:
                            st.session_state.setdefault('download_errors_list', []).append(err)
                            log_deque.append(log_line('error', f"[{getattr(err, 'item_name', '')}] {getattr(err, 'message', err)}"))
                            _render_pan()
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as _pe:
                    # Swallow render noise; RerunException (BaseException) passes
                    # through to drive cancellation, mirroring update_ui.
                    if type(_pe).__name__ != 'RuntimeError':
                        logger.debug(f"pan_progress swallowed: {type(_pe).__name__}: {_pe}")

            cm = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
            _render_pan()

            # Build one target per selected course (lectures saved inside the
            # course folder), each with its own manifest recorder.
            _pan_targets = []
            for course in st.session_state.get('courses_to_download', []):
                _pan_rec = None
                _pan_ign = None
                try:
                    import json as _json
                    from core.sync_manager import SyncManager as _PanSM
                    from panopto.runner import (
                        make_recorder as _make_rec, make_ignorer as _make_ign)
                    _pan_course_folder = Path(st.session_state['download_path']) / cm._sanitize_filename(course.name)
                    _pan_sm = _PanSM(_pan_course_folder, course.id, course.name)
                    # Persist this run's contract (output formats + layout) into the
                    # folder manifest so a later SYNC of the same folder inherits the
                    # exact Panopto config - mirrors 'secondary_content_contract'.
                    try:
                        _pan_sm._save_metadata(
                            'panopto_contract', _json.dumps(extract_contract(pan_settings)))
                    except Exception as _seed_err:
                        # Not fatal - sync/analysis.py can recover the contract from
                        # the folder's panopto_manifest - but it must not be silent:
                        # this write is the ONLY thing that carries the Panopto setup
                        # from a download into future syncs of the same folder.
                        logger.warning(
                            "Could not seed panopto_contract for '%s': %s. A later "
                            "sync will infer it from the folder's artifacts.",
                            _pan_course_folder, _seed_err,
                        )
                    _pan_rec = _make_rec(_pan_sm, _pan_course_folder)
                    _pan_ign = _make_ign(_pan_sm)
                except Exception:
                    _pan_rec = None
                    _pan_ign = None
                _pan_targets.append({
                    'course': course,
                    'course_root': Path(st.session_state['download_path']) / cm._sanitize_filename(course.name),
                    'download_mode': st.session_state.get('download_mode', 'modules'),
                    'record_fn': _pan_rec,
                    'ignore_fn': _pan_ign,
                })

            # Skip-large-files Setting: gate Panopto recordings by the same limit
            # as Canvas files (recordings - usually the kept mp4 - over the limit
            # are skipped + ignored). 0/None when disabled.
            if st.session_state.get('max_file_size_enabled', False):
                _pan_size_mb = int(st.session_state.get('max_file_size_mb', 0) or 0)
                _pan_max_bytes = _pan_size_mb * 1024 * 1024 if _pan_size_mb > 0 else None
            else:
                _pan_max_bytes = None

            try:
                _pan_summary = run_panopto_batch(
                    cm, _pan_targets,
                    settings=pan_settings,
                    progress=pan_progress,
                    is_cancelled=check_cancellation,
                    max_file_size_bytes=_pan_max_bytes,
                )
                st.session_state['panopto_summary'] = _pan_summary
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as _pan_crash:
                logger.error(f"Panopto phase crashed: {_pan_crash}", exc_info=True)
                _pc_err = DownloadError("Panopto", "Panopto", "Phase Crash",
                                        str(_pan_crash), raw_error=_pan_crash, is_app_error=True)
                st.session_state.setdefault('download_errors_list', []).append(_pc_err)
                log_deque.append(log_line('error', f"Panopto phase failed: {_pan_crash}"))

            active_file_placeholder.empty()
            if is_download_cancelled():
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
            # screen - tidy away the Office apps we launched for conversion
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

            # fresh_container, not st.container: the Panopto phase and the
            # isolated-retry pass both put their progress dashboard at THIS
            # index, and Streamlit hands a new block the old block's children.
            # Without it the run's metrics row + terminal log render inside the
            # completion card until the run ends. See shared.components.
            # (The running/scanning dashboard sits higher up, on one of the four
            # placeholders the else-branch above already emits.)
            with fresh_container(border=True, key='completion_dashboard'):
                # Split errors: what failed vs what Canvas simply declined to
                # serve. ONE rule, shared with the sync completion screen, so the
                # same course cannot report differently depending on how the user
                # reached it - see shared.helpers.split_delivery_errors.
                _split = split_delivery_errors(download_errors)
                _app_errors = _split['app']
                _retriable = _split['retriable']
                _unresolvable = _split['unresolvable']

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
                    unresolvable_reasons=_split['reasons'],
                )

                # 2. Post-processing warning
                render_pp_warning(st.session_state.get('pp_failure_count', 0))
                render_archives_skipped_notice()

                # 2b. Panopto recordings summary (if the terminal Panopto phase ran)
                render_panopto_summary(st.session_state.get('panopto_summary'))

                # Office watchdog broad-kill warning (parity with the sync
                # completion screen - previously only shown there even though
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
                        margin="12px 0 2px 0",
                    )

                # Size-skipped files are now rendered inside render_completion_card

                # 3. Error section (with retry button inside)
                download_path = Path(st.session_state['download_path'])
                # ONE manager, and one pass over the courses, for the whole
                # completion screen. A manager used to be constructed inside
                # this loop AND inside the folder-paths loop further down - two
                # per course - each paying for CanvasManager's vanity-URL
                # round-trip, so the screen blocked on live HTTP while Streamlit
                # streamed it in element by element. Both loops only ever wanted
                # _sanitize_filename, which touches no instance state.
                # (CanvasManager now memoises the resolution too, so this
                # construction is free after the scan phase's.)
                cm_temp = CanvasManager(st.session_state['api_token'], st.session_state['api_url'])
                _course_folders = {
                    c.name: download_path / cm_temp._sanitize_filename(c.name)
                    for c in st.session_state.get('courses_to_download', [])
                }
                error_log_paths = [
                    _folder / "download_errors.txt"
                    for _folder in _course_folders.values()
                    if (_folder / "download_errors.txt").exists()
                ]

                # Check if retriable errors exist (file errors with filepath context, not LTI streams, not app errors)
                has_retriable_errors = any(
                    not getattr(err, 'is_app_error', False)
                    and isinstance(getattr(err, 'context', None), dict)
                    and err.context.get('filepath')
                    and getattr(err, 'error_type', '') != 'LTI/Media Stream'
                    and not getattr(err, 'retry_exhausted', False)
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
                    # Fresh time-remaining model for the retry pass (it re-uses
                    # the run's counters, so a stale one would start at 100%).
                    st.session_state.pop('_retry_estimator', None)

                    st.session_state['total_items'] = len(st.session_state['isolated_retry_queue'])

                    st.rerun()

                render_error_section(
                    download_errors, error_log_paths,
                    dialog_fn=error_log_dialog,
                    key_prefix='dl',
                    retry_btn_callback=_do_retry if has_retriable_errors and not retry_attempted else None,
                    has_retriable_errors=has_retriable_errors,
                    # Parity with the sync completion screen: _retry_failed was
                    # already computed above but never passed, so a download user
                    # whose retry was spent saw a dead button and no next step.
                    retry_failed=_retry_failed,
                )

                # render_error_section early-returns on an empty error list, so a
                # run whose ONLY failure was a conversion printed "Check
                # download_errors.txt" with nothing to click. Same gap the sync
                # screen had; fixed the same way, through the same helper.
                if not download_errors and st.session_state.get('pp_failure_count', 0):
                    from shared.components import render_error_log_button
                    render_error_log_button(error_log_paths, key_prefix='dl_pp')

            # 4. Per-course folder cards with filetype summary (folders already
            #    resolved above - see the note on the shared manager)
            folder_paths = {name: str(path) for name, path in _course_folders.items()}

            render_folder_cards(file_details, folder_paths, key_prefix='dl')
        
        elif st.session_state.get('download_status') == 'cancelled':
            # Both the Office tidy-up and the card itself are shared with the sync
            # cancelled screen (shared/components.py). They used to be duplicated
            # here, with a comment claiming this copy "matches sync_ui.py design" -
            # two copies of one visual is how the two modes drift apart.
            from shared.components import quit_office_once, render_cancelled_card
            quit_office_once()
            render_cancelled_card(
                "Download",
                done=st.session_state.get('downloaded_items', 0),
                total=st.session_state.get('total_items', 0),
            )

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
        # Daily/Quick Sync launched from the Today page runs IN-PAGE: the Today
        # dashboard hosts the run as a slim progress card below the auto-sync
        # toggle, instead of the sync engine taking over the whole screen. It
        # drives the very same engine (render_sync_step4) inside that card.
        if st.session_state.get('today_sync_active'):
            from ui.today_dashboard import render_today_dashboard
            render_today_dashboard(fetch_courses)
        else:
            render_sync_step4()


# ─── Deferred dialog hosts ────────────────────────────────────────────────────
# Both modals are hosted here, at the very END of the script and at module level
# (never inside a fragment or a page module), for two reasons:
#
#  1. ORDERING - measured 2026-07-26. A dialog emitted BEFORE the main page
#     inserts its elements ahead of every main-page st.html(<style>) block.
#     Streamlit reuses the existing style hosts and reconciles them by INDEX, so
#     each host gets rewritten with its NEIGHBOUR's stylesheet: for ~110ms the
#     page behind the modal is not unstyled but *mis*-styled - titles collapse
#     (a 287px column snapped to 39px), negative margins reset, icons vanish.
#     Emitting them last means no main-page index moves and nothing restyles.
#     (A plain rerun with the identical CSS produces zero bad frames, so this is
#     an ordering bug, not an st.html-vs-st.markdown one.)
#  2. The transcription dialog runs an internal model-download auto-rerun loop,
#     which needs the modal re-emitted at top script level on every rerun.
#
# Only ONE may open per run - Streamlit crashes with "only one dialog allowed
# open at a time". The two flags are mutually exclusive by construction: opening
# transcription from Settings pops _stg_dialog_open, and panopto_page's close
# handler sets _stg_reopen_dialog to bring Settings back afterwards.
if st.session_state.get('_pan_dialog_open'):
    from ui.panopto_page import render_transcription_dialog
    render_transcription_dialog()
else:
    from ui.auth import open_pending_global_dialog
    open_pending_global_dialog()


# ─── Page-shell bridge ────────────────────────────────────────────────────────
# Sticky-bar pinned/at-rest state + scroll preservation across a dialog. Emitted
# LAST, after the dialog hosts above, so its observers see the final DOM of this
# run; it re-binds itself on every rerun (see the docstring). A 0-height
# components.html iframe is pulled out of flow by global.css, so it adds no gap.
from shared.components import inject_app_shell_bridge
inject_app_shell_bridge()
