"""The development host and the handoff checker.

Two commands exist because the ordinary dev loop cannot reach two of the three
sign-in routes:

* ``python dev.py`` - the app in a browser WITH a working sign-in window.
  ``streamlit run app.py`` cannot open that window and never could: pywebview
  only builds one once ``webview.start()`` has run on the main thread, and under
  ``streamlit run`` Streamlit owns that thread.
* ``python scripts/check_handoff.py`` - the browser-extension transport,
  without Chrome, so "the extension does not work" can be narrowed to the one
  place it might actually be.

What this file guards is the part that ROTS: a harness whose value rests on
being the real app quietly stops being that. So the assertions here are about
provenance rather than behaviour - dev.py must launch the real app through
production's own launcher, must not reimplement any screen, and must not
silently differ from production on the settings that decide what a sign-in
test means.

The product owner asked directly on 2026-09-12 whether the dev host mimics the
auth screen. It does not, and these tests are what keeps that answer true.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_DEV = _ROOT / 'dev.py'
_CHECK = _ROOT / 'scripts' / 'check_handoff.py'


def _src(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def _tree(path: Path) -> ast.Module:
    return ast.parse(_src(path))


# ---------------------------------------------------------------------------
# 1. Both commands exist and are callable in-process
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [_DEV, _CHECK], ids=['dev.py', 'check_handoff.py'])
def test_the_command_exists_and_parses(path):
    assert path.is_file(), f"{path.name} is documented and absent"
    _tree(path)


@pytest.mark.parametrize("path", [_DEV, _CHECK], ids=['dev.py', 'check_handoff.py'])
def test_main_TAKES_argv(path):
    """A CLI entry point that reads `sys.argv` implicitly cannot be called by
    anything in-process, and the first caller is always a test - under pytest
    `sys.argv` is the RUNNER's arguments, so `parse_args()` dies on `-q` with
    `SystemExit(2)`. This repo already paid for that once
    (`test_longpath_gate_check.py`, 2026-08-22) and it is a rule now."""
    fns = {n.name: n for n in ast.walk(_tree(path))
           if isinstance(n, ast.FunctionDef)}
    assert 'main' in fns, f"{path.name} has no main()"
    args = fns['main'].args
    names = [a.arg for a in args.args] + [a.arg for a in args.kwonlyargs]
    assert 'argv' in names, (
        f"{path.name}:main() takes no argv, so it can only be driven through "
        f"the shell")


def test_the_help_text_works_without_importing_the_app(tmp_path):
    """`--help` must answer before anything heavy happens. It is the first
    thing anyone types and the cheapest possible smoke test of the file."""
    out = subprocess.run([sys.executable, str(_DEV), '--help'],
                         cwd=str(_ROOT), capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    for flag in ('--isolated', '--debug', '--window', '--port', '--no-browser'):
        assert flag in out.stdout, f"{flag} is not in the help output"


# ---------------------------------------------------------------------------
# 2. The dev host runs the REAL app - the whole point of it
# ---------------------------------------------------------------------------

def test_the_dev_host_starts_the_app_through_PRODUCTIONS_OWN_LAUNCHER():
    """Not a copy of the argv, not a second `stcli.main()` call.

    `start._start_streamlit_server` carries the theme flags, the headless
    setting, the signal monkeypatch that a non-main thread needs, and the
    frozen-only file-watcher opt-out. A dev host with its own version of that
    list is a dev host that can disagree with production about how the app is
    configured, which is the class of difference nobody notices until a test
    result is wrong.
    """
    src = _src(_DEV)
    assert 'import start as launcher' in src
    assert 'launcher._launch_streamlit(' in src, (
        "the dev host does not go through start.py's own launcher")

    # Through the AST, not a text search. The first version of this grepped for
    # `stcli` and matched the word inside this file's OWN docstring, where it
    # explains that Streamlit's logging setup runs there - the same
    # comment-matching trap this repo records for
    # `test_every_source_deleting_converter_verifies_content...` and the
    # bundle-bytecode pass. A comment explaining a rule must never be able to
    # violate it.
    imported = set()
    for node in ast.walk(_tree(_DEV)):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or '')
            imported.update(f"{node.module}.{a.name}" for a in node.names)
    offenders = {m for m in imported
                 if m.startswith('streamlit') or m.endswith('.cli')}
    assert not offenders, (
        f"the dev host imports {sorted(offenders)}, so it builds its own "
        f"Streamlit invocation instead of reusing production's")


def test_the_dev_host_REIMPLEMENTS_NO_APP_SCREEN():
    """The one thing that would make every test run against this worthless.

    Asked by the product owner in as many words. The dev host is allowed
    exactly one page of its own - the status panel in `_control_html` - and it
    is asserted to be a status panel: no Canvas wording, no auth wording, no
    form controls. Everything a developer looks at otherwise is served by the
    real `app.py`.
    """
    tree = _tree(_DEV)
    html_fns = [n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and 'html' in n.name.lower()]
    assert [n.name for n in html_fns] == ['_control_html'], (
        f"the dev host has more than one page of its own: "
        f"{[n.name for n in html_fns]}")

    panel = ast.get_source_segment(_src(_DEV), html_fns[0]) or ''
    low = panel.lower()
    # A control panel names the host and the ports. An AUTH SCREEN names
    # Canvas, a token, a URL field or a sign-in button - and if any of that
    # ever appears here, somebody has started rebuilding the login page.
    for banned in ('access token', 'sign in', 'log in', 'canvas url',
                   '<input', '<form', '<button'):
        assert banned not in low, (
            f"`_control_html` contains {banned!r}, so the dev host has begun "
            f"imitating a real screen rather than launching it")


def test_the_dev_host_uses_the_SAME_web_view_profile_settings_as_production():
    """`private_mode=False` + an explicit `storage_path` are what make the web
    view remember a sign-in. A dev host running the pywebview DEFAULT
    (`private_mode=True`, a temp folder discarded on exit) would report that
    "stay signed in" does not work, on an app where it does - the most
    expensive possible false negative for this feature."""
    src = _src(_DEV)
    assert 'private_mode=False' in src, (
        "the dev host would run the web view InPrivate, so no sign-in could "
        "ever be remembered and the retention test would always fail")
    assert 'storage_path=profile' in src
    assert 'webview_profile_dir' in src, (
        "the dev host does not resolve the profile through the app's own "
        "helper, so it can point somewhere production never uses")


def test_debug_is_OFF_by_default_because_it_changes_what_a_test_MEANS():
    """pywebview sets `AreDefaultContextMenusEnabled` from its own debug flag,
    and right-click paste in the sign-in window depends on that setting. A dev
    host defaulting to debug would show pasting working whether or not the
    app's code enables it, which is a harness that cannot reproduce the
    production failure."""
    tree = _tree(_DEV)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'add_argument'):
            continue
        if not (node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == '--debug'):
            continue
        action = next((kw.value.value for kw in node.keywords
                       if kw.arg == 'action'), None)
        assert action == 'store_true', (
            "--debug is not an opt-in flag, so debug may be on by default")
        return
    pytest.fail("dev.py has no --debug flag, so debug cannot be opted into "
                "and may be unconditional")


def test_the_signin_line_is_MEASURED_and_not_asserted():
    """The banner's whole job is to say whether a sign-in window can be opened.
    A hard-coded "available" would make the one line a developer relies on a
    claim rather than a reading - and a False there means the GUI loop did not
    come up, so every sign-in test after it is void."""
    src = _src(_DEV)
    assert 'is_available' in src, (
        "the dev host never asks whether the sign-in window is available")
    assert "'Sign-in window   available'" not in src
    assert 'Sign-in window   {signin}' in src, (
        "the banner does not interpolate the measured value")


# ---------------------------------------------------------------------------
# 3. The checker cannot drift from the app it checks
# ---------------------------------------------------------------------------

def test_the_checker_reads_the_APPS_OWN_constants():
    """A checker with its own copy of the port list probes somewhere the app is
    not listening and reports a green that means nothing. Same rule, same
    reason, as `make_long_path`'s duplicate in `core/sync_manager.py`."""
    src = _src(_CHECK)
    assert 'from core.handoff import' in src
    assert 'PORTS' in src and 'ACCEPTED_COOKIES' in src
    # And no literal port numbers of its own.
    from core.handoff import PORTS
    for port in PORTS:
        assert src.count(str(port)) == 0, (
            f"the checker hard-codes port {port} instead of reading "
            f"core.handoff.PORTS")


