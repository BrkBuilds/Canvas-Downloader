---
paths:
  - "docs/**"
  - "marketing/**"
---

# Website and marketing surfaces

> Extracted from CLAUDE.md. Loads only when Claude opens a matching file.
> Each entry states the mechanism, the measurement, and why the obvious fix is wrong.

## A page's own text must not be `opacity: 0` to a crawler that runs no JS (2026-08-21)
`docs/index.html`, `guide.html` and `engine.html` gate nearly every block behind
`class="reveal"`, which an IntersectionObserver un-hides. Measured with a real
parser: **guide 7,025/7,217 words (97%)**, **index 3,125/4,112 (75%)**, both
with the `h1` hidden. Google renders JS; several assistant crawlers do not, and
`marketing/` records the site appearing in zero of three web searches while an
assistant quoted the *Store* copy.
- **The fix is ADDITIVE and that is the whole point**: one rule on
  `html:not(.js) .reveal`, plus an inline `<head>` script. With JS present
  `html.js` matches so the new rule never applies. **Do not invert it onto
  `html.js .reveal`** - that is (0,2,1) and outranks `.reveal.vis` (0,2,0), so
  nothing would ever be revealed again. Total in a browser, invisible in review.
- **The class means "the mechanism that reveals this exists"**, not "scripting is
  on": it is set only when `IntersectionObserver` is present, because the reveal
  script constructs one with no fallback.
- **Verified against the DEPLOYED pre-fix site, not against a claim**: identical
  reveal count, identical initially-hidden count, identical per-element
  `transitionDelay` ladder, identical computed transition, 0 hidden after
  scrolling. No-JS hidden words 3,125 -> 0 and 7,025 -> 0, confirmed live.
- `tests/test_website_noscript_content.py` derives its page list FROM the markup
  so a new page cannot silently miss the rule; 7/7 control mutants caught,
  including the inversion and a rule that is merely commented out. Two of its own
  assertions were too weak first: a lookbehind that a prefixed selector satisfied
  (compare the WHOLE selector), and reading comment-bearing source instead of
  `<style>` blocks with CSS comments stripped.
