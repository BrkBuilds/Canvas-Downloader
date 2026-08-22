"""The scan that decides WHAT to download had no retry; the fetcher had one.

`fp:16e0de9e610a`. A single transient 502 on
`GET /courses/{id}/modules/{mid}/items` dropped that module from the metadata
scan for the whole run - silently, because the consumer does
`if items is None: continue`. The scan feeds BOTH `sync/analysis.py` and the
download engine, so the module's Pages, links and `module_map` entries simply
did not exist for that run. Meanwhile `sync/execution.py` has retried 5xx with
exponential backoff on the FILE-DOWNLOAD path all along.

These tests drive a REAL local HTTP server through the REAL session that
`_new_canvas_client` builds, because the interesting properties are all things
a parameter list cannot tell you - whether a 503 with a hostile `Retry-After`
parks the app, whether a POST is replayed, whether the app's own rate-limit
handling is still reached. Reading `Retry(...)` back and asserting its fields
would test that I typed what I typed.

No Canvas, no network, no credentials - so it runs on every platform and in CI.
"""
from __future__ import annotations

import http.server
import threading
import time

import pytest

from core.canvas_logic import _CANVAS_RETRY, CanvasManager


class _Flaky(http.server.BaseHTTPRequestHandler):
    """Fails `fail_times` in a row, then succeeds. Behaviour set per-test on the
    server object so one handler covers every scenario."""

    def log_message(self, *a):     # keep pytest output clean
        pass

    def _serve(self):
        s = self.server
        s.hits += 1
        mode = s.mode
        if mode == "flaky502" and s.hits <= s.fail_times:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(b"bad gateway")
            return
        if mode == "park503" and s.hits <= s.fail_times:
            self.send_response(503)
            # A hostile value: obeying it parks the app for a DAY.
            self.send_header("Retry-After", "86400")
            self.end_headers()
            self.wfile.write(b"unavailable")
            return
        if mode == "always404":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"nope")
            return
        if mode == "always429":
            self.send_response(429)
            self.send_header("Retry-After", "86400")
            self.end_headers()
            self.wfile.write(b"slow down")
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    do_GET = _serve
    do_POST = _serve


@pytest.fixture
def server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Flaky)
    srv.hits = 0
    srv.mode = "ok"
    srv.fail_times = 0
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    srv.base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def session(server):
    """The REAL session canvasapi will use, adapter and all."""
    canvas = CanvasManager._new_canvas_client(server.base, "tok")
    return canvas._Canvas__requester._session


#: How long any single request in this file may take before the test decides it
#: is parked. Generous next to the real worst case (~3.5s of bounded backoff),
#: tiny next to what a hostile ``Retry-After: 86400`` costs.
_JOIN_TIMEOUT = 25.0


def _get(session, server, mode, fail_times=2, method="GET"):
    """Issue the request ON A THREAD, so a parked one FAILS instead of hanging.

    THE MUTATION PASS FOUND THIS, and it is the reason the helper looks like
    this. The first version called `session.request` directly, and the mutant
    that restores `respect_retry_after_header=True` made urllib3 obey the
    server's `Retry-After: 86400` - so the test did not fail, it BLOCKED for a
    day, the pass had to be killed from outside, and it left a mutant on disk.

    A test for "this does not park" that can only hang is not a test, it is the
    defect wearing the test's clothes. CLAUDE.md states the rule for the ffmpeg
    watchdog ("a test for 'this terminates' must run the call on a thread with a
    join timeout, so a regression FAILS instead of hanging") - it applies to
    every unbounded-wait guard, not just that one.
    """
    server.hits = 0
    server.mode = mode
    server.fail_times = fail_times
    box: dict = {}

    def _work():
        try:
            box["r"] = session.request(method, server.base + "/x", timeout=(5, 10))
        except Exception as e:                                   # noqa: BLE001
            box["exc"] = e

    t0 = time.time()
    th = threading.Thread(target=_work, daemon=True)
    th.start()
    th.join(_JOIN_TIMEOUT)
    elapsed = time.time() - t0
    if th.is_alive():
        raise AssertionError(
            f"the request had not returned after {_JOIN_TIMEOUT}s - it is parked "
            f"or retrying without bound ({server.hits} requests so far)")
    if "exc" in box:
        raise box["exc"]
    return box["r"], server.hits, elapsed


