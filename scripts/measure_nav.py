"""Measure what a page navigation actually costs, and what the overlay charges for it.

Why this exists
---------------
``app.py`` covers every page navigation with a full-screen "Loading…" overlay.
Nobody could say how long the thing it hides actually takes, because the overlay
hides it - so the only available judgement was "it feels slow". This tool
replaces the feeling with numbers, and it is deliberately built so the answer
does not depend on trusting the overlay's own opinion of when it is done.

The trick is that the overlay is **neutralised, not disabled**: a CSS rule hides
``#_cdOv`` while its JavaScript keeps running untouched. One recording therefore
carries, on the same clock:

* the transition as the user would see it with no overlay at all (per-frame
  geometry + optional real pixels via CDP screencast), and
* every decision the live overlay made (``display`` flips, its own gates),

so "how far is the overlay from the truth" is a subtraction rather than a
comparison of two runs that were never the same run.

What a trace contains
---------------------
A ``requestAnimationFrame`` loop samples a *visual signature* every frame:
scroll height, element count, a hash of the top-level children's rects, text
length and stylesheet count. Post-hoc we know the future, so the ground truth
is computable: ``t_settle`` is the last frame whose signature differs from the
final one. A live detector can never know that; this tool can, and that gap is
exactly the thing being measured.

Alternative hide policies are then *replayed* against the recorded frames
(``analyze``), which scores a candidate without shipping it - including whether
it would have uncovered the page while it was still changing.

Usage
-----
    python scripts/measure_nav.py record --repeats 3
    python scripts/measure_nav.py record --scenarios sidebar --cpu 1,4 --screencast
    python scripts/measure_nav.py analyze                     # newest trace
    python scripts/measure_nav.py analyze --trace <path.json>

Requires an audit run with an app and browser already up::

    python -m tests.audit run new --label navperf
    python -m tests.audit app start
    python -m tests.audit browser open
"""

from __future__ import annotations

import argparse
import base64
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.audit.harness import browser, paths  # noqa: E402

TRACE_DIR = REPO / "_audit_runs" / "_navperf"

