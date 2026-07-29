"""Tests for engine.estimation - the shared time-remaining model.

These are behavioural tests against scripted runs, not unit tests of the
algebra: what matters is that the number on screen is roughly right, appears
immediately, and survives the things that actually happen during a download
(a zero-byte opening phase, Streamlit reruns between courses, a freeze).

Every regression guarded here was a real defect found while building the model:
an unconserved fit that was 2x out on collinear work, a per-repaint smoothing
factor that made accuracy depend on how chatty the screen was, completions on a
bin boundary being dropped, and a trailing-interval bias that read a 9 s/unit
phase as anything from 9 s to 18 s depending on when you looked.
"""

import pytest

from engine.estimation import (
    MB, ProgressEstimator, format_duration, stepwise_estimator, transfer_estimator,
)


# ── Harness ─────────────────────────────────────────────────────────────────

class Run:
    """Drives an estimator through a scripted run on a synthetic clock."""

    def __init__(self, est=None, *, units_total=0.0, bytes_total=0.0):
        self.est = est or transfer_estimator()
        self.t = 10_000.0
        self.units = 0.0
        self.bytes = 0.0
        self.units_total = units_total
        self.bytes_total = bytes_total
        self._painted = self.t
        self._sync()

    def _sync(self):
        self.est.update(units_done=self.units, bytes_done=self.bytes,
                        units_total=self.units_total, bytes_total=self.bytes_total,
                        now=self.t)
        # The dashboards repaint on a ~0.4 s throttle, and that is what drives
        # the display smoothing - so the harness has to do it too.
        if self.t - self._painted >= 0.4:
            self._painted = self.t
            self.est.eta_seconds(now=self.t)

    def advance(self, seconds, *, units=0.0, bytes=0.0, steps=1):
        """Do ``units``/``bytes`` worth of work spread over ``seconds``."""
        for _ in range(steps):
            self.t += seconds / steps
            self.units += units / steps
            self.bytes += bytes / steps
            self._sync()

    def idle(self, seconds, steps=None):
        """Wall-clock passes with repaints but no progress."""
        self.advance(seconds, steps=steps or max(1, int(seconds / 0.5)))

    def jump(self, seconds):
        """A gap with no repaints at all - a Streamlit rerun between courses."""
        self.t += seconds
        self._sync()

    @property
    def eta(self):
        return self.est.eta_seconds(now=self.t)

    @property
    def text(self):
        return self.est.eta_text(now=self.t)


def transfer(run, files, size_each, rate, overhead=0.2):
    """Download ``files`` files of ``size_each`` bytes at ``rate`` bytes/s."""
    for _ in range(files):
        run.advance(overhead)
        run.advance(size_each / rate, bytes=size_each, steps=6)
        run.advance(0.0, units=1)


# ── Formatting ──────────────────────────────────────────────────────────────

def test_format_duration_none_is_estimating():
    assert format_duration(None) == "Estimating"


def test_format_duration_pads_minutes_and_seconds():
    assert format_duration(0) == "00:00"
    assert format_duration(65) == "01:05"


def test_format_duration_switches_to_hours_clock():
    """strftime('%M:%S') on 90 minutes silently prints 30:00 - an hour short."""
    assert format_duration(90 * 60) == "1:30:00"
    assert format_duration(3599) == "59:59"


def test_format_duration_marks_approximate():
    assert format_duration(90, approximate=True) == "~01:30"


# ── The reported bug: no number for the first 90 seconds ────────────────────

def test_eta_is_available_before_any_bytes_move():
    """The原 failure: 26 zero-byte items, one and a half minutes of "Estimating".

    Totals are known from the scan, so an estimate is always possible - the old
    model just had no way to express one without a byte sample.
    """
    run = Run(units_total=167, bytes_total=849 * MB)
    assert run.text != "Estimating"
    assert run.eta > 0


def test_eta_is_estimating_only_when_nothing_is_known():
    run = Run()  # no totals supplied at all
    assert run.text == "Estimating"
    assert run.eta is None


def test_provisional_estimate_is_marked_then_stops_being_marked():
    run = Run(units_total=100, bytes_total=200 * MB)
    assert run.text.startswith("~")
    transfer(run, 10, 2 * MB, 5 * MB)
    assert not run.text.startswith("~")


