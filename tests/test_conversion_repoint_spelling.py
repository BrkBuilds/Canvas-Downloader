"""A conversion's manifest repoint must not depend on how a path is SPELLED.

Found by the live macOS audit, 2026-08-21, in a real packaged run of course
43660: **62 of the 63 Office files converted in that run left their manifest row
pointing at the source file the converter had just deleted.** The single one
that repointed correctly was an Excel file - and ``converters/excel.py`` is the
only one of the three Office converters that does not call ``resolve()`` on the
path it returns.

The mechanism, in one line: ``Path.relative_to`` is a STRING operation.
``converters/pdf.py`` and ``converters/word.py`` return
``str(dst.resolve().absolute())`` from their macOS branch, while
``sm.local_path`` carries whatever spelling the download destination was
configured with.  Wherever the course folder is reached through a symlink -
``/tmp`` -> ``/private/tmp``, ``/var`` -> ``/private/var``, or a course folder
linked onto an external drive, which is an ordinary thing for the small-SSD
student this product is aimed at - the two spellings differ, ``relative_to``
raises, and BOTH call sites swallowed it without a word.

Why it matters rather than being untidy bookkeeping:

* a row still pointing at a deleted source is re-offered as a **restore** on
  every later sync, so the user is asked to re-download files they already have
  as PDFs;
* the converted PDF has no row at all, so it is an untracked orphan - and a
  re-download followed by a re-conversion overwrites it, which is how a
  student's annotated PDF is lost;
* the same spelling mismatch in ``_resolve_conversion_target`` loses the "own
  product" ownership check, which is what stops a conversion overwriting a file
  the entry does not own.

The regression guard is therefore about the PROPERTY - a repoint survives any
spelling of the same location - and not about the current fallback.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from converters.post_processing import (           # noqa: E402
    _course_relative,
    _update_manifest_path,
)
from core.sync_manager import SyncManager          # noqa: E402


# ----------------------------------------------------------------------------
# fixtures
# ----------------------------------------------------------------------------

def _symlinks_available(tmp_path: Path) -> bool:
    """Can this process actually CREATE a symlink here?

    ``hasattr(Path, "symlink_to")`` is the wrong question and was silently the
    wrong answer for every Windows run: the attribute always exists there, and
    the call fails at run time with ``WinError 1314`` ("a required privilege is
    not held") unless the account is elevated or Developer Mode is on. So the
    six symlink tests below did not skip, they FAILED - in fixture setup, before
    reaching any product code, which reads exactly like the repoint guard being
    gone. Probe the capability instead of the attribute.
    """
    probe = tmp_path / "_symlink_probe"
    target = tmp_path / "_symlink_probe_target"
    try:
        target.mkdir(exist_ok=True)
        probe.symlink_to(target)
    except (OSError, NotImplementedError, AttributeError):
        return False
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    return True


def _make_course(tmp_path: Path, *, through_symlink: bool) -> tuple[Path, Path]:
    """Return ``(root_for_sm, real_course_dir)``.

    ``through_symlink`` is the whole point: it reproduces a course folder whose
    configured path and whose realpath disagree, which is what the packaged run
    hit.

    The capability check lives HERE rather than as a decorator on each test,
    because only one of the six symlink tests ever carried one - so five were
    unguarded, and a seventh added later would be unguarded too. The helper is
    the one place every symlink test must pass through.
    """
    real = tmp_path / "real"
    real.mkdir()
    course = real / "Course"
    course.mkdir()
    if through_symlink:
        if not _symlinks_available(tmp_path):
            pytest.skip("this account cannot create symlinks "
                        "(Windows needs elevation or Developer Mode)")
        link = tmp_path / "via_link"
        link.symlink_to(real)
        return link / "Course", course
    return course, course


def _seed_manifest(course: Path, rel: str, canvas_file_id: int = 4242) -> None:
    """A single manifest row, written the way the engine writes one."""
    src = course / rel
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"original bytes")
    sm = SyncManager(str(course), 43660)
    sm.record_downloaded_file(
        canvas_file_id=canvas_file_id,
        canvas_filename=Path(rel).name,
        local_path=rel,          # the engine relativises before recording
        canvas_updated_at="2026-01-01T00:00:00Z",
        original_size=src.stat().st_size,
    )


def _row(course: Path, canvas_file_id: int = 4242) -> str:
    con = sqlite3.connect(course / ".canvas_sync.db")
    try:
        got = con.execute(
            "select local_path from sync_manifest where canvas_file_id=?",
            (canvas_file_id,)).fetchone()
    finally:
        con.close()
    return got[0] if got else ""


REL = "Tema 2 Uformelle træk/Lektion uge 41 - upload.pptx"


# ----------------------------------------------------------------------------
# the defect, in the shape it actually shipped
# ----------------------------------------------------------------------------

def test_repoint_survives_a_course_root_reached_through_a_symlink(tmp_path):
    """THE regression. Pre-fix this left the row on the deleted .pptx."""
    root, course = _make_course(tmp_path, through_symlink=True)
    _seed_manifest(course, REL)

    sm = SyncManager(str(root), 43660)
    src = root / REL
    pdf = src.with_suffix(".pdf")
    pdf.write_bytes(b"%PDF-1.4\n" + b"x" * 4000)
    src.unlink()                       # every source-consuming converter does this

    # Exactly what converters/pdf.py and converters/word.py hand back.
    _update_manifest_path(sm,
                          Path(str(src.resolve().absolute())),
                          Path(str(pdf.resolve().absolute())))

    assert _row(course).endswith(".pdf"), (
        "the manifest row still points at the source the converter deleted - "
        "the next sync will re-offer it as a restore and the PDF is untracked")


def test_repoint_still_works_on_a_plain_root(tmp_path):
    """The quiet direction: a check that only ever fires is not a check."""
    root, course = _make_course(tmp_path, through_symlink=False)
    _seed_manifest(course, REL)

    sm = SyncManager(str(root), 43660)
    src = root / REL
    pdf = src.with_suffix(".pdf")
    pdf.write_bytes(b"%PDF-1.4\n" + b"x" * 4000)
    src.unlink()

    _update_manifest_path(sm, src, pdf)
    assert _row(course).endswith(".pdf")


def test_the_unresolved_spelling_still_works(tmp_path):
    """excel.py returns ``str(dst)`` unresolved - that path must keep working."""
    root, course = _make_course(tmp_path, through_symlink=True)
    _seed_manifest(course, REL)

    sm = SyncManager(str(root), 43660)
    src = root / REL
    pdf = src.with_suffix(".pdf")
    pdf.write_bytes(b"%PDF-1.4\n" + b"x" * 4000)
    src.unlink()

    _update_manifest_path(sm, src, pdf)          # no resolve() anywhere
    assert _row(course).endswith(".pdf")


# ----------------------------------------------------------------------------
# the primitive
# ----------------------------------------------------------------------------

def test_course_relative_agrees_across_spellings(tmp_path):
    root, course = _make_course(tmp_path, through_symlink=True)
    sm = SyncManager(str(root), 43660)
    target = root / REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x")

    plain = _course_relative(sm, target)
    resolved = _course_relative(sm, Path(str(target.resolve().absolute())))
    assert plain == resolved == REL.replace("\\", "/")


def test_course_relative_is_defined_on_a_path_that_no_longer_exists(tmp_path):
    """``original_file`` is ALWAYS gone by the time the repoint runs."""
    root, course = _make_course(tmp_path, through_symlink=True)
    sm = SyncManager(str(root), 43660)
    gone = root / REL                            # never created
    assert _course_relative(sm, gone) == REL.replace("\\", "/")
    assert _course_relative(
        sm, Path(str(gone.parent.resolve() / gone.name))) == REL.replace("\\", "/")


def test_course_relative_refuses_a_path_genuinely_outside(tmp_path):
    """Robustness must not become "relativise anything"."""
    root, course = _make_course(tmp_path, through_symlink=False)
    sm = SyncManager(str(root), 43660)
    outside = tmp_path / "elsewhere" / "x.pdf"
    assert _course_relative(sm, outside) is None


def test_course_relative_tolerates_a_manager_without_a_root():
    class _NoRoot:
        local_path = None
    assert _course_relative(_NoRoot(), Path("/x/y.pdf")) is None
    assert _course_relative(object(), Path("/x/y.pdf")) is None


# ----------------------------------------------------------------------------
# the silence is the reason it shipped, so the noise is part of the fix
# ----------------------------------------------------------------------------

def test_a_path_outside_the_course_is_reported_not_swallowed(tmp_path, caplog):
    root, course = _make_course(tmp_path, through_symlink=False)
    _seed_manifest(course, REL)
    sm = SyncManager(str(root), 43660)

    with caplog.at_level("WARNING"):
        _update_manifest_path(sm, tmp_path / "elsewhere" / "a.pptx",
                              tmp_path / "elsewhere" / "a.pdf")

    assert any("manifest was not repointed" in r.getMessage()
               for r in caplog.records), \
        "the pre-fix code returned here in total silence, which is why 62 " \
        "stale rows shipped unnoticed"


def test_repoint_never_raises_out_of_a_conversion(tmp_path):
    """Bookkeeping must not undo work that already succeeded."""
    class _Exploding:
        local_path = tmp_path
        def load_manifest(self):
            raise sqlite3.OperationalError("database is locked")

    _update_manifest_path(_Exploding(), tmp_path / "a.pptx", tmp_path / "a.pdf")


# ----------------------------------------------------------------------------
# the OTHER call site, where a spelling miss costs more than bookkeeping
# ----------------------------------------------------------------------------

def test_own_product_is_recognised_through_a_symlinked_root(tmp_path):
    """``_resolve_conversion_target`` must find the row, or ownership is lost.

    When the lookup misses, the function falls through to "the default name
    exists and is not mine" and diverts to ``<stem> (1).pdf``. Two costs, and
    the second is the serious one: the folder grows a new ``(n)`` file on every
    re-conversion, and the ownership check that would have noticed the student
    had ANNOTATED the previous product - diverting it to ``_NewVersion`` - never
    runs at all.
    """
    from converters.post_processing import _resolve_conversion_target

    root, course = _make_course(tmp_path, through_symlink=True)
    _seed_manifest(course, REL)

    sm = SyncManager(str(root), 43660)
    src = root / REL
    pdf = src.with_suffix(".pdf")
    pdf.write_bytes(b"%PDF-1.4\n" + b"x" * 4000)
    # Record it as THIS entry's own product, the way a previous run would have.
    sm.update_converted_file(4242, str(pdf.relative_to(root)).replace("\\", "/"))
    # The NEXT run re-downloads the source, which repoints the row back at the
    # .pptx while the recorded product stays - the exact state post-processing
    # sees, and the reason the product md5 is stored beside its path.
    src.write_bytes(b"freshly downloaded")
    sm.record_downloaded_file(
        canvas_file_id=4242, canvas_filename=src.name,
        local_path=REL, canvas_updated_at="2026-02-02T00:00:00Z",
        original_size=src.stat().st_size)

    got = Path(_resolve_conversion_target(sm, src, ".pdf"))
    assert got.name == pdf.name, (
        f"diverted to {got.name!r} instead of overwriting its own product - "
        "the ownership lookup missed because of path spelling")


def test_a_rootless_manager_refuses_even_a_path_under_the_cwd(tmp_path):
    """Falling back to a root of '.' is not a harmless default.

    A manager with no ``local_path`` knows nothing about where the course is,
    so every answer it gives is a guess. Treating the missing root as ``"."``
    quietly relativises anything that happens to sit under the process's
    working directory - which for the packaged app is wherever it was launched
    from - and writes that guess into the manifest.
    """
    class _NoRoot:
        local_path = None

    under_cwd = Path.cwd() / "some_file.pdf"
    assert _course_relative(_NoRoot(), under_cwd) is None


def test_own_product_is_recognised_when_the_SOURCE_arrives_resolved(tmp_path):
    """The same spelling-independence, pinned at the ownership site.

    Today the conversion runners walk the course folder and so hand this
    function a path spelled like ``sm.local_path``, which is why this site
    survived while its neighbour broke. That is an accident of the current
    callers, not a property of the function - and the neighbour proves what it
    costs when a caller does resolve(). Pinning it here means a converter that
    starts returning resolved paths cannot silently disable the ownership check
    that protects an annotated PDF.
    """
    from converters.post_processing import _resolve_conversion_target

    root, course = _make_course(tmp_path, through_symlink=True)
    _seed_manifest(course, REL)

    sm = SyncManager(str(root), 43660)
    src = root / REL
    pdf = src.with_suffix(".pdf")
    pdf.write_bytes(b"%PDF-1.4\n" + b"x" * 4000)
    sm.update_converted_file(4242, str(pdf.relative_to(root)).replace("\\", "/"))
    src.write_bytes(b"freshly downloaded")
    sm.record_downloaded_file(
        canvas_file_id=4242, canvas_filename=src.name,
        local_path=REL, canvas_updated_at="2026-02-02T00:00:00Z",
        original_size=src.stat().st_size)

    resolved_src = Path(str(src.resolve().absolute()))
    got = Path(_resolve_conversion_target(sm, resolved_src, ".pdf"))
    assert got.name == pdf.name, (
        f"diverted to {got.name!r}: a resolved source path disabled the "
        "ownership lookup, so the next conversion would mint a (n) copy and "
        "skip the local-edit check entirely")
