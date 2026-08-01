"""A Sync-History run card must fit its own header, with no JavaScript.

The defect
----------
Reported 2026-07-31: multi-course entries in Sync History rendered with the
course pills cut in half and the "Synced N files" line missing entirely, and an
expanded entry painted its header ON TOP of the first row of its body.

The card is a "fake expander": an invisible full-width ``st.button`` is the
click target, and the rich header (title / course pills / meta line) is painted
over it. The header used to be an ABSOLUTELY POSITIONED overlay, which
contributes nothing to its parent's height - so the card's height came from the
button, and the button's height was measured and assigned by a
``components.html`` bridge (``sync_ui._inject_shist_height_bridge``).

Two independent things were wrong with that.

1. IT DID NOT WORK. Its docstring asserted "components.html rebuilds its iframe
   on each rerun and destroys the previous one" and depended on that for
   correctness. Measured in the real app: Streamlit REUSES the iframe whenever
   the srcdoc is unchanged, and this srcdoc was a constant - so the script ran
   once per mount while React went on replacing button nodes underneath it. Any
   button node recreated after that one shot lost its inline height and fell
   back to the stylesheet's 60px floor. Reproduced by switching the By-Course
   filter from a single-course course to a multi-course one: a card rendered
   62px tall around its 106px header (clipped by 46px), pills sliced, meta line
   gone. Only SOME cards break, because a ResizeObserver rescues the ones whose
   header node Streamlit mutates in place rather than replaces - which is what
   made the symptom look random.

2. IT SOLVED THE WRONG PROBLEM. The observation it was built on - "the card
   stayed 92px around a 106px header" - was read as Streamlit 1.51 refusing to
   grow a container from an auto-height flow child. It is not. Streamlit puts
   ``margin-bottom: -16px`` on every stMarkdownContainer, so the header's
   element-container measures exactly 16px shorter than the header inside it,
   and it is the container that sizes the parent. Measured 2026-07-31 in the
   running app: header 105.675px, its element-container 89.675px, card
   91.675px - the reported 92, to a third of a pixel.

The fix
-------
The card is a one-cell CSS grid. Header and button both sit in row 1, so they
stack; the header is IN FLOW at its natural height and therefore sizes the row;
the button stretches to fill it; the body auto-flows into row 2. No measurement,
no JavaScript, so there is no state in which a card and its header can disagree.

Verified in the running app after the change: all 15 cards, 0 clipped, 0 with an
uncovered header bar, 0 misaligned; the By-Course flow that reproduced the bug
gave 4 correct cards; an expanded card overlapped its body by exactly 0px.

What is locked down here
------------------------
* No height bridge, in any form, comes back.
* Every declaration the pure-CSS mechanism needs is present - each one was
  required to make it work in the browser, and each fails differently.
* Today's cards, which share this stylesheet but keep a fixed-height bar, stay
  excluded.
* The button is still emitted BEFORE the header (they share a grid cell, so DOM
  order is what puts the header on top).
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SYNC_UI = REPO / "sync_ui.py"
CSS = REPO / "styles" / "sync_history_cards.css"

_NON_TODAY = 'div[class*="st-key-shist_run_"]:not([class*="st-key-shist_run_today_"])'


@pytest.fixture(scope="module")
def css_text() -> str:
    return CSS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css_rules(css_text: str) -> str:
    """The stylesheet with every comment blanked.

    The comments here quote the exact selectors and declarations under test, so
    a rule deleted from the sheet but still described in prose would otherwise
    keep every assertion passing.
    """
    return re.sub(r"/\*.*?\*/", " ", css_text, flags=re.S)


@pytest.fixture(scope="module")
def sync_ui_src() -> str:
    return SYNC_UI.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 1. The bridge stays dead.
# --------------------------------------------------------------------------

def test_no_height_bridge_function(sync_ui_src: str) -> None:
    """No function may measure a header and assign the button a height again."""
    tree = ast.parse(sync_ui_src)
    names = {
        n.name for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_inject_shist_height_bridge" not in names, (
        "The JS height bridge is back. It cannot work: Streamlit reuses a "
        "components.html iframe whenever the srcdoc is unchanged, so the script "
        "runs once per mount while React replaces button nodes underneath it."
    )


def test_history_renderer_injects_no_components_html(sync_ui_src: str) -> None:
    """`_render_sync_history` must contain no components.html call at all.

    Scoped to that one function via the AST rather than searched for across the
    file, so an unrelated bridge elsewhere in sync_ui.py does not fail this and
    a re-added one here cannot hide behind a different helper name.
    """
    tree = ast.parse(sync_ui_src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_render_sync_history"
    )
    calls = [
        ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)
    ]
    offenders = [c for c in calls if "components" in c and c.endswith(".html")]
    assert not offenders, (
        f"Sync History renders a components.html bridge again: {offenders}. "
        "The card sizes itself in CSS; see styles/sync_history_cards.css."
    )


def test_no_shist_height_registry_anywhere(sync_ui_src: str) -> None:
    """The bridge's window-parent registry name must not reappear."""
    assert "_cdShistHeights" not in sync_ui_src