def test_zero_byte_phase_learns_per_item_cost():
    """A shortcut-only stretch must move the estimate off its prior."""
    run = Run(units_total=60, bytes_total=0)
    for _ in range(20):
        run.advance(2.0, units=1, steps=4)
    # 40 units left at ~2 s each; nothing byte-shaped to confuse it.
    assert 55 < run.eta < 110


def test_zero_byte_phase_still_prices_the_megabytes_ahead():
    """With no transfer sampled yet, the byte prior must still be applied."""
    run = Run(units_total=30, bytes_total=400 * MB)
    for _ in range(10):
        run.advance(1.0, units=1, steps=2)
    # 20 items of overhead plus 400 MB that has not started: minutes, not seconds.
    assert run.eta > 60


def test_setup_latency_is_not_extrapolated_across_the_whole_run():
    """Regression: the first real estimate of a download read 5:37:34.

    A phase opens with tens of seconds of Canvas metadata latency, a couple of
    files land, and conservation dutifully charges all of that dead time to
    whichever channel moved. Multiplied by the hundreds of files and hundreds of
    megabytes still queued, a legitimate fit of the opening window projected
    hours onto a run that finished in minutes.
    """
    files, size, rate = 141, 6 * MB, 3.3 * MB
    run = Run(units_total=files, bytes_total=files * size)
    run.idle(45.0)                            # metadata / discovery, nothing moves
    transfer(run, 9, size, rate)              # the first few files
    true_remaining = (files - 9) * (size / rate + 0.2)
    assert run.eta < 3 * true_remaining


def test_eta_stays_consistent_with_the_speed_on_screen():
    """The two cells sit side by side; they must not contradict each other."""
    files, size, rate = 100, 5 * MB, 4 * MB
    run = Run(units_total=files, bytes_total=files * size)
    run.idle(30.0)
    transfer(run, 20, size, rate)
    bytes_left = (files - 20) * size
    naive = bytes_left / run.est.bytes_per_sec   # what a user computes by eye
    assert run.eta < 3 * naive


# ── Work that arrives after the counters say "done" ─────────────────────────

def test_trailing_synthetic_items_do_not_read_as_finished():
    """Regression: 30-50 shortcut files downloaded behind a finished-looking screen.

    Canvas produces Pages / ExternalUrl shortcuts / secondary content as it
    goes, so each raises the numerator AND the denominator together. Every
    metric pinned at done - 100%, total-of-total MB, 00:00 - for the half minute
    it took to write them.
    """
    run = Run(units_total=40, bytes_total=40 * MB)
    transfer(run, 40, 1 * MB, 10 * MB)
    assert not run.est.is_open_ended
    assert run.text == "00:00"

    for _ in range(5):                        # shortcuts arriving one at a time
        run.units_total += 1
        run.units += 1
        run.advance(0.6)
        assert run.est.is_open_ended
        assert run.text == "Finishing…"


def test_trailing_items_do_not_make_the_eta_flicker():
    """Regression: "Finishing…" and "00:01" alternating three times a second.

    The counters do not advance in the same tick - the total grows when Canvas
    finds the next shortcut, the numerator catches up when it is written - so a
    remainder of exactly zero is only true on half the frames. Requiring one
    turned the fix for a finished-looking screen into a strobing one.
    """
    run = Run(units_total=60, bytes_total=60 * MB)
    transfer(run, 60, 1 * MB, 10 * MB)

    seen = set()
    for _ in range(12):
        run.units_total += 1       # discovered
        run.advance(0.3)
        seen.add(run.text)
        run.units += 1             # written
        run.advance(0.4)
        seen.add(run.text)

    assert seen == {"Finishing…"}


def test_open_ended_clears_once_work_stops_arriving():
    run = Run(units_total=10, bytes_total=10 * MB)
    transfer(run, 10, 1 * MB, 10 * MB)
    run.units_total += 1
    run.units += 1
    run.advance(0.5)
    assert run.est.is_open_ended
    run.idle(10.0)
    assert not run.est.is_open_ended
    assert run.text == "00:00"


