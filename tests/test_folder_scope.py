"""A folder's FILE FILTER decides what the analyzer may even consider (2026-08-11).

REPORTED, then reproduced from the real folder's own manifest and debug log: a
sync review run immediately after a download reported **76 new files**, all Canvas
Pages (.html) and module links (.webloc). Nothing had changed on Canvas.

THE MISMATCH. The download engine skips Pages and links outright under the
"Slides & PDFs" filter - three `if file_filter == 'study': continue` sites in
`download_course_async` - while `get_course_files_metadata`, which feeds the
analyzer, enumerated them unconditionally. Evidence from course 43660's folder:

    sync_contract               file_filter: "study"
    secondary_content_contract  all false        (honoured - "enabled=[none]")
    download_mode               flat
    manifest rows .html/.webloc 0
    on disk                     56 pdf, 51 pptx, 11 pptm - no html, no webloc
    debug log                   "Analysis complete: 76 new | 0 clean updates"

So the diff compared Canvas against a manifest that could never contain those
items, and would have done so on EVERY sync for ever - and accepting them would
have turned the folder into a shape the user never configured.

OUT OF SCOPE IS NOT IGNORED. `is_ignored` records a decision the USER made;
these were never offered to them. Out-of-scope items are dropped before the diff
and listed nowhere.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


# ── the rule itself ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("item_type", ["Page", "ExternalUrl", "ExternalTool"])
def test_study_filter_excludes_pages_and_links(item_type):
    from core.canvas_logic import module_item_in_scope
    assert module_item_in_scope(item_type, "all") is True
    assert module_item_in_scope(item_type, "study") is False, (
        "the download engine skips these under 'study'; the analyzer must agree "
        "or it reports them as new for ever"
    )


@pytest.mark.parametrize("ff", ["all", "study"])
def test_files_are_never_excluded_by_this_rule(ff):
    """This predicate is about module ITEM TYPES only.

    Files-tab files are scoped by extension, which `analyze_course` does not do
    at all - they stay out of the diff via their is_ignored rows. Widening this
    predicate to cover files would break that, so it must stay narrow.
    """
    from core.canvas_logic import module_item_in_scope
    assert module_item_in_scope("File", ff) is True
    assert module_item_in_scope("SubHeader", ff) is True


def test_link_like_types_are_declared_once():
    from core.canvas_logic import LINK_LIKE_MODULE_ITEM_TYPES as T
    assert set(T) == {"Page", "ExternalUrl", "ExternalTool"}


# ── every site asks the shared rule ─────────────────────────────────────────

def _code(src: str) -> str:
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))


def test_no_site_hand_rolls_the_study_check():
    """Four places encoded this rule and the fourth disagreed - hence the bug."""
    src = _code((REPO / "core" / "canvas_logic.py").read_text(encoding="utf-8"))
    stray = [ln.strip() for ln in src.splitlines()
             if "file_filter == 'study'" in ln and "module_item_in_scope" not in ln
             and "def module_item_in_scope" not in ln]
    # count_course_items / get_course_total_size_mb legitimately test the filter
    # for FILE extensions; only the module-item branches are covered here.
    offenders = [ln for ln in stray if "continue" in ln and "item.type" not in ln]
    assert not offenders, offenders


def test_the_three_download_branches_route_through_the_predicate():
    src = (REPO / "core" / "canvas_logic.py").read_text(encoding="utf-8")
    for t in ("Page", "ExternalUrl", "ExternalTool"):
        m = re.search(rf"elif item\.type == '{t}':\s*\n\s*if ([^\n]+)", src)
        assert m, t
        assert "module_item_in_scope" in m.group(1), \
            f"the {t} branch must ask the shared rule, not re-test the filter"


def test_the_metadata_scan_drops_out_of_scope_items():
    from core.canvas_logic import CanvasManager
    sig = inspect.signature(CanvasManager.get_course_files_metadata)
    assert "file_filter" in sig.parameters, \
        "the scan feeds the analyzer, so it must know the folder's filter"
    assert sig.parameters["file_filter"].default == "all", \
        "permissive default: an unknown contract may show more, never hide"
    # The enumeration lives in the module walk `_get_files_from_modules`, not in
    # get_course_files_metadata itself - anchored on the function so a move is a
    # test failure rather than a silent pass.
    src = inspect.getsource(CanvasManager._get_files_from_modules)
    m = re.search(r"elif item\.type in LINK_LIKE_MODULE_ITEM_TYPES:(.{0,400})", src, re.S)
    assert m, "the page/link branch moved - re-anchor"
    assert "module_item_in_scope" in m.group(1)
    assert "continue" in m.group(1)


def test_every_page_and_link_branch_in_the_engine_is_scoped():
    """FIVE sites encoded this rule, not three - two module walks plus the scan.

    Counting them is the point: the original defect was one site out of step, and
    a fix that lands on some of them looks identical in review.
    """
    src = (REPO / "core" / "canvas_logic.py").read_text(encoding="utf-8")
    assert "file_filter == 'study': continue" not in src, \
        "a hand-rolled copy of the rule is how the scan drifted from the engine"
    assert src.count("module_item_in_scope(item.type, file_filter)") == 6, (
        "expected all SIX page/link branches to ask the shared predicate: three "
        "in download_course_async's module walk (Page / ExternalUrl / "
        "ExternalTool), two in the folder-structure walk (Page, and one branch "
        "covering both link types), and one in the metadata scan that feeds the "
        "analyzer. The scan was the odd one out, and that WAS the bug.")


# ── the analyzer supplies it from the folder's own contract ─────────────────

def test_analyzer_reads_the_filter_from_the_manifest_and_passes_it():
    src = (REPO / "sync" / "analysis.py").read_text(encoding="utf-8")
    assert "_load_metadata('sync_contract')" in src, \
        "the folder's own contract is the only truthful source of its scope"
    assert re.search(r"file_filter=_built_filter", src), \
        "the scan must be told the filter, like download_mode already is"
    # and the fallback is permissive
    assert "_built_filter = 'all'" in src


def test_the_filter_is_read_before_the_scan_is_called():
    """An AST check, because ordering is the whole point here."""
    src = (REPO / "sync" / "analysis.py").read_text(encoding="utf-8")
    read_at = src.index("_built_filter = 'all'")
    call_at = src.index("file_filter=_built_filter")
    assert read_at < call_at


def test_a_folder_with_no_contract_is_treated_as_full_scope():
    """Pre-contract folders must not silently lose content."""
    src = (REPO / "sync" / "analysis.py").read_text(encoding="utf-8")
    block = src[src.index("_built_filter = 'all'"):src.index("file_filter=_built_filter")]
    assert "except (json.JSONDecodeError, TypeError, ValueError)" in block, \
        "a corrupt contract must fall back to 'all', not raise mid-analysis"


# ═══════════════════════════════════════════════════════════════════════════
# PASS 2 (2026-08-11): the FILES half, which the first pass left undone
#
# The first pass fixed module ITEMS (Pages, links) and recorded in CLAUDE.md that
# `analyze_course` "never applies file_filter to Files-tab files at all", with the
# legacy `is_ignored` stubs the download engine wrote as the only thing keeping
# them out of "new". Two consequences, both measured against the real analyzer:
#
#   1. A file uploaded to Canvas AFTER the initial download had no stub, so it was
#      offered as NEW - and `sync/execution.py` contains no filter at all, so
#      selecting it downloaded it. The folder widened one file at a time, silently,
#      exactly the shape the user ruled against ("one folder, one configuration").
#   2. The stubs themselves were reported as IGNORED and the dialog offered to
#      RESTORE them - a decision the user was never asked to make, and a button
#      that could not do what it said.
#
# Scope is now enforced ONCE, in `analyze_course`, upstream of both flows.
# ═══════════════════════════════════════════════════════════════════════════

import json


def _code_only(src: str) -> str:
    """*src* with comments and docstrings removed, via the AST.

    Every one of the three source-level checks below failed on its first run by
    matching its OWN explanatory prose - the brittle-anchor trap this repo has hit
    repeatedly ("a brittle test anchor reads like a missing guard"). A check about
    what the code DOES must not read what the comments SAY.

    Done through `ast.unparse` rather than tokenize: comments are not in the AST at
    all, and dropping a leading string statement is exactly the docstring rule, so
    both disappear in one step with no token bookkeeping to get wrong (a first
    attempt tracked the previous token type and silently failed to recognise a
    function docstring, which is how this note came to be written).

    STRING LITERALS ARE KEPT - the inverse of
    tests/test_macos_no_accessibility_permission.py's rule is NOT wanted here: only
    prose is noise, a literal is code.
    """
    import ast as _a
    try:
        tree = _a.parse(_dedent_def(src))
    except SyntaxError:
        return src
    for node in _a.walk(tree):
        if isinstance(node, (_a.Module, _a.FunctionDef, _a.AsyncFunctionDef, _a.ClassDef)):
            body = getattr(node, 'body', None)
            if (body and isinstance(body[0], _a.Expr)
                    and isinstance(body[0].value, _a.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [_a.Pass()]
    _a.fix_missing_locations(tree)
    return _a.unparse(tree)


def _dedent_def(src: str) -> str:
    """`ast.get_source_segment` returns a METHOD still carrying its indentation."""
    import textwrap
    return textwrap.dedent(src)


def _cf(fid, name, size=9):
    from core.sync_manager import CanvasFileInfo
    return CanvasFileInfo(id=fid, filename=name, display_name=name, size=size,
                          modified_at="2026-07-01T00:00:00Z", url="http://x/f")


def _study_folder(tmp_path, file_filter='study', name="Digitalisering"):
    from core.sync_manager import SyncManager
    d = tmp_path / name
    d.mkdir()
    sm = SyncManager(d, course_id=43660, course_name=name)
    if file_filter is not None:
        sm._save_metadata('sync_contract', json.dumps(
            {'file_filter': file_filter, 'download_mode': 'flat'}))
    return sm, d


# ── the predicate ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,keep", [
    ("Lecture.pdf", True), ("Slides.ppt", True), ("Slides.pptx", True),
    ("Slides.pptm", True), ("T.pot", True), ("T.potx", True),
    ("Slides.PPTX", True), ("Lecture.PDF", True),
    ("Notes.docx", False), ("Data.xlsx", False), ("Photo.jpg", False),
    ("Video.mp4", False), ("Code.zip", False), ("Page.html", False),
    ("no-extension", False), ("archive.pdf.zip", False),
])
def test_the_study_allowlist(name, keep):
    from core.canvas_logic import file_in_scope
    assert file_in_scope(name, 'study') is keep
    assert file_in_scope(name, 'all') is True, "'all' excludes nothing"


def test_a_path_is_accepted_not_just_a_bare_name():
    """analyze_course holds the computed destination, which is the best evidence."""
    from core.canvas_logic import file_in_scope
    assert file_in_scope("Week 1/Lecture.pdf", 'study') is True
    assert file_in_scope("Week 1/Notes.docx", 'study') is False


def test_the_allowlist_exists_exactly_once_in_the_tree():
    """The rule was written by hand in FOUR places and one of them had drifted.

    Same divergent-primitive shape as `make_long_path`'s duplicate in
    core/sync_manager.py and the three AppleScript escapers: a rule written more
    than once is a rule some caller is following an old version of.
    """
    offenders = []
    for path in sorted(REPO.rglob("*.py")):
        if any(p in {'.venv', 'build', 'dist', '__pycache__', 'tests'} for p in path.parts):
            continue
        src = _code_only(path.read_text(encoding="utf-8"))
        # THE DISCRIMINATOR IS `.pdf`, and getting it wrong is instructive: a
        # literal naming .pptm and .potx WITHOUT .pdf is the PowerPoint
        # CONVERTER's input set (five sites: post_processing, applescript_bridge,
        # helpers, execution x2), a different concept that must never be merged
        # with this one - a PDF is not converted to PDF. Adding .pdf isolates the
        # study filter exactly, and it still caught a genuine fifth copy in app.py.
        for m in re.finditer(r"[\[{][^\[\]{}\n]*\.pptm[^\[\]{}\n]*[\]}]", src):
            if '.potx' not in m.group(0) or '.pdf' not in m.group(0):
                continue
            if path.name == 'canvas_logic.py' and 'STUDY_FILE_EXTENSIONS' in \
                    src[max(0, m.start() - 120):m.start()]:
                continue                      # the one definition
            offenders.append(f"{path.relative_to(REPO)}: {m.group(0)[:70]}")
    assert not offenders, (
        "a second copy of the Slides & PDFs allowlist:\n  " + "\n  ".join(offenders))


# ── the analyzer ─────────────────────────────────────────────────────────────

def test_a_new_out_of_scope_upload_is_not_offered_as_new(tmp_path):
    """THE live bug. Nothing kept a post-download upload out of the review."""
    sm, d = _study_folder(tmp_path)
    res = sm.analyze_course([_cf(1003, "Groupwork.xlsx")], sm.load_manifest())
    assert [f.filename for f in res.new_files] == []
    assert res.out_of_scope_files == 1


def test_an_in_scope_upload_is_still_offered(tmp_path):
    sm, d = _study_folder(tmp_path)
    res = sm.analyze_course([_cf(1004, "Week 2.pptx")], sm.load_manifest())
    assert [f.filename for f in res.new_files] == ["Week 2.pptx"]
    assert res.out_of_scope_files == 0


def test_a_legacy_filter_created_ignored_stub_is_reclassified(tmp_path):
    """The 23 rows a real folder carried. Never the user's decision to make."""
    sm, d = _study_folder(tmp_path)
    sm.ignore_file(1002, "Syllabus.docx", 4242)
    res = sm.analyze_course([_cf(1002, "Syllabus.docx")], sm.load_manifest())
    assert [f.canvas_filename for f in res.ignored_files] == []
    assert res.out_of_scope_files == 1


