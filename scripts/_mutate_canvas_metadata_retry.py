"""Mutation pass for the Canvas metadata retry (fp:16e0de9e610a).

Every parameter in `_CANVAS_RETRY` is a decision, and most of them are decisions
AGAINST a default - `respect_retry_after_header` and `allowed_methods` in
particular. A test suite that only proved "a 502 is retried" would pass against
a configuration that also obeys a hostile Retry-After, replays POSTs, and
swallows the rate-limit signal the download path is watching for. So each mutant
here restores a plausible default or a plausible "simplification".

Restore is from an in-memory SNAPSHOT, never `git checkout`: this repo is
routinely worked by two sessions at once. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it changed underneath,
restoring nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_canvas_metadata_retry.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

CL = "core/canvas_logic.py"
TESTS = ["tests/test_canvas_metadata_retry.py"]
TEST_TARGET = TESTS

#: (label, file, old, new)
CANVAS_METADATA_RETRY_MUTANTS = [
    ("the retry is not mounted at all, i.e. the original defect",
     CL,
     "            _adapter = _CanvasTimeoutAdapter(max_retries=_CANVAS_RETRY)",
     "            _adapter = _CanvasTimeoutAdapter()"),

    ("urllib3 obeys the server's Retry-After again, so a hostile 86400 parks "
     "the app for a day",
     CL,
     "    respect_retry_after_header=False,",
     "    respect_retry_after_header=True,"),

    ("429 joins the forcelist, silently absorbing the rate-limit signal the "
     "download path handles deliberately",
     CL,
     "    status_forcelist=(502, 503, 504),",
     "    status_forcelist=(429, 502, 503, 504),"),

    ("502 drops out of the forcelist",
     CL,
     "    status_forcelist=(502, 503, 504),",
     "    status_forcelist=(503, 504),"),

    ("allowed_methods widened to the urllib3 default set, so a POST is replayed",
     CL,
     '    allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),',
     "    allowed_methods=None,"),

    ("read timeouts are retried, tripling the wall clock on the slow link the "
     "60s timeout exists for",
     CL,
     "    read=0,",
     "    read=3,"),

    # DOCUMENTED EQUIVALENT MUTANT - kept, not deleted, because the reasoning
    # is the useful part. `status=3` caps status retries INDEPENDENTLY of
    # `total`, so raising `total` alone changes nothing observable. Measured
    # against a real 502-always server:
    #     total=3  status=3  -> 4 requests, 3.02s   (shipped)
    #     total=50 status=3  -> 4 requests, 3.02s   (this mutant)
    #     total=50 status=50 -> HUNG                (genuinely unbounded)
    # So the two caps are belt-and-braces and the SECOND one is what bounds
    # this. A mutant spanning both would be caught - by the join timeout in
    # tests/test_canvas_metadata_retry.py, which exists because the first
    # version of that helper blocked instead of failing.
    ("the retry becomes effectively unbounded (EQUIVALENT - see above)",
     CL,
     "    total=3,\n    connect=0,",
     "    total=50,\n    connect=0,"),

    ("raise_on_status returns to its default, changing the error every "
     "downstream handler sees",
     CL,
     "    raise_on_status=False,",
     "    raise_on_status=True,"),

    ("connect retries come back, so an unreachable Canvas takes 3x longer to "
     "say so on the login path",
     CL,
     "    connect=0,",
     "    connect=2,"),

    ("the dropped-module report is removed, so a module that survives the "
     "retry vanishes silently again",
     CL,
     "        _unfetched = [n for n, its in _modules_items if its is None]",
     "        _unfetched = []"),

    ("the report fires on every scan, burying a real one in noise",
     CL,
     "        _unfetched = [n for n, its in _modules_items if its is None]",
     "        _unfetched = [n for n, its in _modules_items]"),
]


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; a checkout may be CRLF."""
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in CANVAS_METADATA_RETRY_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in CANVAS_METADATA_RETRY_MUTANTS:
        body = snapshot[rel]
        anchored = old.replace("\n", _nl_of(body))
        if anchored not in body:
            stale.append(f"{label!r} in {rel}")
        elif body.count(anchored) > 1:
            # The twin-anchor trap: replace(..., 1) takes whichever copy comes
            # FIRST, so the pass reports a result under a label that is a lie.
            stale.append(f"{label!r} in {rel} matches {body.count(anchored)}x "
                         f"- anchor it uniquely")
    if stale:
        print("STALE OR AMBIGUOUS ANCHORS - unmeasured, not passing:")
        for s in stale:
            print("  " + s)
        return 4

    print(f"baseline: running {len(TESTS)} test file(s)")
    if subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q"],
                      cwd=REPO).returncode != 0:
        print("BASELINE IS RED - fix that first")
        return 2

    caught, survived = [], []
    for label, rel, old, new in CANVAS_METADATA_RETRY_MUTANTS:
        current = _read(rel)
        if current != snapshot[rel]:
            print(f"\nABORT: {rel} changed underneath this pass (another "
                  f"session?). Nothing restored - the file on disk is THEIR edit.")
            return 3
        nl = _nl_of(current)
        old_nl, new_nl = old.replace("\n", nl), new.replace("\n", nl)
        if old_nl not in current:
            print(f"\nSTALE ANCHOR for {label!r} in {rel}")
            return 4

        _write(rel, current.replace(old_nl, new_nl, 1))
        assert _read(rel) != snapshot[rel], f"{label}: mutation changed nothing"
        try:
            rc = subprocess.run([sys.executable, "-m", "pytest", *TEST_TARGET,
                                 "-q", "-x", "--no-header",
                                 "-p", "no:cacheprovider"],
                                cwd=REPO, capture_output=True,
                                timeout=900).returncode
        except subprocess.TimeoutExpired:
            rc = 1          # a mutant that hangs the suite is one it noticed
        finally:
            _write(rel, snapshot[rel])
            assert _read(rel) == snapshot[rel], f"{rel}: RESTORE FAILED"
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(CANVAS_METADATA_RETRY_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
