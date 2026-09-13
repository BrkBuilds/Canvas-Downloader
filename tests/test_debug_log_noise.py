"""The debug log must stay READABLE, because it is the artifact users send.

MEASURED on the product owner's own download log, 2026-09-13:

    total lines                      49,250
    framework tracebacks             37,360   (76%)
    his app's own content            62 INFO + 2 locked-file errors + 1 warning

3,736 copies of one thing: `asyncio` logging "Task exception was never
retrieved" with a chained `StreamClosedError` -> `WebSocketClosedError`, once
for every repaint Streamlit failed to push to a socket the browser had already
closed. A long download with a backgrounded tab produces thousands, and an
earlier log the same week was 4.7 MB with the app's own lines at 0.4%.

The mechanism is that `_DebugFileBridge` is installed on the ROOT logger and
admits any non-app logger at WARNING and above, which an ERROR record satisfies.

This is not tidiness. That file is what a user attaches when something has gone
wrong, so drowning it is the diagnostic being destroyed by the framework's own
bookkeeping - and this session lost real time to it twice.

Everything here drives the REAL bridge with the REAL exception shape.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import canvas_debug as cd                             # noqa: E402

try:                                       # the real ones when tornado is here
    from tornado.iostream import StreamClosedError
    from tornado.websocket import WebSocketClosedError
except Exception:                                              # noqa: BLE001
    WebSocketClosedError = StreamClosedError = None


def _closed_socket_exc_info():
    """The chain tornado actually raises: Stream raised while handling Socket.

    Which of the two ends up outermost is tornado's business, so the guard has
    to walk the chain rather than look at the top exception.
    """
    try:
        try:
            raise WebSocketClosedError()
        except WebSocketClosedError:
            raise StreamClosedError()
    except StreamClosedError:
        return sys.exc_info()


@pytest.fixture
def debug_log(tmp_path, monkeypatch):
    """A real debug file with the real bridge installed on the root logger.

    EVERY GLOBAL IT TOUCHES IS PUT BACK, and the level restore is the one that
    matters. `set_active_debug_file` raises each app logger to INFO and never
    lowers it again - correct in the app, where it is one-way and per run, and
    a trap in a test, because a logger left at INFO drops the `logger.debug`
    calls a LATER test file is asserting on.

    Measured: without this,
    `test_office_automation_lock_coverage.py::test_the_boring_cases_stay_at_debug`
    failed with an empty capture while passing in isolation - a failure that
    reads as an Office regression and is this file leaking.
    """
    if WebSocketClosedError is None:
        pytest.skip("tornado is not importable in this environment")
    path = tmp_path / "debug_log.txt"
    monkeypatch.setattr(cd, '_disconnect_noise', 0, raising=False)

    touched = list(cd._APP_LOGGER_PREFIXES) + ['asyncio']
    levels = {name: logging.getLogger(name).level for name in touched}

    cd.set_active_debug_file(str(path))
    try:
        yield path
    finally:
        cd.set_active_debug_file(None)
        root = logging.getLogger()
        for h in list(root.handlers):
            if type(h).__name__ == '_DebugFileBridge':
                root.removeHandler(h)
        for name, level in levels.items():
            logging.getLogger(name).setLevel(level)


def _emit_disconnects(n: int) -> None:
    framework = logging.getLogger("asyncio")
    framework.setLevel(logging.ERROR)
    for _ in range(n):
        framework.error("Task exception was never retrieved",
                        exc_info=_closed_socket_exc_info())


def test_a_STORM_of_closed_sockets_cannot_drown_the_log(debug_log):
    """3,736 is not a hypothetical - it is the number from the real report."""
    _emit_disconnects(3736)
    lines = debug_log.read_text(encoding='utf-8', errors='replace').splitlines()
    assert len(lines) < 200, (
        f"3,736 closed-socket notices still cost {len(lines)} lines. On the "
        f"measured run that was 37,360 of 49,250, i.e. the user's own content "
        f"was 24% of the file they sent to be diagnosed.")


def test_the_FIRST_one_is_kept_in_full(debug_log):
    """Suppression must not be silent. The reader has to be able to see WHAT
    is being left out, or the log is lying by omission - which this repo
    already calls a bug waiting to be un-diagnosable."""
    _emit_disconnects(500)
    text = debug_log.read_text(encoding='utf-8', errors='replace')
    assert 'WebSocketClosedError' in text, (
        "every closed-socket notice was hidden, so nothing in the file says "
        "this is happening at all")
    assert 'Traceback' in text, "the kept one lost its traceback"


def test_the_suppression_SAYS_how_many(debug_log):
    _emit_disconnects(500)
    text = debug_log.read_text(encoding='utf-8', errors='replace')
    assert 'browser-connection notices' in text, (
        "the log never says how many were suppressed, so a reader cannot tell "
        "a quiet run from a storm")


def test_a_REAL_app_error_still_reaches_the_log(debug_log):
    """The control. A filter that cannot say yes is not a filter - and the
    direction that matters here is the one that would hide a real failure."""
    _emit_disconnects(300)
    app = logging.getLogger("core.canvas_logic")
    try:
        raise RuntimeError("a real download failure")
    except RuntimeError:
        app.error("Download failed for Lecture 4", exc_info=sys.exc_info())
    text = debug_log.read_text(encoding='utf-8', errors='replace')
    assert 'a real download failure' in text, (
        "a genuine app error was suppressed along with the noise")
    assert 'Download failed for Lecture 4' in text


def test_an_APP_side_connection_reset_is_NOT_treated_as_noise(debug_log):
    """A dropped connection reported by the APP is a fact about a transfer.

    Only framework loggers are filtered, deliberately: `ConnectionResetError`
    from `core.canvas_logic` means Canvas dropped a download, which is exactly
    what somebody reading this file is looking for.
    """
    app = logging.getLogger("core.canvas_logic")
    try:
        raise ConnectionResetError("canvas dropped us mid-file")
    except ConnectionResetError:
        app.warning("Canvas dropped the connection", exc_info=sys.exc_info())
    text = debug_log.read_text(encoding='utf-8', errors='replace')
    assert 'canvas dropped us mid-file' in text, (
        "an app-side connection error was filtered as framework noise")


def test_the_detector_walks_the_exception_CHAIN():
    """The record's own exception is the OUTER one. Looking only at the top
    would miss the pair tornado actually raises, in one of its two orders."""
    if WebSocketClosedError is None:
        pytest.skip("tornado is not importable in this environment")
    rec = logging.LogRecord('asyncio', logging.ERROR, __file__, 1,
                            'Task exception was never retrieved', (),
                            _closed_socket_exc_info())
    assert cd._is_browser_disconnect(rec) is True

    try:
        raise ValueError("something the app should hear about")
    except ValueError:
        other = logging.LogRecord('asyncio', logging.ERROR, __file__, 1,
                                  'boom', (), sys.exc_info())
    assert cd._is_browser_disconnect(other) is False, (
        "the detector matches exceptions that are not closed sockets, so it "
        "would swallow real framework failures")


def test_a_record_with_NO_exception_is_never_treated_as_a_disconnect():
    rec = logging.LogRecord('asyncio', logging.ERROR, __file__, 1,
                            'Task exception was never retrieved', (), None)
    assert cd._is_browser_disconnect(rec) is False