# --------------------------------------------------------------------------
# 2. Every declaration the CSS mechanism depends on.
#
#    These are not stylistic preferences. Each was added because the browser
#    demonstrably failed without it, and each fails in a different, silent way.
# --------------------------------------------------------------------------

def test_run_card_is_a_grid(css_rules: str) -> None:
    """The card must be a grid, or the header and button cannot share a cell."""
    block = _declarations_for(css_rules, _NON_TODAY)
    assert "display: grid !important" in block, (
        "The run card is not a grid any more - header and button would stack "
        "vertically and the card would be twice its intended height."
    )
    assert "grid-template-columns: minmax(0, 1fr) !important" in block, (
        "minmax(0, 1fr), not 100%: it is exactly the container width AND it "
        "lets the body's long filenames shrink instead of blowing the track out."
    )


def test_header_and_button_share_row_one(css_rules: str) -> None:
    """Both children pinned to row 1; the body then auto-flows into row 2."""
    block = _declarations_for(
        css_rules,
        f'{_NON_TODAY} > [data-testid="stElementContainer"]:has(.shist-runhead),\n'
        f'{_NON_TODAY} > [data-testid="stElementContainer"][class*="st-key-shist_btn_"]',
    )
    assert "grid-row: 1 !important" in block
    assert "grid-column: 1 !important" in block
    assert "align-self: stretch !important" in block, (
        "Streamlit sets align-items: start on stVerticalBlock. Without an "
        "explicit stretch the button keeps its own 60px height inside a 106px "
        "row, so the header bar's background covers only the top of the card."
    )


def test_header_container_is_positioned_not_static(css_rules: str) -> None:
    """`position: relative`, never `static` or `absolute`.

    absolute -> the header contributes nothing to the row and the card collapses
    back to the reported bug. static -> z-index does not apply, and the button's
    element-container IS positioned (Streamlit's own CSS), so a positioned box
    paints above a static sibling whatever the DOM order: the header would be
    buried under the button's opaque background.
    """
    block = _declarations_for(
        css_rules,
        f'{_NON_TODAY} > [data-testid="stElementContainer"]:has(.shist-runhead)',
    )
    assert "position: relative !important" in block
    assert "absolute" not in block
    assert "z-index: 3 !important" in block
    assert "pointer-events: none !important" in block, (
        "Without this the header swallows clicks and only the parts of the card "
        "it does not cover would toggle the entry."
    )


def test_streamlit_negative_markdown_margin_is_cancelled(css_rules: str) -> None:
    """The 16 pixels the whole JS bridge existed for.

    stMarkdownContainer carries margin-bottom: -16px, so the header's
    element-container - which is what sizes the grid row - measures 16px shorter
    than the header itself. Restore this and the card is 16px short of its
    header again: the meta line is clipped and the bug is back in a subtler form
    that looks like a padding mistake.
    """
    block = _declarations_for(
        css_rules,
        'div[class*="st-key-shist_run_"] [data-testid="stMarkdownContainer"]'
        ':has(> .shist-runhead)',
    )
    assert "margin-bottom: 0 !important" in block


