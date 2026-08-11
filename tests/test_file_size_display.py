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


# ═══════════════════════════════════════════════════════════════════════════
# THE SAME SENTINEL, ONE SCREEN LATER: the bar and the warning (2026-08-11)
#
# `format_available_space` fixed what the Confirm Sync dialog PRINTS. The
# arithmetic beside it still could not tell three cases apart, and two of them
# were wrong:
#
#   * a volume that was never measured (the -1 sentinel) got the 1% floor, so an
#     offline share drew a bar - and the code's own comment claimed the maths
#     "suppresses the bar instead of drawing a false one";
#   * a genuinely FULL volume also got the 1% floor, because the ratio was gated
#     on `avail_bytes > 0`. Measured on the dialog's own expression: 0.4 MB free
#     warned, 0 B free did NOT. The one case the "your disk is getting full"
#     notice exists for was the only one it could not reach.
#
# `ui/sync_review.py` blocks a full volume before the dialog is reached (it
# demands 1 GB), so that half is belt-and-braces; the unmeasured half is not.
# ═══════════════════════════════════════════════════════════════════════════

MB = 1024 * 1024


def test_an_unmeasured_volume_draws_no_bar_and_no_warning():
    from shared.helpers import disk_fill_percent
    assert disk_fill_percent(500 * MB, -1) is None, \
        "None is what lets the caller draw nothing; 0 would be a claim"


def test_a_full_volume_is_the_most_severe_case_not_the_least():
    from shared.helpers import disk_fill_percent
    assert disk_fill_percent(500 * MB, 0) == 100.0


def test_a_nearly_full_volume_still_warns():
    """The neighbour that always worked - it must not regress while fixing 0."""
    from shared.helpers import disk_fill_percent
    assert disk_fill_percent(500 * MB, 0.4) == 100.0


def test_the_linear_middle_is_unchanged():
    from shared.helpers import disk_fill_percent
    assert disk_fill_percent(500 * MB, 600) == pytest.approx(83.33, abs=0.01)


def test_a_tiny_run_keeps_its_1_percent_floor():
    """The floor exists so a small download is still visible; it must survive."""
    from shared.helpers import disk_fill_percent
    assert disk_fill_percent(1024, 50000) == 1.0


def test_nothing_to_transfer_is_zero_not_the_floor():
    from shared.helpers import disk_fill_percent
    assert disk_fill_percent(0, 50000) == 0.0


@pytest.mark.parametrize("avail", [None, float('nan'), 'x', -2, float('-inf')])
def test_any_unusable_availability_reads_as_unmeasured(avail):
    """It runs inside a dialog, where a raise blanks the modal - the same rule
    `format_file_size` follows in this file."""
    from shared.helpers import disk_fill_percent
    assert disk_fill_percent(500 * MB, avail) is None


@pytest.mark.parametrize("total", [None, float('nan'), 'x'])
def test_an_unusable_total_reads_as_unmeasured_too(total):
    from shared.helpers import disk_fill_percent
    assert disk_fill_percent(total, 50000) is None


def test_the_dialog_calls_the_helper_rather_than_re_deriving_it():
    """The whole reason this is a named function.

    `format_available_space`'s own history: "The first version of the test
    re-implemented the dialog's expression instead of calling it, and two
    mutations survived because of it."
    """
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "ui" / "sync_confirmation.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert 'disk_fill_percent' in called
    # and the old inline arithmetic is gone, so there is nothing to drift from
    assert 'real_ratio' not in src and 'real_pct' not in src