def test_an_in_scope_ignored_row_is_still_ignored(tmp_path):
    """The size cap and the user's own Ignore button are REAL decisions."""
    sm, d = _study_folder(tmp_path)
    sm.ignore_file(1005, "Huge lecture.pdf", 900_000_000)
    res = sm.analyze_course([_cf(1005, "Huge lecture.pdf")], sm.load_manifest())
    assert [f.canvas_filename for f in res.ignored_files] == ["Huge lecture.pdf"]
    assert res.out_of_scope_files == 0


def test_custody_outranks_scope_for_a_file_the_folder_HAS(tmp_path):
    """A tracked, downloaded file is never dropped from tracking.

    Reachable by a Canvas-side rename: the id survives, the extension does not.
    Dropping it would silently stop reporting updates for a file the user holds,
    so the rule answers "may this folder GAIN this file?", not "does it match?".
    """
    sm, d = _study_folder(tmp_path)
    (d / "Handout.docx").write_bytes(b"hello world")
    sm.record_downloaded_file(1006, "Handout.docx", str(d / "Handout.docx"),
                              "2026-07-01T00:00:00Z", 11)
    res = sm.analyze_course([_cf(1006, "Handout.docx", 11)], sm.load_manifest())
    assert res.out_of_scope_files == 0, "a file in custody is not 'excluded'"
    tracked = [c.filename for c, _ in res.uptodate_files]
    assert tracked == ["Handout.docx"]


