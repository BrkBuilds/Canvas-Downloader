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

TWO RULES, and the second is a CORRECTION to the first version of this fix
(fd05d18), which fell back on ANY error:

1. **The timeout keeps the OLD answer.** If the request is merely slow and we
   guessed failure, the UN banner could still land AND a fallback banner beside
   it - two notifications for one event, worse than the defect being fixed.

2. **A user DENIAL is not a delivery failure.**
   ``UNErrorCodeNotificationsNotAllowed`` (code 1, verified against the
   framework) means someone turned this app's notifications off in System
   Settings. The only fallback that could still show a banner is ``osascript``,
   which posts under **Script Editor's** identity - so it would route around an
   explicit permission decision AND show a banner attributed to an app the user
   never ran. Product owner's call, 2026-08-11: respect the denial. The user is
   not left with nothing - ``play_completion_beep`` starts the chime on its own
   thread first, governed by the app's own Settings toggle rather than by macOS
   notification permission.
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
            # "reject" is a USER DENIAL (UNErrorCodeNotificationsNotAllowed);
            # "fail" is any other delivery failure. The two must take opposite
            # branches, which is the correction this file exists to pin.
            cb({"reject": "UNErrorDomain Code=1",
                "fail": "UNErrorDomain Code=1401"}.get(self.mode))

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

def test_a_DENIED_request_does_NOT_route_around_the_users_choice(un):
    """Rule 2. `_Center("reject")` returns UNErrorDomain code 1 - a denial - so
    the chain must STOP, not reach osascript under Script Editor's name."""
    N._un_denial_logged = False
    un.setattr(N, "_get_un_center", lambda: _Center("reject"), raising=False)
    assert N._show_macos_notification_un("Sync done", "12 files") is True


def test_a_NON_denial_failure_still_falls_back(un):
    """The original defect, and the half that must survive rule 2: a genuine
    delivery failure has to reach the next mechanism."""
    un.setattr(N, "_get_un_center", lambda: _Center("fail"), raising=False)
    assert N._show_macos_notification_un("Sync done", "12 files") is False


def test_the_denial_explanation_is_logged_ONCE_per_session(un, caplog):
    """It fires per completed download/sync otherwise, burying the run's real
    errors - the same reasoning as `_pan_hook_errs`."""
    import logging
    N._un_denial_logged = False
    un.setattr(N, "_get_un_center", lambda: _Center("reject"), raising=False)
    with caplog.at_level(logging.INFO, logger=N.logger.name):
        for _ in range(3):
            N._show_macos_notification_un("Sync done", "12 files")
    said = [r for r in caplog.records if "turned OFF" in r.getMessage()]
    assert len(said) == 1, f"logged {len(said)} times"


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


def test_a_SLOW_answer_is_still_read(un):
    """The handler is not required to be synchronous, and on a real system it
    is not - it arrives on an internal queue. A slow NON-denial failure must
    still reach the fallbacks."""
    un.setattr(N, "_get_un_center", lambda: _Center("fail", delay=0.05),
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


# --------------------------------------------------------------------------
# the predicate that separates a denial from a failure
# --------------------------------------------------------------------------

class _NSError:
    """What PyObjC hands back when the error IS a live NSError."""

    def __init__(self, domain, code):
        self._d, self._c = domain, code

    def code(self):
        return self._c

    def domain(self):
        return self._d

    def __str__(self):
        return f"{self._d} Code={self._c}"


@pytest.mark.parametrize("err,want,why", [
    (_NSError("UNErrorDomain", 1), True, "the real denial"),
    (_NSError("UNErrorDomain", 1401), False, "invalid-no-content is a FAILURE"),
    (_NSError("UNErrorDomain", 105), False, "attachment corrupt is a FAILURE"),
    (_NSError("NSCocoaErrorDomain", 1), False,
     "code 1 in another domain means something else entirely"),
    ("UNErrorDomain Code=1", True, "the string form the macOS 15 audit LOGGED"),
    ('Error Domain=UNErrorDomain Code=1 "Notifications are not allowed"', True,
     "the fuller NSError description"),
    ("UNErrorDomain Code=105", False, "string form, not a denial"),
    ("something unreadable", False, "unreadable is NOT evidence of a denial"),
    (None, False, "no error at all"),
])
def test_only_a_real_denial_counts_as_a_denial(err, want, why):
    assert N._un_error_is_denial(err) is want, why


def test_an_unreadable_error_falls_back_rather_than_going_silent():
    """The safe direction is the one that cannot suppress a notification the
    user still wants: at worst it costs one extra fallback attempt, whereas
    guessing "denied" would stop trying on evidence we do not have."""
    class _Hostile:
        def code(self): raise RuntimeError("nope")
        def domain(self): raise RuntimeError("nope")
        def __str__(self): raise RuntimeError("nope")
    assert N._un_error_is_denial(_Hostile()) is False


def test_the_denial_branch_returns_SETTLED_not_delivered():
    """The docstring must not go back to promising a banner - the return value
    now means "stop asking", and one of the three ways to settle is that the
    user said no."""
    fn = next(n for n in ast.walk(ast.parse(SRC))
              if isinstance(n, ast.FunctionDef)
              and n.name == "_show_macos_notification_un")
    doc = ast.get_docstring(fn) or ""
    assert "NOT" in doc and "banner was shown" in doc.lower(), (
        "the docstring must state that True means settled, not delivered")
    assert "NotificationsNotAllowed" in doc


def test_the_chime_is_dispatched_before_the_banner_and_independently():
    """The denial policy is only defensible because the user still gets a
    signal. `_play_macos_sound` runs on its own thread and is governed by the
    app's own Settings toggle, not by macOS notification permission - so a
    denied user still hears the run finish."""
    fn = next(n for n in ast.walk(ast.parse(SRC))
              if isinstance(n, ast.FunctionDef) and n.name == "play_completion_beep")
    body = ast.unparse(fn)
    i_sound = body.index("_play_macos_sound")
    i_notify = body.index("_show_macos_notification")
    assert i_sound < i_notify, (
        "the chime must be started before the notification path, so a denial "
        "cannot cost the user both signals")
