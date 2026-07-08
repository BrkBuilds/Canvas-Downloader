"""Tests for ui.update_banner's version comparison and dismissal persistence.

The regression this guards: parsing the two version strings through DIFFERENT
schemes (packaging.Version on one side, numeric tuple on the other) raised
TypeError on comparison, which was silently swallowed - the update banner
just never appeared again. ``_is_newer`` must never raise and must compare
both sides through the same scheme.

The dismissal tests guard the "closeable, reappears on the next version bump"
contract: dismissing a release must persist to disk (survives a process
restart) and must only suppress that exact version - a newer tag un-dismisses.
"""

from __future__ import annotations

import json

import pytest

import ui.update_banner as update_banner
from shared import helpers
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


# ── Dismissal persistence ─────────────────────────────────────────────────────

@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    """Point the dismissal file at an isolated temp config dir.

    update_banner resolves the path via ``shared.helpers.get_config_dir()`` at
    call time (function-local import), so patching the attribute on
    shared.helpers is sufficient and leaks nothing across tests.
    """
    monkeypatch.setattr(helpers, "get_config_dir", lambda: str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_dismiss_globals():
    """Dismissal state is cached on module globals for the process lifetime
    (loaded from disk once); reset so tests don't leak into each other."""
    update_banner._dismissed_loaded = False
    update_banner._dismissed_version = None
    yield
    update_banner._dismissed_loaded = False
    update_banner._dismissed_version = None


def test_not_dismissed_when_no_file_exists(config_dir):
    assert update_banner._is_dismissed("2.4.0") is False


def test_dismiss_then_is_dismissed_for_same_version(config_dir):
    update_banner._dismiss_version("2.4.0")
    assert update_banner._is_dismissed("2.4.0") is True


def test_newer_version_is_not_dismissed(config_dir):
    update_banner._dismiss_version("2.4.0")
    assert update_banner._is_dismissed("2.5.0") is False


def test_dismissal_persists_to_disk(config_dir):
    update_banner._dismiss_version("2.4.0")
    with open(update_banner._dismiss_state_path(), encoding="utf-8") as f:
        assert json.load(f) == {"dismissed_version": "2.4.0"}
    assert not (config_dir / "update_banner_dismissed.json.tmp").exists()


def test_dismissal_survives_a_fresh_process(config_dir):
    """Simulates an app restart: a fresh call re-reads from disk instead of
    relying on the in-memory cache from the process that wrote it."""
    update_banner._dismiss_version("2.4.0")
    update_banner._dismissed_loaded = False
    update_banner._dismissed_version = None
    assert update_banner._is_dismissed("2.4.0") is True


@pytest.mark.parametrize("garbage", ["{not json", '"a string"', "[1,2,3]", ""])
def test_corrupt_dismissal_file_degrades_to_not_dismissed(config_dir, garbage):
    config_dir.joinpath("update_banner_dismissed.json").write_text(garbage, encoding="utf-8")
    assert update_banner._is_dismissed("2.4.0") is False
