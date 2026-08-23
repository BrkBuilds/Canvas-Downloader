"""`_CanvasTimeoutAdapter` injected NOTHING for as long as it used setdefault.

The class exists so `course.get_modules()` / `course.get_files()` cannot hang
forever on a stalled connection - its own docstring says so. It did it with
`kwargs.setdefault('timeout', ...)`, and that is a no-op in an adapter:
`requests.Session.request` builds `send_kwargs = {"timeout": timeout, ...}` and
passes the key down EXPLICITLY, so `send` always sees `'timeout'` present, with
value None whenever the caller named none - which is every canvasapi call.
`setdefault` found a key and did nothing.

MEASURED 2026-08-23 on Windows (requests 2.32.3, urllib3 2.5.0) against a
server that accepts the connection and then sends no byte: the request HUNG
PAST 150s with a 60s read timeout configured. A blackholed IP failed in 21.0s -
Windows' own TCP SYN schedule, not the adapter's 15s - so connect was bounded
only by accident of the platform and read was not bounded at all.

The asymmetry that hid it: the async DOWNLOAD path builds
`aiohttp.ClientTimeout(total=3600, sock_read=60, sock_connect=15)` and really
is bounded. Only the synchronous METADATA path - the one this adapter is
mounted on - was open-ended, and a metadata call that never returns looks like
a slow Canvas rather than a bug.

WHY THESE TESTS RUN ON A THREAD WITH A JOIN TIMEOUT: this repo's rule, already
written for the ffmpeg watchdog, is that a test for "this terminates" must be
able to FAIL rather than hang. Calling the request directly would make a
regression hang the suite (and, during a mutation pass, burn the whole
per-mutant timeout) instead of reporting.

No Canvas, no network, no credentials - runs on every platform and in CI.
"""
from __future__ import annotations

import socket
import threading
import time

import pytest
import requests
from requests.adapters import HTTPAdapter

import core.canvas_logic as CL


# --------------------------------------------------------------- fixtures

@pytest.fixture
def stalling_server():
    """A socket that ACCEPTS and then never sends a byte.

    This is the shape that matters: a refused or blackholed connection is
    bounded by the OS, but a server that completes the TCP handshake and then
    goes quiet is bounded by NOTHING except a read timeout.
    """
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    held: list[socket.socket] = []

    def accept_forever():
        while True:
            try:
                conn, _ = srv.accept()
                held.append(conn)          # keep it open, answer nothing
            except OSError:
                return

    threading.Thread(target=accept_forever, daemon=True).start()
    yield srv.getsockname()[1]
    srv.close()
    for c in held:
        try:
            c.close()
        except OSError:
            pass


def _session():
    """A session mounting the REAL adapter with the REAL retry, as the app does."""
    s = requests.Session()
    adapter = CL._CanvasTimeoutAdapter(max_retries=CL._CANVAS_RETRY)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def _kwargs_reaching_the_transport(url: str, **get_kwargs) -> dict:
    """What `HTTPAdapter.send` actually receives, through the real stack.

    Asserting on the adapter's source, or on a timeout we passed ourselves,
    would not have caught the original defect - the defect was precisely that
    the value never arrived. So intercept at the transport boundary.
    """
    seen: dict = {}
    original = HTTPAdapter.send

    def spy(self, request, **kwargs):
        seen.clear()
        seen.update(kwargs)
        raise requests.exceptions.ConnectTimeout("intercepted")

    HTTPAdapter.send = spy
    try:
        try:
            _session().get(url, **get_kwargs)
        except Exception:
            pass
    finally:
        HTTPAdapter.send = original
    return seen


# ------------------------------------------------- the injection arrives

