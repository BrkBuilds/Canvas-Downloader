"""A <style> block must not be emitted in only one branch.

Every style-only ``st.html()`` on a page lands in the EVENT root container - one
ordered, INDEX-ADDRESSED list - so a stylesheet emitted on some runs and not
others does not merely disappear: Streamlit rewrites each host by index, and the
sheet that used to sit there is replaced by its neighbour's.

MEASURED IN THE REAL APP, 2026-08-20, by sampling that list on every animation
frame across a real "Analyze, Review & Sync" on the sync page:

    at rest      [0] cancel-button  [1] sidebar nav-active  [2] <277KB main
                 sheet>  [3] hub-button  [4] main-column buttons
    t=+242ms     [2] had been REWRITTEN with the sidebar's run-lock stylesheet;
                 the 277KB sheet was gone from the list entirely, while [3] and
                 [4] still held the PREVIOUS screen's stylesheets
    t=+288ms     settled

Index [2] held THREE different stylesheets during one run, and index [3] three.
After the fix the sidebar's two sheets sit at [2] and [3] permanently and no
index is ever handed a stranger's stylesheet - the only remaining churn is a
main-page sheet replaced by another main-page sheet when the screen genuinely
changes, which is what reconciliation is for.

WHY THE GUARDS WERE REDUNDANT, which is what makes removing them safe rather
than a trade: every rule in both sidebar blocks is scoped to ``button:disabled``,
and those buttons carry ``disabled=_locked`` / ``disabled=_is_executing``. The
CSS was already self-gating, so the ``if`` changed nothing about what the page
looked like and bought only the index shift. Verified mid-run in the real app
after the change: Download/Today/logout dimmed at ``brightness(0.5)
saturate(0.5)`` with ``cursor: not-allowed``, and the RUNNING mode's button at
``filter: none`` - i.e. the "you are here, and it's running" exclusion still
fires.

THE COURSE LIST is the same class in the twin the original fix did not reach.
``_render_multi_select_list`` carries a comment saying its own ``if
combined_css:`` was "safe only by accident"; ``_render_single_select_list``
still had it, and its guard also swallowed the first row's ``margin-top``
alignment - so a list whose courses happen to carry no parenthetical code lost
its offset AND shifted the page's host list at the same time.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _payload(call: ast.Call) -> str:
    text = ""
    for arg in list(call.args) + [k.value for k in call.keywords]:
        for sub in ast.walk(arg):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                text += sub.value
    return text


def _is_style_only(text: str) -> bool:
    """Streamlit's own ``_html_only_style_tags`` rule, restated.

    It is what decides the ROUTING, and therefore which of two different bugs a
    conditional emission causes. Nothing but style tags and comments left over
    -> the EVENT root container, one global index-addressed list shared by the
    whole page (this file's subject). One byte of real content beside the style
    tag -> the MAIN container at the call site's own delta path, where a
    conditional emission is the container-inheritance hazard instead, local to
    its own parent and judged separately.
    """
    import re
    rest = re.sub(r"<style\b.*?</style\s*>", "", text, flags=re.S | re.I)
    rest = re.sub(r"<!--.*?-->", "", rest, flags=re.S)
    return "<style" in text.lower() and not rest.strip()


def _style_calls(tree: ast.AST) -> list[ast.Call]:
    """Every ``st.html``/``st.markdown`` call that ships ONLY style tags."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name not in ("html", "markdown"):
            continue
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id != "st":
            continue
        if _is_style_only(_payload(node)):
            out.append(node)
    return out


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found - has it been renamed?")


def _branch_depth(fn: ast.AST, call: ast.Call) -> list[str]:
    """The if/else/except/loop chain enclosing *call* inside *fn*, outermost first."""
    found: list[list[str]] = []

    def rec(node, path):
        for field, value in ast.iter_fields(node):
            for child in (value if isinstance(value, list) else [value]):
                if not isinstance(child, ast.AST):
                    continue
                label = None
                if isinstance(node, ast.If) and field in ("body", "orelse"):
                    label = f"{'if' if field == 'body' else 'else'}@{node.lineno}"
                elif isinstance(node, ast.ExceptHandler):
                    label = f"except@{node.lineno}"
                elif isinstance(node, ast.Try) and field in ("handlers", "orelse"):
                    label = f"{field}@{node.lineno}"
                elif isinstance(node, (ast.For, ast.While)) and field == "body":
                    label = f"loop@{node.lineno}"
                p = path + ([label] if label else [])
                if child is call:
                    found.append(p)
                rec(child, p)

    rec(fn, [])
    assert found, "the call is not inside the function it was found in"
    return found[0]


#: (module, function, how many style emissions must be unconditional there)
UNCONDITIONAL_SITES = [
    ("ui/auth.py", "_render_authenticated_nav_top", 2),
    ("ui/auth.py", "_render_authenticated_nav_bottom", 1),
    ("ui/course_selector.py", "_render_single_select_list", 2),
    ("ui/course_selector.py", "_render_multi_select_list", 2),
]


@pytest.mark.parametrize("module,func,expected", UNCONDITIONAL_SITES)
def test_every_stylesheet_here_is_emitted_unconditionally(module, func, expected):
    tree = ast.parse((REPO / module).read_text(encoding="utf-8"))
    fn = _function(tree, func)
    calls = _style_calls(fn)
    assert len(calls) >= expected, (
        f"{module}:{func} emits {len(calls)} stylesheets, expected at least "
        f"{expected} - if one was removed, update this list deliberately")

    guarded = [(c.lineno, _branch_depth(fn, c)) for c in calls
               if _branch_depth(fn, c)]
    assert not guarded, (
        f"{module}:{func} emits a stylesheet inside a branch: {guarded}. "
        f"Style hosts are reconciled BY INDEX, so a sheet that appears on some "
        f"runs and not others slides every later one onto its neighbour's host. "
        f"Emit it unconditionally and put the condition on the CONTENT, or move "
        f"the CSS to a static .css file.")


def test_the_sidebar_lock_css_is_self_gating():
    """Removing the ``if`` is only safe because every rule already requires
    ``button:disabled``. If a rule ever lands here that paints an ENABLED
    button, the unconditional emission would dim the sidebar at rest."""
    src = (REPO / "ui" / "auth.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for func in ("_render_authenticated_nav_top", "_render_authenticated_nav_bottom"):
        fn = _function(tree, func)
        for call in _style_calls(fn):
            text = _payload(call)
            if "nav_btn_" not in text or "disabled" not in text:
                continue  # the active-state sheet, which is not a lock sheet
            body = text.split("<style>", 1)[-1]
            # Strip comments, then every selector must require :disabled.
            import re
            body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
            for block in body.split("}"):
                head = block.split("{")[0].strip()
                if not head or head.startswith("</style") or "{" not in block:
                    continue
                for sel in head.split(","):
                    sel = sel.strip()
                    if not sel:
                        continue
                    assert ":disabled" in sel, (
                        f"{func}: selector {sel!r} does not require :disabled, so "
                        f"emitting this block unconditionally would paint the "
                        f"sidebar at rest. Either scope it, or re-introduce a "
                        f"guard and accept the index shift knowingly.")


@pytest.mark.parametrize("func", ["_render_single_select_list",
                                 "_render_multi_select_list"])
def test_the_first_row_offset_is_computed_outside_any_css_guard(func):
    """The first row's -10px alignment is a layout constant, not a per-course
    nicety. In the single-select twin it used to be appended INSIDE ``if
    dynamic_css:``, so a list whose courses carry no parenthetical code silently
    lost it.

    Parametrized over BOTH renderers, and that is not symmetry for its own sake.
    The first version of this test named only the single-select twin - and the
    mutation pass then re-nested the MULTI-select's offset and reported the
    mutant as SURVIVED, because the two functions are now textually identical
    here and the harness's anchor matched the wrong one. A test that guards one
    of two identical twins is the exact defect this whole file is about.
    """
    tree = ast.parse((REPO / "ui" / "course_selector.py").read_text(encoding="utf-8"))
    fn = _function(tree, func)

    offset_ifs = [n for n in ast.walk(fn)
                  if isinstance(n, ast.If)
                  and "first_item_top_offset" in ast.unparse(n.test)]
    assert offset_ifs, f"{func}: the first-row offset guard is gone entirely"
    for node in offset_ifs:
        assert not _branch_depth(fn, node), (
            f"{func}: the first-row offset is nested inside another branch "
            f"again - it must depend only on there being a first row")


def test_both_course_list_twins_agree_on_the_rule():
    """The multi-select twin's comment is the one that records WHY. If the twins
    ever disagree about this again, that comment is the thing that went stale."""
    src = (REPO / "ui" / "course_selector.py").read_text(encoding="utf-8")
    assert src.count("UNCONDITIONALLY") >= 2, (
        "one of the two course-list renderers no longer documents why its "
        "stylesheet is emitted unconditionally")
