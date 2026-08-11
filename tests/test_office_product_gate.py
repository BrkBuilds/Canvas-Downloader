"""A failed Office conversion must leave NOTHING behind.

THE DEFECT, found by the 2026-08-11 download matrix (O3 vs O4 - files on disk
with no manifest row) and confirmed by reading `office_container_stage`:

    yield staged_src, staged_dst
    # Success path: relocate the produced PDF back to its real destination.
    if staged_dst.exists():
        if dst.exists(): dst.unlink()
        shutil.move(str(staged_dst), str(dst))

The comment says "success path". The CONDITION is only that a file exists - and
a conversion that errors part-way still leaves whatever Office had written by
then. Two consequences, and the second is the worse one:

* an **870-byte "PDF"** landed in a course folder next to the .pptx it had
  failed to convert (measured, course 43660), tracked by nothing, so it is
  offered as a NEW file on every future sync for ever;
* `dst.unlink()` runs FIRST, so a failed re-conversion **destroyed the good PDF
  a previous run had produced** and replaced it with the stub.

The fix gates the promotion on the same `converters.verify` pair every
source-deleting converter already uses, at the promotion rather than in the
three converters - the counting rule from `pdf_looks_real` (two delete sites
needed two gates) is exactly why a per-converter version is the wrong shape.

Same class as `converters/archive.py:_decline` ("a declined extraction must
leave nothing behind"), in the module that fix did not reach.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import engine.applescript_bridge as AB  # noqa: E402

REAL_PDF = b"%PDF-1.4\n" + b"%\xe2\xe3\xcf\xd3\n" + b"0" * 600 + b"\n%%EOF\n"
STUB_PDF = b"%PDF-1.4\n"                      # the 870-byte artefact, in miniature
NOT_A_PDF = b"<html>Office wrote an error page</html>" * 40
EMPTY = b""


@pytest.fixture
def container(tmp_path, monkeypatch):
    root = tmp_path / "container"
    root.mkdir()
    monkeypatch.setattr(AB, "_office_container_tmp", lambda *a, **k: root)
    return root


def _convert(src: Path, dst: Path, product: bytes | None):
    """Drive one staged conversion that produces *product* (None = nothing)."""
    with AB.office_container_stage(src, dst, "Word") as (_s_src, s_dst):
        if product is not None:
            s_dst.write_bytes(product)


# --------------------------------------------------------------------------
# the staged path
# --------------------------------------------------------------------------

def test_a_real_product_is_still_promoted(container, tmp_path):
    """The control. A gate that rejects everything also 'fixes' the orphan."""
    src = tmp_path / "lecture.doc"
    src.write_bytes(b"doc")
    dst = tmp_path / "lecture.pdf"
    _convert(src, dst, REAL_PDF)
    assert dst.exists() and dst.read_bytes() == REAL_PDF


@pytest.mark.parametrize("product,label", [
    (STUB_PDF, "a truncated PDF"),
    (NOT_A_PDF, "a file that is not a PDF at all"),
    (EMPTY, "a 0-byte file"),
])
def test_a_reject_never_reaches_the_users_folder(container, tmp_path, product, label):
    src = tmp_path / "lecture.doc"
    src.write_bytes(b"doc")
    dst = tmp_path / "lecture.pdf"
    _convert(src, dst, product)
    assert not dst.exists(), (
        f"{label} was written into the course folder; nothing tracks it, so it "
        f"is offered as a new file on every future sync")


def test_a_reject_does_not_destroy_the_GOOD_pdf_from_an_earlier_run(container, tmp_path):
    """The half that is not merely untidy.

    The promotion unlinks the destination BEFORE moving, so a failed
    re-conversion of a file that converted fine last week replaced a good PDF
    with a stub. The user's folder went backwards.
    """
    src = tmp_path / "lecture.doc"
    src.write_bytes(b"doc")
    dst = tmp_path / "lecture.pdf"
    dst.write_bytes(REAL_PDF)                 # last week's good conversion
    _convert(src, dst, STUB_PDF)
    assert dst.exists(), "the previously-good PDF was deleted"
    assert dst.read_bytes() == REAL_PDF, "the good PDF was replaced by a stub"


def test_nothing_is_left_in_the_staging_dir_either(container, tmp_path):
    """`_decline`'s rule: a declined conversion leaves nothing anywhere."""
    src = tmp_path / "lecture.doc"
    src.write_bytes(b"doc")
    _convert(src, tmp_path / "lecture.pdf", STUB_PDF)
    assert not any(container.iterdir()), \
        f"staging litter left behind: {list(container.iterdir())}"


