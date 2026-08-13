"""Every mutation anchor still resolves - so a stale one fails the SUITE.

WHY THIS EXISTS. `scripts/_mutate_office_guard.py` mutates by literal string
replacement, and a mutant whose `old` text is no longer in the source cannot
run. That is not hypothetical:

    f6caf04  writes the concurrency mutation set, "8/9 caught"
    70ce78c  inserts `_note_office_preexisting(app_name)` between
             `with _office_app_lock(app_name):` and `return _run_applescript_locked(`
    ...      nobody re-runs the concurrency set

From `70ce78c` onward "run_applescript stops taking the lock" could not run on
any platform, while the score recorded in `tests/audit/MAC_OFFICE_FIXES.md`
still said 8/9. The quit set WAS re-anchored in the same window (`7a2a674`), so
this is a rot that happens to one set at a time and is invisible unless someone
re-runs the pass.

The harness does print `!! ANCHOR MISSING` and counts it as a survivor, which is
the right behaviour - but only for whoever runs it. The mutation pass is a
deliberate, occasional act; the suite runs constantly. Putting the check here is
what makes an invalidated anchor a failure at the moment the code moves, in the
same commit that moved it.

WHAT THIS DOES NOT DO: it does not run the mutants, and it is not a substitute
for the pass. An anchor can resolve and the mutant still survive. This only
guarantees that a recorded score describes mutants that could actually run.

The harness is imported by PATH, not as a package module, because `scripts/` is
not one and because the file is explicitly a throwaway that ships beside the
tests it verifies rather than as library code.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "scripts" / "_mutate_office_guard.py"


def _harness():
    spec = importlib.util.spec_from_file_location("_mutate_office_guard", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _all_sets(mod):
    """(set name, mutants) for every mutant list the harness exposes.

    Discovered by NAME rather than listed here: a new `*_MUTANTS` set added for
    the next fix has to be covered without anyone remembering to extend this
    file, which is the same failure mode the module docstring is about.
    """
    return [(name, getattr(mod, name)) for name in sorted(dir(mod))
            if name.endswith("MUTANTS") and isinstance(getattr(mod, name), list)]


def test_the_harness_still_imports():
    mod = _harness()
    assert _all_sets(mod), "no mutant sets found - has the harness been renamed?"


@pytest.mark.parametrize("set_name", [n for n, _ in _all_sets(_harness())])
def test_every_anchor_in_this_set_resolves(set_name):
    mod = _harness()
    mutants = getattr(mod, set_name)
    assert mutants, f"{set_name} is empty"
    stale = []
    for label, rel, old, _new in mutants:
        src = (REPO / rel).read_text(encoding="utf-8")
        if old not in src:
            stale.append(f"{label!r} -> {rel}")
    assert not stale, (
        f"{len(stale)} anchor(s) in {set_name} no longer match their source, so "
        f"those mutants CANNOT RUN and any recorded score for this set is "
        f"stale. Re-anchor them on the current code (and re-run the pass - an "
        f"anchor that resolves is not the same as a mutant that is caught):\n  "
        + "\n  ".join(stale))


@pytest.mark.parametrize("set_name", [n for n, _ in _all_sets(_harness())])
def test_every_mutant_actually_changes_the_source(set_name):
    """`old != new`, and the replacement is not already what the file says.

    A mutant whose `new` text is present verbatim in the source would be a
    no-op the runner reports as SURVIVED, which reads as a missing test rather
    than as a broken mutant.
    """
    mod = _harness()
    for label, rel, old, new in getattr(mod, set_name):
        assert old != new, f"{label}: the mutant does not change anything"
        src = (REPO / rel).read_text(encoding="utf-8")
        if old in src:
            assert src.replace(old, new, 1) != src, (
                f"{label}: applying the mutant leaves the file unchanged")


def test_every_target_file_exists():
    mod = _harness()
    for _name, mutants in _all_sets(mod):
        for label, rel, _old, _new in mutants:
            assert (REPO / rel).is_file(), f"{label}: {rel} does not exist"


def test_every_named_test_file_exists():
    """A mutant set pointed at a deleted test file would report every mutant as
    caught - pytest exits non-zero on a missing path, which the runner reads as
    a failure, i.e. as the mutant having been detected."""
    mod = _harness()
    for attr in sorted(dir(mod)):
        if not attr.endswith("TEST"):
            continue
        value = getattr(mod, attr)
        if not isinstance(value, str):
            continue
        for part in value.split():
            assert (REPO / part).exists(), f"{attr} names a missing path: {part}"
