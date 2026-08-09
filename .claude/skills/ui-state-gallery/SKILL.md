---
name: ui-state-gallery
description: Render every state a UI surface can produce, screenshot each one twice (as it appears and fully expanded), and build a review page where notes attach to ELEMENTS so they follow onto every state containing them. Use when asked to review, gauge, audit or gather screenshots of a screen's variants - completion screens, review screens, dialogs, settings cards - or when a UI change needs checking against every combination it can land in.
---

# UI state gallery

Some screens cannot be reviewed by using the app, because reaching a state
means *causing an outcome*: a teacher-locked file, an exhausted retry, an
archive over the guard's limit, a cancelled post-processing pass. Some
combinations cannot be produced at all from the courses any one person has. So
"look at the completion screens" quietly means "download something and hope".

This skill renders them from mock state instead, captures each one, and hands
the user a review tool.

## The three pieces

| Piece | Where | What it is |
|---|---|---|
| Gallery page | `scripts/completion_gallery.py` | A Streamlit script that renders ONE state per page load, chosen by `?v=<id>` |
| Engine | `scripts/ui_gallery.py` | Surface-agnostic: settle, shoot, expand, detect, build the review page |
| Surface | `scripts/capture_completion_gallery.py` | Only what differs: the element vocabulary and the DOM probes |

Reference implementation: the completion screens, 37 states over 35 elements.

## Running the existing one

```bash
streamlit run scripts/completion_gallery.py --server.port 8599 --server.headless true
python scripts/capture_completion_gallery.py
cd ui-review/completion-screens && python -m http.server 8600   # then open :8600
```

**Tell the user to open the http:// URL, never the file path** - Chrome blocks
`localStorage` on `file://`, so notes would not save. The page detects this and
shows a red bar, but by then they have typed.

Output lands in `ui-review/<surface>/` (gitignored - **never `docs/`**, that is
the published website).

## Adding a new surface

1. **Write the gallery page.** A Streamlit script calling the *real* renderers
   with mock state, routed on a query param, with the catalogue as
   `{id: (title, "what to look at", render_fn)}`.
2. **Define the element vocabulary** - `(id, label, group)` for every part a
   note could be about. This is the payload of the whole exercise; see below.
3. **Write `DETECT_JS`** returning the ids present on the current page.
4. **Call the engine** with a `Surface`. That is the whole capture script.

```python
surface = Surface(
    name="sync-review", title="Sync review screen",
    states=[(sid, title, why) for sid, (title, why, _) in SCENARIOS.items()],
    elements=ELEMENTS, detect_js=DETECT_JS,
    url="http://localhost:{port}/?v={id}",
    regenerate="streamlit run scripts/sync_review_gallery.py ...",
)
return capture(surface, Path(args.out), args.port, args.width)
```

## Why notes attach to elements

The states are *combinations*. A note about the stat-card row is a note about
eighteen screens. Writing it eighteen times is what makes the review a chore;
writing it once leaves the other seventeen looking un-reviewed, so on the
second pass nobody can tell "already written down" from "not looked at yet".

So a note filed against an element surfaces on every state carrying it, as an
amber banner at the top: *"3 notes written elsewhere already cover this
screen"*. Chips carrying notes go amber with a count everywhere they appear.
The export names, for each note, the element, the state it was written on, and
every state it applies to.

The user also gets a per-state box for things true only of that combination
(ordering, stacking, spacing between two specific parts).

## Six things that cost a cycle to find

Each of these is silent - the output looks fine and is wrong.

1. **Grow the viewport to the content before shooting.** Streamlit's `stMain`
   is the scroll container, not the window, and Playwright's element screenshot
   scrolls the *window*. Anything below the fold was never painted: measured
   1603px of element against ~620px of content, the rest a black band with a
   ghost of the sticky chrome. `shoot()` then asserts
   `scrollHeight <= clientHeight` rather than trusting it.
2. **Wait for the startup overlay to leave.** `scripts/patch_streamlit_boot.py`
   patches it into Streamlit's `index.html` *in site-packages*, so
   `streamlit run` shows it too. The fastest states settle while it is still
   fading and get shot through it - "Almost ready…" over the card. It removes
   itself, so absence is the signal.
3. **Detect elements with `textContent`, never `innerText`.** A closed
   `<details>` is not rendered, so `innerText` misses every error column and
   panel body on any state where the panel happens to be shut. Detect *after*
   expanding as well.
4. **One state per page load.** Card colour is a `<style>` keyed to a container
   key, Streamlit rejects duplicate widget keys, and element *index* is
   load-bearing on these screens (see the container-inheritance notes in
   CLAUDE.md). Two states on one page is a different app.
5. **Point mock paths at files that exist.** `render_folder_cards` hides "Open
   Folder" unless the path exists and disables per-file actions unless the file
   does. Fictional paths review the disabled paint instead of the real thing.
6. **Namespace the localStorage key, and keep `legacy_keys`.** Renaming the key
   silently orphans a review already in progress. `Surface.legacy_keys` is read
   once on load for exactly this.

## Verify before handing it over

The capture exits non-zero and prints `PROBLEMS` for: a state that never
settled, a broken image `src`, a clipped shot, an unknown element id, a state
with zero elements, and an element no state carries (dead probe, or a missing
state). **A clean run is the check** - do not eyeball 37 screenshots for these.

Then drive the review page once with Playwright: file an element note on one
state, confirm it appears as inherited on another state that has that element
and *not* on one that does not, reload to confirm persistence, and read the
exported Markdown. Clear the test data afterwards - the user starts clean.

## Reporting back

Give the user the URL, how the two note levels differ, and what the export
carries. Screenshots are the deliverable; if measurements are wanted, take them
from the live DOM (`getBoundingClientRect`) rather than from a scaled PNG - the
gaps that matter are a few pixels and the image is scaled twice over.
