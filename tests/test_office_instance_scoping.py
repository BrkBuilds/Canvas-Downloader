"""A staging marker that means "some Canvas Downloader" is not an ownership proof.

`_CANVAS_TMP_MARKER` is baked into every staged conversion path, and two places
treat a match as licence to act destructively: `_idle_quit_script` (a document
carrying it is `pristine`, so the quit goes out `saving no`) and
`_close_marker_docs_script`. With two instances live, one lane's teardown read
the OTHER lane's in-flight staged conversion as ours-and-discardable, quit,
waited 12 s, then pkilled the app mid-conversion - measured 0.77 s from one
lane's force-terminate to the other's -609, corrupting five rows and producing
12 false HIGH findings.

REACHABILITY, stated because a severity inflated by an unreachable consequence
survives on every machine that reads this: `start.py` holds a real flock/mutex
so a second GUI cannot launch, and conversions within one instance are strictly
sequential. This is a multi-instance ROBUSTNESS gap - it blocks the audit
harness, which runs five instances by design - NOT a user-facing defect.

The fix is one distinction, and this file exists to stop it being collapsed
back: the two DESTRUCTIVE sites ask "is this MINE", the Recents purge asks "is
this ANY Canvas Downloader's". They look like the same question and they are
not, and merging them breaks whichever one you did not have in mind - a stale
Recents row is inert, a wrongly-closed document is not.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from engine.applescript_bridge import (
    _CANVAS_TMP_MARKER, _INSTANCE_MARKER, _INSTANCE_TOKEN,
)

SRC = Path("engine/applescript_bridge.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)

#: The two questions, and who is allowed to ask which.
NARROW_ONLY = ("_idle_quit_script", "_close_marker_docs_script")
BROAD_ONLY = ("_marker_in_value", "_purge_securebookmarks")


def _func(name: str) -> ast.FunctionDef:
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{name} not found - was it renamed?")


def _names_in(name: str) -> set[str]:
    return {n.id for n in ast.walk(_func(name)) if isinstance(n, ast.Name)}


# ------------------------------------------------------------ the marker

def test_the_instance_marker_is_a_strict_extension_of_the_broad_one():
    """The Recents purge matches by substring, so the broad marker must remain a
    PREFIX or a crashed run's entries become unreachable - and nothing else in
    the app would ever clean them up."""
    assert _INSTANCE_MARKER.startswith(_CANVAS_TMP_MARKER)
    assert _INSTANCE_MARKER != _CANVAS_TMP_MARKER


def test_the_token_carries_no_path_separator():
    """THE reason the token is in the directory NAME rather than a path segment.

    Word reports an HFS COLON path (`Macintosh HD:Users:...`) while the other
    apps report POSIX, so a token separated by `/` could never match for Word -
    the same trap that made the old `full name contains "/"` fallback dead code
    for Word. A name-embedded token contains no separator, so ONE substring test
    works in both spellings.
    """
    for bad in ("/", ":", "\\", " "):
        assert bad not in _INSTANCE_TOKEN, f"token contains {bad!r}"
    assert re.fullmatch(r"[0-9a-f]{8}", _INSTANCE_TOKEN)


def test_the_token_is_stable_within_the_process():
    from engine.applescript_bridge import _INSTANCE_MARKER as again
    assert again == _INSTANCE_MARKER, (
        "a marker that moves mid-run would orphan the paths already staged "
        "under the old one")


# ----------------------------------------------------- who asks which

@pytest.mark.parametrize("fn", NARROW_ONLY)
def test_the_destructive_sites_ask_only_about_THIS_instance(fn):
    names = _names_in(fn)
    assert "_INSTANCE_MARKER" in names, (
        f"{fn} no longer scopes to this instance - it can close or quit a "
        f"document another Canvas Downloader is converting")
    assert "_CANVAS_TMP_MARKER" not in names, (
        f"{fn} asks the BROAD question. That is the defect: 'some Canvas "
        f"Downloader owns this' is not 'I own this'.")


@pytest.mark.parametrize("fn", BROAD_ONLY)
def test_the_recents_purge_still_asks_about_ANY_instance(fn):
    names = _names_in(fn)
    assert "_CANVAS_TMP_MARKER" in names, (
        f"{fn} narrowed to this instance, so entries left by a crashed or "
        f"earlier run can never be purged - nothing else removes them")
    assert "_INSTANCE_MARKER" not in names


# ------------------------------------------------------------ the kill

def test_the_force_terminate_signals_inside_the_lock():
    """Killing the app another instance is mid-conversion with is the most
    destructive act available. It used to run outside the lock on the reasoning
    that signalling is not driving - true, and beside the point."""
    fn = _func("_terminate_gallery_stuck")
    kills = [n for n in ast.walk(fn)
             if isinstance(n, ast.Constant) and n.value in ("pkill", "pgrep")]
    assert kills, "pgrep/pkill escalation is gone - was it renamed?"

    withs = [w for w in ast.walk(fn) if isinstance(w, ast.With)]
    guarded = [k for k in kills
               if any(w.lineno <= k.lineno <= (w.end_lineno or w.lineno)
                      and "_office_app_lock" in ast.dump(w) for w in withs)]
    assert len(guarded) == len(kills), (
        "a pgrep/pkill sits outside the per-app Office lock")


# ---------------------------------------------------------- the sweep

def test_the_staging_sweep_can_only_remove_EMPTY_directories():
    """A per-process staging dir means dead runs leave siblings behind, so they
    are swept. `rmdir` only: a NON-empty sibling belongs to a live instance
    mid-conversion, or holds a crashed run's evidence, and removing either is
    the exact damage this whole change is about."""
    fn = _func("_office_container_tmp")
    body = ast.dump(fn)
    assert "rmdir" in body, "the sweep is gone - staging dirs will accumulate"
    assert "rmtree" not in body, (
        "the sweep uses rmtree - that deletes a live instance's staged "
        "conversion, which is worse than the leak it fixes")
