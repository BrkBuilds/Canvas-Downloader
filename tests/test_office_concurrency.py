"""macOS gives a user session exactly ONE PowerPoint. Two instances share it.

THE DEFECT, reproduced on demand 2026-08-11 by starting two conversion batches
at the same moment against the real applications:

    batch A   8 files ->  0 converted, 8 failed
    batch B   8 files ->  0 converted, 8 failed
    errors    "Connection is invalid. (-609)"
              "reported success but no output file was created"
    artefact  `B8 (1).pdf` - two conversions racing for one destination
    result    PowerPoint CRASHED into Microsoft Error Reporting

That is the operator's original bug report ("a powerpoint somehow crashed and I
got an error message"), and it is the leading explanation for the crash in the
2026-08-11 download matrix, which ran two audit lanes - i.e. two app instances.

A conversion is `open` -> `save active <doc>` -> `close`, which is
INDIVISIBLE: the other instance's `open` lands between our `open` and our
`save`, so we save and close ITS document.

Two things were wrong, and BOTH were needed:

1. the staged basename was the constant `src.<ext>`, so `our_document_test` -
   which identifies our document by NAME - answered "yes, mine" for the other
   instance's document too. The guard added for the data-loss defect was
   therefore blind to exactly this case, and `guard_trips` was 0 while both
   batches failed;
2. nothing serialised Office automation across processes.

After both fixes, the identical concurrent run gives 8/8 and 8/8, no stray
PDFs, and a PowerPoint that is still alive - with the second batch taking
roughly twice as long, which is the lock doing its job.
"""

from __future__ import annotations

import multiprocessing as mp
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import engine.applescript_bridge as AB  # noqa: E402


# --------------------------------------------------------------------------
# 1. the staged basename must be unique per conversion
# --------------------------------------------------------------------------

@pytest.fixture
def container(tmp_path, monkeypatch):
    root = tmp_path / "container"
    root.mkdir()
    monkeypatch.setattr(AB, "_office_container_tmp", lambda *a, **k: root)
    return root


def _stage_names(container, tmp_path, n: int):
    names = []
    for i in range(n):
        src = tmp_path / f"in{i}.pptx"
        src.write_bytes(b"x")
        with AB.office_container_stage(src, tmp_path / f"o{i}.pdf",
                                       "PowerPoint") as (s_src, s_dst):
            names.append((s_src.name, s_dst.name))
    return names


def test_two_conversions_never_stage_under_the_same_name(container, tmp_path):
    """The uuid used to live ONLY in the directory. `our_document_test`
    compares NAMES, so a constant basename makes two concurrent conversions
    indistinguishable - and the guard silently protects nothing."""
    names = _stage_names(container, tmp_path, 5)
    srcs = [a for a, _b in names]
    assert len(set(srcs)) == len(srcs), f"staged sources collide: {srcs}"
    dsts = [b for _a, b in names]
    assert len(set(dsts)) == len(dsts), f"staged destinations collide: {dsts}"


def test_the_staged_name_is_still_short(container, tmp_path):
    """Word fails past a ~255-byte TOTAL staged path and the container prefix
    already costs ~91, which is the whole reason the basename is not the real
    filename. Uniqueness must not be bought with length."""
    for src_name, dst_name in _stage_names(container, tmp_path, 3):
        assert len(src_name) <= 16, f"{src_name} is {len(src_name)} bytes"
        assert len(dst_name) <= 16, f"{dst_name} is {len(dst_name)} bytes"


def test_the_suffixes_survive_the_unique_token(container, tmp_path):
    """Office picks its importer from the source suffix and its exporter from
    the destination's - a token appended after the dot would change both."""
    src = tmp_path / "lecture.ppt"
    src.write_bytes(b"x")
    with AB.office_container_stage(src, tmp_path / "lecture.pdf",
                                   "PowerPoint") as (s_src, s_dst):
        assert s_src.suffix == ".ppt"
        assert s_dst.suffix == ".pdf"


def test_the_guard_distinguishes_two_staged_documents(container, tmp_path):
    """The property that actually matters: the AppleScript test built for one
    conversion must not match the other one's document."""
    names = _stage_names(container, tmp_path, 2)
    a = AB.our_document_test("PowerPoint", names[0][0])
    b = AB.our_document_test("PowerPoint", names[1][0])
    assert a != b, "both conversions built the SAME guard - it protects nothing"


# --------------------------------------------------------------------------
# 2. the cross-process lock
# --------------------------------------------------------------------------

def test_run_applescript_takes_the_lock():
    """It has to wrap the WHOLE of open/save/close - including the crash retry
    - so it lives on the one entry point every converter shares.

    Asserted through the AST, not a substring: the function's DOCSTRING names
    `_office_app_lock`, so a grep over its source passes even when the `with`
    statement has been deleted. That mutant survived the first version of this
    test - the same "scan code, not prose" trap this repo already documents.
    """
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(AB.run_applescript)).body[0]
    withs = [n for n in ast.walk(fn) if isinstance(n, ast.With)]
    assert any("_office_app_lock" in ast.unparse(item.context_expr)
               for w in withs for item in w.items), (
        "run_applescript does not hold the Office lock - two instances will "
        "interleave open/save/close against the one PowerPoint macOS gives us")


