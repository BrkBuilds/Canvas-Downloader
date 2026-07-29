"""
patch_streamlit_boot.py
=======================

Inject a **boot overlay** into Streamlit's bundled ``static/index.html`` so the
app window never shows an empty page between the launcher splash and the first
painted frame of the UI.

Why this exists
---------------
``start.py`` shows a splash in the pywebview window, then calls ``load_url()``
the moment ``/_stcore/health`` answers 200.  Health is true as soon as tornado
*binds* - which is long before anything is on screen.  Measured on a warm dev
machine (source build, fast network), from ``load_url()``::

    +0.0s  splash torn down, document blank            <- black screen starts
    +2.9s  7 MB JS bundle parsed, React mounts         <- still blank
    +6.9s  first app content paints                    <- black screen ends

Nearly seven seconds of empty window, and that is the *best* case: a cold
first launch (Microsoft Store / fresh install) pays uncached reads of a 474 MB
program directory plus a first-run Defender scan for every DLL, which is where
the reported 10-20s comes from.

Streamlit's ``index.html`` cannot help: ``<body>`` holds nothing but an empty
``<div id="root">`` and carries no background colour, so the window paints the
WebView's background until React has mounted AND the websocket session has
delivered the first script run's elements.

The fix is to make the destination page paint the splash **itself**, from its
first byte.  The overlay is a sibling of ``#root`` (React never touches it),
byte-identical in look to the launcher splash, so the hand-off between the two
documents is invisible.  It removes itself once the app has actually rendered.

Why patch Streamlit instead of owning the page
----------------------------------------------
There is no supported hook for a custom ``index.html``, and every alternative
is worse: pywebview cannot inject a script *before* document creation, and
wrapping the app in an iframe of our own page changes the document topology the
whole UI is built on (``window.parent`` bridges, the ``stDialog`` portal, focus
and native dialogs).  Patching one static file at build time is the smallest
change with the strongest guarantee - and it is the same mechanism the app
already uses for ``patch_streamlit_webkit.py``.

Behaviour of the injected overlay
---------------------------------
* Four **honest** stage labels, each driven by an observable DOM fact - never a
  timer pretending to be progress:
      1. "Starting Canvas Downloader…"  document parsed, bundle loading
      2. "Loading interface…"           React mounted (``#root`` has children)
      3. "Connecting…"                  app shell present, script running
      4. "Almost ready…"                first content painted, settling
* Hides when the app is **genuinely ready**: real content in ``stMain`` *and*
  ``window.prerenderReady`` (Streamlit sets it when the first script run
  finishes - it survives ``st.stop()`` and any ``st.rerun()`` chain) plus one
  stable geometry sample.
* Two escape hatches so it can never trap the user: 5 s after content first
  appears it reveals anyway (a startup that goes straight into a long-running
  operation - e.g. the daily auto-sync - keeps the script RUNNING forever, and
  the app's own live progress UI is the right thing to show), and a 30 s
  absolute cap.

Run this AFTER ``pip install`` and BEFORE PyInstaller collects Streamlit.  It is
invoked automatically from both .spec files; it can also be run standalone::

    python scripts/patch_streamlit_boot.py
"""
from __future__ import annotations

import base64
import os
import sys

# Markers delimit the injected block so a re-run replaces it instead of stacking
# copies (the build runs this on every invocation, and site-packages persists).
BEGIN = "<!--CD-BOOT-OVERLAY-->"
END = "<!--/CD-BOOT-OVERLAY-->"

# Must match start.py's splash exactly - the two documents hand over to each
# other and any difference shows up as a flicker at the swap.
BG = "#0d1117"            # theme.BG_TERMINAL
ACCENT = "#0072CE"        # theme.primaryColor
LOGO_TINT = "rgba(0,114,206,0.18)"
LABEL_COLOR = "rgba(255,255,255,0.55)"
TRACK_COLOR = "rgba(255,255,255,0.08)"
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"

# Fallback mark, used when assets/icon.png cannot be read - identical to the
# fallback start.py draws in the same situation.
_FALLBACK_LOGO = (
    "<svg viewBox='0 0 24 24' fill='none' stroke='" + ACCENT + "' stroke-width='2' "
    "stroke-linecap='round' stroke-linejoin='round' style='width:36px;height:36px'>"
    "<path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/>"
    "<polyline points='7 10 12 15 17 10'/>"
    "<line x1='12' y1='15' x2='12' y2='3'/></svg>"
)


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _logo_markup(project_root: str) -> str:
    """Inline the app icon as a data URI (42 KB -> 56 KB of base64).

    A data URI rather than a second HTTP request: the icon must be on screen in
    the overlay's very first paint, and a separate fetch would pop it in a frame
    or two later - visible as the logo tile filling in after the swap.
    """
    try:
        with open(os.path.join(project_root, "assets", "icon.png"), "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return ("<img src=\"data:image/png;base64," + b64 + "\" alt=\"\" "
                "style=\"width:36px;height:36px\">")
    except Exception as exc:  # noqa: BLE001 - never fail a build over the icon
        print(f"[patch_streamlit_boot] icon.png unavailable ({exc}); using vector mark")
        return _FALLBACK_LOGO


