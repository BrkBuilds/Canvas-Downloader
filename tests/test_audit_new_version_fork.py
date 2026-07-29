"""A file the app forked to ``_NewVersion`` is untracked ON PURPOSE.

When a sync would overwrite a file you have edited - or one that is open in
another program - the engine writes the fresh copy as
``<stem>_NewVersion<ext>`` and leaves yours alone. The completion screen says
so: "Saved next to your copy, which was left untouched." The manifest row then
follows the NEW copy, because that is what the app's download of the Canvas
file now is, and your edited original ends up with no row.

The untracked-files check called that "wrongfully shows up as new" at HIGH
severity, on every row seeding ``edited_update``. Its stated consequence was
testable, so it was tested rather than argued about: seed an edited file, sync,
then sync the SAME FOLDER again.

    pass 1   review -> tick updated_modified -> confirm
             on disk: Page Numbers ... .docx            18,680 B  (the user's)
                      Page Numbers ..._NewVersion.docx  18,634 B  (from Canvas)
             manifest: 1627501 -> ..._NewVersion.docx

    pass 2   landed on COMPLETE, not review:
             "Sync done - everything up to date.
              Checked 50 files in this course - your folder already matches
              Canvas."

It is never re-offered. The premise was false; the product keeps the promise
its own screen makes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness import crosscheck        # noqa: E402


def _file(rel, **kw):
    d = {"rel": rel, "name": Path(rel).name, "ext": Path(rel).suffix,
         "size": 10, "md5": "m", "app_generated": False, "partial": False,
         "secondary_html": False, "new_version": "_NewVersion" in rel}
    d.update(kw)
    return d


def _ev(*rels, tracked=()):
    disk = {"exists": True, "files": [_file(r) for r in rels],
            "content_count": len(rels), "partials": [], "zero_bytes": [],
            "long_paths": [], "app_generated": [], "secondary_html": [],
            "dirs": [], "duplicate_groups": []}
    rows = [{"canvas_file_id": 1, "canvas_filename": Path(t).name,
             "local_path": t, "original_size": 10, "original_md5": "m",
             "is_ignored": False, "content_sig": "", "canvas_updated_at": "",
             "downloaded_at": ""} for t in tracked]
    return crosscheck.Evidence(folder=Path("/x"), disk=disk,
                               db={"exists": True, "rows": rows,
                                   "contracts": {"sync": {}}},
                               log={}, ui={}, canvas={}, expect={}, scenario="s")


REAL = "Course description including examination rules/Page Numbers for 6th and 5th Edition"


# --------------------------------------------------------------------------
# the fork is recognised by its sibling
# --------------------------------------------------------------------------

def test_the_original_beside_a_new_version_is_recognised():
    ev = _ev(f"{REAL}.docx", f"{REAL}_NewVersion.docx")
    assert crosscheck._new_version_originals(ev) == {
        crosscheck._key(f"{REAL}.docx")}


def test_a_folder_with_no_fork_recognises_nothing():
    assert crosscheck._new_version_originals(_ev("a/b.pdf")) == set()


@pytest.mark.parametrize("ext", [".docx", ".pdf", ".pptx", ".md"])
def test_every_extension_pairs_correctly(ext):
    ev = _ev(f"notes{ext}", f"notes_NewVersion{ext}")
    assert crosscheck._key(f"notes{ext}") in crosscheck._new_version_originals(ev)


def test_a_file_with_no_extension_still_pairs():
    ev = _ev("README", "README_NewVersion")
    assert crosscheck._key("README") in crosscheck._new_version_originals(ev)


def test_the_fork_is_found_from_the_SIBLING_not_the_manifest():
    """The whole point is that the original no longer has a row, so any rule
    that consults the manifest for it cannot work."""
    ev = _ev(f"{REAL}.docx", f"{REAL}_NewVersion.docx",
             tracked=[f"{REAL}_NewVersion.docx"])
    assert crosscheck._new_version_originals(ev)


# --------------------------------------------------------------------------
# and it is exempt from the untracked check
# --------------------------------------------------------------------------

def _high(ev):
    return [f.title for f in crosscheck.invariants(ev) if f.severity == "high"]


def test_the_regression_a_forked_original_is_not_a_persistence_defect():
    ev = _ev(f"{REAL}.docx", f"{REAL}_NewVersion.docx",
             tracked=[f"{REAL}_NewVersion.docx"])
    assert not any("no manifest row" in t for t in _high(ev)), _high(ev)


def test_a_genuinely_orphaned_file_is_still_reported():
    """The exemption must not blanket every untracked file - an orphan with no
    _NewVersion sibling is the real 'wrongfully shows up as new'."""
    ev = _ev("Modules/orphan.pdf", tracked=[])
    assert any("no manifest row" in t for t in _high(ev)), _high(ev)


def test_only_the_matching_stem_is_excused():
    """A fork of one file must not excuse an unrelated orphan beside it."""
    ev = _ev(f"{REAL}.docx", f"{REAL}_NewVersion.docx", "Modules/orphan.pdf",
             tracked=[f"{REAL}_NewVersion.docx"])
    assert any("no manifest row" in t for t in _high(ev))


def test_the_new_version_file_itself_was_already_exempt():
    """It carries the disk oracle's own new_version flag."""
    ev = _ev(f"{REAL}_NewVersion.docx", tracked=[])
    assert not any("no manifest row" in t for t in _high(ev)), _high(ev)
