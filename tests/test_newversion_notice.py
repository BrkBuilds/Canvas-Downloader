"""The completion screen must say when a second copy of a file appeared.

A sync has exactly one outcome that silently ADDS a file to the user's folder:
the ``_NewVersion`` fork. It happens when the copy on disk cannot or must not be
overwritten — the file is open in another program, or the user has edited it —
and the app is right to do it. But the copy that keeps the familiar name is then
the STALE one, and until 2026-07-28 nothing anywhere said so. The audit found it
by reading the manifest after a sync: the row had been repointed to
``X_NewVersion.pdf`` while ``X.pdf`` sat there untracked and unexplained.

Two routes reach the same folder state (``sync/execution.py``: a PermissionError
on the atomic rename, and the ``is_update_modified`` branch), so both must be
recorded or the count under-reports.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from sync.completion import build_newversion_notice  # noqa: E402

EXECUTION = (REPO / "sync" / "execution.py").read_text(encoding="utf-8")
COMPLETION = (REPO / "sync" / "completion.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# the copy
# --------------------------------------------------------------------------

def test_nothing_to_say_renders_nothing():
    """An empty card is worse than no card."""
    assert build_newversion_notice(None) is None
    assert build_newversion_notice([]) is None


def test_a_single_file_reads_in_the_singular():
    n = build_newversion_notice([{"name": "Essay.docx", "reason": "in_use"}])
    assert "1 file was saved as a separate copy" in n["message"]
    assert "this file" in n["detail"] and "next to it" in n["detail"]
    assert "these files" not in n["detail"]


def test_several_files_read_in_the_plural():
    n = build_newversion_notice([{"name": "a.pdf"}, {"name": "b.pdf"}])
    assert "2 files were saved" in n["message"]
    assert "these files" in n["detail"] and "next to them" in n["detail"]


def test_the_notice_frames_it_as_protection_not_failure():
    """It is INFO: nothing broke, the app protected work in progress."""
    n = build_newversion_notice([{"name": "a.pdf"}])
    assert "didn't overwrite your version" in n["message"]
    for alarming in ("error", "failed", "could not", "unable", "problem"):
        assert alarming not in n["message"].lower()
        assert alarming not in n["detail"].lower()


def test_the_notice_says_how_to_recognise_the_new_file():
    n = build_newversion_notice([{"name": "Report_NewVersion.pdf"}])
    assert "_NewVersion" in n["detail"]
    assert "Report_NewVersion.pdf" in n["detail"], "an example makes it findable"


def test_the_notice_says_what_to_do_about_it():
    """A notice that only reports is a notice the user cannot act on."""
    n = build_newversion_notice([{"name": "a.pdf"}])
    assert "Your copy is untouched" in n["detail"]
    assert "keep whichever you want" in n["detail"]
    assert "delete the other" in n["detail"]


def test_a_missing_name_still_produces_usable_copy():
    """Never render a dangling "for example: " with nothing after it."""
    n = build_newversion_notice([{"reason": "edited"}])
    assert n["count"] == 1
    assert "for example" not in n["detail"]
    assert n["detail"].rstrip().endswith("delete the other.")


def test_the_example_is_the_first_record_that_has_a_name():
    n = build_newversion_notice([{"reason": "edited"}, {"name": "Second.pdf"}])
    assert n["example"] == "Second.pdf"


def test_malformed_records_are_ignored_rather_than_crashing():
    """This runs on a terminal screen; a raise here loses the whole result."""
    n = build_newversion_notice([None, "junk", {"name": "ok.pdf"}])
    assert n["count"] == 1 and n["example"] == "ok.pdf"


def test_the_reason_is_never_shown_to_the_user():
    """'open' vs 'edited' does not change what the user must do, and splitting
    one tidy outcome into two notices would make it look like two problems."""
    n = build_newversion_notice([{"name": "a.pdf", "reason": "in_use"}])
    assert "in_use" not in n["detail"] and "in_use" not in n["message"]


# --------------------------------------------------------------------------
# both routes are recorded
# --------------------------------------------------------------------------

def test_the_locked_target_route_records_a_new_version():
    """The worse of the two: the user made no choice at all."""
    block = EXECUTION.split("Target is locked", 1)[1][:1200]
    assert "_register_new_version(_alt, 'in_use')" in block


def test_the_locally_edited_route_records_a_new_version():
    block = EXECUTION.split("is_update_modified and filepath.exists()", 1)[1][:600]
    assert "_register_new_version(" in block


def test_every_new_version_site_in_the_sync_engine_is_instrumented():
    """A third route added later must not silently under-report the count."""
    sites = [m.start() for m in
             re.finditer(r'f"\{[^"]*\}_NewVersion\{', EXECUTION)]
    assert sites, "the _NewVersion construction moved; update this guard"
    for s in sites:
        window = EXECUTION[s:s + 900]
        assert "_register_new_version(" in window, (
            "a _NewVersion is created here without being recorded, so the "
            "completion screen would under-report it")


def test_the_recorder_never_breaks_a_sync():
    block = EXECUTION.split("def _register_new_version", 1)[1][:900]
    assert "except Exception" in block, \
        "bookkeeping must never take down a sync in progress"


# --------------------------------------------------------------------------
# state lifecycle
# --------------------------------------------------------------------------

def test_the_key_is_registered_as_transient_sync_state():
    from core.state_registry import SYNC_TRANSIENT_KEYS
    assert "sync_newversion_files" in SYNC_TRANSIENT_KEYS


def test_the_key_survives_until_the_user_leaves_the_completion_screen():
    """It is read ON the completion screen, so an early wipe blanks the notice.

    ``_cleanup_sync_state`` is only called from the 'Go to front page' handlers
    — the same lifecycle the ignored-files notice already relies on.
    """
    calls = [m.start() for m in re.finditer(r"(?<!def )_cleanup_sync_state\(\)",
                                            COMPLETION)]
    assert calls, "the cleanup call moved; update this guard"
    for pos in calls:
        assert "page_nav_front_page" in COMPLETION[max(0, pos - 400):pos], \
            "cleanup is invoked somewhere other than a leave-the-screen button"


@pytest.mark.parametrize("path", ["ui/download_settings.py", "ui/quick_download.py"])
def test_starting_a_download_clears_it(path):
    """Otherwise a download completion screen inherits the last sync's notice."""
    src = (REPO / path).read_text(encoding="utf-8")
    assert "'sync_newversion_files'" in src, \
        f"{path} clears stale sync keys but not this one"


