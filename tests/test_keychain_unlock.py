"""The macOS Keychain prompt must never block the first paint.

WHY THIS FILE EXISTS, measured on macOS 26.6.1 in the PACKAGED app:
``restore_saved_session`` runs on the Streamlit script thread during init, and
``keyring``'s macOS backend calls ``SecItemCopyMatching`` with no UI-suppression
flag. When the saved item's ACL does not trust the running binary that call
BLOCKS on a system prompt, so the script never finishes and the window stays
dead - the boot overlay showed "Connecting..." for its 30s cap and then the
window was COMPLETELY EMPTY until the prompt was answered or the 90s watchdog
fired. It fires on every app UPDATE, because the bundle is ad-hoc signed and
both the trusted-application list and the partition list key on the signature.

Two escapes were measured and are closed, so nobody re-derives them:
  * ``security add-generic-password -A`` (trusted-app list ``<null>``) still
    prompts - the partition list (``apple-tool:``) gates it independently.
  * The app cannot silently repair its own ACL afterwards: the delete half of
    delete+add needs authorisation we do not have and fails ``-25244``.

So the prompt stays; what these tests pin is that it is never in the way, that
the classification is exact, and that the copy keeps the one instruction that
was measured to matter (plain "Allow" leaves the ACL untouched and re-prompts on
EVERY launch; "Always Allow" updates it).
"""

from __future__ import annotations

import ast
import inspect
import re
import sys
import threading
import time
from pathlib import Path

import pytest

import ui.auth as auth

AUTH_SRC = Path(__file__).resolve().parents[1] / "ui" / "auth.py"


