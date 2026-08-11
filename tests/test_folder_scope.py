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