def test_the_protected_card_does_not_claim_the_user_edited_the_file():
    """Two routes produce a ``_NewVersion``, and the card is name-based.

    ``sync/execution.py`` assigns the 'protected' category purely from the
    filename, so a file that was merely OPEN in another program lands in the
    same card as one the user genuinely edited. The old subtitle told that
    second group they had edited something they never touched.
    """
    src = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    block = src.split("def render_course_file_breakdown", 1)[1][:2600]
    # Comments are stripped first, exactly as verify_architecture.py does before
    # its own scans: the comment explaining WHY the old wording was wrong quotes
    # it, and would otherwise trip the check that polices it.
    block = re.sub(r"^\s*#.*$", "", block, flags=re.M)
    assert "'protected'" in block
    assert "the files you had edited" not in block, \
        "the subtitle asserts an action the locked-file case never took"
    assert "left untouched" in block, "the protective framing must survive"


def test_the_category_legend_covers_both_routes():
    src = (REPO / "sync_ui.py").read_text(encoding="utf-8")
    i = src.find("Modified Files Protected:")
    assert i > 0, "the legend entry moved"
    entry = src[i:i + 400]
    assert "open in another program" in entry, \
        "the legend only explains the edited route"


def test_a_conversion_failure_can_reach_the_error_log_it_points_at():
    """"Check download_errors.txt for details" must come with a way to open it.

    A post-processing failure increments ``pp_failure_count``, not the error
    LIST, and both completion screens hid the "View Full Error Log" button
    behind an error-list gate. Measured on a real sync: 2 conversion failures,
    0 sync errors, no button — the screen told the user to go and read a file
    and gave them no way to get there.
    """
    assert "pp_failure_count" in COMPLETION.split("show_sync_errors", 1)[1], \
        "the sync screen's log button is gated on sync errors alone again"
    app = (REPO / "app.py").read_text(encoding="utf-8")
    assert "render_error_log_button" in app, \
        "the download screen has no log button for a conversion-only failure"


def test_both_screens_use_the_same_error_log_button():
    """They are near-duplicates; a fix to one is invisible in review on the other."""
    comp = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    assert "def render_error_log_button" in comp
    for path in ("sync/completion.py", "app.py"):
        src = (REPO / path).read_text(encoding="utf-8")
        assert "render_error_log_button(" in src, f"{path} re-implements the button"


def test_it_is_rendered_next_to_the_ignored_files_notice():
    i = COMPLETION.find("skipped because you ignored them")
    # The CALL site, not the definition (which lives at the top of the module).
    j = COMPLETION.find("= build_newversion_notice(")
    assert 0 < i < j, "the two related notices drifted apart"
    assert j - i < 2000, "another notice was inserted between the two"
    block = COMPLETION[j:j + 500]      # the render call follows the build call
    assert "render_info_notice" in block, "must stay INFO, not a warning"
    assert "render_amber_notice" not in block, \
        "an amber card would imply something went wrong"
