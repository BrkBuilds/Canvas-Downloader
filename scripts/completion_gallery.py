"""Render every completion screen the app can produce, one per page load.

    streamlit run scripts/completion_gallery.py --server.port 8599

Then ``?v=<id>`` selects a variant; ``?v=index`` lists them all.

WHY THIS EXISTS
---------------
The completion screens are the only screens in the app a user cannot reach on
demand: each one needs a specific *outcome* (a locked file, an exhausted retry,
an archive over the guard's limit, a cancelled post-processing pass), and some
combinations cannot be produced at all from the courses any one person has. So
reviewing them meant downloading something and hoping.

This drives the REAL renderers - ``render_completion_card``,
``render_error_section``, ``render_folder_cards``, the amber/info notices, the
Panopto card, the wizard - with mock state, inside a real Streamlit process
with the real stylesheets. That distinction is the whole point: a hand-written
HTML mock proves nothing about spacing, because almost every spacing bug on
these screens came from Streamlit's own wrappers (the -16px markdown margin,
element-container flex gaps, container inheritance) rather than from our CSS.
See CLAUDE.md, "Verify in the REAL app, not a mock".

ONE VARIANT PER PAGE LOAD, deliberately:
  * the card's background/border is injected as a ``<style>`` keyed to
    ``st-key-completion_dashboard``, so two cards on one page would fight over
    it and both would show the last one's colour;
  * Streamlit rejects duplicate widget keys, and the folder cards, retry button
    and per-file actions all carry fixed keys;
  * the real screens have exactly one card, and element *index* is load-bearing
    here (see the container-inheritance notes in CLAUDE.md).

Mock data only. Nothing here is imported by the app; it touches no user data and
writes only into a temp directory.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import streamlit as st  # noqa: E402

from shared.components import (  # noqa: E402
    fresh_container, render_archives_skipped_notice,
    render_panopto_disabled_notice, render_cancelled_card,
    render_completion_card, render_error_section, render_folder_cards,
    render_pp_warning, inject_material_icons_font,
    render_folder_scope_notice,
)
from shared.helpers import (  # noqa: E402
    LOCKED_FILE_ERROR_TYPE, LOCKED_FILE_REASON, LTI_STREAM_ERROR_TYPE,
    LTI_STREAM_REASON, render_download_wizard, render_sync_wizard,
    split_delivery_errors,
)
from styles import inject_css  # noqa: E402
from sync.completion import (  # noqa: E402
    QUICK_SYNC_SKIP_DETAIL, build_newversion_notice,
    build_quick_sync_skip_notice,
)
from ui.amber_notice import render_amber_notice, render_info_notice  # noqa: E402


# ---------------------------------------------------------------------------
# a real folder on disk, so the buttons render in their ENABLED state
# ---------------------------------------------------------------------------
# `render_folder_cards` hides "Open Folder" unless the path exists, and each
# per-file Open/Reveal button is `disabled=not os.path.isfile(...)`. A disabled
# button is painted by the app's one disabled recipe, so pointing these at
# fictional paths would review the wrong pixels.

_SAMPLE = {
    "Introduction to Organisational Behaviour": [
        ("Lecture 1 - Course Introduction.pdf", "Modules/Week 1", "new"),
        ("Lecture 2 - Motivation Theory.pdf", "Modules/Week 2", "new"),
        ("Seminar notes.docx", "Modules/Week 2", "new"),
        ("Reading list.pdf", "", "new"),
        ("Case study - Nordic Air.pptx", "Modules/Week 3", "updated"),
        ("Group assignment brief.pdf", "Assignments", "updated"),
        ("Exam questions 2024.pdf", "Files", "restored"),
        ("My notes_NewVersion.docx", "Modules/Week 1", "protected"),
    ],
    "Statistics for Business (LA E25 BSTAT1020U)": [
        ("Problem set 4.pdf", "Assignments", "new"),
        ("Dataset - housing.xlsx", "Files/Data", "new"),
        ("Solutions week 4.pdf", "Modules/Week 4", "new"),
        ("Formula sheet.pdf", "", "updated"),
    ],
    "Microeconomics (XB F26 BMICR1010U)": [
        ("Slides 01 - Supply and demand.pdf", "Modules/Week 1", "new"),
        ("Slides 02 - Elasticity.pdf", "Modules/Week 2", "new"),
        ("Exercise 1.docx", "Exercises", "new"),
        ("Lecture recording.mp3", "Panopto Recordings", "new"),
        ("Archive of past exams.zip", "Files", "new"),
    ],
}


@st.cache_resource
def _materialise() -> dict:
    """Create the sample tree once per process and return its paths."""
    root = Path(tempfile.gettempdir()) / "cd_completion_gallery" / "Canvas Downloads"
    folders, details, records = {}, {}, {}
    for course, files in _SAMPLE.items():
        course_dir = root / course
        names, recs = [], []
        for name, subdir, category in files:
            target = (course_dir / subdir / name) if subdir else (course_dir / name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(b"gallery sample\n")
            rel = f"{subdir}/{name}" if subdir else name
            names.append(name)
            recs.append({"name": name, "rel": rel, "category": category})
        # An error log next to the course, so "View Full Error Log" appears
        # (render_error_section filters the list by p.exists()).
        log = course_dir / "download_errors.txt"
        if not log.exists():
            log.write_text(
                "[2026-07-29 14:02:11] [Statistics for Business] [HTTP 500] "
                "Problem set 5.pdf: Canvas returned a server error.\n",
                encoding="utf-8",
            )
        folders[course] = str(course_dir)
        details[course] = names
        records[course] = recs
    return {"folders": folders, "details": details, "records": records,
            "logs": [Path(p) / "download_errors.txt" for p in folders.values()]}


def _subset(n: int) -> tuple[dict, dict, dict]:
    """The first `n` courses of the sample tree."""
    tree = _materialise()
    keys = list(tree["details"])[:n]
    return ({k: tree["details"][k] for k in keys},
            {k: tree["folders"][k] for k in keys},
            {k: tree["records"][k] for k in keys})


# ---------------------------------------------------------------------------
# mock errors
# ---------------------------------------------------------------------------

class MockError:
    """The subset of ``DownloadError`` every completion-screen renderer reads.

    Constructed here rather than imported so the gallery cannot be affected by
    (or affect) the engine's error plumbing.
    """

    def __init__(self, course_name, item_name, error_type, message,
                 *, filepath="C:/x/y.pdf", is_app_error=False,
                 retry_exhausted=False, file_id=None):
        self.course_name = course_name
        self.item_name = item_name
        self.error_type = error_type
        self.message = message
        self.is_app_error = is_app_error
        self.retry_exhausted = retry_exhausted
        self.context = {}
        if filepath:
            self.context["filepath"] = filepath
        if file_id:
            self.context["file_dict"] = {"id": file_id, "url": ""}

    def __str__(self):
        return f"[{self.course_name}] {self.message}"


_C1 = "Introduction to Organisational Behaviour"
_C2 = "Statistics for Business (LA E25 BSTAT1020U)"

FAILED = [
    MockError(_C1, "Lecture 7 - Group Dynamics.pdf", "HTTP 500",
              "Canvas returned a server error.", file_id=1784620),
    MockError(_C2, "Problem set 5.pdf", "Timeout",
              "The request timed out after 30 seconds.", file_id=1784621),
    MockError(_C2, "Dataset - crime rates.xlsx", "Network",
              "Connection reset by peer."),
]
LOCKED = [
    MockError(_C1, "Final exam 2026.pdf", LOCKED_FILE_ERROR_TYPE,
              LOCKED_FILE_REASON, retry_exhausted=True, file_id=1784630),
    MockError(_C1, "Solutions - all weeks.pdf", LOCKED_FILE_ERROR_TYPE,
              LOCKED_FILE_REASON, retry_exhausted=True),
]
STREAMS = [
    MockError(_C2, "Guest lecture - Nordea CFO.mp4", LTI_STREAM_ERROR_TYPE,
              LTI_STREAM_REASON, filepath=None),
]
APP_ERRORS = [
    MockError(_C2, None, "Processing Error",
              "cannot access local variable 'isolate' where it is not associated "
              "with a value", filepath=None, is_app_error=True),
]


def _seed_breadcrumbs() -> None:
    """Give the app-error report something to attach, as a real run would.

    `core.canvas_debug` keeps the last few hundred debug lines in memory
    whether or not debug logging is on, and the report bundle includes them.
    A mock that never calls `log_debug` produces a bundle with no narration at
    all - which would make the reviewed screen look better-behaved than the
    real one, the exact failure mode this gallery exists to avoid. Passing
    `None` as the debug file is what the engine does when debug logging is off,
    i.e. the default.
    """
    from core.canvas_debug import log_debug
    for line in (
        "=== Download: Statistics for Business (ID: 45899) ===",
        "Mode: Custom Download  |  layout=modules  isolate_secondary=False",
        "Fetching module list (page 1)",
        "Module 'Week 4 - Regression' -> 12 items",
        "File Saved: Problem set 4.pdf (1.2 MB)",
        "Deferring 'Dataset - housing.xlsx' to Canvas Content phase",
        "Post-Processing: 3 conversions queued",
        "Converting Lecture 7.docx -> PDF via Word COM",
        "ERROR [core.canvas_logic] Processing Error: cannot access local "
        "variable 'isolate' where it is not associated with a value",
    ):
        log_debug(line, None)

SYNC_FAILED = [
    "Error syncing Lecture 7 - Group Dynamics.pdf: Connection reset by peer",
    "Error syncing Problem set 5.pdf: The request timed out after 30 seconds",
]
SYNC_LOCKED = [f"Error syncing Final exam 2026.pdf: {LOCKED_FILE_REASON}"]
SYNC_STREAM = [f"Error syncing Guest lecture.mp4: {LTI_STREAM_REASON}"]

SIZE_SKIPPED = [
    "Lecture recording week 1.mp4 (412.6 MB)",
    "Lecture recording week 2.mp4 (388.1 MB)",
    "Dataset - full census.csv (94.3 MB)",
    "Course textbook scan.pdf (61.8 MB)",
]
# {'name', 'bytes'} - the shape converters/post_processing.py records. A bare
# string is still rendered (a session that predates this can hold the old
# shape), but the size badge only appears for the current one, so the gallery
# has to use it or the review sees a row the app no longer produces.
ARCHIVES = [
    {"name": "R project - assignment 2.zip", "bytes": 48_234_496},
    {"name": "Python starter code.zip", "bytes": 12_058_624},
    {"name": "Lecture slides all weeks.zip", "bytes": 214_958_080},
]

PANOPTO_DL = {"found": 36, "downloaded": 12, "transcribed": 12, "failed": 0,
              "courses": 2, "want_transcription": True}
PANOPTO_DL_ERR = {"found": 36, "downloaded": 10, "transcribed": 8, "failed": 2,
                  "courses": 2, "want_transcription": True}
PANOPTO_SYNC = {"found": 36, "downloaded": 4, "transcribed": 4, "failed": 0,
                "uptodate": 32, "selected": 4, "want_transcription": True}


# ---------------------------------------------------------------------------
# session state
# ---------------------------------------------------------------------------

def _reset_state(**overrides):
    """Clear the keys the renderers read, then apply this variant's values.

    Also seeds the in-memory debug breadcrumbs, so an app-error variant's
    report bundle carries narration the way a real run's would.

    Cleared explicitly rather than by wiping session_state, because the query
    param and Streamlit's own internals live there too.
    """
    for k in ("size_skipped_files", "max_file_size_mb", "pp_archives_skipped",
              "archive_max_files", "pp_failure_count", "pp_force_kill_warning",
              "panopto_summary", "sync_quick_mode", "sync_uptodate_stats",
              "qs_skipped", "sync_has_ignored_files", "sync_newversion_files",
              "error_log_enabled", "is_post_processing", "sync_pairs",
              "courses_to_download", "file_filter", "sync_analysis_results"):
        st.session_state.pop(k, None)
    # THE REAL DEFAULT, and it must stay that way. `error_log_enabled` is False
    # in core/state_registry.py, and three separate places branch on it: the
    # error panel's "saved in download_errors.txt" footer, the conversion
    # notice's detail line, and whether any download_errors.txt exists for the
    # error-log button to point at. Seeding it True showed a reviewer the
    # minority branch of all three at once and produced findings about copy
    # most users never see. A variant that wants the on-state asks for it.
    st.session_state["error_log_enabled"] = False
    st.session_state["api_url"] = "https://cbscanvas.instructure.com"
    st.session_state["notifications_enabled"] = False
    _seed_breadcrumbs()
    st.session_state.update(overrides)


# ---------------------------------------------------------------------------
# the two screen shells - a faithful copy of the real composition order
# ---------------------------------------------------------------------------

def download_screen(*, synced, courses, total_bytes, errors=(),
                    size_skipped=(), size_limit=0, archives=(), archive_limit=0,
                    retry_attempted=False, retry_resolved=0, retry_total=0,
                    retry_failed=False, pp_failures=0, force_kill=False,
                    panopto=None, folder_courses=3, error_log=False,
                    panopto_off_courses=(), scope_courses=()):
    """app.py, `download_status == 'done'` (lines ~2276-2499)."""
    st.session_state["error_log_enabled"] = error_log
    st.session_state["size_skipped_files"] = list(size_skipped)
    st.session_state["max_file_size_mb"] = size_limit
    st.session_state["pp_archives_skipped"] = list(archives)
    st.session_state["archive_max_files"] = archive_limit
    # The Panopto-off panel resolves at RENDER from the run contract plus the
    # selected courses, so seeding those two IS the whole mock. It still only
    # appears when Panopto is genuinely switched off in Settings - run the
    # gallery under CANVAS_DL_CONFIG_DIR to force that without touching the
    # real config.
    if panopto_off_courses:
        st.session_state["persistent_pan_out_mp3"] = True
        st.session_state["courses_to_download"] = [
            SimpleNamespace(name=n) for n in panopto_off_courses]
    # The scope panel resolves the same way - the run's file_filter plus the
    # selected courses - so seeding those two IS the whole mock. Unlike the
    # Panopto panel it needs no Settings state, so it renders here always.
    if scope_courses:
        st.session_state["file_filter"] = 'study'
        st.session_state["courses_to_download"] = [
            SimpleNamespace(name=n) for n in scope_courses]

    render_download_wizard(st, 'complete')
    st.markdown('<h2 class="step-header">Download Complete!</h2>',
                unsafe_allow_html=True)

    details, folders, _ = _subset(folder_courses)
    if not synced:
        details = {}

    with fresh_container(border=True, key='completion_dashboard'):
        split = split_delivery_errors(list(errors))
        render_completion_card(
            synced_count=synced,
            error_count=len(errors),
            total_bytes=total_bytes,
            mode='download',
            size_skipped_files=list(size_skipped),
            size_limit_mb=size_limit,
            retry_attempted=retry_attempted,
            retry_resolved=retry_resolved,
            retriable_count=split['retriable'],
            unresolvable_count=split['unresolvable'],
            app_error_count=split['app'],
            courses_count=courses,
            panopto_summary=panopto,
        )
        # ORDER BY KIND, exactly as app.py does it: the card renders the stat
        # grid, the Panopto grid and the size-skip panel; archives follow; the
        # error panel is the last collapsible; notices come last as one block.
        render_archives_skipped_notice()
        render_panopto_disabled_notice(mode='download')
        render_folder_scope_notice(mode='download')
        has_retriable = any(
            not e.is_app_error and e.context.get('filepath')
            and e.error_type != LTI_STREAM_ERROR_TYPE and not e.retry_exhausted
            for e in errors)
        render_error_section(
            list(errors), key_prefix='dl',
            retry_btn_callback=(lambda: None)
            if has_retriable and not retry_attempted else None,
            has_retriable_errors=has_retriable,
            retry_failed=retry_failed,
        )
        render_pp_warning(pp_failures)
        if force_kill:
            render_amber_notice(
                "An Office process was force-closed during conversion.",
                icon="⚠️",
                detail=("A hung Office process was terminated to unblock "
                        "conversion. If you had other unsaved Word, Excel, or "
                        "PowerPoint files open, they may have been closed "
                        "without saving."),
                margin="0",  # the card's flex gap (16px) is the ONE rhythm; a margin here adds to it
            )

    render_folder_cards(details, folders, key_prefix='dl')
    _front_page()


def _seed_scope_pairs(scope_courses):
    """Real folders with a real 'study' sync_contract, in the gallery's temp dir."""
    import json as _json
    from core.sync_manager import SyncManager
    root = Path(tempfile.gettempdir()) / "cd_completion_gallery" / "scope"
    pairs = []
    for i, (name, _n) in enumerate(scope_courses):
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        sm = SyncManager(d, course_id=90000 + i, course_name=name)
        sm._save_metadata('sync_contract', _json.dumps(
            {'file_filter': 'study', 'download_mode': 'flat'}))
        pairs.append({'course_id': 90000 + i, 'course_name': name,
                      'local_folder': str(d)})
    return pairs


