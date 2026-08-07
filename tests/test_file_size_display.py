"""``format_file_size`` is a DISPLAY CELL and is bound by the same rule as
``engine.progress_dashboard``'s metric builders: it may never raise, and it may
never render a non-number as though it were one.

It is the only such cell that lives outside that module (it sits in
``core.sync_manager``), which is why the hardening pass there never reached it -
while 18 render sites call it, several inside an ``@st.dialog`` where a raised
exception blanks the modal outright.

Two of the cases below are REACHABLE and were measured, not imagined:

* ``check_disk_space`` returns **-1** as its "could not determine" sentinel, and
  the Confirm Sync dialog fed it straight in. An unreachable drive rendered
  "Available Disk Space: **-1048576 B**".
* Canvas sizes are read with ``getattr(file_obj, 'size', 0)``, whose default
  only applies when the attribute is ABSENT - present-and-null yields None.
  ``core/canvas_logic.py`` writes ``... or 0`` at one ``original_size=`` site
  and not at the four others, so the codebase is already split on whether that
  can happen; a None reaching a manifest row comes back out of it.
"""
import pytest

from core.sync_manager import format_file_size
from shared.helpers import (
    DISK_SPACE_UNKNOWN, check_disk_space, format_available_space,
)


# ── It never raises, whatever it is handed ────────────────────────────────────

@pytest.mark.parametrize("value", [
    None, "", "not a number", [], {}, float("nan"),
    float("inf"), float("-inf"), -1, -1048576, True,
])
def test_never_raises_on_a_value_a_counter_could_hold(value):
    out = format_file_size(value)
    assert isinstance(out, str) and out


# ── It never PRINTS a negative or a non-number ────────────────────────────────

@pytest.mark.parametrize("value", [
    None, "x", float("nan"), float("inf"), float("-inf"), -1, -1048576,
])
def test_degrades_to_zero_rather_than_printing_nonsense(value):
    """"-1048576 B", "nan B" and "inf GB" are all worse than "0 B": each reads
    as a real measurement. Callers that need to say "unknown" test the sentinel
    themselves - see test_confirm_dialog_says_unknown_... below."""
    assert format_file_size(value) == "0 B"


def test_no_output_can_ever_start_with_a_minus():
    for v in range(-5_000_000, -4_999_990):
        assert not format_file_size(v).startswith("-")


# ── The ordinary contract is unchanged ────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (0, "0 B"),
    (1, "1 B"),
    (1023, "1023 B"),
    (1024, "1.0 KB"),
    (1536, "1.5 KB"),
    (1024 * 1024, "1.0 MB"),
    (5 * 1024 * 1024, "5.0 MB"),
    (1024 ** 3, "1.0 GB"),
    (3 * 1024 ** 3, "3.0 GB"),
])
def test_known_sizes_are_formatted_exactly_as_before(value, expected):
    assert format_file_size(value) == expected


def test_a_float_byte_count_is_not_printed_with_a_decimal():
    """Sub-KB values are whole bytes; "512.7 B" is noise, and a size that
    arrives as a float (a division result, a Panopto estimate) is common."""
    assert format_file_size(512.7) == "512 B"


def test_the_split_on_space_that_components_relies_on_still_works():
    """``shared/components.py`` does ``format_file_size(n).split(" ", 1)`` and
    indexes both halves, so every output must carry exactly one space."""
    for v in (0, 1, 1023, 1024, 1024 ** 2, 1024 ** 3, None, -1, float("nan")):
        parts = format_file_size(v).split(" ", 1)
        assert len(parts) == 2, v


# ── The sentinel that made this reachable ─────────────────────────────────────

def test_check_disk_space_really_does_return_the_minus_one_sentinel(tmp_path):
    """Guards the premise. If this helper ever stops using -1 for "unknown",
    the dialog's ``>= 0`` test below is testing nothing."""
    ok, avail_mb, total_mb = check_disk_space(r"Q:\no\such\drive", required_bytes=1)
    if avail_mb != -1:                       # a machine that really has Q:
        pytest.skip("drive Q: exists on this machine")
    assert (ok, avail_mb, total_mb) == (True, -1, -1)   # fail OPEN, unknown size


@pytest.mark.parametrize("unknown", [-1, -0.5, -12345, float("nan"), None, "x", []])
def test_an_unmeasured_volume_reads_as_unknown_not_as_a_number(unknown):
    """"0 B" is NOT an acceptable substitute: it reads as a completely full
    disk, which would make a user cancel a sync that had plenty of room."""
    assert format_available_space(unknown) == "Unknown"


@pytest.mark.parametrize("avail_mb,expected", [
    (0, "0 B"),                 # a real, genuinely full volume - not the sentinel
    (1, "1.0 MB"),
    (1536, "1.5 GB"),
    (68617.6171875, "67.0 GB"),
])
def test_a_real_measurement_still_formats_as_a_size(avail_mb, expected):
    assert format_available_space(avail_mb) == expected


def test_zero_and_the_sentinel_do_not_collapse_onto_the_same_text():
    """The whole point of the fix: they mean opposite things."""
    assert format_available_space(0) != format_available_space(DISK_SPACE_UNKNOWN)


def test_the_dialog_renders_through_that_one_function():
    """The dialog must not re-derive the sentinel test inline. It did once, and
    an inline copy is what let the raw -1 reach the markup in the first place;
    a copy also passes every test written against the helper."""
    import inspect
    import ui.sync_confirmation as sc

    src = inspect.getsource(sc.show_sync_confirmation_inner)
    assert "format_available_space(avail_mb)" in src
    assert "format_file_size(avail_bytes)" not in src


def test_the_sentinel_constant_matches_what_check_disk_space_actually_returns(
        tmp_path, monkeypatch):
    """Guards the premise, deterministically.

    An earlier version probed a bogus drive letter and SKIPPED when the answer
    was not -1 - which meant a drifted constant silently skipped instead of
    failing (it survived the mutation pass for exactly that reason). Forcing the
    error path is machine-independent and cannot skip.
    """
    import shutil as _shutil
    from shared import helpers as _h

    def _boom(_path):
        raise OSError("simulated: volume unreadable")

    monkeypatch.setattr(_shutil, "disk_usage", _boom)
    ok, avail_mb, total_mb = _h.check_disk_space(str(tmp_path), required_bytes=1)

    # Fails OPEN (never block a sync on a check that could not run) and reports
    # the size as the sentinel this module's renderer knows how to say.
    assert ok is True
    assert avail_mb == DISK_SPACE_UNKNOWN
    assert total_mb == DISK_SPACE_UNKNOWN
    assert format_available_space(avail_mb) == "Unknown"