def test_button_stretches_through_every_wrapper(css_rules: str) -> None:
    """height:100% must be restated on each wrapper down to the <button>.

    Miss one and the button collapses to its min-height: only the top 60px of a
    tall card is clickable and lit on hover, while the rest shows the darker
    body colour through where the header bar should be.
    """
    wrapper = _declarations_for(
        css_rules,
        f'{_NON_TODAY} div[class*="st-key-shist_btn_"] [data-testid="stButton"]',
    )
    assert "height: 100% !important" in wrapper

    button = _declarations_for(
        css_rules, f'{_NON_TODAY} div[class*="st-key-shist_btn_"] button'
    )
    assert "height: 100% !important" in button, (
        "The button must fill the row, NOT carry a fixed pixel height - a fixed "
        "height is exactly what the deleted JS bridge was there to compute."
    )
    assert "min-height: 60px !important" in button, (
        "The floor for a header that renders empty; a real header can never go "
        "under it (.shist-runhead sets the same min-height)."
    )
    # (?<![-\w]) so `min-height: 60px` above - which is wanted - is not read as
    # the fixed `height: 60px` this forbids.
    assert not re.search(r"(?<![-\w])height:\s*\d+px", button), (
        "A pixel height on this button reintroduces the class of bug that was "
        "just removed - the card would stop tracking its header."
    )


# --------------------------------------------------------------------------
# 3. Today's cards share this stylesheet and must stay on their fixed bar.
# --------------------------------------------------------------------------

def test_today_cards_excluded_from_the_grid(css_rules: str) -> None:
    """Every new structural rule must exclude Today or key off .shist-runhead.

    Today renders `.shist-card` at a fixed 52/60px and never renders
    `.shist-runhead`, so both forms of exclusion are safe; what is not safe is a
    rule that changes `display` or grid placement for a bare `shist_run_` match.
    """
    structural = re.compile(
        r"([^{}]*st-key-shist_run_[^{}]*)\{([^}]*)\}", re.S
    )
    for selector, body in structural.findall(css_rules):
        if not re.search(r"display:\s*grid|grid-row|grid-column|grid-template", body):
            continue
        assert (
            "st-key-shist_run_today_" in selector
            or ".shist-runhead" in selector
        ), (
            "This rule would reshape Today's cards too:\n"
            f"{selector.strip()} {{{body.strip()}}}"
        )


# --------------------------------------------------------------------------
# 4. Emission order - the header is painted over the button by DOM order.
# --------------------------------------------------------------------------

def test_button_is_emitted_before_the_header(sync_ui_src: str) -> None:
    """Swap these and the button's opaque background covers the header text.

    Anchored on the two statements and their relative position, never on them
    being adjacent: a comment inserted between them is a reformat, not a
    regression, and a test that fails on it reads like a missing guard.
    """
    tree = ast.parse(sync_ui_src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_render_sync_history"
    )
    btn_line = header_line = None
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        src = ast.unparse(node)
        if "st.button" in src and "shist_btn_" in src:
            btn_line = node.lineno
        elif "st.markdown" in src and "header_html" in src:
            header_line = node.lineno

    assert btn_line is not None, "the run card's click button has gone"
    assert header_line is not None, "the run card's rich header has gone"
    assert btn_line < header_line, (
        "The header markdown must be emitted AFTER the button: they share one "
        "grid cell, so paint order is DOM order."
    )


# --------------------------------------------------------------------------

def _declarations_for(css: str, selector: str) -> str:
    """Return the declaration block belonging to *selector*.

    Whitespace-insensitive so reindenting the stylesheet cannot fail a test,
    but the selector itself must match exactly - a rule that no longer targets
    these elements is a real regression, not a formatting one.
    """
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    wanted = norm(selector)
    for raw_sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css, re.S):
        if norm(raw_sel) == wanted:
            return norm(body)
    raise AssertionError(
        f"No rule in {CSS.name} targets:\n  {wanted}\n"
        "The card's height depends on it; see this module's docstring."
    )