def sync_screen(*, synced, courses, total_bytes, errors=(),
                size_skipped=(), size_limit=0, archives=(), archive_limit=0,
                retry_attempted=False, retry_resolved=0, retry_total=0,
                retry_failed=False, pp_failures=0, force_kill=False,
                panopto=None, quick=False, uptodate_stats=None, qs_skipped=None,
                ignored=False, newversion=None, structural=0, folder_courses=2,
                interactive_files=True, error_log=False, scope_courses=()):
    """sync/completion.py, `show_sync_complete` (lines ~128-383)."""
    st.session_state["error_log_enabled"] = error_log
    st.session_state["size_skipped_files"] = list(size_skipped)
    st.session_state["max_file_size_mb"] = size_limit
    st.session_state["pp_archives_skipped"] = list(archives)
    st.session_state["archive_max_files"] = archive_limit
    st.session_state["sync_quick_mode"] = quick
    if uptodate_stats:
        st.session_state["sync_uptodate_stats"] = uptodate_stats

    # The scope panel resolves per PAIR from each folder's stored sync_contract,
    # so the mock is a real SyncManager over a temp folder - the same read the app
    # performs. `out_of_scope_files` rides in on a mock analysis result, which is
    # the only path that renders the per-course count badge.
    if scope_courses:
        st.session_state["sync_pairs"] = _seed_scope_pairs(scope_courses)
        st.session_state["sync_analysis_results"] = [
            {'pair': pr, 'result': SimpleNamespace(out_of_scope_files=n)}
            for pr, (_, n) in zip(st.session_state["sync_pairs"], scope_courses)]

    render_sync_wizard(st, 'complete')
    st.markdown('<h2 class="step-header">Sync Complete!</h2>',
                unsafe_allow_html=True)

    details, folders, records = _subset(folder_courses)
    if not synced:
        details, records = {}, {}

    st.empty()
    with fresh_container(border=True, key='completion_dashboard'):
        split = split_delivery_errors(list(errors))
        render_completion_card(
            synced_count=synced,
            error_count=len(errors),
            total_bytes=total_bytes,
            mode='sync',
            size_skipped_files=list(size_skipped),
            size_limit_mb=size_limit,
            retriable_count=split['retriable'],
            unresolvable_count=split['unresolvable'],
            courses_count=courses,
            retry_attempted=retry_attempted,
            retry_resolved=retry_resolved,
            panopto_summary=panopto,
        )
        # ORDER BY KIND, exactly as sync/completion.py does it.
        render_archives_skipped_notice()
        render_panopto_disabled_notice(mode='sync')
        render_folder_scope_notice(mode='sync')
        render_error_section(
            list(errors), key_prefix='sync_complete',
            retry_btn_callback=(lambda: None) if errors else None,
            has_retriable_errors=bool(errors),
            retry_failed=retry_failed,
        )

        # The SENTENCE comes from the app, not from a copy of it. This file had
        # its own, and that is how the `filtered` clause survived here for a
        # while after the app dropped it - the review instrument describing a
        # screen that no longer existed. INFO rather than amber, and
        # `canvas_del` counted but never listed: read
        # `build_quick_sync_skip_notice` for why.
        _qs_message = build_quick_sync_skip_notice(qs_skipped)
        if _qs_message:
            render_info_notice(_qs_message, detail=QUICK_SYNC_SKIP_DETAIL,
                               margin="0")  # the card's flex gap (16px) is the ONE rhythm

        render_pp_warning(pp_failures)

        if force_kill:
            render_amber_notice(
                "An Office process was force-closed during conversion.",
                icon="⚠️",
                detail=("A hung Office process was terminated to unblock "
                        "conversion. If you had other unsaved Word, Excel, or "
                        "PowerPoint files open, they may have been closed "
                        "without saving."),
                margin="0",  # the card's flex gap (16px) is the ONE rhythm; a margin here adds to it
            )
        if structural:
            render_amber_notice(
                f"{structural} module(s) or folder(s) could not be fetched from "
                f"Canvas due to connection/server errors. Their files are "
                f"consequently missing from the syncing checklist and cannot be "
                f"isolated for a targeted retry. A full Rescan is recommended "
                f"later.",
                icon="⚠️",
                margin="0",  # the card's flex gap (16px) is the ONE rhythm; a margin here adds to it
            )
        if ignored:
            render_info_notice(
                "Some files were skipped because you ignored them.",
                detail="You can manage ignored files from the Sync Hub.",
                margin="0",  # the card's flex gap (16px) is the ONE rhythm; a margin here adds to it
            )
        if newversion:
            note = build_newversion_notice(newversion)
            if note:
                render_info_notice(note["message"], detail=note["detail"],
                                   margin="0")

    render_folder_cards(
        details, folders, key_prefix='sync_complete', show_files_expander=True,
        file_records=records if interactive_files else None,
    )
    _front_page()


