"""Office container staging must not hand the app a LONG filename.

Found on real macOS 15, 2026-08-10, by driving the actual Word converter with a
positive control and a fresh Word per case:

    name 104 bytes  -> CONVERTED
    name 168 bytes  -> FAILED   active document doesn't understand the
                                "save as" message (-1708)
    everything above 168 -> FAILED

It is the filename COMPONENT, not the total path: a 763-byte path with a 9-byte
name converts, and a 180-byte name fails at a 200-byte total path even with
staging neutralised. macOS itself allows 255 bytes per component, so the limit is
Word's.

``office_container_stage`` used ``work / src.name``, i.e. it shortened the
DIRECTORY (which was never the problem) and preserved the NAME (which was), so it
could not help - and Canvas filenames of that length are ordinary, since lecture
titles carry the course and week in them. The failure was silent per file.

Staging now uses a fixed short basename. The real name is only ever needed at the
final destination, which this function moves the product to itself, so nothing is
lost. Verified live after the change: a 240-byte name CONVERTS and the PDF lands
under its real long name.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine.applescript_bridge as AB  # noqa: E402

LONG = "L" * 236                        # 240 bytes with the extension


@pytest.fixture
def container(tmp_path, monkeypatch):
    """Force the staging branch on, whatever platform the suite runs on.

    Off macOS ``_office_container_tmp`` returns None and staging degrades to a
    pass-through, so without this the test would assert nothing on Windows/Linux
    while claiming to cover the fix.
    """
    root = tmp_path / "container"
    root.mkdir()
    monkeypatch.setattr(AB, "_office_container_tmp", lambda *a, **k: root)
    return root


def test_the_staged_source_name_is_short_and_independent_of_the_real_one(
        container, tmp_path):
    src = tmp_path / (LONG + ".doc")
    src.write_bytes(b"doc")
    dst = tmp_path / (LONG + ".pdf")

    with AB.office_container_stage(src, dst, "Word") as (s_src, s_dst):
        assert len(s_src.name) <= 16, (
            f"staged source name is {len(s_src.name)} bytes; Word fails past "
            f"~168, and a long name is exactly what staging must not preserve")
        assert len(s_dst.name) <= 16, f"staged dest name is {len(s_dst.name)}"
        assert LONG not in s_src.name and LONG not in s_dst.name
        assert s_src.exists(), "the source must still be copied into the stage"


def test_the_suffixes_are_preserved_because_office_picks_its_filter_from_them(
        container, tmp_path):
    """A staged name of `src` with no extension would change what Office does:
    the importer comes from the source suffix and the exporter from the
    destination's. Shortening the basename must not touch either."""
    for ext, out in ((".doc", ".pdf"), (".xls", ".pdf"), (".ppt", ".pdf"),
                     (".rtf", ".pdf")):
        src = tmp_path / (LONG + ext)
        src.write_bytes(b"x")
        dst = tmp_path / (LONG + out)
        with AB.office_container_stage(src, dst, "Word") as (s_src, s_dst):
            assert s_src.suffix == ext, f"{ext} lost its suffix: {s_src.name}"
            assert s_dst.suffix == out, f"{out} lost its suffix: {s_dst.name}"


#: What Office would produce. It has to be a PLAUSIBLE PDF, not a 16-byte
#: stand-in, because the promotion is now gated on `converters.verify`
#: (>= 512 bytes and a %PDF magic) - a conversion that errors part-way still
#: leaves whatever Office had written, and promoting that both orphaned a stub
#: in the user's folder and destroyed the good PDF a previous run had made.
#: Using a real-shaped product here means this test also proves the gate ACCEPTS
#: one, which is the half a rejection test cannot show.
REAL_PDF = b"%PDF-1.4\n" + b"%\xe2\xe3\xcf\xd3\n" + b"0" * 600 + b"\n%%EOF\n"


def test_the_product_still_lands_under_the_REAL_long_name(container, tmp_path):
    """The whole point: Office writes a short name, the user gets the real one."""
    src = tmp_path / (LONG + ".doc")
    src.write_bytes(b"doc")
    dst = tmp_path / (LONG + ".pdf")

    with AB.office_container_stage(src, dst, "Word") as (s_src, s_dst):
        s_dst.write_bytes(REAL_PDF)

    assert dst.exists(), "the product was not moved back to the real name"
    assert dst.read_bytes() == REAL_PDF
    assert not s_dst.exists(), "staging dir should be cleaned up"


def test_two_concurrent_stagings_cannot_collide_on_the_fixed_basename(
        container, tmp_path):
    """The basenames are now constants, so isolation rests entirely on the uuid
    work dir. Assert that rather than assume it - a shared stage dir would make
    two conversions overwrite each other's source."""
    a = tmp_path / ("A" * 200 + ".doc")
    b = tmp_path / ("B" * 200 + ".doc")
    for p in (a, b):
        p.write_bytes(p.name[:1].encode())

    with AB.office_container_stage(a, tmp_path / "a.pdf", "Word") as (sa, _):
        with AB.office_container_stage(b, tmp_path / "b.pdf", "Word") as (sb, _):
            assert sa.parent != sb.parent, "two stagings shared a work dir"
            assert sa.read_bytes() == b"A" and sb.read_bytes() == b"B"


def test_staging_still_degrades_to_a_passthrough_with_no_container(tmp_path,
                                                                  monkeypatch):
    """Unchanged behaviour when the container is unavailable - the documented
    'never worse than before' path, which is also how non-macOS behaves."""
    monkeypatch.setattr(AB, "_office_container_tmp", lambda *a, **k: None)
    src = tmp_path / (LONG + ".doc")
    src.write_bytes(b"doc")
    dst = tmp_path / (LONG + ".pdf")
    with AB.office_container_stage(src, dst, "Word") as (s_src, s_dst):
        assert s_src == src and s_dst == dst


