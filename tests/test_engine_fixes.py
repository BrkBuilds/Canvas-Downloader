"""Regression tests for the 2026-07 engine audit fixes.

Covers the manifest/analyzer-level fixes that run fully offline:
  H-1  content-signature update detection for secondary entities
  H-4  atomic .part pattern for Panopto ffmpeg downloads
  H-7  ownership-aware conversion targets
  M-3  auto-discovery never claims an already-tracked local file
  M-4  weakest-tier discovery stores an empty md5 baseline
  M-6  teacher re-upload respects the user's local deletion
       + phantom-row pruning after the replacement is tracked
  M-12 fresh-byte downloads clear a stale is_ignored flag
  naming: preferred_disk_name display-name preference
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from core.sync_manager import (
    CanvasFileInfo, SyncManager, make_secondary_id, preferred_disk_name,
    secondary_content_sig,
)


@pytest.fixture()
def course_dir(tmp_path):
    d = tmp_path / "Algorithms 101"
    d.mkdir()
    return d


@pytest.fixture()
def sm(course_dir):
    return SyncManager(course_dir, course_id=4242, course_name="Algorithms 101")


def _write_local(course_dir, rel, content=b"hello world"):
    p = course_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def _cfile(id, filename, size=11, display_name=None, md5=None, sig="",
           modified="2026-07-01T10:00:00Z"):
    return CanvasFileInfo(
        id=id, filename=filename,
        display_name=display_name if display_name is not None else filename,
        size=size, modified_at=modified, url="https://x/f", md5=md5,
        content_sig=sig,
    )


# ── naming: preferred_disk_name ──────────────────────────────────────────────

def test_preferred_disk_name_prefers_display_name():
    f = _cfile(1, "final_v3_REAL2.pdf", display_name="Lecture 1 Slides")
    assert preferred_disk_name(f) == "Lecture 1 Slides.pdf"


def test_preferred_disk_name_locked_and_synthetic_keep_filename():
    locked = _cfile(9, "Assignment: A - doc.pdf", display_name="doc.pdf")
    locked.name_locked = True
    assert preferred_disk_name(locked) == "Assignment: A - doc.pdf"
    synth = _cfile(-5, "Page: X.html", display_name="X.html")
    assert preferred_disk_name(synth) == "Page: X.html"


def test_preferred_disk_name_appends_missing_extension():
    f = _cfile(2, "notes_v2.pdf", display_name="Week 1 Notes")
    assert preferred_disk_name(f) == "Week 1 Notes.pdf"


# ── H-1: content signatures ──────────────────────────────────────────────────

def test_content_sig_roundtrip_and_update_detection(sm, course_dir):
    syn_id = make_secondary_id("assignment", 42)
    _write_local(course_dir, "Assignments/Essay.html", b"<html>v1</html>")
    sm.record_downloaded_file(
        canvas_file_id=syn_id, canvas_filename="Essay.html",
        local_path="Assignments/Essay.html", canvas_updated_at="",
        original_size=0, content_sig=secondary_content_sig("assignment", "Essay", "v1"),
    )
    entry = sm.load_manifest()["files"][str(syn_id)]
    assert entry["content_sig"] == secondary_content_sig("assignment", "Essay", "v1")

    # Same signature → NOT newer (no phantom updates from timestamps)
    same = _cfile(syn_id, "Assignments/Essay.html", size=0,
                  sig=secondary_content_sig("assignment", "Essay", "v1"),
                  modified="2026-12-31T10:00:00Z")  # timestamp churn is ignored
    assert sm._is_canvas_newer(same, entry) is False

    # Changed signature → newer (real content change detected)
    changed = _cfile(syn_id, "Assignments/Essay.html", size=0,
                     sig=secondary_content_sig("assignment", "Essay", "v2"))
    assert sm._is_canvas_newer(changed, entry) is True

    # Missing signature on either side → stable (never a phantom update)
    unknown = _cfile(syn_id, "Assignments/Essay.html", size=0, sig="")
    assert sm._is_canvas_newer(unknown, entry) is False


def test_empty_sig_never_clobbers_stored_sig(sm, course_dir):
    syn_id = make_secondary_id("quiz", 7)
    _write_local(course_dir, "Quizzes/Q1.html")
    sm.record_downloaded_file(syn_id, "Q1.html", "Quizzes/Q1.html", "", 0,
                              content_sig="realsig")
    # A later record WITHOUT a sig (e.g. a legacy code path) must not wipe it
    sm.record_downloaded_file(syn_id, "Q1.html", "Quizzes/Q1.html", "", 0)
    assert sm.load_manifest()["files"][str(syn_id)]["content_sig"] == "realsig"

    # save_manifest with a stale in-memory (empty-sig) entry must not wipe either
    manifest = sm.load_manifest()
    manifest["files"][str(syn_id)]["content_sig"] = ""
    sm.save_manifest(manifest)
    assert sm.load_manifest()["files"][str(syn_id)]["content_sig"] == "realsig"


# ── M-12: is_ignored lifecycle ───────────────────────────────────────────────

def test_fresh_download_clears_stale_ignore(sm, course_dir):
    sm.ignore_file(55, "big.mp4", 999)
    assert sm.load_manifest()["files"]["55"]["is_ignored"] is True
    _write_local(course_dir, "big.mp4", b"x" * 10)
    # Fresh-byte download (clear_ignored=True) → flag cleared
    sm.record_downloaded_file(55, "big.mp4", "big.mp4", "", 10, clear_ignored=True)
    assert sm.load_manifest()["files"]["55"]["is_ignored"] is False


def test_skip_existing_rerecord_still_preserves_ignore(sm, course_dir):
    _write_local(course_dir, "keep.pdf")
    sm.record_downloaded_file(66, "keep.pdf", "keep.pdf", "", 11)
    sm.ignore_file(66, "keep.pdf", 11)
    # skip-existing path re-records WITHOUT clear_ignored → preserved
    sm.record_downloaded_file(66, "keep.pdf", "keep.pdf", "", 11)
    assert sm.load_manifest()["files"]["66"]["is_ignored"] is True


# ── M-3: discovery never claims a tracked file ───────────────────────────────

def test_discovery_skips_already_tracked_paths(sm, course_dir):
    _write_local(course_dir, "notes.pdf", b"a" * 20)
    sm.record_downloaded_file(1, "notes.pdf", "notes.pdf", "2026-01-01T00:00:00Z", 20)
    manifest = sm.load_manifest()

    canvas_files = [
        _cfile(1, "notes.pdf", size=20),           # the tracked file
        _cfile(3, "notes.pdf", size=20),           # NEW id, same name+size
    ]
    result = sm.analyze_course(canvas_files, manifest, cm=None, download_mode="flat")
    # id=3 must NOT be "discovered" onto the file id=1 already owns - it is new.
    new_ids = {f.id for f in result.new_files}
    assert 3 in new_ids
    up_ids = {c.id for c, _ in result.uptodate_files}
    assert 1 in up_ids


# ── M-4: weakest-tier discovery stores an EMPTY baseline ─────────────────────

def test_size_ext_discovery_stores_empty_baseline(sm, course_dir):
    # No manifest rows. One local pdf; canvas file has same size+ext but a
    # DIFFERENT name and no md5 → only the size+ext tier can match.
    _write_local(course_dir, "myrenamed.pdf", b"b" * 33)
    manifest = sm.load_manifest()
    canvas_files = [_cfile(9, "original_name.pdf", size=33)]
    result = sm.analyze_course(canvas_files, manifest, cm=None, download_mode="flat")
    up_ids = {c.id for c, _ in result.uptodate_files}
    assert 9 in up_ids
    entry = manifest["files"]["9"]
    assert entry["original_md5"] == ""  # bias to preserve on next update


def test_name_match_discovery_keeps_real_baseline(sm, course_dir):
    _write_local(course_dir, "slides.pdf", b"c" * 15)
    manifest = sm.load_manifest()
    canvas_files = [_cfile(4, "slides.pdf", size=15)]
    result = sm.analyze_course(canvas_files, manifest, cm=None, download_mode="flat")
    assert {c.id for c, _ in result.uptodate_files} == {4}
    assert manifest["files"]["4"]["original_md5"] != ""


# ── M-6: teacher re-upload respects local deletion + phantom pruning ────────

def test_reupload_routes_to_locally_deleted(sm, course_dir):
    # User downloaded a.pdf (id=1), then deleted it locally. Teacher deleted
    # the Canvas file and re-uploaded the same name under id=2.
    sm.record_downloaded_file(1, "a.pdf", "a.pdf", "2026-01-01T00:00:00Z", 11)
    manifest = sm.load_manifest()
    canvas_files = [_cfile(2, "a.pdf", size=11)]
    result = sm.analyze_course(canvas_files, manifest, cm=None, download_mode="flat")

    assert result.new_files == []                      # not offered as new
    assert result.updated_clean_files == []            # NOT auto-resurrected
    assert len(result.locally_deleted_files) == 1      # respected deletion
    del_info = result.locally_deleted_files[0]
    assert del_info.canvas_file_id == 1
    # The NEW canvas object rides along for a user-selected redownload
    assert getattr(del_info, "_reupload_new_file").id == 2


def test_reupload_with_local_file_present_keeps_both(sm, course_dir):
    # The user still HAS the old file → the same-named new file is genuinely new.
    _write_local(course_dir, "a.pdf", b"x" * 11)
    sm.record_downloaded_file(1, "a.pdf", "a.pdf", "2026-01-01T00:00:00Z", 11)
    manifest = sm.load_manifest()
    canvas_files = [
        _cfile(1, "a.pdf", size=11),
        _cfile(2, "a.pdf", size=999),  # different size → no discovery-claim
    ]
    result = sm.analyze_course(canvas_files, manifest, cm=None, download_mode="flat")
    assert {f.id for f in result.new_files} == {2}
    assert result.locally_deleted_files == []


def test_phantom_row_pruned_after_replacement_tracked(sm, course_dir):
    # Old id=1 row: gone from Canvas, gone from disk. Replacement id=2 row:
    # tracked, file on disk, still on Canvas. The stale row must be pruned
    # instead of resurfacing as "Deleted Locally" forever.
    sm.record_downloaded_file(1, "a.pdf", "a.pdf", "2026-01-01T00:00:00Z", 11)
    _write_local(course_dir, "a.pdf", b"y" * 11)
    sm.record_downloaded_file(2, "a.pdf", "a.pdf", "2026-02-01T00:00:00Z", 11)
    manifest = sm.load_manifest()
    canvas_files = [_cfile(2, "a.pdf", size=11)]
    result = sm.analyze_course(canvas_files, manifest, cm=None, download_mode="flat")

    assert result.locally_deleted_files == []
    assert "1" not in sm.load_manifest()["files"]      # row hard-deleted
    assert "2" in sm.load_manifest()["files"]


# ── H-7: ownership-aware conversion targets ──────────────────────────────────

def test_conversion_target_diverts_from_foreign_pdf(sm, course_dir):
    from converters.post_processing import _resolve_conversion_target
    src = _write_local(course_dir, "Week1.pptx", b"pptx")
    sm.record_downloaded_file(10, "Week1.pptx", "Week1.pptx", "", 4)
    # A teacher-provided PDF with the same stem already exists
    _write_local(course_dir, "Week1.pdf", b"teacher pdf")

    target = _resolve_conversion_target(sm, src, ".pdf")
    assert target.name == "Week1 (1).pdf"              # never clobbered


def test_conversion_target_overwrites_own_product(sm, course_dir):
    from converters.post_processing import _resolve_conversion_target
    src = _write_local(course_dir, "Deck.pptx", b"pptx")
    sm.record_downloaded_file(11, "Deck.pptx", "Deck.pptx", "", 4)

    # First conversion: no collision → default target
    t1 = _resolve_conversion_target(sm, src, ".pdf")
    assert t1.name == "Deck.pdf"
    _write_local(course_dir, "Deck.pdf", b"converted v1")
    assert sm.update_converted_file(11, "Deck.pdf") is True

    # Update flow: sync re-downloaded Deck.pptx and re-pointed the row at it
    sm.record_downloaded_file(11, "Deck.pptx", "Deck.pptx", "", 4)
    src2 = _write_local(course_dir, "Deck.pptx", b"pptx v2")
    # Re-conversion may overwrite its OWN product in place
    t2 = _resolve_conversion_target(sm, src2, ".pdf")
    assert t2.name == "Deck.pdf"


def test_conversion_diverted_name_stays_stable(sm, course_dir):
    from converters.post_processing import _resolve_conversion_target
    src = _write_local(course_dir, "X.pptx", b"pptx")
    sm.record_downloaded_file(12, "X.pptx", "X.pptx", "", 4)
    _write_local(course_dir, "X.pdf", b"teacher pdf")

    t1 = _resolve_conversion_target(sm, src, ".pdf")
    assert t1.name == "X (1).pdf"
    _write_local(course_dir, "X (1).pdf", b"our product")
    assert sm.update_converted_file(12, "X (1).pdf") is True

    # Next update: row re-pointed at the fresh source again
    sm.record_downloaded_file(12, "X.pptx", "X.pptx", "", 4)
    t2 = _resolve_conversion_target(sm, src, ".pdf")
    assert t2.name == "X (1).pdf"                      # stable, no X (2).pdf


# ── H-4: Panopto ffmpeg .part pattern ────────────────────────────────────────

def _fake_ffmpeg_cmd(behavior: str, out_path: str) -> list[str]:
    """Build a command whose last arg is the output path (like real ffmpeg).

    behavior 'ok'      → writes bytes to the target and exits 0
             'fail'    → writes PARTIAL bytes to the target and exits 1
             'empty'   → writes nothing and exits 0
    """
    script = (
        "import sys\n"
        "mode, out = sys.argv[1], sys.argv[2]\n"
        "if mode in ('ok', 'fail'):\n"
        "    open(out, 'wb').write(b'MEDIA' * 100)\n"
        "sys.exit(0 if mode in ('ok', 'empty') else 1)\n"
    )
    return [sys.executable, "-c", script, behavior, out_path]


def test_ffmpeg_part_pattern_success(tmp_path):
    from panopto.stream import _run_ffmpeg_download
    out = tmp_path / "Lecture.mp3"
    ok, err = _run_ffmpeg_download(_fake_ffmpeg_cmd("ok", str(out)), str(out))
    assert ok is True and err is None
    assert out.exists() and out.stat().st_size > 0
    assert not (tmp_path / "Lecture.part.mp3").exists()


def test_ffmpeg_part_pattern_failure_leaves_no_partial(tmp_path):
    from panopto.stream import _run_ffmpeg_download
    out = tmp_path / "Lecture.mp3"
    ok, err = _run_ffmpeg_download(_fake_ffmpeg_cmd("fail", str(out)), str(out))
    assert ok is False and err
    # THE fix: neither a truncated final file nor a stray .part remains,
    # so classification can never mistake a failed download for a complete one.
    assert not out.exists()
    assert not (tmp_path / "Lecture.part.mp3").exists()


def test_ffmpeg_empty_output_is_failure(tmp_path):
    from panopto.stream import _run_ffmpeg_download
    out = tmp_path / "Lecture.mp4"
    ok, err = _run_ffmpeg_download(_fake_ffmpeg_cmd("empty", str(out)), str(out))
    assert ok is False
    assert not out.exists()


# ── misc: partial artifacts invisible to the analyzer ────────────────────────

def test_part_artifacts_ignored_by_analyzer(sm, course_dir):
    _write_local(course_dir, "Lecture.part.mp3", b"partial")
    _write_local(course_dir, "doc.pdf.part", b"partial")
    manifest = sm.load_manifest()
    result = sm.analyze_course([], manifest, cm=None, download_mode="flat")
    assert result.untracked_shortcuts == 0


def test_delete_manifest_rows(sm, course_dir):
    _write_local(course_dir, "z.pdf")
    sm.record_downloaded_file(77, "z.pdf", "z.pdf", "", 11)
    assert "77" in sm.load_manifest()["files"]
    assert sm.delete_manifest_rows([77]) is True
    assert "77" not in sm.load_manifest()["files"]


# ── page-id parity: download-then-sync must not duplicate module Pages ───────
# The download engine records module Pages by PAGE id (-page_id); the sync
# metadata scan historically emitted the MODULE ITEM id (-item.id), so a
# freshly-downloaded course re-analyzed for sync saw every page as "new" and
# downloaded " (1)" duplicates (2026-07-09 macOS run: 35 phantom-new files).
# Analysis now emits -page_id as primary and carries -item.id in
# CanvasFileInfo.legacy_sync_id for folders synced by older versions.

def _page_cfile(page_id, item_id, title="Kontortid", sig="pagesig-v1"):
    f = CanvasFileInfo(
        id=-page_id, filename=f"Page: {title}.html",
        display_name=f"{title}.html", size=0,
        modified_at="2026-07-01T10:00:00Z", url="https://x/p",
        content_type="text/html", content_sig=sig, name_locked=True,
        legacy_sync_id=-item_id,
    )
    return f


def test_downloaded_page_is_uptodate_in_sync_analysis(sm, course_dir):
    # Download convention: tracked under -page_id, healed to the converted .md
    # (the original .html is deleted by the HTML→MD converter).
    _write_local(course_dir, "Page Kontortid.md", b"# converted")
    sm.record_downloaded_file(-261465, "Page Kontortid.html",
                              "Page Kontortid.md", "", 0,
                              content_sig="pagesig-v1")
    manifest = sm.load_manifest()
    result = sm.analyze_course([_page_cfile(261465, 1102048)], manifest,
                               cm=None, download_mode="flat")
    assert result.new_files == []                       # the 35-phantom bug
    assert {c.id for c, _ in result.uptodate_files} == {-261465}
    assert result.deleted_on_canvas == []


def test_legacy_item_id_page_row_still_matches(sm, course_dir):
    # Folder synced by an OLDER version: page tracked under -item.id. The
    # legacy bridge must keep matching that row - no re-download, no deletion.
    _write_local(course_dir, "Page Kontortid.md", b"# converted")
    sm.record_downloaded_file(-1102048, "Page Kontortid.html",
                              "Page Kontortid.md", "", 0,
                              content_sig="pagesig-v1")
    manifest = sm.load_manifest()
    result = sm.analyze_course([_page_cfile(261465, 1102048)], manifest,
                               cm=None, download_mode="flat")
    assert result.new_files == []
    up = {info.canvas_file_id for _, info in result.uptodate_files}
    assert up == {-1102048}                             # stays on the legacy key
    assert result.deleted_on_canvas == []
    assert result.locally_deleted_files == []


# ── completion cards: resolve records to their CONVERTED on-disk files ───────

def test_synced_groups_resolve_converted_files(tmp_path):
    """synced_details carries pre-conversion names; the completion card must
    point at the converted product on disk (html→md, pptx→pdf, code→_ext.txt)
    instead of rendering a dead 'not found' row with the old name."""
    from sync.execution import _build_synced_groups

    root = tmp_path / "Course"
    root.mkdir()
    (root / "Page Kontortid.md").write_bytes(b"# md")          # was .html
    (root / "Deck.pdf").write_bytes(b"pdf")                    # was .pptx
    (root / "StudieTimerVejl_js.txt").write_bytes(b"code")     # was .js
    (root / "Plain.pdf").write_bytes(b"pdf")                   # untouched

    sel = {
        'pair_idx': 0,
        'redownload': [],
        'res_data': {
            'pair': {'local_folder': str(root), 'course_id': 1,
                     'course_name': 'Course'},
            'sync_manager': None,
            'result': None,
        },
    }
    synced_details = {0: ["Page Kontortid.html", "Deck.pptx",
                          "StudieTimerVejl.js", "Plain.pdf"]}
    groups = _build_synced_groups([sel], synced_details)
    assert len(groups) == 1
    by_rel = {f['rel'] for f in groups[0]['files']}
    assert by_rel == {"Page Kontortid.md", "Deck.pdf",
                      "StudieTimerVejl_js.txt", "Plain.pdf"}
    names = {f['name'] for f in groups[0]['files']}
    assert "Page Kontortid.md" in names          # display shows the real file
    assert "Page Kontortid.html" not in names


def test_synced_groups_use_actual_write_paths(tmp_path):
    """The display name and the on-disk name can diverge completely (module
    Pages: recorded "Filer til Klynge 1.html", written "Page Filer til
    Klynge 1 (1).html", converted to ...md). Resolution must start from the
    ACTUAL path the engine wrote (synced_actual_rels, 1:1 with the names) -
    the 2026-07-09 completion screen showed dead .html rows because it only
    ever looked at the display name."""
    from sync.execution import _build_synced_groups

    root = tmp_path / "Course"
    root.mkdir()
    # Converted after write: only the .md exists now.
    (root / "Page Filer til Klynge 1 (1).md").write_bytes(b"# md")
    # Written and NOT converted: exists exactly at its actual path.
    (root / "Page Uge 6 pensum.html").write_bytes(b"<html>")

    sel = {
        'pair_idx': 0,
        'redownload': [],
        'res_data': {
            'pair': {'local_folder': str(root), 'course_id': 1,
                     'course_name': 'Course'},
            'sync_manager': None,
            'result': None,
        },
    }
    synced_details = {0: ["Filer til Klynge 1.html", "Uge 6 pensum.html"]}
    actual_rels = {0: ["Page Filer til Klynge 1 (1).html",
                       "Page Uge 6 pensum.html"]}
    groups = _build_synced_groups([sel], synced_details, actual_rels)
    by_rel = {f['rel'] for f in groups[0]['files']}
    assert by_rel == {"Page Filer til Klynge 1 (1).md", "Page Uge 6 pensum.html"}
    names = {f['name'] for f in groups[0]['files']}
    assert names == {"Page Filer til Klynge 1 (1).md", "Page Uge 6 pensum.html"}


# ── restore routing: locally-deleted conversion products ─────────────────────

def test_redownload_target_exact_path_when_type_matches(tmp_path):
    """A plain restore (recorded ext == downloaded ext) claims the EXACT
    recorded path, surviving the user's folder reorganization."""
    from sync.execution import _redownload_target

    root = tmp_path / "Course"
    (root / "Week 1").mkdir(parents=True)
    fp, td = _redownload_target(root, "Week 1/Notes.pdf", "Notes.pdf")
    assert fp == root / "Week 1" / "Notes.pdf"
    assert td == root / "Week 1"


def test_redownload_target_conversion_product_restores_source(tmp_path):
    """The 2026-07-10 corrupt-restore bug: the manifest tracked the .pdf
    CONVERTED from a .pptx; restoring wrote raw PowerPoint bytes under the
    .pdf name (unreadable in Preview/Safari) and post-processing never saw a
    .pptx to convert. The restore must fetch the SOURCE into the recorded
    folder so the ownership-aware converter regenerates the product."""
    from sync.execution import _redownload_target

    root = tmp_path / "Course"
    root.mkdir()
    fp, td = _redownload_target(
        root, "Lektion uge 43_2 upload.pdf", "Lektion uge 43_2 upload.pptx")
    assert fp == root / "Lektion uge 43_2 upload.pptx"
    assert td == root
    # Same family: video→mp3 and page html→md products.
    fp, _ = _redownload_target(root, "Lecture.mp3", "Lecture.mp4")
    assert fp == root / "Lecture.mp4"
    fp, _ = _redownload_target(root, "Page Kontortid.md", "Page Kontortid.html")
    assert fp == root / "Page Kontortid.html"


def test_redownload_target_missing_parent_falls_back(tmp_path):
    """When the recorded parent folder no longer exists the helper defers to
    the caller's canonical calc_path fallback."""
    from sync.execution import _redownload_target

    root = tmp_path / "Course"
    root.mkdir()
    fp, td = _redownload_target(root, "Gone Folder/Notes.pdf", "Notes.pdf")
    assert (fp, td) == (None, None)


# ── effective (post-conversion) file type shown across the sync UI ───────────

def test_effective_ext_converts_per_contract():
    """A course whose contract converts must display the PRODUCT type
    (pptx→pdf etc.) so Smart Select, review rows and the Confirm dialog all
    tell one story (2026-07-10: pills said PPTX while the same rows said PDF)."""
    from shared.helpers import effective_ext

    on = {'convert_pptx': True, 'convert_word': True, 'convert_excel': True,
          'convert_video': True, 'convert_html': True, 'convert_code': True}
    assert effective_ext("Deck upload.pptx", on) == ".pdf"
    assert effective_ext("Deck upload.PPTM", on) == ".pdf"
    assert effective_ext("Notes.doc", on) == ".pdf"
    assert effective_ext("Grades.xlsx", on) == ".pdf"
    assert effective_ext("Lecture.mp4", on) == ".mp3"
    assert effective_ext("Page X.html", on) == ".md"
    assert effective_ext("script.py", on) == ".txt"
    # Types with no 1:1 conversion product keep their own extension.
    assert effective_ext("Real.pdf", on) == ".pdf"
    assert effective_ext("Archive.zip", on) == ".zip"


def test_effective_ext_respects_disabled_and_missing_contract():
    from shared.helpers import effective_ext

    off = {'convert_pptx': False, 'convert_video': False, 'convert_code': False}
    assert effective_ext("Deck.pptx", off) == ".pptx"
    assert effective_ext("Lecture.mp4", off) == ".mp4"
    # docx has NO converter (only legacy .doc/.rtf/.odt) - never relabeled.
    assert effective_ext("Essay.docx", {'convert_word': True}) == ".docx"
    assert effective_ext("no_extension", {'convert_pptx': True}) == ""
    assert effective_ext("", None) == ""


# ── page-stub fallback: restricted Pages LIST upgraded per slug ──────────────

def test_page_stub_upgrade_restores_download_identity():
    """When course.get_pages() is restricted (hidden Pages tab), the module
    scan emits Pages under the module-item fallback id. The per-slug stub
    fetch must upgrade the entry in place to the download engine's manifest
    identity (-page_id primary, -item.id legacy) - without it, every fresh
    download re-analyzed for sync shows all pages as "new" (the 2026-07-09
    35-phantom bug persisted BECAUSE page_meta was empty on this course)."""
    from types import SimpleNamespace
    from core.canvas_logic import CanvasManager, _apply_page_stub_upgrades

    cm = CanvasManager.__new__(CanvasManager)   # only _sanitize_filename used
    mi = CanvasFileInfo(
        id=-1102048, filename="Page: Kontortid.html",
        display_name="Kontortid.html", size=0,
        modified_at="2026-01-01T00:00:00Z", url="https://x/p",
        content_type="text/html", name_locked=True,
    )
    module_map = {-1102048: "Modul A"}
    stub = SimpleNamespace(page_id=261465,
                           title="Helle Zinner Henriksens Kontortid",
                           updated_at="2026-07-01T10:00:00Z")
    fixed = _apply_page_stub_upgrades(
        {"kontortid": [(mi, "kontortid", -1102048, "Modul A")]},
        [("kontortid", stub)], module_map, cm._sanitize_filename,
    )
    assert fixed == 1
    assert mi.id == -261465                       # download-engine identity
    assert mi.legacy_sync_id == -1102048          # old folders keep matching
    assert "Helle Zinner Henriksens Kontortid" in mi.display_name
    assert mi.content_sig                         # page sig (title+updated_at)
    assert mi.modified_at == "2026-07-01T10:00:00Z"
    assert module_map[-261465] == "Modul A"       # path routing registered


def test_page_stub_upgrade_failed_fetch_keeps_fallback_id():
    from core.canvas_logic import CanvasManager, _apply_page_stub_upgrades

    cm = CanvasManager.__new__(CanvasManager)
    mi = CanvasFileInfo(
        id=-1102048, filename="Page: Kontortid.html",
        display_name="Kontortid.html", size=0,
        modified_at="2026-01-01T00:00:00Z", url="https://x/p",
        content_type="text/html", name_locked=True,
    )
    module_map = {}
    fixed = _apply_page_stub_upgrades(
        {"kontortid": [(mi, "kontortid", -1102048, "Modul A")]},
        [("kontortid", None)], module_map, cm._sanitize_filename,
    )
    assert fixed == 0
    assert mi.id == -1102048                      # untouched degraded path
    assert mi.legacy_sync_id == 0


# ── macOS Office idle-quit script shape ──────────────────────────────────────

def test_idle_quit_script_guards_quit_separately():
    """The idle-quit script must be phase-tagged (Excel's gallery-state -1700
    survived two fixes because a single 'error N' status could not say WHAT
    threw): enumeration, doc scan and the quit verb each return a distinct
    status, the quit only ever runs after the user-owned check passed, and
    the repeat loop lives OUTSIDE any application tell block (inside one, the
    loop's implicit 'count' is dispatched to the app - suspect for the
    gallery -1700)."""
    from engine.applescript_bridge import _idle_quit_script

    s = _idle_quit_script("Microsoft Excel", "workbooks")
    # Distinct phase statuses for diagnosability.
    assert 'enum failed' in s
    assert 'doc scan failed' in s
    assert 'quit failed' in s
    assert 'quit saving no' in s
    # The user-owned bail-out comes BEFORE any quit statement.
    assert s.index('kept running') < s.index('to quit')
    # 'quit saving no' must be the PRIMARY quit verb: a plain 'quit' never
    # errors when a document has unsaved changes - the app just waits forever
    # on a hidden save sheet while the Apple event returns and we log "quit
    # sent" (round 5: Excel answered "quit sent (1 open doc)" and was still
    # alive with that doc 5 minutes later). saving-no is prompt-free and only
    # reached after zero user-owned documents were counted.
    _first_quit = s.index('to quit')
    assert s[_first_quit:].startswith('to quit saving no')
    # The repeat loop must NOT sit inside a tell block: the only tell around
    # the enumeration is the single-line form, and every per-property read
    # targets the app explicitly.
    assert 'repeat with d in docList' in s
    _repeat_at = s.index('repeat with d in docList')
    _last_block_tell = s.rindex('tell application', 0, _repeat_at)
    assert 'to set docList' in s[_last_block_tell:_repeat_at]


def test_probe_open_docs_script_shape():
    """The kill-safety probe must ask the app for a document COUNT and map
    every outcome to one of the statuses the escalation logic gates on."""
    import inspect
    from engine.applescript_bridge import _probe_open_docs

    src = inspect.getsource(_probe_open_docs)
    assert 'count of {collection}' in src
    for token in ('"gone"', '"docs "', 'count failed'):
        assert token in src


def test_quit_worker_escalates_certified_survivors():
    """"quit sent" only proves DELIVERY of the Apple event - an app can stall
    its own quit forever (round 5: Excel, dock-squatting for 5+ minutes after
    "quit sent"). The worker must therefore verify actual process exit and
    terminate any survivor whose status carried the no-user-docs certificate
    ("none user-owned") - and only those."""
    import inspect
    from engine.applescript_bridge import quit_idle_office_apps

    src = inspect.getsource(quit_idle_office_apps)
    assert '_survivors = _wait_for_exit(_expected_exits)' in src
    assert '"none user-owned" in statuses.get(app, "")' in src
    # Survivors WITHOUT the certificate are left alone.
    assert 'leaving it alone' in src or 'without a' in src


def test_dock_recents_cleanup_is_snapshot_scoped():
    """The Dock recents cleanup (the "Excel still in the Dock after the run"
    fix - the icon is a Dock RECENTS tile, not a live process) must (a) run
    only when OUR priming launched an Office app this run (snapshot exists),
    (b) never remove a tile that was in recents before the run or whose
    process is still alive, and (c) restart the Dock only when a tile was
    actually removed."""
    import inspect
    import engine.applescript_bridge as ab

    src = inspect.getsource(ab._cleanup_dock_recents)
    assert '_dock_recents_before is None' in src            # (a) snapshot gate
    strip = inspect.getsource(ab._strip_office_recents_tiles)
    assert 'bid in _dock_recents_before' in strip           # (b) pre-existing
    assert '_office_pgrep_alive' in strip                   # (b) running check
    assert 'killall' in strip and 'if not removed' in strip  # (c)
    # Timing (the 2026-07-09 Excel-tile-reappeared race): the Dock moves a
    # quit app into recents when it processes the TERMINATION - seconds after
    # the process dies - and ALSO writes tiles at LAUNCH, so neither a fixed
    # settle nor tile PRESENCE is a safe trigger (both lost the race on the
    # 21:08 / 21:26 runs). The cleanup must wait for BSD-level death, then
    # watch recent-apps for the termination WRITE (a change followed by
    # quiet), so the Dock restarts exactly ONCE - and still VERIFY with a
    # second strip pass afterwards.
    assert '_office_pgrep_alive' in src and 'sleep' in src
    assert '_primed_apps' in src                       # only when WE launched
    assert '_changed' in src and '_quiet' in src       # change-then-quiet watch
    assert src.count('_strip_office_recents_tiles()') >= 2
    # The quit worker runs it AFTER the Office-Recents purge (dead processes).
    wsrc = inspect.getsource(ab.quit_idle_office_apps)
    assert wsrc.index('_purge_canvas_recents()') < wsrc.index('_cleanup_dock_recents()')


def test_office_ids_in_dock_recents_parses_tiles():
    import engine.applescript_bridge as ab

    dock = {'recent-apps': [
        {'tile-data': {'bundle-identifier': 'com.microsoft.Excel'}},
        {'tile-data': {'bundle-identifier': 'com.apple.TextEdit'}},
        'garbage',
        {'tile-data': {}},
    ]}
    assert ab._office_ids_in_dock_recents(dock) == {'com.microsoft.excel'}
    assert ab._office_ids_in_dock_recents({}) == set()
    assert ab._office_ids_in_dock_recents(None) == set()


def test_reset_office_priming_clears_dock_snapshot():
    import engine.applescript_bridge as ab

    ab._dock_recents_before = {'com.microsoft.excel'}
    try:
        ab.reset_office_priming()
        assert ab._dock_recents_before is None
    finally:
        ab._dock_recents_before = None


def test_teacher_locked_files_classify_as_permanent():
    """A module-linked file the teacher LOCKED in Files has no download URL for
    students (Canvas strips it; even a browser gets 'This file is currently
    locked'). It must be reported as a permanent 'Locked File' (retry_exhausted
    -> the Cannot Be Downloaded bucket), never as a retryable failure - and
    never auto-ignored (teachers often unlock after the lecture)."""
    import inspect

    import core.canvas_logic as cl
    src = inspect.getsource(cl.CanvasManager)
    i = src.index("locked_for_user")
    block = src[i:i + 1800]
    assert '"Locked File"' in block
    assert 'err.retry_exhausted = True' in block
    assert 'lock_explanation' in block

    import shared.components as sc
    assert 'Locked File' in sc._ERROR_TRANSLATIONS

    from pathlib import Path
    sync_src = Path('sync/execution.py').read_text(encoding='utf-8')
    assert "Locked by the teacher on Canvas" in sync_src


def test_panopto_classify_heals_stale_manifest_path(tmp_path):
    """A kind whose MANIFEST path is dead but which exists at the CURRENT
    layout path must classify as PRESENT (real path + real size + a
    healed_paths entry for the manifest upsert) - never as missing. A
    download-mode run of the same folder re-fetches recordings purely by
    layout (it has no manifest to honour), so trusting the stale manifest
    alone re-offered the kind and the next sync re-downloaded a duplicate
    copy into the dead folder (2026-07-10: review showed 'missing: mp3'
    while the freshly-downloaded mp3 sat on disk)."""
    from pathlib import Path
    from types import SimpleNamespace

    from panopto.sync_plan import classify_videos

    cm = SimpleNamespace(_sanitize_filename=lambda s: s)
    root = tmp_path
    settings = {'output_mp3': True, 'output_txt': True, 'layout': 'separate'}
    v = SimpleNamespace(video_id='vid-1', title='Lecture 1', module_name='')

    rec_dir = root / 'Panopto Recordings' / 'Lecture 1'
    rec_dir.mkdir(parents=True)
    # txt: manifest path is alive -> resolved via the manifest, present.
    (rec_dir / 'Lecture 1.txt').write_text('transcript', encoding='utf-8')
    # mp3: manifest points at a DELETED old-layout copy, but a live copy sits
    # at the current layout path (what a download-mode run wrote there).
    (rec_dir / 'Lecture 1.mp3').write_bytes(b'a' * 2048)
    manifest = {'vid-1': {
        'txt': 'Panopto Recordings/Lecture 1/Lecture 1.txt',
        'mp3': 'Old Layout/Lecture 1.mp3',          # gone from disk
    }}

    (ch,) = classify_videos(cm, [v], root, 'flat', settings, manifest)
    assert ch.state == 'uptodate'
    assert ch.missing_kinds == []
    assert set(ch.healed_paths) == {'mp3'}
    assert Path(ch.paths['mp3']) == rec_dir / 'Lecture 1.mp3'
    assert ch.sizes['mp3'] == 2048        # real on-disk size, never an estimate

    # Control: with NO live layout copy, the stale manifest kind stays missing
    # (a genuine locally-deleted restore) and nothing is healed.
    (rec_dir / 'Lecture 1.mp3').unlink()
    (ch2,) = classify_videos(cm, [v], root, 'flat', settings, manifest)
    assert 'mp3' in ch2.missing_kinds
    assert ch2.healed_paths == {}
    assert ch2.state == 'restore'