def test_an_out_of_scope_file_is_not_reported_as_deleted_on_canvas(tmp_path):
    """Dropping it from the diff must not make it look gone.

    `seen_ids` is filled in the first pass, before the scope check in the second,
    which is what keeps the deletion detector honest.
    """
    sm, d = _study_folder(tmp_path)
    sm.ignore_file(1002, "Syllabus.docx", 10)
    res = sm.analyze_course([_cf(1002, "Syllabus.docx")], sm.load_manifest())
    assert [f.canvas_filename for f in res.deleted_on_canvas] == []


@pytest.mark.parametrize("contract", ['all', None, 'garbage'])
def test_a_folder_that_does_not_say_study_drops_nothing(tmp_path, contract):
    """Permissive on anything but an explicit 'study'.

    Showing more than it should is recoverable; silently hiding a file the user
    is entitled to is not.
    """
    from core.sync_manager import SyncManager
    d = tmp_path / "F"
    d.mkdir()
    sm = SyncManager(d, course_id=43660, course_name="F")
    if contract == 'garbage':
        sm._save_metadata('sync_contract', '{not json')
    elif contract is not None:
        sm._save_metadata('sync_contract', json.dumps({'file_filter': contract}))
    res = sm.analyze_course([_cf(1003, "Groupwork.xlsx")], sm.load_manifest())
    assert [f.filename for f in res.new_files] == ["Groupwork.xlsx"]
    assert res.out_of_scope_files == 0


