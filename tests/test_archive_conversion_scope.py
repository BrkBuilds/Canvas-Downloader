"""A zip is unpacked. Its CONTENTS are never converted.

Decided 2026-07-29, and this file previously asserted the opposite - so read
the reasoning before changing it back.

The live audit found (2026-07-27, course BINTO1064U) that files extracted from
archives were skipped by every converter while the same file types at module
level converted normally. That was filed and fixed as a defect: conversion scope
was widened to include extracted trees.

It was right about the symptom and wrong about the cure. Measured afterwards on
one real lecture zip from course 45899 - a JavaScript project carrying
``node_modules``:

* **21,824** files extracted from a single archive;
* **11,818** of them a converter would rewrite;
* **9,730** of those landing on paths past Windows' 260-character limit
  (1,616 even in flat mode), because extracted member names are taken verbatim
  from the zip and converting one makes the name *longer*
  (``x.d.ts`` -> ``x.d_ts.txt``).

The Office half could never have worked at any depth: PowerPoint COM rejects a
long path **and** rejects the long-path prefix - both measured directly. There
was no version of "convert inside archives" that was correct on Windows.

Underneath the path arithmetic is the simpler argument. An archive is an opaque
payload the teacher uploaded. Unpacking it is a convenience; rewriting what is
inside - and DELETING the originals, which is what a source-consuming converter
does - is not something the user asked for. A student's ``.js`` inside their own
project should still be a ``.js``.

Both flows must agree, because the failure is silent either way: a folder
converted by one and not the other looks like churn on every later sync.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from converters.post_processing import _glob_files  # noqa: E402


def _tree(tmp_path: Path) -> dict:
    """A course folder holding one downloaded deck, one archive's unpacked
    contents - including a nested copy, which is how the real zips in
    BINTO1064U are shaped - and a file from an earlier run."""
    downloaded = tmp_path / "Module 1" / "Lecture.pptx"
    downloaded.parent.mkdir(parents=True)
    downloaded.write_bytes(b"deck")

    root = tmp_path / "Module 1" / "Opgaver"          # <archive>.with_suffix('')
    inner = root / "Opgaver"
    inner.mkdir(parents=True)
    unpacked_deck = inner / "Kapitel 1.pptx"
    unpacked_code = inner / "solution.js"
    unpacked_deck.write_bytes(b"deck")
    unpacked_code.write_bytes(b"console.log(1)")

    stray = tmp_path / "Module 2" / "NotThisRun.pptx"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"deck")

    return {"folder": tmp_path, "downloaded": downloaded, "root": root,
            "unpacked_deck": unpacked_deck, "unpacked_code": unpacked_code,
            "stray": stray}


# --------------------------------------------------------------------------
# the rule
# --------------------------------------------------------------------------

def test_extracted_files_are_NOT_converted(tmp_path):
    """The whole decision, in one assertion."""
    t = _tree(tmp_path)
    found = _glob_files(t["folder"], {".pptx"}, [str(t["downloaded"])])
    assert t["downloaded"] in found
    assert t["unpacked_deck"] not in found


def test_extracted_code_is_NOT_converted(tmp_path):
    """The 11,818-file case: a project tree inside a zip stays a project tree.
    Converting it would replace each source with a .txt and delete the original -
    breaking the very code the student is meant to run."""
    t = _tree(tmp_path)
    found = _glob_files(t["folder"], {".js"}, [str(t["downloaded"])])
    assert t["unpacked_code"] not in found


def test_the_downloaded_file_beside_the_archive_still_converts(tmp_path):
    """The rule is about where a file CAME FROM, not where it sits. A deck the
    downloader wrote into the same module folder is unaffected."""
    t = _tree(tmp_path)
    assert _glob_files(t["folder"], {".pptx"}, [str(t["downloaded"])]) == [t["downloaded"]]


def test_scope_still_excludes_files_from_other_runs(tmp_path):
    """Unchanged: explicit_files is what stops a re-run re-converting a whole
    folder, and that is still its job."""
    t = _tree(tmp_path)
    found = _glob_files(t["folder"], {".pptx"}, [str(t["downloaded"])])
    assert t["stray"] not in found


def test_a_tree_unpacked_by_an_EARLIER_run_is_also_excluded(tmp_path):
    """No marker, no bookkeeping, no expiry. Extracted files were never
    downloaded, so they are never in either flow's file list - which is why the
    exclusion holds for an archive unpacked last week just as well as one
    unpacked a second ago."""
    t = _tree(tmp_path)
    found = _glob_files(t["folder"], {".pptx", ".js"}, [str(t["downloaded"])])
    assert t["unpacked_deck"] not in found
    assert t["unpacked_code"] not in found


# --------------------------------------------------------------------------
# both flows, and the guard that makes the rule hold
# --------------------------------------------------------------------------

def test_the_download_flow_never_runs_post_processing_unscoped():
    """_glob_files converts the WHOLE folder when explicit_files is empty, so an
    unscoped call would sweep up every previously-extracted tree. app.py skips
    post-processing outright rather than calling with an empty list, and that
    guard is load-bearing for this rule."""
    src = (REPO / "app.py").read_text(encoding="utf-8")
    i = src.index("if _run_files:")
    assert "invoke_post_processing(" in src[i:i + 900]


def test_the_sync_flow_converts_only_this_runs_synced_files():
    """`_from_archives` used to add extracted trees to every converter's input.
    It now returns this run's synced files and nothing else - the name is kept
    because all eight converters call it, so the two flows cannot drift."""
    src = (REPO / "sync" / "execution.py").read_text(encoding="utf-8")
    i = src.index("def _from_archives(")
    body = src[i:src.index("_items = _from_archives(", i)]
    code = re.sub(r"^\s*#.*$", "", body, flags=re.M)
    assert "return list(get_synced_file_paths(target_exts, conversion_key))" in code
    assert "iter_extracted_files" not in code, \
        "sync must not walk extracted trees for conversion candidates"


def test_neither_flow_feeds_extracted_roots_to_a_converter():
    """The reversal, asserted at the only two places it could come back."""
    pp = (REPO / "converters" / "post_processing.py").read_text(encoding="utf-8")
    sync = (REPO / "sync" / "execution.py").read_text(encoding="utf-8")
    assert "explicit_files, extracted_roots)" not in pp
    assert "iter_extracted_files" not in sync


def test_archives_are_still_EXTRACTED():
    """Unpacking is unchanged - only conversion of the contents stopped. A
    change that quietly disabled extraction too would look identical from the
    converters' side and be a far bigger regression."""
    pp = (REPO / "converters" / "post_processing.py").read_text(encoding="utf-8")
    assert "def run_archive_extraction" in pp
    sync = (REPO / "sync" / "execution.py").read_text(encoding="utf-8")
    assert "run_archive_extraction(" in sync


# --------------------------------------------------------------------------
# the exclusions that predate this rule still apply to ordinary files
# --------------------------------------------------------------------------

def test_package_dirs_are_still_filtered(tmp_path):
    d = tmp_path / "node_modules" / "pkg"
    d.mkdir(parents=True)
    f = d / "index.js"
    f.write_text("x", encoding="utf-8")
    assert _glob_files(tmp_path, {".js"}, [str(f)]) == []


def test_partial_artifacts_are_still_filtered(tmp_path):
    f = tmp_path / "Lecture.part.pptx"
    f.write_bytes(b"x")
    assert _glob_files(tmp_path, {".pptx"}, [str(f)]) == []


def test_office_lock_files_are_still_filtered(tmp_path):
    f = tmp_path / "~$Lecture.pptx"
    f.write_bytes(b"x")
    assert _glob_files(tmp_path, {".pptx"}, [str(f)]) == []
