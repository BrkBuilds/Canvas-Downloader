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
import urllib.parse
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



def _code_only(src: str) -> str:
    """Strip comments and docstrings before scanning source.

    These tests assert on what the CODE says, and a comment explaining why a
    phrase was removed necessarily contains that phrase. Without this, the test
    that bans "API connection" is failed by the comment recording that it was
    banned. `scripts/verify_architecture.py` blanks comments for the same
    reason before its own rules run.
    """
    import io
    import tokenize
    out, prev_type = [], tokenize.INDENT
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and prev_type in (
                tokenize.INDENT, tokenize.NEWLINE, tokenize.NL, tokenize.DEDENT):
            continue                      # a bare string statement == docstring
        out.append(tok.string)
        if tok.type not in (tokenize.NL, tokenize.NEWLINE):
            prev_type = tok.type
    return "\n".join(out)


def _notice_calls(src: str) -> list[str]:
    """Every ``render_amber_notice(...)`` / ``render_info_notice(...)`` call in
    ``src``, each as the full argument text between its parens.

    A paren-depth scanner, not a regex anchored on a trailing comma - that
    naive form is exactly what let one call site through earlier: the LAST
    keyword argument before a closing paren has no comma after it, and a
    string search for ``margin="12px 0 2px 0",`` silently skips it. Depth
    counting finds the true end of the call regardless of formatting.
    """
    calls = []
    for name in ("render_amber_notice(", "render_info_notice("):
        start = 0
        while True:
            i = src.find(name, start)
            if i < 0:
                break
            j = i + len(name)
            depth = 1
            while depth and j < len(src):
                if src[j] == "(":
                    depth += 1
                elif src[j] == ")":
                    depth -= 1
                j += 1
            calls.append(src[i:j])
            start = j
    return calls