def _front_page():
    st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
    col, _ = st.columns([0.35, 0.65])
    with col:
        st.button('Go to front page', type="primary", use_container_width=True,
                  key="page_nav_front_page")


def cancelled_screen(what: str, done: int, total: int, *, during_pp=False):
    if during_pp:
        st.session_state['is_post_processing'] = True
    if what == "Sync":
        render_sync_wizard(st, 'sync')
    else:
        render_download_wizard(st, 'download')
    render_cancelled_card(what, done=done, total=total)
    _front_page()


# ---------------------------------------------------------------------------
# the catalogue
# ---------------------------------------------------------------------------

GB = 1024 ** 3
MB = 1024 ** 2

SCENARIOS: dict[str, tuple[str, str, callable]] = {
    # --- download: clean outcomes -----------------------------------------
    "d-success": (
        "Download · Success",
        "3 courses, no problems. The baseline every other download variant is a "
        "delta from.",
        lambda: download_screen(synced=143, courses=3, total_bytes=int(1.24 * GB)),
    ),
    "d-success-single": (
        "Download · Success (one course, one file)",
        "Every label in its singular form - 'Course Downloaded', 'File "
        "Downloaded'. The plural path is the common one, so this is where a "
        "hardcoded 's' shows up.",
        lambda: download_screen(synced=1, courses=1, total_bytes=int(2.4 * MB),
                                folder_courses=1),
    ),
    "d-panopto-off": (
        "Download · Success + Panopto switched off",
        "The third member of the \"deliberately left alone\" family, beside the "
        "size-skip and archive panels. It counts COURSES, not recordings - the "
        "switch skips discovery, so a recording count is genuinely unknown. "
        "Only renders when Panopto is actually off in Settings.",
        lambda: download_screen(
            synced=143, courses=3, total_bytes=int(1.24 * GB),
            size_skipped=SIZE_SKIPPED, size_limit=50,
            archives=ARCHIVES, archive_limit=1000,
            panopto_off_courses=("Makroøkonomi (XB)", "Statistik 2. semester")),
    ),
    "d-scope-study": (
        "Download \u00b7 Success + Slides & PDFs only",
        "The FOURTH member of the \"deliberately left alone\" family. Fires only "
        "when the run carried the \"Slides & PDFs\" filter, which is the whole "
        "point - it is a standing property of the folder, not a per-run event, "
        "and it replaced an amber Quick-Sync line that told users to widen the "
        "folder past the shape they chose.",
        lambda: download_screen(
            synced=118, courses=2, total_bytes=int(840 * MB),
            size_skipped=SIZE_SKIPPED, size_limit=50,
            archives=ARCHIVES, archive_limit=1000,
            scope_courses=("Makro\u00f8konomi (XB)", "Digitalisering af Forretningsprocesser")),
    ),
    "s-scope-study": (
        "Sync \u00b7 Complete + Slides & PDFs only",
        "The sync side of the scope panel. This is the ONLY path that renders the "
        "per-course count badge - the analyzer knows exactly how many Canvas files "
        "the filter excluded, where a plain download never asks.",
        lambda: sync_screen(
            synced=4, courses=2, total_bytes=int(9.6 * MB),
            scope_courses=(("Digitalisering af Forretningsprocesser", 76),
                           ("Makro\u00f8konomi (XB)", 12))),
    ),
    "d-success-locked": (
        "Download · Success + declined files",
        "Locked + stream-only files. GREEN on purpose: nothing failed, so the "
        "'Cannot Be Downloaded' card is neutral grey and the note below names "
        "the cause.",
        lambda: download_screen(synced=143, courses=3, total_bytes=int(1.24 * GB),
                                errors=LOCKED + STREAMS),
    ),
    "d-success-locked-one": (
        "Download · Success + one locked file",
        "Singular reason copy ('1 file is locked by your teacher').",
        lambda: download_screen(synced=143, courses=3, total_bytes=int(1.24 * GB),
                                errors=LOCKED[:1]),
    ),
    "d-success-skips": (
        "Download · Success + size skips + unpacked archives",
        "The two 'deliberately left alone' notices stacked. They should read as "
        "one family, not two features - collapsed here, expand to compare.",
        lambda: download_screen(synced=143, courses=3, total_bytes=int(1.24 * GB),
                                size_skipped=SIZE_SKIPPED, size_limit=50,
                                archives=ARCHIVES, archive_limit=1000),
    ),
    "d-success-panopto": (
        "Download · Success + Panopto card",
        "The half-width Panopto card under the main card - checks its top "
        "margin against the card above it.",
        lambda: download_screen(synced=143, courses=3, total_bytes=int(4.1 * GB),
                                panopto=PANOPTO_DL),
    ),
    # --- download: something went wrong -----------------------------------
    "d-partial": (
        "Download · Partial Success",
        "Amber. 3 real failures, error panel + Retry button.",
        lambda: download_screen(synced=140, courses=3, total_bytes=int(1.2 * GB),
                                errors=FAILED),
    ),
    "d-partial-mixed": (
        "Download · Partial + declined + app error",
        "All THREE error stat cards at once (Failed / Cannot Be Downloaded / "
        "App Errors), and the error panel's three sections.",
        lambda: download_screen(synced=138, courses=3, total_bytes=int(1.2 * GB),
                                errors=FAILED + LOCKED + STREAMS + APP_ERRORS),
    ),
    "d-partial-recovered": (
        "Download · Partial, retry recovered some",
        "The green 'Recovered 3 of 5' note inside the card.",
        lambda: download_screen(synced=141, courses=3, total_bytes=int(1.2 * GB),
                                errors=FAILED[:2], retry_attempted=True,
                                retry_resolved=3, retry_total=5),
    ),
    "d-recovered-all": (
        "Download · Success, retry recovered everything",
        "Green card + 'Successfully recovered all 5'. The only variant where a "
        "retry note sits on a success card.",
        lambda: download_screen(synced=143, courses=3, total_bytes=int(1.24 * GB),
                                retry_attempted=True, retry_resolved=5,
                                retry_total=5),
    ),
    "d-retry-failed": (
        "Download · Partial, retry exhausted",
        "Disabled Retry button (one disabled recipe), the red-tinted column "
        "subtitle, and the amber 'Retry didn't work' notice below.",
        lambda: download_screen(synced=140, courses=3, total_bytes=int(1.2 * GB),
                                errors=FAILED, retry_attempted=True,
                                retry_resolved=0, retry_total=3,
                                retry_failed=True),
    ),
    "d-failure": (
        "Download · Failed",
        "Red. Nothing arrived and something went wrong.",
        lambda: download_screen(synced=0, courses=0, total_bytes=0,
                                errors=FAILED + APP_ERRORS),
    ),
    "d-nothing": (
        "Download · Nothing Could Be Downloaded",
        "0 files, but nothing FAILED - every candidate was locked or streamed. "
        "Amber, with no stat cards for files/size beyond the zeroes.",
        lambda: download_screen(synced=0, courses=0, total_bytes=0,
                                errors=LOCKED + STREAMS),
    ),
    "d-uptodate": (
        "Download · All Up to Date",
        "The nothing-to-do card + the amber 'possible connection issue' panel "
        "that only download mode shows.",
        lambda: download_screen(synced=0, courses=0, total_bytes=0),
    ),
    "d-pp-failures": (
        "Download · Success + conversion failures",
        "pp_failure_count with no download errors - the case where the only "
        "way to the log is the standalone button.",
        lambda: download_screen(synced=143, courses=3, total_bytes=int(1.24 * GB),
                                pp_failures=4),
    ),
    "d-pp-failures-log": (
        "Download · Conversion failures, error log ON",
        "The minority branch: with error logging enabled the notice points at "
        "download_errors.txt. Default is OFF (see d-pp-failures).",
        lambda: download_screen(synced=143, courses=3, total_bytes=int(1.24 * GB),
                                pp_failures=4, error_log=True),
    ),
    "d-partial-log": (
        "Download · Partial, error log ON",
        "The error panel gains its \"saved in download_errors.txt\" footer only "
        "in this state.",
        lambda: download_screen(synced=140, courses=3, total_bytes=int(1.2 * GB),
                                errors=FAILED, error_log=True),
    ),
    "d-kitchen": (
        "Download · Everything at once",
        "Every optional element on one screen. Not a realistic run - this is "
        "the stacking/margin test.",
        lambda: download_screen(
            synced=138, courses=3, total_bytes=int(4.4 * GB),
            errors=FAILED + LOCKED + STREAMS + APP_ERRORS,
            size_skipped=SIZE_SKIPPED, size_limit=50,
            archives=ARCHIVES, archive_limit=1000,
            retry_attempted=True, retry_resolved=2, retry_total=5,
            pp_failures=4, force_kill=True, panopto=PANOPTO_DL_ERR),
    ),
    # --- download: cancelled ----------------------------------------------
    "d-cancelled": (
        "Download · Cancelled mid-run",
        "Deliberately renders NO error list.",
        lambda: cancelled_screen("Download", done=87, total=143),
    ),
    "d-cancelled-analysis": (
        "Download · Cancelled during analysis",
        "total == 0, so no file count exists yet and the sentence changes.",
        lambda: cancelled_screen("Download", done=0, total=0),
    ),
    "d-cancelled-pp": (
        "Download · Cancelled during post-processing",
        "Third wording of the same card.",
        lambda: cancelled_screen("Download", done=143, total=143,
                                 during_pp=True),
    ),
    # --- sync: clean outcomes ---------------------------------------------
    "s-success": (
        "Sync · Success",
        "Interactive folder cards: per-file Open/Reveal, destination chips, and "
        "all four category headers (New / Updates / Restored / Protected).",
        lambda: sync_screen(synced=12, courses=2, total_bytes=int(184 * MB)),
    ),
    "s-success-single": (
        "Sync · Success (one course, one file)",
        "Singular labels on the sync side.",
        lambda: sync_screen(synced=1, courses=1, total_bytes=int(1.1 * MB),
                            folder_courses=1),
    ),
    "s-success-quick": (
        "Sync · Quick Sync success",
        "Same card, but the wizard strikes through the skipped Review step.",
        lambda: sync_screen(synced=12, courses=2, total_bytes=int(184 * MB),
                            quick=True),
    ),
    "s-success-locked": (
        "Sync · Success + declined files",
        "The sync flow's errors are plain STRINGS, classified by the same "
        "function - so this must look identical to its download twin.",
        lambda: sync_screen(synced=12, courses=2, total_bytes=int(184 * MB),
                            errors=SYNC_LOCKED + SYNC_STREAM),
    ),
    "s-success-panopto": (
        "Sync · Success + Panopto card",
        "Sync's Panopto header reads 'N processed · N already up to date' "
        "instead of download's 'N found across N courses'.",
        lambda: sync_screen(synced=12, courses=2, total_bytes=int(2.2 * GB),
                            panopto=PANOPTO_SYNC),
    ),
    "s-notices": (
        "Sync · Success + the four sync-only notices",
        "Quick-Sync skips (info), ignored files (info), _NewVersion (info), "
        "structural errors (amber). Checks amber-vs-info ordering and gaps. "
        "The canvas_del and filtered tallies are passed and must NOT appear.",
        lambda: sync_screen(
            synced=12, courses=2, total_bytes=int(184 * MB), quick=True,
            qs_skipped={"edited": 2, "local_del": 1, "canvas_del": 3,
                        "filtered": 5, "panopto_local_del": 1},
            ignored=True, structural=2,
            newversion=[{"name": "My notes_NewVersion.docx"},
                        {"name": "Budget_NewVersion.xlsx"}]),
    ),
    "s-qs-canvas-del-only": (
        "Sync · Quick Sync whose only skip was deleted on Canvas",
        "Must render NO Quick-Sync panel at all. A file deleted on Canvas is "
        "not actionable from this screen, so it is counted and never listed - "
        "and this is the branch where that leaves nothing to say.",
        lambda: sync_screen(
            synced=9, courses=1, total_bytes=int(41 * MB), quick=True,
            qs_skipped={"canvas_del": 3}),
    ),
    "s-newversion-one": (
        "Sync · Success + one protected file",
        "The singular _NewVersion copy, on its own.",
        lambda: sync_screen(synced=12, courses=2, total_bytes=int(184 * MB),
                            newversion=[{"name": "My notes_NewVersion.docx"}]),
    ),
    # --- sync: something went wrong ---------------------------------------
    "s-partial": (
        "Sync · Completed with Errors",
        "String errors render as one 'Failed to Download' column with the "
        "default file icon.",
        lambda: sync_screen(synced=10, courses=2, total_bytes=int(150 * MB),
                            errors=SYNC_FAILED),
    ),
    "s-retry-failed": (
        "Sync · Retry exhausted",
        "Sync's copy of the disabled-retry state.",
        lambda: sync_screen(synced=10, courses=2, total_bytes=int(150 * MB),
                            errors=SYNC_FAILED, retry_attempted=True,
                            retry_resolved=0, retry_total=2, retry_failed=True),
    ),
    "s-failure": (
        "Sync · Failed",
        "Red, sync wording.",
        lambda: sync_screen(synced=0, courses=2, total_bytes=0,
                            errors=SYNC_FAILED),
    ),
    "s-nothing": (
        "Sync · Nothing Could Be Synced",
        "Every candidate declined by Canvas.",
        lambda: sync_screen(synced=0, courses=1, total_bytes=0,
                            errors=SYNC_LOCKED + SYNC_STREAM),
    ),
    "s-uptodate": (
        "Sync · Everything up to date (multi-course)",
        "The evidence line counts files, recordings and courses.",
        lambda: sync_screen(synced=0, courses=3, total_bytes=0,
                            uptodate_stats={"files": 412, "courses": 3,
                                            "recordings": 36}),
    ),
    "s-uptodate-one": (
        "Sync · Everything up to date (one course)",
        "Singular: 'in this course', 'your folder already matches Canvas'.",
        lambda: sync_screen(synced=0, courses=1, total_bytes=0,
                            uptodate_stats={"files": 143, "courses": 1,
                                            "recordings": 0}),
    ),
    "s-uptodate-quick": (
        "Sync · Quick Sync, everything up to date",
        "'Quick Sync done' title + the struck-through Review step.",
        lambda: sync_screen(synced=0, courses=2, total_bytes=0, quick=True,
                            uptodate_stats={"files": 288, "courses": 2,
                                            "recordings": 12}),
    ),
    "s-uptodate-nostats": (
        "Sync · Everything up to date (no stats)",
        "The fallback line, used when the analysis pass recorded no counts.",
        lambda: sync_screen(synced=0, courses=2, total_bytes=0),
    ),
    "s-kitchen": (
        "Sync · Everything at once",
        "The sync stacking test.",
        lambda: sync_screen(
            synced=10, courses=2, total_bytes=int(2.4 * GB), quick=True,
            errors=SYNC_FAILED + SYNC_LOCKED + SYNC_STREAM,
            size_skipped=SIZE_SKIPPED, size_limit=50,
            archives=ARCHIVES, archive_limit=1000,
            retry_attempted=True, retry_resolved=1, retry_total=3,
            pp_failures=2, force_kill=True, panopto=PANOPTO_SYNC,
            qs_skipped={"edited": 2, "canvas_del": 3},
            ignored=True, structural=1,
            newversion=[{"name": "My notes_NewVersion.docx"}]),
    ),
    "s-cancelled": (
        "Sync · Cancelled mid-run",
        "Same card as download, different noun.",
        lambda: cancelled_screen("Sync", done=4, total=12),
    ),
    "s-cancelled-analysis": (
        "Sync · Cancelled during analysis",
        "total == 0.",
        lambda: cancelled_screen("Sync", done=0, total=0),
    ),
}


# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------

def _index():
    st.title("Completion screen gallery")
    st.caption(f"{len(SCENARIOS)} variants. Append `?v=<id>` to the URL.")
    for vid, (title, why, _) in SCENARIOS.items():
        st.markdown(f"- **[{title}](/?v={vid})** — `{vid}` — {why}")


def _page():
    """Everything that touches `st` at page level.

    Behind the ``__main__`` guard so ``capture_completion_gallery.py`` can
    import SCENARIOS for its catalogue without executing a page render outside
    a Streamlit runtime (which warns on every call and would build the sample
    tree as a side effect of an import).
    """
    st.set_page_config(page_title="Completion Gallery", layout="wide")
    inject_css('global.css')
    inject_css('preset_dialogs.css')
    inject_material_icons_font()

    v = st.query_params.get("v", "index")
    if v in SCENARIOS:
        _reset_state()
        SCENARIOS[v][2]()
    else:
        _index()


if __name__ == "__main__":
    _page()
