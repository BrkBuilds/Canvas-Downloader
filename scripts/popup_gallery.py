"""Render every state of the browser extension's popup, light and dark.

    python scripts/popup_gallery.py                 # -> packaging/chrome-web-store/screens
    python scripts/popup_gallery.py <out-dir>

WHY THIS EXISTS
---------------
The popup is a state machine with twelve reachable screens and no way to reach
most of them by hand: they depend on whether the app is running, whether it is
asking for a sign-in, whether Chrome has granted the site, and what Canvas
answered. Reading the code tells you what each one SAYS. It does not tell you
what the screen looks like, and every popup defect found on 2026-09-14 came
off this sheet rather than out of the source:

* "Finishing up in 5" rendered on EVERY screen, because `.countdown` carried a
  `display` that beat the `hidden` attribute. Invisible in review, obvious in a
  screenshot, and it was the first thing a Web Store reviewer would have seen.
* the finished screen still claims "Running, ready to log in" in its state row.

Only the `chrome.*` APIs are stubbed. The markup, the CSS and every decision in
`popup.js` are the shipped files, served over HTTP so the ES-module import of
`canvas-hosts.js` resolves. Same discipline as `scripts/completion_gallery.py`:
drive the real thing, then look at it.
"""

from __future__ import annotations


import http.server
import json
import shutil
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXT = REPO / "extension"
DEFAULT_OUT = REPO / "packaging" / "chrome-web-store" / "screens"

CANVAS_TAB = {"url": "https://cbscanvas.instructure.com/courses/1", "active": True}
OTHER_TAB = {"url": "https://www.google.com/search?q=x", "active": True}
LONG_URL_TAB = {"url": "https://learning-portal-very-long-subdomain-name.some-other-institution-domain.edu/students/portal/login", "active": True}
SYSTEM_TAB = {"url": "chrome://newtab/", "active": True}

APP_OFF = None
APP_IDLE = {"port": 53127, "waiting": False}
APP_READY = {"port": 53127, "waiting": True}
REMEMBERED = {"signedIn": {"host": "cbscanvas.instructure.com", "at": 1}}

#: name -> (what it is, scenario, action)
#: The NAME is the deliverable: somebody redesigning this has to be able to
#: pick the screen they mean out of a folder without opening every file.
SCENES = {
    "01_guide_app-off_not-a-web-page": (
        "System tab, app not reachable: open your Canvas page first",
        {"app": APP_OFF, "tab": SYSTEM_TAB}, None),
    "02_guide_app-off_wrong-site": (
        "An ordinary site, app not reachable: this does not look like Canvas",
        {"app": APP_OFF, "tab": OTHER_TAB}, None),
    "02b_guide_wrong-site_long-url": (
        "Long URL, app not reachable: check URL pill wrapping",
        {"app": APP_OFF, "tab": LONG_URL_TAB}, None),
    "03_guide_app-off_on-canvas": (
        "On Canvas, app not reachable: open Canvas Downloader",
        {"app": APP_OFF, "tab": CANVAS_TAB}, None),
    "04_guide_app-running_not-asking-yet": (
        "On Canvas, app running but no sign-in asked for: nearly there",
        {"app": APP_IDLE, "tab": CANVAS_TAB}, None),
    "05_guide_ready_needs-chrome-permission": (
        "Ready, Chrome has not granted this site yet: one-time approval",
        {"app": APP_READY, "tab": CANVAS_TAB, "perm": False}, None),
    "06_guide_ready_to-sign-in": (
        "Ready and granted: the one click that does it",
        {"app": APP_READY, "tab": CANVAS_TAB, "perm": True}, None),
    "07_signing-in": (
        "Mid sign-in, spinner",
        {"app": APP_READY, "tab": CANVAS_TAB, "perm": True, "connectDelay": 60000},
        "click-hold"),
    "08_failed_tab-not-signed-in": (
        "Failure: that Canvas tab is not signed in",
        {"app": APP_READY, "tab": CANVAS_TAB, "perm": True,
         "connect": {"ok": False, "code": "not_signed_in"}}, "click"),
    "09_failed_app-unreachable": (
        "Failure: the app could not be reached",
        {"app": APP_READY, "tab": CANVAS_TAB, "perm": True,
         "connect": {"ok": False, "code": "unreachable"}}, "click"),
    "10_success_countdown": (
        "Signed in, counting down to the resting screen",
        {"app": APP_READY, "tab": CANVAS_TAB, "perm": True,
         "connect": {"ok": True, "host": "cbscanvas.instructure.com"}}, "click"),
    "11_resting_signed-in_app-closed": (
        "Nothing to do: signed in earlier, app not answering now",
        {"app": APP_OFF, "tab": CANVAS_TAB, "storage": REMEMBERED}, None),
    "12_resting_signed-in_app-running": (
        "Nothing to do: signed in earlier, app answering",
        {"app": APP_IDLE, "tab": CANVAS_TAB, "storage": REMEMBERED}, None),
}

