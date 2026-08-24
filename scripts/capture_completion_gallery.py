"""Capture and review every completion screen the app can produce.

    streamlit run scripts/completion_gallery.py --server.port 8599 --server.headless true
    python scripts/capture_completion_gallery.py

Writes ``<id>.png`` (as the screen first appears), ``<id>--open.png`` (every
collapsible open) and ``index.html`` (the review tool) into
``ui-review/completion-screens/``.

This file is ONLY what is specific to this surface: the element vocabulary a
note can be filed against, and the probes that decide which of them a given
screen carries. Everything else - the settle/shoot/expand logic and the review
page - lives in ``scripts/ui_gallery.py`` and is shared with any other surface.

NOTES ARE ATTACHED TO ELEMENTS, NOT (ONLY) TO SCREENS
-----------------------------------------------------
The 37 screens are combinations of ~35 shared elements, so a note about the
stat-card row is a note about eighteen screens. Writing it eighteen times is
what makes reviewing them a chore, and writing it once means the other
seventeen look un-reviewed. So every screen declares which elements it
contains - detected from its own DOM, not hand-maintained - and a note filed
against an element surfaces on every other screen carrying it, marked as
inherited. Walking the list you can always tell "this looks wrong but it is
already written down" from "this is new".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.completion_gallery import SCENARIOS  # noqa: E402
from scripts.ui_gallery import Surface, capture  # noqa: E402


ELEMENTS: list[tuple[str, str, str]] = [
    ("wizard",          "Step tracker",                     "Page chrome"),
    ("heading",         "Page heading",                     "Page chrome"),
    ("card-shell",      "Completion card (colour/inset)",   "Headline card"),
    ("card-title",      "Card title",                       "Headline card"),
    ("stats-grid",      "Stat card row",                    "Headline card"),
    ("stat-error",      "Stat: Failed Downloads",           "Headline card"),
    ("stat-skip",       "Stat: Cannot Be Downloaded",       "Headline card"),
    ("stat-app",        "Stat: App Errors",                 "Headline card"),
    ("stat-recovered",  "Stat: Files Recovered",            "Headline card"),
    ("uptodate-card",   "Nothing-to-do card",               "Headline card"),
    ("nofiles-warn",    "Warning: no files / connection",   "Headline card"),
    ("skip-size",       "Panel: size-skipped files",        "Left alone"),
    ("skip-archive",    "Panel: unpacked archives",         "Left alone"),
    ("pp-warn",         "Notice: conversion failures",      "Notices"),
    ("qs-info",         "Notice: Quick Sync skipped",       "Notices"),
    ("structural-warn", "Notice: modules not fetched",      "Notices"),
    ("office-warn",     "Notice: Office force-closed",      "Notices"),
    ("ignored-info",    "Notice: ignored files",            "Notices"),
    ("newversion-info", "Notice: _NewVersion copies",       "Notices"),
    ("retryfail-warn",  "Notice: retry didn't work",        "Notices"),
    ("panopto-card",    "Panopto summary card",             "Panopto"),
    ("error-panel",     "Error Details panel",              "Errors"),
    ("err-col-failed",  "Error column: Failed to Download", "Errors"),
    ("err-col-declined", "Error column: Cannot Be Downloaded", "Errors"),
    ("app-err-section", "Error section: Application Errors", "Errors"),
    ("app-err-report",  "App-error report actions",         "Errors"),
    ("retry-btn",       "Button: Retry failed downloads",   "Errors"),
    ("folders-section", "Folders Updated header",           "Folders"),
    ("folder-card",     "Folder card",                      "Folders"),
    ("folder-pills",    "Filetype pills",                   "Folders"),
    ("files-expander",  "Files added expander",             "Folders"),
    ("file-rows",       "Per-file rows (Open/Reveal)",      "Folders"),
    ("cancelled-card",  "Cancelled card",                   "Cancelled"),
    ("store-ask",       "Store rating ask",                 "Store rating"),
    ("store-cta",       "Rating CTA button",                "Store rating"),
    ("store-thanks",    "Store rating: thank-you",          "Store rating"),
    ("front-btn",       "Go to front page button",          "Page chrome"),
]

# Detected from the rendered DOM rather than declared per scenario: a
# hand-maintained mapping is one more thing to forget to update, and a chip that
# quietly stops appearing takes its notes' reach with it.
#
# `textContent`, never `innerText` - a closed <details> is not rendered, so
# innerText would miss every error column and skip-panel body on any screen
# where the panel happens to be shut.
DETECT_JS = """() => {
    const M = document.querySelector('div[data-testid="stMainBlockContainer"]');
    if (!M) return [];
    const T = M.textContent || '';
    const q = (s) => M.querySelector(s);
    const qa = (s) => Array.from(M.querySelectorAll(s));
    const out = [];
    const add = (id, cond) => { if (cond) out.push(id); };

    add('wizard', !!q('[class*="st-key-cd_wiz_"]'));
    add('heading', !!q('h2.step-header'));
    add('front-btn', !!q('[class*="st-key-page_nav_front_page"]'));

    const card = q('.completion-card');
    const grid = q('.completion-stats-grid');
    add('card-shell', !!card && !!grid);
    add('card-title', !!q('.card-title'));
    add('stats-grid', !!grid);
    add('stat-error', !!q('.stat-card.stat-error'));
    add('stat-skip', !!q('.stat-card.stat-skip'));
    add('stat-app', !!q('.stat-card.stat-app-error'));
    add('stat-recovered', !!q('.stat-card.stat-recovered'));
    // The nothing-to-do card is the same .completion-card with no stat grid.
    add('uptodate-card', !!card && !grid);
    add('nofiles-warn', T.includes('possible connection issue'));

    const panels = qa('details.skip-panel');
    add('skip-size', panels.some(d => (d.textContent||'').includes('exceeded the')));
    add('skip-archive', panels.some(d => (d.textContent||'').includes('left unpacked')));

    add('pp-warn', T.includes('could not be converted'));
    add('qs-info', T.includes('Quick Sync skipped'));
    add('structural-warn', T.includes('could not be fetched from Canvas'));
    add('office-warn', T.includes('force-closed during conversion'));
    add('ignored-info', T.includes('because you ignored them'));
    add('newversion-info', T.includes('saved as a separate copy'));
    add('retryfail-warn', T.includes('Retry didn'));

    add('panopto-card', !!q('[class*="st-key-panopto_summary_dashboard"]'));

    add('error-panel', !!q('details.error-panel'));
    const titles = qa('.err-col-title').map(e => e.textContent || '');
    add('err-col-failed', titles.some(t => t.includes('Failed to Download')));
    add('err-col-declined', titles.some(
        t => t.includes('Cannot Be Downloaded') || t.includes('Stream-Only')));
    add('app-err-section', !!q('.app-error-section'));
    add('app-err-report', !!q('.app-err-report-btn') && !!q('.app-err-copy-btn'));
    add('retry-btn', !!q('[class*="_retry_failed_btn"]'));

    add('folders-section', !!q('.completion-section-header'));
    add('folder-card', !!q('.fc-wrapper'));
    add('folder-pills', !!q('.ft-expander-pills .ft-pill, .ft-expander-pills > *'));
    add('files-expander', !!q('[data-testid="stExpander"]'));
    add('file-rows', !!q('[class*="st-key-fileactlist_"]'));

    add('store-ask', !!q('.sr-title'));
    add('store-cta', !!q('[class*="_sr_rate"] button'));
    add('store-thanks', !!q('.sr-thanks'));
    add('cancelled-card', T.includes('was cancelled.'));
    return out;
}"""

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8599)
    ap.add_argument("--width", type=int, default=1500)
    # NOT under docs/ - that is the published GitHub Pages site, and this is
    # ~18 MB of regenerable PNGs. `ui-review/` is gitignored.
    ap.add_argument("--out", default=str(REPO / "ui-review" / "completion-screens"))
    args = ap.parse_args()

    surface = Surface(
        name="completion-screens",
        title="Completion screens",
        blurb="Rendered by the real components, each cropped to the full page height.",
        states=[(sid, title, why) for sid, (title, why, _) in SCENARIOS.items()],
        elements=ELEMENTS,
        detect_js=DETECT_JS,
        url="http://localhost:{port}/?v={id}",
        # The key this page used before it was generalised.
        legacy_keys=["cd-completion-review-v1"],
        regenerate=("streamlit run scripts/completion_gallery.py --server.port 8599"
                    " && python scripts/capture_completion_gallery.py"),
    )
    return capture(surface, Path(args.out), args.port, args.width)


if __name__ == "__main__":
    raise SystemExit(main())