def test_the_checker_is_NON_DESTRUCTIVE_unless_told_otherwise():
    """It is run while the app is waiting for a real extension click, so it
    must leave the arming intact - otherwise using it costs you the thing you
    were about to test. Only `--accept` consumes, and it says so."""
    tree = _tree(_CHECK)
    accept = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr == 'add_argument'
              and n.args and isinstance(n.args[0], ast.Constant)
              and n.args[0].value == '--accept']
    assert accept, "the checker has no --accept flag, so it may always consume"
    helptext = next((kw.value.value for kw in accept[0].keywords
                     if kw.arg == 'help'), '')
    assert 'consume' in helptext.lower(), (
        "--accept does not warn that it consumes the arming")


def test_the_checker_FAILS_when_nothing_is_listening():
    """The control. A checker that cannot say no is not a checker - and this
    one's whole purpose is to distinguish "the app is not running" from "the
    extension is broken", so the negative answer is half its value.

    Driven for real: no listener is started, so discovery must fail and the
    exit code must be non-zero.

    SKIPS when the developer has the app open, which is the normal case while
    working on this feature and is exactly when it first fired: `python dev.py`
    was running, the listener was armed, and the checker correctly found it -
    so this test reported a failure that was a fact about the machine rather
    than about the code. A test that cannot run has to say so; one that fails
    instead teaches people to ignore it.
    """
    import socket as _socket
    from core.handoff import PORTS as _PORTS
    for _port in _PORTS:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            if probe.connect_ex(('127.0.0.1', _port)) == 0:
                pytest.skip(
                    f"something is already listening on 127.0.0.1:{_port} "
                    f"(the app, or another test run). The no-listener control "
                    f"cannot be measured while it is.")

    out = subprocess.run([sys.executable, str(_CHECK)],
                         cwd=str(_ROOT), capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 1, (
        f"the checker passed with nothing listening:\n{out.stdout[-800:]}")
    assert 'FAIL' in out.stdout
    assert 'python dev.py' in out.stdout, (
        "the failure does not say how to start the app")


def test_the_checker_asserts_the_SECURITY_property_not_just_the_happy_path():
    """The listener's entire licence to exist is that a web page cannot talk to
    it. A checker that only proved the extension path works would pass on a
    build that had opened the port to every tab."""
    src = _src(_CHECK)
    assert 'PAGE_ORIGIN' in src
    assert 'a web page origin is refused' in src
    assert 'status == 403' in src


# ---------------------------------------------------------------------------
# 4. The documentation and the commands agree
# ---------------------------------------------------------------------------

def test_CLAUDE_md_documents_both_commands():
    """A command nobody can find is a command nobody runs. This is also the
    guard against the opposite decay - a documented command that no longer
    exists, which this repo has recorded twice."""
    doc = (_ROOT / 'CLAUDE.md').read_text(encoding='utf-8')
    assert 'python dev.py' in doc, (
        "CLAUDE.md does not mention `python dev.py`, so the next session will "
        "hit the same `streamlit run app.py` dead end")
    assert 'check_handoff' in doc


def test_dev_py_is_NOT_bundled_into_a_release():
    """It imports `start` and reaches into its privates; it is a dev tool and
    has no business in a shipped build. Both specs name their data files
    explicitly, so this is a guard on that staying true."""
    for spec in ('Canvas_Downloader.spec', 'Canvas_Downloader_macOS.spec'):
        text = (_ROOT / spec).read_text(encoding='utf-8')
        assert "'dev.py'" not in text and '"dev.py"' not in text, (
            f"{spec} bundles dev.py into the release")



# ---------------------------------------------------------------------------
# The checker must not pass against an ORPHANED listener
#
# On 2026-09-13 `check_handoff.py` reported all ten checks green while the app
# could not sign in at all. A module re-import had left a previous
# incarnation's socket listening, and both the checker and the extension take
# the FIRST port that answers - so both were talking to the orphan. It answered
# /ping, called itself armed and accepted a handoff, into state the live app
# cannot read. A checker that stops at the first answer cannot tell that apart
# from a healthy app, which makes it worse than no checker.
# ---------------------------------------------------------------------------

def _import_checker():
    import importlib
    import sys as _sys
    scripts = str(_ROOT / 'scripts')
    if scripts not in _sys.path:
        _sys.path.insert(0, scripts)
    return importlib.import_module('check_handoff')


def _run_checker():
    import io
    from contextlib import redirect_stdout
    checker = _import_checker()
    checker._results.clear()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = checker.main([])
    return rc, buf.getvalue()


def _require_sole_ownership():
    """Refuse to run unless NOTHING else on this machine is listening.

    Both tests below count listeners, so any `python dev.py` or installed app
    that happens to be running is a second one and makes the count wrong. They
    were written without this and failed the moment the product owner restarted
    his dev host - which is precisely the environment-dependence this repo's
    standing rules now warn about, arriving in the tests written to record it.
    """
    import socket
    from core import handoff
    for p in handoff.PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            if probe.connect_ex(('127.0.0.1', p)) == 0:
                pytest.skip(
                    f"127.0.0.1:{p} is already listening (a running "
                    f"`python dev.py` or Canvas Downloader). These tests COUNT "
                    f"listeners, so they need to own the ports.")


def test_the_checker_REFUSES_when_more_than_one_listener_answers():
    """Build the exact state the product owner was in, and require a FAIL."""
    from core import handoff
    _require_sole_ownership()
    handoff.stop()
    live = handoff.start()
    if not live:
        pytest.skip("the handoff ports are in use by another process")

    rt = sys.modules['canvas_downloader._handoff_runtime']
    orphan = rt.server
    second = 0
    try:
        # Exactly what a re-import used to do: lose the reference, keep the
        # socket. The listener stays up and nothing can stop it.
        rt.server = None
        second = handoff.start()
        if not second or second == live:
            pytest.skip("could not open a second handoff port to test with")

        rc, out = _run_checker()
        assert rc != 0, (
            "the checker passed while TWO listeners were running, so it "
            "cannot tell a healthy app from an orphan the extension will "
            "reach first")
        assert 'exactly one listener' in out, (
            "the checker says nothing about there being more than one "
            "listener, so whoever runs it has no way to know")
        assert 'FAIL' in out
    finally:
        try:
            handoff.stop()                    # closes whichever rt holds
        except Exception:                                  # noqa: BLE001
            pass
        rt.server = orphan
        try:
            handoff.stop()
        except Exception:                                  # noqa: BLE001
            pass


def test_the_checker_still_PASSES_that_check_with_one_listener():
    """The positive control. A check that can only say no is not a check."""
    from core import handoff
    _require_sole_ownership()
    handoff.stop()
    port = handoff.start()
    if not port:
        pytest.skip("the handoff ports are in use by another process")
    try:
        rc, out = _run_checker()
        assert 'exactly one listener is running' in out
        assert 'FAIL  exactly one listener' not in out, (
            "the orphan check fires on a perfectly healthy single listener")
    finally:
        handoff.stop()

# ---------------------------------------------------------------------------
# The session RECORD, which dev.py was not keeping
#
# Found 2026-09-13 by reading the logs of a real run rather than the code:
# `diagnostics/health.log` was ZERO BYTES after a full download, because
# `start.py` calls `session_start()` / `session_end()` and this file called
# neither. So phase recording, the failure tally, the clean-exit signal and the
# recorded children the next launch reaps were all unexercised in the tool
# built to exercise production faithfully - and anything verified about them
# under `dev.py` was verified against nothing.
#
# It was never a decision: the orphan reap beside it already says "same as
# start.py".
# ---------------------------------------------------------------------------

def _dev_calls() -> dict:
    """Every call in dev.py, by name, with the line it is on.

    **By AST, because a COMMENT satisfied the old substring test.** dev.py
    explains itself directly above the calls - *"`start.py` calls
    `session_start()` / `session_end()`; this file called neither"* - so
    `'session_start()' in src` was true with the call deleted, and the mutant
    that deletes it SURVIVED the 2026-09-14 pass. The prose that describes a
    guard kept the guard green: the same trap this repo has now hit five times.
    """
    import ast
    tree = ast.parse((_ROOT / 'dev.py').read_text(encoding='utf-8'))
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            if name:
                found.setdefault(name, []).append(node.lineno)
    return found


def test_dev_keeps_the_SAME_session_record_as_production():
    calls = _dev_calls()
    for call in ('session_start', 'session_end'):
        assert call in calls, (
            f"dev.py never calls {call}(), so `diagnostics/health.log` is not "
            f"written under `python dev.py` at all and the whole session "
            f"lifecycle goes untested in the tool built to test production")


def test_dev_CLOSES_the_record_before_killing_the_children():
    """The record is what the NEXT launch reads to decide whether this session
    died. Written after the children are gone it describes a session that has
    already been taken apart - and `start.py` orders it the same way."""
    calls = _dev_calls()
    assert 'session_end' in calls and '_terminate_child_processes' in calls, (
        f"one of the two calls is gone entirely: {sorted(calls)[:0] or ''}"
        f"session_end={calls.get('session_end')}, "
        f"_terminate_child_processes={calls.get('_terminate_child_processes')}")
    assert min(calls['session_end']) < min(calls['_terminate_child_processes']), (
        "dev.py kills its children before closing the session record")


def test_the_sampler_takes_a_reading_BEFORE_it_waits():
    """Otherwise every state written in the first interval reports zeros.

    Measured on a real run: `session_state.json` carried `peak_self_mb: 0.0`,
    `peak_tree_mb: 0.0`, `uptime_s: 0` - which read as MEASUREMENTS and were
    the sampler's untouched defaults, because `_sampler_loop` waited five
    seconds before its first reading while `note_phase` persists on every
    phase change. Same class as this repo's "a sentinel is not a measurement".
    """
    import inspect
    from core import health_log
    src = inspect.getsource(health_log._sampler_loop)
    body = src.split(':', 1)[1]
    first_sample = body.index('_sample_once()')
    first_wait = body.index('stop.wait(')
    assert first_sample < first_wait, (
        "the sampler waits before its first reading, so a state file written "
        "in that window reports zeros it never measured")