def _fn(name: str) -> ast.FunctionDef:
    tree = ast.parse(AUTH_SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found in ui/auth.py")


def _calls(node: ast.AST) -> set[str]:
    """Every function NAME called anywhere inside *node*.

    Matched on the CALL, not on the token appearing somewhere: a leftover import
    or a name in a comment must not be able to satisfy one of these tests.
    """
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


@pytest.fixture(autouse=True)
def _clean_unlock_state():
    auth.reset_keychain_unlock()
    yield
    auth.reset_keychain_unlock()


# ---------------------------------------------------------------------------
# The init read cannot prompt - on ANY platform
# ---------------------------------------------------------------------------

def test_restore_reads_the_token_through_the_non_prompting_seam():
    """The guard against this fix landing on one platform only.

    ``restore_saved_session`` must go through ``keyring_get_without_prompting``.
    If it ever calls ``_safe_keyring_get`` for the token again, the read can
    prompt and the window can go dead - and because the darwin branch is the
    only one that suppresses UI, that regression would PASS on Windows and fail
    only on a Mac, which is precisely how this class of bug survives here.
    """
    calls = _calls(_fn("restore_saved_session"))
    assert "keyring_get_without_prompting" in calls
    assert "_safe_keyring_get" not in calls


def test_non_darwin_keeps_the_watchdogged_read_untouched(monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(auth, "_safe_keyring_get",
                        lambda s, u: seen.append((s, u)) or "win-token")
    monkeypatch.setattr(auth, "_set_keychain_ui_allowed",
                        lambda _a: pytest.fail("must not touch keychain UI off macOS"))

    assert auth.keyring_get_without_prompting("svc", "acct") == ("win-token", False)
    assert seen == [("svc", "acct")]


@pytest.mark.parametrize("status", ["-25293", "-25308"])
def test_a_status_meaning_would_prompt_is_reported_as_such(monkeypatch, status):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(auth, "_set_keychain_ui_allowed", lambda _a: True)
    monkeypatch.setattr(
        auth, "_run_keyring_op",
        lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError(f"Can't get password from keychain: ({status}, 'Unknown Error')")))

    assert auth.keyring_get_without_prompting("svc", "acct") == (None, True)


def test_a_missing_item_is_not_a_prompt(monkeypatch):
    """No saved token is an ordinary first run - prompting cannot help."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(auth, "_set_keychain_ui_allowed", lambda _a: True)
    monkeypatch.setattr(auth, "_run_keyring_op", lambda *a, **k: None)

    assert auth.keyring_get_without_prompting("svc", "acct") == (None, False)


def test_an_unrelated_backend_failure_is_not_a_prompt(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(auth, "_set_keychain_ui_allowed", lambda _a: True)
    monkeypatch.setattr(
        auth, "_run_keyring_op",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("backend exploded")))

    assert auth.keyring_get_without_prompting("svc", "acct") == (None, False)


def test_a_successful_suppressed_read_returns_the_token(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(auth, "_set_keychain_ui_allowed", lambda _a: True)
    monkeypatch.setattr(auth, "_run_keyring_op", lambda *a, **k: "tok")

    assert auth.keyring_get_without_prompting("svc", "acct") == ("tok", False)


def test_keychain_ui_is_restored_even_when_the_read_raises(monkeypatch):
    """Suppression is PROCESS-GLOBAL: leaving it off would silently break every
    later keychain call in the process, including the interactive unlock."""
    toggles: list[bool] = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(auth, "_set_keychain_ui_allowed",
                        lambda a: (toggles.append(a), True)[1])
    monkeypatch.setattr(
        auth, "_run_keyring_op",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    auth.keyring_get_without_prompting("svc", "acct")

    assert toggles and toggles[0] is False, "must suppress before reading"
    assert toggles[-1] is True, "must restore keychain UI afterwards"


def test_if_ui_cannot_be_suppressed_we_do_not_gamble_the_first_paint(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(auth, "_set_keychain_ui_allowed", lambda _a: False)
    monkeypatch.setattr(
        auth, "_run_keyring_op",
        lambda *a, **k: pytest.fail("must not read when UI cannot be suppressed"))

    assert auth.keyring_get_without_prompting("svc", "acct") == (None, True)


def test_a_probe_never_waits_on_an_unlock_already_in_flight(monkeypatch):
    """The unlock thread holds the UI lock for as long as the prompt is up.
    Waiting for it would reintroduce exactly the block being removed.

    Run on a THREAD with a join timeout, so a regression FAILS instead of
    hanging. That is not theoretical here: the first version called the probe
    directly, and the mutant that makes it take the lock blocking deadlocked
    against the lock this test holds - which hung the mutation pass long enough
    to be killed, and a killed pass leaves its mutant on disk.
    """
    monkeypatch.setattr(sys, "platform", "darwin")
    out: list = []
    auth._keychain_ui_lock.acquire()
    try:
        t = threading.Thread(
            target=lambda: out.append(auth.keyring_get_without_prompting("svc", "acct")),
            daemon=True)
        t.start()
        t.join(5)
        assert not t.is_alive(), "the probe blocked on the in-flight unlock"
        assert out == [(None, True)]
    finally:
        auth._keychain_ui_lock.release()


# ---------------------------------------------------------------------------
# Single-flight unlock
# ---------------------------------------------------------------------------

def test_begin_keychain_unlock_raises_exactly_one_prompt(monkeypatch):
    """A once-a-second poll must not be able to stack up prompts.

    Counts THREADS, not calls that got as far as the keychain. Counting the
    latter is not a test of single-flight at all: the workers serialise on the
    UI lock, so only one reaches the backend within any short window even when
    five were spawned - and the mutation pass proved it, by surviving the
    version of this test that counted reads. Five spawned workers means five
    prompts, one after another, which is the defect.
    """
    gate = threading.Event()

    class _FakeKeyring:
        @staticmethod
        def get_password(service, username):
            gate.wait(5)
            return "tok"

    monkeypatch.setitem(sys.modules, "keyring", _FakeKeyring)
    monkeypatch.setattr(auth, "_set_keychain_ui_allowed", lambda _a: True)

    before = {t for t in threading.enumerate() if t.name == "keychain-unlock"}
    for _ in range(5):
        auth.begin_keychain_unlock("svc", "acct")
    time.sleep(0.2)
    spawned = [t for t in threading.enumerate()
               if t.name == "keychain-unlock" and t not in before]
    assert len(spawned) == 1, (
        f"{len(spawned)} unlock threads spawned - each one raises its own "
        f"Keychain prompt, so the user would answer five in a row")
    gate.set()
    for _ in range(50):
        if auth.keychain_unlock_status() == "ok":
            break
        time.sleep(0.05)
    assert auth.keychain_unlock_status() == "ok"
    assert auth.unlocked_token() == "tok"
    assert auth.unlocked_token() == "tok", (
        "the token must survive a second read: the unlock state is process-global "
        "while keychain_unlock_pending is per SESSION, so a reload or a second "
        "window would otherwise get an empty token and a bare login page")


def test_a_denied_prompt_is_recorded_as_denied(monkeypatch):
    class _FakeKeyring:
        @staticmethod
        def get_password(service, username):
            raise RuntimeError("Can't get password from keychain: (-128, 'Keychain Denied')")

    monkeypatch.setitem(sys.modules, "keyring", _FakeKeyring)
    monkeypatch.setattr(auth, "_set_keychain_ui_allowed", lambda _a: True)

    auth.begin_keychain_unlock("svc", "acct")
    for _ in range(60):
        if auth.keychain_unlock_status() != "running":
            break
        time.sleep(0.05)
    assert auth.keychain_unlock_status() == "denied"


# ---------------------------------------------------------------------------
# Adoption
# ---------------------------------------------------------------------------

class _Session(dict):
    """Enough of st.session_state for the adoption pass."""


@pytest.fixture
def sess(monkeypatch):
    s = _Session()
    monkeypatch.setattr(auth.st, "session_state", s)
    return s


def test_adopt_does_nothing_when_no_unlock_is_pending(sess):
    assert auth.adopt_pending_keychain_unlock() is False


def test_adopt_waits_while_the_prompt_is_still_up(sess, monkeypatch):
    sess["keychain_unlock_pending"] = True
    monkeypatch.setattr(auth, "keychain_unlock_status", lambda: "running")

    assert auth.adopt_pending_keychain_unlock() is False
    assert sess["keychain_unlock_pending"] is True, "must keep waiting"


def test_adopt_signs_in_when_the_user_allows(sess, monkeypatch):
    sess["keychain_unlock_pending"] = True
    sess["api_url"] = "https://school.instructure.com"
    monkeypatch.setattr(auth, "keychain_unlock_status", lambda: "ok")
    monkeypatch.setattr(auth, "unlocked_token", lambda: "tok")

    class _CM:
        def __init__(self, key, url):
            pass

        def validate_token(self):
            return True, "Logged in as: Ada Lovelace"

    monkeypatch.setattr(auth, "CanvasManager", _CM)

    assert auth.adopt_pending_keychain_unlock() is True
    assert sess["is_authenticated"] is True
    assert sess["user_name"] == "Ada Lovelace"
    assert sess["keychain_unlock_pending"] is False


def test_adopt_records_a_denial_and_stops_waiting(sess, monkeypatch):
    sess["keychain_unlock_pending"] = True
    monkeypatch.setattr(auth, "keychain_unlock_status", lambda: "denied")

    assert auth.adopt_pending_keychain_unlock() is False
    assert sess["keychain_unlock_pending"] is False
    assert sess["keychain_unlock_failed"] == "denied"


def test_app_init_actually_calls_the_adoption_pass():
    """Nothing else turns a resolved unlock into a signed-in session.

    Matched on the CALL through the AST, not on the name appearing in app.py:
    deleting the call while leaving `from ui.auth import
    adopt_pending_keychain_unlock` above it keeps the token in the file and
    satisfies any substring test - and that mutant SURVIVED the first version of
    this suite, which checked ui/auth.py and never looked at the call site at
    all.
    """
    app_src = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(app_src)
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "adopt_pending_keychain_unlock" in called, \
        "app.py imports the adoption pass but never runs it"


def test_the_adoption_pass_runs_before_the_nav_is_written():
    """_write_nav_to_query_params stamps ?mode=auth when signed out, so adopting
    after it would leave the URL claiming the login page on the very run that
    signs the user in."""
    app_src = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    adopt = app_src.index("adopt_pending_keychain_unlock()")
    nav = app_src.index("_write_nav_to_query_params()\n")
    assert adopt < nav


def test_the_two_ways_a_saved_token_arrives_share_one_verdict():
    """A network blip must not mean one thing on the init path and another on
    the unlock path - so both go through _adopt_restored_token."""
    assert "_adopt_restored_token" in _calls(_fn("restore_saved_session"))
    assert "_adopt_restored_token" in _calls(_fn("adopt_pending_keychain_unlock"))


# ---------------------------------------------------------------------------
# The notice
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state", ["waiting", "checking", "denied", "error"])
def test_every_notice_state_emits_exactly_one_element(state):
    html = auth._kc_notice_html(state)
    assert html.startswith("<div class='kc-notice")
    assert html.count("<div class='kc-notice") == 1, (
        "the notice must be ONE element in every state - Streamlit reconciles by "
        "position and a changing child count shifts the login form below it")
    assert html.rstrip().endswith("</div>")


def test_the_waiting_copy_carries_the_one_measured_instruction():
    """MEASURED on macOS 26.6.1, twice over, and BOTH halves belong in the copy:
    plain 'Allow' leaves the item's ACL untouched so the prompt returns on EVERY
    launch, and it also puts up a SECOND dialog immediately (observed by the
    operator across three runs), while 'Always Allow' does neither. A rewrite
    that drops this costs the user a prompt every single time they open the app,
    and nothing else in the product would ever say so."""
    html = auth._kc_notice_html("waiting")
    assert "Always Allow" in html
    assert re.search(r"Plain\s*<i>Allow</i>", html), \
        "the copy must warn that plain Allow is not enough"
    assert "second dialog" in html, "plain Allow costs an extra dialog right now"
    assert "every time you open the app" in html, "...and one on every launch after"


def test_the_waiting_copy_reassures_before_it_instructs():
    """A student meeting a dialog that demands their Mac password needs to know
    we caused it, that nothing is lost, and that the password is not ours."""
    html = auth._kc_notice_html("waiting")
    assert "not been logged out" in html and "nothing is lost" in html.lower()
    assert "never to Canvas Downloader" in html
    assert "Deny" in html, "the way out must be stated, not implied"


def test_the_denied_copy_says_how_to_get_back(sess=None):
    html = auth._kc_notice_html("denied")
    assert "Always Allow" in html
    assert "quit Canvas Downloader" in html
    assert "nothing is lost" in html.lower() or "Nothing is lost" in html


def test_the_notice_is_silent_when_there_is_nothing_to_say(sess, monkeypatch):
    calls = []
    monkeypatch.setattr(auth.st, "container",
                        lambda **k: calls.append(k) or pytest.fail("rendered nothing-state"))
    auth.render_keychain_unlock_notice()
    assert calls == []


def test_the_poll_fragment_writes_nothing_to_the_event_container():
    """A fragment rerun REWINDS the event container's write index. An extra
    write there lands on a neighbouring stylesheet's host and strips a component
    of its CSS - so this fragment must never emit a style-only st.html or a
    toast."""
    body = _fn("_kc_unlock_poll")
    calls = _calls(body)
    assert "html" not in calls, "st.html inside the poll fragment clobbers a style host"
    assert "toast" not in calls, "st.toast inside the poll fragment clobbers a style host"


def test_the_prompt_is_raised_as_the_last_thing_the_login_page_does():
    """Position IS the fix: the script run ends immediately after, so the page
    paints before the system dialog can land on top of an empty window."""
    fn = _fn("render_login_page")
    last = fn.body[-1]
    assert isinstance(last, ast.If), "expected the guarded unlock start last"
    assert "begin_keychain_unlock" in _calls(last)
    # ...and nowhere earlier, or the prompt could beat the paint.
    earlier = ast.Module(body=fn.body[:-1], type_ignores=[])
    assert "begin_keychain_unlock" not in _calls(earlier)


def test_the_notice_renders_above_the_login_form():
    """It answers "why am I looking at a login screen at all", so it has to be
    read before the form, not after it."""
    src = AUTH_SRC.read_text(encoding="utf-8")
    notice = src.index("render_keychain_unlock_notice()\n\n            if _reauth_mode:")
    form = src.index('with st.form("auth_form"')
    assert notice < form


def test_markup_and_stylesheet_agree():
    """Every class the notice emits must have a rule, and the rules must live in
    the login page's UNCONDITIONAL stylesheet - a style block emitted only in the
    branch that renders the notice would shift every later style host by one."""
    src = AUTH_SRC.read_text(encoding="utf-8")
    used = set()
    for state in ("waiting", "checking", "denied", "error"):
        used |= set(re.findall(r"class='([a-z0-9 \-]+)'", auth._kc_notice_html(state)))
    classes = {c for group in used for c in group.split() if c.startswith("kc-")}
    assert classes, "expected kc- classes in the notice markup"
    for cls in classes:
        assert re.search(rf"\.{re.escape(cls)}\b[^;]*\{{", src), \
            f"class {cls} is emitted but has no CSS rule"


def test_the_slot_kills_its_own_gap():
    """A one-child keyed slot still pays Streamlit's ~1rem block gap unless it
    is zeroed - the same trap padded slots elsewhere in this codebase document."""
    src = AUTH_SRC.read_text(encoding="utf-8")
    assert re.search(r'st-key-kc_unlock_slot"\]\s*\{\s*gap:\s*0', src)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_every_path_that_drops_the_credential_resets_the_unlock():
    """A cached 'denied' outlives the credential it was about: left standing it
    makes begin_keychain_unlock a no-op for the rest of the process, so the
    notice would advertise a prompt that never appears."""
    src = AUTH_SRC.read_text(encoding="utf-8")
    deletes = len(re.findall(r"_safe_keyring_delete\(KEYRING_SERVICE", src))
    resets = len(re.findall(r"reset_keychain_unlock\(\)", src))
    assert deletes >= 2, "expected the logout and force_reauth delete sites"
    # one definition + one call per delete site
    assert resets >= deletes + 1, (
        f"{deletes} credential-clearing sites but only {resets - 1} unlock resets")
