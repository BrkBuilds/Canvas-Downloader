"""Tests for the Panopto acceptable-use acknowledgement (shared/legal.py).

Two families here, and they fail for different reasons:

* **Persistence** - versioning, failing closed, and not clobbering the rest of
  the settings file. Ordinary unit tests against a redirected config dir.
* **Wiring** - that the guard is actually reachable from every path by which a
  recording can be fetched. These are source-level, because the failure they
  catch is a path that silently never calls the guard, which no behavioural test
  of the other four paths can see. They assert presence and ORDER, never
  adjacency: anchoring on two statements being neighbours makes an unrelated
  comment insertion look like the guard has been removed.
"""

from __future__ import annotations

import json
import pathlib
from urllib.parse import urlparse

import pytest

import shared.legal as legal

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Redirect the settings file into a temp dir for the duration of a test."""
    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    return tmp_path / "canvas_downloader_settings.json"


# ── Persistence ──────────────────────────────────────────────────────────────

def test_no_settings_file_means_not_acknowledged(cfg):
    assert not cfg.exists()
    assert legal.stored_ack_version() == 0
    assert legal.panopto_notice_acknowledged() is False


def test_record_then_acknowledged(cfg):
    assert legal.record_panopto_acknowledgement() is True
    assert legal.stored_ack_version() == legal.PANOPTO_NOTICE_VERSION
    assert legal.panopto_notice_acknowledged() is True


def test_older_stored_version_re_prompts(cfg):
    """Bumping PANOPTO_NOTICE_VERSION must re-ask everyone. That is the only
    mechanism by which a change to the terms reaches an existing install."""
    cfg.write_text(json.dumps({legal.ACK_KEY: legal.PANOPTO_NOTICE_VERSION - 1}),
                   encoding="utf-8")
    assert legal.panopto_notice_acknowledged() is False


def test_newer_stored_version_still_counts(cfg):
    """A downgrade must not re-prompt: the user accepted strictly more."""
    cfg.write_text(json.dumps({legal.ACK_KEY: legal.PANOPTO_NOTICE_VERSION + 5}),
                   encoding="utf-8")
    assert legal.panopto_notice_acknowledged() is True


@pytest.mark.parametrize("stored", ["yes", None, "", [], {}, "1.5"])
def test_non_numeric_stored_value_fails_closed(cfg, stored):
    """Showing the notice twice is harmless; skipping it silently is the whole
    failure this module exists to prevent."""
    cfg.write_text(json.dumps({legal.ACK_KEY: stored}), encoding="utf-8")
    assert legal.stored_ack_version() == 0
    assert legal.panopto_notice_acknowledged() is False


def test_corrupt_settings_file_fails_closed(cfg):
    cfg.write_text("{not json at all", encoding="utf-8")
    assert legal.panopto_notice_acknowledged() is False


def test_record_preserves_other_top_level_keys(cfg):
    """The settings file is shared with ui/auth.py and panopto/settings.py. A
    non-atomic or non-merging write here would silently drop the user's saved
    token settings or their whole Panopto engine config."""
    cfg.write_text(json.dumps({
        "show_help_text": False,
        "canvas_url": "https://example.instructure.com",
        "panopto": {"model": "large-v3", "device": "cuda"},
    }), encoding="utf-8")

    assert legal.record_panopto_acknowledgement() is True

    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["show_help_text"] is False
    assert data["canvas_url"] == "https://example.instructure.com"
    assert data["panopto"] == {"model": "large-v3", "device": "cuda"}
    assert data[legal.ACK_KEY] == legal.PANOPTO_NOTICE_VERSION


def test_ack_key_is_not_a_panopto_contract_key():
    """The acknowledgement must NOT live in PANOPTO_DEFAULTS.

    compose_settings() starts from dict(PANOPTO_DEFAULTS), so a key there is
    copied into every composed run config and persisted into every synced
    folder's manifest. It is a one-time global fact about the user, not a
    property of a download.
    """
    from panopto.settings import PANOPTO_DEFAULTS
    assert legal.ACK_KEY not in PANOPTO_DEFAULTS


def test_write_failure_is_reported_not_raised(cfg, monkeypatch):
    """A read-only config dir must not take the app down."""
    def _boom(*a, **k):
        raise OSError("read-only file system")
    monkeypatch.setattr(legal.os, "replace", _boom)
    assert legal.record_panopto_acknowledgement() is False


# ── Decline = "skip Panopto, but still run" ──────────────────────────────────

@pytest.fixture
def stub_st(monkeypatch, tmp_path):
    """A streamlit stub whose session_state is a plain dict.

    shared.legal imports streamlit INSIDE each function, so replacing the module
    in sys.modules is enough. Real st.session_state does not work outside a
    script run ("Session state does not function when running a script without
    streamlit run"), which is why these behaviours cannot be tested against it.
    """
    import sys
    import types

    monkeypatch.setenv("CANVAS_DL_CONFIG_DIR", str(tmp_path))
    stub = types.ModuleType("streamlit")
    stub.session_state = {}
    monkeypatch.setitem(sys.modules, "streamlit", stub)
    return stub


def test_skip_sets_the_run_flag_and_strips_the_outputs(stub_st):
    """Zeroing persistent_pan_* IS the mechanism. A flag that nothing downstream
    honoured would let "skip" quietly download several GB of lectures."""
    from core.state_registry import PANOPTO_OUTPUT_KEYS
    for k in PANOPTO_OUTPUT_KEYS:
        stub_st.session_state[f"persistent_{k}"] = True

    legal.skip_panopto_and_continue()

    assert legal.panopto_skipped_this_run() is True
    assert all(stub_st.session_state[f"persistent_{k}"] is False
               for k in PANOPTO_OUTPUT_KEYS)


def test_skip_does_not_record_consent(stub_st):
    """Someone who declines every time is asked every time - they never agreed."""
    legal.skip_panopto_and_continue()
    assert legal.panopto_notice_acknowledged() is False


def test_skip_leaves_the_users_card_selections_alone(stub_st):
    """Only the per-run copies are stripped. pan_out_* is configuration, and a
    one-off decline must not silently reconfigure the download settings card."""
    from core.state_registry import PANOPTO_OUTPUT_KEYS
    for k in PANOPTO_OUTPUT_KEYS:
        stub_st.session_state[k] = True

    legal.skip_panopto_and_continue()

    assert all(stub_st.session_state[k] is True for k in PANOPTO_OUTPUT_KEYS)


@pytest.mark.parametrize("answer", ["skip", "accept"])
def test_answering_arms_the_resume_but_does_not_fire_it(stub_st, answer):
    """REGRESSION (reported 2026-07-31): the dialog stayed on screen, greyed,
    on top of a running download for 5-7 seconds.

    Applying the resume in the same run that closes the modal sends that run
    into asyncio.run(download_course_async(...)) at app.py:1359, which blocks
    far above the dialog host at app.py:2586. Streamlit drops an element only
    when a COMPLETED run stops producing it, so the modal was marked stale
    (hence the grey) but never removed. The action must therefore be armed, not
    applied, and fired only after a run has finished without the dialog.
    """
    stub_st.session_state[legal.RESUME_KEY] = {"download_status": "scanning", "step": 3}

    if answer == "skip":
        legal.skip_panopto_and_continue()
    else:
        legal.accept_panopto_notice()

    assert legal.resume_is_pending() is True
    assert "download_status" not in stub_st.session_state, (
        "the resume fired in the run that closes the dialog - the modal will "
        "stay painted over the blocking download"
    )
    assert legal.NOTICE_OPEN_KEY not in stub_st.session_state


@pytest.mark.parametrize("answer", ["skip", "accept"])
def test_the_armed_resume_fires_when_applied(stub_st, answer):
    stub_st.session_state[legal.RESUME_KEY] = {"download_status": "scanning", "step": 3}
    (legal.skip_panopto_and_continue if answer == "skip"
     else legal.accept_panopto_notice)()

    legal.apply_pending_resume()

    assert stub_st.session_state["download_status"] == "scanning"
    assert stub_st.session_state["step"] == 3
    assert legal.RESUME_KEY not in stub_st.session_state
    assert legal.resume_is_pending() is False


def test_accept_still_records_consent(stub_st):
    legal.accept_panopto_notice()
    assert legal.panopto_notice_acknowledged() is True
    assert legal.panopto_skipped_this_run() is False


def test_dismiss_leaves_nothing_pending(stub_st):
    """Escape must not arm anything - there is no action to carry out."""
    stub_st.session_state[legal.RESUME_KEY] = {"download_status": "scanning"}
    legal.dismiss_panopto_notice()
    assert legal.resume_is_pending() is False


def test_advancer_waits_for_the_teardown_run():
    """The first call is INLINE, during the run that closed the dialog, and must
    return without acting - letting that run reach the end of the script is what
    actually removes the modal from the DOM."""
    src = _src("ui/panopto_notice.py")
    body = src[src.index("def render_pending_resume"):]
    tick = body.index("if seen == 0:")
    apply_at = body.index("apply_pending_resume()")
    assert tick < apply_at
    assert "return" in body[tick:apply_at]


def test_app_hosts_the_advancer_only_when_the_dialog_is_closed():
    """Rendering both in one run would defeat the whole two-step."""
    src = _src_no_comments("app.py")
    assert "elif _pan_resume_pending():" in src
    assert src.index("render_panopto_notice()") < src.index("render_pending_resume()")


def test_declining_does_not_re_prompt_for_the_same_run(stub_st):
    """Re-asking would make the decline unreachable - every retry re-opens the
    same modal and the user can never get past it."""
    legal.skip_panopto_and_continue()
    stub_st.session_state.pop(legal.NOTICE_OPEN_KEY, None)

    assert legal.require_panopto_notice() is True
    assert legal.NOTICE_OPEN_KEY not in stub_st.session_state


def test_dismiss_drops_the_resume_so_it_cannot_fire_later(stub_st):
    """Escape means "I did not answer", so the action is dropped. A surviving
    payload would fire the next time the notice appeared from somewhere else."""
    stub_st.session_state[legal.RESUME_KEY] = {"download_status": "scanning"}
    legal.dismiss_panopto_notice()
    assert legal.RESUME_KEY not in stub_st.session_state
    assert "download_status" not in stub_st.session_state


def test_resume_payload_is_plain_data():
    """Never a stored callable: the sync path's action opens a dialog, and
    invoking that from inside the notice modal nests two - which Streamlit
    refuses outright."""
    src = _src("shared/legal.py")
    body = src[src.index("def apply_pending_resume"):]
    assert "callable(" not in body
    # The payload is iterated as key/value pairs, never invoked.
    assert "for k, v in resume.items()" in body


def test_review_sync_reads_the_decline_before_clearing_it():
    """This block RE-RUNS after the notice is answered and rebuilds
    sync_selections from the UI, still carrying every ticked recording. Clearing
    first destroys the only evidence the user said no."""
    src = _src_no_comments("ui/sync_review.py")
    read = src.index("panopto_skipped_this_run()")
    clear = src.index("clear_panopto_skip()")
    assert read < clear


# ── Unattended runs (Today) never block, and never fetch without consent ─────

def test_unattended_run_skips_panopto_when_consent_is_missing():
    """start_today_sync fires by itself on the first app open of the day. It
    must not raise a modal at a run the user did not start, and it must not
    fetch recordings they never agreed to - so it marks the run skipped."""
    src = _src_no_comments("core/auto_sync.py")
    fn = src[src.index("def start_today_sync"):]
    assert "panopto_notice_acknowledged()" in fn
    # The ASSIGNMENT, not the bare name: SKIP_RUN_KEY also appears on the import
    # line, so a token check stays green when the assignment is deleted (found
    # by mutation - the same trap as the require_panopto_notice import).
    assert "st.session_state[SKIP_RUN_KEY] = True" in fn
    assert "require_panopto_notice" not in fn, (
        "the unattended daily sync must never raise the notice"
    )


def test_quick_sync_selects_no_recordings_when_skipped():
    """The flag has to reach the SELECTION, not just be set. Quick Sync builds
    its own panopto list, so an unhonoured flag would sync recordings anyway."""
    import ast

    src = _src("sync/analysis.py")
    assert "panopto_skipped_this_run()" in src

    # AST, not a substring: the decline is read into `_pan_declined` on its own
    # line, so a token check survives the loop reverting to the raw list (found
    # by mutation). What matters is that the loop iterates a CONDITIONAL.
    loops = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.For) and getattr(n.target, "id", "") == "_c"]
    assert loops, "the quick-sync panopto selection loop moved"
    assert any(isinstance(n.iter, ast.IfExp) for n in loops), (
        "the quick-sync selection loop iterates the raw change list - a "
        "declined or unattended run would sync recordings anyway"
    )


def test_today_card_requires_all_three_conditions():
    """Any one missing makes the card noise: a university without Panopto would
    be told about a feature it does not have, and an answered notice or a
    dismissal means the user has already decided."""
    src = _src_no_comments("ui/today_dashboard.py")
    fn = src[src.index("def _panopto_optin_needed"):]
    fn = fn[:fn.index("\ndef ", 1)]
    assert "PANOPTO_OPTIN_DISMISSED_KEY" in fn
    assert "panopto_notice_acknowledged()" in fn
    assert "panopto_feature_available()" in fn


def test_today_card_opens_the_notice_in_optin_context():
    """"Skip Panopto recordings" is nonsense on an opt-in - the user is turning
    something ON that is already off."""
    src = _src_no_comments("ui/today_dashboard.py")
    fn = src[src.index("def _open_panopto_optin"):]
    assert '"optin"' in fn[:fn.index("\ndef ", 1)]


# ── Wiring: the guard is reachable from every Panopto entry path ─────────────

def _src(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _src_no_comments(rel: str) -> str:
    """Source with ``#`` comments blanked, length preserved so offsets still line up.

    Same rule the architecture audit follows: a check that scans for a token has
    to ignore the comment that EXPLAINS the token, or documenting the invariant
    is what breaks the test policing it. Length is preserved (spaces, not
    deletion) so ``.index()`` positions remain comparable across both forms.
    """
    out = []
    for line in _src(rel).splitlines(keepends=True):
        body = line.rstrip("\r\n")
        eol = line[len(body):]
        out.append(" " * len(body) + eol if body.lstrip().startswith("#") else line)
    return "".join(out)


@pytest.mark.parametrize("rel", [
    "ui/download_settings.py",   # Custom Download start
    "ui/quick_download.py",      # Quick Download presets (3 of 5 include Panopto)
    "ui/sync_review.py",         # Review sync, before the confirm dialog opens
    "sync_ui.py",                # Quick Sync button
])
def test_every_panopto_entry_path_calls_the_guard(rel):
    """The CALL form, with parentheses, on purpose.

    A bare-name check passes on the ``from shared.legal import
    require_panopto_notice`` line alone, so deleting the actual call left this
    test green (found by mutating the source and re-running). The import carries
    no parentheses; only an invocation does.
    """
    assert "require_panopto_notice(" in _src_no_comments(rel), (
        f"{rel} can start a Panopto download without passing the "
        f"acceptable-use guard"
    )


@pytest.mark.parametrize("rel", [
    "ui/download_settings.py",
    "ui/quick_download.py",
    "ui/sync_review.py",
    "sync_ui.py",
])
def test_every_entry_path_passes_a_resume_payload(rel):
    """A guard call WITHOUT a resume swallows the click.

    The modal consumes the button press, so answering it would close the dialog
    and leave the user on an unchanged screen having achieved nothing - they
    would have to press the button a second time. Passing resume=None reads as
    deliberate and was NOT caught until this test existed (found by mutation).
    """
    src = _src_no_comments(rel)
    call = src.index("require_panopto_notice(")
    args = src[call:call + 200]
    assert "resume=" in args, f"{rel} gates the run but cannot resume it"
    assert "resume=None" not in args, f"{rel} passes an empty resume payload"


@pytest.mark.parametrize("rel,commit", [
    # The statement that actually commits the run, per path. The guard must
    # precede it; anything after it is too late to hold anything back.
    ("ui/quick_download.py", "st.session_state['download_status'] = 'scanning'"),
    ("sync_ui.py", "st.session_state['sync_quick_mode'] = True"),
])
def test_guard_precedes_the_statement_that_starts_the_run(rel, commit):
    src = _src_no_comments(rel)
    assert src.index("require_panopto_notice(") < src.index(commit)


def test_review_sync_gates_before_opening_the_confirm_dialog():
    """The guard must run BEFORE on_confirm_sync.

    _show_sync_confirmation is itself an @st.dialog, and Streamlit crashes on a
    nested dialog. Gating after it opens would not merely be late, it would take
    the app down. Compared by position, not adjacency.
    """
    src = _src("ui/sync_review.py")
    guard = src.index("require_panopto_notice(")
    invoke = src.index("on_confirm_sync(sync_selections")
    assert guard < invoke


def test_confirm_sync_is_still_a_dialog():
    """Guards the reason the check above exists. If Confirm Sync ever stops
    being an @st.dialog this test fails, prompting a re-read of that rule rather
    than leaving a now-mysterious comment behind."""
    src = _src("sync_ui.py")
    idx = src.index("def _show_sync_confirmation")
    assert "@st.dialog" in src[max(0, idx - 200):idx]


def test_notice_dialog_is_hosted_before_the_other_dialogs():
    """app.py hosts all modals at the bottom; only one may open per run. The
    notice gates the feature, so it takes precedence over both others."""
    src = _src_no_comments("app.py")
    notice = src.index("render_panopto_notice")
    transcription = src.index("render_transcription_dialog")
    settings = src.index("open_pending_global_dialog")
    assert notice < transcription < settings


def test_notice_dialog_host_is_actually_reachable():
    """Ordering alone is not enough: a host disabled with ``if False and ...``
    keeps every name in place and in order, so the ordering test above stayed
    green through exactly that mutation. Assert the branch's CONDITION is a live
    read of the open-flag with no constant short-circuiting it.
    """
    import ast

    tree = ast.parse(_src("app.py"))
    hosts = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and any(isinstance(n, ast.Name) and n.id == "render_panopto_notice"
                for n in ast.walk(ast.Module(body=node.body, type_ignores=[])))
    ]
    assert len(hosts) == 1, "expected exactly one host for the notice dialog"

    test_src = ast.dump(hosts[0].test)
    assert "_PAN_NOTICE_OPEN" in test_src or "NOTICE_OPEN_KEY" in test_src, (
        "the notice host no longer reads the open-flag"
    )
    consts = [n for n in ast.walk(hosts[0].test)
              if isinstance(n, ast.Constant) and isinstance(n.value, bool)]
    assert not consts, (
        f"the notice host's condition is short-circuited by a constant: {test_src}"
    )


def test_settings_card_never_raises_the_notice():
    """Ticking a Panopto output is CONFIGURATION, not intent to download.

    Removed 2026-07-31. It fired mid-configuration and then fired again at
    Start, so a user who ticked a box and pressed the button was asked twice.
    It is the same misjudgement the notice would make if it prompted when a
    course is added to the daily-sync list. The run-start guards cover every
    path a recording can actually be fetched through, and this card's permanent
    note carries the information while the user configures.
    """
    src = _src_no_comments("ui/download_settings.py")
    assert "offer_panopto_notice_once" not in src


def test_the_passive_trigger_helper_is_gone():
    """Dead code with a live-looking name invites someone to wire it back in."""
    import shared.legal as legal
    assert not hasattr(legal, "offer_panopto_notice_once")
    assert "offer_panopto_notice_once" not in _src("shared/legal.py")


def test_no_prompt_when_the_feature_cannot_run():
    """A dialog about downloading Panopto is nonsense at a university that has
    no Panopto tool, and doubly so when the user switched it off themselves."""
    src = _src_no_comments("shared/legal.py")
    guard = src.index("def require_panopto_notice")
    # Slice to the NEXT top-level def, not a guessed character count - this
    # function's docstring alone is longer than the window I first used.
    nxt = src.index("\ndef ", guard + 1)
    body = src[guard:nxt]
    assert "panopto_feature_available()" in body
    assert body.index("panopto_feature_available()") < body.index("_SESSION_ACK_KEY")


def test_card_note_is_not_gated_behind_help_text():
    """The reminder is operational copy. Settings -> Show help text must never
    be able to hide a statement about what the software does and does not do."""
    src = _src_no_comments("ui/download_settings.py")
    note = src.index("cd-pan-usage-note")
    window = src[max(0, note - 1500):note]
    assert "help_text_enabled" not in window


def test_card_note_has_styling():
    """A class with no rule renders as unstyled body text with no separator.

    Anchored on the BASE rule's opening brace, not the bare class name: the
    ``.cd-pan-usage-note a`` link rules also contain the name, so renaming the
    base selector alone left this green (found by mutation).
    """
    css = _src("styles/global.css")
    assert ".cd-pan-usage-note {" in css


def test_disclaimer_url_has_one_definition():
    """The modal and the card note must not drift onto different URLs.

    The host is DERIVED from ``legal.DISCLAIMER_URL``, never written as a
    literal. A hardcoded domain stops guarding anything the moment the site
    moves - and it did move (birkls.github.io -> canvasdownloader.app),
    which would have left this green against a freshly hardcoded URL.
    """
    host = urlparse(legal.DISCLAIMER_URL).netloc
    assert host, "DISCLAIMER_URL must carry a host"
    assert _src("ui/panopto_notice.py").count(host) == 0
    assert legal.DISCLAIMER_URL.startswith("https://")


def test_disclaimer_document_states_the_download_setting_limitation():
    """The one admission the whole document's credibility rests on: the app does
    not read Panopto's per-recording download permission. If this sentence ever
    disappears, the notice starts implying a check that does not happen."""
    text = _src("DISCLAIMER.md").lower()
    assert "does not read that setting" in text
    assert "brkbuilds1@gmail.com" in text