def _payload(project_root: str) -> str:
    logo = _logo_markup(project_root)
    return (
        BEGIN
        + "<style id=\"cd-boot-style\">"
        "body{background:" + BG + "}"
        # The failsafe animation is the one guarantee that does not depend on
        # the script below ever running: a parse error on an old WebKit engine,
        # a CSP, anything - after 45s the overlay fades out and stops taking
        # hits, so the worst case is a slow launch, never an app you cannot
        # click. The delay means it contributes nothing on the normal path (no
        # fill during the delay), where the node is removed after a few seconds.
        "#cd-boot{position:fixed;top:0;left:0;right:0;bottom:0;z-index:2147483000;"
        "background:" + BG + ";display:flex;flex-direction:column;align-items:center;"
        "justify-content:center;gap:28px;font-family:" + FONT + ";"
        "transition:opacity .22s ease;"
        "animation:cd-boot-failsafe .4s linear 45s forwards}"
        "@keyframes cd-boot-failsafe{to{opacity:0;visibility:hidden}}"
        "#cd-boot .cd-boot-logo{width:64px;height:64px;background:" + LOGO_TINT + ";"
        "border-radius:16px;display:flex;align-items:center;justify-content:center}"
        # font-size in px and an explicit line-height: this label sits in a
        # document whose stylesheet we do not own, and it has to render at the
        # same size as the launcher splash's - a rem here would follow whatever
        # root size Streamlit's theme sets, and an inherited line-height would
        # change the label's box height and shift the spinner at the hand-off.
        "#cd-boot .cd-boot-label{font-size:16.8px;line-height:normal;font-weight:600;"
        "color:" + LABEL_COLOR + ";"
        "letter-spacing:0.01em;transition:opacity .14s ease;text-align:center;padding:0 24px}"
        "#cd-boot .cd-boot-spinner{width:36px;height:36px;border:3px solid " + TRACK_COLOR + ";"
        "border-top-color:" + ACCENT + ";border-radius:50%;animation:cd-boot-spin .8s linear infinite}"
        "@keyframes cd-boot-spin{to{transform:rotate(360deg)}}"
        "</style>"
        "<div id=\"cd-boot\">"
        "<div class=\"cd-boot-logo\">" + logo + "</div>"
        "<div class=\"cd-boot-label\" id=\"cd-boot-label\">Starting Canvas Downloader…</div>"
        "<div class=\"cd-boot-spinner\"></div>"
        "</div>"
        "<script>" + _SCRIPT + "</script>"
        + END
    )


