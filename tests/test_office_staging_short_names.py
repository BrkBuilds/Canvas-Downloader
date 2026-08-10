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


def test_the_product_still_lands_under_the_REAL_long_name(container, tmp_path):
    """The whole point: Office writes a short name, the user gets the real one."""
    src = tmp_path / (LONG + ".doc")
    src.write_bytes(b"doc")
    dst = tmp_path / (LONG + ".pdf")

    with AB.office_container_stage(src, dst, "Word") as (s_src, s_dst):
        s_dst.write_bytes(b"%PDF-1.4 pretend")     # what Office would produce

    assert dst.exists(), "the product was not moved back to the real name"
    assert dst.read_bytes() == b"%PDF-1.4 pretend"
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
