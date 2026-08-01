"""The navigation overlay must uncover on REAL signals, and as early as they allow.

Two defects, three months apart, both invisible for the same reason: the overlay
hides the evidence of its own misbehaviour.

2026-07-31 (a): the readiness signal was dead
---------------------------------------------
Phase 2 polled for the REMOVAL of ``[data-testid="stStatusWidget"]``. That
element is never in the DOM here - ``styles/global.css`` hides it and both
``.streamlit/config.toml`` and ``start.py`` set ``client.toolbarMode="minimal"``
- so it returned "ready" on its first poll, every time. That left "the DOM has
not changed for 1200 ms" as the only gate, and a render that STALLS mid-stream
holds the DOM perfectly still while the page is half there. Fixed by reading
Streamlit's own ``data-test-script-state``.

2026-07-31 (b): the overlay outlived the thing it was hiding, by a lot
---------------------------------------------------------------------
Measured with ``scripts/measure_nav.py``, which neutralises the mask with CSS
while leaving its JavaScript running - so one recording carries both the true
transition and every decision the overlay made, on one clock. Across 54
navigations the page was final a median of **1484 ms** before the overlay
lifted, and in the worst case **7862 ms**. Three causes:

1. ``pageFingerprint()`` read ``doc.querySelector('[data-testid=
   "stVerticalBlock"]')`` - the FIRST vertical block in the document, which is
   the SIDEBAR's. This app's sidebar is identical on every page (59 elements
   measured on download, sync and today), so the "element count" half was a
   constant and the fingerprint was really just ``stMain.scrollHeight``. Sync
   step 1, Today and the sync review screen are all 1049. "Has the page
   changed" therefore never became true and the only exit was the 8 s valve:
   sync<->today took **8.03 s** against a page that finished in 179 ms.
2. A long run never reaches "script finished", so every run-starting nav button
   - Analyze, Quick Sync, Start Sync, Confirm and Download, login - was covered
   for a flat 8 s. A whole analysis rendered its dashboard, live counts and ETA
   underneath the mask and was discarded unseen.
3. The 1200 ms stability window charged ~1.4 s to every ordinary navigation on
   top of a page that was already final.

What is locked down here
------------------------
* Readiness is Streamlit's ``data-test-script-state``; ``running`` and
  ``rerunRequested`` both count as not-ready.
* "The page changed" is the app's OWN screen id, never a geometry fingerprint.
* Any fingerprint that survives is scoped INSIDE ``stMain``.
* There is a path that uncovers while a run is still going (``data-busy``).
* The show is DEFERRED, and is skipped outright when the screen is already up.
* The whole hide path is re-adopted by each iframe realm.

Assertions target whole EXPRESSIONS, never a bare identifier: strings like
``stStatusWidget`` and ``awaitChange`` legitimately survive in the comments that
explain why they are gone, so "is the name present" proves nothing.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
APP = REPO / "app.py"
AUTH = REPO / "ui" / "auth.py"
GLOBAL_CSS = REPO / "styles" / "global.css"
ST_CONFIG = REPO / ".streamlit" / "config.toml"


@pytest.fixture(scope="module")
def app_src() -> str:
    return APP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def auth_src() -> str:
    return AUTH.read_text(encoding="utf-8")


def _overlay_script(src: str) -> str:
    """The nav-overlay components.html block (the one that owns _cdOv)."""
    start = src.index("var p=win._cdp||(win._cdp=")
    end = src.index("Server-shutdown watchdog", start)
    return src[start:end]


def _watchdog_script(src: str) -> str:
    """The server-shutdown watchdog, which lives AFTER the overlay block."""
    start = src.index("Server-shutdown watchdog")
    return src[start: src.index('</script>""", height=0)', start)]


def _strip_js_comments(js: str) -> str:
    """Blank // and /* */ comments so a rule is never satisfied by prose.

    Same trick ``scripts/verify_architecture.py`` uses before scanning: the
    explanation of a defect names the thing that caused it, so a test that reads
    comments can pass on documentation alone.
    """
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"//[^\n]*", "", js)


def _fn_body(code: str, decl: str) -> str:
    """The source of one JS function, by brace matching from its declaration."""
    i = code.index(decl)
    j = code.index("{", i)
    depth = 0
    for k in range(j, len(code)):
        if code[k] == "{":
            depth += 1
        elif code[k] == "}":
            depth -= 1
            if depth == 0:
                return code[i:k + 1]
    raise AssertionError(f"unbalanced braces after {decl!r}")


