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
    render_archives_skipped_notice, render_panopto_disabled_notice,
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
#
# Show is DEFERRED (SHOW_DELAY): a click arms the watcher but does not paint.
# A navigation that finishes first never shows a mask at all.
#
# Uncover, in one watcher with three exits - all gated on the app's own screen
# id having moved (#cdp_nav_state, written by ui/auth.py):
#   * run finished    - script state left "running" AND the DOM has been quiet
#                       for QUIET ms. Quiet, not a fixed hold, so the wait
#                       scales with the machine instead of being tuned to one.
#   * run STARTED     - data-busy says a download/sync/analysis is under way and
#                       its dashboard is up and quiet. A run holds the script
#                       thread for minutes, so waiting for it to finish means
#                       covering its own progress UI.
#   * no screen change- the click produced a run that did not navigate; bounded
#                       by NOCHANGE_MAX so it costs a beat, not the valve.
# An 8 s valve remains as a last resort and should now never fire.
#
# The three defects this replaced, all measured in the real app on 2026-07-31
# and all invisible precisely because the mask hid the evidence:
#   1. pageFingerprint() read the SIDEBAR's vertical block (the first one in the
#      document), which is identical on every page here - so the fingerprint was
#      really just stMain.scrollHeight, and sync step 1 / Today / the sync review
#      screen are all 1049. "Has the page changed" never became true and the
#      overlay could only exit via the valve: 8.03 s over a 179 ms navigation.
#   2. A long run never reaches "script finished", so Analyze, Quick Sync, Start
#      Sync, Confirm and Download and login were ALL covered for a flat 8 s. A
#      whole analysis - dashboard, live counts, ETA - rendered underneath and was
#      discarded unseen.
#   3. The 1200 ms stability window cost ~1.4 s on every ordinary navigation, on
#      top of a page that was already final. Measured waste: median 1484 ms.
# Script state remains the primary readiness signal and MUST NOT go back to
# stStatusWidget - see isStReady().
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
    var p=win._cdp||(win._cdp={vis:false,armed:false,el:null,obs:null,handler:null,
        showT:null,watchT:null,hideT:null,safeT:null,t0:0,lastMut:0,readyAt:0,
        sawRun:false,preScreen:null,preFP:null,abortScroll:false});

    // --- Tunables, in ONE place ---------------------------------------------
    // SHOW_DELAY: how long to wait before PAINTING the mask. It is 0, and the
    // history of that number is worth keeping because it inverted.
    //
    // It was 200 ms, on the reasoning that the first DOM change of a navigation
    // did not land until 124-235 ms, so an earlier mask covered a page that had
    // not moved yet. That was true - of an app whose pages took 1.2-1.9 s to
    // render. Once `core/course_cache.py` took the Canvas fetch off the render
    // path, whole navigations began finishing in 170-700 ms and the churn
    // started almost immediately, so a 200 ms delay no longer arrived early -
    // it arrived after most of the swap had already happened.
    //
    // Measured with `exposed_churn_ms` (page still changing while the mask is
    // below 85 % opacity - the honest version of the complaint, counting the
    // un-painted window and not just the fade): **median 311 ms, max 458 ms, on
    // EVERY transition** including the ones the mask did cover. Reported as
    // "through each transition it looks like the application is severely
    // glitching - elements are being scrambled everywhere".
    //
    // So the mask now paints from the click. At t=0 the old page is still
    // whole and nothing has moved, which is exactly the right moment to cover:
    // it reads as a cut to a loading state, not as a blackout thrown over
    // motion. The reason this is affordable NOW and was not before is that the
    // thing being hidden is short - the whole point of the two fixes above.
    var SHOW_DELAY=0;       // click -> start painting the mask
    // The fade-IN is the one thing that can make the mask WORSE than no mask:
    // while it ramps, the page churns visibly THROUGH it. Reported as "the ui
    // shift is visible for a split second behind it at ~50% opacity", and
    // measured with scripts/measure_nav.py's `leak_ms` (time the mask is
    // translucent while the page is still changing): a 150 ms linear fade-in
    // leaked a median 138-155 ms on the download-settings screens and 258 ms at
    // worst, on 18 of 30 transitions.
    //
    // So it is short AND front-loaded: the ease-out curve is past 85 % opacity
    // in roughly the first third, which is where the leak is paid, while still
    // being a ramp rather than a step. It exists so the mask arrives as a cut
    // to a loading state rather than a black step; it is NOT there to soften a
    // near-miss, which is why it must stay short.
    //
    // The fade-OUT can stay leisurely: by then the page is final, so there is
    // nothing left to leak and a gradual reveal reads better than a cut.
    var RECHECK=80;         // paint() declined; look again this much later
    var FADE_IN=45, FADE_OUT=110;
    var EASE_IN='cubic-bezier(.2,.8,.3,1)';
    // QUIET is measured from the last DOM mutation, NOT a fixed hold, and that
    // is what makes it scale with the machine. Measured: after the script run
    // ends the DOM still moves for ~58 ms on this machine and ~334 ms at 4x CPU
    // throttling. A constant tuned for one of those is wrong for the other; a
    // quiet window is right for both, because the churn itself is what keeps
    // resetting it.
    var QUIET=90;           // ready + this much DOM silence -> uncover
    var MIN_HOLD=60;        // never uncover in the same tick readiness arrived
    var READY_MAX=1200;     // ...but never wait longer than this after ready
    var BUSY_QUIET=180;     // long-run path: the dashboard is up and gone quiet
    var NOCHANGE_MAX=450;   // the click produced a run but no screen change
    var NORUN_MAX=1500;     // the click produced no run at all
    // Two valves, because "slow" and "hung" are different failures and only one
    // of them is worth uncovering onto. A script state of `running` is positive
    // evidence that the server is alive and working, so VALVE waits for it;
    // HARD_VALVE is the absolute cap that fires regardless, because a mask
    // nothing can lift is the one failure a user cannot work around.
    var VALVE=8000;         // force-uncover once the script is no longer running
    var HARD_VALVE=30000;   // ...and unconditionally at this point

    // --- Create overlay element once ---
    if(!p.el){
        var s=doc.createElement('style');
        s.textContent='@keyframes _cdR{to{transform:rotate(360deg)}}';
        doc.head.appendChild(s);
        p.el=doc.createElement('div');
        p.el.id='_cdOv';
        // opacity is transitioned, display is not - so the mask fades in over
        // the swap instead of slamming over it, and a transition that finishes
        // mid-fade reverses into a soft pulse rather than a hard black flash.
        p.el.style.cssText='position:fixed;top:0;left:0;right:0;bottom:0;'
            +'background:#0d1117;z-index:99999;display:none;flex-direction:column;'
            +'align-items:center;justify-content:center;gap:16px;opacity:0;'
            +'transition:opacity '+FADE_IN+'ms '+EASE_IN;
        p.el.innerHTML=
            '<div style="width:30px;height:30px;border:2.5px solid rgba(255,255,255,.07);'
            +'border-top-color:#38bdf8;border-radius:50%;animation:_cdR .75s linear infinite"></div>'
            +'<div style="color:rgba(255,255,255,.38);font:13px/1 system-ui,sans-serif;'
            +'letter-spacing:.04em">Loading…</div>';
        doc.body.appendChild(p.el);
    }

    function paint(){
        p.showT=null;
        if(p.vis||!p.armed)return;
        // The deferred show is decided on EVIDENCE, not just on the clock. If
        // the new screen is already up and its run has already finished, all
        // that remains is the confirmation window - covering the page now would
        // paint a mask over a page that has arrived, and then take it away
        // again, which is the flash the delay exists to avoid.
        //
        // This is also what makes the behaviour scale with the machine, which a
        // constant cannot: on a faster box more navigations are already
        // finished at this point, so fewer of them are ever masked. Measured
        // here, the two fastest screens land at ~130-215 ms and now show
        // nothing at all, while a 700 ms one is still covered for its whole
        // wait. Re-armed rather than cancelled: if this turns out to be a lull
        // between two runs, the next check still paints.
        if(screenId()!==p.preScreen&&isStReady()&&isPainted()){
            // RECHECK, not SHOW_DELAY: with SHOW_DELAY at 0 a re-arm on the
            // same value is a 0 ms self-rescheduling loop.
            p.showT=win.setTimeout(paint,RECHECK);
            return;
        }
        // Re-attach if Streamlit hot-reload replaced document.body while we were detached
        if(!p.el.isConnected)doc.body.appendChild(p.el);
        p.el.style.transition='opacity '+FADE_IN+'ms '+EASE_IN;
        p.el.style.display='flex';
        p.el.style.pointerEvents='auto';
        p.vis=true;
        // Reading offsetWidth forces the layout that makes the transition
        // actually run; without it the browser coalesces display+opacity into
        // one style recalculation and the mask appears at full strength.
        void p.el.offsetWidth;
        p.el.style.opacity='1';
    }

    function uncover(){
        // Stop covering IMMEDIATELY - pointer-events goes first and p.vis with
        // it, so the page is live for the whole fade rather than for the 110 ms
        // after it. The click handler reads p.vis to decide whether a click
        // that got through means the mask was not really blocking, so the two
        // must be lowered together.
        if(p.showT){win.clearTimeout(p.showT);p.showT=null;}
        if(p.safeT){win.clearTimeout(p.safeT);p.safeT=null;}
        if(p.watchT){win.clearTimeout(p.watchT);p.watchT=null;}
        p.armed=false;
        if(!p.vis){p.el.style.display='none';p.el.style.opacity='0';return;}
        p.vis=false;
        p.el.style.pointerEvents='none';
        p.el.style.transition='opacity '+FADE_OUT+'ms linear';
        p.el.style.opacity='0';
        if(p.hideT)win.clearTimeout(p.hideT);
        // display:none only after the fade, but guarded: a NEW navigation may
        // have re-armed and repainted in the meantime, and hiding it then would
        // strand that navigation with no mask at all.
        p.hideT=win.setTimeout(function(){
            p.hideT=null;
            if(!p.vis&&!p.armed)p.el.style.display='none';
        },FADE_OUT+20);
    }

    // Has the Python script finished?  Streamlit publishes its own script-run
    // state on the app root as data-test-script-state: "initial" | "running" |
    // "rerunRequested" | "notRunning" | "compilationError".
    //
    // This MUST NOT go back to polling [data-testid="stStatusWidget"] (what it
    // did until 2026-07-31).  That element is never in the DOM in this app:
    // styles/global.css hides it and .streamlit/config.toml + start.py both set
    // client.toolbarMode="minimal", so the old check returned "ready" on its
    // very first poll, every single time - Phase 2 was dead code.  That left
    // Phase 3's "1200 ms of DOM stillness" as the only gate, and a mid-render
    // Python stall of that length is indistinguishable from a finished page.
    // Measured: the overlay lifted at 61 elements / 21 stylesheets while the
    // script state still read "running", exposing a half-rendered, partly
    // unstyled Custom Download page with the previous page's elements still on
    // it.  Symptom: "the page was 50% raw unstyled Streamlit containers, STILL,
    // then 2-3 s later the styling was applied" - the stall is why it was
    // frozen, and the freeze is exactly what the old heuristic read as "done".
    function isStReady(){
        var app=doc.querySelector('[data-testid="stApp"]');
        var s=app&&app.getAttribute('data-test-script-state');
        if(s)return s!=='running'&&s!=='rerunRequested';
        // Fallback if a future Streamlit drops the attribute (it is a data-test-*
        // hook, so treat it as unstable): any element still flagged stale means
        // the page swap is mid-flight.  Legacy widget check last.
        if(doc.querySelector('[data-stale="true"]'))return false;
        return !doc.querySelector('[data-testid="stStatusWidget"]');
    }

    // The screen the app says it is rendering, and whether it says a long run
    // is in flight.  Both are written by ui/auth.py onto #cdp_nav_state - read
    // that block for what each field is for.  These are the two facts the
    // overlay cannot work out for itself, and every attempt to infer them from
    // the DOM has been wrong:
    //
    //   * "has the page changed" was a geometry fingerprint, and it COLLIDED.
    //     Sync step 1, the Today page and the sync review screen are all
    //     scrollHeight 1049, so the fingerprint never moved and the overlay sat
    //     until its 8-second valve. Measured 2026-07-31: sync<->today was 8.03 s
    //     against a page that had finished in 179 ms, and a whole Analyze run -
    //     dashboard, live counts, ETA and all - rendered underneath the mask and
    //     was then thrown away, uncovering only once the review screen was up.
    //   * "is the script finished" cannot answer "may I uncover" during a
    //     download or an analysis, because those hold the script thread for
    //     minutes. data-busy is what separates "still painting the screen" from
    //     "the screen is up and now it is working".
    function screenId(){
        var el=doc.getElementById('cdp_nav_state');
        return el?(el.getAttribute('data-screen')||''):'';
    }
    function isBusyRun(){
        var el=doc.getElementById('cdp_nav_state');
        return !!el&&el.getAttribute('data-busy')==='1';
    }

    // "The script has finished" does NOT mean "the DOM is finished".
    //
    // Streamlit renders each element inside <Suspense fallback={<Skeleton/>}>
    // and code-splits the implementations, so until a chunk resolves the page
    // holds `stSkeleton` placeholders where the real widgets go. Measured
    // 2026-07-31 at 4x CPU throttling on sync -> download: at the frame the
    // script state went notRunning the page carried **16 skeletons**, and 535 ms
    // later they became 15 checkboxes and a text input - +112 elements, and the
    // page shrank 1365 -> 1279 px. The DOM is genuinely STILL for most of that
    // gap, so a quiet window alone reads it as finished and uncovers onto a page
    // that is about to visibly pop.
    //
    // This is Streamlit's own "I do not have this component yet" marker, so it
    // is an exact signal rather than a heuristic - and the app never renders one
    // itself (ui/course_selector.py only styles around them, having hit the same
    // phenomenon from the other side). READY_MAX still caps the wait, so a chunk
    // that never arrives degrades to an ordinary uncover instead of a hang.
    function isPainted(){
        var m=doc.querySelector('[data-testid="stMain"]');
        return !m||!m.querySelector('[data-testid="stSkeleton"]');
    }

    // A fingerprint of what the MAIN page looks like.  It is a secondary
    // signal now (screenId() is the primary one), used only to refuse to
    // uncover while the main area still shows the OLD page.
    //
    // The block is looked up INSIDE stMain, and that is the entire bug fix.
    // `doc.querySelector('[data-testid="stVerticalBlock"]')` returns the
    // SIDEBAR's block - the sidebar is the first vertical block in the
    // document - and this app's sidebar is identical on every page. Measured
    // 2026-07-31: 59 elements on download, sync AND today. So the "element
    // count" half of the fingerprint was a constant, the whole fingerprint
    // collapsed to stMain.scrollHeight, and any two screens of equal height
    // were indistinguishable. That is why sync<->today took 8 seconds.
    function pageFingerprint(){
        var m=doc.querySelector('[data-testid="stMain"]');
        if(!m)return '';
        var vb=m.querySelector('[data-testid="stVerticalBlock"]');
        return m.scrollHeight+'|'+(vb?vb.querySelectorAll('*').length:0)
            +'|'+m.querySelectorAll('[data-testid="stElementContainer"]').length;
    }

    function scrollTop(){
        // abortScroll: a click reached a button while the mask claimed to be
        // covering, so it was NOT actually blocking input. The user is already
        // interacting with a settled page (e.g. expanding a sync-history card);
        // uncover silently rather than yanking them to the top.
        if(p.abortScroll){p.abortScroll=false;return;}
        p.abortScroll=false;
        win.scrollTo(0,0);
        var sc=doc.querySelectorAll('[data-testid="stMain"],'
            +'[data-testid="stAppViewContainer"],[data-testid="stVerticalBlock"]');
        for(var i=0;i<sc.length;i++) sc[i].scrollTop=0;
    }

    function done(){
        // Scrolling belongs to the NAVIGATION, not to the mask: with a deferred
        // show the mask often never paints, and a new screen must still arrive
        // at the top. So this runs on the decision, not on the uncover.
        //
        // ...but ONLY when a navigation actually happened. Three of the exits
        // below are "nothing came of that click" (no screen change, no run at
        // all, valve), and scrolling there would yank the user to the top of a
        // page they never left. Re-reading the screen id here rather than
        // taking a flag from each caller keeps that impossible to get wrong at
        // a call site, and is correct for the valve too - which may fire on
        // either kind of click.
        if(screenId()!==p.preScreen)scrollTop();
        uncover();
    }

    // The watcher.  One loop, three ways out, each with a different meaning.
    //
    // Everything is gated on `changed` - the app's own screen id differing from
    // the one captured at click time. That single condition replaces the old
    // `awaitChange` fingerprint dance AND makes the two-rerun pattern a
    // non-event: a sidebar nav button mutates session state and calls
    // st.rerun(), so run 1 renders the sidebar with the OLD screen id and only
    // run 2 publishes the new one. Measured, the gap between those two runs
    // does reach the DOM as a brief `notRunning` (20-38 ms here, longer under
    // load) - and a rule that trusts readiness alone uncovers inside it. In the
    // replay of 54 recorded navigations that mistake happened in 19 of them.
    function watch(){
        p.watchT=null;
        if(!p.armed)return;
        // The mask may have been detached by a Streamlit hot-reload replacing
        // document.body. p.vis would still claim it is covering while nothing
        // is, so the user is free to click - and this loop would later scroll
        // them to the top of a page they are already reading.
        if(p.vis&&!p.el.isConnected){p.vis=false;p.armed=false;return;}

        var now=Date.now();
        var ready=isStReady();
        if(!ready)p.sawRun=true;
        var changed=screenId()!==p.preScreen;

        if(changed){
            if(ready){
                if(!p.readyAt)p.readyAt=now;
                // Nothing is covering the page, so there is no reveal to get
                // wrong: stand down at once. The quiet window below exists to
                // stop a HALF-BUILT page being uncovered - it has no job when
                // the page was never covered, and holding on regardless is
                // what kept the mask fading in over navigations that had
                // already finished (measured: peak opacity 0.36-0.62 on
                // screens that were done in 152-188 ms).
                //
                // This is also the whole deferred-show idea completing itself.
                // The paint is 200 ms away, so on a machine where a screen
                // arrives inside 200 ms the mask is never painted at all, and
                // on a slower one it still covers the swap. Nothing is tuned to
                // a particular machine; the race between the two timers IS the
                // adaptation, and the fade means a photo finish costs a few
                // percent of opacity rather than a black flash.
                if(!p.vis){done();return;}
                // Uncover once the run has ended, the lazy components have
                // actually arrived, AND the DOM has gone quiet. Quiet, not a
                // fixed hold: measured, the DOM keeps moving for ~58 ms after
                // the run ends on this machine and ~334 ms at 4x CPU
                // throttling, so any constant is wrong for one of them while a
                // quiet window is right for both.
                var quiet=now-p.lastMut;
                if(now-p.readyAt>=READY_MAX){done();return;}
                if(now-p.readyAt>=MIN_HOLD&&quiet>=QUIET&&isPainted()){
                    done();return;
                }
            }else{
                p.readyAt=0;
                // The long-run path. A download, a sync or an analysis holds
                // the script thread for minutes, so "wait for the run to
                // finish" would mean covering the operation's own progress
                // dashboard for its whole duration - which is exactly what used
                // to happen, bounded only by the 8 s valve. Here the app has
                // told us a run is under way (data-busy), the screen id has
                // moved to the run's screen, and the main area no longer looks
                // like the page we left; once the DOM goes quiet the dashboard
                // is up and the user should be watching it, not a spinner.
                if(isBusyRun()&&pageFingerprint()!==p.preFP&&now-p.lastMut>=BUSY_QUIET){
                    done();return;
                }
            }
        }else if(ready&&p.sawRun){
            // A run happened but the screen id never moved: the click did not
            // navigate after all (a guard declined it, or it re-rendered the
            // same screen). Bounded so this costs a beat, not the valve.
            if(!p.readyAt)p.readyAt=now;
            if(now-p.readyAt>=NOCHANGE_MAX){done();return;}
        }else{
            p.readyAt=0;
            // No run has even STARTED and the screen has not moved. A real
            // navigation's run reaches the DOM in well under NORUN_MAX
            // (measured 34-78 ms here, ~300 ms at 4x CPU throttling), so this
            // can only mean the click produced nothing at all. Bounded here
            // rather than left to the valve, because "a mask that sits for 8
            // seconds over a page that is already finished" is the entire
            // defect this rewrite exists to remove - it must not survive in a
            // corner.
            if(!p.sawRun&&now-p.t0>=NORUN_MAX){done();return;}
        }

        // The valve. A render that is STILL RUNNING is slow, not hung, and
        // uncovering it shows a frozen half-built page for however long the
        // render still takes. Measured 2026-07-31: a sync-page render stalled
        // 14.7 s behind an expired fetch_courses cache (10-minute TTL, two
        // Canvas round-trips); the old unconditional 8 s valve uncovered onto
        // that half-page and left it there for the remaining 8.5 s. Waiting is
        // the honest answer - "Loading..." is true, a half-built page is not.
        if(now-p.t0>=VALVE&&(ready||now-p.t0>=HARD_VALVE)){done();return;}
        p.watchT=win.setTimeout(watch,25);
    }

    // Backstop for the case where the watcher's timer chain dies with its
    // realm and no new injection arrives to re-adopt it - which is precisely
    // what a long stalled render looks like, since a stalled script emits no
    // deltas and therefore re-injects nothing.
    function valveFire(){
        p.safeT=null;
        if(!p.armed)return;
        var el=Date.now()-p.t0;
        if(!isStReady()&&el<HARD_VALVE){
            p.safeT=win.setTimeout(valveFire,Math.min(VALVE,HARD_VALVE-el));
            return;
        }
        done();
    }

    function arm(){
        p.armed=true;
        p.t0=Date.now();
        p.lastMut=p.t0;
        p.readyAt=0;
        p.sawRun=false;
        p.abortScroll=false;
        p.preScreen=screenId();
        p.preFP=pageFingerprint();
        if(p.showT)win.clearTimeout(p.showT);
        if(p.watchT)win.clearTimeout(p.watchT);
        // With no deferral, paint SYNCHRONOUSLY from the click handler rather
        // than through a timer. A setTimeout(0) is still a macrotask hop, and
        // measured it cost ~34 ms before the mask reached full strength - which
        // was 100 % of the remaining visible churn. Painting inline puts the
        // mask in the DOM before the browser's next frame, so the swap is
        // covered from the first paint after the click.
        if(SHOW_DELAY<=0){paint();}
        else{p.showT=win.setTimeout(paint,SHOW_DELAY);}
        p.watchT=win.setTimeout(watch,25);
        // Last-resort valve. It should now never fire; it stays because the
        // failure it guards against - a mask nothing can lift - is the one
        // failure the user cannot work around.
        if(p.safeT)win.clearTimeout(p.safeT);
        p.safeT=win.setTimeout(valveFire,VALVE);
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
        // Custom Download's "Confirm and Download". Quick Download's twin
        // (page_nav_quick_start) was covered and this one was not, so the same
        // action was masked or bare depending on which screen you started it
        // from. Same class of gap as _retry_failed_btn below.
        'div[class*="st-key-action_dl_confirm"]', // Start the download (Custom)
        'div[class*="st-key-qd_goto_advanced"]',  // Customize configuration in Quick Download
        // Retry replaces a completion screen with a live run dashboard - as big
        // a screen change as any Continue button, and it was the one such
        // action with no cover at all. It is safe to list only now: with the
        // old hide path a run-starting button meant a flat 8-second blindfold
        // over the run's own progress UI, so adding it would have made the
        // worst case worse. Key is `<prefix>_retry_failed_btn`, hence no
        // `st-key-` anchor.
        'div[class*="_retry_failed_btn"]'         // Retry failed downloads
    ].join(',');
    // Re-bind a FRESH listener on every injection, never a one-time guard.
    // components.html destroys and recreates its iframe on every rerun, and a
    // handler whose closure belongs to a destroyed realm stops firing silently
    // - see the Panopto mask below, which already does exactly this, and the
    // JS-bridge rules in CLAUDE.md. The previous `if(!p.clickAdded)` form also
    // meant any edit to this handler kept running the ORIGINAL closure until a
    // full page reload, so a broken change could look fine while testing.
    // The stored reference stays valid for removeEventListener even when its
    // realm is gone, which is what makes the swap safe.
    try{ if(p.handler) doc.removeEventListener('click',p.handler,true); }catch(_){}
    {
        p.handler=function(e){
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
            // Arm. The mask is NOT painted here - see SHOW_DELAY in arm().
            arm();
        };
        doc.addEventListener('click',p.handler,true);
    }

    // --- Recreate MutationObserver on every iframe load ---
    // The previous observer (from the last iframe context) was disconnected when
    // that iframe was destroyed.  Always create a fresh one here.
    //
    // Its only job now is to timestamp the last DOM change; the watcher owns
    // every decision. It used to RESTART the whole hide sequence on each
    // mutation, which meant a screen that repaints continuously - a run
    // dashboard repaints ~2.5x/second - could starve the hide indefinitely and
    // leave the 8 s valve as the only way out.
    if(p.obs){try{p.obs.disconnect();}catch(_){}}
    p.obs=new MutationObserver(function(){
        if(p.armed)p.lastMut=Date.now();
    });
    p.obs.observe(doc.querySelector('[data-testid="stMain"]')||doc.body,
        {childList:true,subtree:true,attributes:false,characterData:false});

    // --- Re-adopt an in-flight navigation into THIS realm ---
    // Every timer above is a closure belonging to the iframe that created it,
    // and a navigation re-injects this script (that is the whole point of the
    // re-bind rule for the click listener). A watcher left owned by the
    // outgoing realm is the same silent-death hazard, only worse: nothing would
    // ever lift the mask except the valve. Re-arming from the current realm on
    // every injection costs three timer swaps and removes the question.
    // Deadlines are recomputed from p.t0, so re-adoption never extends them.
    if(p.armed){
        var el=Date.now()-p.t0;
        if(p.watchT)win.clearTimeout(p.watchT);
        p.watchT=win.setTimeout(watch,25);
        if(p.showT){
            win.clearTimeout(p.showT);
            p.showT=win.setTimeout(paint,Math.max(0,SHOW_DELAY-el));
        }
        if(p.safeT){
            win.clearTimeout(p.safeT);
            p.safeT=win.setTimeout(valveFire,Math.max(0,VALVE-el));
        }
    }else if(!p.vis&&p.el){
        // Not navigating and not covering: make sure a fade-out whose timer
        // died with its realm still ends up display:none rather than an
        // invisible full-screen element sitting on the page.
        p.el.style.display='none';
    }

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