# ---------------------------------------------------------------------------
# fp:ad96dfaae9ad - a filename carrying a CR could never be converted on macOS
#
# `applescript_string` renders a line break as a SPACE, which is the right rule
# for a MESSAGE (deleting it would silently join two words of a name shown to
# the user) and the WRONG one for a PATH: the emitted script stays syntactically
# valid but now names a file that does not exist, so Word cannot open it. The
# failure was silent - one file simply got no PDF.
#
# It is fixed INCIDENTALLY, by the short-basename staging above: the hostile
# name never reaches AppleScript, because the app is handed `src_<hex>.<ext>`
# inside its own container and the product is moved to the real destination
# afterwards. Re-measured on macOS 26.6.1 on 2026-08-20 against the REAL Word
# converter, fresh Word and a positive control per case - 13/13 converted:
#
#     CR, LF, embedded quote, backslash, a 250-BYTE component,
#     Danish + emoji  -> all CONVERTED, PDF at the real path, source consumed
#
# So these tests exist to stop staging being removed or narrowed and silently
# re-opening it, NOT because the escaper was changed - it still cannot carry a
# line break, and that is still correct for its other callers.
LINE_BREAK_NAMES = ["Lec\rture.doc", "Lec\nture.doc", "a\r\nb.doc"]


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows forbids CR/LF in a filename, so the fixture cannot be "
           "built - src.write_bytes raises OSError [Errno 22] before any "
           "product code runs. The path under test is the macOS AppleScript "
           "literal, which does not execute on Windows anyway.",
)
@pytest.mark.parametrize("name", LINE_BREAK_NAMES)
def test_a_line_break_in_the_name_never_reaches_the_applescript_literal(
        container, tmp_path, name):
    src = tmp_path / name
    src.write_bytes(b"doc")
    dst = src.with_suffix(".pdf")

    with AB.office_container_stage(src, dst, "Word") as (s_src, s_dst):
        for staged in (s_src, s_dst):
            assert "\r" not in staged.name and "\n" not in staged.name, (
                f"staged name {staged.name!r} still carries a line break, so "
                f"applescript_string will replace it with a space and the "
                f"script will name a file that does not exist")
        # The literal must round-trip: what AppleScript is told to open has to
        # be exactly the file on disk. This is the assertion that fails if the
        # staged name ever goes back to carrying the real one.
        assert AB.applescript_string(s_src) == str(s_src)


def test_applescript_string_still_cannot_carry_a_line_break(tmp_path):
    """The sharp edge itself, pinned so it is not mistaken for safe.

    An AppleScript string literal cannot span lines, so this is not a bug to be
    fixed in the escaper - it is why a PATH must be staged rather than escaped.
    """
    p = tmp_path / "Lec\rture.doc"
    assert AB.applescript_string(p) != str(p)
    assert "\r" not in AB.applescript_string(p)


# ---------------------------------------------------------------------------
# The guard above only holds if the converters actually USE what staging yields.
# Counting the sites is the lesson this repo has paid for twice - `pdf_looks_real`
# was written for two delete sites and landed on one for eight months - so this
# asserts the property for ALL THREE converters rather than the one a fix
# happened to touch.
import ast                                                      # noqa: E402

CONVERTERS = {
    "converters/word.py": "Word",
    "converters/excel.py": "Excel",
    "converters/pdf.py": "PowerPoint",
}
REPO = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("relpath,app", sorted(CONVERTERS.items()))
def test_the_converter_escapes_the_STAGED_path_not_the_real_one(relpath, app):
    """`_as_posix(...)` must be handed the names bound by `office_container_stage`.

    Passing the ORIGINAL `src`/`dst` is what re-opens fp:ad96dfaae9ad (a line
    break in the name) and the long-name failure together, and it looks
    completely reasonable in review - the two names differ by two characters.
    """
    tree = ast.parse((REPO / relpath).read_text(encoding="utf-8"))

    staged_names, escaped_args, found_stage = set(), [], False
    for node in ast.walk(tree):
        # `with office_container_stage(...) as (s_src, s_dst):`
        if isinstance(node, ast.withitem) and isinstance(node.context_expr, ast.Call):
            fn = node.context_expr.func
            if getattr(fn, "id", getattr(fn, "attr", None)) == "office_container_stage":
                found_stage = True
                if isinstance(node.optional_vars, ast.Tuple):
                    staged_names |= {e.id for e in node.optional_vars.elts
                                     if isinstance(e, ast.Name)}
        # `_as_posix(x)`
        if isinstance(node, ast.Call):
            fn = node.func
            if getattr(fn, "id", getattr(fn, "attr", None)) == "_as_posix":
                for a in node.args:
                    if isinstance(a, ast.Name):
                        escaped_args.append(a.id)

    assert found_stage, f"{relpath} no longer stages through office_container_stage"
    assert staged_names, f"{relpath} does not bind the staged (src, dst) pair"
    assert escaped_args, f"{relpath} no longer escapes any path with _as_posix"
    leaked = [a for a in escaped_args if a not in staged_names]
    assert not leaked, (
        f"{relpath} escapes {leaked} into the AppleScript instead of the staged "
        f"{sorted(staged_names)} - the real filename would reach the literal, "
        f"where a line break becomes a space and a long name breaks Word")