@pytest.fixture(scope="module")
def js(app_src) -> str:
    return _strip_js_comments(_overlay_script(app_src))


# --------------------------------------------------------------------------
# The readiness signal
# --------------------------------------------------------------------------

def test_readiness_reads_streamlits_script_run_state(js):
    """Readiness must consult data-test-script-state, not the status widget."""
    assert "data-test-script-state" in js, (
        "The nav overlay no longer reads Streamlit's script-run state. Without "
        "it the hide path has no real 'the script finished' signal and falls "
        "back to guessing from DOM stillness - which a mid-render stall "
        "satisfies while the page is half-rendered."
    )


def test_running_and_rerun_requested_both_count_as_not_ready(js):
    """A queued rerun still means another page is on its way."""
    normalised = re.sub(r"\s+", "", js)
    assert "s!=='running'&&s!=='rerunRequested'" in normalised, (
        "isStReady() must treat BOTH 'running' and 'rerunRequested' as not "
        "ready. Dropping 'rerunRequested' uncovers the page in the gap between "
        "two chained reruns, which is the two-rerun pattern the sidebar nav "
        "buttons produce."
    )


def test_status_widget_is_never_the_sole_readiness_signal(js):
    """The dead check may remain as a LAST-resort fallback, never as the gate."""
    ready_fn = _fn_body(js, "function isStReady()")
    assert "data-test-script-state" in ready_fn
    if "stStatusWidget" in ready_fn:
        assert ready_fn.index("data-test-script-state") < ready_fn.index(
            "stStatusWidget"
        ), (
            "stStatusWidget is being consulted before Streamlit's script-run "
            "state. That element is hidden by global.css and suppressed by "
            "client.toolbarMode='minimal', so it is ALWAYS absent - reaching it "
            "first makes isStReady() return True on its first poll, every time."
        )


# --------------------------------------------------------------------------
# "Has the page changed" - the 8-second bug
# --------------------------------------------------------------------------

def test_page_change_is_decided_by_the_apps_own_screen_id(js):
    """Not by a geometry fingerprint. Fingerprints collide; screen ids do not."""
    assert "getAttribute('data-screen')" in js, (
        "The overlay no longer reads #cdp_nav_state's data-screen. It is the "
        "only signal that says WHICH screen is rendered; inferring it from "
        "geometry is what made sync<->today take 8 seconds, because sync step "
        "1, Today and the sync review screen are all scrollHeight 1049."
    )
    watch = _fn_body(js, "function watch()")
    assert "screenId()!==p.preScreen" in re.sub(r"\s+", "", watch), (
        "watch() must compare the live screen id against the one captured at "
        "click time. Without that comparison the two-rerun pattern uncovers in "
        "the gap between run 1 and run 2, while the OLD page is still on screen."
    )


def test_fingerprint_is_scoped_inside_stmain(js):
    """The regression that cost 8 seconds a navigation.

    ``doc.querySelector('[data-testid="stVerticalBlock"]')`` returns the
    SIDEBAR's block - it is the first one in the document - and this app's
    sidebar is byte-identical on every page. The fingerprint then degenerates to
    stMain.scrollHeight alone.
    """
    fp = _fn_body(js, "function pageFingerprint()")
    assert "m.querySelector('[data-testid=\"stVerticalBlock\"]')" in fp, (
        "pageFingerprint() must look the vertical block up INSIDE stMain."
    )
    assert "doc.querySelector('[data-testid=\"stVerticalBlock\"]')" not in fp, (
        "pageFingerprint() is back to querying the document for the first "
        "stVerticalBlock. That is the SIDEBAR's block - identical on every page "
        "here (measured: 59 elements on download, sync AND today) - so the "
        "fingerprint collapses to scrollHeight and any two equal-height screens "
        "become indistinguishable."
    )


def test_marker_carries_every_field_a_navigation_can_move(auth_src):
    """mode alone is not a screen id - four fields are each uniquely load-bearing."""
    i = auth_src.index("id='cdp_nav_state'")
    block = auth_src[max(0, i - 2000): i + 400]
    assert "data-screen=" in block and "data-busy=" in block, (
        "#cdp_nav_state must publish data-screen and data-busy - the two facts "
        "the overlay cannot work out for itself."
    )
    assert re.search(r"_screen\s*=\s*_he\(f\"\{mode\}\|\{step\}\|\{_quick\}\|\{_status\}\"",
                     auth_src), (
        "data-screen must be built from mode, step, the quick-download flag AND "
        "download_status. Each is the ONLY field that moves for some navigation: "
        "quick for 'Customize configuration' (Quick and Custom Download are both "
        "mode=download step=2), and status for starting a run at all. Drop one "
        "and those navigations stop being a screen change - which is the "
        "condition every uncover path is gated on."
    )