def test_the_count_is_exact(tmp_path):
    sm, d = _study_folder(tmp_path)
    canvas = ([_cf(2000 + i, f"Handout {i}.docx") for i in range(7)]
              + [_cf(3000 + i, f"Week {i}.pptx") for i in range(3)])
    res = sm.analyze_course(canvas, sm.load_manifest())
    assert res.out_of_scope_files == 7
    assert len(res.new_files) == 3


# ── the identity gate: real files only ───────────────────────────────────────

def test_a_secondary_ENTITY_is_not_scoped_by_extension(tmp_path):
    """The mirror-image bug, and the reason the gate is `real_canvas_file_id`.

    An assignment exports as `.html`, which the study allowlist rejects - but the
    engine's Canvas Content phase is gated on the SECONDARY-CONTENT contract and
    not on file_filter at all, so it produces those files under 'study'. Scoping
    them here would report every one as permanently new, which is precisely the
    defect this whole change exists to remove.
    """
    from core.sync_manager import make_secondary_id
    sm, d = _study_folder(tmp_path)
    aid = make_secondary_id('assignment', 55)
    res = sm.analyze_course([_cf(aid, "Assignment 1.html")], sm.load_manifest())
    assert [f.filename for f in res.new_files] == ["Assignment 1.html"]
    assert res.out_of_scope_files == 0


