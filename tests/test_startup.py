"""Guards the cold-start path: what the window shows, and how long for.

Measured in the real app on 2026-07-27 (warm dev machine, source build, fast
network), from the moment ``start.py`` calls ``load_url()``:

    +0.0s  splash torn down, blank document        <- black screen starts
    +2.9s  7 MB JS bundle parsed, React mounts     <- still blank
    +4.0s  script run #1: keyring + two Canvas round-trips, renders NOTHING,
           ends in st.rerun()                      <- still blank
    +6.9s  script run #2 paints                    <- black screen ends

A cold first launch (Microsoft Store) pays uncached reads of the whole install
directory plus a first-run virus scan on every DLL, which is the reported
10-20s. Three separate defects, one file:

1. The window navigated away from the splash on ``/_stcore/health``, which is
   true as soon as tornado BINDS - nothing is on screen for seconds afterwards.
   Fixed by making Streamlit's own page paint the same splash from its first
   byte (scripts/patch_streamlit_boot.py).
2. The saved login was restored from inside ``render_login_page`` and finished
   with ``st.rerun()``, so a whole script run was spent on I/O behind an empty
   window and then discarded. Fixed by ``ui.auth.restore_saved_session`` running
   during session init.
3. ``_find_free_port`` set SO_REUSEADDR, which on Windows means "bind even if
   another process is LISTENING here" - so it handed out occupied ports.
"""

import importlib.util
import os
import socket

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


boot_patch = _load("patch_streamlit_boot", os.path.join("scripts", "patch_streamlit_boot.py"))
start = _load("cd_start", "start.py")


# A faithful copy of Streamlit 1.51's index.html shape - an empty #root and no
# background colour, which is exactly why the window goes dark.
_INDEX = (
    '<!DOCTYPE html>\n<html lang="en">\n  <head>\n    <meta charset="UTF-8" />\n'
    '    <title>Streamlit</title>\n    <script>window.prerenderReady = false</script>\n'
    '    <script type="module" crossorigin src="./static/js/index.abc.js"></script>\n'
    '  </head>\n  <body>\n    <noscript>You need to enable JavaScript to run this app.'
    '</noscript>\n    <div id="root"></div>\n  </body>\n</html>\n'
)


# ── The boot overlay ────────────────────────────────────────────────────────

def test_overlay_is_injected_and_paints_before_the_app():
    out = boot_patch.inject(_INDEX, _ROOT)
    assert 'id="cd-boot"' in out
    # It has to be the document's first paint, so it must come BEFORE #root -
    # injected after it, the browser paints an empty page first.
    assert out.index('id="cd-boot"') < out.index('id="root"')
    # ...and outside #root, which React owns and would wipe on mount.
    assert out.index('id="cd-boot"') < out.index('<div id="root">')


def test_injection_is_idempotent():
    once = boot_patch.inject(_INDEX, _ROOT)
    twice = boot_patch.inject(once, _ROOT)
    assert once == twice
    assert twice.count(boot_patch.BEGIN) == 1
    assert twice.count('id="cd-boot"') == 1


def test_strip_restores_the_original():
    assert boot_patch.strip(boot_patch.inject(_INDEX, _ROOT)) == _INDEX


def test_payload_has_no_tornado_template_openers():
    """index.html is rendered through tornado's TEMPLATE engine on the 404 path
    (routes.py write_error), where '{{' opens an expression. A stray one would
    take the whole page down on any unknown URL."""
    out = boot_patch.inject(_INDEX, _ROOT)
    for opener in ("{{", "{%", "{#"):
        assert opener not in out


def test_overlay_removes_itself_and_can_never_trap_the_user():
    out = boot_patch.inject(_INDEX, _ROOT)
    # Both escape hatches must be present: the absolute cap, and the
    # content-is-up fallback for a launch that goes straight into a long
    # operation (the daily auto-sync keeps the script RUNNING for minutes, so
    # prerenderReady never arrives).
    assert "30000" in out          # absolute cap
    assert "5000" in out           # content-up fallback
    assert "prerenderReady" in out
    assert "removeChild" in out    # taken out of the DOM, not just hidden
    # ...and a guarantee that survives the script not running AT ALL (a parse
    # error on an old WebKit engine would otherwise leave the app covered
    # forever). Pure CSS, so it cannot be defeated by broken JS.
    assert "cd-boot-failsafe" in out
    assert "visibility:hidden" in out


def test_overlay_script_is_es5_only():
    """It runs in WKWebView on macOS, whose JS engine tracks the installed
    Safari - the same constraint that forces patch_streamlit_webkit.py to exist.
    A syntax error here does not degrade, it covers the whole app."""
    out = boot_patch.inject(_INDEX, _ROOT)
    script = out.split("<script>")[1].split("</script>")[0]
    for modern in ("=>", "const ", "let ", "`", "?.", "??", "class "):
        assert modern not in script, f"non-ES5 syntax in the boot script: {modern!r}"