def test_busy_flag_comes_from_the_apps_own_operation_check(auth_src):
    """Same source as the nav lock, so the two can never disagree."""
    i = auth_src.index("id='cdp_nav_state'")
    assert "data-busy='{'1' if _locked else '0'}'" in auth_src[i - 2000: i + 400], (
        "data-busy must be _locked, i.e. core.cancellation.is_operation_in_"
        "progress() - the same call that locks the sidebar nav buttons. A "
        "second, independent notion of 'a run is happening' is how the overlay "
        "and the rest of the app drift apart."
    )


# --------------------------------------------------------------------------
# A run that holds the script thread
# --------------------------------------------------------------------------

def test_a_running_operation_has_its_own_uncover_path(js):
    """Analyze/sync/download hold the script for minutes - readiness never comes.

    Without this path every run-starting button is a flat 8-second blindfold
    over the run's own progress dashboard. Measured before the fix: an Analyze
    whose dashboard was on screen at 392 ms stayed covered until 8045 ms.
    """
    watch = _fn_body(js, "function watch()")
    flat = re.sub(r"\s+", "", watch)
    assert "isBusyRun()" in flat, (
        "watch() has no long-run path. 'Wait for the script to finish' cannot "
        "decide when to uncover a download or an analysis, because those hold "
        "the script thread for their whole duration."
    )
    assert "pageFingerprint()!==p.preFP" in flat, (
        "The long-run path must also require the MAIN area to no longer look "
        "like the page we left. data-busy is published by the sidebar, which "
        "renders BEFORE the main content - so on its own it would allow "
        "uncovering while the old page is still on screen."
    )


# --------------------------------------------------------------------------
# Deferred show
# --------------------------------------------------------------------------

def test_the_show_is_deferred_and_skippable(js):
    """The deferral MECHANISM must survive, even though SHOW_DELAY is now 0.

    The constant inverted once already and could again. It was 200 ms while the
    app's pages took 1.2-1.9 s to render, on the reasoning that a mask painted
    before the first DOM change covers a page that has not moved. Once
    core/course_cache.py took the Canvas fetch off the render path and whole
    navigations began finishing in 170-700 ms, the churn started almost
    immediately and a 200 ms delay stopped arriving early - it arrived after
    most of the swap. Measured as `exposed_churn_ms`: **median 311 ms, max 458,
    on every transition**, reported as "elements are being scrambled
    everywhere". Keeping the machinery means re-tuning is a one-constant change.
    """
    arm = _fn_body(js, "function arm()")
    assert "win.setTimeout(paint,SHOW_DELAY)" in re.sub(r"\s+", "", arm), (
        "arm() must DEFER the paint. Painting on click means even a 152 ms "
        "navigation gets a full-screen blackout, which reads as slower than "
        "showing the truth."
    )
    paint = _fn_body(js, "function paint()")
    assert "screenId()!==p.preScreen&&isStReady()" in re.sub(r"\s+", "", paint), (
        "paint() must decline to paint when the new screen is already up and "
        "its run has already finished. This is what makes the behaviour scale "
        "with the machine: on a faster box more navigations are finished by "
        "SHOW_DELAY, so fewer are ever masked - no constant can do that."
    )


def test_an_unpainted_mask_uncovers_without_waiting(js):
    """The confirmation window protects a REVEAL, and there is none if nothing covers."""
    watch = _fn_body(js, "function watch()")
    assert "if(!p.vis){done();return;}" in re.sub(r"\s+", "", watch), (
        "watch() must stand down immediately when the mask was never painted. "
        "Holding the quiet window open there kept fading the mask in over "
        "navigations that had already finished (measured: peak opacity "
        "0.36-0.62 on screens done in 152-188 ms)."
    )


def test_uncover_waits_for_dom_quiet_not_a_fixed_hold(js):
    """The wait has to scale with the machine, and only a quiet window does.

    Measured: after a run ends the DOM still moves for ~58 ms on this machine
    and ~334 ms at 4x CPU throttling. A constant tuned for either is wrong for
    the other; the churn itself is what resets a quiet window.
    """
    watch = _fn_body(js, "function watch()")
    flat = re.sub(r"\s+", "", watch)
    assert "varquiet=now-p.lastMut" in flat, (
        "The uncover must be gated on time since the last DOM mutation."
    )
    assert "quiet>=QUIET" in flat


