Find inline `<svg>` icons that have no inline size and are sized only by CSS,
so they balloon to a giant default replaced-element size during a page/mode
transition (when their page-scoped stylesheet is momentarily unmounted while
the old markup still lingers in the DOM). This is the "giant grey course icon
on the Download loading screen" class of bug (see `_SVG_COURSE` in
`ui/today_dashboard.py`).

Execute this command:
```
python scripts/lint_unsized_svg.py
```

The linter scans `ui/`, `sync/`, `engine/`, `core/`, and root `.py` files for
`<svg …>` tags embedded in Python strings that carry no inline `width`/`height`
(neither as an attribute nor inside an inline `style=`). It automatically skips
docstrings and SVGs that are base64-encoded into `data:` URIs (CSS
background-images, which are sized by their box and cannot balloon).

After running, for each finding:
1. Note whether it is sized by **its own CSS class** or **an ancestor's CSS**,
   and identify the stylesheet + rule that currently sizes it (e.g.
   `today.css .tcs-pill-ico`, `completion.css .stat-icon-wrapper svg`).
2. Recommend the fix: add `style='width:<n>px;height:<n>px;flex-shrink:0;'` to
   the `<svg>` tag, matching the size the CSS rule was giving it, so the icon is
   self-sizing regardless of whether its stylesheet is loaded.
3. Flag any that are intentionally container-sized (e.g. a decorative
   illustration meant to fill its parent) as candidates for a
   `# audit-ignore` / `# svg-ignore` suppression comment instead.

Suppress a deliberate case by putting `# audit-ignore` (or `# svg-ignore`) on
the flagged line or the line immediately above it.