def test_an_isolate_mode_ATTACHMENT_is_scoped(tmp_path):
    """The other side of the same gate, and why `id > 0` was not enough.

    In isolate mode the analyzer sees an attachment under a synthetic negative id
    while the engine downloads it under its real positive one and applies the
    filter there. Gating on the sign would have left every out-of-scope
    attachment permanently new.
    """
    from core.sync_manager import make_secondary_id
    sm, d = _study_folder(tmp_path)
    att = make_secondary_id('attachment', 987)
    res = sm.analyze_course([_cf(att, "Brief.docx")], sm.load_manifest())
    assert [f.filename for f in res.new_files] == []
    assert res.out_of_scope_files == 1


def test_an_in_scope_attachment_still_arrives(tmp_path):
    from core.sync_manager import make_secondary_id
    sm, d = _study_folder(tmp_path)
    att = make_secondary_id('attachment', 988)
    res = sm.analyze_course([_cf(att, "Brief.pdf")], sm.load_manifest())
    assert [f.filename for f in res.new_files] == ["Brief.pdf"]


def test_the_gate_is_real_canvas_file_id_not_a_sign_test():
    """Pinned by source, because both mutations above pass a shape check."""
    src = (REPO / "core" / "sync_manager.py").read_text(encoding="utf-8")
    block = src[src.index("# ── SCOPE ─"):]
    block = block[:block.index("if file_id not in files_section:")]
    assert "real_canvas_file_id(c_file) is not None" in block
    assert "file_in_scope(calc_path, scope_filter)" in block
    assert "downloaded_at" in block, "the custody exemption must be in the same gate"