def test_requests_really_does_pass_timeout_explicitly():
    """The premise the whole fix rests on, pinned so it cannot rot.

    If a future requests stopped putting 'timeout' in send_kwargs, `setdefault`
    would start working and this file's reasoning would be obsolete. Better to
    fail here, loudly, than to leave a comment asserting someone else's
    internals.
    """
    seen = _kwargs_reaching_the_transport("http://127.0.0.1:9/x")
    assert "timeout" in seen, (
        "requests no longer passes 'timeout' down explicitly - re-read "
        "_CanvasTimeoutAdapter's docstring, its reasoning has changed")


def test_a_default_timeout_is_injected_when_the_caller_names_none():
    seen = _kwargs_reaching_the_transport("http://127.0.0.1:9/x")
    assert seen.get("timeout") == (CL._CONNECT_TIMEOUT_SECONDS,
                                   CL._DEFAULT_READ_TIMEOUT_SECONDS), (
        "the adapter injected nothing - this is the setdefault defect")


def test_an_explicit_caller_timeout_is_left_alone():
    """The adapter supplies a DEFAULT; it must never override a real choice."""
    seen = _kwargs_reaching_the_transport("http://127.0.0.1:9/x", timeout=(2, 3))
    assert seen.get("timeout") == (2, 3)


def test_the_connect_half_is_not_zero():
    """`_CANVAS_RETRY` sets connect=0 on the stated grounds that a connect
    timeout has 'already elapsed' before a retry begins. That reasoning is only
    sound if a connect timeout exists at all."""
    connect, _read = _kwargs_reaching_the_transport("http://127.0.0.1:9/x")["timeout"]
    assert isinstance(connect, (int, float)) and connect > 0


# ------------------------------------------------------ the behaviour

def _elapsed_until_it_gives_up(port: int, cap: float) -> tuple[float, str]:
    """Run the request on a thread so a regression FAILS instead of hanging."""
    out: dict = {}

    def go():
        start = time.monotonic()
        try:
            _session().get(f"http://127.0.0.1:{port}/api/v1/users/self")
            out["kind"] = "no-exception"
        except Exception as exc:
            out["kind"] = type(exc).__name__
        out["elapsed"] = time.monotonic() - start

    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(timeout=cap)
    if t.is_alive():
        pytest.fail(
            f"a stalled server was still not given up on after {cap}s - the "
            f"read timeout is not being applied (the setdefault defect)")
    return out["elapsed"], out["kind"]


def test_a_server_that_accepts_and_never_replies_is_given_up_on(
        stalling_server, monkeypatch):
    """THE test. Pre-fix this hung past 150s with a 60s read timeout set.

    CANVAS_TIMEOUT is lowered so the test is quick; the property under test is
    'bounded by the configured read timeout', not the specific number.
    """
    monkeypatch.setenv("CANVAS_TIMEOUT", "3")
    elapsed, kind = _elapsed_until_it_gives_up(stalling_server, cap=30)
    assert elapsed < 15, (
        f"gave up only after {elapsed:.1f}s with a 3s read timeout configured")
    assert kind != "no-exception", "a stalled read must surface as an error"


def test_the_read_timeout_is_actually_honoured_not_merely_bounded(
        stalling_server, monkeypatch):
    """A cap alone could be satisfied by some unrelated bound (an OS limit, a
    retry budget). Raising the configured value must move the observed one, or
    we have not shown that OUR timeout is what stopped it."""
    monkeypatch.setenv("CANVAS_TIMEOUT", "2")
    short, _ = _elapsed_until_it_gives_up(stalling_server, cap=30)
    monkeypatch.setenv("CANVAS_TIMEOUT", "6")
    longer, _ = _elapsed_until_it_gives_up(stalling_server, cap=40)
    assert longer > short + 1.5, (
        f"raising CANVAS_TIMEOUT 2->6 changed the wait only {short:.1f}s -> "
        f"{longer:.1f}s, so something other than our read timeout is bounding it")


