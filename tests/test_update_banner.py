"""Tests for ui.update_banner's version comparison.

The regression this guards: parsing the two version strings through DIFFERENT
schemes (packaging.Version on one side, numeric tuple on the other) raised
TypeError on comparison, which was silently swallowed - the update banner
just never appeared again. ``_is_newer`` must never raise and must compare
both sides through the same scheme.
"""

from __future__ import annotations

import pytest

from ui.update_banner import _is_newer, _numeric_tuple


# ── The happy path ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "remote, local, expected",
    [
        ("2.0.1", "2.0.0", True),
        ("2.1.0", "2.0.9", True),
        ("3.0.0", "2.9.9", True),
        ("2.0.0", "2.0.0", False),   # equal -> no banner
        ("1.9.9", "2.0.0", False),   # local ahead (dev build) -> no banner
        ("2.0.0", "2.0.1", False),
    ],
)
def test_semver_ordering(remote, local, expected):
    assert _is_newer(remote, local) is expected


def test_prerelease_ordering_via_packaging():
    # packaging semantics: 2.1.0rc1 < 2.1.0
    assert _is_newer("2.1.0", "2.1.0rc1") is True
    assert _is_newer("2.1.0rc1", "2.1.0") is False


# ── The regression: mixed parseability must not raise ────────────────────────

@pytest.mark.parametrize(
    "remote, local",
    [
        ("2.1.0", "not-a-version"),
        ("not-a-version", "2.1.0"),
        ("release-2026-06", "2.0.0"),
        ("", "2.0.0"),
        ("2.0.0", ""),
        ("", ""),
    ],
)
def test_never_raises_on_malformed_input(remote, local):
    result = _is_newer(remote, local)  # must not raise TypeError/InvalidVersion
    assert isinstance(result, bool)


def test_mixed_parseability_still_compares_sanely():
    # One side malformed -> BOTH fall back to numeric tuples.
    assert _is_newer("2.1.0", "junk") is True      # (2,1,0) > (0,)
    assert _is_newer("junk", "2.1.0") is False     # (0,) < (2,1,0)


# ── Numeric-tuple fallback semantics ─────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2.1.0", (2, 1, 0)),
        ("v2.1.0-beta3", (2, 1, 0, 3)),
        ("no digits here", (0,)),
        ("", (0,)),
        (None, (0,)),
    ],
)
def test_numeric_tuple(raw, expected):
    assert _numeric_tuple(raw) == expected
