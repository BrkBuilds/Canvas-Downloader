"""Predicates that classify by matching text ANOTHER system produced.

This file exists because the same defect was found twice in one day, both live
on macOS 26.6.1:

* ``_classify_stderr`` matched ``"not authorized"`` (American) and the ASCII
  apostrophe, while macOS emits ``"Not authorised"`` and ``Can’t``. THREE of its
  four wording clauses were dead; only the numeric error codes beside them kept
  the verdicts right, and ``app_missing`` had no numeric companion, so a missing
  Office classified as non-fatal.
* the macOS folder picker matched ``"User canceled"`` (American) while macOS
  emits **"User cancelled."** - measured directly with
  ``osascript -e 'error number -128'``.

The rule this encodes: **a literal-text clause over a foreign message is
evidence about a WORDING, not about a CONDITION.** Keep the numeric/structured
companion as the real signal, and if a wording clause exists at all it must
match what the platform actually says - a dead clause is worse than none,
because it reads as coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import shared.helpers as H  # noqa: E402
from core.sync_manager import _is_locked_error  # noqa: E402

#: Exactly what macOS 26.6.1 printed for `osascript -e 'error number -128'`.
REAL_CANCEL = "0:17: execution error: User cancelled. (-128)"


# --------------------------------------------------------------------------
# the macOS folder picker: a cancel must read as a cancel
# --------------------------------------------------------------------------

def _run_multi_picker(monkeypatch, stderr: str, returncode: int = 1):
    """Drive the REAL picker with a canned osascript result."""
    import subprocess

    class _R:
        def __init__(self): self.returncode = returncode; self.stderr = stderr; self.stdout = ""

    monkeypatch.setattr(H.sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
    return H._mac_multi_folder_picker("/tmp")


def test_the_real_macos_cancel_string_reads_as_a_cancel(monkeypatch):
    """British spelling. The American-only clause was dead."""
    assert _run_multi_picker(monkeypatch, REAL_CANCEL) == [], (
        "macOS says 'User cancelled' with two Ls; a cancel that is not "
        "recognised returns None, and the caller answers None by opening a "
        "SECOND picker at someone who just pressed Cancel")


@pytest.mark.parametrize("stderr", [
    # WITHOUT the error number, or the number carries the case and the clause
    # under test is never exercised - which is how the first version of this
    # test let "drop the American spelling" survive the mutation pass.
    "execution error: User canceled.",
    "execution error: User canceled. (-128)",
])
def test_the_american_spelling_still_reads_as_a_cancel(monkeypatch, stderr):
    """Kept, because the point is to stop betting on ONE spelling."""
    assert _run_multi_picker(monkeypatch, stderr) == []


def test_the_wording_alone_is_enough_without_the_error_number(monkeypatch):
    """The number is the real signal; this proves the clause is not decoration.

    If the wording clause were dead again, this case would fall through to the
    failure path - which is exactly how the American-only version passed
    unnoticed for as long as `-128` kept appearing beside it.
    """
    assert _run_multi_picker(monkeypatch, "execution error: User cancelled.") == []


def test_a_genuine_failure_is_NOT_swallowed_as_a_cancel(monkeypatch):
    """The control: broadening the cancel test must not hide real errors."""
    out = _run_multi_picker(
        monkeypatch, "execution error: Application isn't running. (-600)")
    assert out is None, (
        "a real failure returned [] (\"user cancelled\"), so the caller would "
        "silently do nothing instead of falling back")


# --------------------------------------------------------------------------
# one lock predicate, not two spellings
# --------------------------------------------------------------------------

@pytest.mark.parametrize("msg", [
    "database is locked",            # SQLITE_BUSY
    "database table is locked",      # SQLITE_LOCKED - the one the narrow form missed
    "Database Is Locked",            # the narrow form was case-sensitive too
])
def test_every_sqlite_lock_message_is_recognised(msg):
    import sqlite3
    assert _is_locked_error(sqlite3.OperationalError(msg)) is True


@pytest.mark.parametrize("msg", [
    "no such table: sync_manifest",
    "disk I/O error",
    "file is not a database",
    "attempt to write a readonly database",
])
def test_a_non_lock_error_is_not_retried(msg):
    """Retrying a corrupt or read-only database is how a transient story turns
    into a data-loss story - see the sqlite corruption whitelist in CLAUDE.md."""
    import sqlite3
    assert _is_locked_error(sqlite3.OperationalError(msg)) is False


def test_no_site_spells_the_lock_rule_INLINE():
    """Twelve sites asked this in two spellings, one strictly narrower.

    Not a live defect - this app opens one short-lived connection per operation
    with no shared cache, so a contended write raises SQLITE_BUSY (reproduced).
    Fixed because a rule spelled twice is one some caller is already following
    an old version of.
    """
    import re
    src = (REPO / "core" / "sync_manager.py").read_text(encoding="utf-8")
    body = re.sub(r"#.*", "", src)          # a comment may DOCUMENT the spellings
    # the one legitimate occurrence is inside the predicate itself
    defn = body.index("def _is_locked_error")
    end = body.index("def _path_key")
    outside = body[:defn] + body[end:]
    for spelling in ("'locked' in str(", '"locked" in str(',
                     "'database is locked' in", '"database is locked" in'):
        assert spelling not in outside, (
            f"{spelling!r} is spelled inline again instead of asking "
            f"_is_locked_error - that is how the two versions drifted apart")


def test_the_predicate_is_actually_USED():
    """A definition nothing calls would make the test above vacuous."""
    src = (REPO / "core" / "sync_manager.py").read_text(encoding="utf-8")
    assert src.count("_is_locked_error(e)") >= 10, (
        "the lock sites stopped asking the shared predicate")