def test_learning_the_total_is_not_work_arriving_late():
    """The 0 -> N transition at the start is initialisation, not new work."""
    run = Run(units_total=8, bytes_total=8 * MB)
    transfer(run, 8, 1 * MB, 40 * MB)          # finishes in under a second
    assert not run.est.is_open_ended


def test_midrun_discovery_is_not_open_ended():
    """A growing denominator while a queue remains is ordinary, not a lie."""
    run = Run(units_total=50, bytes_total=50 * MB)
    transfer(run, 20, 1 * MB, 10 * MB)
    run.units_total = 70
    run.advance(0.5)
    assert not run.est.is_open_ended


# ── Accuracy on steady work ─────────────────────────────────────────────────

def test_steady_transfer_is_accurate_within_15_percent():
    files, size, rate = 120, 4 * MB, 5 * MB
    run = Run(units_total=files, bytes_total=files * size)
    transfer(run, files // 4, size, rate)          # quarter of the way in
    true_remaining = (files - files // 4) * (size / rate + 0.2)
    assert run.eta == pytest.approx(true_remaining, rel=0.15)


def test_collinear_work_does_not_double_the_estimate():
    """Regression: every bin advancing both channels together is ambiguous.

    "2.3 s per file" and "0.38 s per MB" fit identical data. Without the
    wall-clock conservation constraint the fit landed wherever its regulariser
    pulled it and the ETA came out ~2x high with a clean residual.
    """
    files, size, rate = 200, 6 * MB, 3 * MB
    run = Run(units_total=files, bytes_total=files * size)
    transfer(run, 60, size, rate)
    true_remaining = 140 * (size / rate + 0.2)
    assert run.eta == pytest.approx(true_remaining, rel=0.15)


def test_stepwise_phase_is_not_biased_by_the_unfinished_unit():
    """Regression: a 9 s/unit phase used to fit anywhere from 9 s to 18 s.

    Elapsed time accrued while no unit completed, so the per-unit cost climbed
    linearly between completions. Sampled mid-unit - which is most of the time -
    it read ~50% high.
    """
    run = Run(stepwise_estimator(9.0), units_total=12)
    for _ in range(4):
        run.advance(9.0, units=1, steps=18)
    for _ in range(8):                      # sample all the way through a unit
        assert run.eta == pytest.approx(8 * 9.0, abs=25)
        run.advance(9.0 / 8, steps=2)


def test_count_only_phase_needs_no_byte_channel():
    run = Run(stepwise_estimator(9.0), units_total=12)
    for _ in range(6):
        run.advance(9.0, units=1, steps=18)
    assert run.eta == pytest.approx(54, rel=0.35)


# ── Robustness ──────────────────────────────────────────────────────────────

def test_rerun_gap_between_courses_is_not_counted_as_work_or_stall():
    """A 20 s Streamlit rerun must neither inflate the estimate nor invent speed."""
    files, size, rate = 100, 5 * MB, 6 * MB
    run = Run(units_total=files, bytes_total=files * size)
    transfer(run, 30, size, rate)
    before = run.eta
    run.jump(20.0)                          # post-processing / rerun boundary
    after = run.eta
    assert after == pytest.approx(before, abs=6.0)


def test_long_freeze_pushes_the_estimate_up_instead_of_counting_down():
    files, size, rate = 100, 5 * MB, 6 * MB
    run = Run(units_total=files, bytes_total=files * size)
    transfer(run, 30, size, rate)
    before = run.eta
    run.idle(150.0)                          # nothing moves, repaints keep firing
    assert run.eta > before


def test_estimate_never_reads_zero_while_work_remains():
    run = Run(units_total=50, bytes_total=100 * MB)
    transfer(run, 49, 2 * MB, 500 * MB)      # absurdly fast, ETA collapses
    assert run.text != "00:00"


def test_completed_work_reads_zero():
    run = Run(units_total=10, bytes_total=10 * MB)
    transfer(run, 10, 1 * MB, 50 * MB)
    assert run.eta == 0.0
    assert run.text == "00:00"


def test_growing_totals_are_absorbed():
    """Canvas discovers secondary attachments mid-run; the denominator moves."""
    run = Run(units_total=50, bytes_total=100 * MB)
    transfer(run, 25, 2 * MB, 5 * MB)
    before = run.eta
    run.units_total = 90
    run.bytes_total = 180 * MB
    run.advance(0.0)
    assert run.eta >= before


def test_unknown_byte_total_falls_back_to_the_unit_channel():
    """Panopto knows the recording count but not the byte size up front."""
    run = Run(units_total=10, bytes_total=0)
    for _ in range(4):
        run.advance(5.0, units=1, bytes=20 * MB, steps=10)
    assert run.eta is not None
    assert run.eta > 0


def test_backwards_byte_counter_does_not_invent_progress():
    """A failed attempt rolls its partial bytes back out of the MB tracker."""
    run = Run(units_total=20, bytes_total=100 * MB)
    run.advance(4.0, bytes=20 * MB, steps=8)
    run.bytes -= 20 * MB                      # the retry rollback
    run.advance(1.0)
    assert run.eta is not None and run.eta > 0


# ── Speed read-out ──────────────────────────────────────────────────────────

def test_speed_reflects_the_recent_window_not_the_whole_run():
    """The cumulative average read 0.7 MB/s on a run moving several times faster."""
    run = Run(units_total=100, bytes_total=400 * MB)
    for _ in range(30):                       # a minute of zero-byte shortcuts
        run.advance(2.0, units=1, steps=4)
    transfer(run, 12, 5 * MB, 6 * MB, overhead=0.05)
    assert run.est.mb_per_sec == pytest.approx(6.0, rel=0.35)


def test_speed_is_zero_before_anything_transfers():
    run = Run(units_total=10, bytes_total=10 * MB)
    assert run.est.mb_per_sec == 0.0


# ── Smoothing ───────────────────────────────────────────────────────────────

def test_smoothing_rate_does_not_depend_on_repaint_frequency():
    """Regression: a per-call blend factor made accuracy a function of chattiness.

    The same run, smoothed 8x more often, converged 8x faster - so a quiet
    phase lagged its true estimate by ~30% indefinitely.
    """
    def run_with(steps_per_file):
        run = Run(units_total=100, bytes_total=100 * 4 * MB)
        for _ in range(40):
            run.advance(0.2)
            run.advance(0.8, bytes=4 * MB, steps=steps_per_file)
            run.advance(0.0, units=1)
        return run.eta

    assert run_with(2) == pytest.approx(run_with(16), rel=0.10)


def test_display_counts_down_smoothly_rather_than_jumping():
    run = Run(units_total=100, bytes_total=100 * 4 * MB)
    transfer(run, 40, 4 * MB, 5 * MB)
    samples = []
    for _ in range(10):
        run.advance(0.5, steps=1)
        samples.append(run.eta)
    # Monotonically ticking down, no frame moving more than a couple of seconds.
    jumps = [abs(b - a) for a, b in zip(samples, samples[1:])]
    assert max(jumps) < 3.0


# ── Cross-run calibration ───────────────────────────────────────────────────

def test_learned_priors_are_only_exported_once_measured():
    fresh = transfer_estimator()
    assert fresh.export_priors() == {}


def test_learned_priors_seed_a_faster_first_estimate():
    files, size, rate = 100, 5 * MB, 3 * MB
    first = Run(units_total=files, bytes_total=files * size)
    transfer(first, files, size, rate)
    learned = first.est.export_priors()
    assert 'prior_byte_rate' in learned
    assert learned['prior_byte_rate'] == pytest.approx(rate, rel=0.4)

    seeded = Run(ProgressEstimator(**learned),
                 units_total=files, bytes_total=files * size)
    cold = Run(units_total=files, bytes_total=files * size)
    true_total = files * (size / rate + 0.2)
    assert abs(seeded.eta - true_total) < abs(cold.eta - true_total)


# ── Guards ──────────────────────────────────────────────────────────────────

def test_absurd_inputs_do_not_raise():
    est = transfer_estimator()
    est.update(units_done=-5, bytes_done=-5, units_total=-5, bytes_total=-5)
    est.update(units_done=float('inf'), bytes_done=0, units_total=1)
    assert est.eta_text() is not None


def test_clock_going_backwards_is_survived():
    run = Run(units_total=20, bytes_total=40 * MB)
    transfer(run, 5, 2 * MB, 4 * MB)
    run.t -= 30.0                              # NTP step
    run.advance(1.0, units=1)
    assert run.eta is not None and run.eta >= 0
