"""A blocked or failed extraction must not leave a stray folder behind.

``extract_archive`` creates the target folder BEFORE it can read the archive's
member list, so every guard that trips afterwards (the zip-bomb ratio check, the
zip-slip / tar path-traversal blocks, a corrupt archive) used to leave an empty
directory sitting next to the untouched archive. ``_decline`` already exists for
exactly this reason on the ``max_files`` path and states it in its docstring -
the exception path simply never called it.

``_decline`` uses ``os.rmdir``, which removes ONLY an empty directory. That is
what makes this safe for a PARTIAL extraction: anything already written keeps
the folder, and the folder stays.
"""
import zipfile

from converters.archive import extract_archive


def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    return path


def test_a_blocked_path_traversal_leaves_no_folder_behind(tmp_path):
    archive = _zip(tmp_path / "evil.zip",
                   [("../../ESCAPED.txt", "pwned"), ("ok.txt", "fine")])

    assert extract_archive(archive) is None
    assert not (tmp_path / "evil").exists(), "stray folder left after a blocked extraction"
    assert archive.exists(), "the archive itself must be untouched"
    assert not (tmp_path / "ESCAPED.txt").exists()
    assert not (tmp_path.parent / "ESCAPED.txt").exists()


def test_an_absolute_member_path_is_blocked_and_cleans_up(tmp_path):
    archive = tmp_path / "abs.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(zipfile.ZipInfo("C:/Windows/Temp/canvas_dl_pwn.txt"), "pwned")

    assert extract_archive(archive) is None
    assert not (tmp_path / "abs").exists()
    assert archive.exists()


def test_a_corrupt_archive_leaves_no_folder_behind(tmp_path):
    archive = tmp_path / "broken.zip"
    archive.write_bytes(b"PK\x03\x04 this is not a real zip file at all")

    assert extract_archive(archive) is None
    assert not (tmp_path / "broken").exists()
    assert archive.exists()


# ── What must NOT change ──────────────────────────────────────────────────────

def test_a_good_archive_still_extracts_and_the_archive_is_consumed(tmp_path):
    archive = _zip(tmp_path / "good.zip",
                   [("a.txt", "hello"), ("sub/b.txt", "world")])

    assert extract_archive(archive) is True
    out = tmp_path / "good"
    assert (out / "a.txt").read_text() == "hello"
    assert (out / "sub" / "b.txt").read_text() == "world"
    assert not archive.exists(), "a successfully extracted archive is deleted"


def test_an_archive_whose_every_member_is_filtered_keeps_both_archive_and_no_folder(tmp_path):
    """The 2026-08-06 finding: __MACOSX-only archives produced nothing, and the
    user's only copy was deleted to show for it. Still holds."""
    archive = _zip(tmp_path / "maconly.zip", [("__MACOSX/._x", "junk")])

    assert extract_archive(archive) is None
    assert archive.exists(), "the archive must be kept when nothing came out"
    assert not (tmp_path / "maconly").exists()


def test_a_partial_extraction_keeps_what_it_managed_to_write(tmp_path, monkeypatch):
    """rmdir only removes an EMPTY directory, so cleanup can never discard
    files a half-finished extraction already produced."""
    archive = _zip(tmp_path / "partial.zip",
                   [("first.txt", "kept"), ("second.txt", "never")])

    real_extract = zipfile.ZipFile.extract
    state = {"n": 0}

    def flaky(self, member, path=None, pwd=None):
        state["n"] += 1
        if state["n"] > 1:
            raise OSError("simulated: disk full mid-extraction")
        return real_extract(self, member, path, pwd)

    monkeypatch.setattr(zipfile.ZipFile, "extract", flaky)

    assert extract_archive(archive) is None
    out = tmp_path / "partial"
    assert out.exists(), "cleanup removed a folder that still held extracted files"
    assert (out / "first.txt").read_text() == "kept"
    assert archive.exists(), "a failed extraction must not delete the archive"