def test_overlay_matches_the_launcher_splash():
    """The two documents hand over to each other; any difference in the shared
    splash is a visible flicker at the swap."""
    launcher = open(os.path.join(_ROOT, "start.py"), encoding="utf-8").read()
    out = boot_patch.inject(_INDEX, _ROOT)
    for token in ("#0d1117", "#0072CE", "rgba(0,114,206,0.18)",
                  "rgba(255,255,255,0.55)", "rgba(255,255,255,0.08)",
                  "16.8px", "Starting Canvas Downloader"):
        assert token in launcher, f"{token} missing from the launcher splash"
        assert token in out, f"{token} missing from the boot overlay"


def test_missing_body_tag_is_refused_not_corrupted():
    with pytest.raises(ValueError):
        boot_patch.inject("<html><head></head></html>", _ROOT)


# ── Port probing ────────────────────────────────────────────────────────────

def test_find_free_port_skips_a_port_that_is_in_use():
    """SO_REUSEADDR on Windows means 'bind even if someone is LISTENING', so the
    probe used to report an occupied port as free. Measured 2026-07-27: with a
    server already on 8501 the launcher picked 8501, Streamlit bound it a second
    time, and the health check was answered by the OTHER process."""
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        busy = held.getsockname()[1]
        assert start._find_free_port(preferred=busy) != busy
    finally:
        held.close()


def test_find_free_port_returns_the_preferred_port_when_it_is_free():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    free = probe.getsockname()[1]
    probe.close()
    assert start._find_free_port(preferred=free) == free


# ── Shutdown: the process tree goes with us ─────────────────────────────────
#
# A Store user's 2026-07-15 hang (WER MoAppHangXProc against
# BrkBuilds.CanvasDownloader_2.0.0.0_x64) was msedgewebview2.exe wedged FOREVER
# in its own shutdown - Windows.Media.dll releasing a brokered WinRT activation
# factory from DLL_PROCESS_DETACH, i.e. a cross-process COM call to the
# package's RuntimeBroker made under the loader lock with one thread left.
# os._exit then orphaned it. A TERMINATED process never runs DLL_PROCESS_DETACH,
# so reaping the tree is what makes the hang unreachable.

def test_shutdown_reaps_a_child_that_will_not_exit():
    """The hung msedgewebview2.exe stand-in: a child that is never going to
    leave on its own. Before the fix os._exit orphaned it permanently (~75 MB
    stranded until reboot, plus a failure report filed against the package)."""
    import subprocess
    import sys as _sys
    import psutil

    kid = subprocess.Popen([_sys.executable, "-c", "import time; time.sleep(300)"])
    try:
        proc = psutil.Process(kid.pid)
        assert proc.is_running()
        start._terminate_child_processes(grace=0.2, kill_wait=2.0)
        assert not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE
    finally:
        if kid.poll() is None:
            kid.kill()
        kid.wait(timeout=5)


def test_shutdown_costs_nothing_when_the_tree_is_already_clean():
    """A healthy close has already torn every WebView2 process down by the time
    webview.start() returns (measured 2026-07-27: 6 processes / 465 MB, gone in
    2.36s), so this must not add a grace period to the common path."""
    import time as _time
    t0 = _time.perf_counter()
    start._terminate_child_processes(grace=5.0, kill_wait=5.0)
    assert _time.perf_counter() - t0 < 1.0


def test_shutdown_never_raises_when_psutil_is_unavailable():
    """Reaping is best-effort - it must never be able to stop the app exiting."""
    import builtins
    real_import = builtins.__import__

    def _no_psutil(name, *a, **k):
        if name == "psutil":
            raise ImportError("blocked")
        return real_import(name, *a, **k)

    builtins.__import__ = _no_psutil
    try:
        start._terminate_child_processes()      # must simply return
    finally:
        builtins.__import__ = real_import


def test_reap_runs_before_the_hard_exit_and_survives_a_crash():
    """Order matters: os._exit skips every teardown hook, so the reap has to
    happen first - and from a `finally`, or a crash inside webview.start()
    strands the same children by a different route."""
    src = open(os.path.join(_ROOT, "start.py"), encoding="utf-8").read()
    i_start = src.index("webview.start(_boot)")
    i_finally = src.index("finally:", i_start)
    i_reap = src.index("_terminate_child_processes()", i_finally)
    i_exit = src.index("os._exit(0)", i_reap)
    assert i_start < i_finally < i_reap < i_exit


# ── Prewarm ─────────────────────────────────────────────────────────────────

def test_prewarm_never_imports_app_itself():
    """app.py calls st.set_page_config at module level and belongs to the
    ScriptRunner; importing it from a background thread would run Streamlit
    commands with no script context."""
    names = set(start._PREWARM_CRITICAL) | set(start._PREWARM_SECONDARY)
    assert "app" not in names


def test_prewarm_names_are_real_modules():
    """A typo here fails silently (every import is wrapped) and costs the whole
    benefit without any signal."""
    missing = [n for n in start._PREWARM_CRITICAL + start._PREWARM_SECONDARY
               if importlib.util.find_spec(n) is None]
    assert missing == []


