"""A skip-existing re-download must not rewrite the edit-protection baseline.

``original_md5`` means **what we downloaded**. It is the sole basis of the
app's headline promise - `_classify_local_modification` compares the file on
disk against it to decide 'clean' (safe to overwrite) or 'modified' (preserve
as `_NewVersion`).

``record_downloaded_file`` is called after EVERY file of a download, including
the ones that were skipped because they already existed
(`core/canvas_logic.py`, "Sync Run #0: Record skipped-but-existing files"), and
those callers pass no md5. It used to hash the file on disk and store that -
so a re-download rewrote the baseline to the file's CURRENT content.

MEASURED 2026-08-20, driving the real class:

    first download        baseline = md5(original bytes)
    student edits it      classification -> 'modified'      (protected)
    re-download course    baseline = md5(the EDIT)
                          classification -> 'clean'         (NOT protected)

'clean' is the verdict that lets the next sync overwrite the file, and
`_NewVersion` cannot fire because it reads this row. The edit has to preserve
the file's SIZE, because a size change is what makes the download take the
overwrite branch instead of the skip branch - so this is narrow, but it is
silent and it defeats the one guarantee the product makes about your own work.

The SAME line had a second, certain cost on macOS: hashing reads the file, and
reading an evicted iCloud file MATERIALISES it. Re-running a download over a
folder macOS had evicted pulled the whole course back down - measured 19 of 19
untouched files, against 0 of 22 for the sync path. See
`tests/test_icloud_dataless.py`.

The fix prefers the baseline the row already holds, and only hashes when there
is none - which is what keeps the original promise that a baseline is never
silently dropped.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import core.sync_manager as SM  # noqa: E402
from core.sync_manager import CanvasFileInfo, SyncManager  # noqa: E402

ORIGINAL = b"the original bytes as downloaded from canvas."
EDITED = b"the student's own annotation of the lecture.."
assert len(EDITED) == len(ORIGINAL), "the edit must preserve SIZE to be realistic"


@pytest.fixture
def tracked(tmp_path):
    """One downloaded, tracked file with a real md5 baseline."""
    f = tmp_path / "Lecture.txt"
    f.write_bytes(ORIGINAL)
    sm = SyncManager(str(tmp_path), 4242, "baseline")
    man = sm.load_manifest()
    sm.add_file_to_manifest(
        man,
        CanvasFileInfo(id=1, filename=f.name, display_name=f.name,
                       size=len(ORIGINAL), modified_at="2020-01-01T00:00:00Z",
                       url="https://example/1"),
        f.name, local_md5=hashlib.md5(ORIGINAL).hexdigest())
    return sm, f


def _baseline(sm) -> str:
    return sm.load_manifest()["files"]["1"]["original_md5"]


def _skip_existing_rerecord(sm, f):
    """Exactly what the download engine does for a file it decided to SKIP."""
    sm.record_downloaded_file(
        canvas_file_id=1, canvas_filename=f.name, local_path=f.name,
        canvas_updated_at="2020-01-01T00:00:00Z", original_size=len(ORIGINAL),
        local_md5="")


def test_a_redownload_does_not_rewrite_the_baseline_over_an_edit(tracked):
    """THE data-loss case."""
    sm, f = tracked
    f.write_bytes(EDITED)
    assert SyncManager._classify_local_modification(f, _baseline(sm)) == "modified"

    _skip_existing_rerecord(sm, f)

    assert _baseline(sm) == hashlib.md5(ORIGINAL).hexdigest(), (
        "the baseline was rewritten from the file on disk - it now records the "
        "student's edit as if we had downloaded it")
    assert SyncManager._classify_local_modification(f, _baseline(sm)) == "modified", (
        "the edit lost its protection: 'clean' is what lets the next sync "
        "overwrite it, and _NewVersion cannot fire because it reads this row")


def test_a_redownload_of_an_unedited_file_keeps_the_baseline(tracked):
    sm, f = tracked
    _skip_existing_rerecord(sm, f)
    assert _baseline(sm) == hashlib.md5(ORIGINAL).hexdigest()
    assert SyncManager._classify_local_modification(f, _baseline(sm)) == "clean"


def test_a_skip_existing_rerecord_does_not_READ_the_file(tracked, monkeypatch):
    """The iCloud half: reading an evicted file materialises it, so a
    re-download used to pull an entire course back onto a small SSD."""
    sm, f = tracked
    calls: list[str] = []
    real = SM.compute_local_md5
    monkeypatch.setattr(SM, "compute_local_md5",
                        lambda p: (calls.append(Path(p).name), real(p))[1])
    monkeypatch.setattr(SyncManager, "compute_local_md5",
                        staticmethod(SM.compute_local_md5))
    _skip_existing_rerecord(sm, f)
    assert calls == [], (
        f"hashed {calls} although the row already holds a baseline - on an "
        f"evicted iCloud folder that is a silent re-download per file")


def test_a_row_with_NO_baseline_is_still_hashed(tmp_path):
    """The promise that must survive the fix: a baseline is never silently
    dropped. Reachable on a folder from before baselines existed, and on a
    first download over files that were already there."""
    g = tmp_path / "Legacy.txt"
    g.write_bytes(ORIGINAL)
    sm = SyncManager(str(tmp_path), 4242, "baseline")
    sm.record_downloaded_file(canvas_file_id=7, canvas_filename=g.name,
                              local_path=g.name,
                              canvas_updated_at="2020-01-01T00:00:00Z",
                              original_size=len(ORIGINAL), local_md5="")
    assert sm.load_manifest()["files"]["7"]["original_md5"] == \
        hashlib.md5(ORIGINAL).hexdigest()


def test_a_FRESH_write_still_hashes_its_own_bytes(tmp_path):
    """`clear_ignored=True` is the existing fresh-vs-skip discriminator and is
    what carries this decision. A secondary HTML/URL render just WROTE those
    bytes, so they are ours and hashing them is correct - reusing a stale
    baseline there would describe the previous render."""
    h = tmp_path / "Assignment.html"
    body = b"<html>freshly rendered</html>"
    h.write_bytes(body)
    sm = SyncManager(str(tmp_path), 4242, "baseline")
    sm.record_downloaded_file(canvas_file_id=-9, canvas_filename=h.name,
                              local_path=h.name,
                              canvas_updated_at="2020-01-01T00:00:00Z",
                              original_size=len(body), local_md5="",
                              clear_ignored=True)
    assert sm.load_manifest()["files"]["-9"]["original_md5"] == \
        hashlib.md5(body).hexdigest()


def test_a_fresh_render_REPLACING_an_older_one_updates_the_baseline(tmp_path):
    """The direction the fix must NOT break: a regenerated entity's baseline
    has to follow its new bytes, or the next sync compares against the old
    render and reports a phantom edit for ever."""
    h = tmp_path / "Assignment.html"
    first = b"<html>render one</html>"
    h.write_bytes(first)
    sm = SyncManager(str(tmp_path), 4242, "baseline")
    sm.record_downloaded_file(-9, h.name, h.name, "2020-01-01T00:00:00Z",
                              len(first), local_md5="", clear_ignored=True)
    second = b"<html>render two, longer</html>"
    h.write_bytes(second)
    sm.record_downloaded_file(-9, h.name, h.name, "2021-01-01T00:00:00Z",
                              len(second), local_md5="", clear_ignored=True)
    assert sm.load_manifest()["files"]["-9"]["original_md5"] == \
        hashlib.md5(second).hexdigest()


def test_an_explicit_md5_always_wins(tracked):
    """The fresh-byte download path hashes inline and passes it; that must
    never be second-guessed by the stored row."""
    sm, f = tracked
    new = b"x" * len(ORIGINAL)
    f.write_bytes(new)
    sm.record_downloaded_file(1, f.name, f.name, "2020-01-01T00:00:00Z",
                              len(new), local_md5=hashlib.md5(new).hexdigest())
    assert _baseline(sm) == hashlib.md5(new).hexdigest()


def test_the_SIBLING_writer_has_no_unclassified_caller():
    """`add_file_to_manifest` hashes from disk whenever no md5 is passed, and
    that is CORRECT for its two callers - but only because of a fact about
    them, not about it.

    Flagged for review on 2026-09-11 as the same shape as the defect this file
    exists for, and investigated on 2026-09-12. It does not reproduce:

      * `sync/execution.py:1128` - the real file download - passes
        `local_md5=_dl_hasher.hexdigest()`, the bytes just pulled off the
        network. The disk hash never runs.
      * `sync/execution.py:1735` - the synthetic shortcut / Canvas Page path -
        passes nothing, and every route to it WRITES the file immediately
        above: the real page HTML, else the redirect stub, else the `.url`
        shortcut. A path with nothing to write hits `continue` and never
        reaches the call.

    So the unconditional hash always hashes bytes the app itself just wrote,
    which is the right baseline - the same distinction that made the fix in
    `record_downloaded_file` correct.

    **The invariant is stated in that docstring and enforced nowhere**, and
    that is exactly how its sibling acquired the bug: a third caller was added
    later which recorded skipped-but-existing files, and the docstring stayed
    true of the original two. This is the census, so a new caller has to be
    classified rather than assumed.
    """
    import ast

    repo = Path(__file__).resolve().parents[1]

    #: Call sites allowed to omit `local_md5`, each with the reason it is safe.
    #: A site belongs here ONLY if the app writes the file's bytes immediately
    #: before the call, so hashing from disk records our own write.
    WRITES_ITS_OWN_BYTES = {
        'sync/execution.py': (
            "the synthetic shortcut / Page branch writes the file (real page "
            "HTML, redirect stub, or .url) immediately above the call, and a "
            "path with nothing to write `continue`s before reaching it"),
    }

    unclassified = []
    for path in sorted(repo.glob('**/*.py')):
        rel = path.relative_to(repo).as_posix()
        if rel.startswith(('tests/', 'dist/', 'build/', 'scripts/')):
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute)
                    and fn.attr == 'add_file_to_manifest'):
                continue
            passes_md5 = any(kw.arg == 'local_md5' for kw in node.keywords) \
                or len(node.args) >= 4
            if passes_md5 or rel in WRITES_ITS_OWN_BYTES:
                continue
            unclassified.append(f"{rel}:{node.lineno}")

    assert not unclassified, (
        f"{len(unclassified)} call site(s) of `add_file_to_manifest` pass no "
        f"`local_md5`, so the baseline is hashed FROM DISK, and they are not "
        f"classified as writing their own bytes: {unclassified}. If the site "
        f"records a file it did not just write, that hash is the file's "
        f"CURRENT content - which is how a student's edited file stops being "
        f"protected (see this module's docstring). Either pass the bytes' own "
        f"md5, or add the site to WRITES_ITS_OWN_BYTES with the reason.")


def test_a_row_that_EXISTS_with_an_empty_baseline_is_still_hashed(tmp_path):
    """The distinction the mutation pass forced.

    `get_manifest_baseline` returns None for a MISSING row and ``('', path)``
    for a row that exists carrying no md5 - and only the second case tells
    `_prev is not None` apart from `_prev[0]`. Trusting the empty string would
    mean a row that has never had a baseline can never acquire one, so the
    file's edit protection would stay dead for ever while every test about
    missing rows still passed.

    Reachable: rows written before baselines existed, and any path that stored
    "" because the file could not be read at the time.
    """
    g = tmp_path / "Legacy.txt"
    g.write_bytes(ORIGINAL)
    sm = SyncManager(str(tmp_path), 4242, "baseline")
    # a row that EXISTS but carries no md5
    sm.record_downloaded_file(canvas_file_id=11, canvas_filename=g.name,
                              local_path=g.name,
                              canvas_updated_at="2020-01-01T00:00:00Z",
                              original_size=len(ORIGINAL), local_md5="x" * 32)
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(str(sm.db_path))) as c, c:
        c.execute("UPDATE sync_manifest SET original_md5='' WHERE canvas_file_id=11")
    assert sm.get_manifest_baseline(11) == ("", g.name), "fixture did not arm the case"

    sm.record_downloaded_file(canvas_file_id=11, canvas_filename=g.name,
                              local_path=g.name,
                              canvas_updated_at="2020-01-01T00:00:00Z",
                              original_size=len(ORIGINAL), local_md5="")
    assert sm.load_manifest()["files"]["11"]["original_md5"] == \
        hashlib.md5(ORIGINAL).hexdigest(), (
        "a row with an empty baseline never acquires one - its edit protection "
        "stays dead for ever")
