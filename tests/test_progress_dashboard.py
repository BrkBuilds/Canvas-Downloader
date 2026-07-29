"""Edge cases for the shared metrics row and progress bar.

These builders sit inside repaint loops that run while a download is in flight,
and several of the call sites are not wrapped in a try/except - so a cell that
raises does not mis-render a number, it takes the run's whole progress UI with
it. The values reaching them come from a dozen counters maintained by different
subsystems (the Canvas engine, the Panopto runner, the converters, the sync
executor), which is exactly the situation where "the caller will pass something
sensible" stops being true.

Every case here was found by probing the real builders, not imagined.
"""

import re

import pytest

from engine.progress_dashboard import (
    Metric, analysis_percent, build_metrics_row, build_progress_bar_html,
    build_terminal_html, metric_count, metric_elapsed, metric_speed,
    metric_transferred, metric_value, transfer_metrics,
)
from engine.estimation import transfer_estimator

MB = 1024 * 1024


def bar_width(html: str) -> str:
    m = re.search(r'width:([^;]+);height:100%', html)
    assert m, f"no fill width in {html!r}"
    return m.group(1)


# ── The progress bar ────────────────────────────────────────────────────────
#
# An out-of-range percent fails loudly wrong rather than slightly wrong: it goes
# straight into `width: N%`, and a negative or non-finite value is INVALID CSS,
# so the browser drops the declaration and a block div falls back to the full
# track. "Less than nothing happened" renders identically to "finished".

@pytest.mark.parametrize('value,expected', [
    (0, '0%'), (50, '50%'), (100, '100%'),
    (150, '100%'),              # would overflow its rounded track
    (-20, '0%'),                # invalid CSS -> full bar
    (float('nan'), '0%'),       # invalid CSS -> full bar
    (float('inf'), '0%'),
    (None, '0%'),
    ('55', '55%'),              # a string still has to render as a number
    (99.7, '99%'),
])
def test_bar_fill_is_always_a_drawable_percent(value, expected):
    assert bar_width(build_progress_bar_html(value)) == expected


def test_bar_label_defaults_to_the_clamped_percent():
    assert '>150%<' not in build_progress_bar_html(150)
    assert '100%' in build_progress_bar_html(150)


def test_indeterminate_bar_ignores_percent_entirely():
    html = build_progress_bar_html(-99, indeterminate=True, label='Searching…')
    assert 'cd-indeterminate-bar' in html
    assert 'Searching' in html


def test_bar_label_is_escaped():
    assert '<script>' not in build_progress_bar_html(10, label='<script>x</script>')


# ── The metrics row ─────────────────────────────────────────────────────────

def test_empty_row_renders_nothing_not_an_empty_card():
    """An empty raised box reads as a panel that failed to load."""
    assert build_metrics_row([]) == ''
    assert build_metrics_row(()) == ''


def test_row_escapes_value_and_suffix():
    html = build_metrics_row([Metric('<b>L</b>', '<i>V</i>', '<u>S</u>')])
    for raw in ('<b>', '<i>', '<u>'):
        assert raw not in html
    assert '&lt;b&gt;' in html


def test_row_survives_a_single_cell():
    assert build_metrics_row([metric_value('Type', 'PPTX → PDF')]).count('flex-direction:column') == 1


# ── Cells: no input can raise, and none can print a non-number ──────────────

@pytest.mark.parametrize('done,total,value,suffix', [
    (3, 5, '3', '/ 5'),
    (3.7, 5.2, '3', '/ 5'),
    (236, 233, '236', '/ 236'),        # denominator never below the numerator
    (0, 0, '0', ''),                   # "0 / 0" describes nothing
    (0, None, '0', ''),
    (None, 5, '0', '/ 5'),
    (3, float('nan'), '3', ''),
    (float('nan'), 5, '0', '/ 5'),
    (-4, 5, '0', '/ 5'),
])
def test_metric_count_tolerates_any_counter(done, total, value, suffix):
    m = metric_count('Files', done, total)
    assert (m.value, m.suffix) == (value, suffix)


@pytest.mark.parametrize('done,total,value,suffix', [
    (10 * MB, 100 * MB, '10.0', '/ 100.0 MB'),
    (0, 0, '0.0', 'MB'),               # a re-run with nothing to transfer
    (5 * MB, None, '5.0', 'MB'),
    (None, 100 * MB, '0.0', '/ 100.0 MB'),
    (float('inf'), 100 * MB, '0.0', '/ 100.0 MB'),
    (float('nan'), float('nan'), '0.0', 'MB'),
    (-1, 100 * MB, '0.0', '/ 100.0 MB'),
])
def test_metric_transferred_tolerates_any_counter(done, total, value, suffix):
    m = metric_transferred(done, total)
    assert (m.value, m.suffix) == (value, suffix)


@pytest.mark.parametrize('value,expected', [
    (5 * MB, '5.0'), (0, '0.0'), (None, '0.0'),
    (float('nan'), '0.0'), (float('inf'), '0.0'), (-1, '0.0'),
])
def test_metric_speed_tolerates_any_rate(value, expected):
    assert metric_speed(value).value == expected


@pytest.mark.parametrize('value,expected', [
    (0, '00:00'), (61, '01:01'), (3661, '1:01:01'),
    (None, '00:00'), (float('nan'), '00:00'), (-5, '00:00'),
])
def test_metric_elapsed_tolerates_any_clock(value, expected):
    assert metric_elapsed(value).value == expected


def test_transfer_metrics_never_raises_on_a_cold_estimator():
    row = transfer_metrics(transfer_estimator(), done_files=0, total_files=0,
                           done_bytes=0, total_bytes=0)
    assert [m.label for m in row] == ['Downloaded', 'Speed', 'Files', 'Time Remaining']
    assert row[-1].value == 'Estimating'
    assert build_metrics_row(row)


# ── The analysis bar must measure what the analysis row counts ──────────────

def test_analysis_bar_never_contradicts_the_course_count():
    """Regression: a 100% bar sitting above "COURSES 0 / 2".

    The scan hook reports the *sub-step's* ratio, which hits 1.0 many times per
    course. Passing it straight to the bar meant the card claimed the analysis
    was finished every time a module list was read.
    """
    # first course, its sub-step complete -> half of two courses, not all of it
    assert analysis_percent(0, 2, 5, 5) == 50
    assert analysis_percent(0, 2, 1, 4) == 12
    assert analysis_percent(1, 2, 2, 4) == 75
    assert analysis_percent(2, 2) == 100


def test_analysis_bar_is_monotonic_across_courses():
    seen = [analysis_percent(c, 3, s, 10) for c in range(3) for s in range(11)]
    assert seen == sorted(seen)
    assert seen[0] == 0 and seen[-1] == 100


@pytest.mark.parametrize('args', [
    (0, 0), (1, 0), (0, -2), (None, 2), (0, 2, None, None),
    (0, 2, 5, 0), (0, 2, float('nan'), 4), (0, 2, 9, 4),
])
def test_analysis_bar_survives_degenerate_denominators(args):
    assert 0 <= analysis_percent(*args) <= 100


# ── The terminal log ────────────────────────────────────────────────────────

def test_empty_log_shows_a_waiting_state_not_a_blank_well():
    assert 'Waiting for files' in build_terminal_html([])
    assert 'Waiting for files' in build_terminal_html(None or [])


def test_log_is_capped_so_a_long_run_cannot_grow_the_payload():
    html = build_terminal_html([f'<div>{i}</div>' for i in range(5000)])
    assert html.count('<div>') <= 210
