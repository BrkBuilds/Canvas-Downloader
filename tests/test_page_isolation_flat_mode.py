"""An isolated Page in FLAT mode, and the two halves that must agree.

A module Page normally lives with its module, in both isolate modes - that is
deliberate and stated in the source. In **flat** mode there is no module folder
for it to live in, so "module placement" degenerates to the course root and the
user's "isolate secondary content" setting is the only instruction left. Before
2026-07-29 the setting was ignored there: ticking it filed assignments, quizzes
and discussions into category folders and left 35 loose `Page*.html` at the root
of the folder that setting exists to tidy (measured, course 43660, row m051).

The fix is small and the way it breaks is not. TWO places decide a page's path
and they are in different files:

* the WRITER - ``_download_flat_async`` -> ``_save_secondary_entity``;
* the ANALYZER's expectation - ``_get_files_from_modules`` emits the name that
  becomes ``calc_path`` in ``sync_manager.analyze_course``.

If they disagree, nothing crashes: every page simply reads as **new on every
sync, for ever**, and freshly-synced copies land somewhere the download engine
would not have put them. So these tests assert the two agree, in both modes,
rather than asserting either one alone.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import canvas_logic as cl  # noqa: E402

SRC = cl.__file__
TEXT = Path(SRC).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# the routing the fix depends on
# --------------------------------------------------------------------------

def test_pages_have_a_category_folder_to_go_to():
    """The destination has existed all along; nothing was asking for it."""
    assert cl._ENTITY_ROUTING["page"]["folder"] == "Pages"
    assert cl._ENTITY_ROUTING["page"]["prefix"] == "Page"


def test_resolve_secondary_path_puts_an_isolated_page_in_its_category_folder(tmp_path):
    cm = cl.CanvasManager.__new__(cl.CanvasManager)
    target, name = cm._resolve_secondary_path(
        "page", "Filer til Klynge 1", tmp_path, module_path=tmp_path,
        isolate=True, has_attachments=False)
    assert target == tmp_path / "Pages"
    assert name == "Filer til Klynge 1", "Mode B keeps the bare name"


def test_resolve_secondary_path_prefixes_an_inline_page_instead(tmp_path):
    cm = cl.CanvasManager.__new__(cl.CanvasManager)
    target, name = cm._resolve_secondary_path(
        "page", "Filer til Klynge 1", tmp_path, module_path=tmp_path,
        isolate=False, has_attachments=False)
    assert target == tmp_path
    assert name.startswith("Page: "), "Mode A carries the type in the name"


# --------------------------------------------------------------------------
# the two halves agree
# --------------------------------------------------------------------------

def _emitted_name_source() -> str:
    """The block of _get_files_from_modules that names a module Page."""
    i = TEXT.index("_page_isolated = (item.type == 'Page'")
    return TEXT[i:i + 1200]


def test_the_analyzer_expectation_is_gated_on_BOTH_isolate_and_flat():
    """Either half alone is wrong.

    Without `isolate` it would move pages for users who never asked. Without
    `download_mode == 'flat'` it would move them out of their module folders in
    modules mode too - the blast radius that was explicitly declined, and the
    one the legacy_sync_id machinery exists to survive.
    """
    src = _emitted_name_source()
    assert "isolate" in src and "download_mode == 'flat'" in src


def test_an_isolated_flat_page_is_expected_in_the_Pages_folder():
    src = _emitted_name_source()
    assert "routing['folder']" in src, (
        "the expected path must name the category folder, because the "
        "analyzer's flat-mode target_paths is empty by design")
    assert "routing['prefix']" in src, "the non-isolated branch must survive"


def test_an_isolated_flat_page_claims_no_module_folder():
    """Belt and braces against '<module>/Pages/X.html'.

    In flat mode `analyze_course` never reads module_map at all, so this is
    currently inert - which is exactly why it is asserted: the day someone
    populates target_paths in flat mode, a stale entry here would silently
    prepend a module name to a path that already has its folder.
    """
    i = TEXT.index("if syn_id and not _page_isolated:")
    block = TEXT[i:i + 500]
    assert "module_map.setdefault(syn_id" in block
    assert "if _legacy_alias and not _page_isolated:" in TEXT


def test_the_writer_takes_the_same_decision_from_its_caller():
    """`_download_flat_async` must not decide this for itself - the mode and
    the setting live with the caller, and a second copy of the rule is how the
    two halves drift apart."""
    sig = inspect.signature(cl.CanvasManager._download_flat_async)
    assert "isolate_pages" in sig.parameters
    assert sig.parameters["isolate_pages"].default is False, (
        "default off, so every caller that has not thought about it keeps "
        "today's layout")


def test_only_the_genuine_flat_caller_opts_in():
    """The 401 fallback must NOT.

    It records ``download_mode='modules'``, so the analyzer will expect the
    prefixed form; a fallback that isolated its pages would write the one
    layout the analyzer is guaranteed not to look for.
    """
    opts_in = re.findall(r"_download_flat_async\([^)]*isolate_pages=", TEXT, re.S)
    assert len(opts_in) == 1, (
        f"exactly one caller may opt in, found {len(opts_in)}")
    fallback = TEXT.index("Modules tab is hidden/unauthorized")
    after = TEXT[fallback:fallback + 1800]
    call = after.index("_download_flat_async(")
    assert "isolate_pages" not in after[call:call + 400], (
        "the 401 fallback records modules mode; its pages must stay prefixed")


# --------------------------------------------------------------------------
# the mode reaches the expectation from the right place
# --------------------------------------------------------------------------

def test_the_isolate_flag_is_bound_unconditionally_in_download_course_async():
    """The bug this fix shipped with, for about ten minutes.

    ``isolate`` is a local of ``get_course_files_metadata``; the flat dispatch
    lives in ``download_course_async``, where the only spelling of the same
    idea was ``_iso`` - bound inside BOTH an ``if debug_mode:`` and an
    ``if secondary_content_settings:``. Reading either name at the dispatch
    raises ``UnboundLocalError``, which the engine catches and reports as a
    generic "Processing Error", so the whole course downloads nothing and the
    screen says only "cannot access local variable 'isolate'".

    Every unit test passed while that was true. It took one real download to
    find, which is the entire argument for verifying in the running app.
    """
    import ast
    tree = ast.parse(TEXT)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "download_course_async")

    # every name bound anywhere in the function, and where
    assigns = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigns.setdefault(t.id, []).append(node.lineno)

    assert "_isolate_secondary" in assigns, (
        "download_course_async must bind its own isolate flag")

    # ...and it must not be nested inside a conditional, which is what made
    # `_iso` unusable.
    def _guarded(target_line):
        for node in ast.walk(fn):
            if isinstance(node, (ast.If, ast.Try)):
                body = [c for c in ast.walk(node) if hasattr(c, "lineno")]
                if any(c.lineno == target_line for c in body):
                    return True
        return False

    assert not _guarded(assigns["_isolate_secondary"][0]), (
        "_isolate_secondary is bound inside an if/try - the same trap as _iso")

    used = TEXT[TEXT.index("if mode == 'flat':"):]
    call = used[:used.index("_download_flat_async(") + 400]
    assert "isolate_pages=_isolate_secondary" in call, (
        "the dispatch must use the unconditionally-bound name")


def test_metadata_entry_points_accept_the_mode():
    for fn in (cl.CanvasManager.get_course_files_metadata,
               cl.CanvasManager._get_files_from_modules):
        assert "download_mode" in inspect.signature(fn).parameters, (
            f"{fn.__name__} must be told the mode; without it the expectation "
            f"silently falls back to the non-isolated shape")


def test_sync_reads_the_mode_the_FOLDER_was_built_in():
    """Not the mode a fresh download would choose.

    A folder built in flat mode keeps its layout for ever; asking
    `detect_structure()` or a live setting would change the expected path under
    a folder that never moved, which is the "every page is new" failure.
    """
    src = (REPO / "sync" / "analysis.py").read_text(encoding="utf-8")
    i = src.index("_built_mode")
    assert "_load_metadata('download_mode')" in src[i:i + 200]
    assert "download_mode=_built_mode" in src


def test_the_download_scan_passes_the_mode_it_is_about_to_use():
    src = (REPO / "app.py").read_text(encoding="utf-8")
    i = src.index("is_scanning_phase=True")
    assert "download_mode=" in src[i:i + 200]
