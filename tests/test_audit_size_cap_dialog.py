"""The size cap lives in the Settings dialog, not on the download page.

`configure` only ever knew the download page, so the `max_file_size` factor was
accepted into every matrix row and applied to NONE of them - half the plan
believed it was testing the capped path and ran the uncapped one twice. It is
now driven through the real dialog and proved from the engine's own parameter
line ("Max file size: 5 MB" / "disabled").

Leaving the dialog is the fiddly half. Streamlit only enables Save when
something CHANGED, so asking for the state the app is already in leaves a
disabled button and an open modal for the next click to fight; and the modal's
unmount can land just after `settle()` returns, so a single read reported "did
not close" on a row that had closed it perfectly and went on to download
without a hitch. A check that cries wolf on a healthy run is worse than none.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.audit.harness.flows import DownloadFlow, FlowError    # noqa: E402


class _Locator:
    def __init__(self, n=1): self._n = n
    def count(self): return self._n
    @property
    def first(self): return self
    def click(self, **kw): pass
    def fill(self, *a): pass
    def type(self, *a, **kw): pass
    def press(self, *a): pass
    def locator(self, *a, **kw): return self
    def get_by_role(self, *a, **kw): return self


class _Keyboard:
    def __init__(self, page): self.page = page
    def press(self, key):
        if key == "Escape":
            self.page.dialog_count = 0
            self.page.escapes += 1


class _Page:
    """A dialog that disappears after `closes_after` polls, or never.

    Poll 1 is the flow's "did it open?" check, so `closes_after=1` means the
    modal is gone by the first close poll - i.e. it closed immediately.
    """
    def __init__(self, closes_after=0, closes=True):
        self.dialog_count = 1
        self.polls = 0
        self.escapes = 0
        self._closes_after = closes_after
        self._closes = closes
        self.keyboard = _Keyboard(self)

    def locator(self, sel):
        if 'stDialog' in sel:
            self.polls += 1
            if self._closes and self.polls > self._closes_after:
                self.dialog_count = 0
            return _Locator(self.dialog_count)
        return _Locator(1)


class _Session:
    def __init__(self, page):
        self.page = page
        self.rp = None
    def probe_key(self, key, role="button"): return {"found": True}
    def click(self, key, **kw): return {"clicked": True}
    def set_checkbox(self, key, value, **kw):
        return {"set": True, "changed": False, "checked": value}
    def _host(self, key): return _Locator(1)
    def settle(self, **kw): return {}
    def app_url(self, *a, **kw): return "http://x"
    def goto(self, url, **kw): return {}


def _flow(page):  # noqa: D401
    f = DownloadFlow.__new__(DownloadFlow)
    f.s = _Session(page)
    f.rp = None
    f.trace = []
    return f


# --------------------------------------------------------------------------

def test_a_dialog_that_closes_immediately_reports_success():
    f = _flow(_Page(closes_after=1))
    res = f.set_size_cap(5)
    assert res["ok"] and res["dialog_closed"]
    assert not res["closed_with_escape"]


def test_a_dialog_that_closes_a_moment_later_is_NOT_a_failure():
    """The regression: one sample right after settle() called a healthy row
    broken."""
    f = _flow(_Page(closes_after=7))
    res = f.set_size_cap(None)
    assert res["ok"], "a slow unmount was reported as a failure"
    assert not res["closed_with_escape"]


def test_a_dialog_that_never_closes_is_escaped():
    """Save is disabled when nothing changed, so the modal would otherwise be
    left open for the next click to fight."""
    page = _Page(closes=False)
    f = _flow(page)
    res = f.set_size_cap(None)
    assert res["ok"] and res["closed_with_escape"]
    assert page.escapes == 1


def test_the_dialog_must_actually_open():
    class _Never(_Page):
        def locator(self, sel):
            return _Locator(0) if "stDialog" in sel else _Locator(1)
    with pytest.raises(FlowError):
        _flow(_Never()).set_size_cap(5)


def test_an_unclickable_settings_button_is_fatal_not_silent():
    f = _flow(_Page(closes_after=1))
    f.s.click = lambda key, **kw: {"clicked": False, "reason": "gated"}
    with pytest.raises(FlowError):
        f.set_size_cap(5)


@pytest.mark.parametrize("mb,want_on", [(5, True), (500, True), (None, False)])
def test_the_toggle_is_set_from_the_requested_value(mb, want_on):
    f = _flow(_Page(closes_after=1))
    seen = {}
    f.s.set_checkbox = lambda k, v, **kw: seen.setdefault("v", v) or {"set": True}
    f.set_size_cap(mb)
    assert seen["v"] is want_on


@pytest.mark.parametrize("mb", [5, 500, None])
def test_the_row_records_what_it_asked_for(mb):
    """Each call gets its own page: the flow opens the dialog fresh every
    time, and a shared fake would have it already gone on the second."""
    assert _flow(_Page(closes_after=1)).set_size_cap(mb)["mb"] == mb