def test_the_scope_import_is_function_scoped(tmp_path):
    """core.canvas_logic imports THIS module at module level, so a module-level
    import back would close the cycle. The test checks the LEVEL, not presence."""
    import ast as _ast
    src = (REPO / "core" / "sync_manager.py").read_text(encoding="utf-8")
    tree = _ast.parse(src)
    top = [n.module for n in tree.body
           if isinstance(n, _ast.ImportFrom) and n.module and 'canvas_logic' in n.module]
    assert top == [], f"module-level import of canvas_logic closes a cycle: {top}"
    fn = next(n for n in _ast.walk(tree)
              if isinstance(n, _ast.FunctionDef) and n.name == 'analyze_course')
    inner = [n.module for n in _ast.walk(fn)
             if isinstance(n, _ast.ImportFrom) and n.module and 'canvas_logic' in n.module]
    assert inner, "analyze_course must import the scope helpers itself"


# ── the reclassification, where the user saw it ─────────────────────────────

def test_get_ignored_files_hides_an_out_of_scope_stub(tmp_path):
    sm, d = _study_folder(tmp_path)
    sm.ignore_file(1002, "Syllabus.docx", 10)
    assert [f.canvas_filename for f in sm.get_ignored_files()] == []


def test_get_ignored_files_keeps_a_real_decision(tmp_path):
    sm, d = _study_folder(tmp_path)
    sm.ignore_file(1005, "Huge lecture.pdf", 900_000_000)
    assert [f.canvas_filename for f in sm.get_ignored_files()] == ["Huge lecture.pdf"]


def test_get_ignored_files_keeps_a_downloaded_row_whatever_its_type(tmp_path):
    """Custody again: the folder has the file, so the row is about a real choice."""
    sm, d = _study_folder(tmp_path)
    (d / "Handout.docx").write_bytes(b"x")
    sm.record_downloaded_file(1006, "Handout.docx", str(d / "Handout.docx"),
                              "2026-07-01T00:00:00Z", 1)
    sm.ignore_file(1006, "Handout.docx", 1)
    assert [f.canvas_filename for f in sm.get_ignored_files()] == ["Handout.docx"]


def test_get_ignored_files_lists_everything_when_the_contract_is_unreadable(tmp_path):
    """Fail OPEN: a damaged contract must not hide a decision the user made."""
    sm, d = _study_folder(tmp_path, file_filter=None)
    sm._save_metadata('sync_contract', '{not json')
    sm.ignore_file(1002, "Syllabus.docx", 10)
    assert [f.canvas_filename for f in sm.get_ignored_files()] == ["Syllabus.docx"]


def test_the_reclassification_writes_nothing(tmp_path):
    """It is a QUERY, not a migration - so rows written before this version are
    covered for free and there is no irreversible write to get wrong."""
    sm, d = _study_folder(tmp_path)
    sm.ignore_file(1002, "Syllabus.docx", 10)
    before = sm.load_manifest()['files']
    sm.get_ignored_files()
    sm.analyze_course([_cf(1002, "Syllabus.docx")], sm.load_manifest())
    after = sm.load_manifest()['files']
    assert '1002' in after and after['1002']['is_ignored'] is True, \
        "the row must survive untouched - only its REPORTING changed"
    assert set(before) == set(after)


# ── the engine no longer needs the crutch ───────────────────────────────────

def test_the_download_filter_path_writes_no_ignored_row():
    """The stub existed only because the analyzer did not apply the filter."""
    src = (REPO / "core" / "canvas_logic.py").read_text(encoding="utf-8")
    i = src.index("if not file_in_scope(filepath, file_filter):")
    block = src[i:i + 400]
    assert "ignore_file" not in block, \
        "an out-of-scope file is not an ignored file; nothing may be written here"
    # the SIZE gate is a real user decision and must keep writing one
    assert "ignore_file" in src[src.index("max_bytes and file_size_bytes > max_bytes"):][:1200]


def test_quick_sync_has_no_second_filter():
    """Scope is enforced upstream, in the one place both flows pass through."""
    src = (REPO / "sync" / "analysis.py").read_text(encoding="utf-8")
    assert "def apply_file_filter" not in src
    assert "total_filter_skipped" not in src


