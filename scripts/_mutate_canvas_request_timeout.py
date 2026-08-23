"""Mutation pass for the Canvas request timeout (fp:b7f2093c6e14).

The defect being guarded against is one word: `setdefault` instead of an
`is None` test. It survived from 2026-05-21 to 2026-08-23 because it LOOKS
right - "supply a default if none was given" is exactly the intent, and
`setdefault` is exactly how you write that everywhere except an adapter, where
requests has already put the key there with value None.

So the first mutant is that word, and the rest are the plausible
"simplifications" someone would reach for while tidying this up: dropping the
env override, dropping the defensive parse, zeroing the connect half, or
letting a caller's explicit timeout be overridden.

Restore is from an in-memory SNAPSHOT, never `git checkout`: this repo is
routinely worked by two sessions at once. Before every mutant the target is
compared against its snapshot and the pass ABORTS if it changed underneath,
restoring nothing, because at that point the file on disk is their edit.

    python scripts/_mutate_canvas_request_timeout.py
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

CL = "core/canvas_logic.py"
TESTS = ["tests/test_canvas_request_timeout.py"]
TEST_TARGET = TESTS

#: (label, file, old, new)
CANVAS_REQUEST_TIMEOUT_MUTANTS = [
    ("the original defect verbatim: setdefault, which is a no-op because "
     "requests always passes timeout=None explicitly",
     CL,
     "        if kwargs.get('timeout') is None:\n"
     "            kwargs['timeout'] = (_CONNECT_TIMEOUT_SECONDS, _read_timeout_seconds())",
     "        kwargs.setdefault('timeout', (_CONNECT_TIMEOUT_SECONDS, "
     "_read_timeout_seconds()))"),

    ("the presence test replaces the is-None test, which is the same no-op "
     "wearing different clothes",
     CL,
     "        if kwargs.get('timeout') is None:",
     "        if 'timeout' not in kwargs:"),

    ("the injection is removed entirely, so nothing bounds a stalled read",
     CL,
     "        if kwargs.get('timeout') is None:\n"
     "            kwargs['timeout'] = (_CONNECT_TIMEOUT_SECONDS, _read_timeout_seconds())",
     "        pass"),

    ("the adapter OVERRIDES a caller's explicit timeout instead of supplying "
     "a default",
     CL,
     "        if kwargs.get('timeout') is None:\n"
     "            kwargs['timeout'] = (_CONNECT_TIMEOUT_SECONDS, _read_timeout_seconds())",
     "        kwargs['timeout'] = (_CONNECT_TIMEOUT_SECONDS, _read_timeout_seconds())"),

    ("the connect half goes to zero, which requests reads as 'fail "
     "immediately' and which also invalidates _CANVAS_RETRY's connect=0 note",
     CL,
     "_CONNECT_TIMEOUT_SECONDS = 15",
     "_CONNECT_TIMEOUT_SECONDS = 0"),

    ("the read timeout becomes None, i.e. wait for ever - the exact hang this "
     "class exists to prevent, reintroduced through the constant",
     CL,
     "_DEFAULT_READ_TIMEOUT_SECONDS = 60",
     "_DEFAULT_READ_TIMEOUT_SECONDS = None"),

    ("the defensive env parse reverts to a bare int(), so CANVAS_TIMEOUT=abc "
     "raises out of send() and breaks every Canvas API call",
     CL,
     "    raw = os.environ.get('CANVAS_TIMEOUT')\n"
     "    if raw is None:\n"
     "        return _DEFAULT_READ_TIMEOUT_SECONDS\n"
     "    try:\n"
     "        val = int(float(str(raw).strip()))\n"
     "    except (TypeError, ValueError):\n"
     "        return _DEFAULT_READ_TIMEOUT_SECONDS\n"
     "    return val if val > 0 else _DEFAULT_READ_TIMEOUT_SECONDS",
     "    return int(os.environ.get('CANVAS_TIMEOUT', _DEFAULT_READ_TIMEOUT_SECONDS))"),

    ("a non-positive CANVAS_TIMEOUT is honoured, so CANVAS_TIMEOUT=0 makes "
     "every request fail instantly",
     CL,
     "    return val if val > 0 else _DEFAULT_READ_TIMEOUT_SECONDS",
     "    return val"),

    ("the env override is dropped, so the documented escape hatch for a slow "
     "Canvas silently stops working",
     CL,
     "    raw = os.environ.get('CANVAS_TIMEOUT')",
     "    raw = None"),

    ("the adapter is mounted on https only, so an http Canvas URL is unbounded",
     CL,
     "            canvas._Canvas__requester._session.mount('http://', _adapter)",
     "            pass"),
]


def _read(rel: str) -> str:
    return io.open(REPO / rel, encoding="utf-8", newline="").read()


def _write(rel: str, body: str) -> None:
    io.open(REPO / rel, "w", encoding="utf-8", newline="").write(body)


def _nl_of(body: str) -> str:
    """Anchors are written with ``\\n``; a checkout may be CRLF."""
    return "\r\n" if "\r\n" in body else "\n"


def main() -> int:
    files = sorted({m[1] for m in CANVAS_REQUEST_TIMEOUT_MUTANTS})
    snapshot = {rel: _read(rel) for rel in files}

    stale = []
    for label, rel, old, _new in CANVAS_REQUEST_TIMEOUT_MUTANTS:
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
        print("STALE OR AMBIGUOUS ANCHORS - these mutants could not run "
              "correctly, so any score recorded for them is UNMEASURED:")
        for s in stale:
            print("  " + s)
        return 4

    print(f"baseline: running {len(TESTS)} test file(s)")
    if subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q"],
                      cwd=REPO).returncode != 0:
        print("BASELINE IS RED - fix that first")
        return 2

    caught, survived = [], []
    for label, rel, old, new in CANVAS_REQUEST_TIMEOUT_MUTANTS:
        current = _read(rel)
        if current != snapshot[rel]:
            print(f"\nABORT: {rel} changed underneath this pass (another "
                  f"session?). Nothing restored - the file on disk is THEIR "
                  f"edit, not a mutant.")
            return 3
        nl = _nl_of(current)
        old_nl, new_nl = old.replace("\n", nl), new.replace("\n", nl)
        if old_nl not in current:
            print(f"\nSTALE ANCHOR for {label!r} in {rel} - cannot run it")
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
            # A mutant that hangs the suite is one the suite noticed - and this
            # set can genuinely produce one, since half of it removes timeouts.
            rc = 1
        finally:
            _write(rel, snapshot[rel])
            assert _read(rel) == snapshot[rel], f"{rel}: RESTORE FAILED"
        (caught if rc != 0 else survived).append(label)
        print(f"  [{'CAUGHT ' if rc != 0 else 'SURVIVED'}] {label}")

    print(f"\n{len(caught)}/{len(CANVAS_REQUEST_TIMEOUT_MUTANTS)} caught")
    for s in survived:
        print(f"  SURVIVED: {s}")
    return 0 if not survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