def test_a_lazy_skeleton_means_the_page_is_not_finished(js):
    """"The script finished" is not "the DOM finished".

    Streamlit renders every element inside ``<Suspense fallback={<Skeleton/>}>``
    and code-splits the implementations. Measured 2026-07-31 at 4x CPU
    throttling on sync -> download: at the frame the script state went
    notRunning the page carried **16 stSkeleton placeholders**, which became 15
    checkboxes and a text input **535 ms later** (+112 elements, and the page
    shrank 1365 -> 1279 px). The DOM is still for most of that gap, so a quiet
    window alone reads it as finished and uncovers onto a page about to pop.
    """
    assert "function isPainted()" in js, (
        "The skeleton gate is gone. Without it the overlay uncovers while "
        "Streamlit is still resolving lazy component chunks, and the widgets "
        "pop in afterwards - measured at -89 ms of cover, i.e. the mask was "
        "already transparent before the page reached its final state."
    )
    painted = _fn_body(js, "function isPainted()")
    assert 'stSkeleton' in painted
    watch = _fn_body(js, "function watch()")
    assert "isPainted()" in watch, "watch() no longer consults the skeleton gate"
    paint = _fn_body(js, "function paint()")
    assert "isPainted()" in paint, (
        "paint()'s skip must also require the lazy components to have arrived, "
        "or a navigation that is 'ready' but still all skeletons declines the "
        "mask and shows the user the pop."
    )
    m = re.search(r"READY_MAX\s*=\s*(\d+)", js)
    assert m and int(m.group(1)) >= 800, (
        "READY_MAX is the cap on how long the skeleton gate may hold the mask. "
        "Below the measured chunk-resolution time (535 ms at 4x CPU) it fires "
        "first and the gate never gets to do its job."
    )


def test_the_fade_in_is_short_and_front_loaded(js):
    """A slow fade-in leaks the very churn the mask exists to hide.

    While the mask ramps, the page changes visibly THROUGH it - reported as
    "the ui shift is visible for a split second behind it at ~50% opacity".
    ``scripts/measure_nav.py`` measures it as ``leak_ms``: time the mask is
    translucent (0.02-0.85) while the visual signature is still moving. A
    150 ms LINEAR fade-in leaked a median 138-155 ms on the download-settings
    screens, 258 ms at worst, on 18 of 30 transitions. At 70 ms on
    ``cubic-bezier(.2,.8,.3,1)`` - past 85 % opacity in about the first third -
    that fell to a median of 0 and a max of 83 ms, on 7 of 30.

    The fade-OUT is deliberately NOT capped here: by then the page is final, so
    there is nothing left to leak and a gradual reveal reads better than a cut.
    """
    m = re.search(r"var\s+FADE_IN\s*=\s*(\d+)", js)
    assert m, "FADE_IN is gone - the mask is back to a hard cut, or was renamed"
    assert int(m.group(1)) <= 100, (
        f"FADE_IN is {m.group(1)} ms. Every millisecond of it is a millisecond "
        f"of page churn shown through a half-transparent mask. The flash it "
        f"guards against - a transition finishing just after the paint - is "
        f"rare, because paint()'s evidence check already declines the fast ones."
    )
    e = re.search(r"var\s+EASE_IN\s*=\s*'([^']+)'", js)
    assert e and e.group(1) != "linear", (
        "EASE_IN is linear again. The leak is paid in the low-opacity part of "
        "the ramp, so the curve has to be front-loaded; linear spends half the "
        "fade below 50 % opacity."
    )
    paint = _fn_body(js, "function paint()")
    assert "EASE_IN" in paint, "paint() no longer applies the front-loaded curve"