def test_every_completion_screen_notice_uses_the_one_margin_rhythm():
    """The card is a flex column with a 16px gap; ANY margin on a notice adds
    to that gap rather than replacing it. Two call sites (both the LAST
    keyword argument before a closing paren, so lacking the trailing comma
    every other call had) were missed by an earlier pass for exactly that
    reason - measured live: 28px above the sync `_NewVersion` notice on
    `s-notices` against 16px everywhere else on the same screen.
    """
    bad = []
    for rel in ("app.py", "sync/completion.py", "shared/components.py",
                "scripts/completion_gallery.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        for call in _notice_calls(src):
            m = re.search(r'margin\s*=\s*"([^"]*)"', call)
            if m and m.group(1) not in ("0", ""):
                bad.append(f"{rel}: margin={m.group(1)!r} in {call[:60]!r}...")
    assert not bad, "\n".join(bad)


def test_the_screen_never_points_at_a_log_that_does_not_exist():
    """Never print an instruction without a destination - the SAME invariant the
    old "View Full Error Log" button was protecting, kept after that button was
    removed, and now enforced in the direction that actually applies.

    ``error_log_enabled`` is False by DEFAULT, so for most users
    download_errors.txt is never written. The conversion notice used to name it
    unconditionally in one branch and tell them to switch logging on in the
    other - a file that is not there, or an instruction to redo the whole run.
    It may now mention the file only inside the `error_log_enabled` gate.
    """
    comp = _code_only((REPO / "shared" / "components.py").read_text(encoding="utf-8"))
    body = comp.split("render_pp_warning", 1)[1].split("\ndef", 1)[0]
    assert "download_errors.txt" in body, "the log is worth naming when it exists"
    gate = body.index("error_log_enabled")
    assert body.index("download_errors.txt") > gate, \
        "download_errors.txt is named before the enabled check - most users have no such file"


def test_the_conversion_notice_says_the_original_file_survived():
    """The one question a failed conversion raises is whether the file is gone.

    The old copy ("N files failed during post-processing (conversion/extraction)")
    left it open, in our vocabulary rather than the user's.
    """
    comp = _code_only((REPO / "shared" / "components.py").read_text(encoding="utf-8"))
    body = comp.split("render_pp_warning", 1)[1].split("\ndef", 1)[0]
    assert "original" in body and "course folder" in body
    assert "post-processing" not in body, \
        "the user-facing string is back to our internal word for it"


def test_the_error_log_button_is_gone_from_both_completion_screens():
    """It was a stock Streamlit button offering a raw log, and it appeared on
    runs that had SUCCEEDED - a green screen whose only entries were locked
    files still invited the user to read an error log. Nothing it showed is
    absent from the screen itself, and nothing in it is actionable outside
    Canvas. `error_log_dialog` is kept for a future diagnostics surface."""
    comp = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    assert "def render_error_log_button" not in comp
    assert "def error_log_dialog" in comp, "the dialog itself was to be kept"
    for path in ("sync/completion.py", "app.py"):
        src = (REPO / path).read_text(encoding="utf-8")
        assert "render_error_log_button" not in src
        assert "View Full Error Log" not in src


def test_an_app_error_offers_a_report_instead():
    """What replaced it. An app-level error is the one failure a user genuinely
    cannot act on, so the only useful control is one that reaches the developer."""
    raw = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    assert "def build_app_error_actions" in raw
    assert "brkbuilds1@gmail.com" in raw
    body = raw.split("def build_app_error_actions", 1)[1].split("\ndef ", 1)[0]
    assert "mail.google.com" in raw, \
        "mailto: dead-ends on a machine with no mail client - see _GMAIL_COMPOSE"
    assert 'target="_blank"' in body, \
        "without it pywebview navigates the APP WINDOW to Gmail and ends the session"
    assert "app-err-copy-btn" in body, \
        "the copy control is the fallback for anyone not signed into Gmail"
    # A BAN is the opposite: the comment recording why this phrase was removed
    # necessarily contains it, so this one must read code only.
    assert "API connection" not in _code_only(raw), \
        "the old copy blamed the user's settings for a bug in ours"


def test_the_report_controls_live_inside_the_notice():
    """They are markup, not widgets, and that is structural.

    The app-error notice is rendered inside a raw-HTML ``<details>``, where a
    Streamlit widget cannot go. Putting the control anywhere a widget CAN go
    means putting it outside the box that explains it - which is where it was,
    reading as an unrelated button floating below the panel. Being an anchor
    also removes the stock-Streamlit-button problem permanently.
    """
    raw = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    section = raw.split("if app_errors:", 1)[1].split("body_html +=", 1)[1][:900]
    assert "build_app_error_actions(app_errors)" in section
    assert section.index("build_app_error_actions") < section.index("app_rows_html"), \
        "the controls belong above the technical rows, under the description"
    # Code only: the docstring explains WHY it is not an st.button, so it
    # necessarily contains the phrase this bans.
    code = _code_only(raw)
    actions = code.split("def\nbuild_app_error_actions", 1)[1].split("\ndef\n", 1)[0]
    assert "st\n.\nbutton" not in actions and "st\n.\ncolumns" not in actions, \
        "a Streamlit widget cannot be nested in the notice's raw HTML"
    assert "What gets sent" not in raw, \
        "the report is carried by the email body and the clipboard, not shown on screen"


def test_the_report_button_colour_survives_streamlits_link_style():
    """<a> tags get Streamlit's own link colour (measured: rgb(61,157,243), a
    plain markdown blue) which otherwise wins over a bare class selector - the
    button rendered blue-on-amber with an unstyled anchor colour until this."""
    css = (REPO / "styles" / "completion.css").read_text(encoding="utf-8")
    block = css.split(".app-err-report-btn,", 1)[1][:900]
    assert "color: #ffffff !important" in block


def test_the_fallback_email_cannot_be_autolinked():
    """Streamlit's markdown autolinks a bare email address INSIDE an explicit
    <b> tag, with unsafe_allow_html=True, even though nothing in our source is
    an anchor - measured directly in the rendered DOM. That produced a live
    mailto: link in the ONE place meant to be a plain-text fallback for the
    person the Gmail button doesn't work for, defeating the whole point of it.

    An HTML entity for the `@` does NOT fix this (also measured): the parser
    decodes entities to their literal character before the autolink scanner
    runs, so `&#64;` and `@` look identical to it. What works is breaking node
    ADJACENCY - an empty <wbr> splits the source into two text runs before
    remark ever sees one contiguous `word@word.word` shape.
    """
    raw = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    fn = raw.split("def _unlinkable_email", 1)[1].split("\ndef ", 1)[0]
    assert "<wbr>" in fn
    # Code only: the docstring explains why the entity approach was dropped, so
    # it necessarily contains the phrase this bans.
    assert "&#64;" not in _code_only(fn), \
        "entity substitution was tried and measured not to work"
    assert "_unlinkable_email(DEVELOPER_EMAIL)" in raw, \
        "the fallback line must route through the guard, not a bare esc()"


class _AppErr:
    def __init__(self, course="C", etype="Processing Error", msg="boom"):
        self.course_name, self.error_type, self.message = course, etype, msg


def _href(html: str) -> str:
    return html.split('href="', 1)[1].split('"', 1)[0].replace("&amp;", "&")


_CRASHY_HEALTH = "\n".join(
    f"2026-07-2{d} 1{d}:00:00Z  PREVIOUS SESSION DID NOT EXIT CLEANLY  pid={1000+d} "
    f"phase='downloading' uptime=412s peak_self=1804.2MB failures={{'x': 14}}"
    for d in range(9)
)


def test_the_email_url_fits_the_os_limit_however_many_errors_there_are():
    """pywebview hands the href to `webbrowser.open`, which on Windows reaches
    ShellExecuteW (historically ~2048 chars), and URL-encoding inflates log
    text. The errors are the one part the USER's situation controls, so the
    budget has to survive the bad case, not the typical one.

    Measured before the error cap existed: twelve maxed-out 220-character
    messages produced a 4,020-character URL against a 1,900 limit - trimming
    health lines alone could not reach it, because health was not what was
    large. Each case here failed at some point during development.
    """
    import shared.components as C
    orig = C._read_text_tail
    C._read_text_tail = lambda p, n: _CRASHY_HEALTH
    try:
        cases = {
            "1 error": [_AppErr()],
            "12 maxed": [_AppErr(f"Some Long Course Name {i} (LA E25 BSTAT10{i}0U)",
                                 "Processing Error", "x" * 220) for i in range(12)],
            "40 maxed": [_AppErr(f"Course {i}", "Phase Crash", "y" * 220)
                         for i in range(40)],
            # One error too long for the budget on its own: the loop cannot
            # trim its way out, so the body itself must be cut.
            "1 enormous": [_AppErr("C", "Processing Error", "z" * 5000)],
        }
        for label, errs in cases.items():
            url = _href(C.build_app_error_actions(errs))
            assert len(url) <= C._EMAIL_URL_LIMIT, \
                f"{label}: {len(url)} chars exceeds {C._EMAIL_URL_LIMIT}"
    finally:
        C._read_text_tail = orig


def test_the_email_keeps_the_crash_lines_not_the_routine_ones():
    """A plain tail of health.log is the obvious approach and it is wrong.

    On a log that is almost entirely routine SESSION START/END pairs - the
    normal shape for anyone who has opened the app a few dozen times - a tail
    shows twelve clean sessions and misses the unclean-exit line entirely,
    which `core/health_log.py` calls "the single highest-value signal".
    Measured: 7 of 9 slots went to identical "SESSION END (clean)" lines.
    """
    import shared.components as C
    chatty = "\n".join(
        f"2026-07-{d:02d} 0{h}:00:00Z  SESSION "
        + ("START  app=2.0.1 os=Windows 11" if h % 2 == 0
           else "END (clean)  uptime=1200s peak_self=290.0MB")
        for d in range(10, 30) for h in range(2, 8)
    ) + ("\n2026-07-29 23:00:00Z  PREVIOUS SESSION DID NOT EXIT CLEANLY  "
         "pid=999 phase='analysis' uptime=77s peak_self=180.0MB")

    orig = C._read_text_tail
    C._read_text_tail = lambda p, n: chatty
    try:
        report = C.build_app_error_report([_AppErr()])
    finally:
        C._read_text_tail = orig
    assert "DID NOT EXIT CLEANLY" in report, \
        "the one diagnostic line in 121 was dropped for routine chatter"
    # And it must not be padded back out with the noise it just filtered.
    assert report.count("SESSION END (clean)") <= 1
    assert "earlier line" in report, "silent trimming hides how much was cut"


def test_the_report_no_longer_ships_a_bare_log_path():
    """A path is worthless the moment the mail leaves the machine - the whole
    reason this was rebuilt. The lines themselves have to travel."""
    import shared.components as C
    orig = C._read_text_tail
    C._read_text_tail = lambda p, n: _CRASHY_HEALTH
    try:
        report = C.build_app_error_report([_AppErr()])
    finally:
        C._read_text_tail = orig
    assert "Full session log:" not in report
    assert "DID NOT EXIT CLEANLY" in report, "log CONTENT must be present instead"


def test_the_clipboard_bundle_carries_more_than_the_email():
    """Two channels, two capacities: the URL is capped, the clipboard is not.
    If they ever produce the same thing, the copy button has no reason to
    exist and the paste marker in the email body is a lie."""
    import shared.components as C
    orig = C._read_text_tail
    C._read_text_tail = lambda p, n: _CRASHY_HEALTH
    try:
        email = C.build_app_error_report([_AppErr()], max_health_lines=3)
        bundle = C.build_app_error_bundle([_AppErr()])
    finally:
        C._read_text_tail = orig
    assert len(bundle) > len(email)
    assert "=== health.log ===" in bundle, "the bundle is the whole log, verbatim"


def test_the_debug_log_registry_catches_every_file_written():
    """`clear_debug_log` is called from only 3 sites while `canvas_logic`
    builds `<save_dir>/debug_log.txt` per COURSE and announces it nowhere -
    so registering at construction time would miss most of them. Registering
    on WRITE is the only rule that cannot, and "was written to" is also the
    right definition: an empty log is not worth attaching."""
    import tempfile
    from core.canvas_debug import log_debug, session_debug_files
    path = Path(tempfile.mkdtemp()) / "debug_log.txt"
    log_debug("something happened", str(path))
    assert str(path) in session_debug_files()


def test_the_gmail_link_opens_the_full_interface():
    """`view=cm` opens the standalone compose PAGE - a text editor on a blank
    white canvas with no Gmail around it, which reads as a broken page right
    after the user has been told to report a bug. `tf=cm` opens the real Gmail
    interface with compose inside it, and `fs` is documented as doing nothing
    at all any more."""
    import shared.components as C
    assert "tf=cm" in C._GMAIL_COMPOSE
    assert "view=cm" not in C._GMAIL_COMPOSE
    assert "fs=1" not in C._GMAIL_COMPOSE


def test_the_app_error_badge_sits_beside_its_title():
    """Matching .err-col-header, whose title carries no flex either - the badge
    belongs next to the thing it counts, not pushed to the far right edge."""
    css = (REPO / "styles" / "completion.css").read_text(encoding="utf-8")
    # Blank comments first: the rule documents WHY `flex: 1` was removed, so it
    # necessarily contains the declaration this bans. `verify_architecture.py`
    # blanks comments for the same reason before its own CSS rules run.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    block = css.split(".app-error-section-title", 1)[1].split("}", 1)[0]
    assert "flex: 1" not in block


def test_errors_are_not_numbered_in_a_way_gmail_turns_into_a_list():
    """Gmail's compose box is a rich-text editor: a line starting "1. " is
    auto-formatted into an ordered LIST, which discards the literal marker and
    re-indents the block. Observed in a real report - the pasted bundle arrived
    with the numbers gone, so with several errors there was no way to tell
    which message belonged to which."""
    import shared.components as C
    orig = C._read_text_tail
    C._read_text_tail = lambda p, n: ""
    try:
        report = C.build_app_error_report([_AppErr(), _AppErr(), _AppErr()])
    finally:
        C._read_text_tail = orig
    assert "#1 " in report and "#2 " in report, "error indices must survive"
    for line in report.splitlines():
        assert not re.match(r"\s*\d+\.\s", line), \
            f"Gmail will convert this line into a list item: {line!r}"


def test_the_pasted_bundle_is_marked_off_from_the_email_body():
    """It is pasted UNDER a body that already carries the environment header,
    so without a banner the reader meets the same four lines twice with nothing
    to say where the summary ends and the full record starts."""
    import shared.components as C
    orig = C._read_text_tail
    C._read_text_tail = lambda p, n: _CRASHY_HEALTH
    try:
        bundle = C.build_app_error_bundle([_AppErr()])
    finally:
        C._read_text_tail = orig
    assert bundle.splitlines()[0].startswith("====="), \
        "the paste needs an unmistakable first line"
    assert "FULL DIAGNOSTIC REPORT" in bundle.splitlines()[0]


def test_the_bundle_is_size_capped():
    """It is embedded as a hidden span and re-escaped on EVERY render of the
    completion screen, and the debug-tail budget is per FILE with one file per
    course - so a 12-course download could otherwise put ~750 KB of text in the
    DOM on every rerun, to serve a button most users never press."""
    import shared.components as C
    orig = C._read_text_tail
    # A health log far larger than the cap, on its own.
    C._read_text_tail = lambda p, n: ("x" * 400_000)
    try:
        bundle = C.build_app_error_bundle([_AppErr()])
    finally:
        C._read_text_tail = orig
    assert len(bundle) <= C._BUNDLE_MAX_CHARS + 200, \
        f"bundle grew to {len(bundle)} chars"
    assert bundle.startswith("====="), "the head must survive truncation"
    assert "truncated" in bundle, "a silent cut hides that data is missing"


def test_non_ascii_course_names_still_fit_the_url():
    """This app's users have Danish course names, and URL-encoding a non-ASCII
    character costs 6 characters instead of 1 - so the budget is consumed far
    faster than an English test would ever reveal. Measured: 2 Danish errors
    reach 1,812 of 1,900, leaving 88 characters of headroom."""
    import shared.components as C
    orig = C._read_text_tail
    C._read_text_tail = lambda p, n: _CRASHY_HEALTH
    try:
        for n in (1, 2, 4, 20):
            errs = [_AppErr(
                f"Indføring i organisationers opbygning og funktion {i} (LA E25 BINTO106{i}U)",
                "Processing Error",
                "kunne ikke åbne filen 'Forelæsningsvideo – Økonomistyring "
                "og regnskabsanalyse.docx' på grund af en uventet fejl")
                for i in range(n)]
            url = _href(C.build_app_error_actions(errs))
            assert len(url) <= C._EMAIL_URL_LIMIT, \
                f"{n} Danish errors: {len(url)} chars"
            body = urllib.parse.unquote_plus(url.split("&body=", 1)[1])
            assert "Indføring" in body, "non-ASCII must survive the roundtrip"
            # However tight it gets, the crash signal must not be squeezed out
            # entirely - that is the whole reason the report exists.
            assert "DID NOT EXIT CLEANLY" in body, f"{n} errors lost all health lines"
    finally:
        C._read_text_tail = orig


def test_the_paste_prompt_explains_itself():
    """"--- PASTE THE FULL REPORT BELOW ---" was meaningless to the person
    reading it: nothing had told them a clipboard copy happened, so the
    instruction referred to something they did not know they had. It must say
    WHAT is on the clipboard, that it is already there, and that sending
    without pasting is still worthwhile - otherwise a user who cannot paste
    concludes the report is void and abandons it."""
    import shared.components as C
    m = C._PASTE_MARKER
    assert "clipboard" in m.lower(), "must say where the log already is"
    assert "Ctrl+V" in m and "Cmd+V" in m, "must name the keystroke on both OSes"
    assert "as-is" in m.lower() or "still useful" in m.lower(), \
        "a user who cannot paste must not think the report is worthless"


def test_recent_activity_is_captured_even_with_debug_logging_off():
    """THE default case. `debug_log.txt` is opt-in and OFF by default, so the
    one moment the narration matters - an app error on a stranger's machine -
    was the one where nothing had been written down. `log_debug` breadcrumbs
    before its `debug_file` guard, so a call with None still records."""
    from core.canvas_debug import log_debug, breadcrumbs, session_debug_files
    before = len(breadcrumbs().splitlines())
    log_debug("marker-for-the-breadcrumb-test", None)     # debug logging OFF
    crumbs = breadcrumbs()
    assert "marker-for-the-breadcrumb-test" in crumbs
    assert len(crumbs.splitlines()) >= before
    assert not any("marker-for-the-breadcrumb" in p for p in session_debug_files()), \
        "nothing may be written to DISK when debug logging is off"


def test_breadcrumbs_are_redacted_and_bounded():
    """They are transmitted when the user reports a bug, so the same redaction
    the debug FILE gets applies - and the deque is capped so a long download
    cannot grow it without limit."""
    from core.canvas_debug import (log_debug, breadcrumbs, _BREADCRUMB_LINES)
    for i in range(_BREADCRUMB_LINES + 200):
        log_debug(f"row {i} Bearer sup3rs3cr3t verifier=abc123def", None)
    crumbs = breadcrumbs()
    assert len(crumbs.splitlines()) <= _BREADCRUMB_LINES
    assert "sup3rs3cr3t" not in crumbs, "Bearer token reached the report"
    assert "abc123def" not in crumbs, "signed-URL verifier reached the report"
    assert "[REDACTED]" in crumbs


def test_breadcrumb_capture_is_cheap_enough_to_be_unconditional():
    """It runs on the order of 10^5 times in a large download, which is why
    the message is stored RAW and redacted once at read time instead of being
    sanitized on every append (measured 23x cheaper: 0.014s vs 0.324s per
    100k). If this ever regresses, always-on capture stops being defensible."""
    import time
    from core.canvas_debug import log_debug
    t0 = time.perf_counter()
    for i in range(20000):
        log_debug(f"perf probe {i}", None)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"20k breadcrumb appends took {elapsed:.2f}s"


def test_a_failed_copy_is_visible():
    """The fallback path used to swallow its own failure, so a refused
    clipboard write produced a button that appeared to do nothing - which a
    user cannot tell apart from a broken control. Both outcomes now end in a
    visible state."""
    raw = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    body = raw.split("def inject_app_error_copy_bridge", 1)[1].split("\ndef ", 1)[0]
    assert "flag('failed')" in body, "a refused copy must say so"
    assert "win.focus()" in body, \
        "the async API rejects on an unfocused document - the normal state " \
        "after the report link just opened Gmail"
    css = (REPO / "styles" / "completion.css").read_text(encoding="utf-8")
    assert ".app-err-copy-btn.failed" in css
    assert "--cd-cross" in css


def test_the_copy_bridge_rebinds_every_run():
    """`components.html` builds a fresh iframe per rerun and destroys the last
    one, so a listener attached from a dead realm silently stops firing. A
    one-time guard is how this class of bridge dies after the first rerun."""
    raw = (REPO / "shared" / "components.py").read_text(encoding="utf-8")
    body = raw.split("def inject_app_error_copy_bridge", 1)[1].split("\ndef ", 1)[0]
    assert "removeEventListener" in body and "addEventListener" in body
    assert "win._cdErrCopy" in body, "handler ref must survive on window.parent"
    assert "win.navigator.clipboard" in body, \
        "the click's user activation belongs to the PARENT document"
    assert "execCommand" in body, "and a fallback for where the API is unavailable"


def test_the_copy_bridge_is_collapsed_out_of_flow_on_the_main_page():
    """A `components.html(height=0)` iframe is still a FLOW SIBLING, and a
    flex `gap` applies between boxes regardless of their own height - so an
    invisible 0-height iframe still costs one full gap slot on both sides of
    it. Measured live: the error panel sat 32px from the Retry button whenever
    the run had an app-level error (the only case this bridge injects),
    exactly double the 16px every other row on the same card uses.

    The existing `global.css` rule for this bridge FAMILY matches
    `iframe[height="0"]` - the attribute on the <iframe> element itself. This
    bridge's iframe carries no such attribute; the WRAPPING
    stElementContainer carries `height="0px"` instead (confirmed by
    inspecting the live DOM - ordinary content containers measured
    `height="auto"`, so the attribute is a safe, specific signal). Without a
    second selector matching that, this bridge was invisible in code review
    and in a screenshot taken without measuring gaps.
    """
    css = (REPO / "styles" / "global.css").read_text(encoding="utf-8")
    assert '[height="0px"]:has(iframe)' in css, \
        "no selector matches a components.html bridge whose CONTAINER (not " \
        "the iframe) carries the zero-height attribute"


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
