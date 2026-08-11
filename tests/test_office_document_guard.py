"""`active document` is whoever is frontmost - never assume it is ours.

THE DEFECT (`mac_office_active_document`, HIGH, data loss), found by the macOS
26.6 audit on 2026-08-11 and reproduced against the real applications:

    open POSIX file "<ours>"
    set theDoc to active presentation      <- the FRONTMOST one, not ours
    save theDoc ... as PDF
    close theDoc saving no
    on error
        close active presentation saving no   <- closes whatever is frontmost

Measured with `scripts/verify_office_document_guard.py` (user document open and
dirty, then a corrupt file fed to the real converter):

    pre-fix   user documents 1 -> 0    USER DOCUMENT WAS CLOSED - data loss
    fixed     user documents 1 -> 1    user document SURVIVED

with the CONTROL converting a real PDF in both, so the guard did not simply
stop converting. Excel demonstrated the live path while being tested: it
declined the corrupt file, leaving the user's workbook frontmost, and the new
guard refused it with -30001 exactly where the old code would have closed it.

THESE TESTS RUN ON EVERY PLATFORM. What is most likely to undo this fix is not
macOS, it is an edit to one of the three converters - and the codebase's own
history says a fix applied to two of three sites is the normal failure (see
`pdf_looks_real`, applied to the Windows branch of all three converters and the
macOS branch of none, for eight months). So the tests COUNT rather than merely
checking that a guard exists somewhere.
"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

CONVERTERS = {
    "PowerPoint": (REPO / "converters" / "pdf.py", "presentation"),
    "Word": (REPO / "converters" / "word.py", "document"),
    "Excel": (REPO / "converters" / "excel.py", "workbook"),
}
BRIDGE = REPO / "engine" / "applescript_bridge.py"


def _code_only(path: Path) -> str:
    """Source with COMMENTS and DOCSTRINGS removed.

    Both name the very constructs these tests ban - the whole point of the
    docstrings is to explain what `close active presentation` did - so a
    scanner that reads prose reports the explanation as the violation. Same
    reason `verify_architecture.py` blanks comments before its rules run, and
    the same trap that made an earlier macOS test fail against correct code.
    """
    src = path.read_text(encoding="utf-8")
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        out.append(tok)
    stripped = tokenize.untokenize(out)
    # Docstrings survive tokenisation - drop them via the AST.
    tree = ast.parse(stripped)
    doc_spans = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                doc_spans.add((first.lineno, first.end_lineno))
    lines = stripped.splitlines()
    for lo, hi in doc_spans:
        for i in range(lo - 1, min(hi, len(lines))):
            lines[i] = ""
    return "\n".join(lines)


# --------------------------------------------------------------------------
# the counting rules
# --------------------------------------------------------------------------

@pytest.mark.parametrize("app", sorted(CONVERTERS))
def test_no_unguarded_close_of_the_frontmost_document(app):
    """Every `close active <doc>` must sit behind the ours-test.

    This is the line that destroys a user's unsaved work.
    """
    path, term = CONVERTERS[app]
    code = _code_only(path)
    closes = re.findall(rf"close\s+active\s+{term}\s+saving\s+no", code)
    assert closes, f"{path.name}: no `close active {term}` found - has the "\
                   f"AppleScript been restructured? Re-derive this test."
    guarded = re.findall(
        rf"if\s+\{{ours\}}\s+then\s+close\s+active\s+{term}\s+saving\s+no", code)
    assert len(guarded) == len(closes), (
        f"{path.name}: {len(closes)} `close active {term}` but only "
        f"{len(guarded)} guarded by the ours-test - an unguarded one closes "
        f"the USER'S document `saving no`")


@pytest.mark.parametrize("app", sorted(CONVERTERS))
def test_the_success_path_refuses_a_document_that_is_not_ours(app):
    """Binding the wrong document is silent: their content, our filename.

    So the check has to happen BEFORE the save, not only in the error handler.
    """
    path, _term = CONVERTERS[app]
    code = _code_only(path)
    assert "if not {ours} then" in code, (
        f"{path.name}: nothing verifies the frontmost document before exporting "
        f"it - a slow `open`, or an app in crash-recovery with a recovered "
        f"document frontmost, exports THEIR file into our PDF")
    i_check = code.index("if not {ours} then")
    save = re.search(r"\n\s*(save|save as|save workbook as)\s", code[i_check:])
    assert save, f"{path.name}: no save found after the guard"


@pytest.mark.parametrize("app", sorted(CONVERTERS))
def test_the_guard_is_built_from_the_STAGED_name(app):
    """`office_container_stage` stages as `src.<ext>` - a name we own.

    Using `src.name` (the Canvas filename) instead would be a name the user can
    plausibly have open themselves, and on the degraded no-container path the
    two are the same object, so the mistake is invisible in review.
    """
    path, _term = CONVERTERS[app]
    code = _code_only(path)
    assert re.search(rf'our_document_test\(\s*"{app}"\s*,\s*s_src\.name\s*\)', code), (
        f"{path.name}: the guard must be built from the STAGED basename "
        f"(s_src.name), which is the name this app owns")


@pytest.mark.parametrize("app", sorted(CONVERTERS))
def test_no_converter_hand_rolls_the_comparison(app):
    """One definition, three uses.

    A rule written more than once is a rule some caller is following an old
    version of - this repo has paid for that with `make_long_path`'s duplicate
    (which reached none of the 26 manifest call sites) and with three different
    AppleScript string escapers.
    """
    path, term = CONVERTERS[app]
    code = _code_only(path)
    assert f"name of active {term}" not in code, (
        f"{path.name}: builds the document-identity comparison itself; it must "
        f"come from engine.applescript_bridge.our_document_test")


def test_excel_takes_page_setup_from_our_workbook_not_the_application():
    """Excel is the only converter that MUTATES the document before exporting.

    `page setup of active sheet` is the application's frontmost sheet. The
    guard above runs immediately before, so in practice it is ours - but this
    line rewrites orientation and fit-to-page, i.e. it would EDIT a user's
    workbook (and dirty it) if the binding ever drifted. Binding to `theBook`
    costs nothing and removes the question. Added because the mutation pass
    found this was the one part of the fix nothing tested.
    """
    code = _code_only(CONVERTERS["Excel"][0])
    assert "page setup of active sheet of theBook" in code
    assert not re.search(r"page setup of active sheet(?!\s+of\s+theBook)", code)


def test_every_office_converter_is_covered_by_these_tests():
    """A fourth converter must not be able to join quietly.

    The counting tests above are per-file, so a new one is simply never
    checked - which is exactly how the macOS delete-gates stayed missing.
    """
    found = {p.name for p in (REPO / "converters").glob("*.py")
             if "office_container_stage" in p.read_text(encoding="utf-8")}
    covered = {p.name for p, _t in CONVERTERS.values()}
    assert found == covered, (
        f"converters using Office staging: {sorted(found)}; covered here: "
        f"{sorted(covered)} - add the newcomer to CONVERTERS")


# --------------------------------------------------------------------------
# the shared helper
# --------------------------------------------------------------------------

def test_the_helper_compares_the_name_of_the_frontmost_document():
    from engine.applescript_bridge import our_document_test
    expr = our_document_test("PowerPoint", "src.pptx")
    assert expr == '((name of active presentation) is "src.pptx")'
    assert our_document_test("Word", "src.doc") == \
        '((name of active document) is "src.doc")'
    assert our_document_test("Excel", "src.xlsx") == \
        '((name of active workbook) is "src.xlsx")'


def test_the_helper_escapes_the_name():
    """A staged basename is normally `src.<ext>`, but the no-container fallback
    yields the CANVAS filename - server-controlled, and a bare double quote
    there would close the AppleScript literal."""
    from engine.applescript_bridge import our_document_test
    expr = our_document_test("Word", 'we"ird\\name.doc')
    # Backslash first, then quote: escaping quotes first would produce `a\"b`
    # and the later backslash pass would turn the escape itself into `a\\"b`,
    # which CLOSES the literal. Asserted as the exact string rather than by
    # counting quotes - the first version of this test counted them and got the
    # arithmetic wrong against a correct escaper.
    assert expr == r'((name of active document) is "we\"ird\\name.doc")'


def test_the_helper_refuses_an_unknown_app():
    """Silently returning something that matches nothing would disable the
    guard for that app while every test above still passes."""
    from engine.applescript_bridge import our_document_test
    with pytest.raises(KeyError):
        our_document_test("OneNote", "src.one")


def test_the_helper_uses_the_shared_escaper():
    """Not `.replace()` chains - the repo has had three divergent AppleScript
    escapers and one of them was wrong about line breaks."""
    code = _code_only(BRIDGE)
    fn = re.search(r"def our_document_test\(.*?\n(?=\S)", code, re.S).group(0)
    assert "applescript_string(" in fn
    assert ".replace(" not in fn


def test_the_error_number_is_distinctive_and_outside_apples_ranges():
    """It is what a debug log will be grepped for, and it must not collide with
    a real AppleScript error (whose negative codes cluster above -20000)."""
    from engine.applescript_bridge import OFFICE_WRONG_DOC_ERRNO
    assert OFFICE_WRONG_DOC_ERRNO < -20000


@pytest.mark.parametrize("app", sorted(CONVERTERS))
def test_the_app_doc_map_knows_every_converter(app):
    from engine.applescript_bridge import _APP_DOC_MAP
    assert app in _APP_DOC_MAP
    assert _APP_DOC_MAP[app][1].startswith("active ")