def test_no_multi_second_stability_window_survives(app_src):
    """The 1200 ms window cost ~1.4 s on every navigation, on top of a final page."""
    js = _strip_js_comments(_overlay_script(app_src))
    # READY_MAX and NORUN_MAX are CAPS on paths that should not be reached, not
    # waits on the normal one - READY_MAX in particular has to outlast the
    # measured lazy-chunk resolution (535 ms at 4x CPU) or the skeleton gate
    # never gets to act. Everything that gates an ordinary navigation stays
    # small, and QUIET is the one that decides the common case.
    budgets = {"QUIET": 250, "MIN_HOLD": 250, "BUSY_QUIET": 400,
               "NOCHANGE_MAX": 1000, "READY_MAX": 1500, "NORUN_MAX": 2000,
               # SHOW_DELAY is capped hard and low. It is the window in which
               # the page swap is visible RAW, and the swap now starts within a
               # few tens of ms of the click - so anything above ~100 ms puts
               # the scrambling back on screen. Measured at 200 ms:
               # exposed_churn_ms median 311, max 458, on every transition.
               "SHOW_DELAY": 120}
    for name, cap in budgets.items():
        m = re.search(rf"var\s+{name}\s*=\s*(\d+)", js) or \
            re.search(rf"{name}\s*=\s*(\d+)", js)
        assert m, f"tunable {name} is gone - the hide path was restructured"
        assert int(m.group(1)) <= cap, (
            f"{name} is {m.group(1)} ms, over its {cap} ms budget. The defect "
            f"this file exists to prevent is a page that is already final being "
            f"held behind a mask; the old rule wanted 1200 ms of stillness and "
            f"cost a median 1484 ms per navigation."
        )


# --------------------------------------------------------------------------
# Surviving the iframe teardown
# --------------------------------------------------------------------------

def test_click_listener_is_rebound_on_every_injection(js):
    """Never a one-time guard - components.html rebuilds its iframe each rerun."""
    assert "removeEventListener('click'" in js, (
        "The nav overlay must remove its previous click listener before adding "
        "a fresh one; without the removal every rerun stacks another handler."
    )
    assert "addEventListener('click',p.handler,true)" in re.sub(r"\s+", "", js)
    assert "clickAdded" not in js, (
        "The one-time `p.clickAdded` guard is back. It is the anti-pattern "
        "CLAUDE.md forbids for components.html bridges: the listener is attached "
        "once from an iframe realm that is destroyed on the next rerun, and it "
        "then fails silently and permanently."
    )


def test_an_inflight_navigation_is_readopted_by_each_realm(js):
    """Same hazard as the click listener, applied to the hide path's timers."""
    flat = re.sub(r"\s+", "", js)
    assert "if(p.armed){" in flat and "p.watchT=win.setTimeout(watch,25);" in flat, (
        "There is no re-adoption block. Every timer on the hide path is a "
        "closure owned by the iframe that created it, and a navigation "
        "re-injects this script - so a watcher left with the outgoing realm is "
        "the same silent death the click listener is re-bound to avoid, except "
        "that here nothing would ever lift the mask but the valve."
    )
    assert "Math.max(0,SHOW_DELAY-el)" in flat and "Math.max(0,VALVE-el)" in flat, (
        "Re-adoption must recompute deadlines from p.t0. Restarting them at "
        "full length means a navigation that re-injects repeatedly can push its "
        "own paint - and its safety valve - indefinitely into the future."
    )


def test_hide_path_timers_belong_to_the_parent_realm(js):
    """Timers must be win.setTimeout, not the iframe's own."""
    for fn in ("setTimeout", "clearTimeout"):
        bare = re.findall(r"(?<![\w.])" + fn + r"\(", js)
        assert not bare, (
            f"{len(bare)} bare {fn}() call(s) in the nav-overlay hide path. Use "
            f"win.{fn}() so the id stays valid across the iframe teardown that "
            f"happens on every rerun."
        )


def test_shutdown_watchdog_interval_stays_iframe_scoped(app_src):
    """The one timer that must NOT be hoisted to the parent window."""
    watchdog = _strip_js_comments(_watchdog_script(app_src))
    assert "win.setInterval(" not in watchdog, (
        "The shutdown watchdog's setInterval was hoisted onto window.parent. It "
        "would then survive every rerun and accumulate one health-poll loop per "
        "rerun. It is iframe-scoped on purpose - see the lifetime note beside it."
    )
    assert re.search(r"(?<![\w.])setInterval\(", watchdog), (
        "The shutdown watchdog no longer polls - the branded 'app closed' screen "
        "will never appear when the server dies."
    )


# --------------------------------------------------------------------------
# The mask must never be able to strand the user
# --------------------------------------------------------------------------

def test_every_exit_goes_through_one_function(js):
    """Three conditions uncover; all of them must also scroll and disarm."""
    watch = _fn_body(js, "function watch()")
    assert watch.count("done();return;") >= 3, (
        "watch() should reach done() from the finished-run path, the "
        "long-run path and the no-screen-change path. A path that lowers the "
        "mask by hand instead will skip the scroll-to-top, or leave p.armed set "
        "so the next navigation's re-adoption revives a dead watcher."
    )
    assert "VALVE" in watch, "the last-resort valve is no longer checked in watch()"