# ------------------------------------------------------------ the finding

def test_a_transient_502_is_retried_and_succeeds(session, server):
    """THE regression test. Before: the first 502 ended it and the module was
    dropped from the scan without the user being told anything."""
    r, hits, _ = _get(session, server, "flaky502", fail_times=2)
    assert r.status_code == 200
    assert hits == 3, f"expected 2 failures then a success, saw {hits} requests"


def test_the_retry_is_bounded_and_still_fails_honestly(session, server):
    """An outage is not a transient blip. The retry must give up, and give up
    as a 502 - `raise_on_status=False` keeps canvasapi raising ITS error with
    its existing message, so every handler downstream is unchanged."""
    r, hits, _ = _get(session, server, "flaky502", fail_times=99)
    assert r.status_code == 502
    assert hits <= 6, f"unbounded retry: {hits} requests"


# ------------------------------- the rule this repo already paid for once

def test_a_hostile_retry_after_does_not_park_the_app(session, server):
    """`Retry-After: 86400` on a 503.

    CLAUDE.md: "Nothing may park the app on a number a server chose" - a literal
    Retry-After once parked a download on a one-second cancel-polling loop for a
    DAY. urllib3 honours the header by default, so this is the parameter that
    had to be turned OFF rather than left at its default.
    """
    r, _hits, elapsed = _get(session, server, "park503", fail_times=2)
    assert r.status_code == 200
    assert elapsed < 10, (
        f"took {elapsed:.1f}s - the server's Retry-After was obeyed, which for a "
        f"real hostile value means the app hangs for a day")


# --------------------------------------------------- what must NOT retry

def test_a_404_is_not_retried(session, server):
    """Not transient. Retrying it wastes the user's time and Canvas's quota."""
    r, hits, _ = _get(session, server, "always404")
    assert (r.status_code, hits) == (404, 1)


def test_a_429_is_not_retried_here(session, server):
    """Rate limiting is handled DELIBERATELY elsewhere - `sync/execution.py`
    treats 403 and 429 together with a CLAMPED Retry-After (`parse_retry_after`)
    on the aiohttp download path. Retrying a rate limit on a short backoff
    aggravates it, and silently absorbing it here would hide the one signal that
    path is watching for."""
    r, hits, _ = _get(session, server, "always429")
    assert (r.status_code, hits) == (429, 1)


def test_a_post_is_never_replayed(session, server):
    """A retry replays the request. Only idempotent methods may be replayed;
    canvasapi uses POST/PUT/DELETE for real mutations."""
    r, hits, _ = _get(session, server, "flaky502", fail_times=2, method="POST")
    assert (r.status_code, hits) == (502, 1)


# ------------------------------------------------------ the configuration

def test_only_status_is_retried_never_a_timeout():
    """STATUS retries only - and the connect half of this was a regression I had
    reasoned my way into before measuring it.

    A retry of either kind only begins after a TIMEOUT has already elapsed (60s
    read, 15s connect), so it multiplies the wall clock on exactly the slow or
    unreachable link those timeouts exist for. Measured against a blackholed
    host at a 3s connect timeout: no-retry 3.01s, connect=2 **10.01s**. At the
    adapter's real 15s that is 15s -> ~50s before the user is told Canvas cannot
    be reached, on the LOGIN path, for no benefit to the 502 this exists for.

    "Connect failures are cheap and transient" is true of a REFUSED connection
    and false of a FILTERED one, and the filtered one is the case that hurts.
    """
    assert _CANVAS_RETRY.read == 0, "a read retry costs another full 60s timeout"
    assert _CANVAS_RETRY.connect == 0, (
        "a connect retry costs another full 15s connect timeout on the login "
        "path, measured at 3.3x, and buys nothing for a 502")
    assert _CANVAS_RETRY.status and _CANVAS_RETRY.status > 0