def test_producing_nothing_at_all_is_still_fine(container, tmp_path):
    src = tmp_path / "lecture.doc"
    src.write_bytes(b"doc")
    dst = tmp_path / "lecture.pdf"
    _convert(src, dst, None)
    assert not dst.exists()


# --------------------------------------------------------------------------
# the no-container path - Office writes STRAIGHT to the destination
# --------------------------------------------------------------------------

@pytest.fixture
def no_container(monkeypatch):
    monkeypatch.setattr(AB, "_office_container_tmp", lambda *a, **k: None)


def test_the_passthrough_still_yields_the_real_paths(no_container, tmp_path):
    """Unchanged contract - the documented 'never worse than before' path."""
    src, dst = tmp_path / "a.doc", tmp_path / "a.pdf"
    src.write_bytes(b"doc")
    with AB.office_container_stage(src, dst, "Word") as (s_src, s_dst):
        assert (s_src, s_dst) == (src, dst)


def test_direct_write_of_a_reject_is_removed_when_nothing_was_there(no_container,
                                                                    tmp_path):
    src, dst = tmp_path / "a.doc", tmp_path / "a.pdf"
    src.write_bytes(b"doc")
    with AB.office_container_stage(src, dst, "Word") as (_s, s_dst):
        s_dst.write_bytes(STUB_PDF)
    assert not dst.exists(), "an untracked stub was left in the course folder"


def test_direct_write_KEEPS_a_reject_that_overwrote_something(no_container, tmp_path):
    """Deliberately asymmetric.

    Office has already overwritten the old file and we cannot get it back.
    Deleting the reject would turn a damaged file into a MISSING one, and a
    manifest row may point at that path - so it is kept and reported.
    """
    src, dst = tmp_path / "a.doc", tmp_path / "a.pdf"
    src.write_bytes(b"doc")
    dst.write_bytes(REAL_PDF)
    with AB.office_container_stage(src, dst, "Word") as (_s, s_dst):
        s_dst.write_bytes(STUB_PDF)
    assert dst.exists(), "a file something may point at was deleted"


def test_direct_write_of_a_real_product_is_untouched(no_container, tmp_path):
    src, dst = tmp_path / "a.doc", tmp_path / "a.pdf"
    src.write_bytes(b"doc")
    with AB.office_container_stage(src, dst, "Word") as (_s, s_dst):
        s_dst.write_bytes(REAL_PDF)
    assert dst.read_bytes() == REAL_PDF


# --------------------------------------------------------------------------
# the gate itself
# --------------------------------------------------------------------------

def test_the_gate_uses_the_shared_verifier_not_a_local_rule():
    import inspect
    body = inspect.getsource(AB._product_is_real)
    assert "from converters.verify import" in body
    assert "pdf_looks_real" in body and "file_has_content" in body


def test_the_verify_import_is_function_scoped():
    """A module-level app import here makes a cycle: `shared.helpers` and
    `engine.notifications` both reach this module and it reaches them back."""
    import ast
    tree = ast.parse((REPO / "engine" / "applescript_bridge.py").read_text(
        encoding="utf-8"))
    for node in tree.body:                      # module level only
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            name = getattr(node, "module", "") or ""
            assert not name.startswith("converters"), \
                f"module-level import of {name} creates an import cycle"


def test_a_non_pdf_product_is_gated_on_content_not_on_magic(tmp_path):
    """The staging helper is generic. If a future converter stages a .csv or a
    .txt, the PDF magic must not be demanded of it - but emptiness still is."""
    good = tmp_path / "data.csv"
    good.write_bytes(b"a,b,c\n1,2,3\n")
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    assert AB._product_is_real(good) is True
    assert AB._product_is_real(empty) is False


def test_the_gate_answers_TRUE_if_the_verifier_cannot_be_imported(monkeypatch,
                                                                  tmp_path):
    """A cosmetic guard must never be able to swallow a good PDF. If the import
    fails we fall back to the pre-existing behaviour: promote it."""
    real = tmp_path / "x.pdf"
    real.write_bytes(STUB_PDF)                  # would normally be REJECTED
    import builtins
    orig = builtins.__import__

    def boom(name, *a, **k):
        if name == "converters.verify":
            raise ImportError("simulated")
        return orig(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    assert AB._product_is_real(real) is True