def test_the_completion_screen_no_longer_advises_widening_the_folder():
    """Its detail line told users to run a full Review and select the files
    manually - an instruction to widen the folder past the shape they chose, and
    one `analyze_course` now correctly declines to make possible."""
    src = _code_only((REPO / "sync" / "completion.py").read_text(encoding="utf-8"))
    assert "file-type filter" not in src
    assert "skipped_data.get('filtered'" not in src


# ── the notice ──────────────────────────────────────────────────────────────

def test_the_copy_has_one_source():
    """Two surfaces, two idioms, ONE text - or they drift apart, which is the
    exact failure this whole change is about."""
    import ast as _ast
    src = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    tree = _ast.parse(src)
    for fname in ("render_folder_scope_notice", "render_folder_scope_review_notice"):
        fn = next(n for n in _ast.walk(tree)
                  if isinstance(n, _ast.FunctionDef) and n.name == fname)
        calls = [n.func.id for n in _ast.walk(fn)
                 if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)]
        assert 'folder_scope_copy' in calls, f"{fname} must not write its own copy"


@pytest.mark.parametrize("n,expect", [(1, "is set up"), (2, "are set up"), (5, "are set up")])
def test_the_headline_agrees_with_itself(n, expect):
    """Takes an int, never the rows: both return values go into HTML unescaped
    (they carry `<b>` deliberately), so the signature is what makes that safe."""
    from shared.components import folder_scope_copy
    headline, detail = folder_scope_copy(n)
    assert expect in headline
    assert f"<b>{n}</b>" in headline
    assert ("its folder is not a complete copy" if n == 1
            else "their folders are not complete copies") in headline
    assert "All Files" in detail, "the one route that works must be named"


def test_the_notice_is_silent_when_nothing_is_narrowed(monkeypatch):
    """Most runs are All Files; the panel must not become wallpaper."""
    import shared.components as C
    monkeypatch.setattr(C.st, 'session_state', {}, raising=False)
    assert C.folder_scope_limited_courses('download') == []
    assert C.folder_scope_limited_courses('sync') == []


def test_the_resolver_never_raises(monkeypatch):
    """It decorates terminal screens, which must appear in one frame."""
    import shared.components as C

    class Boom(dict):
        def get(self, *a, **k):
            raise RuntimeError("session state exploded")

    monkeypatch.setattr(C.st, 'session_state', Boom(), raising=False)
    assert C.folder_scope_limited_courses('sync') == []
    assert C.folder_scope_limited_courses('download') == []


def test_every_screen_that_states_this_fact_calls_the_renderer():
    """Counted, not spot-checked. The first pass of this very change missed the
    gallery's sync call site while hitting its download one - which is the same
    N-1-of-N miss that put the rule in six places and got one wrong."""
    sites = {
        (REPO / "sync" / "completion.py"): 2,      # sync complete + Today-minimal
        (REPO / "app.py"): 1,                      # download complete
        (REPO / "scripts" / "completion_gallery.py"): 2,   # the mirror of both
    }
    for path, expected in sites.items():
        src = path.read_text(encoding="utf-8")
        got = len(re.findall(r"render_folder_scope_notice\(mode=", src))
        assert got == expected, f"{path.relative_to(REPO)}: {got} call sites, expected {expected}"
    review = (REPO / "ui" / "sync_review.py").read_text(encoding="utf-8")
    assert review.count("render_folder_scope_review_notice()") == 1


def test_the_review_notice_sits_above_the_lists_it_explains():
    src = (REPO / "ui" / "sync_review.py").read_text(encoding="utf-8")
    assert (src.index("render_folder_scope_review_notice()")
            < src.index("# Feature 1: Advanced filtering & Global Selection"))


def test_the_review_notice_does_not_reach_for_completion_css():
    """Its purge rule is the LIVE one (61 nodes) and those screens are tuned WITH
    the collapse, so injecting it on the review page re-spaces that page."""
    import ast as _ast
    src = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    fn = next(n for n in _ast.walk(_ast.parse(src))
              if isinstance(n, _ast.FunctionDef)
              and n.name == 'render_folder_scope_review_notice')
    body = _code_only(_ast.get_source_segment(src, fn) or '')
    assert 'completion.css' not in body
    assert 'render_info_notice' in body