# --------------------------------------------------------------------------
# The in-page recorder
# --------------------------------------------------------------------------
# Kept in one string so it can be re-installed after any full page load. All
# state hangs off window.__cdM; the app's own overlay state is read from
# window._cdp, never written to.
JS_RECORDER = r"""
(() => {
  const W = window;
  if (W.__cdM && W.__cdM.version === 3) return {installed: 'already', version: 3};

  const M = W.__cdM = {
    version: 3,
    label: null, t0: 0, frames: [], muts: [], states: [], ov: [],
    running: false, raf: null, obs: null, attrObs: null, clickT: null,
    baseline: null, wall0: 0,
  };

  const q = (s, r) => (r || document).querySelector(s);
  const app = () => q('[data-testid="stApp"]');
  const main = () => q('[data-testid="stMain"]') || document.body;

  // Visual signature. Everything here is cheap and layout-read-only; the point
  // is that two frames with the same signature look the same to the user.
  //
  // NOTE the block is looked up INSIDE stMain. A bare
  // document.querySelector('[data-testid="stVerticalBlock"]') returns the
  // SIDEBAR's block, which is identical on every page of this app (59
  // elements) - that is the defect this tool was built to find, and copying it
  // here would have made the instrument blind to the same thing.
  M.sig = function () {
    const m = main();
    const vb = q('[data-testid="stVerticalBlock"]', m);
    let geo = 0, n = 0;
    if (vb) {
      const kids = vb.children;
      n = vb.querySelectorAll('*').length;
      for (let i = 0; i < kids.length; i++) {
        const r = kids[i].getBoundingClientRect();
        // Round to whole pixels: sub-pixel jitter is not a visual change.
        geo = (geo * 33 + (r.top | 0) * 7 + (r.height | 0) * 13 + (r.width | 0)) | 0;
      }
    }
    return {
      h: m.scrollHeight,
      n: n,
      k: vb ? vb.children.length : 0,
      geo: geo,
      txt: (m.textContent || '').length,
      sty: document.querySelectorAll('style').length,
      sh: document.styleSheets.length,
    };
  };

  M.sigKey = s => s.h + '|' + s.n + '|' + s.k + '|' + s.geo + '|' + s.txt + '|' + s.sty + '|' + s.sh;

  M.snapshot = function () {
    const a = app();
    const ovEl = document.getElementById('_cdOv');
    const p = W._cdp || {};
    // Opacity, not display. The mask fades, so `display:none` lands ~130ms
    // AFTER the page is already visible again - measuring it would charge the
    // overlay for time the user spent looking at the page. `ovOp` is what the
    // user actually sees; `ovDisp` is kept because it is what the old
    // hard-cut implementation moved, so the two runs stay comparable.
    let op = 0;
    if (ovEl && (ovEl.style.display || '') !== 'none') {
      op = parseFloat(getComputedStyle(ovEl).opacity) || 0;
    }
    return {
      state: (a && a.getAttribute('data-test-script-state')) || '?',
      conn: (a && a.getAttribute('data-test-connection-state')) || '?',
      stale: document.querySelectorAll('[data-stale="true"]').length,
      ovDisp: ovEl ? (ovEl.style.display || '') : 'absent',
      ovOp: +op.toFixed(3),
      ovVis: !!p.vis,
      sig: M.sig(),
    };
  };

  M.arm = function (label) {
    M.label = label;
    M.frames = []; M.muts = []; M.states = []; M.ov = [];
    M.t0 = performance.now();
    M.wall0 = Date.now();
    M.clickT = null;
    M.baseline = M.snapshot();
    M.lastState = M.baseline.state;
    M.lastOv = M.baseline.ovDisp;
    M.running = true;

    // Structural mutations under stMain - the raw "the DOM is still moving"
    // signal the overlay's MutationObserver also reacts to.
    M.obs = new MutationObserver(recs => {
      if (!M.running) return;
      M.muts.push({t: +(performance.now() - M.t0).toFixed(1), n: recs.length});
    });
    M.obs.observe(main(), {childList: true, subtree: true});

    // Attribute-level watch on the app root so a script-state flip is timed to
    // the mutation, not to whichever animation frame happens to notice it.
    M.attrObs = new MutationObserver(() => {
      if (!M.running) return;
      const a = app();
      const s = a && a.getAttribute('data-test-script-state');
      if (s !== M.lastState) {
        M.states.push({t: +(performance.now() - M.t0).toFixed(1), s: s});
        M.lastState = s;
      }
    });
    if (app()) M.attrObs.observe(app(), {attributes: true, attributeFilter: ['data-test-script-state']});

    const tick = () => {
      if (!M.running) return;
      const s = M.snapshot();
      const t = +(performance.now() - M.t0).toFixed(1);
      M.frames.push({t: t, s: s.state, st: s.stale, ov: s.ovDisp, op: s.ovOp, ...s.sig});
      if (s.ovDisp !== M.lastOv) {
        M.ov.push({t: t, disp: s.ovDisp});
        M.lastOv = s.ovDisp;
      }
      M.raf = requestAnimationFrame(tick);
    };
    M.raf = requestAnimationFrame(tick);
    return {armed: label, t0: M.t0, wall0: M.wall0, baseline: M.baseline};
  };

  // A trusted click is recorded by the same listener the overlay uses, so the
  // two share an origin and no offset has to be assumed.
  if (!M.clickBound) {
    document.addEventListener('click', e => {
      if (!M.running || M.clickT !== null) return;
      const b = e.target.closest && e.target.closest('button');
      if (!b) return;
      M.clickT = +(performance.now() - M.t0).toFixed(1);
    }, true);
    M.clickBound = true;
  }

  // Quiescent = the signature has not moved for `quietMs`, the script is not
  // running, and (when the overlay is live) it has already lifted.
  M.status = function (quietMs) {
    if (!M.frames.length) return {done: false, why: 'no frames'};
    const last = M.frames[M.frames.length - 1];
    const key = f => f.h + '|' + f.n + '|' + f.k + '|' + f.geo + '|' + f.txt + '|' + f.sty + '|' + f.sh;
    const fin = key(last);
    let changedAt = 0;
    for (let i = M.frames.length - 1; i >= 0; i--) {
      if (key(M.frames[i]) !== fin) { changedAt = M.frames[i].t; break; }
    }
    const quiet = last.t - changedAt;
    return {
      done: quiet >= quietMs && last.s !== 'running' && last.s !== 'rerunRequested',
      quiet: +quiet.toFixed(1), t: last.t, state: last.s, ov: last.ov,
      frames: M.frames.length,
    };
  };

  M.take = function () {
    M.running = false;
    if (M.raf) cancelAnimationFrame(M.raf);
    try { M.obs.disconnect(); } catch (e) {}
    try { M.attrObs.disconnect(); } catch (e) {}
    return {
      label: M.label, t0: M.t0, wall0: M.wall0, clickT: M.clickT,
      baseline: M.baseline, frames: M.frames, muts: M.muts,
      states: M.states, ovEvents: M.ov,
    };
  };

  return {installed: 'ok', version: 3};
})()
"""