# Unify the legacy saved-pairs / sync-list / daily-set stores into core.library
# on the first launch after this shipped. Runs here, before anything reads a
# pair: idempotent (guarded by sync_library.json), reversible (backs the legacy
# files up to *.bak), and total - a failure degrades to an empty library, i.e.
# Canvas names everywhere, never a crash. Checked once per SESSION: migration is
# a one-time event guarded by the library file's existence, so re-reading and
# JSON-parsing that file on every rerun buys nothing.
if not st.session_state.get('_library_migration_checked'):
    st.session_state['_library_migration_checked'] = True
    try:
        from core.library_migrate import migrate_if_needed
        migrate_if_needed()
    except Exception:
        pass

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
    {output_url/mp4/mp3/txt/srt, layout} contract shape that the runtime
    consumes. The engine config (model/device/language) is layered in by
    ``panopto.settings.compose_settings``.

    The mapping itself lives in ``panopto.settings.contract_from_ui_state`` -
    every place that needs the user's Panopto choices reads them through that
    one function, so adding an output cannot leave one caller behind.
    """
    from panopto.settings import contract_from_ui_state
    return contract_from_ui_state(st.session_state)


def _next_phase_after_courses() -> str:
    """Decide the status after all courses' files + post-processing finish.

    Runs the terminal Panopto phase when the user selected at least one Panopto
    output format in Section 4 of the download settings; otherwise goes straight
    to the completion screen.

    Resolved through ``effective_contract``, which is what applies the global
    Panopto switch. THIS is the gate for download mode, and it has to be here
    rather than inside the phase: the phase seeds each folder's stored
    ``panopto_contract`` before it runs anything (see "Persist this run's
    contract" below), so a gate any lower would overwrite every folder's saved
    Panopto configuration with all-off the first time someone switched the
    feature off. Called twice, both at the END of a run, so the config-file read
    is not on any render path.
    """
    try:
        from panopto.settings import effective_contract, is_enabled
        if is_enabled(effective_contract(_panopto_run_contract())):
            return 'panopto'
    except Exception:
        pass
    return 'done'



# The course list is cached and refreshed OFF the render path - see
# core/course_cache.py for why (it was the largest remaining page-render
# blocker: ~950 ms of Canvas round-trips, paid on every sidebar navigation).
from core.course_cache import fetch_courses

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
# A PLAIN container - deliberately NOT st.empty().container(), and this is the
# fix for a measured defect, not a simplification.
#
# `st.empty()` is an ELEMENT: it enqueues an `Empty` delta immediately.
# `slot = st.empty(); slot.container(...)` puts both deltas on the SAME delta
# path, and ForwardMsgQueue.enqueue composes two deltas at one path into the
# last one - so the `Empty` normally never reaches the browser. But composition
# only holds while BOTH are still in the queue, and Runtime._loop_coroutine
# flushes every ~10ms. When a flush lands between those two lines, the `Empty`
# ships on its own and the browser renders an empty box IN PLACE OF THE WHOLE
# PAGE until the container delta arrives.
#
# Reported as "after a certain amount of clicks the whole page turns dark for
# ~10ms and then comes back straight, with no UI shifting". Reproduced 2026-07-31
# by driving 300 rapid reruns: the page blanked FOUR times (~1.3% of reruns).
# Captured mid-dip - stMain down to 5-6 element containers, every one of them
# height 0, innerText "", and exactly one stEmpty present; stMain's own height
# stayed 999px, which is why the content returns without shifting anything.
#
# The wrapper existed so a long-running screen could wipe the page mid-run via
# `main_placeholder.empty()`. It bought almost nothing: `render_sync_step4()` is
# called with NO arguments, so sync/analysis.py's "wipe before blocking on
# analysis" has been a no-op for its whole life, and the only two live callers
# blanked the page ~200ms before an st.rerun() replaced it anyway - leaving the
# previous screen up until the new one arrives is the smoother of the two.
#
# Both forms emit exactly ONE `vertical` block at this index, so nothing about
# the page's reconciliation shape changes; only the stray `Empty` is gone.
with st.container():

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
            render_sync_step1(fetch_courses)

        
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

        # ── Debug log: ONE lifecycle for BOTH quick and custom download ──
        # Set up here, at the FIRST render of step 3, BEFORE the scan phase - so
        # discovery logs are captured too - and for EITHER entry path. The only
        # wiring used to be set_active_debug_file() deep in the per-course
        # 'running' loop below: it installed the bridge AFTER the scan (so a
        # session's first scan logged nothing to disk), and only *custom*
        # download cleared the file per run - quick download relied on the
        # once-per-session clear at startup, so its log silently accumulated or
        # stayed stale. Both paths reach step 3, so one block here covers both.
        # set_active_debug_file is idempotent and re-dedupes any bridge a
        # hot-reload left behind, so it runs every rerun; the clear + header run
        # once per run (the flag is reset at each run's start handler).
        if st.session_state.get('debug_mode', False):
            from core.canvas_debug import (
                clear_debug_log as _run_clear_dbg,
                set_active_debug_file as _run_set_dbg,
                log_session_header as _run_hdr_dbg,
            )
            _run_dbg_file = str(Path(st.session_state['download_path']) / 'debug_log.txt')
            if not st.session_state.get('_dl_debug_run_inited'):
                st.session_state['_dl_debug_run_inited'] = True
                _run_clear_dbg(_run_dbg_file)
                _run_n_courses = len(st.session_state.get('courses_to_download', []))
                _run_mode = 'quick' if st.session_state.get('quick_download_mode') else 'custom'
                _run_hdr_dbg(_run_dbg_file,
                             context=f"Download mode ({_run_mode}) | {_run_n_courses} course(s)")
            _run_set_dbg(_run_dbg_file)

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
                from engine.applescript_bridge import TCC_FIRST_RUN_NOTICE
                render_info_notice(
                    TCC_FIRST_RUN_NOTICE,  # audit-ignore: TCC_FIRST_RUN_NOTICE is a static module constant
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
                    # The logging bridge + session header + per-run clear are set
                    # up once at step-3 entry (shared by quick and custom, ahead
                    # of the scan). Here we only stamp the per-course markers.
                    _dl_dbg = str(Path(st.session_state['download_path']) / 'debug_log.txt')
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
                        margin="0",  # the card's flex gap (16px) is the ONE rhythm; a margin here adds to it
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
                'sc_total': 0, 'sc_done': 0,
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
                elif ph == 'links':
                    # Writing link files is instant, so this phase is usually a
                    # single frame - but it must exist: a Shortcut-only run has
                    # no other phase, and leaving the header on "Searching for
                    # Panopto Recordings" would describe the wrong activity for
                    # the whole run. No speed or ETA: nothing crosses the
                    # network, and a transfer rate for a 100-byte local write is
                    # noise dressed up as information.
                    render_progress_header(_pan_dp, "Saving Lecture Links", _pan['course'])
                    pct = int(_pan['sc_done'] / _pan['sc_total'] * 100) if _pan['sc_total'] else 0
                    render_progress_bar(_pan_dp, min(100, pct), color=PHASE_BAR_COLOR['panopto'])
                    render_metrics(_pan_dp, [
                        metric_count('Links Saved', _pan['sc_done'], _pan['sc_total'],
                                     accent=PHASE_BAR_COLOR['panopto']),
                        metric_elapsed(time.time() - pan_start),
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

                    # ── Shortcut phase ──
                    elif kind == 'shortcut_phase':
                        _pan['phase'] = 'links'
                        _pan['sc_total'] = kw.get('total', 0)
                        _pan['sc_done'] = 0
                        log_deque.append(log_divider(
                            f"Saving {_pan['sc_total']} lecture link{'s' if _pan['sc_total'] != 1 else ''}"))
                        _render_pan()
                    elif kind == 'shortcut':
                        _pan['sc_done'] += 1
                        log_deque.append(log_line('success', kw.get('title', ''),
                                                  icon=file_icon_svg(kw.get('path') or 'x.url'),
                                                  detail='link saved'))
                        render_active_file(active_file_placeholder, kw.get('title', ''),
                                           phase='panopto', label='Saving link')
                        _render_pan()
                    elif kind == 'shortcut_done':
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
                    retriable_count=_retriable,
                    unresolvable_count=_unresolvable,
                    app_error_count=_app_errors,
                    courses_count=len(file_details),
                    # Rendered INSIDE the card, right under the stat grid - it
                    # is a stat grid too. See the ordering note there.
                    panopto_summary=st.session_state.get('panopto_summary'),
                )

                # THE ORDER IS BY KIND, and it is the same on both completion
                # screens: stats -> Panopto stats -> every collapsible -> every
                # notice. It used to be the order the features were built in, so
                # an amber warning sat between two expanders and the Panopto
                # stat grid sat below both of them.
                #
                # EXPANDERS. The size-skip panel is emitted by
                # render_completion_card above; archives follow it, then the
                # Panopto-off panel (the third member of the same "deliberately
                # left alone" family), and the error panel is last because it is
                # the one the user opens.
                render_archives_skipped_notice()
                render_panopto_disabled_notice(mode='download')

                # (error section: the last expander, plus the retry button and
                #  the app-error report that belong to it)
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
                    download_errors,
                    key_prefix='dl',
                    retry_btn_callback=_do_retry if has_retriable_errors and not retry_attempted else None,
                    has_retriable_errors=has_retriable_errors,
                    # Parity with the sync completion screen: _retry_failed was
                    # already computed above but never passed, so a download user
                    # whose retry was spent saw a dead button and no next step.
                    retry_failed=_retry_failed,
                )

                # NOTICES, last, as one block. Everything above is a metric or
                # a collapsible; these are the run's asides, and interleaving
                # them broke both groups.
                render_pp_warning(st.session_state.get('pp_failure_count', 0))

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
                        margin="0",  # the card's flex gap (16px) is the ONE rhythm; a margin here adds to it
                    )

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
# open at a time". The flags are mutually exclusive by construction: opening
# transcription from Settings pops _stg_dialog_open, and panopto_page's close
# handler sets _stg_reopen_dialog to bring Settings back afterwards.
#
# The acceptable-use notice comes FIRST. It gates the Panopto feature itself, so
# it can be raised from a settings-card callback, a Quick Download preset or a
# sync confirm - any of which could otherwise be contending for the same slot.
# Its guard returns False and the caller does nothing further, so the run this
# notice interrupts has not started and there is nothing for another modal to be
# about. Deciding precedence here (rather than at the four call sites) is what
# keeps that guarantee in one place.
from shared.legal import NOTICE_OPEN_KEY as _PAN_NOTICE_OPEN
from shared.legal import resume_is_pending as _pan_resume_pending
if st.session_state.get(_PAN_NOTICE_OPEN):
    from ui.panopto_notice import render_panopto_notice
    render_panopto_notice()
elif _pan_resume_pending():
    # The notice has just been answered. Its action is deliberately NOT run in
    # that same script run: the transition it performs enters the blocking
    # download at app.py:1359, a thousand lines above this host, so the run
    # would never get here and the modal would stay painted over the download.
    # This lets the current run FINISH (which is what removes the modal) and
    # fires the action on the next tick. See render_pending_resume.
    from ui.panopto_notice import render_pending_resume
    render_pending_resume()
elif st.session_state.get('_pan_dialog_open'):
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
