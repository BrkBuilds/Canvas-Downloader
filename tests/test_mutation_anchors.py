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


def _harness_paths():
    """Every mutation harness in scripts/, discovered by FILENAME.

    Discovered rather than listed for the same reason `_all_sets` discovers by
    name: the harness written for the next fix has to be covered without anyone
    remembering to extend this file, and "nobody re-runs it" is precisely the
    rot this module exists to catch. Sorted so parametrize ids are stable.
    """
    return sorted(REPO.glob("scripts/_mutate_*.py"))


def _load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _all_sets(mod):
    """(set name, mutants) for every mutant list a harness exposes.

    Discovered by NAME rather than listed here: a new `*_MUTANTS` set added for
    the next fix has to be covered without anyone remembering to extend this
    file, which is the same failure mode the module docstring is about.
    """
    return [(name, getattr(mod, name)) for name in sorted(dir(mod))
            if name.endswith("MUTANTS") and isinstance(getattr(mod, name), list)]


def _every_set():
    """(harness stem, set name) for every mutant set in every harness."""
    out = []
    for path in _harness_paths():
        for name, _mutants in _all_sets(_load(path)):
            out.append((path.stem, name))
    return out


def _mutants_of(stem, set_name):
    path = next(p for p in _harness_paths() if p.stem == stem)
    return getattr(_load(path), set_name)


def test_every_harness_still_imports():
    paths = _harness_paths()
    assert paths, "no mutation harnesses found in scripts/"
    for path in paths:
        assert _all_sets(_load(path)), (
            f"{path.name} exposes no mutant sets - has one been renamed?")


@pytest.mark.parametrize("stem,set_name", _every_set())
def test_every_anchor_in_this_set_resolves(stem, set_name):
    mutants = _mutants_of(stem, set_name)
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


@pytest.mark.parametrize("stem,set_name", _every_set())
def test_every_mutant_actually_changes_the_source(stem, set_name):
    """`old != new`, and the replacement is not already what the file says.

    A mutant whose `new` text is present verbatim in the source would be a
    no-op the runner reports as SURVIVED, which reads as a missing test rather
    than as a broken mutant.
    """
    for label, rel, old, new in _mutants_of(stem, set_name):
        assert old != new, f"{label}: the mutant does not change anything"
        src = (REPO / rel).read_text(encoding="utf-8")
        if old in src:
            assert src.replace(old, new, 1) != src, (
                f"{label}: applying the mutant leaves the file unchanged")


def test_every_target_file_exists():
    for stem, set_name in _every_set():
        for label, rel, _old, _new in _mutants_of(stem, set_name):
            assert (REPO / rel).is_file(), f"{label}: {rel} does not exist"


def test_every_named_test_file_exists():
    """A mutant set pointed at a deleted test file would report every mutant as
    caught - pytest exits non-zero on a missing path, which the runner reads as
    a failure, i.e. as the mutant having been detected."""
    for path in _harness_paths():
        mod = _load(path)
        for attr in sorted(dir(mod)):
            if not (attr.endswith("TEST") or attr.endswith("TESTS")
                    or attr == "TEST_TARGET"):
                continue
            value = getattr(mod, attr)
            parts = ([value] if isinstance(value, str)
                     else value if isinstance(value, list) else [])
            for entry in parts:
                if not isinstance(entry, str):
                    continue
                for part in entry.split():
                    assert (REPO / part).exists(), (
                        f"{path.name}:{attr} names a missing path: {part}")