def _hold(app: str, seconds: float, started, done):
    sys.path.insert(0, str(REPO))
    import engine.applescript_bridge as ab
    with ab._office_app_lock(app):
        started.set()
        time.sleep(seconds)
    done.set()


@pytest.mark.skipif(sys.platform != "darwin", reason="flock path is macOS-only")
def test_the_lock_is_held_across_PROCESSES():
    """A threading lock would not help: the contention is between two separate
    Canvas Downloader processes driving one Office."""
    started, done = mp.Event(), mp.Event()
    p = mp.Process(target=_hold, args=("PowerPoint", 2.5, started, done))
    p.start()
    try:
        assert started.wait(20), "helper never acquired the lock"
        t0 = time.time()
        with AB._office_app_lock("PowerPoint"):
            waited = time.time() - t0
        assert waited > 0.5, (
            f"acquired the lock in {waited:.2f}s while another process held it "
            f"- the lock is not shared across processes")
    finally:
        p.join(timeout=30)
        if p.is_alive():
            p.terminate()


@pytest.mark.skipif(sys.platform != "darwin", reason="flock path is macOS-only")
def test_a_different_app_does_not_wait():
    """Per app, not global: Word in one instance must never block on
    PowerPoint in another."""
    started, done = mp.Event(), mp.Event()
    p = mp.Process(target=_hold, args=("PowerPoint", 2.5, started, done))
    p.start()
    try:
        assert started.wait(20)
        t0 = time.time()
        with AB._office_app_lock("Word"):
            waited = time.time() - t0
        assert waited < 0.5, f"Word waited {waited:.2f}s on PowerPoint's lock"
    finally:
        p.join(timeout=30)
        if p.is_alive():
            p.terminate()


def test_the_lock_is_a_no_op_off_macos(monkeypatch):
    """A macOS-only hazard must not add a failure mode on Windows.

    The platform check must be the FIRST thing the function does, before it
    reaches for `fcntl` or creates a lock file. Asserted structurally, because
    a timing assertion cannot see this: these tests run ON macOS, where
    deleting the gate changes nothing observable - the flock simply succeeds
    immediately and the run still finishes in microseconds. That mutant
    survived the first version of this test.
    """
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(AB._office_app_lock)).body[0]
    body = [n for n in fn.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    first = body[0]
    assert isinstance(first, ast.If) and "darwin" in ast.unparse(first.test), (
        "the platform gate must come first, before any fcntl import or lock "
        f"file, got: {ast.unparse(first)[:80]}")

    monkeypatch.setattr(AB.sys, "platform", "win32", raising=False)
    t0 = time.time()
    with AB._office_app_lock("PowerPoint"):
        pass
    assert time.time() - t0 < 0.5


def test_the_lock_never_blocks_a_run_forever():
    """Bounded on purpose. Proceeding after the timeout is exactly what the app
    did before this existed, so the degraded case is the old behaviour - not a
    stalled run, which would be worse than the bug."""
    assert 0 < AB._OFFICE_LOCK_TIMEOUT_S <= 600


@pytest.mark.skipif(sys.platform != "darwin", reason="flock path is macOS-only")
def test_a_dead_holder_cannot_wedge_every_future_run():
    """`flock` is chosen because the kernel drops it when the holder dies. A
    lock file with a hand-rolled pid/heartbeat could strand every later run
    behind a crashed instance - and a crashed instance is the very thing this
    is defending against."""
    started, done = mp.Event(), mp.Event()
    p = mp.Process(target=_hold, args=("Excel", 30, started, done))
    p.start()
    assert started.wait(20)
    p.terminate()
    p.join(timeout=20)
    t0 = time.time()
    with AB._office_app_lock("Excel"):
        waited = time.time() - t0
    assert waited < 3.0, f"a killed holder left the lock held for {waited:.1f}s"


def test_the_lock_survives_an_exception_in_the_body():
    """A conversion that raises must not keep the lock - the next file, and
    every other instance, would wait out the full timeout.

    NOTE, so nobody re-chases it: deleting the explicit ``LOCK_UN`` is an
    EQUIVALENT mutant and survives the mutation pass legitimately. The same
    ``finally`` closes the descriptor, and POSIX releases a flock when its last
    descriptor closes - so the unlock is belt-and-braces, not the mechanism.
    It is kept because it states the intent at the point of the guarantee, and
    because it still holds if the close ever moves.
    """
    with pytest.raises(RuntimeError):
        with AB._office_app_lock("Word"):
            raise RuntimeError("boom")
    t0 = time.time()
    with AB._office_app_lock("Word"):
        pass
    assert time.time() - t0 < 1.0, "the lock was not released on the error path"