def test_the_valve_waits_on_a_script_that_is_still_running(js):
    """Slow is not hung, and only one of them is worth uncovering onto.

    Measured 2026-07-31: a sync-page render stalled 14.7 s behind an expired
    ``fetch_courses`` cache. The old unconditional 8 s valve uncovered onto a
    frozen half-built page and left it there for the remaining 8.5 s - strictly
    worse than continuing to say "Loading...", which was true.
    """
    watch = _fn_body(js, "function watch()")
    assert "now-p.t0>=VALVE&&(ready||now-p.t0>=HARD_VALVE)" in re.sub(r"\s+", "", watch), (
        "The valve fires again while the script is still running. A `running` "
        "state is positive evidence the server is alive and working; the only "
        "thing uncovering buys there is a half-rendered page."
    )
    valve = _fn_body(js, "function valveFire()")
    assert "isStReady()" in valve and "HARD_VALVE" in valve, (
        "The timer backstop must apply the same rule as watch(), and must still "
        "have an absolute cap - a mask nothing can lift is the one failure the "
        "user cannot work around."
    )


def test_scroll_to_top_only_happens_when_a_navigation_happened(js):
    """Three of the exits mean "nothing came of that click"."""
    d = _fn_body(js, "function done()")
    assert "if(screenId()!==p.preScreen)scrollTop();" in re.sub(r"\s+", "", d), (
        "done() must scroll only when the screen id actually moved. The "
        "no-screen-change, no-run and valve exits all reach done() too, and "
        "scrolling there yanks the user to the top of a page they never left - "
        "the same intermittent complaint the abortScroll guard exists for."
    )


def test_pointer_events_drop_before_the_fade_completes(js):
    """The page must be live for the whole fade-out, not just after it."""
    unc = _fn_body(js, "function uncover()")
    flat = re.sub(r"\s+", "", unc)
    # Only the FADING branch is at issue. The early return above it handles the
    # never-painted case, where opacity is already 0 and there is nothing to
    # order against.
    early = "if(!p.vis){p.el.style.display='none';p.el.style.opacity='0';return;}"
    assert early in flat, (
        "uncover() no longer short-circuits when the mask was never painted. "
        "Without it a skipped navigation still runs a fade-out."
    )
    flat = flat[flat.index(early) + len(early):]
    assert flat.index("p.vis=false") < flat.index("p.el.style.opacity='0'"), (
        "uncover() must lower p.vis and pointer-events BEFORE starting the "
        "fade. The click handler reads p.vis to decide whether a click that got "
        "through means the mask was not really blocking, so the two have to move "
        "together - otherwise every click during the 110 ms fade is misread as "
        "the mask having been detached, and cancels the scroll-to-top."
    )
    assert "pointerEvents='none'" in flat


def test_run_starting_buttons_are_covered(app_src):
    """The allowlist must include the actions that replace a screen with a run.

    Retry was the one such action with no cover at all. It is only safe to list
    now: with the old hide path a run-starting button meant a flat 8-second
    blindfold over the run's own progress UI.
    """
    js = _strip_js_comments(_overlay_script(app_src))
    nav = js[js.index("var NAV_SEL="): js.index(".join(',')")]
    for key in ("st-key-btn_analyze_sync", "st-key-btn_quick_sync",
                "st-key-page_nav_", "_retry_failed_btn",
                # Quick Download's start was covered and Custom Download's was
                # not, so the same action was masked or bare depending on which
                # screen it was launched from.
                "st-key-action_dl_confirm"):
        assert key in nav, f"{key} is no longer covered by the nav overlay"


# --------------------------------------------------------------------------
# Why the old signal was dead - the two facts that made it invisible
# --------------------------------------------------------------------------

def test_status_widget_really_is_suppressed():
    """Records WHY polling stStatusWidget could never work here."""
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    assert '[data-testid="stStatusWidget"]' in css, (
        "global.css no longer hides stStatusWidget - the comment in app.py's "
        "isStReady() explaining why that signal was dead is now stale."
    )
    config = ST_CONFIG.read_text(encoding="utf-8")
    assert re.search(r'toolbarMode\s*=\s*"minimal"', config), (
        "client.toolbarMode is no longer 'minimal' - re-check whether "
        "stStatusWidget is back in the DOM and update isStReady()'s comment."
    )