def _fresh_session():
    import streamlit as st
    st.session_state.clear()
    return st.session_state


@pytest.fixture
def auth(monkeypatch, tmp_path):
    import ui.auth as auth_mod
    _fresh_session()
    monkeypatch.setattr(auth_mod, 'CONFIG_FILE', str(tmp_path / 'settings.json'))
    monkeypatch.setattr(auth_mod.st, 'rerun',
                        lambda *a, **k: pytest.fail(
                            'restore_saved_session must not rerun: it runs during '
                            'session init, so the SAME run renders the signed-in page'))
    yield auth_mod
    _fresh_session()


def _write_config(auth_mod, **kw):
    import json
    cfg = {'api_url': 'https://school.instructure.com'}
    cfg.update(kw)
    with open(auth_mod.CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f)


class _FakeManager:
    def __init__(self, key, url):
        self.api_key, self.api_url = key, url

    def validate_token(self):
        return True, 'Connected as: Ada Lovelace'


def test_restore_signs_in_without_a_rerun(auth, monkeypatch):
    """The whole point of the move: no second script run. The rerun is trapped
    by the fixture, so this fails loudly if it ever comes back."""
    _write_config(auth)
    monkeypatch.setattr(auth, 'keyring_get_without_prompting', lambda *a: ('tok', False))
    monkeypatch.setattr(auth, 'CanvasManager', _FakeManager)

    auth.restore_saved_session()

    assert auth.st.session_state['is_authenticated'] is True
    assert auth.st.session_state['user_name'] == 'Ada Lovelace'


def test_restore_applies_saved_settings_before_anything_renders(auth, monkeypatch):
    """These used to be adopted from inside render_login_page - i.e. after the
    sidebar had already rendered on the run that read them."""
    _write_config(auth, concurrent_downloads=9, show_help_text=False, debug_mode=True)
    monkeypatch.setattr(auth, 'keyring_get_without_prompting', lambda *a: ('', False))

    auth.restore_saved_session()

    assert auth.st.session_state['concurrent_downloads'] == 9
    assert auth.st.session_state['show_help_text'] is False
    assert auth.st.session_state['debug_mode'] is True


def test_restore_is_a_noop_without_a_config(auth):
    """A genuinely fresh install: no file, no crash, and the login page shows."""
    auth.restore_saved_session()
    assert auth.st.session_state['token_loaded'] is True
    assert not auth.st.session_state.get('is_authenticated')


def test_restore_runs_once_per_session(auth, monkeypatch):
    _write_config(auth)
    reads = []
    monkeypatch.setattr(auth, 'keyring_get_without_prompting',
                        lambda *a: (reads.append(1), ('', False))[1])

    auth.restore_saved_session()
    auth.restore_saved_session()
    auth.restore_saved_session()

    assert len(reads) == 1


def test_restore_survives_a_corrupt_config(auth, monkeypatch):
    """A half-written settings file must not take the whole launch down."""
    with open(auth.CONFIG_FILE, 'w', encoding='utf-8') as f:
        f.write('{"api_url": "https://school.inst')

    auth.restore_saved_session()          # must not raise
    assert not auth.st.session_state.get('is_authenticated')


def test_app_restores_the_session_during_init():
    """Order matters: after ensure_download_state (whose defaults it overrides)
    and before _write_nav_to_query_params (which writes ?mode=auth when signed
    out) - and before the sidebar and page body."""
    src = open(os.path.join(_ROOT, 'app.py'), encoding='utf-8').read()
    i_ensure = src.index('ensure_download_state()')
    i_restore = src.index('restore_saved_session()')
    i_nav = src.index('_write_nav_to_query_params()\n')
    i_sidebar = src.index('render_sidebar(fetch_courses)')
    assert i_ensure < i_restore < i_nav < i_sidebar


def test_prewarm_covers_what_the_first_script_run_imports():
    """The point of the prewarm is that script run #1 finds its imports already
    in sys.modules. If app.py grows a new top-level local import, it belongs
    here too."""
    import ast
    tree = ast.parse(open(os.path.join(_ROOT, "app.py"), encoding="utf-8").read())
    local_roots = {"core", "ui", "engine", "shared", "sync", "styles", "converters",
                   "panopto", "sync_ui"}
    needed = set()
    for node in tree.body:                      # top-level imports only
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in local_roots:
                needed.add(node.module)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in local_roots:
                    needed.add(a.name)
    prewarmed = set(start._PREWARM_CRITICAL) | set(start._PREWARM_SECONDARY)
    # A module is covered if it is prewarmed directly or is a parent package of
    # something prewarmed (importing the child imports the parent).
    uncovered = {n for n in needed
                 if n not in prewarmed and not any(p.startswith(n + ".") for p in prewarmed)}
    assert uncovered == set(), f"top-level imports of app.py not prewarmed: {uncovered}"
