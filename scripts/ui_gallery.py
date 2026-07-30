"""Render every state of a Streamlit surface, screenshot each, review the lot.

A *surface* is a screen whose appearance is a combination of optional parts -
completion screens, a review screen, a settings dialog. The states that matter
are combinations, most of them unreachable on demand because each needs a
specific outcome (a locked file, an exhausted retry, a cancelled pass). This
module drives a gallery page that renders them from mock state, captures each
one twice (as it appears, and with every collapsible open), and writes a
self-contained review page.

Two things it does that a naive screenshot script does not, both found by
measuring rather than reasoning - see the notes on `shoot` and `wait_settled`:

* it grows the VIEWPORT to the content before shooting, because Streamlit's
  `stMain` is the scroll container and Playwright's element screenshot scrolls
  the window - so anything below the fold was simply never painted;
* it waits for the app's startup overlay to leave, because the fastest screens
  settle while it is still fading and get shot through it.

To add a surface: build a gallery page (a Streamlit script keyed off a query
param), then hand this module a :class:`Surface`. Nothing here knows anything
about the completion screens - see ``scripts/capture_completion_gallery.py``
for the reference wiring.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import sync_playwright

# Streamlit's page-content wrapper. Every shot is cropped to this rather than to
# the viewport, so a short screen is not padded out with empty page and a long
# one is not cut off - which is what makes two states comparable side by side.
MAIN = 'div[data-testid="stMainBlockContainer"]'

# Opening a <details> covers almost everything; the extra selector is for the
# pure-CSS checkbox toggles this app uses for its filetype pills (see "CSS
# Checkbox Hack" in CLAUDE.md). Override per surface if yours differ.
DEFAULT_EXPAND_JS = """() => {
    let n = 0;
    document.querySelectorAll('details').forEach(d => {
        if (!d.open) { d.open = true; n++; }
    });
    document.querySelectorAll('input.ft-expand-toggle').forEach(c => {
        if (!c.checked) { c.checked = true; n++; }
    });
    return n;
}"""


@dataclass
class Surface:
    """Everything that differs between one reviewable surface and another."""

    name: str
    """Folder name under ui-review/, e.g. "completion-screens"."""

    title: str
    """Human title for the review page."""

    states: list[tuple[str, str, str]]
    """(id, title, what to look at) in the order they should be reviewed."""

    elements: list[tuple[str, str, str]]
    """(id, label, group) - the vocabulary a note can be filed against.

    This is the point of the whole tool: the states are combinations of these,
    so a note about an element is a note about every state containing it.
    """

    detect_js: str
    """JS returning the element ids present. MUST use `textContent`, not
    `innerText`: a closed <details> is not rendered, so innerText silently
    misses everything inside one."""

    url: str
    """URL template with {port} and {id}."""

    regenerate: str = ""
    """Command line that reproduces this capture, recorded in the export."""

    legacy_keys: list[str] = field(default_factory=list)
    """localStorage keys an earlier version of this page used. Read once, so a
    review already in progress survives a re-capture."""

    expand_js: str = DEFAULT_EXPAND_JS
    blurb: str = ""
    problems: list[str] = field(default_factory=list)


def wait_settled(page, timeout_ms: int = 20000) -> None:
    """Wait for real content, not a fixed sleep.

    Streamlit streams a page in element by element, so a sleep either wastes
    time on the small states or catches the big ones mid-stream. This polls
    until the container's height stops changing, then waits for every image.
    """
    page.wait_for_selector(MAIN, timeout=timeout_ms)
    # The startup overlay (scripts/patch_streamlit_boot.py patches it into
    # Streamlit's index.html in site-packages, so `streamlit run` shows it too)
    # sits above the page and fades out. Height alone settles before it does, so
    # the fastest screens were shot mid-fade with the spinner ghosted over the
    # card. It removes itself rather than just hiding, so absence is the signal.
    page.wait_for_function("() => !document.getElementById('cd-boot')",
                           timeout=timeout_ms)
    page.wait_for_function(
        """(sel) => {
            const el = document.querySelector(sel);
            if (!el) return false;
            const h = el.getBoundingClientRect().height;
            if (h < 40) return false;
            window.__cdPrev = window.__cdPrev || {};
            const same = window.__cdPrev.h === h ? (window.__cdPrev.n || 0) + 1 : 0;
            window.__cdPrev = {h, n: same};
            return same >= 3;
        }""",
        arg=MAIN, timeout=timeout_ms, polling=120,
    )
    # Icons are data: URIs so this resolves immediately once the markup is in -
    # but a broken one leaves complete===true with naturalWidth 0, which
    # `broken_images` then catches.
    page.wait_for_function(
        "() => Array.from(document.images).every(i => i.complete)",
        timeout=timeout_ms,
    )


def broken_images(page) -> list[str]:
    return page.evaluate(
        """() => Array.from(document.images)
              .filter(i => i.complete && i.naturalWidth === 0)
              .map(i => (i.getAttribute('src') || '').slice(0, 60))"""
    )


def shoot(page, target, path: Path, width: int) -> tuple[int, str | None]:
    """Size the viewport to the content, capture it, and prove nothing was cut.

    GROWING THE VIEWPORT IS THE WHOLE TRICK. `stMain` is the scroll container,
    not the window, and it clips at `overflow: auto`; Playwright's element
    screenshot scrolls the WINDOW, which moves nothing here. So anything below
    the fold was never painted and came out as a black band with a ghost of the
    sticky chrome at the bottom (measured on the completion surface: 1603px of
    element against ~620px of actual content).

    Returns (height, problem-or-None).
    """
    h = int(target.bounding_box()["height"])
    page.set_viewport_size({"width": width, "height": min(h + 160, 30000)})
    wait_settled(page)
    h = int(target.bounding_box()["height"])
    # Assert rather than assume: if the content still overflows its scroll
    # container the shot is missing the bottom, and the only sign is that it
    # looks fine.
    clipped = page.evaluate(
        """() => {
            const m = document.querySelector('[data-testid="stMain"]');
            if (!m) return null;
            const over = m.scrollHeight - m.clientHeight;
            return over > 2 ? over : null;
        }"""
    )
    target.screenshot(path=str(path))
    page.set_viewport_size({"width": width, "height": 1000})
    return h, (f"clipped: {clipped}px still below the fold" if clipped else None)


def capture(surface: Surface, out: Path, port: int, width: int = 1500,
            scale: int = 2) -> int:
    """Capture every state of `surface` into `out`. Returns a process exit code."""
    out.mkdir(parents=True, exist_ok=True)
    known = {i for i, _, _ in surface.elements}
    shots: list[dict] = []
    problems: list[str] = list(surface.problems)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 1000},
                                device_scale_factor=scale)
        for sid, title, why in surface.states:
            page.goto(surface.url.format(port=port, id=sid),
                      wait_until="domcontentloaded")
            try:
                wait_settled(page)
            except Exception as exc:                       # noqa: BLE001
                problems.append(f"{sid}: did not settle - {exc}")
            broken = broken_images(page)
            if broken:
                problems.append(f"{sid}: broken image src {broken}")

            target = page.locator(MAIN)
            h, clip = shoot(page, target, out / f"{sid}.png", width)
            if clip:
                problems.append(f"{sid}: {clip}")

            # Second view with everything open. Skipped when nothing was shut -
            # an identical duplicate is just noise in the review page.
            opened = page.evaluate(surface.expand_js)
            eh = None
            if opened:
                eh, clip = shoot(page, target, out / f"{sid}--open.png", width)
                if clip:
                    problems.append(f"{sid}--open: {clip}")

            # AFTER expanding, so a probe can never miss something merely shut.
            els = page.evaluate(surface.detect_js)
            unknown = [e for e in els if e not in known]
            if unknown:
                problems.append(f"{sid}: detector returned unknown ids {unknown}")
            if not els:
                problems.append(f"{sid}: no elements detected")

            shots.append({"id": sid, "title": title, "why": why, "h": h,
                          "eh": eh, "opened": opened, "elements": els})
            extra = f"  +{opened} opened -> {eh}px" if opened else ""
            print(f"  {sid:24s} {h:5d}px  {len(els):2d} elements{extra}")

        browser.close()

    seen = {e for s in shots for e in s["elements"]}
    orphans = [i for i in known if i not in seen]
    if orphans:
        # A chip nothing carries is either a dead probe or a state the catalogue
        # is missing - both worth knowing, neither fatal.
        problems.append(f"elements never detected on any state: {sorted(orphans)}")

    (out / "index.html").write_text(review_page(surface, shots), encoding="utf-8")
    print(f"\n{len(shots)} states -> {out}")
    print(f"review page   -> {out / 'index.html'}")
    print(f"serve it      -> cd {out} && python -m http.server 8600")
    if problems:
        print("\nPROBLEMS")
        for p in problems:
            print("  " + p)
        return 1
    return 0


def review_page(surface: Surface, shots: list[dict]) -> str:
    """Build the standalone review tool.

    Self-contained on purpose: no CDN, no build step. All state lives in
    localStorage under one key, and Export writes it out as Markdown + JSON so
    a review survives a re-capture.
    """
    payload = json.dumps({
        "generated": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "title": surface.title,
        "blurb": surface.blurb,
        "renders": f"ui-review/{surface.name}/<id>.png and <id>--open.png",
        "regenerate": surface.regenerate,
        "storeKey": f"cd-ui-review-{surface.name}-v1",
        "legacyKeys": surface.legacy_keys,
        "name": surface.name,
        "elements": [{"id": i, "label": l, "group": g}
                     for i, l, g in surface.elements],
        "screens": shots,
    }, indent=1)
    return (_PAGE
            .replace("__TITLE__", surface.title)
            .replace("/*__DATA__*/null", payload))


_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>__TITLE__ &middot; review</title>
<style>
:root{color-scheme:dark;--bg:#0e1117;--panel:#161b22;--line:#30363d;--line2:#21262d;
      --txt:#e2e8f0;--dim:#8b949e;--dim2:#6b7280;--accent:#4da8da;--amber:#fbbf24;
      --green:#4ade80;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
     font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
button{font:inherit;cursor:pointer;border-radius:6px;border:1px solid var(--line);
       background:#1c2128;color:var(--txt);padding:6px 12px}
button:hover{border-color:var(--accent);color:#fff}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
button.primary:hover{filter:brightness(1.1)}
textarea{width:100%;background:#0d1117;color:var(--txt);border:1px solid var(--line);
         border-radius:6px;padding:9px 11px;font:inherit;resize:vertical}
textarea:focus{outline:none;border-color:var(--accent)}
code{color:#9ca3af;font-size:.85em}

/* ---------- top bar ---------- */
#bar{position:sticky;top:0;z-index:30;background:rgba(14,17,23,.94);
     backdrop-filter:blur(8px);border-bottom:1px solid var(--line);
     display:flex;align-items:center;gap:14px;padding:10px 24px;flex-wrap:wrap}
#bar .t{font-weight:700}
#bar .sp{flex:1}
#prog{color:var(--dim);font-size:.85rem;white-space:nowrap}
#saved{font-size:.78rem;color:var(--dim2);min-width:96px}
.filters{display:flex;gap:4px}
.filters button{padding:4px 10px;font-size:.82rem}
.filters button[aria-pressed="true"]{border-color:var(--accent);color:#fff;background:#12283a}

/* ---------- layout ---------- */
header.intro{padding:26px 24px 6px;max-width:96ch}
header.intro h1{margin:0 0 6px;font-size:1.5rem}
header.intro p{margin:0 0 6px;color:var(--dim)}
#overview{padding:6px 24px 20px;border-bottom:1px solid var(--line)}
#overview h3{margin:12px 0 8px;font-size:.78rem;letter-spacing:.7px;
             text-transform:uppercase;color:var(--dim2)}
#ovchips{display:flex;flex-wrap:wrap;gap:6px}
nav{display:flex;flex-wrap:wrap;gap:5px;padding:14px 24px;border-bottom:1px solid var(--line)}
nav a{color:var(--dim);text-decoration:none;font-size:.78rem;border:1px solid var(--line2);
      border-radius:6px;padding:3px 8px}
nav a:hover{color:#fff;border-color:var(--accent)}
nav a.done{color:#2f6f4a;border-color:#1e3a2a}
nav a.noted{color:var(--amber);border-color:#5a4213}

section{padding:30px 24px;border-bottom:1px solid var(--line2);scroll-margin-top:56px}
section.hide{display:none}
section.reviewed{background:linear-gradient(90deg,rgba(34,197,94,.05),transparent 40%)}
.shead{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
.shead h2{margin:0;font-size:1.12rem;color:#fff}
.sid{color:var(--dim2);font-size:.8rem}
.why{margin:4px 0 12px;color:#b1bac4;max-width:82ch}
.rev{margin-left:auto;display:inline-flex;align-items:center;gap:6px;
     color:var(--dim);font-size:.82rem;cursor:pointer;user-select:none}

/* ---------- chips ---------- */
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:.78rem;
      border:1px solid var(--line2);border-radius:20px;padding:3px 11px;
      background:#12161d;color:var(--dim);cursor:pointer}
.chip:hover{border-color:var(--accent);color:#fff}
.chip[data-n]:not([data-n="0"]){border-color:#5a4213;background:#211a09;color:var(--amber)}
.chip[aria-expanded="true"]{border-color:var(--accent);color:#fff;background:#12283a}
.chip .n{background:rgba(255,255,255,.12);border-radius:9px;padding:0 6px;
         font-size:.72rem;font-weight:700}
.chip.ov{cursor:default}
.chip.ov:hover{border-color:var(--line2);color:var(--dim)}
.chip.ov[data-n]:not([data-n="0"]):hover{color:var(--amber)}

/* ---------- notes ---------- */
.inherit{border:1px solid #5a4213;background:#1a1509;border-radius:8px;
         padding:10px 13px;margin:0 0 12px;font-size:.86rem}
.inherit b{color:var(--amber)}
.inherit ul{margin:7px 0 0;padding-left:18px;color:#d7ceb4}
.inherit li{margin:3px 0}
.inherit .src{color:var(--dim2);font-size:.78rem}
.pad{display:grid;gap:10px;margin:0 0 16px}
.elpanel{border:1px solid var(--line);border-radius:8px;padding:12px 14px;
         background:var(--panel);margin:0 0 12px}
.elpanel h4{margin:0 0 3px;font-size:.9rem;color:#fff}
.elpanel .sub{margin:0 0 10px;color:var(--dim2);font-size:.78rem}
.elpanel .row{display:flex;gap:8px;align-items:flex-start;margin:6px 0;
              border-top:1px solid var(--line2);padding-top:8px}
.elpanel .row p{margin:0;flex:1}
.elpanel .row .src{display:block;color:var(--dim2);font-size:.76rem;margin-top:2px}
.elpanel .add{display:flex;gap:8px;align-items:flex-start;margin-top:10px}
.elpanel .add textarea{flex:1}
.lbl{font-size:.78rem;letter-spacing:.5px;text-transform:uppercase;color:var(--dim2)}

/* ---------- images ---------- */
.views{display:grid;grid-template-columns:repeat(auto-fit,minmax(600px,1fr));
       gap:18px;align-items:start}
.view{min-width:0}
.tag{display:block;margin-bottom:6px;font-size:.72rem;letter-spacing:.6px;
     text-transform:uppercase;color:var(--dim2)}
img{display:block;width:100%;border:1px solid var(--line);border-radius:8px}
section:has(.cb:not(:checked)) .view.open{display:none}
section:has(.cb:not(:checked)) .views{grid-template-columns:1fr}
.none{color:#4b5563;font-style:italic;font-size:.82rem}
.sw{display:inline-flex;align-items:center;gap:6px;cursor:pointer;color:var(--dim);
    font-size:.82rem;user-select:none}
.meta{margin:0 0 12px;color:var(--dim2);font-size:.8rem;
      display:flex;align-items:center;gap:14px;flex-wrap:wrap}

/* ---------- export modal ---------- */
#modal{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:50;display:none;
       padding:40px 24px;overflow:auto}
#modal.on{display:block}
#modal .box{max-width:960px;margin:0 auto;background:var(--panel);
            border:1px solid var(--line);border-radius:12px;padding:20px 22px}
#modal h2{margin:0 0 4px;font-size:1.15rem}
#modal p{margin:0 0 12px;color:var(--dim);font-size:.86rem}
#modal textarea{height:52vh;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;
                font-size:.82rem}
#modal .acts{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
#warn{display:none;background:#3b1d1d;border-bottom:1px solid #7f1d1d;color:#fca5a5;
      padding:9px 24px;font-size:.86rem}
#warn.on{display:block}
</style></head><body>

<div id="warn"></div>
<div id="bar">
  <span class="t">__TITLE__</span>
  <span id="prog"></span>
  <span class="filters">
    <button data-f="all" aria-pressed="true">All</button>
    <button data-f="todo" aria-pressed="false">Not reviewed</button>
    <button data-f="noted" aria-pressed="false">Has notes</button>
    <button data-f="flagged" aria-pressed="false">Inherits notes</button>
  </span>
  <span class="sp"></span>
  <span id="saved"></span>
  <button id="import">Import</button>
  <button id="clear">Clear</button>
  <button id="export" class="primary">Export notes</button>
</div>

<header class="intro">
  <h1>__TITLE__ review</h1>
  <p id="blurb"></p>
  <p>Notes filed against an <b>element</b> follow that element onto every screen
  that contains it, so you only write it once. Notes typed into the box under a
  screen stay with that screen. Everything is saved as you type; press
  <b>Export notes</b> when you are done.</p>
</header>

<div id="overview">
  <h3>Elements &mdash; amber means a note already exists</h3>
  <div id="ovchips"></div>
</div>

<nav id="nav"></nav>
<main id="main"></main>

<div id="modal"><div class="box">
  <h2 id="mtitle">Export</h2>
  <p id="msub"></p>
  <textarea id="mtext" spellcheck="false"></textarea>
  <div class="acts">
    <button id="mcopy" class="primary">Copy to clipboard</button>
    <button id="mmd">Download .md</button>
    <button id="mjson">Download .json</button>
    <button id="mload" style="display:none">Load these notes</button>
    <button id="mclose">Close</button>
  </div>
</div></div>

<script>
const DATA = /*__DATA__*/null;
const KEY = DATA.storeKey;
const EL = new Map(DATA.elements.map(e => [e.id, e]));
const SCREENS = DATA.screens;
const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* ---------- store ---------- */
let DB = {screens:{}, elements:{}};
let canSave = true;
function load(){
  try{
    let raw = localStorage.getItem(KEY);
    if(!raw){
      // Keys an earlier version of this page wrote. Read once so notes taken
      // before a refactor are never silently orphaned; the next save writes
      // them back under the current key.
      for(const legacy of (DATA.legacyKeys || [])){
        raw = localStorage.getItem(legacy);
        if(raw) break;
      }
    }
    if(raw) DB = Object.assign({screens:{}, elements:{}}, JSON.parse(raw));
  }catch(e){
    canSave = false;
    const w = document.getElementById('warn');
    w.className = 'on';
    w.textContent = 'Notes cannot be saved in this browser context (localStorage '
      + 'is blocked on file:// URLs). Serve the folder instead - '
      + 'python -m http.server 8600 - or export before closing the tab.';
  }
}
let saveT = null;
function save(){
  if(!canSave) return;
  clearTimeout(saveT);
  saveT = setTimeout(() => {
    try{
      localStorage.setItem(KEY, JSON.stringify(DB));
      const s = document.getElementById('saved');
      s.textContent = 'saved ' + new Date().toLocaleTimeString();
    }catch(e){ canSave = false; }
  }, 250);
}
const scr = id => DB.screens[id] || (DB.screens[id] = {note:'', reviewed:false});
const notes = el => DB.elements[el] || [];

/* ---------- derived ---------- */
const screensWith = el => SCREENS.filter(s => s.elements.includes(el)).map(s => s.id);
function inherited(s){
  // Element notes that apply here but were written somewhere else. Notes
  // written ON this screen are not "inherited" - they are already in view.
  const out = [];
  for(const el of s.elements)
    for(const n of notes(el))
      if(n.screen !== s.id) out.push({el, ...n});
  return out;
}
function ownElementNotes(s){
  const out = [];
  for(const el of s.elements)
    for(const n of notes(el))
      if(n.screen === s.id) out.push({el, ...n});
  return out;
}
const hasOwn = s => !!(scr(s.id).note || '').trim() || ownElementNotes(s).length > 0;

/* ---------- render ---------- */
function build(){
  document.getElementById('blurb').innerHTML =
    SCREENS.length + ' states, ' + DATA.elements.length + ' shared elements. '
    + esc(DATA.blurb || '') + ' Captured ' + esc(DATA.generated) + '.';

  document.getElementById('nav').innerHTML = SCREENS.map(s =>
    '<a href="#' + s.id + '" data-nav="' + s.id + '">' + esc(s.title) + '</a>').join('');

  document.getElementById('main').innerHTML = SCREENS.map(s => {
    const views =
      '<div class="view"><span class="tag">collapsed &middot; ' + s.h + 'px</span>'
      + '<img src="' + s.id + '.png" alt="' + esc(s.title) + '" loading="lazy"/></div>'
      + (s.opened
        ? '<div class="view open"><span class="tag">expanded &middot; ' + s.eh
          + 'px</span><img src="' + s.id + '--open.png" alt="' + esc(s.title)
          + ' expanded" loading="lazy"/></div>'
        : '');
    const toggle = s.opened
      ? '<label class="sw"><input type="checkbox" class="cb" checked/> show expanded view</label>'
      : '<span class="none">nothing to expand</span>';
    return '<section id="' + s.id + '" data-s="' + s.id + '">'
      + '<div class="shead"><h2>' + esc(s.title) + '</h2>'
      + '<span class="sid"><code>?v=' + esc(s.id) + '</code></span>'
      + '<label class="rev"><input type="checkbox" data-rev="' + s.id
      + '"/> reviewed</label></div>'
      + '<p class="why">' + esc(s.why) + '</p>'
      + '<div class="meta">' + toggle + '</div>'
      + '<div class="inherit" data-inh="' + s.id + '"></div>'
      + '<div class="lbl" style="margin-bottom:5px">Elements on this screen &mdash; click one to note it everywhere</div>'
      + '<div class="chips" data-chips="' + s.id + '"></div>'
      + '<div class="elpanel" data-panel="' + s.id + '" style="display:none"></div>'
      + '<div class="pad"><textarea rows="2" data-note="' + s.id
      + '" placeholder="Note about THIS screen only (layout, ordering, copy specific to this combination)..."></textarea></div>'
      + '<div class="views">' + views + '</div></section>';
  }).join('');

  document.querySelectorAll('[data-note]').forEach(t => {
    t.value = scr(t.dataset.note).note || '';
    t.addEventListener('input', () => {
      scr(t.dataset.note).note = t.value; save(); paint();
    });
  });
  document.querySelectorAll('[data-rev]').forEach(c => {
    c.checked = !!scr(c.dataset.rev).reviewed;
    c.addEventListener('change', () => {
      scr(c.dataset.rev).reviewed = c.checked; save(); paint();
    });
  });
  paint();
}

let openPanel = {};   // screenId -> elementId currently expanded

function paint(){
  // Overview chips
  document.getElementById('ovchips').innerHTML = DATA.elements.map(e => {
    const n = notes(e.id).length, k = screensWith(e.id).length;
    return '<span class="chip ov" data-n="' + n + '" title="' + esc(e.group)
      + ' - on ' + k + ' screen' + (k===1?'':'s') + '">' + esc(e.label)
      + (n ? '<span class="n">' + n + '</span>' : '') + '</span>';
  }).join('');

  let done = 0, noted = 0;
  for(const s of SCREENS){
    const st = scr(s.id);
    if(st.reviewed) done++;
    if(hasOwn(s)) noted++;

    const sec = document.querySelector('section[data-s="' + s.id + '"]');
    sec.classList.toggle('reviewed', !!st.reviewed);

    // chips
    document.querySelector('[data-chips="' + s.id + '"]').innerHTML =
      s.elements.map(id => {
        const e = EL.get(id); if(!e) return '';
        const n = notes(id).length;
        return '<button class="chip" data-el="' + id + '" data-sc="' + s.id
          + '" data-n="' + n + '" aria-expanded="' + (openPanel[s.id]===id)
          + '" title="' + esc(e.group) + '">' + esc(e.label)
          + (n ? '<span class="n">' + n + '</span>' : '') + '</button>';
      }).join('');

    // inherited banner
    const inh = inherited(s);
    const box = document.querySelector('[data-inh="' + s.id + '"]');
    if(inh.length){
      box.style.display = '';
      box.innerHTML = '<b>' + inh.length + ' note' + (inh.length===1?'':'s')
        + ' written elsewhere already cover' + (inh.length===1?'s':'') + ' this screen.</b>'
        + '<ul>' + inh.map(n => '<li>' + esc(n.text)
          + ' <span class="src">&mdash; ' + esc(EL.get(n.el).label)
          + ', from ' + esc(n.screen) + '</span></li>').join('') + '</ul>';
    } else { box.style.display = 'none'; box.innerHTML = ''; }

    // element panel
    const panel = document.querySelector('[data-panel="' + s.id + '"]');
    const cur = openPanel[s.id];
    if(cur && s.elements.includes(cur)){
      const e = EL.get(cur), on = screensWith(cur);
      panel.style.display = '';
      panel.innerHTML = '<h4>' + esc(e.label) + '</h4>'
        + '<p class="sub">' + esc(e.group) + ' &middot; appears on ' + on.length
        + ' of ' + SCREENS.length + ' screens. A note here applies to all of them.</p>'
        + notes(cur).map((n,i) =>
            '<div class="row"><p>' + esc(n.text)
            + '<span class="src">written on ' + esc(n.screen) + ' &middot; '
            + esc(n.ts) + '</span></p>'
            + '<button data-del="' + cur + '" data-i="' + i + '">Delete</button></div>'
          ).join('')
        + '<div class="add"><textarea rows="2" data-eladd="' + cur
        + '" data-sc="' + s.id + '" placeholder="Note about the '
        + esc(e.label).toLowerCase() + ', on every screen that has it..."></textarea>'
        + '<button class="primary" data-elsave="' + cur + '" data-sc="' + s.id
        + '">Add</button></div>';
    } else { panel.style.display = 'none'; panel.innerHTML = ''; }
  }

  document.getElementById('prog').textContent =
    done + ' / ' + SCREENS.length + ' reviewed  ·  ' + noted + ' with notes';
  document.querySelectorAll('[data-nav]').forEach(a => {
    const s = SCREENS.find(x => x.id === a.dataset.nav);
    a.className = hasOwn(s) ? 'noted' : (scr(s.id).reviewed ? 'done' : '');
  });
  applyFilter();
}

/* ---------- events ---------- */
document.addEventListener('click', ev => {
  const chip = ev.target.closest('.chip[data-el]');
  if(chip){
    const s = chip.dataset.sc;
    openPanel[s] = openPanel[s] === chip.dataset.el ? null : chip.dataset.el;
    paint();
    return;
  }
  const add = ev.target.closest('[data-elsave]');
  if(add){
    const el = add.dataset.elsave;
    const ta = document.querySelector('[data-eladd="' + el + '"][data-sc="' + add.dataset.sc + '"]');
    const text = (ta.value || '').trim();
    if(!text) return;
    (DB.elements[el] = notes(el)).push(
      {text, screen: add.dataset.sc, ts: new Date().toISOString().slice(0,16).replace('T',' ')});
    ta.value = ''; save(); paint();
    return;
  }
  const del = ev.target.closest('[data-del]');
  if(del){
    DB.elements[del.dataset.del].splice(+del.dataset.i, 1);
    save(); paint();
  }
});

let filter = 'all';
document.querySelectorAll('.filters button').forEach(b =>
  b.addEventListener('click', () => {
    filter = b.dataset.f;
    document.querySelectorAll('.filters button').forEach(x =>
      x.setAttribute('aria-pressed', String(x === b)));
    applyFilter();
  }));
function applyFilter(){
  for(const s of SCREENS){
    const sec = document.querySelector('section[data-s="' + s.id + '"]');
    const show = filter === 'all' ? true
      : filter === 'todo' ? !scr(s.id).reviewed
      : filter === 'noted' ? hasOwn(s)
      : inherited(s).length > 0;
    sec.classList.toggle('hide', !show);
  }
}

/* ---------- export ---------- */
function markdown(){
  const L = [];
  L.push('# ' + DATA.title + ' review');
  L.push('');
  L.push('Captured ' + DATA.generated + ' · exported '
         + new Date().toISOString().slice(0,16).replace('T',' '));
  L.push('Renders: `' + DATA.renders + '`.');
  if(DATA.regenerate) L.push('Regenerate: `' + DATA.regenerate + '`');
  L.push('');

  const withNotes = DATA.elements.filter(e => notes(e.id).length);
  L.push('## Element notes');
  L.push('');
  if(!withNotes.length) L.push('_none_');
  for(const e of withNotes){
    const on = screensWith(e.id);
    L.push('### ' + e.label + '  `' + e.id + '`');
    L.push('');
    L.push('- Group: ' + e.group);
    L.push('- Applies to ' + on.length + ' screen' + (on.length===1?'':'s') + ': '
           + on.map(x => '`' + x + '`').join(', '));
    L.push('');
    for(const n of notes(e.id)) L.push('- ' + n.text + '  _(seen on `' + n.screen + '`)_');
    L.push('');
  }

  const perScreen = SCREENS.filter(s => (scr(s.id).note || '').trim());
  L.push('## Screen-specific notes');
  L.push('');
  if(!perScreen.length) L.push('_none_');
  for(const s of perScreen){
    L.push('### ' + s.title + '  `' + s.id + '`');
    L.push('');
    L.push('- Elements: ' + s.elements.map(x => '`' + x + '`').join(', '));
    L.push('');
    for(const line of scr(s.id).note.trim().split('\n'))
      L.push(line.trim() ? '- ' + line.trim() : '');
    L.push('');
  }

  const done = SCREENS.filter(s => scr(s.id).reviewed).map(s => s.id);
  L.push('## Review coverage');
  L.push('');
  L.push('- Reviewed ' + done.length + ' of ' + SCREENS.length + ': '
         + (done.length ? done.map(x => '`' + x + '`').join(', ') : '_none_'));
  const skipped = SCREENS.filter(s => !scr(s.id).reviewed).map(s => s.id);
  if(skipped.length)
    L.push('- Not marked reviewed: ' + skipped.map(x => '`' + x + '`').join(', '));
  L.push('');
  return L.join('\n');
}
function bundle(){
  return JSON.stringify({key:KEY, surface:DATA.name, generated:DATA.generated,
                         exported:new Date().toISOString(), db:DB}, null, 1);
}
function download(name, text, type){
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], {type}));
  a.download = name; a.click(); URL.revokeObjectURL(a.href);
}
const modal = document.getElementById('modal');
const mtext = document.getElementById('mtext');
document.getElementById('export').addEventListener('click', () => {
  document.getElementById('mtitle').textContent = 'Export';
  document.getElementById('msub').textContent =
    'Markdown below - copy it straight into the chat. The .json is the exact '
    + 'state, for reloading later with Import.';
  document.getElementById('mload').style.display = 'none';
  mtext.value = markdown();
  modal.classList.add('on');
});
document.getElementById('import').addEventListener('click', () => {
  document.getElementById('mtitle').textContent = 'Import';
  document.getElementById('msub').textContent =
    'Paste a previously exported .json here, then Load. This REPLACES the current notes.';
  document.getElementById('mload').style.display = '';
  mtext.value = '';
  modal.classList.add('on');
});
document.getElementById('mload').addEventListener('click', () => {
  try{
    const o = JSON.parse(mtext.value);
    DB = Object.assign({screens:{}, elements:{}}, o.db || o);
    save(); build(); modal.classList.remove('on');
  }catch(e){ alert('That is not valid exported JSON.'); }
});
document.getElementById('mcopy').addEventListener('click', async () => {
  try{ await navigator.clipboard.writeText(mtext.value); }
  catch(e){ mtext.select(); document.execCommand('copy'); }
  document.getElementById('mcopy').textContent = 'Copied';
  setTimeout(() => document.getElementById('mcopy').textContent = 'Copy to clipboard', 1400);
});
document.getElementById('mmd').addEventListener('click', () =>
  download(DATA.name + '-review.md', markdown(), 'text/markdown'));
document.getElementById('mjson').addEventListener('click', () =>
  download(DATA.name + '-review.json', bundle(), 'application/json'));
document.getElementById('mclose').addEventListener('click', () => modal.classList.remove('on'));
modal.addEventListener('click', e => { if(e.target === modal) modal.classList.remove('on'); });
document.addEventListener('keydown', e => {
  if(e.key === 'Escape') modal.classList.remove('on');
});
document.getElementById('clear').addEventListener('click', () => {
  if(!confirm('Delete every note and reviewed mark?')) return;
  DB = {screens:{}, elements:{}}; save(); build();
});

load();
build();
</script></body></html>
"""