# Kept as its own constant so the JS stays readable and can be linted by eye.
# NOTE: no "{" may be immediately followed by another "{" anywhere in this
# payload - tornado renders index.html through its template engine on the 404
# path, and "{{" is a template expression opener. _assert_template_safe() below
# enforces it.
_SCRIPT = """
(function(){
  var doc = document;
  var ov = doc.getElementById('cd-boot');
  if (!ov) { return; }
  var lab = doc.getElementById('cd-boot-label');
  var STAGES = [
    'Starting Canvas Downloader\\u2026',
    'Loading interface\\u2026',
    'Connecting\\u2026',
    'Almost ready\\u2026'
  ];
  var t0 = Date.now();
  var tContent = 0;
  var stage = 0;
  var done = false;
  var fp = null;
  var stable = 0;

  function setStage(i) {
    if (done || i <= stage) { return; }
    stage = i;
    if (!lab) { return; }
    lab.style.opacity = '0';
    setTimeout(function () {
      if (done) { return; }
      lab.textContent = STAGES[i];
      lab.style.opacity = '1';
    }, 140);
  }

  // Real content = an element container in the main area with actual height.
  // Style-only injections render a zero-height container, so they cannot be
  // mistaken for a painted page (the app emits several before any content).
  function hasContent() {
    var els = doc.querySelectorAll('[data-testid="stMain"] [data-testid="stElementContainer"]');
    for (var i = 0; i < els.length; i++) {
      if (els[i].getBoundingClientRect().height > 8) { return true; }
    }
    return false;
  }

  function fingerprint() {
    var m = doc.querySelector('[data-testid="stMain"]');
    if (!m) { return ''; }
    return m.scrollHeight + '|' + m.querySelectorAll('*').length
         + '|' + (doc.querySelector('[data-testid="stSidebar"]') ? 1 : 0);
  }

  function finish() {
    if (done) { return; }
    done = true;
    ov.style.opacity = '0';
    setTimeout(function () {
      var s = doc.getElementById('cd-boot-style');
      if (s && s.parentNode) { s.parentNode.removeChild(s); }
      if (ov.parentNode) { ov.parentNode.removeChild(ov); }
    }, 260);
  }

  function tick() {
    if (done) { return; }
    var now = Date.now();
    if (now - t0 > 30000) { finish(); return; }          // absolute safety cap

    var root = doc.getElementById('root');
    if (root && root.childElementCount > 0) { setStage(1); }
    if (doc.querySelector('[data-testid="stApp"]')) { setStage(2); }

    if (hasContent()) {
      if (!tContent) { tContent = now; }
      setStage(3);
      var cur = fingerprint();
      if (cur === fp) { stable++; } else { fp = cur; stable = 0; }
      // Normal path: the script run has finished and the page held still for a
      // frame.  Fallback: content has been up for 5s and the run is still going
      // (a launch that starts a sync immediately) - show it the live UI.
      if ((window.prerenderReady === true && stable >= 1) || now - tContent > 5000) {
        // Uncover after two painted frames so the last delta is on screen
        // first.  finish() is idempotent and also armed on a timer: rAF does
        // not fire while the window is occluded/minimised, and a stalled
        // callback must never leave the overlay up.
        setTimeout(finish, 1000);
        requestAnimationFrame(function () { requestAnimationFrame(finish); });
        return;
      }
    }
    setTimeout(tick, 160);
  }

  tick();
})();
"""


def _assert_template_safe(payload: str) -> None:
    """index.html is passed through tornado's template engine on the 404 path."""
    for opener in ("{{", "{%", "{#"):
        if opener in payload:
            raise RuntimeError(
                f"patch_streamlit_boot: payload contains tornado template opener {opener!r}"
            )


def _index_html_path() -> str:
    import streamlit  # noqa: WPS433 (deliberately lazy - only when patching)

    return os.path.join(os.path.dirname(streamlit.__file__), "static", "index.html")


def strip(text: str) -> str:
    """Remove any previously injected block(s). Idempotent, safe on clean input."""
    while BEGIN in text and END in text:
        start = text.index(BEGIN)
        end = text.index(END, start) + len(END)
        text = text[:start] + text[end:]
    return text


def inject(html: str, project_root: str | None = None) -> str:
    """Return ``html`` with exactly one boot-overlay block in it.

    Pure function - all the I/O lives in :func:`patch`. Re-injecting is safe:
    any previous block is stripped first, so a rebuild replaces the payload
    instead of stacking copies.
    """
    text = strip(html)
    if "<body>" not in text:
        raise ValueError("no <body> tag in index.html")
    payload = _payload(project_root or _project_root())
    _assert_template_safe(payload)
    # Immediately after <body> so the overlay is the document's first paint.
    return text.replace("<body>", "<body>" + payload, 1)


def patch(project_root: str | None = None) -> bool:
    """Inject the boot overlay into Streamlit's index.html. Returns True if written."""
    path = _index_html_path()
    if not os.path.isfile(path):
        print(f"[patch_streamlit_boot] index.html not found: {path} - skipping")
        return False

    with open(path, "r", encoding="utf-8") as f:
        original = f.read()

    try:
        patched = inject(original, project_root)
    except ValueError as exc:
        print(f"[patch_streamlit_boot] WARNING: {exc} - skipping "
              "(the app still runs; startup will show a blank window)")
        return False

    if patched == original:
        print("[patch_streamlit_boot] already up to date")
        return False

    with open(path, "w", encoding="utf-8") as f:
        f.write(patched)

    # Verify what actually landed on disk rather than trusting the write.
    with open(path, "r", encoding="utf-8") as f:
        check = f.read()
    if BEGIN not in check or 'id="cd-boot"' not in check or "</body>" not in check:
        raise RuntimeError("patch_streamlit_boot: verification failed after write")

    print(f"[patch_streamlit_boot] boot overlay injected into {path} "
          f"(+{len(patched) - len(strip(original))} bytes)")
    return True


if __name__ == "__main__":
    try:
        patch()
    except Exception as exc:  # noqa: BLE001 - surface a clear CI failure
        print(f"[patch_streamlit_boot] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
