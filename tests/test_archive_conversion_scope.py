"""Files unpacked from an archive must be converted like any other file.

Found by the live audit on 2026-07-27 (course BINTO1064U, every converter
enabled): 11,872 code files and 7 .pptx were extracted from zips and then
silently skipped by every converter, while the same file types sitting at
module level converted normally.

Root cause: the DOWNLOAD path passes ``explicit_files`` - the list of paths the
downloader itself wrote - and ``_glob_files`` scoped every converter to that
set. Archive extraction runs first and CREATES files that were never
downloaded, so nothing after it could see them. The SYNC path passes no
explicit list at all, so it globbed the whole folder and converted them fine -
the same contract produced two different results depending on which flow you
came from.

These tests pin both halves: the scope now includes extracted content, and it
still excludes everything the explicit list was introduced to exclude.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from converters.post_processing import _glob_files  # noqa: E402


def _tree(tmp_path: Path) -> dict:
    """A course folder holding one downloaded deck, one archive, and its
    unpacked contents - including a nested copy, which is how the real zips in
    BINTO1064U are shaped."""
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


def test_extracted_files_are_in_scope(tmp_path):
    t = _tree(tmp_path)
    found = _glob_files(t["folder"], {".pptx"},
                        explicit_files=[str(t["downloaded"])],
                        extracted_roots=[t["root"]])
    assert t["unpacked_deck"] in found, (
        "a .pptx unpacked from an archive was skipped by the converter")
    assert t["downloaded"] in found


def test_extracted_code_files_are_in_scope(tmp_path):
    t = _tree(tmp_path)
    found = _glob_files(t["folder"], {".js"},
                        explicit_files=[str(t["downloaded"])],
                        extracted_roots=[t["root"]])
    assert t["unpacked_code"] in found


def test_scope_still_excludes_files_from_other_runs(tmp_path):
    """The reason ``explicit_files`` exists: a re-download must not re-convert
    the whole folder. Widening it for extracted content must not widen it for
    anything else."""
    t = _tree(tmp_path)
    found = _glob_files(t["folder"], {".pptx"},
                        explicit_files=[str(t["downloaded"])],
                        extracted_roots=[t["root"]])
    assert t["stray"] not in found


def test_without_extracted_roots_the_old_behaviour_holds(tmp_path):
    """Guards the regression itself: with no roots supplied, unpacked content is
    invisible. If this ever passes, the roots are being ignored."""
    t = _tree(tmp_path)
    found = _glob_files(t["folder"], {".pptx"},
                        explicit_files=[str(t["downloaded"])])
    assert t["unpacked_deck"] not in found
    assert t["downloaded"] in found


def test_no_explicit_list_means_whole_folder(tmp_path):
    """The sync path. It never had the bug and must keep behaving the same."""
    t = _tree(tmp_path)
    found = _glob_files(t["folder"], {".pptx"})
    assert {t["downloaded"], t["unpacked_deck"], t["stray"]} <= set(found)


def test_package_dirs_still_filtered_inside_archives(tmp_path):
    """An unpacked node_modules must stay out - that filter is why a code course
    does not produce 40,000 .txt files."""
    t = _tree(tmp_path)
    vendored = t["root"] / "node_modules" / "left-pad" / "index.js"
    vendored.parent.mkdir(parents=True)
    vendored.write_bytes(b"module.exports = 1")
    found = _glob_files(t["folder"], {".js"},
                        explicit_files=[str(t["downloaded"])],
                        extracted_roots=[t["root"]])
    assert vendored not in found
    assert t["unpacked_code"] in found


def test_partial_artifacts_still_filtered_inside_archives(tmp_path):
    t = _tree(tmp_path)
    partial = t["root"] / "Opgaver" / "half.pptx.part"
    partial.write_bytes(b"x")
    found = _glob_files(t["folder"], {".part"},
                        explicit_files=[str(t["downloaded"])],
                        extracted_roots=[t["root"]])
    assert partial not in found


def test_run_archive_extraction_reports_its_roots():
    """The fix depends on extraction telling the caller where it wrote.

    A signature change here (back to returning None) would disable the whole
    thing silently, because ``extracted_roots`` would just stay empty.
    """
    import inspect
    from converters.post_processing import run_archive_extraction
    src = inspect.getsource(run_archive_extraction)
    assert "return extracted_roots" in src
    assert "extracted_roots.append" in src


def test_iter_extracted_files_applies_the_same_exclusions(tmp_path):
    """The shared helper both flows use. It must filter exactly like _glob_files,
    or a file unpacked during a SYNC would be treated differently from the same
    file unpacked during a DOWNLOAD."""
    from converters.post_processing import iter_extracted_files
    root = tmp_path / "Opgaver"
    (root / "node_modules" / "dep").mkdir(parents=True)
    (root / "__MACOSX").mkdir()
    (root / "sub").mkdir()
    keep = root / "sub" / "solution.js"
    keep.write_bytes(b"1")
    for junk in (root / "node_modules" / "dep" / "index.js",
                 root / "__MACOSX" / "resource.js",
                 root / "._hidden.js",
                 root / "half.js.part"):
        junk.write_bytes(b"1")

    found = iter_extracted_files(root, {".js"})
    names = {p.name for p in found}
    assert "solution.js" in names
    assert names == {"solution.js"}, f"leaked: {names - {'solution.js'}}"


def test_sync_flow_widens_scope_through_the_same_helper():
    """Sync must fix the archive gap the same way download does.

    Sync does not call run_all_conversions - it drives each converter itself -
    so the fix cannot be inherited. Both flows now route unpacked content
    through iter_extracted_files; if either stops, they diverge again and only
    one mode converts archive contents.
    """
    import inspect
    from sync import execution
    src = inspect.getsource(execution)
    assert "iter_extracted_files" in src, (
        "sync no longer widens its converter scope to unpacked files")
    assert "_from_archives" in src

    body = src[src.index("# Archive Extraction"):src.index("# --- Inject post-processing sidecars")]
    calls = []
    for ln in body.splitlines():
        s = ln.strip()
        if s.startswith("#") or "def " in s or "results = " in s:
            continue          # comments and the helper's own definition/body
        if "_from_archives(" in s or "get_synced_file_paths(" in s:
            calls.append(s)
    assert calls, "no converter selector calls found; the block moved"
    # The extraction call itself legitimately uses the un-widened selector: it
    # runs BEFORE anything is unpacked.
    for call in calls:
        if "'.zip'" in call:
            assert "get_synced_file_paths(" in call
        else:
            assert "_from_archives(" in call, (
                f"sync converter still scoped to downloaded files only: {call}")


def test_both_flows_share_one_converter_ordering():
    """Download and sync must run converters in the same order.

    The ordering is load-bearing in two places: extraction has to precede every
    converter so unpacked files are visible, and Excel data extraction has to
    precede Excel->PDF because the PDF step DELETES the .xlsx. Two hand-written
    orderings is how one flow silently loses a step.
    """
    import inspect
    from converters.post_processing import run_all_conversions
    from sync import execution

    def order(src, names):
        seen = []
        for line in src.splitlines():
            for n in names:
                if n + "(" in line and "def " not in line and "import" not in line:
                    if n not in seen:
                        seen.append(n)
        return seen

    names = ["run_archive_extraction", "run_pptx_conversion", "run_html_conversion",
             "run_code_conversion", "run_word_conversion",
             "run_excel_data_conversion", "run_excel_conversion",
             "run_video_conversion"]
    dl = order(inspect.getsource(run_all_conversions), names)
    sy_src = inspect.getsource(execution)
    sy = order(sy_src[sy_src.index("# Archive Extraction"):], names)

    assert dl.index("run_archive_extraction") == 0
    assert sy.index("run_archive_extraction") == 0
    for flow, seq in (("download", dl), ("sync", sy)):
        assert seq.index("run_excel_data_conversion") < seq.index("run_excel_conversion"), (
            f"{flow}: Excel PDF runs before data extraction; the PDF step deletes "
            f"the .xlsx, so the _Data.txt sidecar would be lost")
    assert dl == sy, (
        f"converter ORDER differs between flows.\n  download: {dl}\n  sync:     {sy}")


def test_converters_after_extraction_receive_the_roots():
    """Every converter that runs AFTER extraction must be passed the roots, and
    the archive glob itself must NOT be (it runs before anything is unpacked)."""
    import inspect
    from converters.post_processing import run_all_conversions
    src = inspect.getsource(run_all_conversions)
    calls = [ln.strip() for ln in src.splitlines() if "_glob_files(course_folder" in ln]
    assert calls, "converter globs moved; update this guard"
    for call in calls:
        if "archive_exts" in call:
            assert "extracted_roots" not in call, (
                "the archive glob must not see roots from its own run")
        else:
            assert "extracted_roots" in call, (
                f"converter glob missing extracted_roots, so unpacked files "
                f"will be skipped: {call}")