NEUTRALISE_CSS = """
(() => {
  let s = document.getElementById('__cdM_neutralise');
  if (!s) {
    s = document.createElement('style');
    s.id = '__cdM_neutralise';
    document.head.appendChild(s);
  }
  s.textContent = '#_cdOv{display:none!important;pointer-events:none!important}' +
                  '#_cdPanMaskOv{display:none!important;pointer-events:none!important}';
  return true;
})()
"""

DENEUTRALISE = """
(() => { const s = document.getElementById('__cdM_neutralise');
         if (s) s.remove(); return true; })()
"""


# --------------------------------------------------------------------------
# Scenario catalogue
# --------------------------------------------------------------------------
# A scenario is (id, group, description, setup, action). ``setup`` puts the app
# in the starting state and is NOT measured; ``action`` is the single click that
# is. Both take the audit Session.

def _goto(sess, mode, step=1, quick=False):
    sess.page.goto(sess.app_url(mode, str(step), quick), wait_until="domcontentloaded")
    sess.wait_ready()
    _settle(sess)


def _settle(sess, quiet=0.6, timeout=25.0):
    """Wait until the DOM has been still for `quiet` s and no run is in flight."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        st = sess.page.evaluate(
            """() => {
                const a = document.querySelector('[data-testid="stApp"]');
                const m = document.querySelector('[data-testid="stMain"]');
                const vb = m && m.querySelector('[data-testid="stVerticalBlock"]');
                return {s: a && a.getAttribute('data-test-script-state'),
                        n: vb ? vb.querySelectorAll('*').length : 0,
                        h: m ? m.scrollHeight : 0,
                        ov: (document.getElementById('_cdOv') || {}).style
                            ? document.getElementById('_cdOv').style.display : 'absent'};
            }"""
        )
        key = (st.get("s"), st.get("n"), st.get("h"))
        if last == key and st.get("s") not in ("running", "rerunRequested") \
                and st.get("ov") != "flex":
            return st
        last = key
        time.sleep(quiet / 2)
    return {"timeout": True}


def _locate(sess, key):
    host = sess.page.locator(f'[class*="st-key-{key.lower()}"]').first
    loc = host.locator("button").first
    if loc.count() == 0:
        loc = host
    # A sticky action bar can leave a control below the fold. Scrolling is done
    # here, by the caller, BEFORE arming - a scroll inside the measured window
    # would show up as a geometry change and inflate the settle time.
    try:
        loc.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass
    return loc


def _click_key(sess, key, timeout=20.0):
    _locate(sess, key).click(timeout=timeout * 1000, force=True)


def _select_first_course(sess):
    """Tick one course so the download buttons are not JS-gated."""
    sess.page.evaluate(
        """() => {
            const c = document.querySelector('[class*="st-key-dl_chk_"] input[type=checkbox]');
            return !!c;
        }"""
    )
    host = sess.page.locator('[class*="st-key-dl_chk_"]').first
    box = host.locator('[data-testid="stCheckbox"] > label').first
    checked = sess.page.evaluate(
        """() => { const c = document.querySelector('[class*="st-key-dl_chk_"] input[type=checkbox]');
                   return c ? c.checked : null; }"""
    )
    if not checked:
        box.click(timeout=15000)
        _settle(sess)


SCENARIOS = [
    # id, group, description, setup(sess), action key
    ("dl1_to_sync1", "sidebar", "Download step 1 -> Sync page",
     lambda s: _goto(s, "download", 1), "nav_btn_sync"),
    ("sync1_to_today", "sidebar", "Sync page -> Today",
     lambda s: _goto(s, "sync", 1), "nav_btn_today"),
    ("today_to_dl1", "sidebar", "Today -> Download step 1",
     lambda s: _goto(s, "today", 1), "nav_btn_download"),
    ("sync1_to_dl1", "sidebar", "Sync page -> Download step 1",
     lambda s: _goto(s, "sync", 1), "nav_btn_download"),
    ("dl1_to_today", "sidebar", "Download step 1 -> Today",
     lambda s: _goto(s, "download", 1), "nav_btn_today"),
    ("today_to_sync1", "sidebar", "Today -> Sync page",
     lambda s: _goto(s, "today", 1), "nav_btn_sync"),

    ("dl1_to_dl2", "wizard", "Course list -> Custom Download settings",
     lambda s: (_goto(s, "download", 1), _select_first_course(s)),
     "btn_custom_download"),
    ("dl2_to_dl1", "wizard", "Download settings -> Back to course list",
     lambda s: (_goto(s, "download", 1), _select_first_course(s),
                _click_key(s, "btn_custom_download"), _settle(s)),
     "action_dl_back"),
    ("dl1_to_quick", "wizard", "Course list -> Quick Download",
     lambda s: (_goto(s, "download", 1), _select_first_course(s)),
     "btn_quick_download"),
    ("quick_to_dl2", "wizard", "Quick Download -> Customize configuration",
     lambda s: (_goto(s, "download", 1), _select_first_course(s),
                _click_key(s, "btn_quick_download"), _settle(s)),
     "qd_goto_advanced"),
]

GROUPS = sorted({s[1] for s in SCENARIOS})


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------

def _cdp(sess):
    return sess.page.context.new_cdp_session(sess.page)


def record(args) -> dict:
    rp = paths.latest_run()
    TRACE_DIR.mkdir(parents=True, exist_ok=True)

    wanted = None
    if args.scenarios and args.scenarios != "all":
        want = {w.strip() for w in args.scenarios.split(",")}
        wanted = [s for s in SCENARIOS if s[0] in want or s[1] in want]
    else:
        wanted = list(SCENARIOS)
    if not wanted:
        raise SystemExit(f"No scenario matched {args.scenarios!r}. "
                         f"ids: {[s[0] for s in SCENARIOS]} groups: {GROUPS}")

    cpus = [float(c) for c in str(args.cpu).split(",")] if args.cpu else [1.0]

    out = {
        "recorded": time.strftime("%Y-%m-%d %H:%M:%S"),
        "overlay": args.overlay,
        "repeats": args.repeats,
        "cpu_rates": cpus,
        "app_port": rp.load_meta().get("app", {}).get("port"),
        "transitions": [],
    }

    with browser.session(rp) as sess:
        sess.page.goto(sess.app_url(), wait_until="domcontentloaded")
        sess.wait_ready()
        sess.page.evaluate(JS_RECORDER)

        cdp = _cdp(sess) if (args.cpu or args.screencast) else None

        for rate in cpus:
            if cdp and rate != 1.0:
                cdp.send("Emulation.setCPUThrottlingRate", {"rate": rate})
            elif cdp:
                cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})

            for rep in range(args.repeats):
                for sid, group, desc, setup, key in wanted:
                    try:
                        rec = _record_one(sess, cdp, sid, group, desc, setup, key,
                                          args, rate, rep)
                    except Exception as e:  # a broken scenario must not lose the run
                        rec = {"id": sid, "group": group, "cpu": rate, "rep": rep,
                               "error": f"{type(e).__name__}: {e}"}
                        print(f"  !! {sid} cpu={rate} rep={rep}: {rec['error']}")
                    out["transitions"].append(rec)

        if cdp:
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
        sess.page.evaluate(DENEUTRALISE)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = TRACE_DIR / f"trace_{stamp}_{args.overlay}.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\nwrote {path}  ({len(out['transitions'])} transitions)")
    return {"trace": str(path), "n": len(out["transitions"])}


def _record_one(sess, cdp, sid, group, desc, setup, key, args, rate, rep) -> dict:
    # Setup runs at full speed - only the measured click is throttled.
    if cdp and rate != 1.0:
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
    setup(sess)
    sess.page.evaluate(JS_RECORDER)
    if args.overlay == "neutralized":
        sess.page.evaluate(NEUTRALISE_CSS)
    else:
        sess.page.evaluate(DENEUTRALISE)
    _settle(sess)
    if cdp and rate != 1.0:
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": rate})

    shots: list[dict] = []
    if args.screencast and cdp:
        def _on_frame(ev):
            shots.append({"t": ev["metadata"]["timestamp"], "data": ev["data"]})
            try:
                cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
            except Exception:
                pass
        cdp.on("Page.screencastFrame", _on_frame)
        cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 60,
                                          "maxWidth": 900, "maxHeight": 620,
                                          "everyNthFrame": 1})

    loc = _locate(sess, key)          # scroll first; never inside the window
    _settle(sess, quiet=0.3, timeout=8)
    armed = sess.page.evaluate(f"__cdM.arm({json.dumps(sid)})")
    try:
        loc.click(timeout=8000, force=True)
    except Exception:
        # Some controls sit in a sticky bar whose transformed ancestor makes
        # Playwright call them "outside the viewport" however much you scroll.
        # A dispatched click still drives React (its synthetic handler does not
        # check isTrusted) and still reaches the overlay's own listener.
        loc.dispatch_event("click")

    # Poll for quiescence. The budget is generous because an under-measured
    # tail would understate exactly the number this tool exists to produce.
    deadline = time.time() + args.max_seconds
    status = {}
    while time.time() < deadline:
        status = sess.page.evaluate(f"__cdM.status({args.quiet_ms})")
        if status.get("done") and status.get("ov") != "flex":
            break
        time.sleep(0.08)

    trace = sess.page.evaluate("__cdM.take()")

    if args.screencast and cdp:
        try:
            cdp.send("Page.stopScreencast")
        except Exception:
            pass

    rec = {
        "id": sid, "group": group, "desc": desc, "cpu": rate, "rep": rep,
        "key": key, "status": status, "armed_wall": armed.get("wall0"),
        "baseline": trace.get("baseline"),
        "clickT": trace.get("clickT"),
        "frames": trace.get("frames"),
        "muts": trace.get("muts"),
        "states": trace.get("states"),
        "ovEvents": trace.get("ovEvents"),
    }
    if shots:
        rec["screencast"] = _pixel_settle(shots, armed.get("wall0"))
    m = metrics(rec)
    rec["metrics"] = m
    print(f"  {sid:<16} cpu={rate:<4} rep={rep}  "
          f"settle={_f(m.get('t_settle'))}  script={_f(m.get('t_script_done'))}  "
          f"maskShown={'Y' if m.get('mask_shown') else 'n'}"
          f" peak={m.get('peak_opacity'):.2f} maskMs={_f(m.get('mask_visible_ms'))}"
          f" coverWaste={_f(m.get('cover_waste'))} EXPOSED={_f(m.get('exposed_churn_ms'))}")
    return rec


def _f(v):
    return "  n/a" if v is None else f"{v:6.0f}"


def _pixel_settle(shots, wall0) -> dict:
    """Last screencast frame that differs from the final one, in trace time."""
    try:
        from PIL import Image, ImageChops
        import io
    except Exception as e:
        return {"error": f"PIL unavailable: {e}", "frames": len(shots)}

    imgs = []
    for s in shots:
        try:
            im = Image.open(io.BytesIO(base64.b64decode(s["data"]))).convert("L")
            im = im.resize((160, 110))
            imgs.append((s["t"], im))
        except Exception:
            continue
    if len(imgs) < 2:
        return {"frames": len(imgs), "note": "too few frames"}

    final = imgs[-1][1]
    diffs = []
    for ts, im in imgs:
        d = ImageChops.difference(im, final)
        hist = d.histogram()
        n_diff = sum(hist[8:])            # ignore jpeg noise below 8/255
        mean = sum(i * c for i, c in enumerate(hist)) / (160 * 110)
        # timestamp is seconds since epoch; map onto the trace's perf clock
        t = (ts * 1000.0) - wall0
        diffs.append({"t": round(t, 1), "n": n_diff, "mean": round(mean, 3)})

    last_change = None
    for d in reversed(diffs):
        if d["n"] > 60:                   # >0.3% of pixels visibly different
            last_change = d["t"]
            break
    return {"frames": len(imgs), "t_pixel_settle": last_change,
            "diffs": diffs[:400]}


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def _key(f):
    return (f["h"], f["n"], f["k"], f["geo"], f["txt"], f["sty"], f["sh"])


def metrics(rec: dict) -> dict:
    frames = rec.get("frames") or []
    if len(frames) < 3:
        return {"error": "too few frames", "frames": len(frames)}

    fin = _key(frames[-1])
    base = _key(frames[0])

    t_settle = 0.0            # last frame that did not look like the end state
    for f in reversed(frames):
        if _key(f) != fin:
            t_settle = f["t"]
            break

    t_first_change = None     # first frame that stopped looking like the start
    for f in frames:
        if _key(f) != base:
            t_first_change = f["t"]
            break

    states = rec.get("states") or []
    t_script_done = None
    for s in states:                       # last entry into a non-running state
        if s["s"] not in ("running", "rerunRequested"):
            t_script_done = s["t"]
    t_run_start = next((s["t"] for s in states if s["s"] == "running"), None)

    # First moment the live gate (script state) would have said "ready" and
    # never went back on it - the earliest a coherence-only policy could fire.
    t_ready_stable = None
    for i, f in enumerate(frames):
        if f["s"] in ("running", "rerunRequested"):
            t_ready_stable = None
        elif t_ready_stable is None:
            t_ready_stable = f["t"]

    ov = rec.get("ovEvents") or []
    t_ov_show = next((e["t"] for e in ov if e["disp"] == "flex"), None)
    t_ov_hide = None
    for e in ov:
        if e["disp"] == "none":
            t_ov_hide = e["t"]

    # What the user actually saw: the mask is opaque enough to hide the page
    # from ~0.5 opacity. `peak_opacity` of 0 means it never painted at all.
    lit = [f for f in frames if f.get("op", 0) > 0.02]
    covered = [f for f in frames if f.get("op", 0) >= 0.5]
    peak_op = max((f.get("op", 0) for f in frames), default=0.0)
    t_vis_from = lit[0]["t"] if lit else None
    t_vis_to = lit[-1]["t"] if lit else None
    t_cov_to = covered[-1]["t"] if covered else None

    stale_nonzero = any(f["st"] > 0 for f in frames)
    stale_without_running = any(
        f["st"] > 0 and f["s"] not in ("running", "rerunRequested") for f in frames)

    # How different does the page actually LOOK end to end? A transition whose
    # start and end signatures match is one the overlay covered for nothing.
    visual_delta = sum(1 for a, b in zip(base, fin) if a != b)
    dh = abs(frames[-1]["h"] - frames[0]["h"])
    dn = abs(frames[-1]["n"] - frames[0]["n"])

    # THE LEAK: time during which the mask is TRANSLUCENT while the page is
    # still changing underneath it. This is the user-reported symptom - "the ui
    # shift is visible for a split second behind it at ~50% opacity" - and it is
    # a direct cost of the fade-IN, which ramps across exactly the window where
    # the swap is at its ugliest. Frames are ~16.7ms, so a count is a duration.
    leak = 0.0
    # EXPOSED CHURN: the honest version of the user-visible complaint. Time the
    # page is still changing while the mask is NOT effectively covering it -
    # whether that is because it has not painted yet (the SHOW_DELAY window),
    # because it is mid-fade, or because it already lifted. `leak_ms` below
    # counts only the translucent part; this counts everything the eye can see.
    exposed = 0.0
    for a, b in zip(frames, frames[1:]):
        op = a.get("op", 0)
        changing = _key(a) != fin
        if changing and op < 0.85:
            exposed += b["t"] - a["t"]
        if changing and 0.02 < op < 0.85:
            leak += b["t"] - a["t"]

    out = {
        "frames": len(frames),
        "leak_ms": round(leak, 1),
        "exposed_churn_ms": round(exposed, 1),
        "frame_ms_median": round(statistics.median(
            [b["t"] - a["t"] for a, b in zip(frames, frames[1:])]) or 0, 1),
        "t_click": rec.get("clickT"),
        "t_run_start": t_run_start,
        "t_script_done": t_script_done,
        "t_ready_stable": t_ready_stable,
        "t_first_change": t_first_change,
        "t_settle": t_settle,
        "t_ov_show": t_ov_show,
        "t_ov_hide": t_ov_hide,
        "peak_opacity": round(peak_op, 3),
        "t_mask_from": t_vis_from,
        "t_mask_to": t_vis_to,
        "t_mask_covered_to": t_cov_to,
        "mask_shown": peak_op > 0.02,
        "mask_visible_ms": (round(t_vis_to - t_vis_from, 1)
                            if (t_vis_from is not None and t_vis_to is not None) else 0.0),
        "t_pixel_settle": (rec.get("screencast") or {}).get("t_pixel_settle"),
        "visual_delta": visual_delta,
        "d_scrollheight": dh,
        "d_elements": dn,
        "mutation_batches": len(rec.get("muts") or []),
        "stale_ever_nonzero": stale_nonzero,
        "stale_while_not_running": stale_without_running,
        "state_changes": [f"{s['t']:.0f}:{s['s']}" for s in states],
    }
    if t_ov_hide is not None:
        out["overlay_waste"] = round(t_ov_hide - t_settle, 1)
        out["overlay_total"] = round(t_ov_hide - (t_ov_show or 0), 1)
    # The honest number: how long the page stayed HIDDEN after it was final.
    if t_cov_to is not None:
        out["cover_waste"] = round(t_cov_to - t_settle, 1)
    elif peak_op <= 0.02:
        out["cover_waste"] = 0.0
    if t_script_done is not None:
        out["settle_after_script"] = round(t_settle - t_script_done, 1)
    return out


# --------------------------------------------------------------------------
# Policy replay - score a candidate hide rule against recorded frames
# --------------------------------------------------------------------------

def replay(rec: dict, policy) -> dict:
    """Run `policy` over the frames and report when it would have uncovered.

    A policy is a callable(frames, i) -> bool meaning "hide now, given frames
    up to and including i". Exposure is the ground-truth question: did anything
    still change visually after the policy fired?

    No policy is offered a frame before the run has been seen RUNNING. At t=0
    the page still carries the *previous* run's ``notRunning``, because the
    click has not reached the server yet - a replay without this gate reports
    every ready-based policy firing at 3 ms, which is an artefact of the
    measurement and not something any implementation would do. The real
    overlay has the same obligation and meets it with the screen-id marker.
    """
    frames = rec.get("frames") or []
    if len(frames) < 3:
        return {"error": "too few frames"}
    start = next((i for i, f in enumerate(frames) if not _ready(f)), None)
    if start is None:
        return {"t_hide": None, "exposed": False, "no_run": True}
    fin = _key(frames[-1])
    for i in range(start, len(frames)):
        if policy(frames, i):
            t = frames[i]["t"]
            after = [f for f in frames[i + 1:] if _key(f) != fin]
            return {
                "t_hide": t,
                "exposed_ms": round(after[-1]["t"] - t, 1) if after else 0.0,
                "exposed": bool(after),
            }
    return {"t_hide": None, "exposed_ms": None, "exposed": False, "never": True}


def _ready(f):
    return f["s"] not in ("running", "rerunRequested")


def policy_current(frames, i):
    """The shipped rule, as closely as a frame replay can express it.

    150 ms debounce from the last mutation, then coherence, then six identical
    200 ms samples. Replayed on frames the stability window is 6 * 200 ms of
    unchanged signature after coherence.
    """
    f = frames[i]
    if not _ready(f):
        return False
    k = _key(f)
    t = f["t"]
    for j in range(i, -1, -1):
        if frames[j]["t"] < t - 1200:
            return _ready(frames[j])
        if _key(frames[j]) != k or not _ready(frames[j]):
            return False
    return False


def make_policy_quiet(quiet_ms: float):
    """Coherent, plus `quiet_ms` of unchanged signature."""
    def p(frames, i):
        f = frames[i]
        if not _ready(f):
            return False
        k = _key(f)
        t = f["t"]
        for j in range(i, -1, -1):
            if frames[j]["t"] < t - quiet_ms:
                return True
            if _key(frames[j]) != k or not _ready(frames[j]):
                return False
        return False
    return p


def policy_coherent_now(frames, i):
    """Hide on the first frame the script is not running. The floor."""
    return _ready(frames[i])


def make_policy_confirm(confirm_ms: float):
    """The proposed rule: the run has ended and stayed ended for `confirm_ms`.

    Deliberately does NOT require the signature to be unchanged over the
    window. Post-run settling (clearStaleNodes, an icon font swapping in) moves
    geometry for a few frames, and a rule that resets on every such move is the
    1200 ms stability window all over again - it waits for stillness the page
    reaches only after it is already correct.
    """
    def p(frames, i):
        f = frames[i]
        if not _ready(f):
            return False
        t = f["t"]
        for j in range(i, -1, -1):
            if frames[j]["t"] < t - confirm_ms:
                return True
            if not _ready(frames[j]):
                return False
        return False
    return p


POLICIES = {
    "current(1200ms stable)": policy_current,
    "ready+0ms": policy_coherent_now,
    "ready+50ms": make_policy_quiet(50),
    "ready+150ms": make_policy_quiet(150),
    "ready+400ms": make_policy_quiet(400),
    "PROPOSED ready-held 60ms": make_policy_confirm(60),
    "PROPOSED ready-held 100ms": make_policy_confirm(100),
    "PROPOSED ready-held 160ms": make_policy_confirm(160),
    "PROPOSED ready-held 250ms": make_policy_confirm(250),
}


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

def _newest_trace() -> Path:
    if not TRACE_DIR.is_dir():
        raise SystemExit(f"No traces in {TRACE_DIR}")
    # `_summary.json` files also start with `trace_`; picking one up produces a
    # KeyError on 'transitions' that reads like a corrupt trace.
    files = sorted(p for p in TRACE_DIR.glob("trace_*.json")
                   if not p.name.endswith("_summary.json"))
    if not files:
        raise SystemExit(f"No traces in {TRACE_DIR}")
    return files[-1]


def analyze(args) -> dict:
    path = Path(args.trace) if args.trace else _newest_trace()
    data = json.loads(path.read_text(encoding="utf-8"))
    trans = [t for t in data["transitions"] if not t.get("error")]
    if not trans:
        raise SystemExit(f"{path} has no usable transitions")

    print(f"\n=== {path.name} ===")
    print(f"overlay={data.get('overlay')}  repeats={data.get('repeats')}  "
          f"cpu={data.get('cpu_rates')}  n={len(trans)}\n")

    rows = []
    for t in trans:
        m = t.get("metrics") or metrics(t)
        rows.append({"id": t["id"], "group": t["group"], "cpu": t["cpu"], **m})

    # ---- per-scenario summary
    hdr = (f"{'scenario':<16}{'cpu':>4} {'n':>3} {'settle':>8}{'script':>8}"
           f"{'ready':>8}{'ovHide':>8}{'waste':>8}{'muts':>6}{'dH':>7}{'dN':>7}")
    print(hdr)
    print("-" * len(hdr))
    by = {}
    for r in rows:
        by.setdefault((r["id"], r["cpu"]), []).append(r)
    for (sid, cpu), rs in sorted(by.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        def med(k):
            v = [x[k] for x in rs if x.get(k) is not None]
            return statistics.median(v) if v else None
        print(f"{sid:<16}{cpu:>4} {len(rs):>3} "
              f"{_f(med('t_settle'))}{_f(med('t_script_done'))}"
              f"{_f(med('t_ready_stable'))}{_f(med('t_ov_hide'))}"
              f"{_f(med('overlay_waste'))}{med('mutation_batches') or 0:>6.0f}"
              f"{med('d_scrollheight') or 0:>7.0f}{med('d_elements') or 0:>7.0f}")

    # ---- baseline + relative
    settles = [r["t_settle"] for r in rows if r.get("t_settle") is not None]
    if settles:
        base = statistics.mean(settles)
        print(f"\nBASELINE  mean settle = {base:.0f} ms   "
              f"median = {statistics.median(settles):.0f} ms   "
              f"min = {min(settles):.0f}   max = {max(settles):.0f}")
        print("\nrelative to baseline (median settle per scenario):")
        for (sid, cpu), rs in sorted(
                by.items(), key=lambda kv: statistics.median(
                    [x["t_settle"] for x in kv[1]])):
            m = statistics.median([x["t_settle"] for x in rs])
            print(f"  {sid:<16} cpu={cpu:<4} {m:7.0f} ms   {m / base:5.2f}x baseline")

    wastes = [r["overlay_waste"] for r in rows if r.get("overlay_waste") is not None]
    if wastes:
        print(f"\nOVERLAY WASTE (hide - visual settle): mean {statistics.mean(wastes):.0f} ms   "
              f"median {statistics.median(wastes):.0f}   min {min(wastes):.0f}   max {max(wastes):.0f}")

    # ---- no-visual-change transitions
    flat = [r for r in rows if r.get("visual_delta") == 0]
    if flat:
        print(f"\nTRANSITIONS WITH NO VISUAL CHANGE AT ALL: "
              f"{sorted({r['id'] for r in flat})}")

    # ---- the redundancy check
    tautology = [r for r in rows if r.get("stale_while_not_running")]
    print(f"\nstale-while-not-running frames seen in {len(tautology)}/{len(rows)} "
          f"transitions "
          f"({'the stale gate adds information' if tautology else 'the stale gate is REDUNDANT with the script-state gate'})")

    # ---- policy replay
    print("\nPOLICY REPLAY  (median hide time / worst exposure across all transitions)")
    print(f"  {'policy':<24}{'median':>9}{'mean':>9}{'p95':>9}{'exposed':>9}{'worstExp':>10}")
    for name, pol in POLICIES.items():
        res = [replay(t, pol) for t in trans]
        ok = [r for r in res if r.get("t_hide") is not None]
        if not ok:
            print(f"  {name:<24}    never fired")
            continue
        hs = sorted(r["t_hide"] for r in ok)
        exp = [r for r in ok if r["exposed"]]
        worst = max((r["exposed_ms"] for r in ok), default=0)
        p95 = hs[min(len(hs) - 1, int(len(hs) * 0.95))]
        print(f"  {name:<24}{statistics.median(hs):9.0f}{statistics.mean(hs):9.0f}"
              f"{p95:9.0f}{len(exp):>6}/{len(ok):<3}{worst:10.0f}")

    out = TRACE_DIR / (path.stem + "_summary.json")
    out.write_text(json.dumps({"trace": str(path), "rows": rows}, indent=1),
                   encoding="utf-8")
    print(f"\nrows written to {out}")
    return {"rows": len(rows)}


# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="drive navigations and record traces")
    r.add_argument("--scenarios", default="all",
                   help=f"comma list of ids or groups {GROUPS}, or 'all'")
    r.add_argument("--repeats", type=int, default=3)
    r.add_argument("--cpu", default="",
                   help="comma list of CDP CPU throttling rates, e.g. 1,4,6")
    r.add_argument("--overlay", choices=("neutralized", "live"),
                   default="neutralized",
                   help="neutralized: CSS-hide #_cdOv but keep its JS running")
    r.add_argument("--screencast", action="store_true",
                   help="also record real pixels via CDP (slower, authoritative)")
    r.add_argument("--quiet-ms", type=float, default=700)
    r.add_argument("--max-seconds", type=float, default=20)
    r.set_defaults(func=record)

    a = sub.add_parser("analyze", help="summarise a trace and replay policies")
    a.add_argument("--trace", default="")
    a.set_defaults(func=analyze)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
