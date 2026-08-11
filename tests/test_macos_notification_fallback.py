"""A macOS notification macOS REJECTS must fall through to the next mechanism.

Found by the macOS 15 live audit (2026-08-10), finding fp:3833d3d15043, and
provable from the source alone: ``_show_macos_notification_un`` handed the
request to ``addNotificationRequest_withCompletionHandler_`` and then returned
``True`` on the very next line - **before** the completion handler had run. The
handler only LOGGED the error; nothing consulted it.

So a request macOS rejected was reported to the dispatcher as SUCCESS, and
``_show_macos_notification`` never tried NSUserNotification, pync, or osascript.
The user got no banner at all, from any of the four mechanisms.

The log ordering PROVES the race rather than inferring it - from one call:

    UN notification posted via UNUserNotificationCenter     <- returned True
    UN addNotificationRequest error: ...                    <- the answer

It also broke the function's own documented promise: "Returns False on ANY
failure so the caller falls back to NSUserNotification, keeping us strictly no
worse than before".

THE FALLBACK FIRES ONLY ON AN EXPLICIT REJECTION, and the timeout deliberately
keeps the OLD answer. If the request is merely slow and we guessed failure, the
UN banner could still land AND a fallback banner beside it - two notifications
for one event, which is a worse defect than the one being fixed.
"""

from __future__ import annotations

import ast
import sys
import threading
import time
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import engine.notifications as N  # noqa: E402

SRC = (REPO / "engine" / "notifications.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# a fake UNUserNotificationCenter
# --------------------------------------------------------------------------

class _Center:
    """Stands in for UNUserNotificationCenter.

    *mode* decides what the completion handler is called with and WHEN, which
    is the whole subject of this file.
    """

    def __init__(self, mode: str, delay: float = 0.0):
        self.mode = mode
        self.delay = delay
        self.requests = []

    def addNotificationRequest_withCompletionHandler_(self, req, cb):
        self.requests.append(req)

        def _fire():
            if self.delay:
                time.sleep(self.delay)
            cb("UNErrorDomain Code=1" if self.mode == "reject" else None)

        if self.mode == "never":
            return                      # handler is simply never called
        if self.delay:
            threading.Thread(target=_fire, daemon=True).start()
        else:
            _fire()


@pytest.fixture
def un(monkeypatch):
    """Make the UN path reachable off macOS, with every side effect stubbed."""
    mod = types.ModuleType("UserNotifications")

    class _Content:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

        def setTitle_(self, v): self.title = v
        def setSubtitle_(self, v): self.subtitle = v
        def setBody_(self, v): self.body = v

    class _Request:
        @staticmethod
        def requestWithIdentifier_content_trigger_(ident, content, trigger):
            return {"id": ident, "content": content, "trigger": trigger}

    mod.UNMutableNotificationContent = _Content
    mod.UNNotificationRequest = _Request
    monkeypatch.setitem(sys.modules, "UserNotifications", mod)
    monkeypatch.setattr(N, "request_macos_notification_permission",
                        lambda *a, **k: None, raising=False)
    monkeypatch.setattr(N, "_ensure_un_delegate", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(N, "_log_un_settings", lambda *a, **k: None, raising=False)
    return monkeypatch


# --------------------------------------------------------------------------
# the three outcomes
# --------------------------------------------------------------------------

def test_a_REJECTED_request_reports_failure_so_the_caller_falls_back(un):
    """The reported defect. Before the fix this returned True."""
    un.setattr(N, "_get_un_center", lambda: _Center("reject"), raising=False)
    assert N._show_macos_notification_un("Sync done", "12 files") is False


def test_an_ACCEPTED_request_still_reports_success(un):
    """The direction that must not regress - this is the normal path."""
    un.setattr(N, "_get_un_center", lambda: _Center("accept"), raising=False)
    assert N._show_macos_notification_un("Sync done", "12 files") is True


def test_a_handler_that_never_answers_keeps_the_OLD_answer(un):
    """Guessing failure on a slow accept would let the UN banner land AND a
    fallback banner beside it - two notifications for one event."""
    un.setattr(N, "_get_un_center", lambda: _Center("never"), raising=False)
    monkey_timeout = 0.05
    un.setattr(N, "_UN_DELIVERY_TIMEOUT_S", monkey_timeout, raising=False)
    t0 = time.time()
    assert N._show_macos_notification_un("Sync done", "12 files") is True
    assert time.time() - t0 >= monkey_timeout, "it must actually have waited"


def test_a_SLOW_rejection_is_still_caught(un):
    """The handler is not required to be synchronous, and on a real system it
    is not - it arrives on an internal queue."""
    un.setattr(N, "_get_un_center", lambda: _Center("reject", delay=0.05),
               raising=False)
    assert N._show_macos_notification_un("Sync done", "12 files") is False


def test_the_wait_is_bounded(un):
    """This runs at the end of a download or sync. An unbounded wait on a
    system callback is the failure mode this repo already documents for
    ffmpeg and the transcription worker."""
    assert isinstance(N._UN_DELIVERY_TIMEOUT_S, (int, float))
    assert 0 < N._UN_DELIVERY_TIMEOUT_S <= 5, (
        "generous enough for a real accept, small enough to be invisible at "
        "the end of a run")


def test_the_request_is_actually_posted_before_we_wait(un):
    """Without this the tests above would pass against a function that waits
    on a handler for a request it never sent."""
    center = _Center("accept")
    un.setattr(N, "_get_un_center", lambda: center, raising=False)
    N._show_macos_notification_un("Sync done", "12 files")
    assert len(center.requests) == 1


# --------------------------------------------------------------------------
# the shape, so the race cannot be reintroduced
# --------------------------------------------------------------------------

def _fn(name: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(ast.parse(SRC))
                if isinstance(n, ast.FunctionDef) and n.name == name)


def test_the_result_is_not_returned_before_the_handler_is_awaited():
    """The regression is one line: `return True` immediately after the add.

    Asserted structurally because the behavioural tests above stub the center,
    and a future edit could satisfy them while restoring the race for the real
    framework - e.g. by returning early on some other branch.
    """
    fn = _fn("_show_macos_notification_un")
    src = ast.unparse(fn)
    add = src.index("addNotificationRequest_withCompletionHandler_")
    wait = src.find(".wait(", add)
    assert wait != -1, "the completion handler must be awaited after the add"
    tail = src[add:wait]
    assert "return True" not in tail, (
        "a `return True` between posting the request and awaiting its result "
        "is exactly the reported defect")


def test_the_fallback_chain_below_it_is_still_wired():
    """The fix is worthless if nothing consults the False."""
    disp = ast.unparse(_fn("_show_macos_notification"))
    i = disp.index("_show_macos_notification_un")
    assert "_show_macos_notification_native" in disp[i:], (
        "NSUserNotification must still be tried when the UN path reports "
        "failure")