def test_every_canvas_client_gets_the_retry():
    """`_new_canvas_client` is the ONE place a canvasapi session is built - the
    main client and both per-worker clients go through it - so mounting here is
    what makes the bulk get_files(), get_modules(), the module-items fan-out and
    the per-file fan-out all covered by one decision."""
    canvas = CanvasManager._new_canvas_client("https://x.instructure.com", "tok")
    for scheme in ("https://x.instructure.com", "http://x.instructure.com"):
        retries = canvas._Canvas__requester._session.get_adapter(scheme).max_retries
        assert retries.status and retries.status > 0, f"{scheme} has no status retry"
        assert 502 in retries.status_forcelist


# ------------------------------------------- the residual must be LOUD

class _FakeModule:
    def __init__(self, mid, name):
        self.id, self.name = mid, name


class _FakeCourse:
    id = 43660
    name = "Test Course"

    def __init__(self, mods):
        self._mods = mods

    def get_modules(self):
        return list(self._mods)


def _drive_scan(monkeypatch, failing_ids, caplog, progress=None):
    """Run the REAL _get_files_from_modules with the module-items fetch failing
    for `failing_ids`, i.e. the state left after the retry has been exhausted."""
    import logging

    import canvasapi.module
    import core.canvas_logic as cl

    mods = [_FakeModule(1, "Uge 44: JavaScript"), _FakeModule(2, "Uge 45: HTML")]
    course = _FakeCourse(mods)

    class _FakeReq:
        pass

    class _FakeWorkerCourse:
        _requester = _FakeReq()

    class _FakeCanvas:
        def get_course(self, _cid):
            return _FakeWorkerCourse()

    monkeypatch.setattr(cl.CanvasManager, "_new_canvas_client",
                        staticmethod(lambda *a, **k: _FakeCanvas()))

    class _FakeCanvasModule:
        def __init__(self, requester, attrs):
            self._id = attrs["id"]

        def get_module_items(self):
            if self._id in failing_ids:
                raise Exception("Encountered an error: status code 502")
            return []

    monkeypatch.setattr(canvasapi.module, "Module", _FakeCanvasModule)

    mgr = object.__new__(cl.CanvasManager)
    mgr.api_url, mgr.api_key = "https://x.instructure.com", "tok"
    with caplog.at_level(logging.WARNING, logger="core.canvas_logic"):
        mgr._get_files_from_modules(course, progress_callback=progress)
    return caplog.text


def test_a_module_dropped_after_retries_is_reported_not_swallowed(monkeypatch, caplog):
    """The other half of the finding. Retrying fixes the transient case; a
    module that is STILL unreadable used to vanish with only a per-module debug
    line, and this scan feeds both the analyzer and the download engine."""
    events = []
    text = _drive_scan(monkeypatch, {1}, caplog,
                       progress=lambda *a, **k: events.append((a, k)))

    assert "1 of 2 module(s)" in text, text
    assert "Uge 44: JavaScript" in text, "the dropped module is not named"

    logged = [a for a, k in events if k.get("progress_type") == "log"]
    assert logged, "nothing reached the run's own log - only the debug file"
    assert "Could not read 1 of 2 modules" in logged[0][0]


def test_a_clean_scan_reports_nothing(monkeypatch, caplog):
    """A warning on every healthy run is noise, and noise is what makes a real
    one unnoticeable."""
    events = []
    text = _drive_scan(monkeypatch, set(), caplog,
                       progress=lambda *a, **k: events.append((a, k)))
    assert "module(s) after retries" not in text
    assert not [a for a, k in events if k.get("progress_type") == "log"
                and "Could not read" in str(a)]


def test_the_report_is_ONE_line_not_one_per_module(monkeypatch, caplog):
    """The failure mode being guarded against is a 502 STORM. One line per
    module would bury the run's real errors - the same reasoning as the Panopto
    hook's first-failure-only rule."""
    events = []
    _drive_scan(monkeypatch, {1, 2}, caplog,
                progress=lambda *a, **k: events.append((a, k)))
    logged = [a for a, k in events if k.get("progress_type") == "log"
              and "Could not read" in str(a)]
    assert len(logged) == 1, f"{len(logged)} summary lines for 2 failed modules"
    assert "2 of 2" in logged[0][0]