def test_a_slow_but_PROGRESSING_response_is_not_cut_off(monkeypatch):
    """The safety argument for turning the timeout on, proved rather than claimed.

    The read half is the gap BETWEEN bytes, not the total duration, so a large
    paginated reply that keeps arriving is unaffected however long it takes.
    If that were wrong, this fix would convert "Canvas is slow today" into
    "Canvas failed", which is a far worse regression than the hang it removes.

    Here: a 2s read timeout against a response that drips for ~4s in 0.5s
    steps. Total duration is double the timeout; no individual gap reaches it.
    """
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def drip():
        conn, _ = srv.accept()
        try:
            conn.recv(4096)
            body = b"x" * 8
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 64\r\n\r\n")
            for _ in range(8):                 # 8 x 0.5s = ~4s total
                time.sleep(0.5)
                conn.sendall(body)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    threading.Thread(target=drip, daemon=True).start()
    monkeypatch.setenv("CANVAS_TIMEOUT", "2")

    out: dict = {}

    def go():
        start = time.monotonic()
        try:
            r = _session().get(f"http://127.0.0.1:{port}/x")
            out["status"] = r.status_code
            out["len"] = len(r.content)
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
        out["elapsed"] = time.monotonic() - start

    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(timeout=30)
    srv.close()

    assert not t.is_alive(), "the drip test itself hung"
    assert "error" not in out, (
        f"a progressing response was cut off: {out.get('error')} - the read "
        f"timeout is being applied to the TOTAL duration, not the gap between "
        f"bytes, which would make slow-Canvas days fail outright")
    assert out.get("len") == 64
    assert out["elapsed"] > 2, (
        "the fixture did not actually outlast the timeout, so it proved nothing")


# ------------------------------------------- CANVAS_TIMEOUT is parsed safely

@pytest.mark.parametrize("raw,expected", [
    ("90", 90),
    ("  120  ", 120),
    ("90.5", 90),          # a float string used to raise ValueError
    ("abc", 60),           # ...and so did this, on EVERY request
    ("", 60),
    ("0", 60),             # requests treats 0 as immediate failure
    ("-5", 60),
])
def test_canvas_timeout_env_is_parsed_defensively(monkeypatch, raw, expected):
    """It is read inside `send`, so a malformed value used to break every
    Canvas API call in the app with the env var as the only clue."""
    monkeypatch.setenv("CANVAS_TIMEOUT", raw)
    assert CL._read_timeout_seconds() == expected


def test_canvas_timeout_absent_uses_the_default(monkeypatch):
    monkeypatch.delenv("CANVAS_TIMEOUT", raising=False)
    assert CL._read_timeout_seconds() == CL._DEFAULT_READ_TIMEOUT_SECONDS


def test_a_malformed_env_var_cannot_break_a_request(monkeypatch):
    """The consequence, not just the parser: a bad value must still produce a
    usable timeout at the transport rather than raising out of send()."""
    monkeypatch.setenv("CANVAS_TIMEOUT", "not-a-number")
    seen = _kwargs_reaching_the_transport("http://127.0.0.1:9/x")
    assert seen.get("timeout") == (CL._CONNECT_TIMEOUT_SECONDS,
                                   CL._DEFAULT_READ_TIMEOUT_SECONDS)


# --------------------------------------------- the adapter is really mounted

def test_the_app_mounts_this_adapter_on_both_schemes():
    """A perfect adapter that nothing mounts bounds nothing. The mount lives in
    `_new_canvas_client` behind a broad except, so a silent failure there is
    exactly the shape that would leave this unbounded again."""
    import ast
    import inspect
    import textwrap

    # dedent: getsource on a method returns it at class-body indentation, and
    # a decorator line makes ast.parse reject it outright.
    src = textwrap.dedent(inspect.getsource(CL.CanvasManager._new_canvas_client))
    tree = ast.parse(src)
    mounts = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr == "mount"]
    schemes = {a.value for m in mounts for a in m.args
               if isinstance(a, ast.Constant) and isinstance(a.value, str)}
    assert {"https://", "http://"} <= schemes, (
        f"the timeout adapter is not mounted on both schemes: {schemes}")
    assert "_CanvasTimeoutAdapter" in src