#: The chrome.* surface the popup uses, and nothing else. The scenario arrives
#: in the URL fragment so one build serves every screen.
STUB = r"""
(() => {
  const S = JSON.parse(decodeURIComponent(location.hash.slice(1) || '%7B%7D'));
  let statusCalls = 0;
  window.chrome = {
    runtime: {
      lastError: undefined,
      sendMessage(msg, cb) {
        const reply = (v, ms) => setTimeout(() => cb(v), ms || 15);
        if (msg.type === 'status') { statusCalls += 1; return reply({ app: S.app }); }
        if (msg.type === 'connect') return reply(S.connect || { ok: true, host: 'x' },
                                                 S.connectDelay || 30);
        return reply({ ok: true });
      },
    },
    storage: { session: {
      get: async (k) => ({ [k]: (S.storage || {})[k] }),
      set: async () => {}, remove: async () => {},
    } },
    tabs: { query: async () => [S.tab] },
    permissions: { contains: async () => !!S.perm, request: async () => true },
  };
})();
"""


def _serve(root: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a):
            pass                               # one line per asset, per screen

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _sheet(paths, dest, cols=4):
    from PIL import Image, ImageDraw
    ims = [Image.open(p) for p in paths]
    w = max(i.width for i in ims)
    h = max(i.height for i in ims)
    canvas = Image.new("RGB", (cols * (w + 16) + 16,
                               ((len(ims) + cols - 1) // cols) * (h + 40) + 16),
                       (120, 120, 120))
    d = ImageDraw.Draw(canvas)
    for n, (p, im) in enumerate(zip(paths, ims)):
        x = 16 + (n % cols) * (w + 16)
        y = 16 + (n // cols) * (h + 40)
        d.text((x + 2, y + 2), Path(p).stem, fill=(255, 255, 255))
        canvas.paste(im, (x, y + 22))
    canvas.save(dest)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out = Path(argv[0]).resolve() if argv else DEFAULT_OUT
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed: pip install playwright && playwright install chromium")
        return 2

    if out.exists():
        shutil.rmtree(out)
    srv = _serve(EXT)
    base = f"http://127.0.0.1:{srv.server_address[1]}/popup.html"
    manifest = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for scheme in ("light", "dark"):
                (out / scheme).mkdir(parents=True, exist_ok=True)
                shots = []
                for name, (what, scene, action) in SCENES.items():
                    ctx = browser.new_context(viewport={"width": 340, "height": 640},
                                              device_scale_factor=2,
                                              color_scheme=scheme)
                    ctx.add_init_script(STUB)
                    page = ctx.new_page()
                    problems = []
                    page.on("pageerror", lambda e: problems.append(str(e)))
                    page.goto(base + "#" + json.dumps(scene))
                    page.wait_for_timeout(400)
                    if action:
                        page.click("#go")
                        page.wait_for_timeout(1600 if action == "click" and
                                              name.startswith("10") else 300)
                    # Crop to the popup's OWN height: a fixed viewport leaves a
                    # slab of empty page under short screens, which reads as
                    # part of the design when somebody reviews the folder.
                    height = page.evaluate("() => Math.ceil(document.body.getBoundingClientRect().bottom) + 14")
                    page.set_viewport_size({"width": 340, "height": int(height)})
                    dest = out / scheme / f"{name}.png"
                    page.screenshot(path=str(dest))
                    shots.append(dest)
                    if scheme == "light":
                        manifest.append((name, what))
                    if problems:
                        print(f"  PAGE ERROR in {scheme}/{name}: {problems}")
                    ctx.close()
                _sheet(shots, out / f"_all_{scheme}.png")
            browser.close()
    finally:
        srv.shutdown()

    lines = ["Extension popup, every reachable screen.",
             "Rendered by scripts/popup_gallery.py from the real popup.html and popup.js.",
             "", "light/ and dark/ hold the same twelve screens; _all_*.png are contact sheets.",
             ""]
    lines += [f"{name}\n    {what}" for name, what in manifest]
    (out / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(manifest)} screens x 2 themes -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
